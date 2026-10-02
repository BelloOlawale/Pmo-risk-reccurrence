"""Notification layer: recipient matrix, in-app rows, and email.

SPEC §9. Email is optional and injectable (the scheduler and suggestion flows
never hard-depend on Azure Communication Services), while in-app notifications
are always recorded so the React bell has data to show. The recipient matrix is
a pure function so it is exhaustively unit-tested.
"""

from __future__ import annotations

import datetime as dt
import html
import logging
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.config import settings
from riskapp.external import ACK_TTL_DAYS, acknowledgement_url

logger = logging.getLogger(__name__)

EVENT_OWNER_ASSIGNMENT = "owner_assignment"
EVENT_SLA_WARNING = "sla_warning"
EVENT_BREACH = "breach"
EVENT_RISK_START = "risk_start"
EVENT_WEEKLY_SUMMARY = "weekly_summary"
EVENT_MATERIALIZED = "materialized"


@dataclass(frozen=True)
class RecipientContext:
    """Resolved identities for one notification event."""

    owner_user_id: int | None = None
    owner_email: str | None = None
    pm_user_id: int | None = None
    pm_email: str | None = None
    pmo_lead_email: str | None = None
    practice_lead_email: str | None = None


@dataclass(frozen=True)
class Recipients:
    """The recipients selected for an event."""

    to_user_ids: tuple[int, ...]
    to_emails: tuple[str, ...]
    cc_emails: tuple[str, ...]


class EmailProvider(Protocol):
    """Contract for sending email (stubbed in tests, ACS in production)."""

    def send_email(
        self,
        *,
        to: list[str],
        cc: list[str] | None = None,
        subject: str,
        body_html: str,
    ) -> None:
        ...


def _unique_ids(*ids: int | None) -> tuple[int, ...]:
    seen: set[int] = set()
    result: list[int] = []
    for value in ids:
        if value is not None and value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _unique(*emails: str | None) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in emails:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def resolve_recipients(event: str, ctx: RecipientContext) -> Recipients:
    """Map an event type to its recipient set (SPEC §9 matrix)."""
    if event == EVENT_OWNER_ASSIGNMENT:
        return Recipients(
            to_user_ids=_unique_ids(ctx.owner_user_id, ctx.pm_user_id),
            to_emails=_unique(ctx.owner_email, ctx.pm_email, ctx.pmo_lead_email),
            cc_emails=_unique(ctx.practice_lead_email),
        )
    if event == EVENT_SLA_WARNING:
        return Recipients(
            to_user_ids=_unique_ids(ctx.owner_user_id),
            to_emails=_unique(ctx.owner_email),
            cc_emails=(),
        )
    if event == EVENT_BREACH:
        return Recipients(
            to_user_ids=_unique_ids(ctx.owner_user_id, ctx.pm_user_id),
            to_emails=_unique(ctx.owner_email, ctx.pm_email, ctx.pmo_lead_email),
            cc_emails=(),
        )
    if event == EVENT_MATERIALIZED:
        # Risk owner + project manager are notified that the risk became an
        # Event and an Issue was raised; the PMO Lead is emailed.
        return Recipients(
            to_user_ids=_unique_ids(ctx.owner_user_id, ctx.pm_user_id),
            to_emails=_unique(ctx.owner_email, ctx.pm_email, ctx.pmo_lead_email),
            cc_emails=(),
        )
    if event == EVENT_RISK_START:
        return Recipients(
            to_user_ids=_unique_ids(ctx.owner_user_id),
            to_emails=_unique(ctx.owner_email),
            cc_emails=(),
        )
    if event == EVENT_WEEKLY_SUMMARY:
        return Recipients(
            to_user_ids=_unique_ids(ctx.pm_user_id),
            to_emails=_unique(ctx.pm_email, ctx.pmo_lead_email),
            cc_emails=(),
        )
    raise ValueError(f"Unknown notification event {event!r}")


def _fmt_date(value: dt.date | dt.datetime | None) -> str:
    """Format a ``date``/``datetime`` for an email, tolerating ``None``."""
    if value is None:
        return "—"
    if isinstance(value, dt.datetime):
        return value.strftime("%d %b %Y, %H:%M UTC")
    return value.strftime("%d %b %Y")


