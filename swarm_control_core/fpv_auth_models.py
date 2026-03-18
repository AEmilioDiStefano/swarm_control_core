#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""
fpv_auth_models.py

Shared auth/session data models for browser FPV access control.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, FrozenSet, Iterable, Mapping, Optional


AUTH_MODE_OFF = "off"
AUTH_MODE_DEV = "dev"
AUTH_MODE_OIDC = "oidc"
VALID_AUTH_MODES = frozenset((AUTH_MODE_OFF, AUTH_MODE_DEV, AUTH_MODE_OIDC))

SWARM_SCOPE_READ = "swarm:read"
SWARM_SCOPE_CONTROL = "swarm:control"


def _norm_str(value: Any) -> str:
    return str(value or "").strip()


def normalize_values(value: Any, separators: str = ", ") -> FrozenSet[str]:
    """
    Normalize a list-like or string-like value into a cleaned set of strings.
    """
    items = []
    if value is None:
        return frozenset()
    if isinstance(value, str):
        text = value
        for sep in separators:
            text = text.replace(sep, ",")
        items = text.split(",")
    elif isinstance(value, Mapping):
        items = list(value.keys())
    elif isinstance(value, Iterable):
        items = list(value)
    else:
        items = [value]

    out = []
    for item in items:
        s = _norm_str(item)
        if s:
            out.append(s)
    return frozenset(out)


@dataclass(frozen=True)
class Principal:
    subject: str
    display_name: str
    roles: FrozenSet[str]
    scopes: FrozenSet[str]
    tenant_id: str = ""
    session_id: str = ""

    def has_scope(self, scope: str) -> bool:
        scope = _norm_str(scope)
        if not scope:
            return True
        return scope in self.scopes

    def to_public_dict(self) -> dict:
        return {
            "subject": self.subject,
            "display_name": self.display_name,
            "roles": sorted(self.roles),
            "scopes": sorted(self.scopes),
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
        }


@dataclass(frozen=True)
class AuthConfig:
    mode: str = AUTH_MODE_OFF
    issuer: str = ""
    audience: str = ""
    jwks_url: str = ""
    allow_readonly_anonymous: bool = True

    def normalized(self) -> "AuthConfig":
        return AuthConfig(
            mode=_norm_str(self.mode).lower() or AUTH_MODE_OFF,
            issuer=_norm_str(self.issuer),
            audience=_norm_str(self.audience),
            jwks_url=_norm_str(self.jwks_url),
            allow_readonly_anonymous=bool(self.allow_readonly_anonymous),
        )

    def validate(self) -> None:
        cfg = self.normalized()
        if cfg.mode not in VALID_AUTH_MODES:
            raise ValueError(
                f"Invalid auth mode '{cfg.mode}'. Expected one of: {sorted(VALID_AUTH_MODES)}"
            )
        if cfg.mode == AUTH_MODE_OIDC:
            missing = []
            if not cfg.issuer:
                missing.append("issuer")
            if not cfg.audience:
                missing.append("audience")
            if not cfg.jwks_url:
                missing.append("jwks_url")
            if missing:
                raise ValueError(
                    "OIDC mode requires non-empty values for: " + ", ".join(missing)
                )


@dataclass(frozen=True)
class AuthDecision:
    ok: bool
    principal: Optional[Principal]
    reason: str = ""
    http_status: int = 200

    @staticmethod
    def allow(principal: Principal) -> "AuthDecision":
        return AuthDecision(ok=True, principal=principal, reason="", http_status=200)

    @staticmethod
    def deny(reason: str, http_status: int = 401) -> "AuthDecision":
        return AuthDecision(ok=False, principal=None, reason=_norm_str(reason), http_status=int(http_status))


def principal_from_claims(claims: Mapping[str, Any]) -> Principal:
    """
    Convert generic auth claims into a normalized Principal model.
    """
    sub = _norm_str(claims.get("sub") or claims.get("subject") or "unknown")
    name = _norm_str(
        claims.get("name")
        or claims.get("preferred_username")
        or claims.get("display_name")
        or sub
    )

    roles = set(normalize_values(claims.get("roles") or claims.get("role")))
    realm_access = claims.get("realm_access")
    if isinstance(realm_access, Mapping):
        roles.update(normalize_values(realm_access.get("roles")))

    scopes = set(normalize_values(claims.get("scopes")))
    scopes.update(normalize_values(claims.get("scope"), separators=" "))
    scopes.update(normalize_values(claims.get("scp"), separators=" "))

    tenant_id = _norm_str(claims.get("tenant_id") or claims.get("tid"))
    session_id = _norm_str(claims.get("session_id") or claims.get("sid"))

    return Principal(
        subject=sub,
        display_name=name,
        roles=frozenset(roles),
        scopes=frozenset(scopes),
        tenant_id=tenant_id,
        session_id=session_id,
    )


def anonymous_principal(readonly: bool = True) -> Principal:
    scopes = {SWARM_SCOPE_READ}
    if not readonly:
        scopes.add(SWARM_SCOPE_CONTROL)
    return Principal(
        subject="anonymous",
        display_name="anonymous",
        roles=frozenset(("anonymous",)),
        scopes=frozenset(scopes),
        tenant_id="",
        session_id="",
    )
