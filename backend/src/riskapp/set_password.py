"""Set a local (email + password) credential for a user.

Usage:
    python -m riskapp.set_password --upn user@wragbysolutions.com --role "PMO Lead"
    python -m riskapp.set_password --upn user@x --password 'Secret123' --role "Project Manager"

Prompts for the password (twice) when --password is omitted. Existing users are
updated in place; unknown emails are created (matched case-insensitively by UPN,
so this reuses the Entra-imported directory rows).
"""

from __future__ import annotations

import argparse
import getpass

from sqlalchemy import func, select

from riskapp import models
from riskapp.auth import Role
from riskapp.db import SessionLocal
from riskapp.security import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Set a user's local password and role.")
    parser.add_argument("--upn", required=True, help="Email address (UPN) to set")
    parser.add_argument(
        "--role",
        choices=[role.value for role in Role],
        default=Role.PROJECT_MANAGER.value,
        help="Role granted to this local account",
    )
    parser.add_argument("--password", default="", help="Password (prompted if omitted)")
    parser.add_argument("--display-name", default="", help="Display name for a new user")
    args = parser.parse_args()

    password = args.password
    if not password:
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Confirm : ")
        if password != confirm:
            raise SystemExit("ERROR: passwords do not match")
    if len(password) < 8:
        raise SystemExit("ERROR: password must be at least 8 characters")

    upn = args.upn.strip()
    with SessionLocal() as db:
        user = db.scalar(
            select(models.User).where(func.lower(models.User.upn) == upn.lower())
        )
        if user is None:
            user = models.User(upn=upn, display_name=args.display_name.strip() or upn)
            db.add(user)
            db.flush()
        elif args.display_name.strip():
            user.display_name = args.display_name.strip()

        user.password_hash = hash_password(password)
        user.role = args.role
        db.commit()
        print(f"Local login set for {user.upn} (role: {args.role})")


if __name__ == "__main__":
    main()
