from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

import numpy as np


class NavPhase(str, Enum):
    IDLE = "idle"
    SEARCHING = "searching"
    TRACKING = "tracking"
    SUCCESS = "success"
    BLOCKED = "blocked"
    NOT_FOUND = "not_found"
    CANCELLED = "cancelled"


@dataclass
class TargetHint:
    label: str
    strategy: Literal["auto", "color_mask", "sam3"] = "auto"
    text_prompt: str | None = None
    rgb_range: tuple[tuple[int, int, int], tuple[int, int, int]] | None = None
    min_pixels: int = 150
    bbox: tuple[int, int, int, int] | None = None
    point_xy: tuple[int, int] | None = None
    detector_plugin: str | None = None
    detector_params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Detection:
    found: bool
    confidence: float = 0.0
    center_px: tuple[int, int] | None = None
    bbox_xyxy: tuple[int, int, int, int] | None = None
    distance_m: float | None = None
    position_robot_m: tuple[float, float, float] | None = None
    area_pixels: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Observation:
    rgb: np.ndarray | None = None
    depth_m: np.ndarray | None = None
    occupancy: np.ndarray | None = None
    pose_xy_yaw: tuple[float, float, float] = (0.0, 0.0, 0.0)
    timestamp: float = 0.0


@dataclass
class HorizonTarget:
    forward_m: float
    lateral_m: float
    heading_rad: float
    valid_for_s: float
    source: str
    sequence_id: int
    issued_at: float
    lookahead_xy: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "forward_m": self.forward_m,
            "lateral_m": self.lateral_m,
            "heading_rad": self.heading_rad,
            "valid_for_s": self.valid_for_s,
            "source": self.source,
            "sequence_id": self.sequence_id,
            "issued_at": self.issued_at,
            "lookahead_xy": self.lookahead_xy,
        }


@dataclass
class NavigationConfig:
    success_distance_m: float = 0.8
    success_heading_deg: float = 10.0
    obstacle_margin_m: float = 0.45
    robot_collision_radius_m: float = 0.22
    clearance_buffer_m: float = 0.05
    max_search_turns: int = 8
    search_turn_deg: float = 45.0
    target_relocation_m: float = 0.75
    max_steps: int = 64
    camera_fx: float = 525.0
    camera_fy: float = 525.0
    camera_cx: float | None = None
    camera_cy: float | None = None
    action_forward_m: float = 0.35
    action_turn_deg: float = 30.0
    occupancy_resolution_m: float = 0.10
    control_mode: Literal["preemptive", "blocking"] = "preemptive"
    horizon_valid_for_s: float = 0.8
    search_horizon_valid_for_s: float = 1.4
    horizon_lookahead_steps: int = 4
    horizon_refresh_interval_s: float = 0.25
    horizon_max_lateral_m: float = 0.35
    horizon_heading_gain: float = 1.0
    rotate_in_place_threshold_deg: float = 12.0
    horizon_progress_timeout_s: float = 3.0
    horizon_min_progress_m: float = 0.05
    horizon_min_progress_heading_deg: float = 6.0
    monocular_reference_area_px: float = 1600.0
    monocular_reference_distance_m: float = 1.2
    monocular_min_distance_m: float = 0.35
    monocular_max_distance_m: float = 4.0


@dataclass
class NavigationState:
    target_label: str | None = None
    phase: NavPhase = NavPhase.IDLE
    message: str = "idle"
    steps: int = 0
    search_turns_completed: int = 0
    last_detection: Detection | None = None
    target_world_xy: tuple[float, float] | None = None
    closest_reachable_xy: tuple[float, float] | None = None
    closest_reachable_distance_m: float | None = None
    active_horizon_target: HorizonTarget | None = None
    stagnation_started_at: float | None = None
    last_progress_timestamp: float | None = None
    last_progress_pose_xy_yaw: tuple[float, float, float] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_label": self.target_label,
            "phase": self.phase.value,
            "message": self.message,
            "steps": self.steps,
            "search_turns_completed": self.search_turns_completed,
            "target_world_xy": self.target_world_xy,
            "closest_reachable_xy": self.closest_reachable_xy,
            "closest_reachable_distance_m": self.closest_reachable_distance_m,
            "active_horizon_target": None if self.active_horizon_target is None else self.active_horizon_target.to_dict(),
            "stagnation_started_at": self.stagnation_started_at,
            "last_progress_timestamp": self.last_progress_timestamp,
            "last_progress_pose_xy_yaw": self.last_progress_pose_xy_yaw,
            "last_detection": None
            if self.last_detection is None
            else {
                "found": self.last_detection.found,
                "confidence": self.last_detection.confidence,
                "center_px": self.last_detection.center_px,
                "bbox_xyxy": self.last_detection.bbox_xyxy,
                "distance_m": self.last_detection.distance_m,
                "position_robot_m": self.last_detection.position_robot_m,
                "area_pixels": self.last_detection.area_pixels,
                "metadata": self.last_detection.metadata,
            },
            "history_tail": self.history[-10:],
        }
