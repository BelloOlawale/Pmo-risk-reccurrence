# ruff: noqa: E501
"""Weekly portfolio risk report for the PMO Lead.

The Monday email is a properly structured management report rather than a
handful of KPI numbers: it groups the portfolio by **Project Manager → project →
risk**, summarises each project against the application's real status model, and
lists the risks that genuinely need follow-up.

Role-specific report visibility
-------------------------------
The report is generated from the same query and the same figures for every
recipient; only the *scope* changes with the recipient's role, so nobody ever
sees a risk they are not entitled to see:

* **PMO Lead / System Admin** — the full portfolio (every Project Manager,
  every project, every risk).
* **Project Manager** — only the projects they manage (``pm_user_id`` matches).
  Their copy omits other PMs' sections entirely.
* **Risk Owner / anyone else** — no access to the portfolio report at all; Risk
  Owners act from their own signed, single-risk link.

Idempotency
-----------
``run_weekly_report`` records the business date it last ran in the ``settings``
table, so a Celery Beat retry on the same day does not send the report (or
create duplicate in-app notifications) twice.

Status classification
---------------------
Counts use the application's own statuses, one bucket per status, and never
double-count a risk: ``Open``, ``In Progress``, ``Pending Resolution`` (shown as
"Pending Review"), ``Escalated``, ``Event`` (Materialized), ``Resolved`` and
``Closed``. ``Suggested`` risks (not yet accepted) and ``Dismissed`` risks are
excluded from the counts and reported separately as a note.
"""

from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass, field
from typing import TypedDict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from riskapp import branding, models
from riskapp.domain.status import RiskStatus
from riskapp.notifications import (
    EVENT_WEEKLY_SUMMARY,
    NotificationService,
    Recipients,
)

# Statuses that make up the report. One bucket each — no overlap.
OPEN = RiskStatus.OPEN.value
IN_PROGRESS = RiskStatus.IN_PROGRESS.value
PENDING_REVIEW = RiskStatus.PENDING_RESOLUTION.value
ESCALATED = RiskStatus.ESCALATED.value
EVENT = RiskStatus.EVENT.value
RESOLVED = RiskStatus.RESOLVED.value
CLOSED = RiskStatus.CLOSED.value
SUGGESTED = RiskStatus.SUGGESTED.value
DISMISSED = RiskStatus.DISMISSED.value

IN_SCOPE_STATUSES: tuple[str, ...] = (
    OPEN,
    IN_PROGRESS,
    PENDING_REVIEW,
    ESCALATED,
    EVENT,
    RESOLVED,
    CLOSED,
)

# Ordered (label, status) columns for the per-project summary table.
SUMMARY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("Open", OPEN),
    ("In Progress", IN_PROGRESS),
    ("Pending Review", PENDING_REVIEW),
    ("Escalated", ESCALATED),
    ("Events", EVENT),
    ("Resolved", RESOLVED),
    ("Closed", CLOSED),
)

# Statuses whose risk is still live and can therefore be "overdue".
_OVERDUE_STATUSES = (OPEN, IN_PROGRESS, ESCALATED)

LONG_SUMMARY_LIMIT = 240


@dataclass
class RiskRow:
    """One risk as shown in the report's detail tables."""

    id: int
    risk_code: str
    description: str
    owner_name: str
    status: str
    risk_rating: str
    risk_end_date: dt.date | None
    resolution_summary: str | None
    awaiting_review: bool = False
    overdue: bool = False

    @property
    def url(self) -> str:
        return f"{settings_app_base()}/risks/{self.id}"


@dataclass
class ProjectReport:
    """A single project and its risks within the report."""

    id: int
    project_code: str
    name: str
    customer: str | None
    counts: dict[str, int] = field(default_factory=dict)
    risks: list[RiskRow] = field(default_factory=list)
    attention: list[RiskRow] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass
class PmReport:
    """All projects for one Project Manager (or the unassigned bucket)."""

    user_id: int | None
    name: str
    email: str | None
    projects: list[ProjectReport] = field(default_factory=list)

    @property
    def totals(self) -> dict[str, int]:
        totals = {status: 0 for _, status in SUMMARY_COLUMNS}
        for project in self.projects:
            for status, value in project.counts.items():
                totals[status] = totals.get(status, 0) + value
        return totals


