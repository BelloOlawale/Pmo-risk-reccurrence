"""Create (or refresh) the temporary demo logins.

Three accounts share one temporary password:

    PM@automation.dev          Project Manager
    PMO@automation.dev         PMO Lead
    RiskOwner@automation.dev   Project Manager  (a Risk Owner is a per-risk
                               assignment, not a permission role — see SPEC §10,
                               so they carry the Project Manager permission)

Idempotent: existing rows are updated in place (password + role); unknown
emails are created. Matches UPNs case-insensitively, so it reuses any
directory row that already exists.

Usage:
    python -m riskapp.seed_temp_users
    python -m riskapp.seed_temp_users --password 'SomethingElse123'

Runs against whatever ``RISKAPP_DATABASE_URL`` points at. Rotate or delete
these accounts before the app is shared more widely.
"""

from __future__ import annotations

import argparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.auth import Role
from riskapp.db import SessionLocal
from riskapp.security import hash_password

# Shared temporary password for all three demo accounts.
DEFAULT_TEMP_PASSWORD = "Wragby@2026"

TEMP_ACCOUNTS: tuple[tuple[str, str, str], ...] = (
    ("PM@automation.dev", "Project Manager (temp)", Role.PROJECT_MANAGER.value),
    ("PMO@automation.dev", "PMO Lead (temp)", Role.PMO_LEAD.value),
    ("RiskOwner@automation.dev", "Risk Owner (temp)", Role.PROJECT_MANAGER.value),
)


def upsert_account(
    db: Session, upn: str, display_name: str, role: str, password: str
) -> models.User:
    user = db.scalar(select(models.User).where(func.lower(models.User.upn) == upn.lower()))
    if user is None:
        user = models.User(upn=upn, display_name=display_name)
        db.add(user)
        db.flush()
    else:
        user.display_name = display_name
    user.password_hash = hash_password(password)
    user.role = role
    user.is_active = True
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--password", default=DEFAULT_TEMP_PASSWORD, help="Shared password")
    args = parser.parse_args()

    if len(args.password) < 8:
        raise SystemExit("ERROR: password must be at least 8 characters")

    with SessionLocal() as db:
        for upn, display_name, role in TEMP_ACCOUNTS:
            user = upsert_account(db, upn, display_name, role, args.password)
            print(f"  {user.upn:<24} {role}")
        db.commit()

    print(f"\nTemporary logins ready. Shared password: {args.password}")


if __name__ == "__main__":
    main()
