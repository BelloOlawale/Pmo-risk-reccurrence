"""Notification layer: recipient matrix, in-app rows, and email.

SPEC §9. Email is optional and injectable (the scheduler and suggestion flows
never hard-depend on Azure Communication Services), while in-app notifications
are always recorded so the React bell has data to show. The recipient matrix is
a pure function so it is exhaustively unit-tested.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.config import settings

EVENT_OWNER_ASSIGNMENT = "owner_assignment"
EVENT_SLA_WARNING = "sla_warning"
EVENT_BREACH = "breach"
EVENT_RISK_START = "risk_start"
EVENT_WEEKLY_SUMMARY = "weekly_summary"


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
                # in-app notification or the surrounding transaction.
                pass
        return recipients

    @staticmethod
    def _email_body(body: str, risk: models.Risk | None) -> str:
        escaped = html.escape(body)
        if risk is None:
            return f"<p>{escaped}</p>"
        link = f"{settings.app_base_url}/risks/{risk.id}"
        return (
            f"<p>{escaped}</p>"
            f'<p><a href="{link}">Open risk {risk.risk_code} in Risk Recurrence</a></p>'
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
