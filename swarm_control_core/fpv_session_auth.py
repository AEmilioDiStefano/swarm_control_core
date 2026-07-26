#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

"""
fpv_session_auth.py

Signed server-issued session tokens and the scrypt operator credential store
for FPV UI `session` auth mode (ADR-0010).

The community CLI never enables this mode; distribution editions inject it
through the explicit `main()` seam in `swarm_fpv_ui`. Everything here is
stdlib-only and fails closed: bad files, bad permissions, bad tokens, and bad
hashes all raise or deny rather than degrade to a weaker posture.
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import os
import secrets
import stat
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence

from .fpv_auth_models import SWARM_SCOPE_CONTROL, SWARM_SCOPE_READ

TOKEN_PREFIX = "swst1"
SCRYPT_PREFIX = "scrypt"
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_SALT_BYTES = 16
SCRYPT_KEY_BYTES = 32
SESSION_SECRET_BYTES = 32
DEFAULT_SESSION_TTL_S = 28800
OPERATOR_STORE_VERSION = 1


class SessionAuthError(ValueError):
    """Raised for any credential-store, secret, or token failure."""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padded = text + "=" * ((4 - (len(text) % 4)) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def hash_password(password: str, *, n: int = SCRYPT_N, r: int = SCRYPT_R, p: int = SCRYPT_P) -> str:
    """Hash a password into the stored `scrypt$n$r$p$salt$dk` format."""
    pw = str(password or "")
    if not pw:
        raise SessionAuthError("Password must not be empty")
    salt = secrets.token_bytes(SCRYPT_SALT_BYTES)
    dk = hashlib.scrypt(pw.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=SCRYPT_KEY_BYTES)
    return "$".join((SCRYPT_PREFIX, str(n), str(r), str(p), _b64url_encode(salt), _b64url_encode(dk)))


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time scrypt verification against a stored hash string."""
    try:
        prefix, n_s, r_s, p_s, salt_s, dk_s = str(stored_hash or "").split("$")
        if prefix != SCRYPT_PREFIX:
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = _b64url_decode(salt_s)
        expected = _b64url_decode(dk_s)
        if n < 2 or r < 1 or p < 1 or not salt or not expected:
            return False
        candidate = hashlib.scrypt(
            str(password or "").encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected)
        )
    except Exception:
        return False
    return hmac.compare_digest(candidate, expected)


def _is_valid_stored_hash(stored_hash: str) -> bool:
    parts = str(stored_hash or "").split("$")
    if len(parts) != 6 or parts[0] != SCRYPT_PREFIX:
        return False
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = _b64url_decode(parts[4])
        dk = _b64url_decode(parts[5])
    except Exception:
        return False
    return n >= 2 and r >= 1 and p >= 1 and bool(salt) and bool(dk)


@dataclass(frozen=True)
class OperatorRecord:
    username: str
    password_hash: str
    subject: str
    display_name: str
    roles: tuple
    scopes: tuple
    tenant_id: str


def _require_private_regular_file(path: str, label: str) -> None:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise SessionAuthError(f"{label} not found at {path}")
    except OSError as exc:
        raise SessionAuthError(f"{label} at {path} is unreadable: {exc}")
    if not stat.S_ISREG(st.st_mode):
        raise SessionAuthError(f"{label} at {path} must be a regular file")
    if st.st_mode & 0o077:
        raise SessionAuthError(
            f"{label} at {path} is group/other-accessible. Fix with: chmod 600 {path}"
        )


