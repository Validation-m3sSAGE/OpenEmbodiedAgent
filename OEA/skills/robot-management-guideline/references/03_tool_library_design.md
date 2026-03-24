# Phase 3: Tool Library Design

**Build reusable utilities before writing task-specific scripts.**

Jumping directly to task scripts (e.g., "grasp the bottle") without a utility layer leads to:
- Repeated boilerplate in every script
- Hardware quirks (offsets, unit conversions) handled inconsistently
- Debugging the same low-level issue multiple times

## 3.1 The Tool-First Principle

For any robot project involving more than one script, design the tool library **first**, before writing any task logic.

```
✅ Correct order:
   1. Write robot_utils.py  (move, read_state, gripper)
   2. Write camera_utils.py (capture, depth_at_pixel, detect_color)
   3. Write perception_utils.py (segment, compute_3d)
   4. Write task_script.py  (calls the above, ~50 lines)

❌ Wrong order:
   1. Write grasp_v1.py  (500 lines, everything mixed)
   2. Write grasp_v2.py  (copy-paste from v1, fix one thing)
   3. Write grasp_v3.py  ...
```

## 3.2 Mandatory Utility Modules

For a typical robot manipulation project, the following modules should be built:

### `robot_utils.py` — Robot Control Abstraction
Must encapsulate:
- Initialization (connect, enable, wait for ready)
- **All hardware offsets** (joint zero offsets, TCP offsets) applied in the constructor
- `joint_move(j1..j6, speed, duration)` — joint space motion
- `cart_move(x, y, z, rx, ry, rz, speed, duration)` — Cartesian motion
- `go_home()`, `go_observe()` — named poses
- `gripper_open()`, `gripper_close(position)`
- `read_joints()`, `read_tcp()`, `read_status()`
- `get_transform_to_base()` — returns 4×4 homogeneous matrix

### `camera_utils.py` — Sensor Abstraction
Must encapsulate:
- Initialization (pipeline start, warmup frames)
- **Valid range constants** as class attributes (e.g., `MIN_DEPTH`, `MAX_DEPTH`)
- `capture()` → returns (color_image, depth_map_meters)
- `pixel_to_3d(u, v, depth)` → camera-frame 3D point
- `depth_in_mask(mask, percentile)` → robust depth estimate
- `save_debug(color, depth, mask, path)` → side-by-side visualization

### `perception_utils.py` (if using vision models)
Must encapsulate:
- Model loading (done once in constructor)
- `segment_from_point(image, uv)` → mask
- `segment_from_box(image, box)` → mask
- `detect_color_region(image, color)` → center pixel

## 3.3 Design Rules for Utility Modules

1. **No task logic in utilities.** Utilities only provide primitive operations. Task scripts compose them.
2. **Hardware constants at the top.** All magic numbers (valid ranges, unit factors, default poses) must be named constants at the module level, not buried in functions.
3. **Fail loudly.** If a utility receives invalid input or the hardware is out of range, raise an exception with a clear message — do not silently return `None` or `0`.
4. **Parameterize, don't hardcode.** Pass target positions, speeds, and thresholds as arguments. Use sensible defaults.
5. **One environment per module.** If the robot SDK and the vision model require different conda environments, keep their utilities in separate files and communicate via files, sockets, or ROS topics.

## 3.4 Task Script Design

Once utilities exist, task scripts should be thin:

```python
# Good task script structure (~50-80 lines)
robot  = RobotUtils(offset_deg=-60)
camera = CameraUtils()
vision = PerceptionUtils()

robot.go_observe()
color, depth = camera.capture()
cap_uv = camera.detect_color_region(color, 'red')
mask, score = vision.segment_from_point(color, cap_uv)
depth_val, n = camera.depth_in_mask(mask)
if n < 10:
    raise RuntimeError(f"Insufficient depth ({n} px). Move closer.")
xyz_cam = camera.pixel_to_3d(*cap_uv, depth_val)
xyz_base = robot.transform_cam_to_base(xyz_cam, T_cam2gripper)
robot.grasp(xyz_base)
```

## 3.5 Calibration Scripts

Calibration (hand-eye, intrinsics, workspace mapping) should also be standalone reusable scripts, not one-off experiments:

- Accept parameters via `argparse` (e.g., `--square_mm`, `--j6_offset`)
- Save results to a standard path (e.g., `calibration_result.npz`)
- Print a quality metric at the end (e.g., reprojection error, TSAI vs PARK diff)
- Be runnable at any time to re-calibrate without code changes
