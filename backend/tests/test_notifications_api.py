"""Tests for the notifications API (principal-scoped)."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from riskapp import models


def _user(db: Session, upn: str) -> models.User:
    user = models.User(upn=upn, display_name=upn)
    db.add(user)
    db.flush()
    return user


def _notification(db: Session, user: models.User, title: str = "hi") -> models.Notification:
    note = models.Notification(
        recipient_user_id=user.id, type="owner_assignment", title=title, body="body"
    )
    db.add(note)
    db.flush()
    return note


class TestNotificationsApi:
    def test_lists_only_callers_notifications(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        _notification(db_session, alice, title="for alice")
        _notification(db_session, bob, title="for bob")
        db_session.commit()

        resp = client.get(
            "/api/notifications", headers={"X-User-Id": str(alice.id), "X-User-Role": "PMO Lead"}
        )
        assert resp.status_code == 200
        titles = [n["title"] for n in resp.json()]
        assert "for alice" in titles
        assert "for bob" not in titles

    def test_admin_without_identity_sees_none(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        _notification(db_session, alice)
        db_session.commit()

        resp = client.get("/api/notifications", headers={"X-User-Role": "System Admin"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_cannot_mark_another_users_notification_read(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        note = _notification(db_session, alice)
        db_session.commit()

        resp = client.post(
            f"/api/notifications/{note.id}/read",
            headers={"X-User-Id": str(bob.id), "X-User-Role": "PMO Lead"},
        )
        assert resp.status_code == 403

    def test_mark_own_notification_read(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        note = _notification(db_session, alice)
        db_session.commit()

        resp = client.post(
            f"/api/notifications/{note.id}/read",
            headers={"X-User-Id": str(alice.id), "X-User-Role": "PMO Lead"},
        )
        assert resp.status_code == 200
        assert resp.json()["read"] is True
