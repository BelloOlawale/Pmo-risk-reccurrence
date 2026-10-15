"""Bulk-provision app-managed (local) sign-in accounts from a CSV.

Creates or updates ``User`` rows and assigns each one a scrypt-hashed password
plus an application role, so people can sign in with the email + password form
when ``RISKAPP_LOCAL_LOGIN_ENABLED=true``.

CSV format (header row required; column names are case-insensitive):

    email,name,role
    ada@wragby.com,Ada Lovelace,System Admin
    sam@wragby.com,Sam Bello,PMO Lead

``role`` is optional (default ``Project Manager``) and must be one of the three
application roles. An optional ``password`` column is used verbatim (minimum 8
characters); blank or absent values are replaced by a strong generated password.

Passwords are never printed to the console. The passwords created in a run are
written once to ``--out`` (owner-only permissions) for the administrator to
distribute out-of-band, then delete.

Usage:
    python -m riskapp.provision_users --file people.csv
    python -m riskapp.provision_users --file people.csv --out creds.csv
    python -m riskapp.provision_users --file people.csv --dry-run
"""

from __future__ import annotations

import argparse
import csv
import secrets
import string
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.auth import Role
from riskapp.db import SessionLocal
from riskapp.security import hash_password

# Column aliases so the CSV is forgiving about the header names.
_EMAIL_KEYS = ("email", "e-mail", "upn", "user principal name")
_NAME_KEYS = ("name", "display name", "display_name", "full name")
_ROLE_KEYS = ("role", "app role")
_PASSWORD_KEYS = ("password", "initial password", "temp password")

_PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*()-_=+"
_PASSWORD_LENGTH = 16
_MIN_PASSWORD_LENGTH = 8


@dataclass(frozen=True)
class ProvisionedUser:
    """Outcome for a single CSV row."""

    email: str
    name: str
    role: str
    password: str | None
    status: str  # created | updated | skipped
    reason: str = ""


def generate_password(length: int = _PASSWORD_LENGTH) -> str:
    """Return a strong random password satisfying the API's complexity needs."""
    while True:
        candidate = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))
        if (
            any(c.islower() for c in candidate)
            and any(c.isupper() for c in candidate)
            and any(c.isdigit() for c in candidate)
            and any(c in "!@#$%^&*()-_=+" for c in candidate)
        ):
            return candidate


def _pick(row: dict[str, str], keys: Iterable[str]) -> str:
    """Return the first non-empty value among ``keys`` (case-insensitive)."""
    for key in keys:
        value = row.get(key, "")
        if value and value.strip():
            return value.strip()
    return ""


def load_rows(path: Path) -> list[dict[str, str]]:
    """Read and normalise a provisioning CSV (UTF-8, optional BOM)."""
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header row")
        rows: list[dict[str, str]] = []
        for raw in reader:
            normalised = {
                (key or "").strip().lower(): (value or "").strip()
                for key, value in raw.items()
            }
            rows.append(normalised)
    return rows


def _valid_roles() -> set[str]:
    return {role.value for role in Role}


def provision(
    db: Session,
    rows: Iterable[dict[str, str]],
    *,
    default_role: str = Role.PROJECT_MANAGER.value,
    dry_run: bool = False,
) -> list[ProvisionedUser]:
    """Create/update local accounts for ``rows``.

    Never commits when ``dry_run`` is set. Callers should commit otherwise.
    External owner rows are never turned into login accounts.
    """
    valid_roles = _valid_roles()
    if default_role not in valid_roles:
        raise ValueError(f"Unknown default role: {default_role!r}")

    results: list[ProvisionedUser] = []
    for row in rows:
        email = _pick(row, _EMAIL_KEYS)
        name = _pick(row, _NAME_KEYS) or email
        role = _pick(row, _ROLE_KEYS) or default_role

        if not email or "@" not in email:
            results.append(
                ProvisionedUser(email, name, role, None, "skipped", "missing/invalid email")
            )
            continue
        if role not in valid_roles:
            results.append(
                ProvisionedUser(
                    email, name, role, None, "skipped",
                    f"unknown role {role!r} (expected one of {sorted(valid_roles)})",
                )
            )
            continue

        existing = db.scalar(
            select(models.User).where(func.lower(models.User.upn) == email.lower())
        )
        if existing is not None and existing.owner_type == "External":
            results.append(
                ProvisionedUser(email, name, role, None, "skipped",
                                "existing external owner cannot be granted access")
            )
            continue

        provided = _pick(row, _PASSWORD_KEYS)
        if provided and len(provided) < _MIN_PASSWORD_LENGTH:
            results.append(
                ProvisionedUser(email, name, role, None, "skipped",
                                f"password must be at least {_MIN_PASSWORD_LENGTH} characters")
            )
            continue
        password = provided or generate_password()

        created = existing is None
        user = existing if existing is not None else models.User(upn=email)
        user.display_name = name
        user.role = role
        user.is_active = True
        user.password_hash = hash_password(password)
        # The password was generated by the administrator, so the user must set
        # their own on first sign-in.
        user.must_change_password = True
        if created:
            db.add(user)
        db.flush()

        results.append(
            ProvisionedUser(
                email=user.upn,
                name=user.display_name,
                role=role,
                password=password,
                status="created" if created else "updated",
            )
        )
    return results


def write_credentials(path: Path, results: list[ProvisionedUser]) -> int:
    """Write the one-time credentials CSV; return the number of rows written."""
    rows = [r for r in results if r.status in {"created", "updated"} and r.password]
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["email", "name", "role", "password"])
        for r in rows:
            writer.writerow([r.email, r.name, r.role, r.password])
    try:
        path.chmod(0o600)
    except OSError:  # pragma: no cover - best effort on platforms without POSIX perms
        pass
    return len(rows)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bulk-provision local sign-in accounts.")
    parser.add_argument("--file", required=True, type=Path, help="Input CSV (email,name,role)")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("provisioned-credentials.csv"),
        help="Where to write the one-time credentials CSV",
    )
    parser.add_argument("--default-role", default=Role.PROJECT_MANAGER.value)
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing")
    parser.add_argument(
        "--no-passwords",
        action="store_true",
        help="Do not write the credentials file",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    rows = load_rows(args.file)

    with SessionLocal() as db:
        results = provision(
            db, rows, default_role=args.default_role, dry_run=args.dry_run
        )
        if not args.dry_run:
            db.commit()

    created = sum(1 for r in results if r.status == "created")
    updated = sum(1 for r in results if r.status == "updated")
    skipped = [r for r in results if r.status == "skipped"]

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Provisioned {created} new and {updated} existing account(s).")
    for r in skipped:
        print(f"  SKIPPED {r.email or '<no email>'}: {r.reason}")

    if not args.dry_run and not args.no_passwords:
        written = write_credentials(args.out, results)
        if written:
            print(
                f"Wrote {written} credential(s) to {args.out}.\n"
                "Deliver them out-of-band, then delete that file."
            )


if __name__ == "__main__":
    main()
