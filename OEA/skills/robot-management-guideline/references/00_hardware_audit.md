# Phase 0: Hardware Audit

**This phase must be completed before writing any code.**
A single overlooked hardware parameter can waste hours of debugging.

## 0.1 Mandatory Information Checklist

Before writing any script, you must be able to answer every question below.
If you cannot answer a question, **stop and find the answer first** — from the datasheet, the user, or a quick physical test.

### Mechanical
- [ ] What is the robot's **maximum reach / workspace radius**?
- [ ] What are the **joint angle limits** for each axis?
- [ ] Are there any **known mechanical offsets or zero-point deviations** (e.g., a joint whose physical zero does not match the encoder zero)?
- [ ] What is the **mounting configuration** (floor, ceiling, wall, mobile base)?

### Sensors & Cameras
- [ ] What is the **valid measurement range** of each sensor?
  - Depth cameras: minimum and maximum depth (e.g., D405: **7–53 cm**, D435i: 20–300 cm)
  - Force/torque sensors: rated range and overload limit
- [ ] Where is each sensor **physically mounted** relative to the end-effector? (Eye-in-hand vs. eye-to-hand)
- [ ] Does the sensor have **known failure modes** for the target object type?
  - Transparent objects → depth cameras return 0 or noise
  - Specular surfaces → structured-light sensors fail
  - Dark objects → time-of-flight sensors may underperform

### Communication & Control
- [ ] What is the **communication interface**? (CAN, USB, Ethernet, ROS topics)
- [ ] What is the **required control frequency**? (e.g., Piper requires ~100 Hz continuous streaming)
- [ ] Does the SDK require a **continuous heartbeat**, or is single-shot command sufficient?
- [ ] What **firmware version** is installed, and does it affect API behavior?

### Coordinate Systems
- [ ] What are the **positive directions** of X, Y, Z in the robot base frame?
  - **Do not assume.** Verify with a physical test: command +50 mm in X and observe which direction the robot moves.
- [ ] What is the **TCP pose at the zero/home position**?
- [ ] If a camera is mounted on the end-effector, what is the **camera's viewing direction** at the home pose?

## 0.2 Hardware Offset Handling Rule

Any hardware deviation (joint zero offset, sensor mounting angle, TCP offset) must be handled **at the lowest layer** — in the robot utility class constructor, not scattered across individual scripts.

```
✅ PiperRobot(j6_offset_deg=-60)  →  all motion commands auto-compensate
❌ Manually adding -60° in every script  →  inconsistent, error-prone
```

## 0.3 Coordinate System Verification Protocol

If you are uncertain about the coordinate system directions, run this test **before any other motion**:

1. Move the robot to a known safe home pose.
2. Command +50 mm in X only. Observe and record which physical direction moved.
3. Command +50 mm in Y only. Observe and record.
4. Command +50 mm in Z only. Observe and record.
5. Document the result in the robot's SKILL.md.

This 3-step test takes under 5 minutes and prevents hours of misdirected searching.

## 0.4 Sensor Validation Protocol

Before relying on any sensor for closed-loop control:

1. Place a known object at a known distance.
2. Read the sensor output and compare with ground truth.
3. Test at the **minimum** and **maximum** of the expected operating range.
4. If the sensor returns 0 or invalid values, diagnose the cause before proceeding:
   - Is the object within the sensor's valid range?
   - Is the object material compatible with the sensor technology?
   - Is the sensor properly initialized and aligned?
