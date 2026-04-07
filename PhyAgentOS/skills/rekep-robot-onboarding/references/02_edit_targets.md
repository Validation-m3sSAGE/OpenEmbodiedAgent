# Edit Targets

## Required Plugin Files

Touch the minimum set needed for the new robot:

- `runtime/<robot_slug>_adapter.py` or `runtime/cellbot_adapter.py`
- `runtime/robot_factory.py`
- `runtime/docs/robot_adaptation.md`
- `runtime/docs/robot_adaptation_zh.md`

## Frequently Needed Plugin Updates

Update these when the new SDK changes setup or invocation:

- `README.md`
- `README_zh.md`
- `runtime/README.md`
- `tests/test_rekep_robot_factory.py`

## Main Repo Entry Points

If you are introducing or documenting this workflow in PhyAgentOS itself, keep changes limited to:

- `README.md`
- `README_zh.md`
- `PhyAgentOS/skills/README.md`
- `docs/user_development_guide/PLUGIN_DEVELOPMENT_GUIDE.md`
- `docs/user_development_guide/PLUGIN_DEVELOPMENT_GUIDE_zh.md`

## Adapter Design Guidance

Prefer this split:

- Adapter file: robot SDK session lifecycle, action mapping, runtime state
- `robot_factory.py`: family registration and constructor wiring
- Docs: SDK placement, dependency install, preflight, dry-run, real execution, HAL startup

The adapter should support dry-run first. Real motion should stay behind an explicit flag such as `execute_motion=True`.
