"""Trigger base class and runtime context.

A Trigger is the atomic monitoring unit in the Triggers system.  It
watches specific observation points in a TriggerEnvironment and fires
specific actions when conditions are met.

Design choices
--------------
- **Class-based** (not function-based): provides state encapsulation,
  lifecycle hooks, declarative safety constraints, and configuration
  via attributes.
- **Three states** (simplified from the original 4-state + group model):
  active → monitoring + messages visible;
  muted  → monitoring + messages NOT visible to agent (visible to user);
  inactive → not monitoring.
- **Safety**: each Trigger declares ``watched_observations`` (which
  observation keys it may read) and ``allowed_actions`` (which action
  types it may fire).  The environment validates these at registration.

For simple cases, use the ``FunctionTrigger`` adapter to wrap a plain
function as a Trigger class.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, Coroutine

if TYPE_CHECKING:
    from PhyAgentOS.triggers.base import TriggerEnvironment
    from PhyAgentOS.triggers.buffer import TriggerBuffer


# ---------------------------------------------------------------------------
# Trigger state
# ---------------------------------------------------------------------------

class TriggerState(str, Enum):
    """Trigger lifecycle state.

    - ``ACTIVE``:monitoring observations, producing visible messages.
    - ``MUTED``:    monitoring observations, messages go to session file
                    but do NOT wake the agent (user-visible only).
    - ``INACTIVE``: not monitoring, not producing messages.
    """
    ACTIVE = "active"
    MUTED = "muted"
    INACTIVE = "inactive"


# ---------------------------------------------------------------------------
# Trigger permission flags (set by developer / user, not by agent)
# ---------------------------------------------------------------------------

class TriggerPermission(str, Enum):
    """Permission flags restricting agent access to a trigger.

    - ``FIXED``:    agent cannot modify or delete this trigger.
    - ``DISABLED``: agent cannot start/invoke this trigger.
    - ``HIDDEN``:   agent cannot discover or list this trigger.
    """
    FIXED = "fixed"
    DISABLED = "disabled"
    HIDDEN = "hidden"


# ---------------------------------------------------------------------------
# Trigger context (passed to on_tick / on_observation_change)
# ---------------------------------------------------------------------------

@dataclass
class TriggerContext:
    """Runtime context provided to a Trigger during execution.

    This is the only interface a Trigger uses to interact with the
    environment and the agent messaging layer.  All access is
    constrained to the trigger's declared observation/action subsets.
    """

    #: Reference to the parent environment (for observation/action).
    _environment: TriggerEnvironment

    #: Reference to the session buffer (for message emission).
    _buffer: TriggerBuffer | None = None

    #: The trigger's declared observation keys (filter).
    _watched_observations: list[str] = field(default_factory=list)

    #: The trigger's declared action types (filter).
    _allowed_actions: list[str] = field(default_factory=list)

    #: Current trigger state (for muted logic).
    _trigger_state: TriggerState = TriggerState.ACTIVE

    #: Sender ID for messages emitted by this trigger.
    _sender_id: str = ""

    # -- 观测访问 ----------------------------------------------------------

    def get_observation_space(self) -> dict[str, Any]:
        """返回完整的观测空间定义。"""
        return self._environment.get_observation_space()

    def get_action_space(self) -> dict[str, Any]:
        """返回完整的动作空间定义。"""
        return self._environment.get_action_space()

    def get_global_observation(self) -> dict[str, Any]:
        """返回静态的任务级信息。"""
        return self._environment.get_global_observation()

    def get_current_observation(self) -> dict[str, Any]:
        """返回当前观测，按watched_observations 过滤。

        仅包含本触发器在 ``watched_observations`` 中声明的观测键。
        如果列表为空，则返回完整观测（兼容旧 Worker API）。

        此过滤是安全模型的运行时执行：即使触发器以某种方式获得了
        完整的环境引用，上下文层也确保它只能看到其声明的子集。
        """
        full_obs = self._environment.get_current_observation()
        if not self._watched_observations:
            return full_obs
        # Filter payload to watched keys only
        payload = full_obs.get("payload", {})
        filtered_payload = {
            k: v for k, v in payload.items()
            if k in self._watched_observations
        }
        return {
            **full_obs,
            "payload": filtered_payload,
        }

    # -- Message emission --------------------------------------------------

    async def emit_message(
        self,
        content: str,
        priority: str = "normal",
        muted: bool | None = None,
        relates_to: str | None = None,
    ) -> bool:
        """Emit a message to the agent session.

        Parameters
        ----------
        content:
            The message text.
        priority:
            "high" | "normal" | "low".  High-priority messages are
            never dropped by the buffer.
        muted:
            If True, the message is written to the session file but
            does not wake the agent.  If None (default), follows the
            trigger's current state (MUTED state → muted=True).
        relates_to:
            Optional action_id reference.

        Returns
        -------
        bool
            True if the message was accepted by the buffer.
        """
        if self._buffer is None:
            return False

        from PhyAgentOS.triggers.buffer import BufferedMessage

        # Auto-mute if not explicitly set and trigger is in MUTED state
        if muted is None:
            muted = self._trigger_state == TriggerState.MUTED

        msg = BufferedMessage(
            role="trigger",
            content=content,
            priority=priority,
            muted=muted,
            relates_to=relates_to,
            sender_id=self._sender_id,
        )
        return await self._buffer.enqueue(msg)

    # -- Action execution --------------------------------------------------

    def enqueue_action(
        self,
        action_type: str,
        params: dict[str, Any] | None = None,
        priority: str = "normal",
        timeout: int | None = None,
        retries: int = 0,
    ) -> str:
        """Enqueue an action for execution on the environment.

        Returns the action_id (UUID string) for tracking.

        Raises
        ------
        PermissionError
            If the action_type is not in this trigger's allowed_actions.
        """
        if self._allowed_actions and action_type not in self._allowed_actions:
            raise PermissionError(
                f"Trigger '{self._sender_id}' is not allowed to fire "
                f"action '{action_type}'.  Allowed: {self._allowed_actions}"
            )
        action_id = uuid.uuid4().hex[:16]
        # Actions are executed directly on the environment side (not via
        # message passing) for minimal latency.  Remote environments use
        # gRPC to proxy the call.  There is NO trigger-to-trigger chaining;
        # if cascading effects are needed, the agent orchestrates them.
        self._environment.execute_action(action_type, params or {})
        return action_id


# ---------------------------------------------------------------------------
# BaseTrigger
# ---------------------------------------------------------------------------

class BaseTrigger(ABC):
    """Abstract base class for individual triggers.

    Subclass this and implement ``on_tick()`` to create a trigger that
    monitors observations and fires actions.

    Attributes
    ----------
    name:
        Human-readable trigger name (must be unique within an environment).
    description:
        Short description for the agent's context.
    watched_observations:
        List of observation keys this trigger is allowed to read.
        Empty list = access to all observations (backward-compatible).
    allowed_actions:
        List of action types this trigger is allowed to fire.
        Empty list = access to all actions (backward-compatible).
    """

    name: str = "unnamed_trigger"
    description: str = ""

    #: Observation keys this trigger may read (empty = all).
    watched_observations: list[str] = []

    #: Action types this trigger may fire (empty = all).
    allowed_actions: list[str] = []

    def __init__(self, **kwargs: Any) -> None:
        # Allow overriding class attributes via constructor kwargs
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
        # Immutable numeric ID, assigned at creation
        self._trigger_id: int = hash(uuid.uuid4()) & 0xFFFFFFFF
        self._state: TriggerState = TriggerState.INACTIVE
        #双级权限系统：系统权限和用户权限。
        # 只有当系统和用户都没有设置对应限制时，智能体才有权限。
        # 环境离线时，系统自动设置 HIDDEN+DISABLED+FIXED；上线时移除。
        self._system_permissions: set[TriggerPermission] = set()
        self._user_permissions: set[TriggerPermission] = set()

    @property
    def trigger_id(self) -> int:
        """Immutable numeric ID, unique for the lifetime of this trigger."""
        return self._trigger_id

    @property
    def state(self) -> TriggerState:
        return self._state

    @state.setter
    def state(self, value: TriggerState) -> None:
        self._state = value

    @property
    def system_permissions(self) -> set[TriggerPermission]:
        """系统级权限（由环境/框架控制）。"""
        return self._system_permissions

    @property
    def user_permissions(self) -> set[TriggerPermission]:
        """用户级权限（由用户/开发者控制）。"""
        return self._user_permissions

    @property
    def effective_permissions(self) -> set[TriggerPermission]:
        """生效权限 = 系统权限 ∪ 用户权限。任一方设限即生效。"""
        return self._system_permissions | self._user_permissions

    @property
    def is_agent_visible(self) -> bool:
        """智能体是否可见（系统和用户都未设 HIDDEN）。"""
        return TriggerPermission.HIDDEN not in self.effective_permissions

    @property
    def is_agent_modifiable(self) -> bool:
        """智能体是否可修改（系统和用户都未设 FIXED）。"""
        return TriggerPermission.FIXED not in self.effective_permissions

    @property
    def is_agent_startable(self) -> bool:
        """智能体是否可启动（系统和用户都未设 DISABLED）。"""
        return TriggerPermission.DISABLED not in self.effective_permissions

    # ------------------------------------------------------------------
    # Abstract interface — must implement
    # ------------------------------------------------------------------

    @abstractmethod
    async def on_tick(self, ctx: TriggerContext) -> None:
        """Called each clock tick (or on observation change).

        This is the main entry point of the trigger.  Use ``ctx`` to:
        - Read observations: ``ctx.get_current_observation()``
        - Emit messages: ``await ctx.emit_message(...)``
        - Fire actions: ``ctx.enqueue_action(...)``

        The trigger should check conditions and act accordingly.

        Note: This method is called concurrently for all active triggers
        in the same environment session, sharing the same observation
        snapshot to avoid redundant data fetching.
        """

    # ------------------------------------------------------------------
    # Optional lifecycle hooks
    # ------------------------------------------------------------------

    async def on_start(self, ctx: TriggerContext) -> None:
        """Called when the trigger is activated (state → ACTIVE/MUTED)."""

    async def on_stop(self) -> None:
        """Called when the trigger is deactivated (state → INACTIVE)."""

    async def on_observation_change(
        self, key: str, old_value: Any, new_value: Any, ctx: TriggerContext,
    ) -> None:
        """Called when a specific observation key changes value.

        Only invoked for keys listed in ``watched_observations``.
        Default: no-op.  Override for event-driven triggers that react
        to specific observation changes rather than polling on each tick.
        """


# ---------------------------------------------------------------------------
# FunctionTrigger — convenience adapter
# ---------------------------------------------------------------------------

class FunctionTrigger(BaseTrigger):
    """Adapt a plain function as a Trigger class.

    This adapter is designed for two scenarios:
    1. Agent-generated triggers: the LLM writes a simple async function
       and wraps it with FunctionTrigger for quick deployment.
    2. Quick prototyping: developers can test trigger logic without
       creating a full subclass.

    Usage::

        async def my_monitor(ctx: TriggerContext) -> None:
            obs = ctx.get_current_observation()
            if obs["payload"].get("temperature", 0) > 80:
                await ctx.emit_message("Temperature alert!")
                ctx.enqueue_action("cool_down", {"target_temp": 70})

        trigger = FunctionTrigger(
            name="temp_monitor",
            description="Monitors temperature sensor",
            fn=my_monitor,
            watched_observations=["temperature"],
            allowed_actions=["cool_down"],
        )
    """

    def __init__(
        self,
        fn: Callable[[TriggerContext], Coroutine[Any, Any, None]],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._fn = fn

    async def on_tick(self, ctx: TriggerContext) -> None:
        await self._fn(ctx)
