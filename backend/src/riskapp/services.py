"""Application service layer: business operations over the ORM models."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from riskapp import models, schemas
from riskapp.audit import record_change
from riskapp.domain.scoring import compute_risk_rating
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


def _next_risk_code(db: Session) -> str:
    count = (
        db.scalar(
            select(func.count())
            .select_from(models.Risk)
            .where(models.Risk.risk_code.like("RSK-%"))
        )
        or 0
    )
    return f"RSK-{count + 1:03d}"


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


def create_project(db: Session, payload: schemas.ProjectCreate) -> models.Project:
    department = get_or_create_department(db, payload.department)
    project_type = get_or_create_project_type(db, payload.project_type)

    project = models.Project(
        project_code=_next_project_code(db),
        name=payload.name,
        customer=payload.customer,
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


def create_risk(db: Session, payload: schemas.RiskCreate) -> models.Risk:
    risk = models.Risk(
        project_id=payload.project_id,
        risk_code=_next_risk_code(db),
        description=payload.description,
        category=payload.category,
        subcategory=payload.subcategory,
        risk_source=payload.risk_source,
        likelihood=payload.likelihood,
        impact=payload.impact,
        risk_rating=compute_risk_rating(payload.likelihood, payload.impact),
        response_strategy=payload.response_strategy,
        response_plan=payload.response_plan,
        owner_user_id=payload.owner_user_id,
        risk_start_date=payload.risk_start_date,
        risk_end_date=payload.risk_end_date,
        status=RiskStatus.SUGGESTED.value,
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
    db.commit()
    db.refresh(risk)
    return risk


def acknowledge_risk(
    db: Session, risk: models.Risk, actor_user_id: int | None = None
) -> models.Risk:
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


def update_risk(
    db: Session,
    risk: models.Risk,
    payload: schemas.RiskUpdate,
    actor_user_id: int | None = None,
) -> models.Risk:
    """Apply a partial update, auditing each changed field.

    Raises:
        InvalidTransitionError: if ``status`` requests an invalid transition.
        ValueError: if a non-nullable field is cleared, or status is unknown.
    """
    data = payload.model_dump(exclude_unset=True)
    data.pop("actor_user_id", None)
    target_status = data.pop("status", None)

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
