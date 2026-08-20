"""Application service layer: business operations over the ORM models."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from riskapp import models, schemas
from riskapp.domain.scoring import compute_risk_rating
from riskapp.domain.status import RiskStatus


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
