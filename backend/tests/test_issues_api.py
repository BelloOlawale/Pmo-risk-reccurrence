"""API tests for Issues raised from materialized risks.

The materialization itself is a backend job (``run_end_date_monitor``), so these
tests drive it through the session and then assert the HTTP surface: listing
issues under a Risk Register, reading an issue, the risk -> issue link, and the
row-level access rules (PMO Lead / PM / risk owner).
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.notifications import NotificationService
from riskapp.scheduler import run_end_date_monitor

PAST = dt.date(2026, 8, 20)
TODAY = dt.date(2026, 8, 24)


def _headers(user_id: int | None, role: str) -> dict[str, str]:
    headers = {"X-User-Role": role}
    if user_id is not None:
        headers["X-User-Id"] = str(user_id)
    return headers


def _create_project(client: TestClient, *, user_id: int, name: str) -> dict:
    resp = client.post(
        "/api/projects",
        json={
            "name": name,
            "department": "Digital Advisory",
            "project_type": "Cloud Migration",
            "customer": "Customer",
        },
        headers=_headers(user_id, "Project Manager"),
    )
    assert resp.status_code == 201
    return resp.json()


def _open_risk(client: TestClient, project: dict, *, user_id: int) -> dict:
    risk = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "description": "Unavailability of key project stakeholders",
            "category": "Project Management",
            "risk_source": "Human",
            "likelihood": "High",
            "impact": "High",
            "response_strategy": "Mitigate",
            "response_plan": "Assign a named deputy to every decision forum.",
            "identified_during": "Execution",
        },
        headers=_headers(user_id, "Project Manager"),
    ).json()
    # Manually added risks are already Open; no acceptance step needed.
    assert risk["status"] == "Open"
    return risk


def _materialize(client: TestClient, db: Session, risk_id: int) -> dict:
    """Force the Risk End Date into the past and run the backend monitor."""
    risk = db.get(models.Risk, risk_id)
    assert risk is not None
    risk.risk_end_date = PAST
    # Only an acknowledged risk materializes into an Event; an unacknowledged
    # one escalates instead.
    risk.sla_acknowledged = True
    db.commit()

    run_end_date_monitor(db, NotificationService(), TODAY)

    issue = db.scalar(
        select(models.Issue).where(models.Issue.source_risk_id == risk_id)
    )
    assert issue is not None
    return issue


class TestProjectIssues:
    def test_lists_empty_before_materialization(self, client: TestClient) -> None:
        project = _create_project(client, user_id=7, name="No issues yet")
        resp = client.get(
            f"/api/projects/{project['id']}/issues",
            headers=_headers(7, "Project Manager"),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_issues_are_fully_populated(self, client: TestClient, db_session: Session) -> None:
        project = _create_project(client, user_id=7, name="PMO Automation")
        risk = _open_risk(client, project, user_id=7)
        issue = _materialize(client, db_session, risk["id"])

        resp = client.get(
            f"/api/projects/{project['id']}/issues",
            headers=_headers(7, "Project Manager"),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        row = body[0]
        assert row["issue_code"] == issue.issue_code
        assert row["source_risk_id"] == risk["id"]
        assert row["source_risk_code"] == risk["risk_code"]
        assert row["project_id"] == project["id"]
        assert row["project_name"] == "PMO Automation"
        assert row["description"] == risk["description"]
        assert row["category"] == "Project Management"
        assert row["likelihood"] == "High"
        assert row["impact"] == "High"
        assert row["risk_rating"] == risk["risk_rating"]
        assert row["response_strategy"] == "Mitigate"
        assert row["identified_during"] == "Execution"
        assert row["owner_user_id"] == risk["owner_user_id"]
        assert row["risk_start_date"] == risk["risk_start_date"]
        assert row["risk_end_date"] == "2026-08-20"
        assert row["status"] == "Open"
        assert row["source_risk_status"] == "Event"
        assert row["created_at"]

    def test_issues_are_scoped_per_project(self, client: TestClient, db_session: Session) -> None:
        project_a = _create_project(client, user_id=7, name="Register A")
        project_b = _create_project(client, user_id=7, name="Register B")
        risk = _open_risk(client, project_a, user_id=7)
        _materialize(client, db_session, risk["id"])

        resp = client.get(
            f"/api/projects/{project_b['id']}/issues",
            headers=_headers(7, "Project Manager"),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_other_pm_is_forbidden(self, client: TestClient, db_session: Session) -> None:
        project = _create_project(client, user_id=7, name="PM A project")
        risk = _open_risk(client, project, user_id=7)
        _materialize(client, db_session, risk["id"])

        resp = client.get(
            f"/api/projects/{project['id']}/issues",
            headers=_headers(8, "Project Manager"),
        )
        assert resp.status_code == 403


class TestReadIssue:
    def test_pmo_lead_pm_and_owner_can_read(self, client: TestClient, db_session: Session) -> None:
        project = _create_project(client, user_id=7, name="Shared register")
        risk = _open_risk(client, project, user_id=7)
        # Assign a distinct risk owner (user 9).
        risk_row = db_session.get(models.Risk, risk["id"])
        assert risk_row is not None
        risk_row.owner_user_id = 9
        db_session.commit()
        issue = _materialize(client, db_session, risk["id"])

        for headers in (
            _headers(7, "Project Manager"),  # project PM
            _headers(None, "PMO Lead"),  # PMO Lead (no user id)
            _headers(9, "Project Manager"),  # risk owner
        ):
            resp = client.get(f"/api/issues/{issue.id}", headers=headers)
            assert resp.status_code == 200, headers
            assert resp.json()["id"] == issue.id

    def test_other_pm_is_forbidden(self, client: TestClient, db_session: Session) -> None:
        project = _create_project(client, user_id=7, name="Another register")
        risk = _open_risk(client, project, user_id=7)
        issue = _materialize(client, db_session, risk["id"])

        resp = client.get(f"/api/issues/{issue.id}", headers=_headers(8, "Project Manager"))
        assert resp.status_code == 403

    def test_missing_issue_returns_404(self, client: TestClient) -> None:
        resp = client.get("/api/issues/999999", headers=_headers(None, "PMO Lead"))
        assert resp.status_code == 404


class TestRiskIssueLink:
    def test_materialized_risk_exposes_issue(self, client: TestClient, db_session: Session) -> None:
        project = _create_project(client, user_id=7, name="Linked register")
        risk = _open_risk(client, project, user_id=7)
        issue = _materialize(client, db_session, risk["id"])

        resp = client.get(
            f"/api/risks/{risk['id']}/issue",
            headers=_headers(7, "Project Manager"),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == issue.id
        assert resp.json()["issue_code"] == issue.issue_code
        assert resp.json()["source_risk_code"] == risk["risk_code"]

    def test_plain_risk_has_no_issue(self, client: TestClient, db_session: Session) -> None:
        project = _create_project(client, user_id=7, name="No link register")
        risk = _open_risk(client, project, user_id=7)

        resp = client.get(
            f"/api/risks/{risk['id']}/issue",
            headers=_headers(7, "Project Manager"),
        )
        assert resp.status_code == 404

    def test_owner_can_read_issue_link(self, client: TestClient, db_session: Session) -> None:
        project = _create_project(client, user_id=7, name="Owner link register")
        risk = _open_risk(client, project, user_id=7)
        issue = _materialize(client, db_session, risk["id"])

        resp = client.get(
            f"/api/risks/{risk['id']}/issue",
            headers=_headers(9, "Project Manager"),
        )
        # User 9 is not the owner or the project PM -> forbidden.
        assert resp.status_code == 403

        risk_row = db_session.get(models.Risk, risk["id"])
        assert risk_row is not None
        risk_row.owner_user_id = 9
        db_session.commit()

        resp = client.get(
            f"/api/risks/{risk['id']}/issue",
            headers=_headers(9, "Project Manager"),
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == issue.id


class TestEffectiveIssueStatus:
    """The Issue's effective status follows the materialized risk's lifecycle."""

    def test_open_while_risk_event(self, client: TestClient, db_session: Session) -> None:
        project = _create_project(client, user_id=7, name="Status register")
        risk = _open_risk(client, project, user_id=7)
        issue = _materialize(client, db_session, risk["id"])

        resp = client.get(f"/api/issues/{issue.id}", headers=_headers(7, "Project Manager"))
        assert resp.status_code == 200
        assert resp.json()["status"] == "Open"
        assert resp.json()["source_risk_status"] == "Event"

    def test_resolved_when_risk_resolved(self, client: TestClient, db_session: Session) -> None:
        project = _create_project(client, user_id=7, name="Resolves register")
        risk = _open_risk(client, project, user_id=7)
        issue = _materialize(client, db_session, risk["id"])

        risk_row = db_session.get(models.Risk, risk["id"])
        assert risk_row is not None
        risk_row.status = "Resolved"
        db_session.commit()

        resp = client.get(f"/api/issues/{issue.id}", headers=_headers(None, "PMO Lead"))
        assert resp.status_code == 200
        assert resp.json()["status"] == "Resolved"
        assert resp.json()["source_risk_status"] == "Resolved"

    def test_closed_when_risk_closed(self, client: TestClient, db_session: Session) -> None:
        project = _create_project(client, user_id=7, name="Closed register")
        risk = _open_risk(client, project, user_id=7)
        issue = _materialize(client, db_session, risk["id"])

        risk_row = db_session.get(models.Risk, risk["id"])
        assert risk_row is not None
        risk_row.status = "Closed"
        db_session.commit()

        resp = client.get(f"/api/issues/{issue.id}", headers=_headers(None, "PMO Lead"))
        assert resp.status_code == 200
        assert resp.json()["status"] == "Closed"
        assert resp.json()["source_risk_status"] == "Closed"


class TestManualEventMaterialization:
    """A manual status change to Event materializes the risk like the job does."""

    def _issue_for(self, db_session: Session, risk_id: int) -> models.Issue | None:
        return db_session.scalar(
            select(models.Issue).where(models.Issue.source_risk_id == risk_id)
        )

    def test_patch_to_event_creates_issue_immediately(
        self, client: TestClient, db_session: Session
    ) -> None:
        project = _create_project(client, user_id=7, name="Manual event register")
        risk = _open_risk(client, project, user_id=7)

        resp = client.patch(
            f"/api/risks/{risk['id']}",
            json={"status": "Event", "actor_user_id": 7},
            headers=_headers(7, "Project Manager"),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "Event"

        issue = self._issue_for(db_session, risk["id"])
        assert issue is not None
        assert issue.issue_code == "ISS-001"
        assert issue.source_risk_id == risk["id"]
        assert issue.project_id == project["id"]
        # Fully populated from the originating risk (no blanking).
        assert issue.description == risk["description"]
        assert issue.category == risk["category"]
        assert issue.risk_rating == risk["risk_rating"]
        assert issue.status == "Open"

        # Original risk is retained, not closed.
        risk_row = db_session.get(models.Risk, risk["id"])
        assert risk_row is not None
        assert risk_row.status == "Event"

    def test_repeat_edits_of_event_risk_do_not_duplicate_issue(
        self, client: TestClient, db_session: Session
    ) -> None:
        project = _create_project(client, user_id=7, name="No dup register")
        risk = _open_risk(client, project, user_id=7)

        assert (
            client.patch(
                f"/api/risks/{risk['id']}",
                json={"status": "Event", "actor_user_id": 7},
                headers=_headers(7, "Project Manager"),
            ).status_code
            == 200
        )
        # A later ordinary edit of the Event risk must not create a second Issue.
        assert (
            client.patch(
                f"/api/risks/{risk['id']}",
                json={"description": "Updated while materialized", "actor_user_id": 7},
                headers=_headers(7, "Project Manager"),
            ).status_code
            == 200
        )

        issues = list(
            db_session.scalars(
                select(models.Issue).where(models.Issue.source_risk_id == risk["id"])
            ).all()
        )
        assert len(issues) == 1

    def test_manual_event_is_audited_and_notified(
        self, client: TestClient, db_session: Session
    ) -> None:
        project = _create_project(client, user_id=7, name="Audit register")
        risk = _open_risk(client, project, user_id=7)

        # Dev-mode auth does not create user rows, so give the risk real owner/PM
        # rows (the same setup the scheduler notification tests use).
        owner = models.User(upn="owner@example.com", display_name="Owner")
        pm = models.User(upn="pm@example.com", display_name="PM")
        db_session.add_all([owner, pm])
        db_session.flush()
        risk_row = db_session.get(models.Risk, risk["id"])
        project_row = db_session.get(models.Project, project["id"])
        assert risk_row is not None and project_row is not None
        risk_row.owner_user_id = owner.id
        project_row.pm_user_id = pm.id
        db_session.commit()

        assert (
            client.patch(
                f"/api/risks/{risk['id']}",
                json={"status": "Event", "actor_user_id": pm.id},
                headers=_headers(pm.id, "Project Manager"),
            ).status_code
            == 200
        )

        # Audit trail: Open -> Event plus issue_created.
        actions = list(
            db_session.scalars(
                select(models.RiskAuditLog.action).where(
                    models.RiskAuditLog.risk_id == risk["id"]
                )
            ).all()
        )
        assert "status_change" in actions
        assert "issue_created" in actions

        # In-app notification mirrors the scheduler materialization event.
        notices = list(
            db_session.scalars(
                select(models.Notification).where(
                    models.Notification.type == "materialized",
                    models.Notification.risk_id == risk["id"],
                )
            ).all()
        )
        assert {n.recipient_user_id for n in notices} == {owner.id, pm.id}

    def test_patch_to_event_is_not_an_issue_for_non_materializing_targets(
        self, client: TestClient, db_session: Session
    ) -> None:
        project = _create_project(client, user_id=7, name="Resolve only register")
        risk = _open_risk(client, project, user_id=7)

        # Resolving does not create an Issue.
        resp = client.patch(
            f"/api/risks/{risk['id']}",
            json={"status": "Resolved", "actor_user_id": 7},
            headers=_headers(7, "Project Manager"),
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "Resolved"
        assert self._issue_for(db_session, risk["id"]) is None
