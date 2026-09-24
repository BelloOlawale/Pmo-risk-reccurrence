"""Tests for syncing the Entra ID directory into the local users table."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.directory import is_guest_upn, sync_directory_users


class TestGuestDetection:
    def test_flags_b2b_guest_upns(self) -> None:
        assert is_guest_upn("alice_contoso.com#EXT#@wragby.onmicrosoft.com")
        assert is_guest_upn("BOB_X.COM#ext#@t.onmicrosoft.com")

    def test_internal_upn_is_not_a_guest(self) -> None:
        assert not is_guest_upn("obello@wragbysolutions.com")


class TestSyncDirectoryUsers:
    def test_creates_users(self, db_session: Session) -> None:
        created, updated, guests = sync_directory_users(
            db_session,
            [("alice@example.com", "Alice"), ("bob@example.com", None)],
        )
        assert (created, updated, guests) == (2, 0, 0)
        users = list(db_session.scalars(select(models.User).order_by(models.User.upn)))
        assert [u.upn for u in users] == ["alice@example.com", "bob@example.com"]
        # Missing display name falls back to the UPN.
        assert users[1].display_name == "bob@example.com"

    def test_excludes_guests_by_default(self, db_session: Session) -> None:
        created, _, guests = sync_directory_users(
            db_session,
            [
                ("internal@example.com", "Internal"),
                ("guest_partner.com#EXT#@t.onmicrosoft.com", "Guest"),
            ],
        )
        assert created == 1
        assert guests == 1
        upns = {u.upn for u in db_session.scalars(select(models.User))}
        assert upns == {"internal@example.com"}

    def test_include_guests_imports_them(self, db_session: Session) -> None:
        created, _, guests = sync_directory_users(
            db_session,
            [("guest_partner.com#EXT#@t.onmicrosoft.com", "Guest")],
            include_guests=True,
        )
        assert (created, guests) == (1, 0)
        assert len(list(db_session.scalars(select(models.User)))) == 1

    def test_is_idempotent(self, db_session: Session) -> None:
        sync_directory_users(db_session, [("alice@example.com", "Alice")])
        created, updated, _ = sync_directory_users(
            db_session, [("alice@example.com", "Alice")]
        )
        assert (created, updated) == (0, 0)
        found = db_session.scalar(
            select(models.User).where(models.User.upn == "alice@example.com")
        )
        assert found is not None

    def test_updates_changed_display_name(self, db_session: Session) -> None:
        sync_directory_users(db_session, [("alice@example.com", "Alice")])
        created, updated, _ = sync_directory_users(
            db_session, [("alice@example.com", "Alice Smith")]
        )
        assert (created, updated) == (0, 1)
        user = db_session.scalar(
            select(models.User).where(models.User.upn == "alice@example.com")
        )
        assert user is not None and user.display_name == "Alice Smith"

    def test_matches_case_insensitively(self, db_session: Session) -> None:
        sync_directory_users(db_session, [("Alice@Example.com", "Alice")])
        created, _, _ = sync_directory_users(db_session, [("alice@example.com", "Alice")])
        assert created == 0
        assert len(list(db_session.scalars(select(models.User)))) == 1

    def test_skips_blank_and_duplicate_upns(self, db_session: Session) -> None:
        created, _, _ = sync_directory_users(
            db_session,
            [("", "No UPN"), ("  ", None), ("a@x.com", "A"), ("A@X.com", "A again")],
        )
        assert created == 1

    def test_preserves_manually_created_users(self, db_session: Session) -> None:
        db_session.add(models.User(upn="manual@example.com", display_name="Manual"))
        db_session.commit()
        created, _, _ = sync_directory_users(db_session, [("dir@example.com", "Dir")])
        assert created == 1
        upns = {u.upn for u in db_session.scalars(select(models.User))}
        assert upns == {"manual@example.com", "dir@example.com"}
