"""Entra ID directory sync: keep the local ``users`` table in step with the tenant.

Risk ownership is stored as ``Risk.owner_user_id`` -> ``users.id``, so every
selectable owner must have a local row. Rather than waiting for people to sign
in, this module imports the whole Entra ID directory so the owner picker lists
everyone up front.

**B2B guest accounts are excluded by default.** Guests appear in the tenant with
UPNs like ``alice_contoso.com#EXT#@tenant.onmicrosoft.com``; they are external
partner identities and are not offered as risk owners. Pass ``include_guests``
to import them anyway.

Existing rows are matched case-insensitively by UPN and only their display name
is refreshed; rows are never deleted here (history may reference them).
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from riskapp import models

DirectoryEntry = tuple[str | None, str | None]

# Marker Entra assigns to B2B guest UPNs (e.g. bob_contoso.com#EXT#@t.onmicrosoft.com).
GUEST_MARKER = "#EXT#"


def is_guest_upn(upn: str) -> bool:
    """True for B2B guest accounts (case-insensitive)."""
    return GUEST_MARKER in upn.upper()


def sync_directory_users(
    db: Session,
    entries: Iterable[DirectoryEntry],
    *,
    include_guests: bool = False,
) -> tuple[int, int, int]:
    """Upsert ``(upn, display_name)`` pairs into ``users``.

    Returns ``(created, updated, skipped_guests)``. Blank UPNs and
    case-insensitive duplicates within ``entries`` are skipped, so the same
    directory can be re-imported safely. Guests are skipped unless
    ``include_guests`` is set.
    """
    existing = {user.upn.lower(): user for user in db.scalars(select(models.User))}
    created = 0
    updated = 0
    skipped_guests = 0
    seen: set[str] = set()

    for raw_upn, raw_name in entries:
        upn = (raw_upn or "").strip()
        if not upn:
            continue
        if not include_guests and is_guest_upn(upn):
            skipped_guests += 1
            continue
        key = upn.lower()
        if key in seen:
            continue
        seen.add(key)

        display_name = (raw_name or "").strip() or upn
        user = existing.get(key)
        if user is None:
            db.add(models.User(upn=upn, display_name=display_name))
            created += 1
        elif user.display_name != display_name:
            user.display_name = display_name
            updated += 1

    db.commit()
    return created, updated, skipped_guests


# Columns that reference ``users.id`` (nullable everywhere), cleared before a
# prune so referential integrity is preserved.
_USER_REFERENCES: tuple[tuple[type, str], ...] = (
    (models.Risk, "owner_user_id"),
    (models.Issue, "owner_user_id"),
    (models.Project, "pm_user_id"),
    (models.Project, "closed_by_user_id"),
    (models.RiskAuditLog, "user_id"),
    (models.Notification, "recipient_user_id"),
)


def prune_guest_users(db: Session) -> int:
    """Delete B2B guest rows, clearing any references first.

    Returns the number of users removed. Safe to call when there are none.
    """
    guest_ids = list(
        db.scalars(select(models.User.id).where(models.User.upn.ilike(f"%{GUEST_MARKER}%")))
    )
    if not guest_ids:
        return 0

    for model, column in _USER_REFERENCES:
        db.execute(
            update(model).where(getattr(model, column).in_(guest_ids)).values({column: None})
        )
    db.execute(delete(models.User).where(models.User.id.in_(guest_ids)))
    db.commit()
    return len(guest_ids)
