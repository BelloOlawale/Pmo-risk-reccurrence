"""Weekly portfolio report: grouping, reconciliation, scoping and delivery."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.notifications import NotificationService
from riskapp.reports import (
    CLOSED,
    DISMISSED,
    ESCALATED,
    EVENT,
    IN_PROGRESS,
    OPEN,
    PENDING_REVIEW,
    RESOLVED,
    SUGGESTED,
    build_weekly_report,
    render_html,
    render_text,
    run_weekly_report,
)

TODAY = dt.date(2026, 10, 14)
APP_BASE = "https://risk.example.com"


class FakeEmail:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send_email(self, *, to, cc=None, subject, body_html, body_text=None) -> None:
        self.sent.append(
            {
                "to": list(to),
                "cc": cc,
                "subject": subject,
                "body_html": body_html,
                "body_text": body_text,
            }
        )


def _pm(db: Session, name: str) -> models.User:
    user = models.User(upn=f"{name.lower().replace(' ', '.')}@wragby.com", display_name=name)
    db.add(user)
    db.flush()
    return user


def _project(
    db: Session, name: str, pm: models.User | None, *, code: str | None = None
) -> models.Project:
    dept = models.Department(name=f"D-{name}")
    ptype = models.ProjectType(name=f"T-{name}")
    db.add_all([dept, ptype])
    db.flush()
    project = models.Project(
        name=name,
        project_code=code or f"PRJ-{name}",
        status="Active",
        pm_user_id=pm.id if pm else None,
    )
    project.department = dept
    project.project_type = ptype
    db.add(project)
    db.flush()
    return project


def _risk(
    db: Session,
    project: models.Project,
    *,
    code: str,
    status: str = OPEN,
    rating: str = "High",
    end: dt.date | None = None,
    desc: str | None = None,
    summary: str | None = None,
    resolved_date: dt.datetime | None = None,
    owner: models.User | None = None,
) -> models.Risk:
    risk = models.Risk(
        project_id=project.id,
        risk_code=code,
        description=desc or f"risk {code}",
        likelihood="High",
        impact="High",
        risk_rating=rating,
        status=status,
        risk_end_date=end,
        resolution_summary=summary,
        resolved_date=resolved_date,
        owner_user_id=owner.id if owner else None,
    )
    db.add(risk)
    db.commit()
    return risk


def test_report_groups_by_pm_then_project(db_session: Session) -> None:
    alice = _pm(db_session, "Alice PM")
    bob = _pm(db_session, "Bob PM")
    pa1 = _project(db_session, "Alpha", alice)
    pa2 = _project(db_session, "Bravo", alice)
    pb1 = _project(db_session, "Charlie", bob)
    _risk(db_session, pa1, code="RSK-1", status=OPEN)
    _risk(db_session, pa1, code="RSK-2", status=IN_PROGRESS)
    _risk(db_session, pa2, code="RSK-3", status=RESOLVED)
    _risk(db_session, pb1, code="RSK-4", status=ESCALATED)

    report = build_weekly_report(db_session, today=TODAY)

    assert [s.name for s in report.sections] == ["Alice PM", "Bob PM"]
    alice_section = report.sections[0]
    assert [p.name for p in alice_section.projects] == ["Alpha", "Bravo"]
    assert alice_section.projects[0].counts[OPEN] == 1
    assert alice_section.projects[0].counts[IN_PROGRESS] == 1
    assert alice_section.projects[1].counts[RESOLVED] == 1


def test_totals_reconcile_with_project_counts(db_session: Session) -> None:
    pm = _pm(db_session, "Pat PM")
    project = _project(db_session, "Recon", pm)
    for i, status in enumerate(
        [OPEN, IN_PROGRESS, PENDING_REVIEW, ESCALATED, EVENT, RESOLVED, CLOSED]
    ):
        _risk(db_session, project, code=f"RSK-R{i}", status=status)

    report = build_weekly_report(db_session, today=TODAY)

    per_bucket = sum(report.totals.values())
    per_project = sum(p.total for s in report.sections for p in s.projects)
    assert per_bucket == 7
    assert per_project == per_bucket == report.total_risks


def test_suggested_and_dismissed_are_excluded(db_session: Session) -> None:
    pm = _pm(db_session, "Ex PM")
    project = _project(db_session, "Exclusions", pm)
    _risk(db_session, project, code="RSK-O", status=OPEN)
    _risk(db_session, project, code="RSK-S", status=SUGGESTED)
    _risk(db_session, project, code="RSK-D", status=DISMISSED)

    report = build_weekly_report(db_session, today=TODAY)
    assert report.total_risks == 1
    assert report.excluded_suggested == 1
    assert report.excluded_dismissed == 1


def test_pm_scope_only_includes_their_projects(db_session: Session) -> None:
    alice = _pm(db_session, "Alice PM")
    bob = _pm(db_session, "Bob PM")
    _risk(
        db_session,
        _project(db_session, "Alpha", alice),
        code="RSK-A",
        status=OPEN,
    )
    _risk(
        db_session,
        _project(db_session, "Bravo", bob),
        code="RSK-B",
        status=OPEN,
    )

    scoped = build_weekly_report(db_session, scope_pm_user_id=alice.id, today=TODAY)
    names = [p.name for s in scoped.sections for p in s.projects]
    assert names == ["Alpha"]


def test_attention_items_flag_overdue_review_escalated_and_event(
    db_session: Session,
) -> None:
    pm = _pm(db_session, "Att PM")
    project = _project(db_session, "Attention", pm)
    _risk(db_session, project, code="RSK-OVER", status=OPEN, end=dt.date(2026, 10, 1))
    _risk(db_session, project, code="RSK-REV", status=PENDING_REVIEW, end=dt.date(2026, 11, 1))
    _risk(db_session, project, code="RSK-ESC", status=ESCALATED, end=dt.date(2026, 11, 1))
    _risk(db_session, project, code="RSK-EVT", status=EVENT, end=dt.date(2026, 10, 5))
    _risk(db_session, project, code="RSK-OK", status=OPEN, end=dt.date(2026, 11, 1))

    report = build_weekly_report(db_session, today=TODAY)
    flagged = {r.risk_code for _, _, r in report.attention}
    assert flagged == {"RSK-OVER", "RSK-REV", "RSK-ESC", "RSK-EVT"}
    overdue = next(r for _, _, r in report.attention if r.risk_code == "RSK-OVER")
    assert overdue.overdue is True


def test_html_escapes_user_supplied_content(db_session: Session) -> None:
    pm = _pm(db_session, "XSS PM")
    project = _project(db_session, "Escape", pm)
    _risk(
        db_session,
        project,
        code="RSK-X",
        status=PENDING_REVIEW,
        end=dt.date(2026, 10, 1),
        desc="<script>alert('x')</script>",
        summary="<img src=x onerror=alert(1)>",
    )

    report = build_weekly_report(db_session, today=TODAY)
    page = render_html(report)
    assert "<script>alert('x')</script>" not in page
    assert "&lt;script&gt;" in page
    assert "<img src=x onerror" not in page


def test_html_uses_branding_and_configured_app_url(
    db_session: Session, monkeypatch
) -> None:
    from riskapp.config import settings

    monkeypatch.setattr(settings, "app_base_url", APP_BASE)
    pm = _pm(db_session, "Brand PM")
    project = _project(db_session, "Brand", pm)
    # A pending-review risk is an attention item, so its detail link is rendered.
    _risk(db_session, project, code="RSK-BR", status=PENDING_REVIEW, end=dt.date(2026, 10, 1))

    report = build_weekly_report(db_session, today=TODAY)
    page = render_html(report)
    text = render_text(report)
    assert "PMO RISK" in page and "INTELLIGENCE" in page
    assert "PMO Risk Intelligence" in page
    assert f"{APP_BASE}/risks/" in page
    assert APP_BASE in text


def test_run_weekly_report_is_idempotent_per_day(db_session: Session) -> None:
    pm = _pm(db_session, "Idem PM")
    _risk(db_session, _project(db_session, "Idem", pm), code="RSK-ID", status=OPEN)
    email = FakeEmail()
    notifier = NotificationService(email)

    first = run_weekly_report(db_session, notifier, today=TODAY)
    assert first["skipped"] is False
    sent_after_first = len(email.sent)

    second = run_weekly_report(db_session, notifier, today=TODAY)
    assert second["skipped"] is True
    assert len(email.sent) == sent_after_first  # no duplicate email

    marker = db_session.scalar(
        select(models.Setting.value).where(models.Setting.key == "last_weekly_report_on")
    )
    assert marker == TODAY.isoformat()

    # Forcing a resend is possible when explicitly requested.
    third = run_weekly_report(db_session, notifier, today=TODAY, force=True)
    assert third["skipped"] is False
    assert len(email.sent) > sent_after_first


def test_pm_receives_only_their_own_projects(db_session: Session) -> None:
    alice = _pm(db_session, "Alice PM")
    bob = _pm(db_session, "Bob PM")
    _risk(db_session, _project(db_session, "AlphaSecret", alice), code="RSK-AA", status=OPEN)
    _risk(db_session, _project(db_session, "BravoSecret", bob), code="RSK-BB", status=OPEN)
    db_session.add(models.Setting(key="pmo_lead_email", value="pmo@wragby.com"))
    db_session.commit()

    email = FakeEmail()
    run_weekly_report(db_session, NotificationService(email), today=TODAY, force=True)

    alice_mail = next(m for m in email.sent if alice.upn in m["to"])
    bob_mail = next(m for m in email.sent if bob.upn in m["to"])
    assert "AlphaSecret" in alice_mail["body_html"]
    assert "BravoSecret" not in alice_mail["body_html"]
    assert "BravoSecret" in bob_mail["body_html"]
    assert "AlphaSecret" not in bob_mail["body_html"]

    pmo_mail = next(m for m in email.sent if "pmo@wragby.com" in m["to"])
    assert "AlphaSecret" in pmo_mail["body_html"]
    assert "BravoSecret" in pmo_mail["body_html"]


def _headers(user_id: int | None, role: str) -> dict[str, str]:
    headers = {"X-User-Role": role}
    if user_id is not None:
        headers["X-User-Id"] = str(user_id)
    return headers


def test_weekly_report_api_scope_by_role(client: TestClient, db_session: Session) -> None:
    alice = _pm(db_session, "Alice PM")
    bob = _pm(db_session, "Bob PM")
    _risk(db_session, _project(db_session, "AlphaApi", alice), code="RSK-AA", status=OPEN)
    _risk(db_session, _project(db_session, "BravoApi", bob), code="RSK-BB", status=OPEN)

    full = client.get("/api/reports/weekly", headers=_headers(None, "PMO Lead"))
    assert full.status_code == 200
    assert "AlphaApi" in full.json()["html"]
    assert "BravoApi" in full.json()["html"]
    assert full.json()["scope"] == "Portfolio"

    scoped = client.get("/api/reports/weekly", headers=_headers(alice.id, "Project Manager"))
    assert scoped.status_code == 200
    assert "AlphaApi" in scoped.json()["html"]
    assert "BravoApi" not in scoped.json()["html"]
    assert scoped.json()["scope"] == "Your projects"

    forbidden = client.post(
        "/api/reports/weekly/send", headers=_headers(alice.id, "Project Manager")
    )
    assert forbidden.status_code == 403
