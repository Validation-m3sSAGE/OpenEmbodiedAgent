"""TriggerRegistry — discover and manage TriggerEnvironment classes.

Status: BASE IMPLEMENTATION — registration, instantiation, and basic
trigger management are implemented.

How a TriggerEnvironment becomes'available'
---------------------------------------------
A TriggerEnvironment is available when its class is registered with the
registry.  Registration can happen in two ways:

1. **Static registration** (recommended for built-in environments):
   Call ``TriggerRegistry.register(MyEnvironment)`` at import time.

2. **Dynamic discovery** (planned, not yet implemented):
   The registry will scan a configured ``triggers/`` directory for
   Python files that define a ``TriggerEnvironment`` subclass.

Online / offline semantics
--------------------------
A registered TriggerEnvironment class is 'offline' (available but not
running).  When a session is created via ``registry.instantiate()``,
the environment transitions to 'online' (running) for that session.

Simplified management
---------------------
Compared to the original Missions protocol:
- No WorkGroup (simplified away)
- No ContactBook (merged into registry)
- No group management (may add tags later if needed)
- Trigger states simplified to active/muted/inactive
- Permission model: fixed/disabled/hidden (agent-facing only)

Replaces: ``PhyAgentOS.missions.registry``
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from PhyAgentOS.triggers.base import TriggerEnvironment
from PhyAgentOS.triggers.trigger import BaseTrigger, TriggerContext, TriggerState


class EnvironmentSession:
    """A running instance of a TriggerEnvironment bound to a session.

    Wraps a ``TriggerEnvironment`` object, tracks lifecycle state,
    and manages the triggers registered within this session.
    """

    def __init__(self, environment: TriggerEnvironment, session_key: str) -> None:
        self.environment = environment
        self.session_key = session_key
        self._running = False
        # trigger_id -> (BaseTrigger, TriggerContext)
        self._triggers: dict[int, tuple[BaseTrigger, TriggerContext | None]] = {}
        # name -> trigger_id (name registry for rename support)
        self._name_map: dict[str, int] = {}

    @property
    def name(self) -> str:
        return self.environment.name

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """启动环境，移除系统级权限限制使触发器对智能体可见。"""
        if self._running:
            logger.warning("EnvironmentSession '{}' already running", self.name)
            return
        self.environment.start()
        self._running = True
        # 环境上线：移除系统级权限限制
        from PhyAgentOS.triggers.trigger import TriggerPermission
        for trigger, _ in self._triggers.values():
            trigger._system_permissions.discard(TriggerPermission.HIDDEN)
            trigger._system_permissions.discard(TriggerPermission.DISABLED)
            trigger._system_permissions.discard(TriggerPermission.FIXED)
        logger.info(
            "EnvironmentSession '{}' started for session '{}'",
            self.name, self.session_key,
        )

    def stop(self) -> None:
        """停止环境，设置系统级权限限制使触发器对智能体不可见。"""
        if not self._running:
            return
        # 环境离线：设置系统级全权限限制
        from PhyAgentOS.triggers.trigger import TriggerPermission
        for trigger, _ in self._triggers.values():
            if trigger.state != TriggerState.INACTIVE:
                trigger.state = TriggerState.INACTIVE
            trigger._system_permissions.add(TriggerPermission.HIDDEN)
            trigger._system_permissions.add(TriggerPermission.DISABLED)
            trigger._system_permissions.add(TriggerPermission.FIXED)
        self.environment.stop()
        self._running = False
        logger.info(
            "EnvironmentSession '{}' stopped for session '{}'",
            self.name, self.session_key,
        )

    # ------------------------------------------------------------------
    # Context injection (for ContextBuilder)
    # ------------------------------------------------------------------

    def get_context_block(self) -> str:
        """Return the Markdown context block for injection into the system prompt.

        Includes the environment's context block plus a summary of
        active triggers.
        """
        parts = [self.environment.get_context_block()]

                # 添加触发器摘要 — 仅列出对智能体可见的触发器。
        # 隐藏触发器（TriggerPermission.HIDDEN）对智能体完全不可见，
        # 确保开发者/用户可以维护私有监控而不被智能体发现或干扰。
        visible_triggers = [
            (t, ctx) for t, ctx in self._triggers.values()
            if t.is_agent_visible
        ]
        if visible_triggers:
            lines = ["\n### Active Triggers"]
            for trigger, _ in visible_triggers:
                state_icon = {
                    TriggerState.ACTIVE: "🟢",
                    TriggerState.MUTED: "🔇",
                    TriggerState.INACTIVE: "⭕",
                }.get(trigger.state, "❓")
                lines.append(
                    f"- {state_icon} **{trigger.name}** (id={trigger.trigger_id}): "
                    f"{trigger.description or 'No description'}"
                )
            parts.append("\n".join(lines))

        return "\n\n".join(parts)

    def get_current_observation(self) -> dict[str, Any]:
        return self.environment.get_current_observation()

    def on_agent_reply(self, reply: str) -> None:
        self.environment.on_agent_reply(reply)

    # ------------------------------------------------------------------
    # Trigger management (simplified, no groups)
    # ------------------------------------------------------------------

    def add_trigger(
        self,
        trigger: BaseTrigger,
        buffer: Any | None = None,
    ) -> int:
        """Register a trigger with this environment session.

        The environment validates the trigger's declared observation/action
        spaces against its own maximum spaces.  If validation fails, the
        trigger is rejected withPermissionError — this is the "create first,
        environment validates" model where the agent can freely request
        creation but the environment enforces safety constraints.

        Returns the trigger's numeric ID.

        Raises
        ------
        ValueError
            If the trigger name is already taken.
        PermissionError
            If the trigger's observation/action spaces are not valid
            subsets of the environment's spaces.
        """
        if trigger.name in self._name_map:
            raise ValueError(
                f"Trigger name '{trigger.name}' already exists in "
                f"environment '{self.name}'."
            )

        # Validate trigger access against environment spaces
        if not self.environment.validate_trigger_access(
            trigger.watched_observations,
            trigger.allowed_actions,
        ):
            raise PermissionError(
                f"Trigger '{trigger.name}' declares observation/action keys "
                f"outside the environment's spaces."
            )

        # Create context for this trigger
        ctx = TriggerContext(
            _environment=self.environment,
            _buffer=buffer,
            _watched_observations=trigger.watched_observations,
            _allowed_actions=trigger.allowed_actions,
            _trigger_state=trigger.state,
            _sender_id=trigger.name,
        )

        self._triggers[trigger.trigger_id] = (trigger, ctx)
        self._name_map[trigger.name] = trigger.trigger_id
        logger.info(
            "Trigger '{}' (id={}) added to environment '{}'",
            trigger.name, trigger.trigger_id, self.name,
        )
        return trigger.trigger_id

    def remove_trigger(self, name: str) -> None:
        """Remove a trigger by name."""
        tid = self._name_map.pop(name, None)
        if tid is not None:
            self._triggers.pop(tid, None)
            logger.info("Trigger '{}' removed from environment '{}'", name, self.name)

    def get_trigger(self, name: str) -> BaseTrigger | None:
        """Get a trigger by name."""
        tid = self._name_map.get(name)
        if tid is None:
            return None
        entry = self._triggers.get(tid)
        return entry[0] if entry else None

    def set_trigger_state(self, name: str, state: TriggerState) -> bool:
        """Change a trigger's state."""
        tid = self._name_map.get(name)
        if tid is None:
            return False
        trigger, ctx = self._triggers[tid]
        old_state = trigger.state
        trigger.state = state
        if ctx:
            ctx._trigger_state = state
        logger.info(
            "Trigger '{}' state: {} -> {}",
            name, old_state.value, state.value,
        )
        return True

    def rename_trigger(self, old_name: str, new_name: str) -> bool:
        """Rename a trigger."""
        if old_name not in self._name_map:
            return False
        if new_name in self._name_map:
            raise ValueError(f"Name '{new_name}' already in use.")
        tid = self._name_map.pop(old_name)
        self._name_map[new_name] = tid
        trigger, ctx = self._triggers[tid]
        trigger.name = new_name
        if ctx:
            ctx._sender_id = new_name
        return True

    def list_triggers(
        self,
        *,
        agent_visible_only: bool = False,
        state_filter: TriggerState | None = None,
    ) -> list[dict[str, Any]]:
        """List all triggers with optional filtering."""
        result = []
        for trigger, _ in self._triggers.values():
            if agent_visible_only and not trigger.is_agent_visible:
                continue
            if state_filter is not None and trigger.state != state_filter:
                continue
            result.append({
                "name": trigger.name,
                "trigger_id": trigger.trigger_id,
                "state": trigger.state.value,
                "description": trigger.description,
                "watched_observations": trigger.watched_observations,
                "allowed_actions": trigger.allowed_actions,
                "is_agent_visible": trigger.is_agent_visible,
                "is_agent_modifiable": trigger.is_agent_modifiable,
                "is_agent_startable": trigger.is_agent_startable,
            })
        return result


