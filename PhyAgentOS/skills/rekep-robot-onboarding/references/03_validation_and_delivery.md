# Validation And Delivery

## Safe Validation Checklist

Before finishing:

1. Run syntax checks on touched Python files.
2. Run factory or import smoke tests if the repo already has them.
3. Prefer `preflight` and dry-run execution over real hardware motion.
4. Call out missing runtime dependencies instead of pretending verification succeeded.

## ReKep Validation Pattern

Typical commands to adapt for the new robot:

```bash
python runtime/dobot_bridge.py preflight \
  --robot_family <robot_slug> \
  --robot_driver <driver_name> \
  --robot_host <host> \
  --robot_port <port> \
  --pretty
```

```bash
python runtime/dobot_bridge.py execute \
  --robot_family <robot_slug> \
  --robot_driver <driver_name> \
  --robot_host <host> \
  --robot_port <port> \
  --instruction "执行一个小幅安全动作进行连通性验证" \
  --pretty
```

```bash
python hal/hal_watchdog.py --driver rekep_real --workspace ~/.PhyAgentOS/workspace
```

## Final Response Checklist

Report:

- Which repo path was edited
- Where the SDK should live
- Which files changed
- What was verified
- Exact deployment, startup, and `ACTION.md` usage commands