def load_operator_store(path: str) -> Dict[str, OperatorRecord]:
    """Load and strictly validate the operators file; raise SessionAuthError otherwise."""
    file_path = str(path or "").strip()
    if not file_path:
        raise SessionAuthError("Operators file path is empty")
    _require_private_regular_file(file_path, "Operators file")
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:
        raise SessionAuthError(f"Operators file at {file_path} is not valid JSON: {exc}")
    if not isinstance(payload, dict) or int(payload.get("version") or 0) != OPERATOR_STORE_VERSION:
        raise SessionAuthError(
            f"Operators file at {file_path} must be an object with version={OPERATOR_STORE_VERSION}"
        )
    rows = payload.get("operators")
    if not isinstance(rows, list) or not rows:
        raise SessionAuthError(f"Operators file at {file_path} declares no operators")

    out: Dict[str, OperatorRecord] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise SessionAuthError(f"Operators file at {file_path} has a non-object operator entry")
        username = str(row.get("username") or "").strip()
        password_hash = str(row.get("password_hash") or "").strip()
        if not username:
            raise SessionAuthError(f"Operators file at {file_path} has an operator without a username")
        if username in out:
            raise SessionAuthError(f"Operators file at {file_path} repeats username '{username}'")
        if not _is_valid_stored_hash(password_hash):
            raise SessionAuthError(
                f"Operator '{username}' in {file_path} has a missing or invalid scrypt password_hash"
            )
        roles = tuple(str(v).strip() for v in (row.get("roles") or ["operator"]) if str(v).strip())
        scopes = tuple(
            str(v).strip()
            for v in (row.get("scopes") or [SWARM_SCOPE_READ, SWARM_SCOPE_CONTROL])
            if str(v).strip()
        )
        out[username] = OperatorRecord(
            username=username,
            password_hash=password_hash,
            subject=str(row.get("subject") or username).strip(),
            display_name=str(row.get("display_name") or username).strip(),
            roles=roles,
            scopes=scopes,
            tenant_id=str(row.get("tenant_id") or "pro").strip(),
        )
    return out


def _write_private_file(path: str, data: bytes) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, mode=0o700, exist_ok=True)
    tmp_path = f"{path}.tmp.{os.getpid()}"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def save_operator_store(path: str, operators: Mapping[str, OperatorRecord]) -> None:
    """Persist the operators mapping as a 0600 version-1 store file."""
    rows = []
    for record in operators.values():
        rows.append(
            {
                "username": record.username,
                "password_hash": record.password_hash,
                "subject": record.subject,
                "display_name": record.display_name,
                "roles": list(record.roles),
                "scopes": list(record.scopes),
                "tenant_id": record.tenant_id,
            }
        )
    payload = {"version": OPERATOR_STORE_VERSION, "operators": rows}
    _write_private_file(str(path), (json.dumps(payload, indent=2) + "\n").encode("utf-8"))


def load_or_create_session_secret(path: str) -> bytes:
    """Load the HMAC session secret, creating a fresh 0600 one on first use."""
    file_path = str(path or "").strip()
    if not file_path:
        raise SessionAuthError("Session secret path is empty")
    if not os.path.exists(file_path):
        _write_private_file(file_path, _b64url_encode(secrets.token_bytes(SESSION_SECRET_BYTES)).encode("ascii"))
    _require_private_regular_file(file_path, "Session secret file")
    try:
        with open(file_path, "r", encoding="utf-8") as handle:
            raw = handle.read().strip()
        secret = _b64url_decode(raw)
    except Exception as exc:
        raise SessionAuthError(f"Session secret file at {file_path} is unreadable or malformed: {exc}")
    if len(secret) < 16:
        raise SessionAuthError(
            f"Session secret file at {file_path} is too short. Delete it to regenerate."
        )
    return secret


def _sign(secret: bytes, payload_b64: str) -> str:
    mac = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).digest()
    return _b64url_encode(mac)


