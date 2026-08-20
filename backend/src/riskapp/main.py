"""FastAPI application entrypoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models, schemas
from riskapp.db import get_db
from riskapp.domain.status import InvalidTransitionError
from riskapp.services import (
    acknowledge_risk,
    create_project,
    create_risk,
    get_or_create_department,
    get_or_create_project_type,
    get_project,
    get_risk,
    update_risk,
)

app = FastAPI(title="Risk Recurrence Predictor")

DbDep = Annotated[Session, Depends(get_db)]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/departments",
    response_model=schemas.DepartmentRead,
    status_code=status.HTTP_201_CREATED,
)
def add_department(payload: schemas.DepartmentCreate, db: DbDep) -> schemas.DepartmentRead:
    return schemas.DepartmentRead.model_validate(get_or_create_department(db, payload.name))


@app.post(
    "/api/project-types",
    response_model=schemas.ProjectTypeRead,
    status_code=status.HTTP_201_CREATED,
)
def add_project_type(
    payload: schemas.ProjectTypeCreate, db: DbDep
) -> schemas.ProjectTypeRead:
    return schemas.ProjectTypeRead.model_validate(
        get_or_create_project_type(db, payload.name)
    )


@app.post(
    "/api/projects",
    response_model=schemas.ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
def add_project(payload: schemas.ProjectCreate, db: DbDep) -> schemas.ProjectRead:
    return schemas.ProjectRead.model_validate(create_project(db, payload))


@app.get("/api/projects/{project_id}", response_model=schemas.ProjectRead)
def read_project(project_id: int, db: DbDep) -> schemas.ProjectRead:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return schemas.ProjectRead.model_validate(project)


@app.post(
    "/api/risks",
    response_model=schemas.RiskRead,
    status_code=status.HTTP_201_CREATED,
)
def add_risk(payload: schemas.RiskCreate, db: DbDep) -> schemas.RiskRead:
    return schemas.RiskRead.model_validate(create_risk(db, payload))


@app.get("/api/risks/{risk_id}", response_model=schemas.RiskRead)
def read_risk(risk_id: int, db: DbDep) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    return schemas.RiskRead.model_validate(risk)


@app.patch("/api/risks/{risk_id}", response_model=schemas.RiskRead)
def patch_risk(risk_id: int, payload: schemas.RiskUpdate, db: DbDep) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    try:
        updated = update_risk(db, risk, payload, actor_user_id=payload.actor_user_id)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return schemas.RiskRead.model_validate(updated)


@app.post("/api/risks/{risk_id}/acknowledge", response_model=schemas.RiskRead)
def acknowledge(risk_id: int, db: DbDep) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    return schemas.RiskRead.model_validate(acknowledge_risk(db, risk))


@app.get("/api/risks/{risk_id}/history", response_model=list[schemas.RiskAuditLogRead])
def risk_history(risk_id: int, db: DbDep) -> list[schemas.RiskAuditLogRead]:
    if get_risk(db, risk_id) is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    entries = db.scalars(
        select(models.RiskAuditLog)
        .where(models.RiskAuditLog.risk_id == risk_id)
        .order_by(models.RiskAuditLog.created_at, models.RiskAuditLog.id)
    ).all()
    return [schemas.RiskAuditLogRead.model_validate(e) for e in entries]
