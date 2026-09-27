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

import datetime as dt
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Annotated, Any

import jwt as pyjwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWKClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.config import settings
from riskapp.db import get_db
from riskapp.security import verify_password
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

# ---------------------------------------------------------------------------
# Local test login (non-Microsoft)
#
# Issues a short-lived HS256 token carrying the same shape of claims the rest
# of the app expects (upn / name / roles), so authorization behaves identically
# to an Entra token. Disabled unless ``settings.test_login_enabled``.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Local (non-Microsoft) sign-in
#
# Issues a short-lived HS256 token carrying the same shape of claims the rest
# of the app expects (upn / name / roles), so authorization behaves identically
# to an Entra token. Two ways to obtain one, each behind its own flag:
#   * email + password        (local_login_enabled)
#   * role-only test login    (test_login_enabled, optional shared code)
# ---------------------------------------------------------------------------

LOCAL_LOGIN_ISSUER = "riskapp-test-login"
LOCAL_LOGIN_TTL_HOURS = 8


def _local_login_key() -> str:
    """Signing key for local tokens (stable across replicas)."""
    return (
        settings.test_login_secret
        or settings.entra_client_secret
        or "riskapp-local-login-dev-key"
    )


def create_local_token(
    *, user_id: int | None, upn: str, display_name: str, role: Role
) -> str:
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, Any] = {
        "iss": LOCAL_LOGIN_ISSUER,
        "sub": str(user_id) if user_id is not None else upn,
        "upn": upn,
        "name": display_name,
        "roles": [role.value],
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(hours=LOCAL_LOGIN_TTL_HOURS)).timestamp()),
    }
    return pyjwt.encode(payload, _local_login_key(), algorithm="HS256")


def _decode_local_token(token: str) -> dict[str, Any] | None:
    """Return the claims for a valid local token, else None."""
    try:
        claims: dict[str, Any] = pyjwt.decode(
            token,
            _local_login_key(),
            algorithms=["HS256"],
            issuer=LOCAL_LOGIN_ISSUER,
        )
        return claims
    except Exception:
        return None


def _principal_from_local_claims(claims: dict[str, Any], db: Session) -> Principal:
    upn = str(claims.get("upn") or "")
    display_name = str(claims.get("name") or upn)
    roles: set[Role] = set()
    for raw in claims.get("roles") or []:
        try:
            roles.add(Role(str(raw)))
        except ValueError:
            continue
    user_id: int | None = None
    if upn:
        user_id = get_or_create_user(db, upn, display_name).id
        db.commit()
    return Principal(user_id=user_id, upn=upn, roles=frozenset(roles))


def authenticate_local(db: Session, email: str, password: str) -> Principal | None:
    """Verify an app-managed email + password; None when invalid.

    Deliberately returns the same result for "no such user" and "wrong
    password" so the endpoint cannot be used to enumerate accounts.
    """
    upn = (email or "").strip()
    if not upn or not password:
        return None
    user = db.scalar(
        select(models.User).where(func.lower(models.User.upn) == upn.lower())
    )
    if user is None or not user.password_hash:
        return None
    if not verify_password(password, user.password_hash):
        return None
    try:
        role = Role(user.role) if user.role else Role.PROJECT_MANAGER
    except ValueError:
        role = Role.PROJECT_MANAGER
    return Principal(user_id=user.id, upn=user.upn, roles=frozenset({role}))


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
    """Resolve the current principal (Entra token, test token, or dev headers)."""
    token: str | None = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()

    # Locally-issued token (password login, or the role-only test login).
    if (settings.test_login_enabled or settings.local_login_enabled) and token:
        claims = _decode_local_token(token)
        if claims is not None:
            return _principal_from_local_claims(claims, db)

    if settings.entra_tenant_id:
        if not token:
            raise HTTPException(status_code=401, detail="Missing bearer token")
        return _principal_from_token(token, db)

    role_name = x_user_role or Role.SYSTEM_ADMIN.value
    try:
        role = Role(role_name)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=f"Unknown role {role_name!r}") from exc
    user_id = int(x_user_id) if x_user_id else None
    dev_upn = "dev.pm@local" if role == Role.PROJECT_MANAGER else "dev@local"
    if user_id is None and role == Role.PROJECT_MANAGER:
        user_id = get_or_create_user(db, dev_upn).id
        db.commit()
    elif user_id is None and role == Role.SYSTEM_ADMIN:
        admin = db.scalar(select(models.User).where(models.User.upn == dev_upn))
        user_id = admin.id if admin else None
    return Principal(
        user_id=user_id,
        upn=x_user_id or dev_upn,
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
    """Only an assigned creator with PM or Admin authority can close a register."""
    return (
        principal.has_role(Role.PROJECT_MANAGER, Role.SYSTEM_ADMIN)
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


def can_access_issue(principal: Principal, issue: Any) -> bool:
    """PMO Lead / Admin see everything; project PMs and risk owners see their Issues."""
    if principal.is_pmo_or_admin:
        return True
    if principal.user_id is None:
        return False
    if issue.owner_user_id is not None and issue.owner_user_id == principal.user_id:
        return True
    return (
        principal.has_role(Role.PROJECT_MANAGER)
        and issue.project.pm_user_id == principal.user_id
    )