class TriggerRegistry:
    """Central registry for TriggerEnvironment classes and active sessions.

    Usage
    -----
    registry = TriggerRegistry()
    registry.register(MyEnvironment)

    # Later, when a session starts:
    session = registry.instantiate("my_env", session_key="telegram:12345")
    session.start()

    # Inject context into agent prompt:
    block = session.get_context_block()

    # Stop when done:
    session.stop()
    registry.remove_instance("telegram:12345")
    """

    def __init__(self) -> None:
        # name -> class
        self._classes: dict[str, type[TriggerEnvironment]] = {}
        # session_key -> EnvironmentSession
        self._instances: dict[str, EnvironmentSession] = {}

    # ------------------------------------------------------------------
    # Class registration
    # ------------------------------------------------------------------

    def register(self, cls: type[TriggerEnvironment]) -> None:
        """Register a TriggerEnvironment class."""
        if not cls.name or cls.name == "unnamed_environment":
            raise ValueError(
                f"TriggerEnvironment class {cls.__name__} must define "
                f"a non-empty 'name' attribute."
            )
        if cls.name in self._classes:
            logger.warning(
                "TriggerRegistry: overwriting existing environment '{}'",
                cls.name,
            )
        self._classes[cls.name] = cls
        logger.info("TriggerRegistry: registered environment '{}'", cls.name)

    def unregister(self, name: str) -> None:
        """Unregister a TriggerEnvironment class by name."""
        self._classes.pop(name, None)

    def list_available(self) -> list[str]:
        """Return names of all registered TriggerEnvironment classes."""
        return list(self._classes.keys())

    def is_registered(self, name: str) -> bool:
        return name in self._classes

    # ------------------------------------------------------------------
    # Instance management
    # ------------------------------------------------------------------

    def instantiate(
        self,
        env_name: str,
        session_key: str,
        **kwargs: Any,
    ) -> EnvironmentSession:
        """Create (but do not start) an EnvironmentSession.

        Raises KeyError if env_name is not registered.
        Raises RuntimeError if session_key already has an active instance.
        """
        if env_name not in self._classes:
            raise KeyError(f"Environment '{env_name}' is not registered.")
        if session_key in self._instances:
            existing = self._instances[session_key]
            raise RuntimeError(
                f"Session '{session_key}' already has an active environment "
                f"'{existing.name}'.Stop it first."
            )
        cls = self._classes[env_name]
        env_obj = cls(**kwargs)
        instance = EnvironmentSession(environment=env_obj, session_key=session_key)
        self._instances[session_key] = instance
        return instance

    def get_instance(self, session_key: str) -> EnvironmentSession | None:
        """Return the active EnvironmentSession for *session_key*, or None."""
        return self._instances.get(session_key)

    def remove_instance(self, session_key: str) -> None:
        """Stop (if running) and remove the instance for *session_key*."""
        instance = self._instances.pop(session_key, None)
        if instance and instance.is_running:
            instance.stop()

    def list_active_sessions(self) -> list[str]:
        """Return session keys that have an active EnvironmentSession."""
        return list(self._instances.keys())
