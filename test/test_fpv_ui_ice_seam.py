#!/usr/bin/env python3

import ast
from pathlib import Path


CORE_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = CORE_ROOT / "swarm_control_core" / "swarm_fpv_ui.py"


def _extract_functions(names):
    tree = ast.parse(UI_PATH.read_text(encoding="utf-8"))
    wanted = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            wanted[node.name] = node
    assert set(wanted) == set(names), f"missing functions: {set(names) - set(wanted)}"
    return wanted


def _load_resolver():
    funcs = _extract_functions(
        ["_normalize_webrtc_ice_transport_policy", "_resolve_distribution_webrtc_ice_config"]
    )
    module = ast.Module(body=list(funcs.values()), type_ignores=[])
    from typing import Any, Optional, Tuple

    namespace = {"Any": Any, "Optional": Optional, "Tuple": Tuple}
    exec(compile(ast.fix_missing_locations(module), str(UI_PATH), "exec"), namespace)
    return namespace["_resolve_distribution_webrtc_ice_config"]


def test_resolver_defaults_keep_community_lockdown():
    resolve = _load_resolver()

    assert resolve(None, None) == ("[]", "all")
    assert resolve("", "") == ("[]", "all")
    assert resolve("   ", "bogus") == ("[]", "all")


def test_resolver_passes_distribution_overrides_through():
    resolve = _load_resolver()

    ice_json = '[{"urls":"turn:relay.example.net:3478","username":"u","credential":"p"}]'
    assert resolve(ice_json, "relay") == (ice_json, "relay")
    assert resolve(ice_json, "ALL") == (ice_json, "all")


def test_run_server_and_main_expose_the_ice_seam():
    funcs = _extract_functions(["_run_server", "main"])

    for name in ("_run_server", "main"):
        arg_names = [a.arg for a in funcs[name].args.args]
        assert "webrtc_ice_servers_json" in arg_names
        assert "webrtc_ice_transport_policy" in arg_names
        # Both must stay optional so the community CLI keeps calling with no args.
        assert len(funcs[name].args.defaults) >= 2


def test_community_entrypoint_never_reads_ice_env_vars():
    funcs = _extract_functions(["_run_server", "_resolve_distribution_webrtc_ice_config"])

    for name, node in funcs.items():
        source_segment = ast.unparse(node)
        assert "SWARM_CORE_WEBRTC_ICE_SERVERS_JSON" not in source_segment, (
            f"{name} must not read ICE env vars; the community guardrail requires the "
            "explicit main() code seam"
        )
        assert "SWARM_CORE_WEBRTC_ICE_TRANSPORT_POLICY" not in source_segment
