#!/usr/bin/env python3
"""
Unified command facade for Swarm Control quickstart workflows.

The historical shell scripts remain supported. This CLI centralizes presets
and delegates to those scripts so current docs and user workflows keep working.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .runtime_presets import (
    apply_env_to_mapping,
    json_env,
    list_preset_choices,
    list_preset_names,
    resolve_preset,
    shell_exports,
)


def _candidate_source_dirs() -> list[Path]:
    here = Path(__file__).resolve()
    candidates = [
        Path(os.environ.get("SC", "")),
        Path(os.environ.get("SWARM_CORE_SOURCE_DIR", "")),
        Path.cwd() / "swarm_control_core",
        Path.cwd() / "src" / "swarm_control_core",
        here.parents[1] if len(here.parents) > 1 else Path(),
        here.parents[2] / "src" / "swarm_control_core" if len(here.parents) > 2 else Path(),
    ]
    return [path for path in candidates if str(path) and (path / "scripts").is_dir()]


def _source_dir() -> Path:
    candidates = _candidate_source_dirs()
    if candidates:
        return candidates[0]
    raise SystemExit(
        "Could not locate swarm_control_core source scripts. "
        "Set SC or SWARM_CORE_SOURCE_DIR to <workspace>/src/swarm_control_core."
    )


def _script(name: str) -> str:
    path = _source_dir() / "scripts" / name
    if not path.exists():
        raise SystemExit(f"Missing script: {path}")
    return str(path)


def _env_for_preset(args: argparse.Namespace) -> dict[str, str]:
    env = dict(os.environ)
    preset_env = resolve_preset(args.preset)
    apply_env_to_mapping(preset_env, env)
    if getattr(args, "gateway_id", ""):
        env["SWARM_CORE_GATEWAY_ID"] = str(args.gateway_id)
    if getattr(args, "gateway_name", ""):
        env["SWARM_CORE_GATEWAY_NAME"] = str(args.gateway_name)
    if getattr(args, "hub_url", ""):
        env["SWARM_CORE_HUB_URL"] = str(args.hub_url)
    return env


def cmd_presets(_args: argparse.Namespace) -> int:
    for name in list_preset_names():
        print(name)
    return 0


def cmd_env(args: argparse.Namespace) -> int:
    env = resolve_preset(args.preset)
    if args.gateway_id:
        env["SWARM_CORE_GATEWAY_ID"] = args.gateway_id
    if args.gateway_name:
        env["SWARM_CORE_GATEWAY_NAME"] = args.gateway_name
    if args.hub_url:
        env["SWARM_CORE_HUB_URL"] = args.hub_url
    if args.format == "json":
        print(json_env(env, include_pro_aliases=args.pro_aliases))
    else:
        print(shell_exports(env, include_pro_aliases=args.pro_aliases))
    return 0


def _run(cmd: Sequence[str], env: dict[str, str]) -> int:
    return subprocess.call(list(cmd), env=env)


def cmd_ui(args: argparse.Namespace) -> int:
    env = _env_for_preset(args)
    cmd = [_script("swarm_core_quickstart_step3.sh"), "--domain-id", str(args.domain_id)]
    if args.balanced_fleet:
        cmd.append("--balanced-fleet")
    if args.switch_heavy:
        cmd.append("--switch-heavy")
    if args.allow_lan_bind:
        cmd.append("--allow-lan-bind")
    return _run(cmd, env)


def cmd_robot(args: argparse.Namespace) -> int:
    env = _env_for_preset(args)
    cmd = [_script("swarm_core_quickstart_step2.sh"), "--domain-id", str(args.domain_id)]
    if args.robot_name:
        cmd.extend(["--robot-name", str(args.robot_name)])
    if args.skip_camera_profile:
        cmd.append("--skip-camera-profile")
    return _run(cmd, env)


def cmd_setup(args: argparse.Namespace) -> int:
    env = _env_for_preset(args)
    role = str(args.role)
    step0 = [_script("swarm_core_quickstart_step0.sh"), "--machine-role", role, "--domain-id", str(args.domain_id)]
    step1 = [_script("swarm_core_quickstart_step1.sh"), "--machine-role", role, "--domain-id", str(args.domain_id)]
    first = _run(step0, env)
    if first != 0:
        return first
    return _run(step1, env)


def cmd_register(args: argparse.Namespace) -> int:
    cmd = ["ros2", "run", "swarm_control_core", "sync_robot_entries_core", "--workspace", str(args.workspace)]
    for source in args.source:
        cmd.extend(["--source", source])
    return _run(cmd, dict(os.environ))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Swarm Control unified quickstart facade.")
    sub = parser.add_subparsers(dest="command", required=True)
    preset_choices = list_preset_choices()

    presets = sub.add_parser("presets", help="List available runtime presets.")
    presets.set_defaults(func=cmd_presets)

    env_cmd = sub.add_parser("env", help="Print shell exports for a preset.")
    env_cmd.add_argument("preset", choices=preset_choices)
    env_cmd.add_argument("--format", choices=("shell", "json"), default="shell")
    env_cmd.add_argument("--pro-aliases", action="store_true", help="Also emit SWARM_FPV_* aliases.")
    env_cmd.add_argument("--gateway-id", default="")
    env_cmd.add_argument("--gateway-name", default="")
    env_cmd.add_argument("--hub-url", default="")
    env_cmd.set_defaults(func=cmd_env)

    setup = sub.add_parser("setup", help="Run dependency/build setup via existing quickstart scripts.")
    setup.add_argument("--role", choices=("control", "robot"), required=True)
    setup.add_argument("--preset", choices=preset_choices, default="local_lab")
    setup.add_argument("--domain-id", default="17")
    setup.add_argument("--gateway-id", default="")
    setup.add_argument("--gateway-name", default="")
    setup.add_argument("--hub-url", default="")
    setup.set_defaults(func=cmd_setup)

    ui = sub.add_parser("ui", help="Launch the control-machine UI.")
    ui.add_argument("--preset", choices=preset_choices, default="local_lab")
    ui.add_argument("--domain-id", default="17")
    ui.add_argument("--balanced-fleet", action="store_true")
    ui.add_argument("--switch-heavy", action="store_true")
    ui.add_argument("--allow-lan-bind", action="store_true")
    ui.add_argument("--gateway-id", default="")
    ui.add_argument("--gateway-name", default="")
    ui.add_argument("--hub-url", default="")
    ui.set_defaults(func=cmd_ui)

    robot = sub.add_parser("robot", help="Prepare and launch a robot.")
    robot.add_argument("--preset", choices=preset_choices, default="local_lab")
    robot.add_argument("--domain-id", default="17")
    robot.add_argument("--robot-name", default="")
    robot.add_argument("--skip-camera-profile", action="store_true")
    robot.add_argument("--gateway-id", default="")
    robot.add_argument("--gateway-name", default="")
    robot.add_argument("--hub-url", default="")
    robot.set_defaults(func=cmd_robot)

    register = sub.add_parser("register", help="Register robots on the control machine.")
    register.add_argument("--workspace", default=os.environ.get("WS", str(Path.cwd())))
    register.add_argument("--source", action="append", default=[], required=True)
    register.set_defaults(func=cmd_register)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
