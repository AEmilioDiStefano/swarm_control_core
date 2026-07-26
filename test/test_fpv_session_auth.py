#!/usr/bin/env python3

"""Session auth (ADR-0010): hashing, tokens, store, fail-closed seam tests."""

import ast
import os
from pathlib import Path

import pytest

from swarm_control_core.fpv_auth_models import (
    AuthConfig,
    SWARM_SCOPE_CONTROL,
    SWARM_SCOPE_READ,
)
from swarm_control_core.fpv_auth_service import SessionAuthService, build_auth_service
from swarm_control_core.fpv_session_auth import (
    SessionAuthError,
    hash_password,
    load_operator_store,
    load_or_create_session_secret,
    main as operator_admin_main,
    mint_session_token,
    save_operator_store,
    verify_password,
    verify_session_token,
)

CORE_ROOT = Path(__file__).resolve().parents[1]
UI_PATH = CORE_ROOT / "swarm_control_core" / "swarm_fpv_ui.py"


class FakeRequest:
    def __init__(self, headers=None, query=None):
        self.headers = headers or {}
        self.query = query or {}


def _bearer(token: str) -> FakeRequest:
    return FakeRequest(headers={"Authorization": f"Bearer {token}"})


def _write_store(tmp_path, monkeypatch=None, scopes=None) -> str:
    store_path = str(tmp_path / "operators.json")
    env = os.environ.copy()
    env_var = "TEST_OPERATOR_PASSWORD"
    os.environ[env_var] = "correct horse battery staple"
    try:
        args = ["add", "operator1", "--file", store_path, "--password-env", env_var]
        if scopes:
            args += ["--scopes", scopes]
        assert operator_admin_main(args) == 0
    finally:
        os.environ.pop(env_var, None)
        os.environ.update({k: v for k, v in env.items() if k == env_var})
    return store_path


def test_password_hash_roundtrip_and_rejects():
    stored = hash_password("hunter22")
    assert stored.startswith("scrypt$")
    assert verify_password("hunter22", stored)
    assert not verify_password("hunter23", stored)
    assert not verify_password("hunter22", "not-a-hash")
    assert not verify_password("hunter22", "")
    with pytest.raises(SessionAuthError):
        hash_password("")


def test_token_mint_verify_and_tamper_rejection():
    secret = b"s" * 32
    token = mint_session_token(
        secret,
        subject="op_1",
        display_name="Operator One",
        roles=["operator"],
        scopes=[SWARM_SCOPE_READ, SWARM_SCOPE_CONTROL],
        tenant_id="pro",
        session_id="sess_1",
        ttl_s=3600,
        now=1000.0,
    )
    claims = verify_session_token(secret, token, now=1500.0)
    assert claims["sub"] == "op_1"
    assert claims["session_id"] == "sess_1"
    assert SWARM_SCOPE_CONTROL in claims["scopes"]

    # Expired
    with pytest.raises(SessionAuthError, match="expired"):
        verify_session_token(secret, token, now=1000.0 + 3601.0)
    # Wrong secret
    with pytest.raises(SessionAuthError, match="signature"):
        verify_session_token(b"x" * 32, token, now=1500.0)
    # Tampered payload (scope escalation attempt)
    prefix, payload, mac = token.split(".")
    with pytest.raises(SessionAuthError):
        verify_session_token(secret, f"{prefix}.{payload}x.{mac}", now=1500.0)
    # Foreign formats (the old forgeable dev pipe token must not verify)
    for bad in ("", "dev|x|x|r|s|t|sid", "devjson.e30", "swst1.only-two-parts"):
        with pytest.raises(SessionAuthError):
            verify_session_token(secret, bad, now=1500.0)


def test_operator_store_loads_and_fails_closed(tmp_path):
    store_path = _write_store(tmp_path)
    operators = load_operator_store(store_path)
    assert operators["operator1"].subject == "operator1"
    assert SWARM_SCOPE_CONTROL in operators["operator1"].scopes
    assert (os.stat(store_path).st_mode & 0o777) == 0o600

    # Group/other-readable store is refused
    os.chmod(store_path, 0o644)
    with pytest.raises(SessionAuthError, match="chmod 600"):
        load_operator_store(store_path)
    os.chmod(store_path, 0o600)

    # Missing file
    with pytest.raises(SessionAuthError, match="not found"):
        load_operator_store(str(tmp_path / "absent.json"))

    # Empty operator list
    empty = tmp_path / "empty.json"
    empty.write_text('{"version": 1, "operators": []}')
    os.chmod(empty, 0o600)
    with pytest.raises(SessionAuthError, match="no operators"):
        load_operator_store(str(empty))

    # Unknown version
    bad_version = tmp_path / "v2.json"
    bad_version.write_text('{"version": 2, "operators": [{"username": "x"}]}')
    os.chmod(bad_version, 0o600)
    with pytest.raises(SessionAuthError, match="version"):
        load_operator_store(str(bad_version))

    # Plaintext password instead of a hash is refused
    plain = tmp_path / "plain.json"
    plain.write_text(
        '{"version": 1, "operators": [{"username": "x", "password_hash": "plaintext"}]}'
    )
    os.chmod(plain, 0o600)
    with pytest.raises(SessionAuthError, match="scrypt"):
        load_operator_store(str(plain))


