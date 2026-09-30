"""Risk acknowledgement workflow.

No owner            -> Acknowledge hidden / rejected
Owner assigned      -> status In Progress, Acknowledge available
Acknowledged in SLA -> no escalation
Not acknowledged    -> Escalated + Issue + escalation notification
Acknowledged but
unresolved at SLA   -> Event + Issue
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.domain.status import RiskStatus
from riskapp.notifications import NotificationService
from riskapp.scheduler import run_end_date_monitor, run_sla_monitor
from riskapp.services import get_or_create_user

NOW = dt.datetime(2026, 8, 24, 12, 0, 0)
PAST_DATE = dt.date(2026, 8, 20)


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


def _assign_owner(client: TestClient, db: Session, risk_id: int) -> models.User:
    owner = get_or_create_user(db, "workflow-owner@example.com", "Workflow Owner")
    db.commit()
    resp = client.patch(f"/api/risks/{risk_id}", json={"owner_user_id": owner.id})
    assert resp.status_code == 200
    return owner


def test_assigning_owner_moves_risk_to_in_progress(
    client: TestClient, db_session: Session
) -> None:
    _, risk = _project_and_risk(client)
    assert risk["status"] == "Open"

    _assign_owner(client, db_session, risk["id"])

    read = client.get(f"/api/risks/{risk['id']}").json()
    assert read["status"] == "In Progress"
    assert read["owner_user_id"] is not None
    # Ownership alone does not acknowledge the risk.
    assert read["sla_acknowledged"] is False


def test_not_acknowledged_past_deadline_escalates_and_raises_issue(
    client: TestClient, db_session: Session
) -> None:
    project, risk = _project_and_risk(client)
    _assign_owner(client, db_session, risk["id"])

    row = db_session.get(models.Risk, risk["id"])
    assert row is not None
    row.sla_deadline = NOW - dt.timedelta(hours=1)
    row.risk_end_date = PAST_DATE
    db_session.commit()

    count = run_sla_monitor(db_session, NotificationService(), NOW)
    assert count == 1

    db_session.refresh(row)
    assert row.status == RiskStatus.ESCALATED.value

    issue = db_session.scalar(
        select(models.Issue).where(models.Issue.source_risk_id == row.id)
    )
    assert issue is not None

    notices = db_session.scalars(
        select(models.Notification).where(models.Notification.type == "breach")
    ).all()
    assert notices

    # The escalated risk is visible in the register's Issues table.
    listed = client.get(f"/api/projects/{project['id']}/issues").json()
    assert [i["source_risk_id"] for i in listed] == [row.id]


def test_acknowledged_but_unresolved_past_deadline_becomes_event(
    client: TestClient, db_session: Session
) -> None:
    project, risk = _project_and_risk(client)
    _assign_owner(client, db_session, risk["id"])
    assert client.post(f"/api/risks/{risk['id']}/acknowledge").status_code == 200

    row = db_session.get(models.Risk, risk["id"])
    assert row is not None
    row.risk_end_date = PAST_DATE
    db_session.commit()

    count = run_end_date_monitor(db_session, NotificationService(), dt.date(2026, 8, 24))
    assert count == 1

    db_session.refresh(row)
    assert row.status == RiskStatus.EVENT.value
    issue = db_session.scalar(
        select(models.Issue).where(models.Issue.source_risk_id == row.id)
    )
    assert issue is not None

    listed = client.get(f"/api/projects/{project['id']}/issues").json()
    assert [i["source_risk_id"] for i in listed] == [row.id]


def test_acknowledged_and_resolved_before_deadline_does_not_escalate_or_materialize(
    client: TestClient, db_session: Session
) -> None:
    _, risk = _project_and_risk(client)
    _assign_owner(client, db_session, risk["id"])
    client.post(f"/api/risks/{risk['id']}/acknowledge")
    assert (
        client.patch(
            f"/api/risks/{risk['id']}", json={"status": "Resolved"}
        ).status_code
        == 200
    )

    row = db_session.get(models.Risk, risk["id"])
    assert row is not None
    row.sla_deadline = NOW - dt.timedelta(hours=1)
    row.risk_end_date = PAST_DATE
    db_session.commit()

    assert run_sla_monitor(db_session, NotificationService(), NOW) == 0
    assert run_end_date_monitor(db_session, NotificationService(), dt.date(2026, 8, 24)) == 0
    assert (
        db_session.scalar(
            select(models.Issue).where(models.Issue.source_risk_id == row.id)
        )
        is None
    )


def test_acknowledge_does_not_resolve(client: TestClient, db_session: Session) -> None:
    _, risk = _project_and_risk(client)
    _assign_owner(client, db_session, risk["id"])
    client.post(f"/api/risks/{risk['id']}/acknowledge")

    read = client.get(f"/api/risks/{risk['id']}").json()
    assert read["sla_acknowledged"] is True
    assert read["status"] == "In Progress"
