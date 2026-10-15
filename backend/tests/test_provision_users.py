"""Tests for bulk local-account provisioning."""

from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.provision_users import (
    generate_password,
    load_rows,
    provision,
    write_credentials,
)
from riskapp.security import verify_password


def _find(db: Session, email: str) -> models.User | None:
    return db.scalar(
        select(models.User).where(func.lower(models.User.upn) == email.lower())
    )


class TestGeneratePassword:
    def test_meets_complexity(self) -> None:
        password = generate_password()
        assert len(password) >= 12
        assert any(c.islower() for c in password)
        assert any(c.isupper() for c in password)
        assert any(c.isdigit() for c in password)
        assert any(c in "!@#$%^&*()-_=+" for c in password)

    def test_is_random(self) -> None:
        assert generate_password() != generate_password()


class TestLoadRows:
    def test_normalises_headers(self, tmp_path: Path) -> None:
        csv_path = tmp_path / "people.csv"
        csv_path.write_text(
            "Email,Display Name,Role\nada@x.com,Ada,PMO Lead\n", encoding="utf-8"
        )
        rows = load_rows(csv_path)
        assert rows[0]["email"] == "ada@x.com"
        assert rows[0]["display name"] == "Ada"


class TestProvision:
    def test_creates_a_new_account(self, db_session: Session) -> None:
        results = provision(
            db_session,
            [{"email": "ada@x.com", "name": "Ada Lovelace", "role": "System Admin"}],
        )
        assert results[0].status == "created"
        user = _find(db_session, "ada@x.com")
        assert user is not None
        assert user.display_name == "Ada Lovelace"
        assert user.role == "System Admin"
        assert user.must_change_password is True
        assert user.password_hash is not None
        assert verify_password(results[0].password or "", user.password_hash)

    def test_updates_an_existing_directory_row(self, db_session: Session) -> None:
        db_session.add(models.User(upn="sam@x.com", display_name="Old Name"))
        db_session.flush()

        results = provision(
            db_session,
            [{"email": "SAM@x.com", "name": "Sam Bello", "role": "PMO Lead"}],
        )
        assert results[0].status == "updated"
        user = _find(db_session, "SAM@x.com")
        assert user is not None
        assert user.display_name == "Sam Bello"
        assert user.role == "PMO Lead"
        assert verify_password(results[0].password or "", user.password_hash)

    def test_uses_a_supplied_password(self, db_session: Session) -> None:
        results = provision(
            db_session,
            [{"email": "a@x.com", "name": "A", "role": "Project Manager",
              "password": "Supplied-Pass-123"}],
        )
        user = _find(db_session, "a@x.com")
        assert user is not None
        assert verify_password("Supplied-Pass-123", user.password_hash)
        assert results[0].password == "Supplied-Pass-123"

    def test_generates_when_password_blank(self, db_session: Session) -> None:
        results = provision(
            db_session, [{"email": "b@x.com", "name": "B", "role": "Project Manager",
                          "password": ""}]
        )
        assert results[0].password
        assert len(results[0].password or "") >= 12

    def test_rejects_short_supplied_password(self, db_session: Session) -> None:
        results = provision(
            db_session,
            [{"email": "c@x.com", "name": "C", "role": "Project Manager",
              "password": "short"}],
        )
        assert results[0].status == "skipped"
        assert _find(db_session, "c@x.com") is None

    def test_skips_unknown_role(self, db_session: Session) -> None:
        results = provision(
            db_session, [{"email": "d@x.com", "name": "D", "role": "Superuser"}]
        )
        assert results[0].status == "skipped"
        assert _find(db_session, "d@x.com") is None

    def test_skips_invalid_email(self, db_session: Session) -> None:
        results = provision(db_session, [{"email": "not-an-email", "name": "X"}])
        assert results[0].status == "skipped"

    def test_skips_external_owners(self, db_session: Session) -> None:
        db_session.add(
            models.User(upn="vendor@partner.com", display_name="Vendor",
                        owner_type="External")
        )
        db_session.flush()

        results = provision(
            db_session, [{"email": "vendor@partner.com", "name": "Vendor"}]
        )
        assert results[0].status == "skipped"
        user = _find(db_session, "vendor@partner.com")
        assert user is not None
        assert user.password_hash is None

    def test_default_role_is_project_manager(self, db_session: Session) -> None:
        provision(db_session, [{"email": "e@x.com", "name": "E"}])
        user = _find(db_session, "e@x.com")
        assert user is not None
        assert user.role == "Project Manager"


class TestWriteCredentials:
    def test_writes_only_provisioned_rows(self, db_session: Session, tmp_path: Path) -> None:
        results = provision(
            db_session,
            [
                {"email": "a@x.com", "name": "A", "role": "PMO Lead"},
                {"email": "bad", "name": "Bad"},
            ],
        )
        out = tmp_path / "creds.csv"
        written = write_credentials(out, results)
        assert written == 1
        with out.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        assert rows[0]["email"] == "a@x.com"
        assert rows[0]["role"] == "PMO Lead"
        assert rows[0]["password"]