def test_operator_admin_cli_lifecycle(tmp_path):
    store_path = _write_store(tmp_path, scopes=SWARM_SCOPE_READ)
    operators = load_operator_store(store_path)
    assert operators["operator1"].scopes == (SWARM_SCOPE_READ,)

    os.environ["TEST_OPERATOR_PASSWORD"] = "next password 9"
    try:
        assert operator_admin_main(
            ["set-password", "operator1", "--file", store_path, "--password-env", "TEST_OPERATOR_PASSWORD"]
        ) == 0
        operators = load_operator_store(store_path)
        assert verify_password("next password 9", operators["operator1"].password_hash)
        # Scopes survive password rotation
        assert operators["operator1"].scopes == (SWARM_SCOPE_READ,)
        assert operator_admin_main(["remove", "operator1", "--file", store_path]) == 0
        with pytest.raises(SessionAuthError, match="no operators"):
            load_operator_store(store_path)
        # Unknown operator fails loudly
        assert operator_admin_main(
            ["set-password", "ghost", "--file", store_path, "--password-env", "TEST_OPERATOR_PASSWORD"]
        ) == 1
    finally:
        os.environ.pop("TEST_OPERATOR_PASSWORD", None)


def test_session_secret_create_and_reload(tmp_path):
    secret_path = str(tmp_path / "secret")
    first = load_or_create_session_secret(secret_path)
    assert len(first) >= 32
    assert (os.stat(secret_path).st_mode & 0o777) == 0o600
    assert load_or_create_session_secret(secret_path) == first

    Path(secret_path).write_text("dG9vc2hvcnQ")
    with pytest.raises(SessionAuthError, match="too short"):
        load_or_create_session_secret(secret_path)


def _session_service(secret=b"k" * 32, allow_anon=False) -> SessionAuthService:
    config = AuthConfig(mode="session", allow_readonly_anonymous=allow_anon)
    return build_auth_service(config, session_secret=secret)


def test_session_service_denies_without_token_and_enforces_scopes():
    service = _session_service()
    denied = service.authorize_http(FakeRequest(), required_scope=SWARM_SCOPE_READ)
    assert not denied.ok and denied.http_status == 401

    secret = b"k" * 32
    readonly_token = mint_session_token(
        secret,
        subject="viewer",
        display_name="Viewer",
        roles=["viewer"],
        scopes=[SWARM_SCOPE_READ],
        tenant_id="pro",
        session_id="sess_ro",
    )
    read = service.authorize_http(_bearer(readonly_token), required_scope=SWARM_SCOPE_READ)
    assert read.ok and read.principal.subject == "viewer"
    # A read-only operator demonstrably cannot obtain control scope
    control = service.authorize_http(_bearer(readonly_token), required_scope=SWARM_SCOPE_CONTROL)
    assert not control.ok and control.http_status == 403

    # Forged/tampered tokens deny 401
    tampered = readonly_token[:-2] + "aa"
    bad = service.authorize_http(_bearer(tampered), required_scope=SWARM_SCOPE_READ)
    assert not bad.ok and bad.http_status == 401


def test_session_service_anonymous_readonly_is_explicit_and_read_only():
    service = _session_service(allow_anon=True)
    read = service.authorize_http(FakeRequest(), required_scope=SWARM_SCOPE_READ)
    assert read.ok and read.principal.subject == "anonymous"
    control = service.authorize_http(FakeRequest(), required_scope=SWARM_SCOPE_CONTROL)
    assert not control.ok and control.http_status == 401


def test_session_service_fails_closed_when_verifier_unavailable(monkeypatch):
    # Misconfigured build: no secret cannot construct a session service
    with pytest.raises(ValueError, match="session secret"):
        build_auth_service(AuthConfig(mode="session"), session_secret=b"")

    # Defensive runtime path: empty secret denies 503, never anonymous
    service = SessionAuthService(AuthConfig(mode="session"), session_secret=b"")
    denied = service.authorize_http(FakeRequest(), required_scope=SWARM_SCOPE_READ)
    assert not denied.ok and denied.http_status == 503

    # The unsafe weak-auth override must not weaken session auth
    monkeypatch.setenv("SWARM_CORE_UNSAFE_ALLOW_WEAK_AUTH_NON_LOOPBACK", "1")
    strict = _session_service()
    denied = strict.authorize_http(FakeRequest(), required_scope=SWARM_SCOPE_READ)
    assert not denied.ok and denied.http_status == 401


