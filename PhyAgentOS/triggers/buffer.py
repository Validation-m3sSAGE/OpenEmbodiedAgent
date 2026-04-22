"""TriggerBuffer — session-scoped message buffer for Triggers.

Responsibilities
----------------
1. Accept incoming messages from triggers (and optionally users) before
   the agent is ready to process them.
2. Enforce capacity limits with soft / hard watermarks and a clear
   priority-based drop policy:
       - ``high`` priority (user / system): NEVER dropped.
       - ``normal`` / ``low`` priority (trigger): dropped when the buffer
         is at or above the soft watermark.
3. Produce ``dropped`` message entries that are written to the session
   file for user-side transparency but are invisible to the LLM.
4. Provide a ``flush()`` method that atomically drains the buffer and
   returns the ordered list of messages to be appended to the session.
5. Expose an asyncio ``Event`` (``wakeup``) that is set whenever a
   non-muted, non-dropped message arrives — allowing the AgentLoop to
   treat trigger messages exactly like user messages.

Design constraints
------------------
- No threading: all methods are called from the asyncio event loop.
  Internal state is protected by a single ``asyncio.Lock``.
- The buffer is per-session (one ``TriggerBuffer`` per session key).
- Capacity and watermarks are configured via ``TriggersConfig``
  (see ``config/schema.py``).

Watermark semantics
-------------------
``soft_watermark``(default 0.80x capacity)
    When ``len(buffer) >= soft_watermark``, new *trigger* messages are
    immediately marked as dropped and written as dropped entries.
    High-priority messages are still accepted normally.

``hard_watermark``  (default 1.00 x capacity, i.e. full)
    When ``len(buffer) >= hard_watermark`` (buffer is full), ALL new
    messages — including high-priority ones — are rejected.

Note:'muted' is a *trigger state* property, not a buffer property.
A muted trigger's messages are written directly to the session as
``muted=True`` entries without going through the buffer.

Replaces: ``PhyAgentOS.missions.buffer``
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class BufferFullError(Exception):
    """Raised when a high-priority message cannot be accepted (buffer full)."""


# ---------------------------------------------------------------------------
# Buffered message entry
# ---------------------------------------------------------------------------

@dataclass
class BufferedMessage:
    """A message waiting in the buffer before being flushed to the session."""

    role: str                # "trigger" | "user" | "system"
    content: str
    priority: str = "normal"# "high" | "normal" | "low"
    muted: bool = False
    dropped: bool = False
    relates_to: str | None = None# optional action_id reference
    sender_id: str | None = None      # trigger name or user id
    timestamp: datetime = field(default_factory=datetime.now)
    extra: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# TriggerBuffer
# ---------------------------------------------------------------------------

class TriggerBuffer:
    """Per-session message buffer for Triggers.

    Parameters
    ----------
    capacity:
        Maximum number of messages the buffer can hold.
    soft_watermark:
        Fraction of capacity at which trigger messages start being dropped.
        Must be in (0, 1].  Default 0.80.
    wakeup_event:
        An external ``asyncio.Event`` that is set whenever a message that
        should wake the agent (non-muted, non-dropped) is enqueued.
        Pass the AgentLoop's per-session wakeup event here.
    """

    def __init__(
        self,
        capacity: int = 256,
        soft_watermark: float = 0.80,
        wakeup_event: asyncio.Event | None = None,
    ) -> None:
        if not (0 < soft_watermark <= 1.0):
            raise ValueError("soft_watermark must be in (0, 1]")

        self._capacity = capacity
        self._soft_limit = max(1, int(capacity * soft_watermark))
        self._lock = asyncio.Lock()
        self._queue: list[BufferedMessage] = []
        self.wakeup: asyncio.Event = wakeup_event or asyncio.Event()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def size(self) -> int:
        """Current number of messages in the buffer (advisory)."""
        return len(self._queue)

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def soft_limit(self) -> int:
        return self._soft_limit

    def is_soft_full(self) -> bool:
        return len(self._queue) >= self._soft_limit

    def is_hard_full(self) -> bool:
        return len(self._queue) >= self._capacity

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    async def enqueue(self, msg: BufferedMessage) -> bool:
        """Enqueue a message, applying watermark and drop policy.

        Returns True if the message was accepted (possibly as a dropped
        entry), False if silently ignored.

        Raises BufferFullError if the buffer is completely full and the
        message has priority == "high".
        """
        async with self._lock:
            is_high = msg.priority == "high"
            current = len(self._queue)

                        # 硬水位线：缓冲区已满。
            # 此时即使高优先级消息也会被拒绝以保护系统稳定性。
            # 调用方收到 BufferFullError。
            if current >= self._capacity:
                if is_high:
                    raise BufferFullError(
                        f"Trigger buffer full ({current}/{self._capacity}); "
                        "cannot accept high-priority message."
                    )
                logger.debug(
                    "TriggerBuffer: hard-full, silently ignoring trigger message"
                )
                return False

            # Soft watermark: drop trigger messages.
            if not is_high and current >= self._soft_limit:
                msg.dropped = True
                logger.debug(
                    "TriggerBuffer: soft-full ({}/{}), marking message as dropped",
                    current, self._soft_limit,
                )

            self._queue.append(msg)

            # Wake the agent only for visible (non-muted, non-dropped) messages.
            if not msg.muted and not msg.dropped:
                self.wakeup.set()

            return True

    # ------------------------------------------------------------------
    # Flush
    # ------------------------------------------------------------------

    async def flush(self) -> list[BufferedMessage]:
        """Atomically drain and return all buffered messages in order."""
        async with self._lock:
            messages = list(self._queue)
            self._queue.clear()
            self.wakeup.clear()
            return messages

    # ------------------------------------------------------------------
    # Peek
    # ------------------------------------------------------------------

    def peek_size(self) -> int:
        """Return current buffer size without acquiring the lock (advisory)."""
        return len(self._queue)


# ---------------------------------------------------------------------------
# TriggerBufferManager — one buffer per session
# ---------------------------------------------------------------------------

class TriggerBufferManager:
    """Manages one ``TriggerBuffer`` per session key.

    Instantiated once by the AgentLoop and shared across all sessions.
    """

    def __init__(self, capacity: int = 256, soft_watermark: float = 0.80) -> None:
        self._capacity = capacity
        self._soft_watermark = soft_watermark
        self._buffers: dict[str, TriggerBuffer] = {}

    def get_or_create(
        self,
        session_key: str,
        wakeup_event: asyncio.Event | None = None,
    ) -> TriggerBuffer:
        """Return the buffer for *session_key*, creating if necessary."""
        if session_key not in self._buffers:
            self._buffers[session_key] = TriggerBuffer(
                capacity=self._capacity,
                soft_watermark=self._soft_watermark,
                wakeup_event=wakeup_event,
            )
        return self._buffers[session_key]

    def get(self, session_key: str) -> TriggerBuffer | None:
        """Return the buffer for *session_key* or None."""
        return self._buffers.get(session_key)

    def remove(self, session_key: str) -> None:
        """Remove and discard the buffer for *session_key*."""
        self._buffers.pop(session_key, None)

    def all_keys(self) -> list[str]:
        return list(self._buffers.keys())
