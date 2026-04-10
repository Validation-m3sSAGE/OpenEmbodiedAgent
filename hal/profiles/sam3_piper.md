# Robot Embodiment Declaration

This file describes the physical capabilities and constraints of the connected robot.
The Critic Agent reads this file to validate whether proposed actions are safe and feasible.

## Identity

- **Name**: SAM3 Piper Grasping Arm
- **Type**: 6-DOF robotic arm with gripper

## Sensors

- **RGB-D**: Intel RealSense D405 depth camera
- **Vision**: SAM3 segmentation model for zero-shot object detection

## Supported Actions

| Action | Parameters | Description |
|--------|-----------|-------------|
| `grasp_simple` | `target_name: str` | Execute single grasp of target object using SAM3 vision and Piper arm |
| `explore_and_grasp` | `target_name: str` | Rotate arm to search for target, then grasp when found |
| `explore_and_place` | `target_name: str` | Search for target location and place held object there |
| `explore_right_and_place` | `target_name: str` | Search right side for target location and place held object |
| `check_target` | `target_name: str` | Check if target exists in current camera view |
| `calibrate_axes` | - | Perform hand-eye calibration between arm and camera |
| `go_home` | - | Return arm to standby observation position |

## Connection

- **Transport**: local (direct CAN bus)
- **CAN Interface**: can0
- **CAN Bitrate**: 1000000
- **Control API**: piper_sdk via CAN bus

## Workspace Constraints

- **Max reach radius**: 0.46 m
- **Min Z height**: 0.05 m (safety floor)
- **Max Z height**: 0.50 m
- **Default standby pose**: (0.25, 0, 0.32) m, pitch=135°
- **TCP tool length**: 0.075 m
- **Grasp penetration**: 0.020 m

## Grasp Pipeline

1. Move to standby observation pose
2. Capture RGB image from RealSense
3. SAM3 segmentation for target object
4. Compute point cloud centroid
5. Transform camera→base coordinates via hand-eye calibration
6. Plan approach trajectory (45° angle)
7. Execute pre-grasp → grasp → retract → standby

## Safety Constraints

- **Collision policy**: IK solver validates joint limits before execution
- **Emergency stop**: CAN bus watchdog monitors communication
- **Calibration required**: Hand-eye matrix must exist (calibration_result.npz)
- **Object size**: Optimized for objects 5-15cm in diameter

## Runtime Protocol

- **Vision service**: http://127.0.0.1:8000 (SAM3 inference)
- **Health owner**: grasp_manager.py monitors arm state
- **State persistence**: calibration_result.npz stores T_ee_to_cam
