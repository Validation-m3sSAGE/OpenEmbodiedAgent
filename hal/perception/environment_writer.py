"""Environment writer for side-loaded perception updates.

Usage (without event bus — standalone / HAL Watchdog):
    writer = EnvironmentWriter(workspace)
    writer.write(robot_id="go2_edu_001", robot_pose=pose, scene_graph=sg)

Usage (with event bus — perception service integrated with AgentLoop):
    writer = EnvironmentWriter(workspace, bus=message_bus)
    writer.write(
        robot_id="go2_edu_001",
        scene_graph=sg,
        events=[
            PerceptionEventSpec("target_detected", "Apple detected at (0.5, 0.3, 0.8)"),
        ],
    )
    # The PerceptionEvent is published to bus.perception so the AgentLoop
    # can inject it as a system message into the active session.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hal.simulation.scene_io import load_environment_doc, merge_environment_doc, save_environment_doc

if TYPE_CHECKING:
    from PhyAgentOS.bus.queue import MessageBus


@dataclass
class PerceptionEventSpec:
    """Lightweight spec for a perception event to be published after a write.

    Attributes
    ----------
    event_type:
        Machine-readable label (e.g. ``"target_detected"``).
    description:
        Human-readable text forwarded to the LLM as a system message.
    session_key:
        Optional routing key ``"channel:chat_id"``.  ``None`` = broadcast.
    data:
        Arbitrary structured payload attached to the event.
    """

    event_type: str
    description: str
    session_key: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class EnvironmentWriter:
    """Writes structured perception outputs into ENVIRONMENT.md.

    Parameters
    ----------
    workspace:
        Directory that contains ``ENVIRONMENT.md``.
    bus:
        Optional ``MessageBus`` instance.  When provided, perception events
        passed to :meth:`write` are published to ``bus.perception`` so the
        AgentLoop can react proactively.
    """

    def __init__(self, workspace: Path, bus: "MessageBus | None" = None):
        self.workspace = workspace
        self._bus = bus

    def write(
        self,
        *,
        robot_id: str,
        robot_pose: dict[str, Any] | None = None,
        nav_state: dict[str, Any] | None = None,
        scene_graph: dict[str, Any] | None = None,
        map_data: dict[str, Any] | None = None,
        tf_data: dict[str, Any] | None = None,
        events: list[PerceptionEventSpec] | None = None,
    ) -> dict[str, Any]:
        """Write perception data to ENVIRONMENT.md and optionally publish events.

        Parameters
        ----------
        robot_id:
            ID of the robot whose state is being updated.
        robot_pose, nav_state, scene_graph, map_data, tf_data:
            Perception data partitions.  ``None`` means "leave unchanged".
        events:
            List of :class:`PerceptionEventSpec` objects to publish to the
            message bus after the file write.  Ignored when no bus is set.

        Returns
        -------
        dict
            The merged environment document that was written to disk.
        """
        env_path = self.workspace / "ENVIRONMENT.md"
        existing = load_environment_doc(env_path)
        robots = dict(existing.get("robots", {}))
        robot_entry = dict(robots.get(robot_id, {}))
        if robot_pose is not None:
            robot_entry["robot_pose"] = robot_pose
        if nav_state is not None:
            robot_entry["nav_state"] = nav_state
        if robot_entry:
            robots[robot_id] = robot_entry

        merged = merge_environment_doc(
            existing,
            robots=robots,
            scene_graph=scene_graph,
            map_data=map_data,
            tf_data=tf_data,
            updated_at=datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        )
        save_environment_doc(env_path, merged)

        # ── publish perception events ─────────────────────────────────────────
        if events and self._bus is not None:
            self._publish_events(robot_id, events)

        return merged

    def _publish_events(self, robot_id: str, specs: list[PerceptionEventSpec]) -> None:
        """Fire-and-forget: schedule perception event publishing on the running loop."""
        from PhyAgentOS.bus.events import PerceptionEvent

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop (e.g. called from a sync thread).
            # Create a new loop just for this publish batch.
            loop = None

        for spec in specs:
            event = PerceptionEvent(
                event_type=spec.event_type,
                robot_id=robot_id,
                description=spec.description,
                session_key=spec.session_key,
                data=spec.data,
            )
            if loop is not None:
                loop.create_task(self._bus.publish_perception(event))
            else:
                # Synchronous fallback: put directly (thread-safe for asyncio.Queue)
                self._bus.perception.put_nowait(event)
