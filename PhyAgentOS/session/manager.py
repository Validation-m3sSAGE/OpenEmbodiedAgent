"""Session management for conversation history."""

import fcntl
import json
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from PhyAgentOS.config.paths import get_legacy_sessions_dir
from PhyAgentOS.utils.helpers import ensure_dir, safe_filename


# ---------------------------------------------------------------------------
# Message-level helpers
# ---------------------------------------------------------------------------

def _make_message_id() -> str:
    """Generate a short unique message ID."""
    return uuid.uuid4().hex[:16]


def _is_agent_visible(msg: dict[str, Any]) -> bool:
    """Return True if this message should be included in the LLM context.

    Messages with ``dropped=True`` are written to the session file for
    user-side transparency but must never be forwarded to the LLM.
    Messages with ``muted=True`` are also excluded from LLM context
    (they are informational-only for the user / front-end).

    This filter is used by both Trigger messages and muted Tool results,
    providing a unified mechanism for session-logged-but-agent-invisible
    entries across all PhyAgentOS subsystems.
    """
    return not msg.get("dropped", False) and not msg.get("muted", False)


@dataclass
class Session:
    """
    A conversation session.

    Stores messages in JSONL format for easy reading and persistence.

    Important: Messages are append-only for LLM cache efficiency.
    The consolidation process writes summaries to MEMORY.md/HISTORY.md
    but does NOT modify the messages list or get_history() output.

    Triggers extension (minimal, backward-compatible):
    - Each message may carry extra optional fields:
        ``message_id``(str)  — unique ID, auto-assigned on add_message()
        ``priority``    (str)  — "high" | "normal" | "low"  (default "normal")
        ``muted``       (bool) — trigger muted message; visible to user, not to LLM
        ``dropped``     (bool) — buffer-overflow discard; visible to user, not to LLM
        ``relates_to``  (str)  — optional action_id reference
        ``sender_id``   (str)  — optional sender identifier
    """

    key: str  # channel:chat_id
    messages: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_consolidated: int = 0  # Number of messages already consolidated to files

    def add_message(
        self,
        role: str,
        content: str,
        *,
        priority: str = "normal",
        muted: bool = False,
        dropped: bool = False,
        relates_to: str | None = None,
        sender_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Add a message to the session and return the constructed entry."""
        msg: dict[str, Any] = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "message_id": _make_message_id(),
            **kwargs,
        }
        # Only write non-default Triggers fields to keep legacy sessions clean.
        if priority != "normal":
            msg["priority"] = priority
        if muted:
            msg["muted"] = True
        if dropped:
            msg["dropped"] = True
        if relates_to is not None:
            msg["relates_to"] = relates_to
        if sender_id is not None:
            msg["sender_id"] = sender_id

        self.messages.append(msg)
        self.updated_at = datetime.now()
        return msg

    def get_history(self, max_messages: int = 500) -> list[dict[str, Any]]:
        """Return unconsolidated, agent-visible messages for LLM input.

        Dropped and muted messages are excluded from the LLM context.
        The slice is aligned to a user turn to avoid orphaned tool_result blocks.
        """
        unconsolidated = self.messages[self.last_consolidated:]
        # Filter out messages that must not reach the LLM.
        visible = [m for m in unconsolidated if _is_agent_visible(m)]
        sliced = visible[-max_messages:] if max_messages else visible

        # Drop leading non-user messages to avoid orphaned tool_result blocks
        for i, m in enumerate(sliced):
            if m.get("role") == "user":
                sliced = sliced[i:]
                break

        out: list[dict[str, Any]] = []
        for m in sliced:
            entry: dict[str, Any] = {"role": m["role"], "content": m.get("content", "")}
            for k in ("tool_calls", "tool_call_id", "name"):
                if k in m:
                    entry[k] = m[k]
            out.append(entry)
        return out

    def clear(self) -> None:
        """Clear all messages and reset session to initial state."""
        self.messages = []
        self.last_consolidated = 0
        self.updated_at = datetime.now()


class SessionManager:
    """
    Manages conversation sessions.

    Sessions are stored as JSONL files in the sessions directory.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.sessions_dir = ensure_dir(self.workspace / "sessions")
        self.legacy_sessions_dir = get_legacy_sessions_dir()
        self._cache: dict[str, Session] = {}

    def _get_session_path(self, key: str) -> Path:
        """Get the file path for a session."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.sessions_dir / f"{safe_key}.jsonl"

    def _get_legacy_session_path(self, key: str) -> Path:
        """Legacy global session path (~/.PhyAgentOS/sessions/)."""
        safe_key = safe_filename(key.replace(":", "_"))
        return self.legacy_sessions_dir / f"{safe_key}.jsonl"

    def get_or_create(self, key: str) -> Session:
        """
        Get an existing session or create a new one.

        Args:
            key: Session key (usually channel:chat_id).

        Returns:
            The session.
        """
        if key in self._cache:
            return self._cache[key]

        session = self._load(key)
        if session is None:
            session = Session(key=key)

        self._cache[key] = session
        return session

    def _load(self, key: str) -> Session | None:
        """Load a session from disk."""
        path = self._get_session_path(key)
        if not path.exists():
            legacy_path = self._get_legacy_session_path(key)
            if legacy_path.exists():
                try:
                    shutil.move(str(legacy_path), str(path))
                    logger.info("Migrated session {} from legacy path", key)
                except Exception:
                    logger.exception("Failed to migrate session {}", key)

        if not path.exists():
            return None

        try:
            messages = []
            metadata = {}
            created_at = None
            last_consolidated = 0

            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    data = json.loads(line)

                    if data.get("_type") == "metadata":
                        metadata = data.get("metadata", {})
                        created_at = datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None
                        last_consolidated = data.get("last_consolidated", 0)
                    else:
                        messages.append(data)

            return Session(
                key=key,
                messages=messages,
                created_at=created_at or datetime.now(),
                metadata=metadata,
                last_consolidated=last_consolidated
            )
        except Exception as e:
            logger.warning("Failed to load session {}: {}", key, e)
            return None

    def append_message(self, session: Session, msg: dict[str, Any]) -> None:
        """Append a single message line to the session file.

        This is the preferred hot-path write for new messages.  It avoids
        rewriting the entire file and uses an advisory file lock to prevent
        concurrent corruption on POSIX systems.

        If the session file does not yet exist, a full ``save()`` is
        performed first to write the metadata header.
        """
        path = self._get_session_path(session.key)
        if not path.exists():
            self.save(session)
            return

        line = json.dumps(msg, ensure_ascii=False) + "\n"
        try:
            with open(path, "a", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    f.write(line)
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except Exception as e:
            logger.warning("append_message failed for session {}: {}", session.key, e)

    def save(self, session: Session) -> None:
        """Rewrite the full session file (metadata header + all messages)."""
        path = self._get_session_path(session.key)

        try:
            with open(path, "w", encoding="utf-8") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                try:
                    metadata_line = {
                        "_type": "metadata",
                        "key": session.key,
                        "created_at": session.created_at.isoformat(),
                        "updated_at": session.updated_at.isoformat(),
                        "metadata": session.metadata,
                        "last_consolidated": session.last_consolidated,
                    }
                    f.write(json.dumps(metadata_line, ensure_ascii=False) + "\n")
                    for msg in session.messages:
                        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
                finally:
                    fcntl.flock(f, fcntl.LOCK_UN)
        except Exception as e:
            logger.error("save failed for session {}: {}", session.key, e)

        self._cache[session.key] = session

    def invalidate(self, key: str) -> None:
        """Remove a session from the in-memory cache."""
        self._cache.pop(key, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all sessions.

        Returns:
            List of session info dicts.
        """
        sessions = []

        for path in self.sessions_dir.glob("*.jsonl"):
            try:
                # Read just the metadata line
                with open(path, encoding="utf-8") as f:
                    first_line = f.readline().strip()
                    if first_line:
                        data = json.loads(first_line)
                        if data.get("_type") == "metadata":
                            key = data.get("key") or path.stem.replace("_", ":", 1)
                            sessions.append({
                                "key": key,
                                "created_at": data.get("created_at"),
                                "updated_at": data.get("updated_at"),
                                "path": str(path)
                            })
            except Exception:
                continue

        return sorted(sessions, key=lambda x: x.get("updated_at", ""), reverse=True)
