"""Application service layer: business operations over the ORM models."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from riskapp import models, schemas
from riskapp.audit import record_change
from riskapp.config import settings
from riskapp.domain.scoring import compute_risk_rating
from riskapp.domain.sla import as_naive_utc, compute_deadline, deadline_anchor
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


# A project can only be closed once every Project Risk on it is Resolved or
# Closed (ADR 0002). Everything else counts as still open.
_CLOSED_PROJECT_RISK_STATUSES = ("Resolved", "Closed")


def close_project(db: Session, project: models.Project) -> models.Project:
    """Close a project, blocking while any Project Risk is not Resolved/Closed.

    Raises:
        ValueError: with the still-open risks listed, when closure is blocked.
    """
    open_risks = db.scalars(
        select(models.ProjectRisk)
        .options(selectinload(models.ProjectRisk.catalog_risk))
        .where(models.ProjectRisk.project_id == project.id)
        .where(models.ProjectRisk.status.not_in(_CLOSED_PROJECT_RISK_STATUSES))
        .order_by(models.ProjectRisk.id)
    ).all()
    if open_risks:
        descriptions = [r.catalog_risk.description for r in open_risks]
        raise ValueError(
            f"Cannot close project: {len(open_risks)} risk(s) still open — "
            + "; ".join(descriptions)
        )
    project.status = "Closed"
    db.commit()
    db.refresh(project)
    return project


def reopen_project(db: Session, project: models.Project) -> models.Project:
    """Reopen a Closed project, returning it to Active (an explicit action)."""
    project.status = "Active"
    db.commit()
    db.refresh(project)
    return project


def _get_or_create_catalog_risk(
    db: Session,
    description: str,
    category: str | None,
    subcategory: str | None,
    risk_source: str | None,
) -> models.RiskCatalog:
    """Return the catalog entry for ``description`` + ``category``, creating it
    if absent. Deduplication matches the backfill (normalized description +
    category), so re-adding a known concept reuses its entry.
    """
    normalized_description = description.strip().lower()
    normalized_category = (category or "").strip().lower()
    catalog = db.scalar(
        select(models.RiskCatalog).where(
            func.lower(func.trim(models.RiskCatalog.description))
            == normalized_description,
            func.lower(func.trim(func.coalesce(models.RiskCatalog.category, "")))
            == normalized_category,
        )
    )
    if catalog is None:
        catalog = models.RiskCatalog(
            description=description,
            category=category,
            subcategory=subcategory,
            risk_source=risk_source,
        )
        db.add(catalog)
        db.flush()
    return catalog


def create_risk(db: Session, payload: schemas.RiskCreate) -> models.ProjectRisk:
    rating = compute_risk_rating(payload.likelihood, payload.impact)
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    sla_deadline = compute_deadline(
        rating, deadline_anchor(payload.risk_start_date, now, settings.tz)
    )

    # Resolve the shared catalog Risk: attach an existing one by id, or create
    # (or reuse) one from the description + category.
    if payload.catalog_risk_id is not None:
        catalog = get_catalog_risk(db, payload.catalog_risk_id)
        if catalog is None:
            raise ValueError("Catalog risk not found")
    else:
        catalog = _get_or_create_catalog_risk(
            db,
            payload.description or "",
            payload.category,
            payload.subcategory,
            payload.risk_source,
        )

    # The tracked occurrence: a Project Risk linking the project to the catalog
    # entry. Concept fields (description/category/…) live on the catalog entry;
    # everything here is per-project tracking state.
    instance = models.ProjectRisk(
        project_id=payload.project_id,
        risk_id=catalog.id,
        likelihood=payload.likelihood,
        impact=payload.impact,
        risk_rating=rating,
        response_strategy=payload.response_strategy,
        response_plan=payload.response_plan,
        owner_user_id=payload.owner_user_id,
        status=RiskStatus.SUGGESTED.value,
        source=payload.source or "Custom",
        identified_during=payload.identified_during,
        risk_start_date=payload.risk_start_date,
        risk_end_date=payload.risk_end_date,
        sla_deadline=sla_deadline,
        created_at=now,
        updated_at=now,
    )
    db.add(instance)
    db.commit()
    db.refresh(instance)
    return instance


_NON_NULLABLE_FIELDS = frozenset({"likelihood", "impact"})


def get_risk(db: Session, risk_id: int) -> models.ProjectRisk | None:
    return db.scalar(
        select(models.ProjectRisk)
        .options(
            selectinload(models.ProjectRisk.catalog_risk),
            selectinload(models.ProjectRisk.project),
        )
        .where(models.ProjectRisk.id == risk_id)
    )


def to_risk_read(instance: models.ProjectRisk) -> schemas.RiskRead:
    """Flatten a Project Risk + its catalog Risk into the tracked-risk shape."""
    catalog = instance.catalog_risk
    return schemas.RiskRead(
        id=instance.id,
        project_id=instance.project_id,
        risk_id=instance.risk_id,
        name=catalog.name,
        description=catalog.description,
        category=catalog.category,
        subcategory=catalog.subcategory,
        risk_source=catalog.risk_source,
        likelihood=instance.likelihood,
        impact=instance.impact,
        risk_rating=instance.risk_rating,
        response_strategy=instance.response_strategy,
        response_plan=instance.response_plan,
        owner_user_id=instance.owner_user_id,
        status=instance.status,
        source=instance.source,
        raised_by=instance.raised_by,
        identified_during=instance.identified_during,
        source_file_name=instance.source_file_name,
        source_file_url=instance.source_file_url,
        source_risk_id=instance.source_risk_id,
        llm_analysis=instance.llm_analysis,
        risk_start_date=instance.risk_start_date,
        risk_end_date=instance.risk_end_date,
        sla_deadline=instance.sla_deadline,
        sla_acknowledged=instance.sla_acknowledged,
        sla_manual_override=instance.sla_manual_override,
        accepted_date=instance.accepted_date,
        resolved_date=instance.resolved_date,
        closed_date=instance.closed_date,
        root_cause=instance.root_cause,
        what_worked=instance.what_worked,
        resolution_category=instance.resolution_category,
        created_at=instance.created_at,
    )


def get_catalog_risk(db: Session, risk_id: int) -> models.RiskCatalog | None:
    return db.get(models.RiskCatalog, risk_id)


def create_catalog_risk(
    db: Session, payload: schemas.RiskCatalogCreate
) -> models.RiskCatalog:
    """Create a shared catalog Risk entry (the short name is optional)."""
    risk = models.RiskCatalog(
        name=payload.name,
        description=payload.description,
        category=payload.category,
        subcategory=payload.subcategory,
        risk_source=payload.risk_source,
    )
    db.add(risk)
    db.commit()
    db.refresh(risk)
    return risk


def update_catalog_risk(
    db: Session, risk: models.RiskCatalog, payload: schemas.RiskCatalogUpdate
) -> models.RiskCatalog:
    """Apply a partial update (rename and/or re-categorize) to a catalog entry."""
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(risk, field, value)
    db.commit()
    db.refresh(risk)
    return risk


def merge_catalog_risks(
    db: Session,
    survivor: models.RiskCatalog,
    absorbed: models.RiskCatalog,
) -> models.RiskCatalog:
    """Merge ``absorbed`` into ``survivor`` and delete the absorbed entry.

    Every Project Risk that pointed at ``absorbed`` is re-pointed at
    ``survivor`` first, so the surviving entry stays referenced while the
    near-duplicate is removed from the catalog.
    """
    db.execute(
        update(models.ProjectRisk)
        .where(models.ProjectRisk.risk_id == absorbed.id)
        .values(risk_id=survivor.id)
    )
    db.delete(absorbed)
    db.commit()
    db.refresh(survivor)
    return survivor


def transition_risk(
    db: Session, risk: models.ProjectRisk, target: str, actor_user_id: int | None = None
) -> models.ProjectRisk:
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
    db.commit()
    db.refresh(risk)
    return risk


def acknowledge_risk(
    db: Session, risk: models.ProjectRisk, actor_user_id: int | None = None
) -> models.ProjectRisk:
    """Mark a risk as acknowledged (idempotent) and audit the event."""
    if not risk.sla_acknowledged:
        risk.sla_acknowledged = True
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


def accept_risk(
    db: Session, risk: models.ProjectRisk, actor_user_id: int | None = None
) -> models.ProjectRisk:
    """Accept a Suggested risk: transition to Open, assign owner, start SLA.

    The owner defaults to the project's PM when the risk has no explicit owner.
    Raises :class:`InvalidTransitionError` if the risk is not Suggested.
    """
    target = ensure_transition(risk.status, RiskStatus.OPEN.value)
    now = dt.datetime.now(dt.UTC).replace(tzinfo=None)
    old_status = risk.status
    risk.status = target.value
    risk.accepted_date = now

    owner_changed = False
    if risk.owner_user_id is None and risk.project.pm_user_id is not None:
        risk.owner_user_id = risk.project.pm_user_id
        owner_changed = True

    if risk.sla_deadline is None:
        risk.sla_deadline = compute_deadline(
            risk.risk_rating,
            deadline_anchor(risk.risk_start_date, risk.created_at or now, settings.tz),
        )

    record_change(
        db,
        risk,
        action="status_change",
        field="status",
        old_value=old_status,
        new_value=target.value,
        actor_user_id=actor_user_id,
    )
    if owner_changed:
        record_change(
            db,
            risk,
            action="field_edit",
            field="owner_user_id",
            old_value=None,
            new_value=risk.owner_user_id,
            actor_user_id=actor_user_id,
        )

    db.commit()
    db.refresh(risk)
    return risk


def dismiss_risk(
    db: Session,
    risk: models.ProjectRisk,
    *,
    actor_user_id: int | None = None,
    reason: str | None = None,
) -> models.ProjectRisk:
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
            historical_risk_key=str(risk.id),
            reason=reason,
        )
    )

    db.commit()
    db.refresh(risk)
    return risk


def de_escalate_risk(
    db: Session,
    risk: models.ProjectRisk,
    *,
    rationale: str,
    actor_user_id: int | None = None,
) -> models.ProjectRisk:
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


def _set_auto_deadline(
    db: Session, risk: models.ProjectRisk, actor_user_id: int | None = None
) -> None:
    """Recompute the SLA deadline from the rating and start date, auditing if changed."""
    new_deadline = compute_deadline(
        risk.risk_rating,
        deadline_anchor(risk.risk_start_date, risk.created_at, settings.tz),
    )
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


def update_risk(
    db: Session,
    risk: models.ProjectRisk,
    payload: schemas.RiskUpdate,
    actor_user_id: int | None = None,
) -> models.ProjectRisk:
    """Apply a partial update, auditing each changed field.

    Concept fields (description/category/subcategory/risk_source) are applied to
    the shared catalog entry; everything else is the per-project tracking state.

    Raises:
        InvalidTransitionError: if ``status`` requests an invalid transition.
        ValueError: if a non-nullable field is cleared, or status is unknown.
    """
    data = payload.model_dump(exclude_unset=True)
    data.pop("actor_user_id", None)
    target_status = data.pop("status", None)
    manual_deadline = data.pop("sla_deadline", None)
    reset_deadline = data.pop("reset_sla_deadline", False)

    catalog = risk.catalog_risk
    for field in ("description", "category", "subcategory", "risk_source"):
        if field not in data:
            continue
        new_value = data.pop(field)
        if field == "description" and (new_value is None or not str(new_value).strip()):
            raise ValueError("Field 'description' cannot be cleared")
        if new_value == getattr(catalog, field):
            continue
        old_value = getattr(catalog, field)
        setattr(catalog, field, new_value)
        record_change(
            db,
            risk,
            action="field_edit",
            field=field,
            old_value=old_value,
            new_value=new_value,
            actor_user_id=actor_user_id,
        )

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

    # Recompute the rating whenever likelihood or impact changed.
    if "likelihood" in data or "impact" in data:
        new_rating = compute_risk_rating(risk.likelihood, risk.impact)
        if new_rating != risk.risk_rating:
            old_rating = risk.risk_rating
            risk.risk_rating = new_rating
            record_change(
                db,
                risk,
                action="field_edit",
                field="risk_rating",
                old_value=old_rating,
                new_value=new_rating,
                actor_user_id=actor_user_id,
            )

    # Recompute the deadline when the rating or the start date changed,
    # unless manually overridden.
    if any(key in data for key in ("likelihood", "impact", "risk_start_date")):
        if not risk.sla_manual_override:
            _set_auto_deadline(db, risk, actor_user_id)

    # Manual deadline override (PM / PMO Lead).
    if manual_deadline is not None:
        old_deadline = risk.sla_deadline
        risk.sla_deadline = manual_deadline
        record_change(
            db,
            risk,
            action="field_edit",
            field="sla_deadline",
            old_value=old_deadline,
            new_value=manual_deadline,
            actor_user_id=actor_user_id,
        )
        if not risk.sla_manual_override:
            risk.sla_manual_override = True
            record_change(
                db,
                risk,
                action="field_edit",
                field="sla_manual_override",
                old_value=False,
                new_value=True,
                actor_user_id=actor_user_id,
            )

    # Reset the override back to the auto-computed deadline.
    if reset_deadline and risk.sla_manual_override:
        risk.sla_manual_override = False
        record_change(
            db,
            risk,
            action="field_edit",
            field="sla_manual_override",
            old_value=True,
            new_value=False,
            actor_user_id=actor_user_id,
        )
        _set_auto_deadline(db, risk, actor_user_id)

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

    db.commit()
    db.refresh(risk)
    return risk