def test_store_roundtrip_preserves_records(tmp_path):
    store_path = str(tmp_path / "ops.json")
    os.environ["TEST_OPERATOR_PASSWORD"] = "pw one"
    try:
        assert operator_admin_main(
            ["add", "alpha", "--file", store_path, "--password-env", "TEST_OPERATOR_PASSWORD",
             "--display-name", "Alpha One", "--roles", "operator,lead", "--tenant-id", "siteA"]
        ) == 0
    finally:
        os.environ.pop("TEST_OPERATOR_PASSWORD", None)
    loaded = load_operator_store(store_path)
    save_operator_store(store_path, loaded)
    reloaded = load_operator_store(store_path)
    assert reloaded == loaded
    assert reloaded["alpha"].display_name == "Alpha One"
    assert reloaded["alpha"].roles == ("operator", "lead")
    assert reloaded["alpha"].tenant_id == "siteA"


# --- Distribution seam guardrails (mirrors test_fpv_ui_ice_seam.py) ---


def _extract_functions(names):
    tree = ast.parse(UI_PATH.read_text(encoding="utf-8"))
    wanted = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            wanted[node.name] = node
    assert set(wanted) == set(names), f"missing functions: {set(names) - set(wanted)}"
    return wanted


def test_run_server_and_main_expose_the_session_auth_seam():
    funcs = _extract_functions(["_run_server", "main"])
    for name in ("_run_server", "main"):
        arg_names = [a.arg for a in funcs[name].args.args]
        assert "distribution_session_auth" in arg_names
        # Must stay optional so the community CLI keeps calling with no args.
        assert len(funcs[name].args.defaults) == len(arg_names)


def test_session_auth_resolver_never_reads_env():
    funcs = _extract_functions(["_resolve_distribution_session_auth"])
    source_segment = ast.unparse(funcs["_resolve_distribution_session_auth"])
    assert "os.environ" not in source_segment, (
        "the session auth seam must be env-locked: community processes must not "
        "be able to enable session mode via environment variables"
    )
    assert "SWARM_CORE_AUTH_MODE" not in source_segment


def test_community_env_cannot_enable_session_mode():
    funcs = _extract_functions(["_run_server"])
    source_segment = ast.unparse(funcs["_run_server"])
    # The env-provided auth_mode must still be forced to off for any
    # unsupported mode whenever the distribution seam is absent.
    assert "session_auth_runtime is not None" in source_segment
    assert "Forcing auth_mode=off" in source_segment


def test_resolver_fails_closed_on_misconfigured_store(tmp_path):
    funcs = _extract_functions(["_resolve_distribution_session_auth"])
    module = ast.Module(body=list(funcs.values()), type_ignores=[])
    from typing import Any, Dict, Mapping, Optional

    from swarm_control_core.fpv_session_auth import DEFAULT_SESSION_TTL_S

    namespace = {
        "Any": Any,
        "Dict": Dict,
        "Mapping": Mapping,
        "Optional": Optional,
        "AUTH_MODE_SESSION": "session",
        "DEFAULT_SESSION_TTL_S": DEFAULT_SESSION_TTL_S,
        "SessionAuthError": SessionAuthError,
        "load_operator_store": load_operator_store,
        "load_or_create_session_secret": load_or_create_session_secret,
    }
    exec(compile(ast.fix_missing_locations(module), str(UI_PATH), "exec"), namespace)
    resolve = namespace["_resolve_distribution_session_auth"]

    # Community CLI: no seam argument -> no session auth
    assert resolve(None) is None

    secret_file = str(tmp_path / "secret")

    # Missing operators file refuses startup with a named remedy
    with pytest.raises(RuntimeError, match="misconfigured"):
        resolve(
            {
                "mode": "session",
                "operators_file": str(tmp_path / "absent.json"),
                "secret_file": secret_file,
            }
        )

    # Missing paths refuse startup
    with pytest.raises(RuntimeError, match="operators_file"):
        resolve({"mode": "session"})

    # Non-session modes are rejected outright
    with pytest.raises(RuntimeError, match="session"):
        resolve({"mode": "dev", "operators_file": "x", "secret_file": "y"})

    # A valid store resolves with fail-closed anonymous default
    store_path = _write_store(tmp_path)
    resolved = resolve(
        {"mode": "session", "operators_file": store_path, "secret_file": secret_file}
    )
    assert resolved is not None
    assert "operator1" in resolved["operators"]
    assert resolved["allow_readonly_anonymous"] is False
    assert len(resolved["secret"]) >= 32
