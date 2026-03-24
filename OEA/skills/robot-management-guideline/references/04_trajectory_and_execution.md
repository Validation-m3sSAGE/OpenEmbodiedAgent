# Phase 4: Trajectory Generation and Execution

Once the environment is healthy and drivers are running, you will be tasked with controlling the robot's physical movement.

## 1. Interface Identification
- Determine if the robot is controlled via **ROS** (e.g., publishing to standard geometry topics, Action Clients, MoveIt!) or a specific **Python/C++ SDK**.

## 2. Code Generation
- **Align with Official Demos:** Your code MUST align with the patterns found in the official `demo/` or `examples/` directory (e.g., initialization sequence, heartbeat requirements, control frequency).
- Write a clean, well-commented script defining the robot's trajectory (e.g., waypoints, joint angles, or Cartesian coordinates).
- Ensure the script correctly imports the necessary SDKs or ROS libraries.
- For initial tests, explicitly set velocity and acceleration limits to a low, safe threshold (e.g., 10%-20% of max speed) within the code.

## 3. Execution
- Save the script to the workspace.
- Execute the script using your terminal tool **strictly within the activated virtual environment**.
- **Verify Physical Movement:** Do NOT rely solely on the script's terminal output (e.g., "Command sent successfully") to confirm the robot is actually moving. You MUST design logic to verify physical execution.
  - **Primary Method:** Monitor the robot's real-time pose/joint states via the SDK or ROS topics (e.g., `GetArmStatus()`, `/joint_states`). Compare the current state with the target state over time.
  - **Secondary Methods:** If pose feedback is unavailable or unreliable, consider using other sensors if available (e.g., odometry, vision/camera feedback) to confirm movement.
- Monitor the terminal output for success signals or collision warnings. Update the code if it fails.

## 4. Protection Mode & Recovery (CRITICAL)
When a robot stops responding to commands, do NOT keep sending different commands blindly. Diagnose first:
- **Symptom:** TCP/joint feedback is frozen (identical values across multiple reads), all motion commands are ignored.
- **Cause:** The robot has entered a protection state (collision detection, joint limit violation, or singular configuration).
- **Recovery procedure:**
  1. **Software reset:** `DisableArm()` → wait 1-2s → `EnableArm()` → re-run `EnablePiper()` loop.
  2. **Hardware reset (if software fails):** Ask the user to press the physical reset button or power-cycle the robot.
- **Prevention:** Always monitor `GetArmStatus()` for non-zero error codes after each motion command.

## 5. Iterative Debugging Strategy
When a motion task fails repeatedly, follow this structured approach instead of ad-hoc retries:
1. **Isolate the variable:** Change only ONE parameter per test (e.g., only X, then only Y).
2. **Probe the workspace first:** Before attempting a complex trajectory, run a workspace probing script to map reachable positions.
3. **Confirm spatial direction early:** Before starting any approach sequence, explicitly confirm the target's direction relative to the robot base (forward/backward/left/right) — either by asking the user or using a vision model on a captured image.
4. **Prefer joint space for large motions:** Cartesian space (`EndPoseCtrl`) is prone to limit errors for large or unusual poses. Use joint space (`JointCtrl`) for large sweeping motions, then switch to Cartesian for fine adjustments.
5. **Log every attempt:** Record what was tried and what failed in the robot's SKILL.md Troubleshooting section immediately, not at the end.

## 6. Perception-Control Integration (Eye-in-Hand / Eye-to-Hand)

When a camera is part of the control loop, additional rules apply.

### 6.1 Hand-Eye Calibration Requirements
- Calibration must be done with **sufficient rotational diversity** (≥30° rotation change across poses).
- Use **joint space** to generate pose diversity — Cartesian space rotations are often silently rejected near singularities.
- Always run at least two calibration methods (e.g., TSAI + PARK) and compare their translation vectors. If the difference exceeds 5 mm, the calibration data is suspect.
- **Verify calibration before use:** Command the robot to a known pose, project a known 3D point through the calibration matrix, and check that the projected pixel lands on the expected image location.

### 6.2 Sensor-to-Target Distance Management
- Before running any perception-based task, confirm that the target will be within the sensor's **valid operating range** at the observation pose.
- If the sensor returns all-zero depth or invalid values, the **first diagnostic question** is: "Is the target within the sensor's valid range?" — not a software bug.
- Design the observation pose so the target occupies **at least 5–10% of the image area** for reliable segmentation.

### 6.3 Robust Depth Estimation
- For partially transparent or specular objects, do not use the median depth of the full mask.
  - Use the **10th percentile** of valid depth values (captures the nearest, most reliable surface).
  - Or use a **color-based anchor** (e.g., a colored cap on a transparent bottle) to locate a reliable depth point.
- Always clip depth values to the sensor's valid range before any computation.

### 6.4 Visual Verification at Each Step
After every major robot motion, capture an image and use a vision model to confirm:
- Is the target still in the field of view?
- Is the robot approaching from the correct direction?
- Is there any unexpected obstacle?

Do not proceed to the next step based on coordinate calculations alone.
