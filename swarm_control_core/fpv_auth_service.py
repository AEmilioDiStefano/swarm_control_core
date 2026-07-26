#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-Vitruvian-Community-1.0

"""
fpv_auth_service.py

Auth service layer for FPV UI HTTP/WS access control.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from .fpv_auth_models import (
    AUTH_MODE_DEV,
    AUTH_MODE_OIDC,
    AUTH_MODE_OFF,
    AUTH_MODE_SESSION,
    AuthConfig,
    AuthDecision,
    Principal,
    SWARM_SCOPE_CONTROL,
    SWARM_SCOPE_READ,
    anonymous_principal,
    principal_from_claims,
)
from .fpv_session_auth import SessionAuthError, verify_session_token


def _extract_bearer_token(request: Any) -> str:
    # aiohttp Request supports .headers and .query. Keep this generic for tests.
    headers = getattr(request, "headers", {}) or {}
    query = getattr(request, "query", {}) or {}

    auth_header = str(headers.get("Authorization") or headers.get("authorization") or "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()

    query_token = str(query.get("access_token") or query.get("token") or "").strip()
    if query_token:
        return query_token

    return ""


def _enforce_scope(principal: Principal, required_scope: str) -> AuthDecision:
    scope = str(required_scope or "").strip()
    if not scope:
        return AuthDecision.allow(principal)
    if principal.has_scope(scope):
        return AuthDecision.allow(principal)
    return AuthDecision.deny(f"Missing required scope '{scope}'", http_status=403)


@dataclass(frozen=True)
class _DevToken:
    subject: str
    display_name: str
    roles_csv: str
    scopes_csv: str
    tenant_id: str
    session_id: str

    def to_claims(self) -> Mapping[str, Any]:
        return {
            "sub": self.subject,
            "name": self.display_name,
            "roles": self.roles_csv,
            "scopes": self.scopes_csv,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
        }


class AuthService:
    def __init__(self, config: AuthConfig):
        self.config = config.normalized()
        self.config.validate()

    def authorize_http(self, request: Any, required_scope: str = "") -> AuthDecision:
        raise NotImplementedError

    def authorize_ws(self, request: Any, required_scope: str = "") -> AuthDecision:
        return self.authorize_http(request, required_scope=required_scope)


class DevAuthService(AuthService):
    """
    Local auth implementation used for `off` and `dev` modes.
    """

    def _parse_devjson_claims(self, encoded: str) -> Mapping[str, Any]:
        # format: devjson.<base64url(json)>
        padded = encoded + "=" * ((4 - (len(encoded) % 4)) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("utf-8"))
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("devjson payload must decode to an object")
        return payload

    def _parse_pipe_token(self, token: str) -> _DevToken:
        # format:
        # dev|<subject>|<display_name>|<roles_csv>|<scopes_csv>|<tenant_id>|<session_id>
        parts = token.split("|")
        if len(parts) != 7:
            raise ValueError("Invalid dev token format")
        tag, subject, display_name, roles_csv, scopes_csv, tenant_id, session_id = parts
        if tag != "dev":
            raise ValueError("Invalid dev token prefix")
        if not str(subject).strip():
            raise ValueError("Dev token subject is required")
        return _DevToken(
            subject=str(subject).strip(),
            display_name=str(display_name or subject).strip(),
            roles_csv=str(roles_csv or ""),
            scopes_csv=str(scopes_csv or ""),
            tenant_id=str(tenant_id or ""),
            session_id=str(session_id or ""),
        )

    def _principal_from_token(self, token: str) -> Principal:
        raw = str(token or "").strip()
        if not raw:
            raise ValueError("Missing token")

        static = {
            "dev-admin": {
                "sub": "dev_admin",
                "name": "Dev Admin",
                "roles": "admin,operator",
                "scopes": f"{SWARM_SCOPE_READ},{SWARM_SCOPE_CONTROL}",
                "tenant_id": "dev",
                "session_id": "dev_admin",
            },
            "dev-readonly": {
                "sub": "dev_viewer",
                "name": "Dev Viewer",
                "roles": "viewer",
                "scopes": SWARM_SCOPE_READ,
                "tenant_id": "dev",
                "session_id": "dev_viewer",
            },
        }
        if raw in static:
            return principal_from_claims(static[raw])

        if raw.startswith("devjson."):
            claims = self._parse_devjson_claims(raw[len("devjson."):])
            return principal_from_claims(claims)

        if raw.startswith("dev|"):
            token_data = self._parse_pipe_token(raw)
            return principal_from_claims(token_data.to_claims())

        raise ValueError("Unsupported token format for dev mode")

    def authorize_http(self, request: Any, required_scope: str = "") -> AuthDecision:
        required_scope = str(required_scope or "").strip()

        if self.config.mode == AUTH_MODE_OFF:
            principal = anonymous_principal(readonly=False)
            return _enforce_scope(principal, required_scope)

        token = _extract_bearer_token(request)
        if not token:
            if self.config.allow_readonly_anonymous and required_scope in ("", SWARM_SCOPE_READ):
                return AuthDecision.allow(anonymous_principal(readonly=True))
            return AuthDecision.deny("Missing bearer token", http_status=401)

        try:
            principal = self._principal_from_token(token)
        except Exception as exc:
            return AuthDecision.deny(f"Invalid token: {exc}", http_status=401)
        return _enforce_scope(principal, required_scope)


class SessionAuthService(AuthService):
    """
    Signed server-issued session tokens (ADR-0010).

    Verifies HMAC signature and expiry statelessly; the UI server additionally
    enforces live-session registry membership for revocation.
    """

    def __init__(self, config: AuthConfig, session_secret: bytes):
        super().__init__(config)
        self._secret = bytes(session_secret or b"")

    def authorize_http(self, request: Any, required_scope: str = "") -> AuthDecision:
        required_scope = str(required_scope or "").strip()
        if not self._secret:
            # Defensive: a running service must never degrade to anonymous.
            return AuthDecision.deny("Session auth verifier is unavailable", http_status=503)

        token = _extract_bearer_token(request)
        if not token:
            if self.config.allow_readonly_anonymous and required_scope in ("", SWARM_SCOPE_READ):
                return AuthDecision.allow(anonymous_principal(readonly=True))
            return AuthDecision.deny("Missing bearer token", http_status=401)

        try:
            claims = verify_session_token(self._secret, token)
        except SessionAuthError as exc:
            return AuthDecision.deny(f"Invalid session token: {exc}", http_status=401)
        return _enforce_scope(principal_from_claims(claims), required_scope)


class OidcAuthService(AuthService):
    """
    OIDC scaffold for Phase 1.
    """

    def authorize_http(self, request: Any, required_scope: str = "") -> AuthDecision:
        token = _extract_bearer_token(request)
        if not token:
            return AuthDecision.deny("Missing bearer token", http_status=401)
        # Phase 1 intentionally does not implement remote JWKS verification.
        return AuthDecision.deny(
            "OIDC token verification is not enabled in this build",
            http_status=503,
        )


def build_auth_service(config: AuthConfig, session_secret: bytes = b"") -> AuthService:
    cfg = config.normalized()
    cfg.validate()
    if cfg.mode in (AUTH_MODE_OFF, AUTH_MODE_DEV):
        return DevAuthService(cfg)
    if cfg.mode == AUTH_MODE_SESSION:
        if not session_secret:
            raise ValueError("Session auth mode requires a non-empty session secret")
        return SessionAuthService(cfg, session_secret)
    if cfg.mode == AUTH_MODE_OIDC:
        return OidcAuthService(cfg)
    # Defensive fallback (validate() should already prevent this path).
    raise ValueError(f"Unsupported auth mode '{cfg.mode}'")
