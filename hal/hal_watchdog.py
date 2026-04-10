#!/usr/bin/env python3
"""
hal/hal_watchdog.py

HAL Watchdog — polls ACTION.md for commands, dispatches them to the
active driver, and writes updated state back to ENVIRONMENT.md.

Queue-aware version: reads the action queue via ``hal.action_queue``,
marks entries as *running* before execution, then writes *completed* or
*failed* with the result message.  Completed entries are purged after a
configurable number of poll cycles so the LLM can still read the result
before it disappears.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from hal.action_queue import (
    pop_next_pending,
    purge_completed,
    update_action_status,
)
from hal.simulation.scene_io import (
    load_environment_doc,
    load_scene_from_md,
    merge_environment_doc,
    save_environment_doc,
)


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[HAL Watchdog {ts}] {msg}", flush=True)


def load_driver_config(path: Path | None) -> dict[str, object]:
    """Load a driver config JSON object for transparent kwargs passthrough."""
    if path is None:
        return {}
    if not path.exists():
        raise FileNotFoundError(f"driver-config file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"failed to parse driver-config JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"driver-config must be a JSON object: {path}")
    return data


def _load_scene(path: Path) -> dict[str, dict]:
    return load_scene_from_md(path)


def _save_scene(driver, path: Path, scene: dict[str, dict], registry=None) -> None:
    existing = load_environment_doc(path)
    runtime_state = {}
    runtime_getter = getattr(driver, "get_runtime_state", None)
    if callable(runtime_getter):
        runtime_state = runtime_getter() or {}
    updated = merge_environment_doc(
        existing,
        objects=scene,
        robots=runtime_state.get("robots"),
        scene_graph=runtime_state.get("scene_graph"),
        map_data=runtime_state.get("map"),
        tf_data=runtime_state.get("tf"),
        updated_at=datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    )
    save_environment_doc(path, updated)
    if registry is not None and getattr(registry, "is_fleet", False):
        registry.write_robot_index()


def _ensure_connection(driver) -> None:
    connect = getattr(driver, "connect", None)
    is_connected = getattr(driver, "is_connected", None)
    if callable(connect) and callable(is_connected) and not is_connected():
        connect()


def _refresh_health(driver, env_file: Path, registry=None) -> None:
    health_check = getattr(driver, "health_check", None)
    if callable(health_check):
        health_check()
    _save_scene(driver, env_file, driver.get_scene(), registry=registry)


def _install_profile(driver, workspace: Path) -> None:
    """Copy the driver's EMBODIED.md profile into the workspace."""
    src = driver.get_profile_path()
    dst = workspace / "EMBODIED.md"
    if src.exists():
        workspace.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        _log(f"Profile installed: {src.name} -> {dst}")
    else:
        _log(f"WARNING: profile not found at {src}")


def _resolve_watchdog_topology(
    workspace: Path | None,
    driver_name: str,
    robot_id: str | None,
):
    if not robot_id:
        if workspace is None:
            workspace = Path.home() / ".PhyAgentOS" / "workspace"
        return workspace, workspace / "ENVIRONMENT.md", driver_name, None

    from PhyAgentOS.config.loader import load_config
    from PhyAgentOS.embodiment_registry import EmbodimentRegistry

    registry = EmbodimentRegistry(load_config())
    instance = registry.require_instance(robot_id)
    return instance.workspace, registry.resolve_environment_path(robot_id=robot_id), instance.driver, registry


def watch_loop(
    workspace: Path,
    driver_name: str = "simulation",
    gui: bool = False,
    poll_interval: float = 1.0,
    *,
    driver_kwargs: dict[str, object] | None = None,
    env_file: Path | None = None,
    registry=None,
    purge_after_cycles: int = 5,
) -> None:
    """Load a driver, install its profile, then poll ACTION.md forever.

    Parameters
    ----------
    purge_after_cycles:
        Number of poll cycles to keep completed/failed entries in the queue
        before purging them.  This gives the waiting AgentLoop time to read
        the result.  Default is 5 cycles (≈ 5 × poll_interval seconds).
    """
    from hal.drivers import load_driver

    env_file = env_file or (workspace / "ENVIRONMENT.md")

    _log(f"Workspace : {workspace}")
    _log(f"Driver    : {driver_name}")
    _log(f"GUI       : {gui}")
    _log(f"Env File  : {env_file}")
    if driver_kwargs:
        _log(f"DriverCfg : {json.dumps(driver_kwargs, ensure_ascii=False, sort_keys=True)}")

    driver = load_driver(driver_name, gui=gui, **(driver_kwargs or {}))

    with driver:
        _install_profile(driver, workspace)
        _ensure_connection(driver)

        scene = _load_scene(env_file)
        driver.load_scene(scene)
        _refresh_health(driver, env_file, registry=registry)
        _log(f"Scene loaded ({len(scene)} object(s))")
        _log("Watching ACTION.md ... Ctrl+C to stop.\n")

        action_file = workspace / "ACTION.md"
        # Track how many cycles each completed/failed entry has been sitting
        _completed_age: dict[str, int] = {}

        try:
            while True:
                _poll_once(
                    driver,
                    action_file,
                    env_file,
                    registry=registry,
                    completed_age=_completed_age,
                    purge_after_cycles=purge_after_cycles,
                )
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            _log("Shutdown.")


