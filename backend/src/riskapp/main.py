"""FastAPI application entrypoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy.orm import Session

from riskapp import schemas
from riskapp.db import get_db
from riskapp.services import (
    create_project,
    create_risk,
    get_or_create_department,
    get_or_create_project_type,
    get_project,
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
