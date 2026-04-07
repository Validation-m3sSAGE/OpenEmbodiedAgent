from __future__ import annotations

from collections import deque
import base64
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable

import numpy as np
from PIL import Image

from hal.navigation.models import Detection, NavigationConfig, Observation, TargetHint


def _connected_components(mask: np.ndarray) -> Iterable[np.ndarray]:
    height, width = mask.shape
    visited = np.zeros_like(mask, dtype=bool)
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or visited[y, x]:
                continue
            queue = deque([(y, x)])
            visited[y, x] = True
            coords: list[tuple[int, int]] = []
            while queue:
                cy, cx = queue.popleft()
                coords.append((cy, cx))
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        queue.append((ny, nx))
            yield np.array(coords, dtype=np.int32)


class TargetDetector:
    def __init__(self, config: NavigationConfig):
        self.config = config
        self.sam3_client: SAM3Client | None = None

    def detect(self, observation: Observation, hint: TargetHint) -> Detection:
        if observation.rgb is None:
            return Detection(found=False, metadata={"reason": "missing_rgb"})
        sam3_detection = self._detect_with_sam3(observation.rgb, observation.depth_m, hint)
        if sam3_detection is not None:
            return sam3_detection
        mask = self._build_mask(observation.rgb, hint)
        if mask is None or not np.any(mask):
            metadata = {"reason": "target_not_detected"}
            if hint.rgb_range is None and hint.bbox is None:
                metadata["sam3_status"] = self._sam3_status()
            return Detection(found=False, metadata=metadata)
        return self._mask_to_detection(mask, observation.depth_m, observation.rgb.shape[:2], {})

    def _detect_with_sam3(self, rgb: np.ndarray, depth_m: np.ndarray | None, hint: TargetHint) -> Detection | None:
        if hint.strategy == "color_mask":
            return None
        if hint.strategy == "auto" and hint.rgb_range is not None:
            return None
        client = self._get_sam3_client()
        if client is None:
            return None
        response = client.detect(
            rgb=rgb,
            text_prompt=hint.text_prompt or hint.label,
            bbox=hint.bbox,
            plugin_name=hint.detector_plugin,
            plugin_config=hint.detector_params,
        )
        if not response.get("ok"):
            return None
        detections = response.get("detections", [])
        if not detections:
            return None
        best = detections[0]
        bbox = tuple(int(v) for v in best["bbox_xyxy"])
        cx, cy = int(best["center_px"][0]), int(best["center_px"][1])
        distance_m = self._sample_depth(depth_m, cx, cy)
        distance_source = "depth"
        area_pixels = int(best["area_pixels"])
        if distance_m is None:
            distance_m = self._estimate_distance_from_area(area_pixels)
            distance_source = "monocular_area"
        position_robot_m = None if distance_m is None else self._project_to_robot(distance_m, cx, cy, rgb.shape[:2])
        return Detection(
            found=True,
            confidence=float(best.get("score", 0.0)),
            center_px=(cx, cy),
            bbox_xyxy=bbox,
            distance_m=distance_m,
            position_robot_m=position_robot_m,
            area_pixels=area_pixels,
            metadata={
                "distance_source": distance_source,
                "detector": "sam3",
                "text_prompt": hint.text_prompt or hint.label,
                "detector_plugin": hint.detector_plugin,
            },
        )

    def _get_sam3_client(self) -> "SAM3Client | None":
        if self.sam3_client is None:
            self.sam3_client = SAM3Client()
        if not self.sam3_client.ensure_started():
            return None
        return self.sam3_client if self.sam3_client.available else None

    def _sam3_status(self) -> str:
        if self.sam3_client is None:
            return "not_initialized"
        return "ready" if self.sam3_client.available else (self.sam3_client.error or "unavailable")

    @staticmethod
    def _build_mask(rgb: np.ndarray, hint: TargetHint) -> np.ndarray | None:
        if hint.bbox is not None:
            x1, y1, x2, y2 = hint.bbox
            mask = np.zeros(rgb.shape[:2], dtype=bool)
            mask[max(0, y1):max(0, y2), max(0, x1):max(0, x2)] = True
            return mask
        if hint.rgb_range is not None:
            lo = np.array(hint.rgb_range[0], dtype=np.uint8)
            hi = np.array(hint.rgb_range[1], dtype=np.uint8)
            return np.all((rgb >= lo) & (rgb <= hi), axis=2)
        return None

    def _mask_to_detection(
        self,
        mask: np.ndarray,
        depth_m: np.ndarray | None,
        image_shape: tuple[int, int],
        extra_metadata: dict[str, Any],
    ) -> Detection:
        components = [component for component in _connected_components(mask) if len(component) >= 1]
        component = max(components, key=len)
        ys = component[:, 0]
        xs = component[:, 1]
        x1, x2 = int(xs.min()), int(xs.max())
        y1, y2 = int(ys.min()), int(ys.max())
        cx = int(np.mean(xs))
        cy = int(np.mean(ys))
        distance_m = self._sample_depth(depth_m, cx, cy)
        distance_source = "depth"
        if distance_m is None:
            distance_m = self._estimate_distance_from_area(len(component))
            distance_source = "monocular_area"
        position_robot_m = None if distance_m is None else self._project_to_robot(distance_m, cx, cy, image_shape)
        area = int(len(component))
        confidence = min(0.99, 0.4 + area / max(1, image_shape[0] * image_shape[1]))
        return Detection(
            found=True,
            confidence=confidence,
            center_px=(cx, cy),
            bbox_xyxy=(x1, y1, x2, y2),
            distance_m=distance_m,
            position_robot_m=position_robot_m,
            area_pixels=area,
            metadata={"distance_source": distance_source, **extra_metadata},
        )

    @staticmethod
    def _sample_depth(depth_m: np.ndarray | None, cx: int, cy: int) -> float | None:
        if depth_m is None:
            return None
        height, width = depth_m.shape[:2]
        patch = depth_m[max(0, cy - 2):min(height, cy + 3), max(0, cx - 2):min(width, cx + 3)]
        valid = patch[np.isfinite(patch) & (patch > 0.0)]
        return None if valid.size == 0 else float(np.median(valid))

    def _project_to_robot(self, depth_m: float, cx: int, cy: int, image_shape: tuple[int, int]) -> tuple[float, float, float]:
        height, width = image_shape
        c_x = self.config.camera_cx if self.config.camera_cx is not None else width / 2.0
        c_y = self.config.camera_cy if self.config.camera_cy is not None else height / 2.0
        x_cam = (cx - c_x) * depth_m / self.config.camera_fx
        y_cam = (cy - c_y) * depth_m / self.config.camera_fy
        return (float(depth_m), float(-x_cam), float(-y_cam))

    def _estimate_distance_from_area(self, area_pixels: int) -> float | None:
        if area_pixels <= 0:
            return None
        distance = self.config.monocular_reference_distance_m * math.sqrt(self.config.monocular_reference_area_px / float(area_pixels))
        return float(np.clip(distance, self.config.monocular_min_distance_m, self.config.monocular_max_distance_m))