def mint_session_token(
    secret: bytes,
    *,
    subject: str,
    display_name: str,
    roles: Sequence[str],
    scopes: Sequence[str],
    tenant_id: str,
    session_id: str,
    ttl_s: float = DEFAULT_SESSION_TTL_S,
    now: Optional[float] = None,
) -> str:
    """Mint a signed `swst1.<payload>.<mac>` session token."""
    if not secret:
        raise SessionAuthError("Session secret is empty")
    issued = float(now if now is not None else time.time())
    claims = {
        "v": 1,
        "sub": str(subject or "").strip(),
        "name": str(display_name or subject or "").strip(),
        "roles": [str(v).strip() for v in roles if str(v).strip()],
        "scopes": [str(v).strip() for v in scopes if str(v).strip()],
        "tenant_id": str(tenant_id or "").strip(),
        "session_id": str(session_id or "").strip(),
        "iat": int(issued),
        "exp": int(issued + max(60.0, float(ttl_s))),
    }
    if not claims["sub"]:
        raise SessionAuthError("Session token subject is required")
    if not claims["session_id"]:
        raise SessionAuthError("Session token session_id is required")
    payload_b64 = _b64url_encode(json.dumps(claims, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{TOKEN_PREFIX}.{payload_b64}.{_sign(secret, payload_b64)}"


def verify_session_token(secret: bytes, token: str, now: Optional[float] = None) -> Dict[str, Any]:
    """Verify signature and expiry; return claims or raise SessionAuthError."""
    if not secret:
        raise SessionAuthError("Session auth verifier is unavailable (empty secret)")
    parts = str(token or "").strip().split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise SessionAuthError("Unsupported token format for session mode")
    _, payload_b64, mac_b64 = parts
    if not hmac.compare_digest(_sign(secret, payload_b64), mac_b64):
        raise SessionAuthError("Session token signature mismatch")
    try:
        claims = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        raise SessionAuthError("Session token payload is malformed")
    if not isinstance(claims, dict) or int(claims.get("v") or 0) != 1:
        raise SessionAuthError("Session token version is unsupported")
    t_now = float(now if now is not None else time.time())
    try:
        expires = float(claims.get("exp"))
    except Exception:
        raise SessionAuthError("Session token has no expiry")
    if t_now >= expires:
        raise SessionAuthError("Session token is expired")
    if not str(claims.get("sub") or "").strip() or not str(claims.get("session_id") or "").strip():
        raise SessionAuthError("Session token is missing identity claims")
    return claims


def _cli_read_password(args: argparse.Namespace) -> str:
    if args.password_env:
        password = str(os.environ.get(args.password_env, ""))
        if not password:
            raise SessionAuthError(f"Environment variable {args.password_env} is empty or unset")
        return password
    if not sys.stdin.isatty():
        password = sys.stdin.readline().rstrip("\n")
        if not password:
            raise SessionAuthError("No password provided on stdin")
        return password
    return getpass.getpass("Operator password: ")


def _cli_load_or_empty(path: str) -> Dict[str, OperatorRecord]:
    if os.path.exists(path):
        return dict(load_operator_store(path))
    return {}


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Operator-store admin CLI: add/set-password/remove/list."""
    parser = argparse.ArgumentParser(description="FPV session-auth operator store admin")
    parser.add_argument("command", choices=("add", "set-password", "remove", "list"))
    parser.add_argument("username", nargs="?", default="")
    parser.add_argument("--file", required=True, help="Operators JSON file path")
    parser.add_argument("--display-name", default="")
    parser.add_argument("--roles", default="operator", help="Comma-separated roles")
    parser.add_argument(
        "--scopes",
        default=f"{SWARM_SCOPE_READ},{SWARM_SCOPE_CONTROL}",
        help="Comma-separated scopes (omit swarm:control for read-only operators)",
    )
    parser.add_argument("--tenant-id", default="pro")
    parser.add_argument(
        "--password-env",
        default="",
        help="Read the password from this environment variable instead of prompting",
    )
    args = parser.parse_args(argv)

    try:
        if args.command == "list":
            operators = _cli_load_or_empty(args.file)
            for record in operators.values():
                print(f"{record.username}  scopes={','.join(record.scopes)}  roles={','.join(record.roles)}")
            if not operators:
                print("(no operators)")
            return 0

        username = str(args.username or "").strip()
        if not username:
            raise SessionAuthError(f"Command '{args.command}' requires a username argument")
        operators = _cli_load_or_empty(args.file)

        if args.command == "remove":
            if operators.pop(username, None) is None:
                raise SessionAuthError(f"Operator '{username}' not found in {args.file}")
            save_operator_store(args.file, operators)
            print(f"Removed operator '{username}'")
            return 0

        password_hash = hash_password(_cli_read_password(args))
        if args.command == "set-password":
            existing = operators.get(username)
            if existing is None:
                raise SessionAuthError(f"Operator '{username}' not found in {args.file}")
            operators[username] = OperatorRecord(
                username=username,
                password_hash=password_hash,
                subject=existing.subject,
                display_name=existing.display_name,
                roles=existing.roles,
                scopes=existing.scopes,
                tenant_id=existing.tenant_id,
            )
        else:
            operators[username] = OperatorRecord(
                username=username,
                password_hash=password_hash,
                subject=username,
                display_name=str(args.display_name or username).strip() or username,
                roles=tuple(v.strip() for v in str(args.roles).split(",") if v.strip()),
                scopes=tuple(v.strip() for v in str(args.scopes).split(",") if v.strip()),
                tenant_id=str(args.tenant_id or "pro").strip() or "pro",
            )
        save_operator_store(args.file, operators)
        print(f"Saved operator '{username}' to {args.file}")
        return 0
    except SessionAuthError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
