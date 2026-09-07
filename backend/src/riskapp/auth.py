"""Authentication and row-level authorization.

Two modes:

* **Production** (``RISKAPP_ENTRA_TENANT_ID`` set): the ``Authorization`` bearer
  token is a Microsoft Entra ID OIDC token, validated against the tenant JWKS,
  with roles resolved from the ``groups`` claim via the configured group-object
  id mapping.

* **Development** (no tenant configured): identity and role come from the
  ``X-User-Id`` / ``X-User-Role`` headers, defaulting to ``System Admin`` so the
  app remains usable and existing tests keep passing without tokens. Tests
  inject a fake principal via FastAPI dependency overrides.

The authorization *decisions* (who can see/edit what) are pure functions and are
exhaustively unit-tested independently of Entra.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any

import jwt as pyjwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from riskapp.config import settings
from riskapp.db import get_db
from riskapp.services import get_or_create_user


class Role(str, Enum):  # noqa: UP042 — str+Enum is intentional (claims-friendly)
    SYSTEM_ADMIN = "System Admin"
    PMO_LEAD = "PMO Lead"
    PROJECT_MANAGER = "Project Manager"


@dataclass(frozen=True)
class Principal:
    """The authenticated caller and their roles."""

    user_id: int | None
    upn: str
    roles: frozenset[Role] = field(default_factory=frozenset)

    def has_role(self, *roles: Role) -> bool:
        return any(role in self.roles for role in roles)

    @property
    def is_pmo_or_admin(self) -> bool:
        return self.has_role(Role.PMO_LEAD, Role.SYSTEM_ADMIN)


def _role_group_map() -> dict[Role, str]:
    """Parse the configured group-object-id → role mapping (JSON)."""
    raw = settings.entra_role_group_ids.strip()
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    valid = {role.value for role in Role}
    return {Role(key): str(group_id) for key, group_id in value.items() if key in valid}


_JWKS_CLIENT: PyJWKClient | None = None


def _signing_key(token: str) -> Any:
    """Return the RS256 signing key for ``token`` (JWKS, cached)."""
    global _JWKS_CLIENT
    if _JWKS_CLIENT is None:
        jwks_uri = (
            f"https://login.microsoftonline.com/{settings.entra_tenant_id}"
            "/discovery/v2.0/keys"
        )
        _JWKS_CLIENT = PyJWKClient(jwks_uri, cache_keys=True)
    return _JWKS_CLIENT.get_signing_key_from_jwt(token).key


def _principal_from_token(token: str, db: Session) -> Principal:
    try:
        payload = pyjwt.decode(
            token,
            key=_signing_key(token),
            algorithms=["RS256"],
            audience=settings.entra_client_id or None,
            issuer=(
                f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0"
            ),
            options={"verify_aud": bool(settings.entra_client_id)},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Token validation failed") from exc

    upn = str(payload.get("preferred_username") or payload.get("upn") or "")
    display_name = str(payload.get("name") or "")
    groups = payload.get("groups") or []
    role_map = _role_group_map()
    roles = {role for role, group_id in role_map.items() if group_id in groups}

    # Resolve the caller's identity to a stable user id so row-level scoping
    # (PM sees own projects; owner sees own risks) works under Entra.
    user_id: int | None = None
    if upn:
        user_id = get_or_create_user(db, upn, display_name).id
        db.commit()  # persist identity immediately so the id is stable

    return Principal(user_id=user_id, upn=upn, roles=frozenset(roles))


def get_principal(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_user_id: Annotated[str | None, Header()] = None,
    x_user_role: Annotated[str | None, Header()] = None,
) -> Principal:
    """Resolve the current principal (Entra token in prod, headers in dev)."""
    if settings.entra_tenant_id:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        return _principal_from_token(authorization.split(" ", 1)[1].strip(), db)

    role_name = x_user_role or Role.SYSTEM_ADMIN.value
    try:
        role = Role(role_name)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=f"Unknown role {role_name!r}") from exc
    user_id = int(x_user_id) if x_user_id else None
    return Principal(
        user_id=user_id,
        upn=x_user_id or "dev@local",
        roles=frozenset({role}),
    )


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_roles(*roles: Role) -> Callable[[Principal], Principal]:
    """Dependency factory: require at least one of ``roles``."""

    def dependency(principal: PrincipalDep) -> Principal:
        if principal.has_role(*roles):
            return principal
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    return dependency


def can_access_project(principal: Principal, project: Any) -> bool:
    """PMO Lead / Admin see everything; a PM sees only their own projects."""
    if principal.is_pmo_or_admin:
        return True
    return (
        principal.has_role(Role.PROJECT_MANAGER)
        and principal.user_id is not None
        and project.pm_user_id == principal.user_id
    )


def can_close_project(principal: Principal, project: Any) -> bool:
    """True only for the Project Manager explicitly assigned to the project."""
    return (
        principal.has_role(Role.PROJECT_MANAGER)
        and principal.user_id is not None
        and project.pm_user_id == principal.user_id
    )


def can_close_risk(principal: Principal) -> bool:
    """True for the PMO Lead (final risk-closure authority).

    System Admin is the application's superuser and may also close a risk, but
    Project Managers and ordinary users cannot — enforced server-side on any
    transition to ``Closed``.
    """
    return principal.has_role(Role.PMO_LEAD, Role.SYSTEM_ADMIN)


def can_access_risk(principal: Principal, risk: Any) -> bool:
    """PMO Lead / Admin see everything; owners and project PMs see their risks."""
    if principal.is_pmo_or_admin:
        return True
    if risk.owner_user_id is not None and risk.owner_user_id == principal.user_id:
        return True
    return (
        principal.has_role(Role.PROJECT_MANAGER)
        and principal.user_id is not None
        and risk.project.pm_user_id == principal.user_id
    )