class SAM3Client:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.available = False
        self.error: str | None = None
        self.plugin_name: str | None = None
        self.plugin_config: dict[str, Any] = {}

    def ensure_started(self, plugin_name: str | None = None, plugin_config: dict[str, Any] | None = None) -> bool:
        desired_plugin = (plugin_name or os.environ.get("OEA_TARGET_NAV_SAM_PLUGIN") or "sam3_builtin").strip()
        desired_config = dict(plugin_config or {})
        if self.process is not None and (self.plugin_name != desired_plugin or self.plugin_config != desired_config):
            self.close()
        if self.available and self.process is not None and self.process.poll() is None:
            return True
        if self.error is not None and self.plugin_name == desired_plugin and self.plugin_config == desired_config:
            return False
        from hal.navigation.sam_plugins import resolve_sam_worker_spec

        try:
            spec = resolve_sam_worker_spec(desired_plugin, desired_config)
            self.process = subprocess.Popen(
                list(spec.command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=dict(spec.env),
            )
            self.plugin_name = desired_plugin
            self.plugin_config = desired_config
            assert self.process.stdout is not None
            line = self.process.stdout.readline()
            if not line:
                stderr = "" if self.process.stderr is None else self.process.stderr.read().strip()
                self.error = f"sam3_worker_start_failed: {stderr or 'no_output'}"
                self.available = False
                return False
            response = json.loads(line)
            self.available = bool(response.get("ok")) and bool(response.get("ready"))
            self.error = None if self.available else response.get("error", "sam3_worker_not_ready")
            return self.available
        except Exception as exc:
            self.error = f"sam3_worker_spawn_failed: {exc}"
            self.available = False
            return False

    def detect(
        self,
        rgb: np.ndarray,
        text_prompt: str,
        bbox: tuple[int, int, int, int] | None,
        plugin_name: str | None = None,
        plugin_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.ensure_started(plugin_name=plugin_name, plugin_config=plugin_config):
            return {"ok": False, "error": self.error or "sam3_unavailable"}
        assert self.process is not None and self.process.stdin is not None and self.process.stdout is not None
        payload = {
            "image_base64_png": self._encode_image(rgb),
            "text_prompt": text_prompt,
            "bbox": None if bbox is None else list(bbox),
        }
        try:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            line = self.process.stdout.readline()
            if not line:
                self.available = False
                self.error = "sam3_worker_closed"
                return {"ok": False, "error": self.error}
            return json.loads(line)
        except Exception as exc:
            self.available = False
            self.error = f"sam3_worker_io_failed: {exc}"
            return {"ok": False, "error": self.error}

    def close(self) -> None:
        if self.process is not None:
            try:
                self.process.terminate()
            except Exception:
                pass
        self.process = None
        self.available = False
        self.plugin_name = None
        self.plugin_config = {}

    @staticmethod
    def _encode_image(rgb: np.ndarray) -> str:
        image = Image.fromarray(rgb.astype(np.uint8), mode="RGB")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("ascii")
