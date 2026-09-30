"""External risk owners and secure acknowledgement.

External owners (partners, vendors, consultants) are people who are not Wragby
employees and are not in the Entra directory, yet still need to own a risk. They
are stored as ordinary ``users`` rows flagged ``owner_type='External'`` so the
existing ``risks.owner_user_id`` foreign key, SLA/escalation workflow and
notifications keep working unchanged — they simply never authenticate and hold
no application roles.

Because they have no Wragby account, an external owner acknowledges a risk via a
**signed, expiring, single-risk** link emailed to them. The token encodes only
the owner id and the one risk id it grants access to, so it can never be used to
reach other registers, projects, reports or admin functionality.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import jwt
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.config import settings

INTERNAL = "Internal"
EXTERNAL = "External"

_ACK_ISSUER = "riskapp-external-ack"
_ACK_PURPOSE = "acknowledge"
ACK_TTL_DAYS = 30

# Deliberately simple: a single ``@`` with a dotted domain. Enough to reject
# obvious typos without pulling in an extra dependency.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str | None) -> str:
    """Lower-case and trim an email address for stable dedup/matching."""
    return (email or "").strip().lower()


def is_valid_email(email: str | None) -> bool:
    """True when ``email`` looks like a deliverable address."""
    return bool(_EMAIL_RE.match(normalize_email(email)))


def get_or_create_external_owner(
    db: Session,
    *,
    full_name: str,
    email: str,
    organization: str | None = None,
) -> models.User:
    """Return the external owner for ``email``, creating one if needed.

    The email is normalized before matching so the same person entered twice is
    never duplicated. Raises :class:`ValueError` when the email is invalid or
    already belongs to an internal user.
    """
    normalized = normalize_email(email)
    if not is_valid_email(normalized):
        raise ValueError("Enter a valid email address.")
    name = (full_name or "").strip() or normalized
    org = (organization or "").strip() or None

    existing = db.scalar(
        select(models.User).where(func.lower(models.User.upn) == normalized)
    )
    if existing is not None:
        if existing.owner_type != EXTERNAL:
            raise ValueError("This email address belongs to an internal user.")
        # Refresh the display details from the latest submission.
        if name and existing.display_name != name:
            existing.display_name = name
        if org and existing.organization != org:
            existing.organization = org
        db.commit()
        db.refresh(existing)
        return existing

    owner = models.User(
        upn=normalized,
        display_name=name,
        owner_type=EXTERNAL,
        organization=org,
        is_active=True,
    )
    db.add(owner)
    db.commit()
    db.refresh(owner)
    return owner


def _signing_key() -> str:
    """HMAC key for acknowledgement tokens (stable across replicas)."""
    return (
        settings.test_login_secret
        or settings.entra_client_secret
        or "riskapp-external-ack-dev-key"
    )


def create_acknowledgement_token(*, owner_user_id: int, risk_id: int) -> str:
    """Mint a signed, expiring token scoped to a single owner + risk."""
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, Any] = {
        "iss": _ACK_ISSUER,
        "purpose": _ACK_PURPOSE,
        "sub": str(owner_user_id),
        "risk_id": risk_id,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(days=ACK_TTL_DAYS)).timestamp()),
    }
    return jwt.encode(payload, _signing_key(), algorithm="HS256")


def decode_acknowledgement_token(token: str) -> dict[str, Any] | None:
    """Return the claims for a valid acknowledgement token, else ``None``."""
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            _signing_key(),
            algorithms=["HS256"],
            issuer=_ACK_ISSUER,
        )
    except Exception:
        return None
    if claims.get("purpose") != _ACK_PURPOSE:
        return None
    return claims


def acknowledgement_url(risk: models.Risk) -> str | None:
    """The secure acknowledgement link for a risk, or None when not applicable.

    Only external owners get a link: internal owners acknowledge in the app.
    """
    if risk.owner is None or risk.owner.owner_type != EXTERNAL:
        return None
    token = create_acknowledgement_token(owner_user_id=risk.owner.id, risk_id=risk.id)
    return f"{settings.app_base_url}/acknowledge/{token}"