def _email_row(label: str, value: str) -> str:
    label_td = (
        '<td style="padding:6px 12px 6px 0;color:#64748B;'
        f'font-size:13px;">{html.escape(label)}</td>'
    )
    value_td = (
        '<td style="padding:6px 0;color:#111827;font-size:13px;'
        f'font-weight:600;">{html.escape(value)}</td>'
    )
    return f"<tr>{label_td}{value_td}</tr>"


def _external_ack_email(risk: models.Risk, ack_link: str) -> str:
    """A professional, self-contained email for an external Risk Owner.

    It never links to the internal application and only exposes the single risk
    the token grants access to.
    """
    owner = risk.owner
    owner_name = html.escape((owner.display_name if owner else "") or "there")
    project_name = risk.project.name if risk.project else "—"
    code = html.escape(risk.risk_code)
    description = html.escape(risk.description or "")
    rows = "".join(
        [
            _email_row("Risk", f"{risk.risk_code} — {risk.description or ''}"),
            _email_row("Project", project_name),
            _email_row("Severity", risk.risk_rating),
            _email_row("Risk start date", _fmt_date(risk.risk_start_date)),
            _email_row("SLA deadline", _fmt_date(risk.sla_deadline)),
        ]
    )
    link = html.escape(ack_link, quote=True)
    return f"""\
<div style="font-family:Inter,Segoe UI,Arial,sans-serif;max-width:600px;
            margin:0 auto;color:#111827;">
  <div style="border-top:4px solid #ED1C2E;padding:20px 24px 0;">
    <div style="font-size:20px;font-weight:800;letter-spacing:0.04em;">
      <span style="color:#ED1C2E;">WRAGBY</span> RiskIntel
    </div>
    <div style="color:#64748B;font-size:13px;margin-top:2px;">PMO Risk Management</div>
  </div>
  <div style="padding:20px 24px 24px;">
    <p style="font-size:15px;">Dear {owner_name},</p>
    <p style="font-size:14px;line-height:1.55;">
      You have been assigned as the Risk Owner for the risk below. Please review
      it and confirm that you accept ownership by acknowledging it.
    </p>
    <h2 style="font-size:16px;margin:18px 0 6px;">{code}</h2>
    <p style="font-size:14px;color:#374151;margin:0 0 12px;">{description}</p>
    <table style="border-collapse:collapse;margin:8px 0 18px;">{rows}</table>
    <p style="font-size:14px;line-height:1.55;">
      This secure link is personal to you and expires after {ACK_TTL_DAYS} days.
      It only shows the risk assigned to you.
    </p>
    <p style="margin:22px 0;">
      <a href="{link}"
         style="background:#ED1C2E;color:#ffffff;text-decoration:none;padding:12px 22px;
                border-radius:6px;font-weight:700;font-size:14px;display:inline-block;"
        >View &amp; Acknowledge Risk</a>
    </p>
    <p style="font-size:13px;color:#64748B;line-height:1.55;">
      If you were not expecting this email, you can safely ignore it.
    </p>
  </div>
</div>"""


class AzureCommunicationEmail:
    """Email sender backed by Azure Communication Services."""

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        sender: str | None = None,
    ) -> None:
        self._endpoint = settings.acs_endpoint if endpoint is None else endpoint
        self._access_key = settings.acs_access_key if access_key is None else access_key
        self._sender = settings.acs_sender_email if sender is None else sender

    def send_email(
        self,
        *,
        to: list[str],
        cc: list[str] | None = None,
        subject: str,
        body_html: str,
    ) -> None:
        if not to:
            return
        if not self._endpoint or not self._access_key:
            raise RuntimeError(
                "Azure Communication Services is not configured; set "
                "RISKAPP_ACS_ENDPOINT and RISKAPP_ACS_ACCESS_KEY."
            )
        try:
            from azure.communication.email import EmailClient
            from azure.core.credentials import AzureKeyCredential
        except ImportError as exc:  # pragma: no cover - dependency not in dev env
            raise RuntimeError(
                "azure-communication-email is not installed; "
                "run `pip install azure-communication-email`."
            ) from exc

        message: dict[str, Any] = {
            "senderAddress": self._sender,
            "recipients": {"to": [{"address": address} for address in to]},
            "content": {"subject": subject, "html": body_html},
        }
        if cc:
            message["recipients"]["cc"] = [{"address": address} for address in cc]

        client = EmailClient(
            self._endpoint, AzureKeyCredential(self._access_key)
        )
        poller = client.begin_send(message)
        poller.result()