@dataclass
class PortfolioReport:
    """The generated weekly report (scoped to the recipient)."""

    generated_at: dt.datetime
    period_start: dt.date
    period_end: dt.date
    sections: list[PmReport]
    totals: dict[str, int]
    total_projects: int
    total_risks: int
    excluded_suggested: int
    excluded_dismissed: int
    resolved_this_period: int
    scope_label: str = "Portfolio"

    @property
    def attention(self) -> list[tuple[PmReport, ProjectReport, RiskRow]]:
        rows: list[tuple[PmReport, ProjectReport, RiskRow]] = []
        for section in self.sections:
            for project in section.projects:
                for risk in project.attention:
                    rows.append((section, project, risk))
        return rows


def settings_app_base() -> str:
    """The configured application base URL (never a hardcoded dev origin)."""
    from riskapp.config import settings

    return settings.app_base_url.rstrip("/")


def _period_bounds(today: dt.date) -> tuple[dt.date, dt.date]:
    """The trailing seven-day reporting window ending on ``today``."""
    return today - dt.timedelta(days=6), today


def _risk_row(risk: models.Risk, today: dt.date) -> RiskRow:
    owner = risk.owner
    overdue = (
        risk.status in _OVERDUE_STATUSES
        and risk.risk_end_date is not None
        and risk.risk_end_date < today
    )
    return RiskRow(
        id=risk.id,
        risk_code=risk.risk_code,
        description=risk.description or "",
        owner_name=(owner.display_name if owner else "Unassigned"),
        status=risk.status,
        risk_rating=risk.risk_rating,
        risk_end_date=risk.risk_end_date,
        resolution_summary=risk.resolution_summary,
        awaiting_review=risk.status == PENDING_REVIEW,
        overdue=overdue,
    )


