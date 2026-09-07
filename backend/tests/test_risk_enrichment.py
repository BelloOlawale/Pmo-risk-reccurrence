"""Risk enrichment on suggestion acceptance + form option sets.

When a suggested risk is accepted the matched historical record is used to
populate the full risk (category, risk source, response strategy/plan, owner,
lifecycle, dates) — exact-match enrichment grounded in the source data, never
invented. Dates keep the existing business rules (no past start dates; end
date stays SLA-calculated).
"""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.suggestions import accept_suggestion


def _projects(db: Session) -> tuple[models.Project, models.Project]:
    dept = models.Department(name="SAP")
    db.add(dept)
    db.flush()
    ptype = models.ProjectType(name="ERP")
    db.add(ptype)
    db.flush()

    def make(code: str) -> models.Project:
        p = models.Project(name=f"Project {code}", project_code=code, status="Active")
        p.department = dept
        p.project_type = ptype
        db.add(p)
        db.flush()
        return p

    return make("PRJ-H"), make("PRJ-T")


def _enriched_historical_risk(
    db: Session,
    project: models.Project,
    *,
    owner: models.User | None,
    start: dt.date | None,
) -> models.Risk:
    risk = models.Risk(
        project_id=project.id,
        risk_code="RSK-ENRICH-1",
        description="Data migration causes downtime during cutover",
        category="Technical",
        subcategory=None,
        risk_source="Technical",
        likelihood="High",
        impact="High",
        risk_rating="High",
        response_strategy="Mitigate",
        response_plan="Run the migration over the weekend and keep a rollback plan.",
        owner_user_id=owner.id if owner else None,
        identified_during="Execution",
        risk_start_date=start,
        status="Closed",
        source="Historical",
    )
    db.add(risk)
    db.flush()
    return risk


def test_accept_suggestion_copies_enriched_fields(db_session: Session) -> None:
    historical, target = _projects(db_session)
    owner = models.User(upn="risk.owner@example.test", display_name="Risk Owner")
    db_session.add(owner)
    db_session.flush()
    _enriched_historical_risk(
        db_session, historical, owner=owner, start=dt.date.today()
    )

    accepted = accept_suggestion(db_session, target, "RSK-ENRICH-1")

    assert accepted.status == "Open"
    assert accepted.description == "Data migration causes downtime during cutover"
    assert accepted.category == "Technical"
    assert accepted.risk_source == "Technical"
    assert accepted.response_strategy == "Mitigate"
    assert accepted.response_plan == (
        "Run the migration over the weekend and keep a rollback plan."
    )
    assert accepted.identified_during == "Execution"
    assert accepted.owner_user_id == owner.id
    assert accepted.risk_start_date == dt.date.today()
    # End date remains governed by the existing SLA calculation, not invented.
    assert accepted.risk_end_date is not None
    assert accepted.risk_end_date >= accepted.risk_start_date


def test_accept_suggestion_never_copies_past_start_date(db_session: Session) -> None:
    historical, target = _projects(db_session)
    past = dt.date.today() - dt.timedelta(days=30)
    _enriched_historical_risk(db_session, historical, owner=None, start=past)

    accepted = accept_suggestion(db_session, target, "RSK-ENRICH-1")

    # A past start date would violate the app's date rules -> left for the user.
    assert accepted.risk_start_date is None
    assert accepted.risk_end_date is None
    # Non-date enrichment is still copied.
    assert accepted.category == "Technical"
    assert accepted.response_plan is not None


def test_risk_meta_returns_option_sets(client: TestClient, db_session: Session) -> None:
    # A risk using an existing category + lifecycle and a project stage gate.
    dept = models.Department(name="D")
    db_session.add(dept)
    db_session.flush()
    ptype = models.ProjectType(name="T")
    db_session.add(ptype)
    db_session.flush()
    project = models.Project(
        name="Meta project",
        project_code="PRJ-META",
        status="Active",
        stage_gate="Planning",
    )
    project.department = dept
    project.project_type = ptype
    db_session.add(project)
    db_session.flush()
    db_session.add(
        models.Risk(
            project_id=project.id,
            risk_code="RSK-META-1",
            description="meta",
            category="Technical",
            likelihood="Low",
            impact="Low",
            risk_rating="Low",
            status="Closed",
            source="Historical",
            identified_during="Execution",
        )
    )
    db_session.commit()

    resp = client.get("/api/risk-meta")
    assert resp.status_code == 200
    body = resp.json()
    assert "Technical" in body["categories"]
    assert "Execution" in body["lifecycle"]
    assert "Planning" in body["lifecycle"]
    assert body["risk_sources"] == ["Human", "Environmental", "Technical"]
    assert body["response_strategies"] == ["Mitigate", "Transfer", "Avoid", "Accept"]
