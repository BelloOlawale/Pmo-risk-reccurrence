"""Application service layer: business operations over the ORM models."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session, selectinload

from riskapp import models, schemas
from riskapp.audit import record_change
from riskapp.config import settings
from riskapp.domain.scoring import compute_risk_rating
from riskapp.domain.sla import as_naive_utc, deadline_from_end_date
from riskapp.domain.status import RiskStatus, ensure_transition


def _next_project_code(db: Session) -> str:
    year = dt.date.today().year
    prefix = f"PRJ-{year}-"
    count = (
        db.scalar(
            select(func.count())
            .select_from(models.Project)
            .where(models.Project.project_code.like(f"{prefix}%"))
        )
        or 0
    )
    return f"{prefix}{count + 1:03d}"


def max_risk_code_number(db: Session) -> int:
    """Return the highest numeric suffix among existing ``RSK-<n>`` codes.

    Returns 0 when no code of that shape exists. Codes whose suffix is not a
    plain number (e.g. ``RSK-H1`` used in fixtures) are ignored.
    """
    highest = 0
    for code in db.scalars(select(models.Risk.risk_code)).all():
        suffix = code[len("RSK-") :] if code.startswith("RSK-") else ""
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest


def next_risk_code(db: Session) -> str:
    """Return the next free risk code (``RSK-<n>``), one past the highest in use.

    Allocation is based on the highest existing code rather than a row count, so
    gaps left by deleted or rolled-back rows never reuse a code. Count-based
    allocation previously surfaced as an uncaught IntegrityError (HTTP 500) when
    accepting a suggestion after any risk row had been removed.
    """
    return f"RSK-{max_risk_code_number(db) + 1:03d}"


def max_issue_code_number(db: Session) -> int:
    """Return the highest numeric suffix among existing ``ISS-<n>`` codes.

    Returns 0 when no code of that shape exists. Mirrors ``max_risk_code_number``
    so issue codes never collide with rows that were rolled back.
    """
    highest = 0
    for code in db.scalars(select(models.Issue.issue_code)).all():
        suffix = code[len("ISS-") :] if code.startswith("ISS-") else ""
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return highest


def next_issue_code(db: Session) -> str:
    """Return the next free issue code (``ISS-<n>``), one past the highest in use."""
    return f"ISS-{max_issue_code_number(db) + 1:03d}"


def get_or_create_department(db: Session, name: str) -> models.Department:
    department = db.scalar(select(models.Department).where(models.Department.name == name))
    if department is None:
        department = models.Department(name=name)
        db.add(department)
        db.flush()
    return department


def get_or_create_project_type(db: Session, name: str) -> models.ProjectType:
    project_type = db.scalar(select(models.ProjectType).where(models.ProjectType.name == name))
    if project_type is None:
        project_type = models.ProjectType(name=name)
        db.add(project_type)
        db.flush()
    return project_type


def get_or_create_user(
    db: Session, upn: str, display_name: str | None = None
) -> models.User:
    """Return the user for ``upn``, creating one on first sight.

    The user row is flushed (id assigned) but not committed — callers decide
    when to persist (identity resolution in auth commits immediately).
    """
    user = db.scalar(select(models.User).where(models.User.upn == upn))
    if user is None:
        user = models.User(upn=upn, display_name=display_name or upn)
        db.add(user)
        db.flush()
    elif display_name and user.display_name != display_name:
        user.display_name = display_name
    return user


def list_users(db: Session) -> list[models.User]:
    """Every known user (created on first sign-in), ordered for pickers."""
    return list(
        db.scalars(select(models.User).order_by(models.User.display_name, models.User.id))
    )


def create_project(
    db: Session, payload: schemas.ProjectCreate, *, pm_user_id: int | None = None
) -> models.Project:
    department = get_or_create_department(db, payload.department)
    project_type = get_or_create_project_type(db, payload.project_type)

    project = models.Project(
        project_code=_next_project_code(db),
        name=payload.name,
        customer=payload.customer,
        pm_user_id=pm_user_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        stage_gate=payload.stage_gate,
        status="Active",
        created_source="User",
    )
    project.department = department
    project.project_type = project_type
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def get_project(db: Session, project_id: int) -> models.Project | None:
    stmt = (
        select(models.Project)
        .where(models.Project.id == project_id)
        .options(
            selectinload(models.Project.department),
            selectinload(models.Project.project_type),
        )
    )
    return db.scalar(stmt)


# Risk statuses that count as "resolved/closed" for the purpose of closing a
# risk register. Suggested / Open / In Progress / Escalated / Event risks are
# still outstanding and block closure.
_CLOSED_ELIGIBLE_STATUSES = frozenset(
    {
        RiskStatus.RESOLVED.value,
        RiskStatus.CLOSED.value,
        RiskStatus.DISMISSED.value,
    }
)


def close_project(
    db: Session, project: models.Project, *, actor_user_id: int | None = None
) -> models.Project:
    """Close an Active project, recording who closed it and when.

    Closing a project only changes its project-level lifecycle status. Risks,
    risk statuses and historical data are left untouched.

    Raises:
        ValueError: if the project is already closed, or if any risk in the
            register is still unresolved (not Resolved / Closed / Dismissed).
    """
    if project.status == "Closed":
        raise ValueError("Project is already closed")

    unresolved = db.scalar(
        select(func.count())
        .select_from(models.Risk)
        .where(
            models.Risk.project_id == project.id,
            ~models.Risk.status.in_(_CLOSED_ELIGIBLE_STATUSES),
        )
    ) or 0
    if unresolved > 0:
        raise ValueError(
            "Cannot close risk register: there are unresolved risks. "
            "Please resolve or close all outstanding risks before closing the risk register."
        )

    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    project.status = "Closed"
    project.closed_date = now
    project.closed_by_user_id = actor_user_id
    db.commit()
    db.refresh(project)
    return project


def validate_risk_dates(start: dt.date | None, end: dt.date | None) -> None:
    """Raise when a Risk End Date is earlier than its Risk Start Date."""
    if start is not None and end is not None and end < start:
        raise ValueError(
            "Risk end date cannot be earlier than the risk start date."
        )


def create_risk(
    db: Session,
    payload: schemas.RiskCreate,
    *,
    status: str = RiskStatus.OPEN.value,
) -> models.Risk:
    """Create a risk for a register.

    Manually added risks start life as ``Open`` — they are already accepted by
    the person capturing them, so there is no suggestion/acceptance step. The
    status is overridable so tests and internal callers can still create a
    ``Suggested`` risk (the state the accept/dismiss lifecycle operates on).

    The Risk Start Date and Risk End Date are set by the PM. The Risk End Date
    *is* the SLA deadline (never derived from the risk rating). Assigning an
    owner at creation moves the risk straight to ``In Progress``.
    """
    rating = compute_risk_rating(payload.likelihood, payload.impact)
    validate_risk_dates(payload.risk_start_date, payload.risk_end_date)
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    initial_status = status
    if payload.owner_user_id is not None and status == RiskStatus.OPEN.value:
        initial_status = RiskStatus.IN_PROGRESS.value
    risk = models.Risk(
        project_id=payload.project_id,
        risk_code=next_risk_code(db),
        description=payload.description,
        category=payload.category,
        subcategory=payload.subcategory,
        risk_source=payload.risk_source,
        likelihood=payload.likelihood,
        impact=payload.impact,
        risk_rating=rating,
        response_strategy=payload.response_strategy,
        response_plan=payload.response_plan,
        owner_user_id=payload.owner_user_id,
        risk_start_date=payload.risk_start_date,
        risk_end_date=payload.risk_end_date,
        source=payload.source or "Custom",
        identified_during=payload.identified_during,
        status=initial_status,
        created_at=now,
        updated_at=now,
        sla_deadline=deadline_from_end_date(payload.risk_end_date, settings.tz),
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)
    return risk


_NON_NULLABLE_FIELDS = frozenset({"description", "likelihood", "impact"})


def get_risk(db: Session, risk_id: int) -> models.Risk | None:
    return db.get(models.Risk, risk_id)


def transition_risk(
    db: Session, risk: models.Risk, target: str, actor_user_id: int | None = None
) -> models.Risk:
    """Transition a risk to ``target``, validating the transition and auditing it."""
    target_status = ensure_transition(risk.status, target)
    old_status = risk.status
    risk.status = target_status.value
    record_change(
        db,
        risk,
        action="status_change",
        field="status",
        old_value=old_status,
        new_value=target_status.value,
        actor_user_id=actor_user_id,
    )
    # Escalation and materialization both raise a tracked Issue. Creating it in
    # the same transaction (idempotent) means an escalated or Event risk shows
    # up in the Issues table immediately, not on the next backfill sweep.
    if target_status in (RiskStatus.EVENT, RiskStatus.ESCALATED):
        ensure_issue_for_risk(db, risk, actor_user_id=actor_user_id)
    db.commit()
    db.refresh(risk)
    return risk


def acknowledge_risk(
    db: Session, risk: models.Risk, actor_user_id: int | None = None
) -> models.Risk:
    """Mark a risk as acknowledged (idempotent) and audit the event.

    Acknowledgement satisfies the SLA acknowledgement requirement only. It does
    NOT resolve the risk: the risk stays active until the owner resolves it.
    """
    if risk.owner_user_id is None:
        raise ValueError("A risk must have an assigned owner before it can be acknowledged.")
    if not risk.sla_acknowledged:
        now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
        risk.sla_acknowledged = True
        risk.acknowledged_at = now
        record_change(
            db,
            risk,
            action="acknowledge",
            field="sla_acknowledged",
            old_value=False,
            new_value=True,
            actor_user_id=actor_user_id,
        )
        db.commit()
        db.refresh(risk)
    return risk


def ensure_issue_for_risk(
    db: Session, risk: models.Risk, *, actor_user_id: int | None = None
) -> models.Issue:
    """Return the single Issue for a materialized (Event) risk, creating it when missing.

    Issue creation is idempotent: the unique constraint on ``source_risk_id`` and
    the existence check here guarantee exactly one Issue per materialized risk,
    no matter how many times the automation runs.

    Raises:
        ValueError: if ``risk`` is neither escalated nor in the ``Event``
            (materialized) status.
    """
    if risk.status not in (RiskStatus.EVENT.value, RiskStatus.ESCALATED.value):
        raise ValueError(
            f"Issues are only created for escalated or materialized (Event) risks; "
            f"{risk.risk_code} is {risk.status!r}."
        )
    existing = db.scalar(
        select(models.Issue).where(models.Issue.source_risk_id == risk.id)
    )
    if existing is not None:
        return existing

    issue = models.Issue(
        issue_code=next_issue_code(db),
        project_id=risk.project_id,
        source_risk_id=risk.id,
        description=risk.description,
        category=risk.category,
        subcategory=risk.subcategory,
        risk_source=risk.risk_source,
        likelihood=risk.likelihood,
        impact=risk.impact,
        risk_rating=risk.risk_rating,
        response_strategy=risk.response_strategy,
        response_plan=risk.response_plan,
        owner_user_id=risk.owner_user_id,
        identified_during=risk.identified_during,
        risk_start_date=risk.risk_start_date,
        risk_end_date=risk.risk_end_date,
        status="Open",
    )
    db.add(issue)
    db.flush()
    # Record the automatic Issue creation on the originating risk's audit trail.
    record_change(
        db,
        risk,
        action="issue_created",
        field="issue_code",
        old_value=None,
        new_value=issue.issue_code,
        actor_user_id=actor_user_id,
    )
    db.flush()
    return issue


def accept_risk(
    db: Session, risk: models.Risk, actor_user_id: int | None = None
) -> models.Risk:
    """Accept a Suggested risk: transition to Open and start the SLA clock.

    Ownership is never assigned implicitly — the accepted risk keeps whatever
    explicit ``owner_user_id`` it already had (usually none), and a human
    assigns the owner afterwards. Raises :class:`InvalidTransitionError` if the
    risk is not Suggested.
    """
    target = ensure_transition(risk.status, RiskStatus.OPEN.value)
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    old_status = risk.status
    risk.status = target.value
    risk.accepted_date = now

    if risk.sla_deadline is None and risk.risk_end_date is not None:
        # The Risk End Date is the SLA deadline; never derived from the rating.
        risk.sla_deadline = deadline_from_end_date(risk.risk_end_date, settings.tz)

    record_change(
        db,
        risk,
        action="status_change",
        field="status",
        old_value=old_status,
        new_value=target.value,
        actor_user_id=actor_user_id,
    )

    db.commit()
    db.refresh(risk)
    return risk


def dismiss_risk(
    db: Session,
    risk: models.Risk,
    *,
    actor_user_id: int | None = None,
    reason: str | None = None,
) -> models.Risk:
    """Dismiss a Suggested risk and remember it so it never reappears.

    Raises :class:`InvalidTransitionError` if the risk is not Suggested.
    """
    target = ensure_transition(risk.status, RiskStatus.DISMISSED.value)
    old_status = risk.status
    risk.status = target.value

    record_change(
        db,
        risk,
        action="status_change",
        field="status",
        old_value=old_status,
        new_value=target.value,
        actor_user_id=actor_user_id,
    )
    db.add(
        models.SuggestionDismissal(
            project_id=risk.project_id,
            historical_risk_key=risk.risk_code,
            reason=reason,
        )
    )

    db.commit()
    db.refresh(risk)
    return risk


def de_escalate_risk(
    db: Session,
    risk: models.Risk,
    *,
    rationale: str,
    actor_user_id: int | None = None,
) -> models.Risk:
    """De-escalate an Escalated risk back to In Progress, with a rationale.

    Restricted to PM / PMO Lead (enforced at the API layer). The rationale is
    audit-logged so the decision is always traceable.
    """
    target = ensure_transition(risk.status, RiskStatus.IN_PROGRESS.value)
    old_status = risk.status
    risk.status = target.value
    record_change(
        db,
        risk,
        action="status_change",
        field="status",
        old_value=old_status,
        new_value=target.value,
        actor_user_id=actor_user_id,
    )
    record_change(
        db,
        risk,
        action="de_escalate",
        field="escalation_rationale",
        old_value=None,
        new_value=rationale,
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(risk)
    return risk


# Fields that are fixed at creation. The Edit Details form shows them
# read-only; the API rejects any attempt to change them.
_IMMUTABLE_RISK_FIELDS = frozenset(
    {"likelihood", "impact", "category", "response_strategy", "identified_during"}
)


def _refresh_sla_deadline(
    db: Session, risk: models.Risk, actor_user_id: int | None = None
) -> None:
    """Derive the SLA deadline from the (PM-set) Risk End Date, auditing changes."""
    new_deadline = deadline_from_end_date(risk.risk_end_date, settings.tz)
    current_deadline = (
        as_naive_utc(risk.sla_deadline) if risk.sla_deadline is not None else None
    )
    if new_deadline != current_deadline:
        risk.sla_deadline = new_deadline
        record_change(
            db,
            risk,
            action="field_edit",
            field="sla_deadline",
            old_value=current_deadline,
            new_value=new_deadline,
            actor_user_id=actor_user_id,
        )


def _reject_immutable_edits(data: dict[str, object], risk: models.Risk) -> None:
    """Drop immutable fields whose value is unchanged; reject actual changes."""
    for field in list(data):
        if field not in _IMMUTABLE_RISK_FIELDS:
            continue
        if data[field] != getattr(risk, field):
            raise ValueError(
                f"{field.replace('_', ' ').title()} cannot be edited after the risk "
                "is created."
            )
        data.pop(field)


def update_risk(
    db: Session,
    risk: models.Risk,
    payload: schemas.RiskUpdate,
    actor_user_id: int | None = None,
) -> models.Risk:
    """Apply a partial update, auditing each changed field.

    Likelihood, Impact, Category, Response Strategy and Project Lifecycle are
    fixed at creation and rejected here (not only disabled in the UI). The Risk
    End Date is PM-set and *is* the SLA deadline.

    Raises:
        InvalidTransitionError: if ``status`` requests an invalid transition.
        ValueError: if a non-nullable field is cleared, an immutable field is
            changed, the dates are inconsistent, or the status is unknown.
    """
    data = payload.model_dump(exclude_unset=True)
    data.pop("actor_user_id", None)
    # owner_upn is a convenience alias: resolve/create the user, then assign.
    owner_upn = data.pop("owner_upn", None)
    if owner_upn:
        data["owner_user_id"] = get_or_create_user(db, owner_upn).id
    target_status = data.pop("status", None)

    _reject_immutable_edits(data, risk)

    owner_before = risk.owner_user_id

    for field, new_value in data.items():
        if new_value is None and field in _NON_NULLABLE_FIELDS:
            raise ValueError(f"Field {field!r} cannot be cleared")
        if new_value == getattr(risk, field):
            continue
        old_value = getattr(risk, field)
        setattr(risk, field, new_value)
        record_change(
            db,
            risk,
            action="field_edit",
            field=field,
            old_value=old_value,
            new_value=new_value,
            actor_user_id=actor_user_id,
        )

    if "risk_start_date" in data or "risk_end_date" in data:
        validate_risk_dates(risk.risk_start_date, risk.risk_end_date)
        _refresh_sla_deadline(db, risk, actor_user_id)

    # Assigning an owner moves a live, unowned Open risk into the workflow.
    newly_assigned = risk.owner_user_id is not None and owner_before is None
    if (
        newly_assigned
        and target_status is None
        and risk.status == RiskStatus.OPEN.value
    ):
        target_status = RiskStatus.IN_PROGRESS.value

    if target_status is not None and target_status != risk.status:
        target = ensure_transition(risk.status, target_status)
        old_status = risk.status
        risk.status = target.value
        record_change(
            db,
            risk,
            action="status_change",
            field="status",
            old_value=old_status,
            new_value=target.value,
            actor_user_id=actor_user_id,
        )

    # Escalation and materialization both raise the single tracked Issue;
    # repeated edits of an already-escalated/Event risk are idempotent.
    if risk.status in (RiskStatus.EVENT.value, RiskStatus.ESCALATED.value):
        ensure_issue_for_risk(db, risk, actor_user_id=actor_user_id)

    db.commit()
    db.refresh(risk)
    return risk


def delete_risk(db: Session, risk: models.Risk) -> None:
    """Delete a risk and every record that points at it, leaving no orphans.

    The originating risk is normally retained for audit; an explicit PM delete
    is the one sanctioned exception. Its auto-created Issue, audit log entries
    and notification references are removed (or unlinked) in the same
    transaction so no dangling foreign keys remain.
    """
    db.execute(delete(models.Issue).where(models.Issue.source_risk_id == risk.id))
    db.execute(delete(models.RiskAuditLog).where(models.RiskAuditLog.risk_id == risk.id))
    db.execute(
        update(models.Notification)
        .where(models.Notification.risk_id == risk.id)
        .values(risk_id=None)
    )
    db.delete(risk)
    db.commit()
