from __future__ import annotations

import abc
import math
import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from hal.navigation.models import Observation


@dataclass
class ActionCommand:
    kind: str
    value: float = 0.0


@dataclass
class LocalHorizonCommand:
    forward_m: float
    lateral_m: float
    heading_rad: float
    valid_for_s: float
    source: str
    sequence_id: int
    issued_at: float
    lookahead_xy: tuple[float, float] | None = None


class RobotBridge(abc.ABC):
    @abc.abstractmethod
    def get_observation(self) -> Observation:
        raise NotImplementedError

    @abc.abstractmethod
    def execute(self, command: ActionCommand | LocalHorizonCommand) -> dict[str, Any]:
        raise NotImplementedError

    def get_motion_feedback(self) -> dict[str, Any] | None:
        return None

    def stop(self) -> dict[str, Any]:
        return self.execute(ActionCommand(kind="stop", value=0.0))

    def describe_navigation_capabilities(self) -> dict[str, Any]:
        return {
            "has_rgb": True,
            "has_depth": False,
            "has_occupancy": False,
            "supports_local_horizon": True,
            "supports_obstacle_avoidance": False,
            "supports_external_map_assist": False,
        }


class SimulatedRobotBridge(RobotBridge):
    def __init__(self) -> None:
        self.pose = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        self.last_motion_feedback: dict[str, Any] | None = None
        self.obstacle_cells = {(7, 4), (7, 5), (7, 6)}

    def get_observation(self) -> Observation:
        occupancy = np.zeros((12, 12), dtype=np.uint8)
        for row, col in self.obstacle_cells:
            if 0 <= row < occupancy.shape[0] and 0 <= col < occupancy.shape[1]:
                occupancy[row, col] = 1
        rgb = np.zeros((120, 160, 3), dtype=np.uint8)
        rgb[52:68, 72:88, 0] = 220
        return Observation(
            rgb=rgb,
            depth_m=None,
            occupancy=occupancy,
            pose_xy_yaw=(float(self.pose[0]), float(self.pose[1]), float(self.pose[2])),
            timestamp=time.time(),
        )

    def get_motion_feedback(self) -> dict[str, Any] | None:
        return self.last_motion_feedback

    def describe_navigation_capabilities(self) -> dict[str, Any]:
        return {
            "has_rgb": True,
            "has_depth": False,
            "has_occupancy": True,
            "supports_local_horizon": True,
            "supports_obstacle_avoidance": True,
            "supports_external_map_assist": False,
        }

    def execute(self, command: ActionCommand | LocalHorizonCommand) -> dict[str, Any]:
        if isinstance(command, LocalHorizonCommand):
            return self._execute_horizon(command)
        if command.kind == "stop":
            self.last_motion_feedback = {"event": "motion_finished", "reason": "simulated_stop", "controller": "closed_loop"}
            return {"ok": True, "kind": "stop"}
        if command.kind == "forward":
            next_x = float(self.pose[0] + command.value * math.cos(self.pose[2]))
            next_y = float(self.pose[1] + command.value * math.sin(self.pose[2]))
            if self._pose_hits_obstacle(next_x, next_y):
                self.last_motion_feedback = {"event": "motion_finished", "reason": "collision_predicted", "controller": "closed_loop"}
                return {"ok": False, "reason": "collision_predicted"}
            self.pose[0] = next_x
            self.pose[1] = next_y
        elif command.kind == "turn_left":
            self.pose[2] += math.radians(command.value)
        elif command.kind == "turn_right":
            self.pose[2] -= math.radians(command.value)
        self.last_motion_feedback = {"event": "motion_finished", "reason": "simulated_complete", "controller": "closed_loop"}
        return {"ok": True, "pose": self.pose.tolist()}

    def _execute_horizon(self, command: LocalHorizonCommand) -> dict[str, Any]:
        new_yaw = float(self.pose[2] + command.heading_rad)
        dx = command.forward_m * math.cos(new_yaw) - command.lateral_m * math.sin(new_yaw)
        dy = command.forward_m * math.sin(new_yaw) + command.lateral_m * math.cos(new_yaw)
        next_x = float(self.pose[0] + dx)
        next_y = float(self.pose[1] + dy)
        if self._pose_hits_obstacle(next_x, next_y):
            self.last_motion_feedback = {
                "event": "motion_finished",
                "reason": "local_horizon_blocked",
                "controller": "local_horizon",
                "sequence_id": command.sequence_id,
            }
            return {"ok": False, "reason": "local_horizon_blocked"}
        self.pose[0] = next_x
        self.pose[1] = next_y
        self.pose[2] = new_yaw
        self.last_motion_feedback = {
            "event": "motion_finished",
            "reason": "local_horizon_target_reached",
            "controller": "local_horizon",
            "sequence_id": command.sequence_id,
        }
        return {"ok": True, "pose": self.pose.tolist(), "controller": "local_horizon"}

    def _pose_hits_obstacle(self, x: float, y: float) -> bool:
        gx = int(round(x / 0.10))
        gy = int(round(y / 0.10)) + 6
        return (gy, gx) in self.obstacle_cells
