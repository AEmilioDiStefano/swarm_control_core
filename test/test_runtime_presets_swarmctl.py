#!/usr/bin/env python3

from swarm_control_core.runtime_presets import (
    json_env,
    list_preset_names,
    pro_env_aliases,
    resolve_preset,
    shell_exports,
)
from swarm_control_core.swarmctl import build_parser, main


def test_runtime_presets_include_target_architecture_modes():
    names = set(list_preset_names())

    assert {"local_lab", "large_fleet"} <= names
    assert "cloudflare_remote" not in names
    assert "field_gateway" not in names
    assert "direct_robot_agent" not in names
    assert resolve_preset("large")["SWARM_CORE_GATEWAY_ROUTE_TYPE"] == "local_gateway"
    assert resolve_preset("large")["SWARM_CORE_AUTH_MODE"] == "off"


def test_runtime_preset_export_helpers_emit_core_and_pro_aliases():
    env = resolve_preset("large_fleet", overrides={"SWARM_CORE_GATEWAY_ID": "local-hub-01"})

    assert "export SWARM_CORE_GATEWAY_ID='local-hub-01'" in shell_exports(env)
    assert "SWARM_FPV_GATEWAY_ID" in pro_env_aliases(env)
    assert '"SWARM_CORE_GATEWAY_ID": "local-hub-01"' in json_env(env)


def test_swarmctl_parser_exposes_simplified_commands():
    parser = build_parser()

    assert parser.parse_args(["presets"]).command == "presets"
    assert parser.parse_args(["env", "local_lab"]).preset == "local_lab"
    assert parser.parse_args(["env", "large"]).preset == "large"
    assert parser.parse_args(["ui", "--preset", "large_fleet"]).preset == "large_fleet"
    assert parser.parse_args(["robot", "--skip-camera-profile"]).skip_camera_profile is True


def test_swarmctl_env_prints_exports(capsys):
    rc = main(["env", "large_fleet", "--gateway-id", "local-hub-01"])

    assert rc == 0
    out = capsys.readouterr().out
    assert "SWARM_CORE_GATEWAY_ROUTE_TYPE='local_gateway'" in out
    assert "SWARM_CORE_GATEWAY_ID='local-hub-01'" in out
