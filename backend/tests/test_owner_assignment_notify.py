"""Tests for owner-assignment notifications and start-date idempotency.

Covers three previously-broken behaviours:
  1. Assigning an owner notifies them (in-app + email).
  2. The ACS email provider is actually wired (it was never instantiated).
  3. The start-date check can run repeatedly without spamming owners.
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models, notifications
from riskapp.config import settings
from riskapp.notifications import build_notification_service
from riskapp.scheduler import run_start_date_check
from riskapp.services import get_or_create_user


def _project_and_risk(client: TestClient) -> tuple[dict, dict]:
    project = client.post(
        "/api/projects",
        json={"name": "P", "department": "D", "project_type": "T", "customer": "C"},
    ).json()
    risk = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "description": "Risk",
            "likelihood": "High",
            "impact": "High",
        },
    ).json()
    return project, risk


class TestAssignOwnerNotifies:
    def test_patch_owner_creates_in_app_notification(
        self, client: TestClient, db_session: Session
    ) -> None:
        owner = get_or_create_user(db_session, "owner@example.com", "Owner")
        db_session.commit()
        _, risk = _project_and_risk(client)

        resp = client.patch(f"/api/risks/{risk['id']}", json={"owner_user_id": owner.id})
        assert resp.status_code == 200

        rows = list(
            db_session.scalars(
                select(models.Notification).where(models.Notification.type == "owner_assignment")
            )
        )
        assert len(rows) == 1
        assert rows[0].recipient_user_id == owner.id
        assert rows[0].risk_id == risk["id"]

    def test_reassigning_notifies_the_new_owner_only(
        self, client: TestClient, db_session: Session
    ) -> None:
        first = get_or_create_user(db_session, "a@example.com", "A")
        second = get_or_create_user(db_session, "b@example.com", "B")
        db_session.commit()
        _, risk = _project_and_risk(client)

        client.patch(f"/api/risks/{risk['id']}", json={"owner_user_id": first.id})
        client.patch(f"/api/risks/{risk['id']}", json={"owner_user_id": second.id})

        rows = list(
            db_session.scalars(
                select(models.Notification)
                .where(models.Notification.type == "owner_assignment")
                .order_by(models.Notification.id)
            )
        )
        assert [r.recipient_user_id for r in rows] == [first.id, second.id]

    def test_assigning_the_same_owner_again_does_not_renotify(
        self, client: TestClient, db_session: Session
    ) -> None:
        owner = get_or_create_user(db_session, "same@example.com", "Same")
        db_session.commit()
        _, risk = _project_and_risk(client)

        client.patch(f"/api/risks/{risk['id']}", json={"owner_user_id": owner.id})
        client.patch(f"/api/risks/{risk['id']}", json={"owner_user_id": owner.id})

        rows = list(
            db_session.scalars(
                select(models.Notification).where(models.Notification.type == "owner_assignment")
            )
        )
        assert len(rows) == 1

    def test_create_risk_with_owner_notifies(
        self, client: TestClient, db_session: Session
    ) -> None:
        owner = get_or_create_user(db_session, "c@example.com", "C")
        db_session.commit()
        project = client.post(
            "/api/projects",
            json={"name": "P", "department": "D", "project_type": "T", "customer": "C"},
        ).json()

        client.post(
            "/api/risks",
            json={
                "project_id": project["id"],
                "description": "Risk",
                "likelihood": "High",
                "impact": "High",
                "owner_user_id": owner.id,
            },
        )
        rows = list(
            db_session.scalars(
                select(models.Notification).where(models.Notification.type == "owner_assignment")
            )
        )
        assert len(rows) == 1
        assert rows[0].recipient_user_id == owner.id


class TestEmailProviderWiring:
    def test_factory_returns_email_capable_service_when_acs_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "acs_endpoint", "https://acs.example.com")
        monkeypatch.setattr(settings, "acs_access_key", "key")
        monkeypatch.setattr(settings, "acs_sender_email", "noreply@example.com")

        sent: list[dict] = []

        class FakeEmail:
            def send_email(self, **kwargs):  # type: ignore[no-untyped-def]
                sent.append(kwargs)

        monkeypatch.setattr(notifications, "AzureCommunicationEmail", FakeEmail)

        service = build_notification_service()
        assert service._email is not None  # noqa: SLF001 — assertion is the point

    def test_factory_without_acs_has_no_email_provider(self) -> None:
        service = build_notification_service()
        assert service._email is None  # noqa: SLF001


class TestStartDateIdempotency:
    def _risk_starting_today(self, db: Session, today: dt.date) -> models.Risk:
        dept = models.Department(name="D-start")
        ptype = models.ProjectType(name="T-start")
        db.add_all([dept, ptype])
        db.flush()
        project = models.Project(project_code="PRJ-X", name="P", status="Active")
        db.add(project)
        project.department = dept
        project.project_type = ptype
        db.flush()
        owner = models.User(upn="starter@example.com", display_name="Starter")
        db.add(owner)
        db.flush()
        risk = models.Risk(
            risk_code="RSK-X",
            project_id=project.id,
            description="Starts today",
            likelihood="High",
            impact="High",
            risk_rating="High",
            status="Open",
            owner_user_id=owner.id,
            risk_start_date=today,
        )
        db.add(risk)
        db.commit()
        return risk

    def test_second_run_does_not_renotify(self, db_session: Session) -> None:
        today = dt.date(2026, 8, 23)
        self._risk_starting_today(db_session, today)

        first = run_start_date_check(db_session, build_notification_service(), today)
        second = run_start_date_check(db_session, build_notification_service(), today)

        assert first == 1
        assert second == 0
