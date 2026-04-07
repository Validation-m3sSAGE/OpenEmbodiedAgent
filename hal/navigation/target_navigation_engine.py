from __future__ import annotations

import heapq
import math
import time
from typing import Any

import numpy as np

from hal.navigation.bridge import LocalHorizonCommand, RobotBridge
from hal.navigation.models import Detection, HorizonTarget, NavPhase, NavigationConfig, NavigationState, Observation, TargetHint
from hal.perception.target_detector import TargetDetector


class NavigationEngine:
    def __init__(self, bridge: RobotBridge, config: NavigationConfig | None = None):
        self.bridge = bridge
        self._base_config = config or NavigationConfig()
        self.config = NavigationConfig(**vars(self._base_config))
        self.detector = TargetDetector(self.config)
        self.state = NavigationState()
        self.target_hint: TargetHint | None = None
        self.injected_observation: Observation | None = None
        self._next_horizon_sequence = 1

    def set_target(
        self,
        target_label: str,
        success_distance_m: float | None = None,
        success_heading_deg: float | None = None,
        control_mode: str | None = None,
        detection_hint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.state = NavigationState(target_label=target_label, phase=NavPhase.SEARCHING, message=f"searching for {target_label}")
        self._next_horizon_sequence = 1
        self.config = NavigationConfig(**vars(self._base_config))
        self.detector.config = self.config
        if success_distance_m is not None:
            self.config.success_distance_m = success_distance_m
        if success_heading_deg is not None:
            self.config.success_heading_deg = success_heading_deg
        if control_mode is not None:
            if control_mode not in {"preemptive", "blocking"}:
                raise ValueError(f"unsupported control_mode: {control_mode}")
            self.config.control_mode = control_mode
        self.target_hint = self._build_hint(target_label, detection_hint)
        return self.state.to_dict()

    def cancel(self) -> dict[str, Any]:
        self.bridge.stop()
        self.state.phase = NavPhase.CANCELLED
        self.state.message = "navigation cancelled"
        return self.state.to_dict()

    def get_status(self) -> dict[str, Any]:
        return self.state.to_dict()

    def run_until_done(self, timeout_s: float = 30.0, step_delay_s: float = 0.0) -> dict[str, Any]:
        deadline = time.time() + timeout_s
        delay_s = step_delay_s if step_delay_s > 0.0 else self.config.horizon_refresh_interval_s
        while time.time() < deadline:
            result = self.step()
            if result["phase"] in {NavPhase.SUCCESS.value, NavPhase.BLOCKED.value, NavPhase.NOT_FOUND.value, NavPhase.CANCELLED.value}:
                return result
            if self.state.steps >= self.config.max_steps:
                self.bridge.stop()
                self.state.phase = NavPhase.BLOCKED
                self.state.active_horizon_target = None
                self.state.message = "maximum navigation steps reached"
                self.state.history.append({"event": "max_steps_blocked"})
                break
            if delay_s > 0.0:
                time.sleep(delay_s)
        return self.state.to_dict()

    def step(self) -> dict[str, Any]:
        if self.target_hint is None or self.state.target_label is None:
            raise ValueError("navigation target is not set")
        if self.state.phase in {NavPhase.SUCCESS, NavPhase.BLOCKED, NavPhase.NOT_FOUND, NavPhase.CANCELLED}:
            return self.state.to_dict()
        obs = self._consume_observation()
        if self.config.control_mode == "blocking":
            blocked_result = self._maybe_blocking_wait(obs)
            if blocked_result is not None:
                return blocked_result
        self._update_progress(obs)
        if self._stagnation_exceeded(obs):
            self.bridge.stop()
            self.state.phase = NavPhase.BLOCKED
            self.state.message = "robot failed to make progress toward refreshed horizons"
            self.state.history.append({"event": "stagnation_blocked"})
            return self.state.to_dict()
        detection = self.detector.detect(obs, self.target_hint)
        self.state.last_detection = detection
        self.state.steps += 1
        if detection.found:
            self.state.phase = NavPhase.TRACKING
            return self._track_target(obs, detection)
        return self._search_or_fail(obs)

    def _consume_observation(self) -> Observation:
        if self.injected_observation is not None:
            obs = self.injected_observation
            self.injected_observation = None
            return obs
        return self.bridge.get_observation()

    def _track_target(self, obs: Observation, detection: Detection) -> dict[str, Any]:
        if detection.position_robot_m is None or detection.distance_m is None:
            self.state.message = "target detected but depth unavailable"
            self.state.history.append({"event": "depth_missing"})
            return self.state.to_dict()
        pose_x, pose_y, pose_yaw = obs.pose_xy_yaw
        self.state.target_world_xy = self._robot_point_to_world(pose_x, pose_y, pose_yaw, detection.position_robot_m)
        angle_deg = math.degrees(math.atan2(detection.position_robot_m[1], detection.position_robot_m[0]))
        distance_source = str(detection.metadata.get("distance_source", ""))
        if distance_source == "depth" and detection.distance_m <= self.config.success_distance_m:
            if abs(angle_deg) > self.config.success_heading_deg:
                horizon = self._make_horizon_target(0.0, 0.0, math.radians(max(-self.config.action_turn_deg, min(self.config.action_turn_deg, angle_deg))), "success_alignment", (0.0, 0.0), issued_at=self._obs_time(obs))
                return self._dispatch_horizon(obs, horizon, "within success distance, aligning to face target", "success_alignment", {"angle_deg": angle_deg})
            self.bridge.stop()
            self.state.phase = NavPhase.SUCCESS
            self.state.active_horizon_target = None
            self.state.message = f"target reached within {self.config.success_distance_m:.2f} m and aligned"
            self.state.history.append({"event": "success", "distance_m": detection.distance_m, "angle_deg": angle_deg})
            return self.state.to_dict()
        plan = self._plan_tracking_motion(obs, detection)
        if plan is None:
            self.state.closest_reachable_xy = self._closest_reachable_xy(obs)
            self.bridge.stop()
            self.state.phase = NavPhase.BLOCKED
            self.state.active_horizon_target = None
            self.state.message = "no reachable free space toward target"
            self.state.history.append({"event": "blocked"})
            return self.state.to_dict()
        self.state.closest_reachable_xy = plan.get("closest_world_xy")
        self.state.closest_reachable_distance_m = plan.get("closest_target_distance_m")
        if plan["status"] == "blocked":
            self.bridge.stop()
            self.state.phase = NavPhase.BLOCKED
            self.state.active_horizon_target = None
            self.state.message = "reached closest reachable position but target remains obstructed"
            self.state.history.append({"event": "blocked", "closest_target_distance_m": self.state.closest_reachable_distance_m, "closest_reachable_xy": self.state.closest_reachable_xy})
            return self.state.to_dict()
        if plan["status"] == "detour_goal":
            return self._dispatch_horizon(obs, plan["horizon"], "tracking target via obstacle detour", "detour_horizon", {"closest_target_distance_m": self.state.closest_reachable_distance_m})
        if plan["status"] == "closest_approach":
            return self._dispatch_horizon(obs, plan["horizon"], "approaching closest reachable position before blocked assessment", "closest_approach_horizon", {"closest_target_distance_m": self.state.closest_reachable_distance_m})
        return self._dispatch_horizon(obs, plan["horizon"], "tracking target", "direct_horizon", {})

    def _search_or_fail(self, obs: Observation) -> dict[str, Any]:
        if self.state.search_turns_completed >= self.config.max_search_turns:
            self.bridge.stop()
            self.state.phase = NavPhase.NOT_FOUND
            self.state.active_horizon_target = None
            self.state.message = "target not observed after one full clockwise scan"
            self.state.history.append({"event": "not_found"})
            return self.state.to_dict()
        horizon = self._make_horizon_target(0.0, 0.0, -math.radians(self.config.search_turn_deg), "search_sweep", (0.0, 0.0), valid_for_s=self.config.search_horizon_valid_for_s)
        self.state.search_turns_completed += 1
        self.state.phase = NavPhase.SEARCHING
        return self._dispatch_horizon(obs, horizon, f"target missing, rotating clockwise {self.config.search_turn_deg:.0f} deg", "search_turn", {"turn_index": self.state.search_turns_completed, "turn_deg": self.config.search_turn_deg})

    def _build_hint(self, target_label: str, detection_hint: dict[str, Any] | None) -> TargetHint:
        if not detection_hint:
            return TargetHint(label=target_label)
        rgb_range = detection_hint.get("rgb_range")
        bbox = detection_hint.get("bbox")
        point_xy = detection_hint.get("point_xy")
        prompt = detection_hint.get("text_prompt") or detection_hint.get("prompt") or detection_hint.get("sam_prompt") or target_label
        strategy = str(detection_hint.get("strategy") or ("color_mask" if rgb_range is not None else "sam3")).strip()
        return TargetHint(label=target_label, strategy=strategy if strategy in {"auto", "color_mask", "sam3"} else "auto", text_prompt=prompt, rgb_range=None if rgb_range is None else (tuple(rgb_range[0]), tuple(rgb_range[1])), min_pixels=int(detection_hint.get("min_pixels", 150)), bbox=None if bbox is None else tuple(int(v) for v in bbox), point_xy=None if point_xy is None else tuple(int(v) for v in point_xy), detector_plugin=detection_hint.get("detector_plugin") or detection_hint.get("plugin"), detector_params=dict(detection_hint.get("detector_params") or {}))

    def _line_of_sight_clear(self, obs: Observation, target_distance_m: float) -> bool:
        if obs.occupancy is None:
            return True
        rows, cols = obs.occupancy.shape[:2]
        meters = np.arange(self.config.obstacle_margin_m, target_distance_m, self.config.occupancy_resolution_m)
        for dist in meters:
            gx = int(round(dist / self.config.occupancy_resolution_m))
            gy = rows // 2
            if 0 <= gy < rows and 0 <= gx < cols and obs.occupancy[gy, gx] > 0:
                return False
        return True

    def _plan_tracking_motion(self, obs: Observation, detection: Detection) -> dict[str, Any] | None:
        if detection.position_robot_m is None or detection.distance_m is None:
            return None
        direct_horizon = self._direct_tracking_horizon(obs, detection)
        if obs.occupancy is None or self._line_of_sight_clear(obs, detection.distance_m):
            return {"status": "direct", "horizon": direct_horizon, "lookahead_xy": direct_horizon.lookahead_xy}
        plan = self._plan_path_in_occupancy(obs.occupancy, detection)
        if plan is None:
            return None
        path = plan["path"]
        closest_cell = plan["closest_cell"]
        closest_x_m, closest_y_m = self._grid_to_robot_xy(obs.occupancy, closest_cell)
        closest_world_xy = self._robot_point_to_world(obs.pose_xy_yaw[0], obs.pose_xy_yaw[1], obs.pose_xy_yaw[2], (closest_x_m, closest_y_m, 0.0))
        if len(path) <= 1:
            return {"status": "blocked", "closest_world_xy": closest_world_xy, "closest_target_distance_m": plan["closest_target_distance_m"]}
        lookahead = path[min(len(path) - 1, self.config.horizon_lookahead_steps)]
        target_x_m, target_y_m = self._grid_to_robot_xy(obs.occupancy, lookahead)
        heading_rad = math.atan2(target_y_m, target_x_m)
        horizon = self._make_guided_motion_horizon(min(self.config.action_forward_m, max(0.0, target_x_m)), float(np.clip(target_y_m, -self.config.horizon_max_lateral_m, self.config.horizon_max_lateral_m)), float(np.clip(heading_rad * self.config.horizon_heading_gain, -math.radians(self.config.action_turn_deg), math.radians(self.config.action_turn_deg))), plan["status"], (target_x_m, target_y_m), issued_at=self._obs_time(obs))
        return {"status": plan["status"], "horizon": horizon, "closest_world_xy": closest_world_xy, "closest_target_distance_m": plan["closest_target_distance_m"], "lookahead_xy": (target_x_m, target_y_m)}

    def _direct_tracking_horizon(self, obs: Observation, detection: Detection) -> HorizonTarget:
        forward = min(self.config.action_forward_m, max(0.0, detection.distance_m - self.config.success_distance_m))
        lateral = float(np.clip(detection.position_robot_m[1], -self.config.horizon_max_lateral_m, self.config.horizon_max_lateral_m))
        heading_rad = math.atan2(lateral, max(0.05, forward if forward > 0.0 else detection.position_robot_m[0]))
        return self._make_guided_motion_horizon(max(0.05, forward), lateral, float(np.clip(heading_rad * self.config.horizon_heading_gain, -math.radians(self.config.action_turn_deg), math.radians(self.config.action_turn_deg))), "direct", (detection.position_robot_m[0], detection.position_robot_m[1]), issued_at=self._obs_time(obs))

    def _make_guided_motion_horizon(self, forward_m: float, lateral_m: float, heading_rad: float, source: str, lookahead_xy: tuple[float, float] | None, issued_at: float | None = None) -> HorizonTarget:
        if self._should_rotate_in_place(heading_rad, forward_m, lateral_m):
            return self._make_horizon_target(0.0, 0.0, heading_rad, f"{source}_rotate_in_place", lookahead_xy, issued_at=issued_at)
        return self._make_horizon_target(forward_m, lateral_m, 0.0, source, lookahead_xy, issued_at=issued_at)

    def _should_rotate_in_place(self, heading_rad: float, forward_m: float, lateral_m: float) -> bool:
        return (abs(forward_m) > 1e-3 or abs(lateral_m) > 1e-3) and abs(math.degrees(heading_rad)) >= self.config.rotate_in_place_threshold_deg

    def _plan_path_in_occupancy(self, occupancy: np.ndarray, detection: Detection) -> dict[str, Any] | None:
        rows, cols = occupancy.shape[:2]
        start = (rows // 2, 0)
        if occupancy[start] > 0:
            return None
        target_row, target_col = self._robot_xy_to_grid(occupancy, detection.position_robot_m[0], detection.position_robot_m[1])
        goal_radius = max(1, int(round(self.config.success_distance_m / self.config.occupancy_resolution_m)))
        candidate_goals = [(row, col) for row in range(rows) for col in range(cols) if occupancy[row, col] == 0 and math.hypot(row - target_row, col - target_col) <= goal_radius and col <= target_col + 1]
        clear_goals = {goal for goal in candidate_goals if self._goal_has_clearance(occupancy, goal)}
        frontier: list[tuple[float, float, tuple[int, int]]] = [(0.0, 0.0, start)]
        came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        cost_so_far: dict[tuple[int, int], float] = {start: 0.0}
        neighbors = [(-1, 0), (1, 0), (0, 1), (-1, 1), (1, 1)]
        best_cell = start
        best_distance = float("inf")
        while frontier:
            _, current_cost, current = heapq.heappop(frontier)
            if current_cost > cost_so_far[current]:
                continue
            current_distance = math.hypot(current[0] - target_row, current[1] - target_col)
            if current_distance < best_distance:
                best_distance = current_distance
                best_cell = current
            if current in clear_goals:
                return {"status": "detour_goal", "path": self._reconstruct_path(came_from, current), "closest_cell": current, "closest_target_distance_m": current_distance * self.config.occupancy_resolution_m}
            for d_row, d_col in neighbors:
                nxt = (current[0] + d_row, current[1] + d_col)
                if not (0 <= nxt[0] < rows and 0 <= nxt[1] < cols):
                    continue
                if occupancy[nxt] > 0 or not self._goal_has_clearance(occupancy, nxt):
                    continue
                step_cost = math.hypot(d_row, d_col)
                new_cost = current_cost + step_cost
                if new_cost >= cost_so_far.get(nxt, float("inf")):
                    continue
                cost_so_far[nxt] = new_cost
                came_from[nxt] = current
                heuristic = 0.0 if not clear_goals else min(math.hypot(nxt[0] - goal[0], nxt[1] - goal[1]) for goal in clear_goals)
                heapq.heappush(frontier, (new_cost + heuristic, new_cost, nxt))
        if best_distance == float("inf"):
            return None
        return {"status": "closest_approach", "path": self._reconstruct_path(came_from, best_cell), "closest_cell": best_cell, "closest_target_distance_m": best_distance * self.config.occupancy_resolution_m}

    def _goal_has_clearance(self, occupancy: np.ndarray, cell: tuple[int, int]) -> bool:
        clearance_cells = max(1, int(math.ceil(max(self.config.occupancy_resolution_m, self.config.robot_collision_radius_m + self.config.clearance_buffer_m) / self.config.occupancy_resolution_m)))
        row, col = cell
        rows, cols = occupancy.shape[:2]
        for rr in range(max(0, row - clearance_cells), min(rows, row + clearance_cells + 1)):
            for cc in range(max(0, col - clearance_cells), min(cols, col + clearance_cells + 1)):
                if occupancy[rr, cc] > 0:
                    return False
        return True

    def _robot_xy_to_grid(self, occupancy: np.ndarray, forward_m: float, lateral_m: float) -> tuple[int, int]:
        rows, cols = occupancy.shape[:2]
        col = int(round(forward_m / self.config.occupancy_resolution_m))
        row = int(round(lateral_m / self.config.occupancy_resolution_m)) + rows // 2
        return int(np.clip(row, 0, rows - 1)), int(np.clip(col, 0, cols - 1))

    def _grid_to_robot_xy(self, occupancy: np.ndarray, cell: tuple[int, int]) -> tuple[float, float]:
        rows, _ = occupancy.shape[:2]
        row, col = cell
        return col * self.config.occupancy_resolution_m, (row - rows // 2) * self.config.occupancy_resolution_m

    @staticmethod
    def _reconstruct_path(came_from: dict[tuple[int, int], tuple[int, int] | None], current: tuple[int, int]) -> list[tuple[int, int]]:
        path = [current]
        while came_from[current] is not None:
            current = came_from[current]
            path.append(current)
        path.reverse()
        return path

    def _closest_reachable_xy(self, obs: Observation) -> tuple[float, float]:
        pose_x, pose_y, pose_yaw = obs.pose_xy_yaw
        backoff = max(0.0, (self.state.last_detection.distance_m or 0.0) - self.config.success_distance_m)
        reach = max(0.0, min(backoff, self.config.action_forward_m))
        return pose_x + math.cos(pose_yaw) * reach, pose_y + math.sin(pose_yaw) * reach

    def _make_horizon_target(self, forward_m: float, lateral_m: float, heading_rad: float, source: str, lookahead_xy: tuple[float, float] | None, issued_at: float | None = None, valid_for_s: float | None = None) -> HorizonTarget:
        target = HorizonTarget(float(forward_m), float(lateral_m), float(heading_rad), float(self.config.horizon_valid_for_s if valid_for_s is None else valid_for_s), source, self._next_horizon_sequence, float(time.time() if issued_at is None else issued_at), lookahead_xy)
        self._next_horizon_sequence += 1
        return target

    def _dispatch_horizon(self, obs: Observation, horizon: HorizonTarget, message: str, event: str, extra_history: dict[str, Any]) -> dict[str, Any]:
        self.state.active_horizon_target = horizon
        exec_result = self.bridge.execute(LocalHorizonCommand(horizon.forward_m, horizon.lateral_m, horizon.heading_rad, horizon.valid_for_s, horizon.source, horizon.sequence_id, horizon.issued_at, horizon.lookahead_xy))
        if not exec_result.get("ok", False):
            self.state.phase = NavPhase.BLOCKED
            self.state.message = f"horizon dispatch failed: {exec_result.get('reason', 'unknown')}"
            self.state.history.append({"event": f"{event}_failed", "horizon": horizon.to_dict(), "result": exec_result})
            return self.state.to_dict()
        self.state.message = message
        self.state.history.append({"event": event, "horizon": horizon.to_dict(), "result": exec_result, **extra_history})
        return self.state.to_dict()

    def _maybe_blocking_wait(self, obs: Observation) -> dict[str, Any] | None:
        active = self.state.active_horizon_target
        if active is None:
            return None
        feedback = self.bridge.get_motion_feedback()
        if not isinstance(feedback, dict) or feedback.get("controller") != "local_horizon" or feedback.get("sequence_id") != active.sequence_id or feedback.get("event") != "motion_finished":
            self.state.message = f"waiting for horizon {active.sequence_id} to finish"
            return self.state.to_dict()
        reason = str(feedback.get("reason", "unknown"))
        self.state.history.append({"event": "blocking_horizon_finished", "sequence_id": active.sequence_id, "reason": reason, "feedback": feedback})
        self.state.active_horizon_target = None
        self.state.stagnation_started_at = None
        self.state.last_progress_pose_xy_yaw = obs.pose_xy_yaw
        self.state.last_progress_timestamp = self._obs_time(obs)
        if active.source == "search_sweep" and reason in {"horizon_expired", "local_horizon_target_reached"}:
            self.state.message = f"search horizon finished with {reason}, continuing search"
            return None
        if reason in {"local_horizon_blocked", "horizon_expired"}:
            self.state.phase = NavPhase.BLOCKED
            self.state.message = f"blocking horizon ended with {reason}"
            return self.state.to_dict()
        return None

    def _update_progress(self, obs: Observation) -> None:
        now = self._obs_time(obs)
        if self.state.last_progress_pose_xy_yaw is None:
            self.state.last_progress_pose_xy_yaw = obs.pose_xy_yaw
            self.state.last_progress_timestamp = now
            return
        last_pose = self.state.last_progress_pose_xy_yaw
        delta_xy = math.hypot(obs.pose_xy_yaw[0] - last_pose[0], obs.pose_xy_yaw[1] - last_pose[1])
        delta_heading = abs(math.degrees(self._angle_diff(obs.pose_xy_yaw[2], last_pose[2])))
        if delta_xy >= self.config.horizon_min_progress_m or delta_heading >= self.config.horizon_min_progress_heading_deg:
            self.state.last_progress_pose_xy_yaw = obs.pose_xy_yaw
            self.state.last_progress_timestamp = now
            self.state.stagnation_started_at = None
        elif self.state.active_horizon_target is not None and self.state.stagnation_started_at is None:
            self.state.stagnation_started_at = now

    def _stagnation_exceeded(self, obs: Observation) -> bool:
        return self.state.active_horizon_target is not None and self.state.stagnation_started_at is not None and (self._obs_time(obs) - self.state.stagnation_started_at) >= self.config.horizon_progress_timeout_s

    @staticmethod
    def _obs_time(obs: Observation) -> float:
        return float(obs.timestamp if obs.timestamp > 0.0 else time.time())

    @staticmethod
    def _angle_diff(current: float, previous: float) -> float:
        delta = current - previous
        while delta > math.pi:
            delta -= 2 * math.pi
        while delta < -math.pi:
            delta += 2 * math.pi
        return delta

    @staticmethod
    def _robot_point_to_world(pose_x: float, pose_y: float, pose_yaw: float, robot_point: tuple[float, float, float]) -> tuple[float, float]:
        forward, lateral, _ = robot_point
        return float(pose_x + forward * math.cos(pose_yaw) - lateral * math.sin(pose_yaw)), float(pose_y + forward * math.sin(pose_yaw) + lateral * math.cos(pose_yaw))
