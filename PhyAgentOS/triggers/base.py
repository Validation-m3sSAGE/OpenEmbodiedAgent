"""TriggerEnvironment base class — interface contract for environment developers.

Status: BASE CLASS — defines the interface that a TriggerEnvironment
implementation must satisfy.  No existing functionality is affected
until an environment is registered and a session is started.

Developer guide
---------------
To create a TriggerEnvironment, subclass ``TriggerEnvironment`` and
implement the abstract methods.  See the docstrings for each method.

The environment lifecycle is:

    1. Developer registers the class via ``TriggerRegistry.register()``.
    2. User (or agent, with user approval) calls ``registry.instantiate()``.
    3. The returned ``EnvironmentSession`` is started via ``session.start()``.
    4. The environment clock ticks; triggers are invoked each tick.
    5. Triggers emit messages (injected into the session buffer) and
       enqueue actions (forwarded to the environment).
    6. The session is stopped via ``session.stop()``.

Context injection
-----------------
When anEnvironmentSession is active, theContextBuilder will call
``session.get_context_block()`` and append the result to the system
prompt so the agent is aware of available observations and actions.

Safety model
------------
The TriggerEnvironment declares the *maximum* observation and action
spaces.  Each individual Trigger can only access subsets of these
spaces, as declared in its ``watched_observations`` and
``allowed_actions`` attributes.  The environment enforces these
constraints at runtime.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TriggerEnvironment(ABC):
    """Abstract base class for trigger environments.

    Subclass this and implement all abstract methods to register an
    environment that can host triggers.
    """

    # ------------------------------------------------------------------
    # Identity (class-level, set by subclass or registry)
    # ------------------------------------------------------------------

    #: 在上下文块和 CLI 中显示的可读名称。
    name: str = "unnamed_environment"

    #: 在智能体上下文块中显示的简短描述。
    description: str = ""

    #: 是否为远程（gRPC）环境。
    is_remote: bool = False

    #: 时钟周期间隔（秒）。None = 纯事件驱动（无周期性轮询）。
    #: 设为float/int 则按周期轮询观测。
    #: 事件驱动环境中的触发器仅在观测变化时被调用。
    tick_interval: float | None = 1.0

    # ------------------------------------------------------------------
    # Abstract interface — spaces and observations
    # ------------------------------------------------------------------

    @abstractmethod
    def get_observation_space(self) -> dict[str, Any]:
        """Return the maximum observation space definition.

        This describes ALL possible observation keys and their types
        that triggers in this environment can monitor.  Must be
        JSON-serialisable.

        Example return value::

            {
                "temperature": {"type": "float", "unit": "celsius"},
                "gripper_state": {"type": "enum", "values": ["open", "closed"]},
                "camera_frame": {"type": "image_ref"},
            }
        """

    @abstractmethod
    def get_action_space(self) -> dict[str, Any]:
        """Return the maximum action space definition.

        This describes ALL possible action types that triggers in this
        environment can fire.  Must be JSON-serialisable.

        Example return value::

            {
                "move_gripper": {"params": {"position": "float[3]"}},
                "set_temperature": {"params": {"target": "float"}},
                "capture_image": {"params": {}},
            }
        """

    @abstractmethod
    def get_global_observation(self) -> dict[str, Any]:
        """Return static task-level information.

        This includes information that does not change during the
        session (e.g. robot model, workspace bounds, calibration data).
        Called once when the session starts.  Must be JSON-serialisable.
        """

    @abstractmethod
    def get_current_observation(self) -> dict[str, Any]:
        """Return the current real-time observation.

        Called each tick (if tick-driven) or when an observation changes
        (if event-driven).  Must include at minimum::

            {
                "timestamp": "2025-04-22T12:00:00",  # ISO-8601
                "stale": false,
                "source": "sensor_name",
                "payload": { ... }  # observation data
            }
        """

    # ------------------------------------------------------------------
    # Abstract interface — lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    def start(self) -> None:
        """Start the environment clock and any background services."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the environment clock and release all resources."""

    # ------------------------------------------------------------------
    # Action execution (environment-side)
    # ------------------------------------------------------------------

    def execute_action(self, action_type: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute an action on the environment side.

        Called by the trigger runtime when a trigger enqueues an action.
        Returns an execution receipt dict with at minimum::

            {
                "status": "succeeded" | "failed",
                "result_text": "...",
                "error_code": None | "TIMEOUT" | ...,
            }

        Default implementation raises NotImplementedError.
        Override this to handle actions in your environment.
        """
        raise NotImplementedError(
            f"Environment '{self.name}' does not implement execute_action. "
            f"Received action_type='{action_type}'."
        )

    # ------------------------------------------------------------------
    # Optional hooks
    # ------------------------------------------------------------------

    def get_context_block(self) -> str:
        """Return a Markdown block injected into the agent system prompt.

        Default implementation formats the observation/action spaces and
        latest observation.  Override for custom formatting.
        """
        import json
        obs_space = self.get_observation_space()
        act_space = self.get_action_space()
        obs = self.get_current_observation()
        lines = [
            f"## Trigger Environment: {self.name}",
            "",
            f"**Description**: {self.description}",
            "",
            "### Observation Space",
            "```json",
            json.dumps(obs_space, ensure_ascii=False, indent=2),
            "```",
            "",
            "### Action Space",
            "```json",
            json.dumps(act_space, ensure_ascii=False, indent=2),
            "```",
            "",
            "### Current Observation",
            "```json",
            json.dumps(obs, ensure_ascii=False, indent=2),
            "```",
        ]
        return "\n".join(lines)

    def on_agent_reply(self, reply: str) -> None:
        """Called after the agent produces a reply (optional hook).

        Use this to react to agent decisions, e.g. parse action commands
        from the reply text.  Default: no-op.
        """

    def validate_trigger_access(
        self,
        watched_observations: list[str],
        allowed_actions: list[str],
    ) -> bool:
        """Validate that a trigger's declared spaces are subsets of this
        environment's maximum spaces.

        This is the core safety gate: it ensures third-party triggers
        cannot access observation keys or fire action types beyond
        what the environment explicitly exposes.

        Default implementation checks key membership.  Override for
        custom validation logic (e.g. role-based access, conditional
        permissions based on environment state).
        """
        obs_keys = set(self.get_observation_space().keys())
        act_keys = set(self.get_action_space().keys())
        return(
            set(watched_observations).issubset(obs_keys)
            and set(allowed_actions).issubset(act_keys)
        )
