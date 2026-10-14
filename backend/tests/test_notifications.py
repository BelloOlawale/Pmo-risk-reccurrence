"""Tests for the notification recipient matrix and in-app/email wiring."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.notifications import (
    EVENT_ESCALATION,
    EVENT_MATERIALIZED,
    EVENT_OWNER_ASSIGNMENT,
    EVENT_OWNER_REMINDER,
    EVENT_WEEKLY_SUMMARY,
    NotificationService,
    RecipientContext,
    resolve_recipients,
)


class FakeEmail:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_email(self, *, to, cc=None, subject, body_html, body_text=None) -> None:
        self.sent.append(
            {
                "to": to,
                "cc": cc,
                "subject": subject,
                "body_html": body_html,
                "body_text": body_text,
            }
        )


def _ctx(**overrides) -> RecipientContext:
    defaults = dict(
        owner_user_id=1,
        owner_email="owner@example.com",
        pm_user_id=2,
        pm_email="pm@example.com",
        pmo_lead_email="pmo@example.com",
        practice_lead_email="pl@example.com",
    )
    defaults.update(overrides)
    return RecipientContext(**defaults)


class TestResolveRecipients:
    def test_owner_assignment_includes_owner_pm_pmo_and_cc_practice_lead(self) -> None:
        r = resolve_recipients(EVENT_OWNER_ASSIGNMENT, _ctx())
        assert r.to_user_ids == (1, 2)
        assert r.to_emails == ("owner@example.com", "pm@example.com", "pmo@example.com")
        assert r.cc_emails == ("pl@example.com",)

    def test_owner_reminder_owner_only(self) -> None:
        r = resolve_recipients(EVENT_OWNER_REMINDER, _ctx())
        assert r.to_emails == ("owner@example.com",)
        assert r.cc_emails == ()

    def test_escalation_includes_owner_and_pm(self) -> None:
        r = resolve_recipients(EVENT_ESCALATION, _ctx())
        assert r.to_user_ids == (1, 2)
        assert r.to_emails == ("owner@example.com", "pm@example.com")
        assert r.cc_emails == ()

    def test_materialized_goes_to_pm_with_pmo_cc(self) -> None:
        r = resolve_recipients(EVENT_MATERIALIZED, _ctx())
        assert r.to_user_ids == (2,)
        assert r.to_emails == ("pm@example.com",)
        assert r.cc_emails == ("pmo@example.com",)

    def test_weekly_summary_pm_and_pmo(self) -> None:
        r = resolve_recipients(EVENT_WEEKLY_SUMMARY, _ctx())
        assert r.to_emails == ("pm@example.com", "pmo@example.com")

    def test_deduplicates_overlapping_roles(self) -> None:
        # owner is also the PM
        r = resolve_recipients(
            EVENT_ESCALATION,
            _ctx(pm_email="owner@example.com"),
        )
        assert r.to_emails == ("owner@example.com",)


class TestNotificationService:
    def _risk_with_owner(self, db: Session) -> models.Risk:
        owner = models.User(upn="owner@example.com", display_name="Owner")
        pm = models.User(upn="pm@example.com", display_name="PM")
        db.add_all([owner, pm])
        db.flush()

        dept = models.Department(name="Digital Advisory")
        ptype = models.ProjectType(name="Cloud Migration")
        db.add_all([dept, ptype])
        db.flush()

        project = models.Project(
            name="AWS Migration", project_code="PRJ-N", status="Active"
        )
        project.department = dept
        project.project_type = ptype
        project.pm_user_id = pm.id
        db.add(project)
        db.flush()

        risk = models.Risk(
            project_id=project.id,
            risk_code="RSK-N",
            description="Data loss",
            likelihood="High",
            impact="High",
            risk_rating="High",
            status="Open",
            owner_user_id=owner.id,
        )
        db.add(risk)
        db.flush()
        db.commit()
        return risk

    def test_notify_records_in_app_and_sends_email(self, db_session: Session) -> None:
        risk = self._risk_with_owner(db_session)
        email = FakeEmail()
        service = NotificationService(email=email)

        service.notify(
            db_session,
            event=EVENT_OWNER_REMINDER,
            title="Acknowledgement reminder",
            body="Please acknowledge this risk",
            risk=risk,
        )

        rows = db_session.scalars(select(models.Notification)).all()
        assert len(rows) == 1
        assert rows[0].recipient_user_id == risk.owner_user_id
        assert rows[0].type == EVENT_OWNER_REMINDER
        assert rows[0].risk_id == risk.id

        assert len(email.sent) == 1
        assert email.sent[0]["to"] == ["owner@example.com"]
        # Risk Owners (internal or external) act from the emailed secure link.
        assert "/acknowledge/" in email.sent[0]["body_html"]

    def test_owner_assignment_splits_owner_and_staff_emails(
        self, db_session: Session
    ) -> None:
        """The owner gets the secure link; PM/PMO get the app notification."""
        db_session.add(models.Setting(key="pmo_lead_email", value="pmo@example.com"))
        db_session.commit()
        risk = self._risk_with_owner(db_session)
        email = FakeEmail()
        service = NotificationService(email=email)

        service.notify(
            db_session,
            event=EVENT_OWNER_ASSIGNMENT,
            title="Risk assigned",
            body="Risk assigned to you",
            risk=risk,
        )

        by_to = {tuple(m["to"]): m for m in email.sent}
        owner_msg = by_to[("owner@example.com",)]
        staff_msg = by_to[("pm@example.com", "pmo@example.com")]
        assert "/acknowledge/" in owner_msg["body_html"]
        assert f"/risks/{risk.id}" in staff_msg["body_html"]
        assert "/acknowledge/" not in staff_msg["body_html"]

    def test_notify_without_email_provider_does_not_send(self, db_session: Session) -> None:
        risk = self._risk_with_owner(db_session)
        service = NotificationService(email=None)

        service.notify(
            db_session,
            event=EVENT_OWNER_REMINDER,
            title="Acknowledgement reminder",
            body="Please acknowledge this risk",
            risk=risk,
        )
        rows = db_session.scalars(select(models.Notification)).all()
        assert len(rows) == 1