class NotificationService:
    """Records in-app notifications and (optionally) sends email."""

    def __init__(self, email: EmailProvider | None = None) -> None:
        self._email = email

    def notify(
        self,
        db: Session,
        *,
        event: str,
        title: str,
        body: str,
        risk: models.Risk | None = None,
        project: models.Project | None = None,
    ) -> Recipients:
        """Resolve recipients, persist in-app rows, and send email."""
        ctx = self._build_context(db, risk, project)
        recipients = resolve_recipients(event, ctx)
        return self.notify_recipients(
            db,
            event=event,
            title=title,
            body=body,
            recipients=recipients,
            risk=risk,
            project=project,
        )

    def notify_recipients(
        self,
        db: Session,
        *,
        event: str,
        title: str,
        body: str,
        recipients: Recipients,
        risk: models.Risk | None = None,
        project: models.Project | None = None,
    ) -> Recipients:
        """Persist and email for an already-resolved recipient set."""
        project_id = (
            project.id if project is not None else (risk.project_id if risk else None)
        )
        for user_id in recipients.to_user_ids:
            db.add(
                models.Notification(
                    recipient_user_id=user_id,
                    type=event,
                    title=title,
                    body=body,
                    risk_id=risk.id if risk else None,
                    project_id=project_id,
                )
            )
        db.flush()

        if self._email and recipients.to_emails:
            try:
                self._email.send_email(
                    to=list(recipients.to_emails),
                    cc=list(recipients.cc_emails) or None,
                    subject=title,
                    body_html=self._email_body(body, risk),
                )
            except Exception:
                # Email is best-effort; never let a mail failure roll back the
                # in-app notification or the surrounding transaction. Log it so
                # silent delivery failures are visible in the container logs.
                logger.exception(
                    "Email delivery failed for event=%s to=%s", event, recipients.to_emails
                )
        return recipients

    @staticmethod
    def _email_body(body: str, risk: models.Risk | None) -> str:
        escaped = html.escape(body)
        if risk is None:
            return f"<p>{escaped}</p>"
        # External owners have no Wragby account, so they get a signed, expiring
        # link that grants access to this one risk only — and never the internal
        # application link, which they are not permitted to open.
        ack_link = acknowledgement_url(risk)
        if ack_link:
            return _external_ack_email(risk, ack_link)
        link = f"{settings.app_base_url}/risks/{risk.id}"
        code = html.escape(risk.risk_code)
        return (
            f"<p>{escaped}</p>"
            f'<p><a href="{link}">Open risk {code} in WRAGBY RiskIntel</a></p>'
        )

    @staticmethod
    def _build_context(
        db: Session, risk: models.Risk | None, project: models.Project | None
    ) -> RecipientContext:
        proj = project or (risk.project if risk else None)

        owner = risk.owner if risk else None
        pm = proj.pm_user if proj else None
        practice_lead = risk.practice_lead if risk else None

        return RecipientContext(
            owner_user_id=owner.id if owner else None,
            owner_email=owner.upn if owner else None,
            pm_user_id=pm.id if pm else None,
            pm_email=pm.upn if pm else None,
            pmo_lead_email=_get_setting(db, "pmo_lead_email"),
            practice_lead_email=(
                practice_lead.upn
                if practice_lead
                else _get_setting(db, "practice_lead_email")
            ),
        )


def _get_setting(db: Session, key: str) -> str | None:
    value = db.scalar(select(models.Setting.value).where(models.Setting.key == key))
    return value or None


def build_notification_service(
    email: EmailProvider | None = None,
) -> NotificationService:
    """A NotificationService with ACS email wired whenever it is configured.

    Callers (API endpoints and Celery tasks) should use this instead of
    ``NotificationService()`` — constructing it directly leaves the email
    provider unset, so only in-app rows are written and no mail is ever sent.
    Email stays best-effort: a mail failure never fails the request.
    """
    if email is not None:
        return NotificationService(email)
    if settings.acs_endpoint and settings.acs_access_key and settings.acs_sender_email:
        return NotificationService(AzureCommunicationEmail())
    return NotificationService()