def _poll_once(
    driver,
    action_file: Path,
    env_file: Path,
    *,
    registry=None,
    completed_age: dict[str, int],
    purge_after_cycles: int,
) -> None:
    """Single poll: refresh health, execute one pending action, age completed entries."""
    _refresh_health(driver, env_file, registry=registry)

    # ── age tracking & purge ──────────────────────────────────────────────────
    from hal.action_queue import read_queue
    queue = read_queue(action_file)
    current_ids = {e["action_id"] for e in queue}

    # Remove stale tracking entries for actions no longer in the file
    for aid in list(completed_age.keys()):
        if aid not in current_ids:
            del completed_age[aid]

    # Increment age counter for completed/failed entries
    for entry in queue:
        aid = entry["action_id"]
        if entry.get("status") in ("completed", "failed"):
            completed_age[aid] = completed_age.get(aid, 0) + 1

    # Purge entries that have been sitting long enough
    aged_out = {aid for aid, age in completed_age.items() if age >= purge_after_cycles}
    if aged_out:
        from hal.action_queue import _file_lock, _read_queue_raw, _write_queue_raw
        lock_path = action_file.with_suffix(".lock")
        with _file_lock(lock_path):
            q = _read_queue_raw(action_file)
            q = [e for e in q if e.get("action_id") not in aged_out]
            _write_queue_raw(action_file, q)
        for aid in aged_out:
            del completed_age[aid]
        _log(f"Purged {len(aged_out)} completed/failed action(s) from queue.")

    # ── claim and execute one pending action ──────────────────────────────────
    action = pop_next_pending(action_file)
    if action is None:
        return

    action_id   = action["action_id"]
    action_type = action["action_type"]
    params      = action.get("parameters", {})
    _log(f"Executing action_id={action_id!r}  type={action_type!r}  params={params}")

    time.sleep(0.3)  # brief settle before hardware call

    try:
        result = driver.execute_action(action_type, params)
        _log(f"Result: {result}")
        update_action_status(action_file, action_id, "completed", result_msg=result)
    except Exception as exc:  # noqa: BLE001
        err_msg = f"Driver raised exception: {exc}"
        _log(f"ERROR: {err_msg}")
        update_action_status(action_file, action_id, "failed", result_msg=err_msg)

    _save_scene(driver, env_file, driver.get_scene(), registry=registry)
    _log("ENVIRONMENT.md updated.\n")


def main() -> None:
    from hal.drivers import list_drivers

    parser = argparse.ArgumentParser(
        description="HAL Watchdog - Physical Agent Operating System hardware layer",
    )
    parser.add_argument(
        "--driver",
        default="simulation",
        help=f"Driver name (available: {', '.join(list_drivers())})",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="Workspace directory (single mode only; fleet mode prefers --robot-id)",
    )
    parser.add_argument("--robot-id", default=None, help="Robot instance id in fleet mode")
    parser.add_argument("--gui", action="store_true", help="Open 3-D viewer")
    parser.add_argument(
        "--interval", type=float, default=1.0, help="Poll interval (seconds)",
    )
    parser.add_argument(
        "--driver-config",
        default=None,
        help="Path to a JSON object file that will be passed through to the selected driver as keyword args.",
    )
    parser.add_argument(
        "--purge-after",
        type=int,
        default=5,
        help="Number of poll cycles to keep completed/failed entries before purging (default: 5).",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve() if args.workspace else None
    driver_config_path = Path(args.driver_config).expanduser().resolve() if args.driver_config else None
    try:
        driver_kwargs = load_driver_config(driver_config_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    robot_workspace, env_file, resolved_driver, registry = _resolve_watchdog_topology(
        workspace,
        args.driver,
        args.robot_id,
    )

    if not robot_workspace.exists():
        print(f"Error: workspace not found: {robot_workspace}", file=sys.stderr)
        print("Run 'paos onboard' first.", file=sys.stderr)
        sys.exit(1)

    watch_loop(
        robot_workspace,
        driver_name=resolved_driver,
        gui=args.gui,
        poll_interval=args.interval,
        driver_kwargs=driver_kwargs,
        env_file=env_file,
        registry=registry,
        purge_after_cycles=args.purge_after,
    )


if __name__ == "__main__":
    main()
