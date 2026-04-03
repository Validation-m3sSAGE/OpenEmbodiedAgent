#!/usr/bin/env python3
"""Install or update the external ReKep real-world plugin for PhyAgentOS."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hal.plugins import get_plugin_repo_path, get_registry_path, read_plugin_manifest, register_plugin


def _run_checked(argv: list[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()
        raise RuntimeError(f"Command failed: {' '.join(argv)}\n{detail}")
    return proc.stdout.strip()


def _resolve_default_source() -> str:
    from_env = os.environ.get("PhyAgentOS_REKEP_REAL_PLUGIN_REPO", "").strip()
    if from_env:
        return from_env
    sibling = (REPO_ROOT.parent / "PhyAgentOS-rekep-real-plugin").resolve()
    if sibling.exists():
        return str(sibling)
    return ""


def _checkout_ref(dest: Path, ref: str) -> None:
    if ref.strip():
        _run_checked(["git", "checkout", ref], cwd=dest)


def _clone_or_sync_repo(source: str, dest: Path, ref: str, force: bool) -> Path:
    source_path = Path(source).expanduser()
    is_local_path = source_path.exists()
    source_is_git_repo = is_local_path and (source_path / ".git").exists()

    if force and dest.exists():
        shutil.rmtree(dest)

    if is_local_path and not source_is_git_repo:
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(source_path.resolve(), dest)
        return dest

    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        _run_checked(["git", "clone", source, str(dest)])
        _checkout_ref(dest, ref)
        return dest

    if (dest / ".git").exists():
        _run_checked(["git", "fetch", "--all", "--tags"], cwd=dest)
        _checkout_ref(dest, ref)
        if not ref.strip():
            _run_checked(["git", "pull", "--ff-only"], cwd=dest)
        return dest

    raise RuntimeError(
        f"Destination already exists but is not a git checkout: {dest}. "
        "Use --force to replace it."
    )


def _iter_requirement_files(manifest: dict, include_optional: bool) -> list[Path]:
    entries = manifest.get("requirements", [])
    if not isinstance(entries, list):
        return []
    paths: list[Path] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if bool(entry.get("optional", False)) and not include_optional:
            continue
        raw_path = str(entry.get("path", "")).strip()
        if raw_path:
            paths.append(Path(raw_path))
    return paths


def _install_requirements(repo_path: Path, manifest: dict, python_bin: str, with_solver: bool) -> None:
    for rel_path in _iter_requirement_files(manifest, include_optional=with_solver):
        req_path = repo_path / rel_path
        if not req_path.exists():
            raise FileNotFoundError(f"Requirement file not found: {req_path}")
        _run_checked([python_bin, "-m", "pip", "install", "-r", str(req_path)], cwd=repo_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Clone/copy the ReKep real plugin repo and register it with PhyAgentOS.",
    )
    parser.add_argument(
        "--repo-url",
        default="",
        help=(
            "Plugin git URL or local path. "
            "Defaults to $PhyAgentOS_REKEP_REAL_PLUGIN_REPO or ../PhyAgentOS-rekep-real-plugin when available."
        ),
    )
    parser.add_argument("--ref", default="", help="Optional git branch/tag/commit to checkout.")
    parser.add_argument("--python", default=sys.executable, help="Python used for pip installs.")
    parser.add_argument("--no-install-deps", action="store_true", help="Register the plugin only.")
    parser.add_argument(
        "--with-solver",
        action="store_true",
        help="Also install optional solver dependencies listed in the plugin manifest.",
    )
    parser.add_argument("--force", action="store_true", help="Replace any existing local checkout.")
    args = parser.parse_args()

    source = args.repo_url.strip() or _resolve_default_source()
    if not source:
        parser.error(
            "No plugin source available. Pass --repo-url, set PhyAgentOS_REKEP_REAL_PLUGIN_REPO, or place the plugin repo next to PhyAgentOS."
        )

    plugin_dest = get_plugin_repo_path("rekep_real")
    repo_path = _clone_or_sync_repo(source, plugin_dest, args.ref.strip(), args.force)
    manifest = read_plugin_manifest(repo_path)

    if not args.no_install_deps:
        _install_requirements(repo_path, manifest, args.python, with_solver=args.with_solver)

    spec = register_plugin(repo_path, source_url=source, ref=args.ref.strip())

    print(f"Plugin source : {repo_path}")
    print(f"Driver       : {spec.driver_name}")
    print(f"Registry     : {get_registry_path()}")
    if args.no_install_deps:
        print("Dependencies : skipped")
    else:
        print(f"Dependencies : installed with {args.python}")
        if args.with_solver:
            print("Solver deps  : installed")
    print("Next step    : python hal/hal_watchdog.py --driver rekep_real")


if __name__ == "__main__":
    main()