def build_weekly_report(
    db: Session,
    *,
    scope_pm_user_id: int | None = None,
    today: dt.date | None = None,
) -> PortfolioReport:
    """Build the weekly report from live data.

    ``scope_pm_user_id`` restricts the report to one Project Manager's projects
    (used for the PM's own copy). ``None`` builds the full portfolio.
    """
    if today is None:
        today = dt.date.today()
    period_start, period_end = _period_bounds(today)

    stmt = select(models.Project).options(
        selectinload(models.Project.pm_user),
        selectinload(models.Project.risks).selectinload(models.Risk.owner),
    )
    if scope_pm_user_id is not None:
        stmt = stmt.where(models.Project.pm_user_id == scope_pm_user_id)

    projects = db.scalars(stmt.order_by(models.Project.name)).all()

    sections: dict[int | None, PmReport] = {}
    totals = {status: 0 for _, status in SUMMARY_COLUMNS}
    excluded_suggested = 0
    excluded_dismissed = 0
    resolved_this_period = 0
    total_projects = 0

    for project in projects:
        total_projects += 1
        in_scope = [r for r in project.risks if r.status in IN_SCOPE_STATUSES]
        for risk in project.risks:
            if risk.status == SUGGESTED:
                excluded_suggested += 1
            elif risk.status == DISMISSED:
                excluded_dismissed += 1
        if (
            project.pm_user_id is not None
            and project.pm_user is not None
            and project.pm_user.is_external
        ):
            # Defensive: PMs must be staff. Treat an external PM as unassigned.
            pm = None
        else:
            pm = project.pm_user

        counts = {status: 0 for _, status in SUMMARY_COLUMNS}
        rows: list[RiskRow] = []
        for risk in in_scope:
            counts[risk.status] = counts.get(risk.status, 0) + 1
            totals[risk.status] = totals.get(risk.status, 0) + 1
            row = _risk_row(risk, today)
            rows.append(row)
            if risk.resolved_date is not None:
                resolved_on = (
                    risk.resolved_date.date()
                    if isinstance(risk.resolved_date, dt.datetime)
                    else risk.resolved_date
                )
                if period_start <= resolved_on <= period_end:
                    resolved_this_period += 1

        attention = [
            r
            for r in rows
            if r.overdue or r.awaiting_review or r.status in (ESCALATED, EVENT)
        ]
        attention.sort(key=lambda r: (not r.overdue, r.status, r.risk_code))
        rows.sort(key=lambda r: (r.status, r.risk_code))

        pm_key = pm.id if pm is not None else None
        section = sections.get(pm_key)
        if section is None:
            section = PmReport(
                user_id=pm.id if pm is not None else None,
                name=pm.display_name if pm is not None else "Unassigned Project Manager",
                email=pm.upn if pm is not None else None,
            )
            sections[pm_key] = section
        section.projects.append(
            ProjectReport(
                id=project.id,
                project_code=project.project_code,
                name=project.name,
                customer=project.customer,
                counts=counts,
                risks=rows,
                attention=attention,
            )
        )

    ordered = sorted(
        sections.values(),
        key=lambda s: (s.user_id is None, (s.name or "").lower()),
    )
    for section in ordered:
        section.projects.sort(key=lambda p: p.name.lower())

    total_risks = sum(totals.values())
    return PortfolioReport(
        generated_at=dt.datetime.now(dt.UTC),
        period_start=period_start,
        period_end=period_end,
        sections=ordered,
        totals=totals,
        total_projects=total_projects,
        total_risks=total_risks,
        excluded_suggested=excluded_suggested,
        excluded_dismissed=excluded_dismissed,
        resolved_this_period=resolved_this_period,
        scope_label="Your projects" if scope_pm_user_id is not None else "Portfolio",
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

_BLUE = branding.BRAND_BLUE
_BLUE_DARK = branding.BRAND_BLUE_DARK
_RED = branding.BRAND_RED
_TEXT = "#111827"
_MUTED = "#64748B"
_BORDER = "#E2E8F0"
_HEAD_BG = "#F1F5F9"


def _fmt_date(value: dt.date | dt.datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d %b %Y")


def _fmt_datetime(value: dt.datetime) -> str:
    return value.strftime("%d %b %Y, %H:%M UTC")


def _truncate(text: str | None, limit: int = LONG_SUMMARY_LIMIT) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return "—"
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 1].rstrip() + "…"


def _status_label(status: str) -> str:
    """User-facing label for a status (Event reads as Materialized)."""
    if status == EVENT:
        return "Materialized"
    if status == PENDING_REVIEW:
        return "Pending Review"
    return status


def _rating_color(rating: str) -> str:
    return {"High": "#DC2626", "Medium": "#F97316", "Low": "#16A34A"}.get(rating, _MUTED)


def _cell(
    content: str,
    *,
    align: str = "left",
    color: str = _TEXT,
    weight: str = "400",
    size: str = "13px",
    padding: str = "8px 10px",
    bg: str = "#FFFFFF",
) -> str:
    return (
        f'<td style="padding:{padding};text-align:{align};color:{color};'
        f'font-weight:{weight};font-size:{size};background:{bg};'
        f'border-bottom:1px solid {_BORDER};vertical-align:top;">{content}</td>'
    )


def _metrics_table(report: PortfolioReport) -> str:
    metrics = [
        ("Projects covered", report.total_projects),
        ("Risks in scope", report.total_risks),
        ("Open", report.totals.get(OPEN, 0)),
        ("In Progress", report.totals.get(IN_PROGRESS, 0)),
        ("Pending Review", report.totals.get(PENDING_REVIEW, 0)),
        ("Escalated", report.totals.get(ESCALATED, 0)),
        ("Events / Materialized", report.totals.get(EVENT, 0)),
        ("Resolved", report.totals.get(RESOLVED, 0)),
        ("Closed", report.totals.get(CLOSED, 0)),
        ("Resolved this period", report.resolved_this_period),
    ]
    cells = []
    for label, value in metrics:
        color = _RED if label in ("Escalated", "Events / Materialized") and value else _BLUE_DARK
        cells.append(
            '<td style="width:33.33%;padding:10px 12px;vertical-align:top;">'
            f'<div style="font-size:12px;color:{_MUTED};text-transform:uppercase;'
            'letter-spacing:0.04em;">'
            f"{html.escape(label)}</div>"
            f'<div style="font-size:20px;font-weight:700;color:{color};margin-top:2px;">'
            f"{value}</div></td>"
        )
    rows = "".join(
        "<tr>" + "".join(cells[i : i + 3]) + "</tr>" for i in range(0, len(cells), 3)
    )
    return (
        '<table role="presentation" width="100%" '
        f'style="border-collapse:collapse;">{rows}</table>'
    )


def _project_summary_table(project: ProjectReport) -> str:
    header = "".join(
        _cell(
            html.escape(label),
            align="center",
            color="#FFFFFF",
            weight="700",
            size="12px",
            bg=_BLUE,
        )
        for label, _ in SUMMARY_COLUMNS
    )
    values = "".join(
        _cell(str(project.counts.get(status, 0)), align="center", size="13px")
        for _, status in SUMMARY_COLUMNS
    )
    return (
        '<table role="presentation" width="100%" style="border-collapse:collapse;'
        'margin:6px 0 4px;">'
        f'<tr>{_cell("Project", color="#FFFFFF", weight="700", size="12px", bg=_BLUE)}'
        f"{header}</tr>"
        f'<tr>{_cell(html.escape(project.name), weight="600")}{values}</tr>'
        "</table>"
    )


def _risk_detail_table(project: ProjectReport) -> str:
    headers = [
        ("Risk Code", "left"),
        ("Risk Description", "left"),
        ("Risk Owner", "left"),
        ("Current Status", "left"),
        ("Rating", "center"),
        ("Risk End Date", "left"),
        ("Resolution Summary", "left"),
    ]
    head = "".join(
        _cell(
            html.escape(label),
            align=align,
            color="#FFFFFF",
            weight="700",
            size="12px",
            bg=_BLUE_DARK,
        )
        for label, align in headers
    )
    body_rows = []
    for risk in project.attention:
        summary = _truncate(risk.resolution_summary)
        link = html.escape(risk.url, quote=True)
        code = (
            f'<a href="{link}" style="color:{_BLUE};text-decoration:none;font-weight:700;">'
            f"{html.escape(risk.risk_code)}</a>"
        )
        status_color = _RED if risk.status in (ESCALATED, EVENT) else _TEXT
        body_rows.append(
            "<tr>"
            + _cell(code)
            + _cell(html.escape(_truncate(risk.description, 160)))
            + _cell(html.escape(risk.owner_name))
            + _cell(html.escape(_status_label(risk.status)), color=status_color, weight="600")
            + _cell(
                html.escape(risk.risk_rating),
                align="center",
                color=_rating_color(risk.risk_rating),
                weight="700",
            )
            + _cell(html.escape(_fmt_date(risk.risk_end_date)))
            + _cell(html.escape(summary))
            + "</tr>"
        )
    return (
        '<table role="presentation" width="100%" style="border-collapse:collapse;'
        'margin:4px 0 12px;table-layout:fixed;word-wrap:break-word;">'
        f"<tr>{head}</tr>{''.join(body_rows)}</table>"
    )


def render_html(report: PortfolioReport) -> str:
    """Render the report as a self-contained, inline-styled HTML email."""
    attention = report.attention
    clean_sections = [s for s in report.sections if s.projects]

    # Executive summary
    exec_rows = []
    escalated = report.totals.get(ESCALATED, 0)
    events = report.totals.get(EVENT, 0)
    pending = report.totals.get(PENDING_REVIEW, 0)
    exec_rows.append(
        f"This week the portfolio covers <strong>{report.total_projects}</strong> "
        f"project(s) and <strong>{report.total_risks}</strong> risk(s) in the managed "
        f"lifecycle. <strong>{report.totals.get(OPEN, 0)}</strong> are open, "
        f"<strong>{report.totals.get(IN_PROGRESS, 0)}</strong> in progress, "
        f"<strong>{pending}</strong> awaiting Project Manager review, "
        f"<strong>{escalated}</strong> escalated and <strong>{events}</strong> "
        f"materialized as events."
    )

    # PM sections
    sections_html = []
    for section in clean_sections:
        project_blocks = []
        for project in section.projects:
            block = [
                f'<div style="font-size:14px;font-weight:700;color:{_TEXT};'
                f'margin:14px 0 2px;">{html.escape(project.name)}'
                f'<span style="color:{_MUTED};font-weight:400;"> '
                f"({html.escape(project.project_code)})</span></div>"
            ]
            block.append(_project_summary_table(project))
            if project.attention:
                block.append(
                    f'<div style="font-size:12px;color:{_RED};font-weight:700;'
                    'text-transform:uppercase;letter-spacing:0.04em;margin:8px 0 2px;">'
                    "Risks requiring attention</div>"
                )
                block.append(_risk_detail_table(project))
            else:
                block.append(
                    f'<div style="font-size:12px;color:{_MUTED};margin:2px 0 10px;">'
                    "No risks currently require attention.</div>"
                )
            project_blocks.append("".join(block))
        sections_html.append(
            f'<tr><td style="padding:18px 0 4px;">'
            f'<div style="font-size:16px;font-weight:800;color:{_BLUE};'
            f'border-bottom:2px solid {_BLUE};padding-bottom:4px;">'
            f"{html.escape(section.name)}"
            + (
                f'<span style="font-size:12px;color:{_MUTED};font-weight:400;"> '
                f"· {html.escape(section.email)}</span>"
                if section.email
                else ""
            )
            + "</div>"
            + "".join(project_blocks)
            + "</td></tr>"
        )

    if not clean_sections:
        sections_html.append(
            f'<tr><td style="padding:18px 0;">'
            f'<div style="color:{_MUTED};font-size:14px;">'
            "No projects are in scope for this report.</div></td></tr>"
        )

    # Attention index
    if attention:
        attention_items = []
        for section, project, risk in attention:
            reasons = []
            if risk.overdue:
                reasons.append("overdue")
            if risk.awaiting_review:
                reasons.append("awaiting review")
            if risk.status == ESCALATED:
                reasons.append("escalated")
            if risk.status == EVENT:
                reasons.append("materialized")
            reason_text = ", ".join(reasons)
            link = html.escape(risk.url, quote=True)
            attention_items.append(
                "<li style=\"margin:0 0 6px;font-size:13px;color:"
                + _TEXT
                + ';">'
                f'<strong>{html.escape(risk.risk_code)}</strong> — '
                f"{html.escape(_truncate(risk.description, 120))} "
                f'<span style="color:{_MUTED};">· {html.escape(project.name)} · '
                f"{html.escape(section.name)} · {html.escape(reason_text)}</span> "
                f'<a href="{link}" style="color:{_BLUE};font-weight:600;">Open risk</a>'
                "</li>"
            )
        attention_html = (
            f'<tr><td style="padding:20px 0 4px;">'
            f'<div style="font-size:16px;font-weight:800;color:{_RED};'
            f'border-bottom:2px solid {_RED};padding-bottom:4px;">'
            "Items Requiring Attention</div>"
            f'<ul style="margin:10px 0 0;padding-left:18px;">'
            + "".join(attention_items)
            + "</ul></td></tr>"
        )
    else:
        attention_html = (
            f'<tr><td style="padding:20px 0 4px;">'
            f'<div style="font-size:16px;font-weight:800;color:{_BLUE};'
            f'border-bottom:2px solid {_BLUE};padding-bottom:4px;">'
            "Items Requiring Attention</div>"
            f'<div style="font-size:13px;color:{_MUTED};margin-top:10px;">'
            "No overdue, escalated, materialized or pending-review risks this "
            "period.</div></td></tr>"
        )

    excluded_note = ""
    if report.excluded_suggested or report.excluded_dismissed:
        excluded_note = (
            f'<div style="font-size:12px;color:{_MUTED};margin-top:8px;">'
            f"Not counted: {report.excluded_suggested} suggested and "
            f"{report.excluded_dismissed} dismissed risk(s).</div>"
        )

    cta_url = html.escape(settings_app_base(), quote=True)
    return f"""\
<!doctype html>
<html>
<body style="margin:0;padding:0;background:#F8FAFC;">
<table role="presentation" width="100%" style="border-collapse:collapse;background:#F8FAFC;">
<tr><td align="center" style="padding:20px 10px;">
<table role="presentation" width="100%" style="max-width:720px;border-collapse:collapse;background:#FFFFFF;border:1px solid {_BORDER};">
  <tr><td style="border-top:4px solid {_RED};padding:20px 24px 0;font-family:'Segoe UI',Arial,sans-serif;">
    <div style="font-size:17px;font-weight:600;letter-spacing:0.12em;color:{_BLUE};">{branding.BRAND_LINE_1}</div>
    <div style="font-size:22px;font-weight:800;letter-spacing:0.03em;color:{_BLUE_DARK};">{branding.BRAND_LINE_2}</div>
    <div style="font-size:18px;font-weight:700;color:{_TEXT};margin-top:14px;">Weekly Portfolio Risk Report</div>
    <div style="font-size:13px;color:{_MUTED};margin-top:2px;">
      Reporting period: { _fmt_date(report.period_start) } – { _fmt_date(report.period_end) } &nbsp;·&nbsp;
      Generated: { _fmt_datetime(report.generated_at) }
    </div>
  </td></tr>
  <tr><td style="padding:16px 24px 0;font-family:'Segoe UI',Arial,sans-serif;">
    <div style="font-size:14px;font-weight:700;color:{_BLUE};text-transform:uppercase;letter-spacing:0.05em;">Executive Summary</div>
    <p style="font-size:14px;line-height:1.55;color:{_TEXT};margin:8px 0 14px;">{exec_rows[0]}</p>
    <table role="presentation" width="100%" style="border-collapse:collapse;background:#F8FAFC;border:1px solid {_BORDER};">
      <tr><td style="padding:6px 10px;">{_metrics_table(report)}</td></tr>
    </table>
    {excluded_note}
  </td></tr>
  <tr><td style="padding:0 24px;font-family:'Segoe UI',Arial,sans-serif;">
    <table role="presentation" width="100%" style="border-collapse:collapse;">
      {''.join(sections_html)}
      {attention_html}
    </table>
  </td></tr>
  <tr><td style="padding:20px 24px 26px;font-family:'Segoe UI',Arial,sans-serif;">
    <p style="font-size:14px;line-height:1.55;color:{_TEXT};margin:0 0 14px;">
      Please review the outstanding risks above and follow up on the items requiring
      attention with the responsible Project Managers. Risks awaiting review should
      be accepted or returned promptly so the Risk Owner can continue working them.
    </p>
    <a href="{cta_url}"
       style="display:inline-block;background:{_RED};color:#FFFFFF;text-decoration:none;
              padding:12px 22px;border-radius:6px;font-weight:700;font-size:14px;">
      Open {branding.PRODUCT_NAME}
    </a>
    <p style="font-size:12px;color:{_MUTED};margin-top:18px;">
      This report was generated automatically from live {branding.PRODUCT_NAME} data.
    </p>
  </td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def render_text(report: PortfolioReport) -> str:
    """Plain-text fallback for clients that block HTML."""
    lines = [
        f"{branding.BRAND_LINE_1} {branding.BRAND_LINE_2}",
        "Weekly Portfolio Risk Report",
        f"Reporting period: {_fmt_date(report.period_start)} - {_fmt_date(report.period_end)}",
        f"Generated: {_fmt_datetime(report.generated_at)}",
        "",
        "EXECUTIVE SUMMARY",
        f"Projects covered: {report.total_projects}",
        f"Risks in scope: {report.total_risks}",
        f"Open: {report.totals.get(OPEN, 0)} | In Progress: {report.totals.get(IN_PROGRESS, 0)}"
        f" | Pending Review: {report.totals.get(PENDING_REVIEW, 0)}"
        f" | Escalated: {report.totals.get(ESCALATED, 0)}"
        f" | Events: {report.totals.get(EVENT, 0)}"
        f" | Resolved: {report.totals.get(RESOLVED, 0)}"
        f" | Closed: {report.totals.get(CLOSED, 0)}",
        "",
    ]
    for section in report.sections:
        if not section.projects:
            continue
        lines.append(f"== {section.name} ==")
        for project in section.projects:
            lines.append(f"-- {project.name} ({project.project_code})")
            counts = " | ".join(
                f"{label}: {project.counts.get(status, 0)}"
                for label, status in SUMMARY_COLUMNS
            )
            lines.append(f"   {counts}")
            for risk in project.attention:
                lines.append(
                    f"   * {risk.risk_code} [{_status_label(risk.status)}] "
                    f"{_truncate(risk.description, 120)} — owner {risk.owner_name}, "
                    f"rating {risk.risk_rating}, end {_fmt_date(risk.risk_end_date)}"
                )
                if risk.resolution_summary:
                    lines.append(
                        f"     Resolution: {_truncate(risk.resolution_summary)}"
                    )
                lines.append(f"     {risk.url}")
        lines.append("")
    attention = report.attention
    lines.append("ITEMS REQUIRING ATTENTION")
    if attention:
        for section, project, risk in attention:
            lines.append(
                f"- {risk.risk_code} ({project.name}, {section.name}): "
                f"{_status_label(risk.status)} — {risk.url}"
            )
    else:
        lines.append("None this period.")
    lines.append("")
    lines.append(f"Open {branding.PRODUCT_NAME}: {settings_app_base()}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------

_LAST_RUN_SETTING = "last_weekly_report_on"


class WeeklyTotals(TypedDict):
    """Compact, typed total payload returned by :func:`run_weekly_report`."""

    skipped: bool
    total: int
    open: int
    in_progress: int
    pending_review: int
    escalated: int
    events: int
    resolved: int
    closed: int


def _get_setting(db: Session, key: str) -> str | None:
    value = db.scalar(select(models.Setting.value).where(models.Setting.key == key))
    return value or None


def _set_setting(db: Session, key: str, value: str) -> None:
    row = db.scalar(select(models.Setting).where(models.Setting.key == key))
    if row is None:
        db.add(models.Setting(key=key, value=value))
    else:
        row.value = value


def _totals_payload(
    report: PortfolioReport, *, skipped: bool = False
) -> WeeklyTotals:
    return {
        "skipped": skipped,
        "total": report.total_risks,
        "open": report.totals.get(OPEN, 0),
        "in_progress": report.totals.get(IN_PROGRESS, 0),
        "pending_review": report.totals.get(PENDING_REVIEW, 0),
        "escalated": report.totals.get(ESCALATED, 0),
        "events": report.totals.get(EVENT, 0),
        "resolved": report.totals.get(RESOLVED, 0),
        "closed": report.totals.get(CLOSED, 0),
    }


def run_weekly_report(
    db: Session,
    notifier: NotificationService,
    *,
    today: dt.date | None = None,
    force: bool = False,
) -> WeeklyTotals:
    """Send the weekly portfolio report and scoped copies to every PM.

    Recipients and visibility:

    * the PMO Lead receives the full portfolio report (when ``pmo_lead_email``
      is configured);
    * each Project Manager receives a copy scoped to their own projects only.

    Idempotent per business day unless ``force`` is set, so a Celery Beat retry
    neither re-sends the report nor duplicates in-app notifications.
    """
    if today is None:
        today = dt.date.today()

    if not force and _get_setting(db, _LAST_RUN_SETTING) == today.isoformat():
        report = build_weekly_report(db, today=today)
        return _totals_payload(report, skipped=True)

    full = build_weekly_report(db, today=today)
    subject = (
        f"{branding.PRODUCT_NAME} — Weekly Portfolio Risk Report "
        f"({_fmt_date(full.period_end)})"
    )
    body = (
        f"Weekly portfolio risk report: {full.total_projects} project(s), "
        f"{full.total_risks} risk(s) in scope, "
        f"{full.totals.get(ESCALATED, 0)} escalated, "
        f"{full.totals.get(EVENT, 0)} materialized."
    )

    pmo_email = _get_setting(db, "pmo_lead_email")
    if pmo_email:
        notifier.notify_recipients(
            db,
            event=EVENT_WEEKLY_SUMMARY,
            title=subject,
            body=body,
            recipients=Recipients(to_user_ids=(), to_emails=(pmo_email,), cc_emails=()),
            email_body=render_html(full),
            email_text=render_text(full),
        )

    for section in full.sections:
        if section.user_id is None or not section.email:
            continue
        scoped = build_weekly_report(db, scope_pm_user_id=section.user_id, today=today)
        notifier.notify_recipients(
            db,
            event=EVENT_WEEKLY_SUMMARY,
            title=f"{branding.PRODUCT_NAME} — Weekly Risk Report (your projects)",
            body=(
                f"Your weekly risk report: {scoped.total_projects} project(s), "
                f"{scoped.total_risks} risk(s) in scope."
            ),
            recipients=Recipients(
                to_user_ids=(section.user_id,),
                to_emails=(section.email,),
                cc_emails=(),
            ),
            email_body=render_html(scoped),
            email_text=render_text(scoped),
        )

    _set_setting(db, _LAST_RUN_SETTING, today.isoformat())
    db.commit()
    return _totals_payload(full)
