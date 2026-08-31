"""FastAPI application entrypoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from riskapp import models, schemas
from riskapp.auth import (
    Principal,
    PrincipalDep,
    Role,
    can_access_project,
    can_access_risk,
    require_roles,
)
from riskapp.config import settings
from riskapp.db import get_db
from riskapp.domain.status import InvalidTransitionError
from riskapp.embeddings import AzureOpenAIEmbeddings, EmbeddingProvider
from riskapp.import_api import (
    create_import_job,
    get_import_job,
    run_import,
    suggest_mapping,
)
from riskapp.import_pipeline.excel_parser import parse_excel_bytes
from riskapp.llm.chat import AzureOpenAIChat, ChatProvider
from riskapp.services import (
    accept_risk,
    acknowledge_risk,
    create_project,
    create_risk,
    de_escalate_risk,
    dismiss_risk,
    get_or_create_department,
    get_or_create_project_type,
    get_or_create_user,
    get_project,
    get_risk,
    update_risk,
)
from riskapp.suggestions import (
    accept_suggestion,
    dismiss_suggestion,
    generate_suggestions,
    list_suggestions,
)

app = FastAPI(title="Risk Recurrence Predictor")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DbDep = Annotated[Session, Depends(get_db)]


def get_chat_provider() -> ChatProvider:
    return AzureOpenAIChat()


def get_embedding_provider() -> EmbeddingProvider:
    return AzureOpenAIEmbeddings()


# Role-gated dependencies (dev mode defaults to System Admin, so these are no-ops
# locally; production resolves roles from the Entra token).
ProjectManagerDep = Annotated[
    Principal, Depends(require_roles(Role.PROJECT_MANAGER, Role.SYSTEM_ADMIN))
]
AdminDep = Annotated[
    Principal, Depends(require_roles(Role.SYSTEM_ADMIN, Role.PMO_LEAD))
]


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
def add_project(
    payload: schemas.ProjectCreate,
    db: DbDep,
    principal: ProjectManagerDep,
) -> schemas.ProjectRead:
    # Assign the PM: an explicit pm_upn wins, otherwise the creating user.
    pm_user_id = principal.user_id
    if payload.pm_upn:
        pm_user_id = get_or_create_user(db, payload.pm_upn).id
    return schemas.ProjectRead.model_validate(
        create_project(db, payload, pm_user_id=pm_user_id)
    )


@app.get("/api/projects", response_model=list[schemas.ProjectRead])
def list_projects(principal: PrincipalDep, db: DbDep) -> list[schemas.ProjectRead]:
    stmt = select(models.Project).options(
        selectinload(models.Project.department),
        selectinload(models.Project.project_type),
    )
    if not principal.is_pmo_or_admin:
        stmt = stmt.where(models.Project.pm_user_id == principal.user_id)
    projects = db.scalars(stmt.order_by(models.Project.id)).all()

    # Risk counts + risk ids grouped by project — the link from the projects
    # table back to the risk register (the FK is risk.project_id -> project.id).
    risk_rows = db.execute(
        select(models.Risk.project_id, models.Risk.id, models.Risk.risk_code)
    ).all()
    counts: dict[int, int] = {}
    risk_ids: dict[int, list[int]] = {}
    risk_codes: dict[int, list[str]] = {}
    for project_id, risk_id, risk_code in risk_rows:
        counts[project_id] = counts.get(project_id, 0) + 1
        risk_ids.setdefault(project_id, []).append(risk_id)
        risk_codes.setdefault(project_id, []).append(risk_code)

    result: list[schemas.ProjectRead] = []
    for project in projects:
        item = schemas.ProjectRead.model_validate(project)
        item.risk_count = counts.get(project.id, 0)
        item.risk_ids = risk_ids.get(project.id, [])
        item.risk_codes = risk_codes.get(project.id, [])
        result.append(item)
    return result


@app.get("/api/projects/{project_id}", response_model=schemas.ProjectRead)
def read_project(
    project_id: int, principal: PrincipalDep, db: DbDep
) -> schemas.ProjectRead:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_access_project(principal, project):
        raise HTTPException(status_code=403, detail="Forbidden")
    risk_count = db.scalar(
        select(func.count(models.Risk.id)).where(models.Risk.project_id == project_id)
    ) or 0
    item = schemas.ProjectRead.model_validate(project)
    item.risk_count = int(risk_count)
    return item


@app.post(
    "/api/risks",
    response_model=schemas.RiskRead,
    status_code=status.HTTP_201_CREATED,
)
def add_risk(
    payload: schemas.RiskCreate, principal: PrincipalDep, db: DbDep
) -> schemas.RiskRead:
    project = get_project(db, payload.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_access_project(principal, project):
        raise HTTPException(status_code=403, detail="Forbidden")
    return schemas.RiskRead.model_validate(create_risk(db, payload))


@app.get("/api/risks", response_model=list[schemas.RiskRead])
def list_risks(principal: PrincipalDep, db: DbDep) -> list[schemas.RiskRead]:
    """Global risk register: every risk in the system, across all projects.

    Row-level scoping mirrors ``can_access_risk``: PMO Lead / Admin see all
    risks; owners see the risks assigned to them; PMs see the risks of their
    own projects.
    """
    stmt = select(models.Risk)
    if not principal.is_pmo_or_admin:
        stmt = stmt.where(
            or_(
                models.Risk.owner_user_id == principal.user_id,
                models.Risk.project.has(models.Project.pm_user_id == principal.user_id),
            )
        )
    risks = db.scalars(stmt.order_by(models.Risk.id)).all()
    return [schemas.RiskRead.model_validate(r) for r in risks]


@app.get("/api/risks/{risk_id}", response_model=schemas.RiskRead)
def read_risk(risk_id: int, principal: PrincipalDep, db: DbDep) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    if not can_access_risk(principal, risk):
        raise HTTPException(status_code=403, detail="Forbidden")
    return schemas.RiskRead.model_validate(risk)


@app.patch("/api/risks/{risk_id}", response_model=schemas.RiskRead)
def patch_risk(
    risk_id: int, payload: schemas.RiskUpdate, principal: PrincipalDep, db: DbDep
) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    if not can_access_risk(principal, risk):
        raise HTTPException(status_code=403, detail="Forbidden")
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


@app.post("/api/risks/{risk_id}/accept", response_model=schemas.RiskRead)
def accept(risk_id: int, db: DbDep) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    try:
        accepted = accept_risk(db, risk)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return schemas.RiskRead.model_validate(accepted)


@app.post("/api/risks/{risk_id}/dismiss", response_model=schemas.RiskRead)
def dismiss(risk_id: int, payload: schemas.RiskDismiss, db: DbDep) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    try:
        dismissed = dismiss_risk(
            db, risk, actor_user_id=payload.actor_user_id, reason=payload.reason
        )
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return schemas.RiskRead.model_validate(dismissed)


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


@app.get(
    "/api/projects/{project_id}/risks", response_model=list[schemas.RiskRead]
)
def list_project_risks(
    project_id: int, principal: PrincipalDep, db: DbDep
) -> list[schemas.RiskRead]:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_access_project(principal, project):
        raise HTTPException(status_code=403, detail="Forbidden")
    risks = db.scalars(
        select(models.Risk)
        .where(models.Risk.project_id == project_id)
        .order_by(models.Risk.id)
    ).all()
    return [schemas.RiskRead.model_validate(r) for r in risks]


@app.post(
    "/api/risks/{risk_id}/de-escalate",
    response_model=schemas.RiskRead,
    dependencies=[Depends(require_roles(Role.PROJECT_MANAGER, Role.PMO_LEAD, Role.SYSTEM_ADMIN))],
)
def de_escalate(
    risk_id: int, payload: schemas.RiskDeEscalate, db: DbDep
) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    try:
        updated = de_escalate_risk(
            db, risk, rationale=payload.rationale, actor_user_id=payload.actor_user_id
        )
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return schemas.RiskRead.model_validate(updated)


@app.post(
    "/api/projects/{project_id}/suggest",
    response_model=schemas.SuggestionRead,
)
def suggest_risks(
    project_id: int,
    db: DbDep,
    chat: Annotated[ChatProvider, Depends(get_chat_provider)],
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> schemas.SuggestionRead:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    result = generate_suggestions(db, project, chat, embeddings)
    return schemas.SuggestionRead.model_validate(result, from_attributes=True)


@app.get(
    "/api/projects/{project_id}/suggestions",
    response_model=list[schemas.SuggestedRiskRead],
)
def list_project_suggestions(
    project_id: int, principal: PrincipalDep, db: DbDep
) -> list[schemas.SuggestedRiskRead]:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_access_project(principal, project):
        raise HTTPException(status_code=403, detail="Forbidden")
    return list_suggestions(db, project)


@app.post(
    "/api/projects/{project_id}/suggestions/accept",
    response_model=schemas.RiskRead,
    status_code=status.HTTP_201_CREATED,
)
def accept_project_suggestion(
    project_id: int,
    payload: schemas.SuggestionAccept,
    principal: PrincipalDep,
    db: DbDep,
) -> schemas.RiskRead:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_access_project(principal, project):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        risk = accept_suggestion(
            db,
            project,
            payload.risk_id,
            likelihood=payload.likelihood,
            impact=payload.impact,
            actor_user_id=payload.actor_user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return schemas.RiskRead.model_validate(risk)


@app.post("/api/projects/{project_id}/suggestions/dismiss")
def dismiss_project_suggestion(
    project_id: int,
    payload: schemas.SuggestionDismiss,
    principal: PrincipalDep,
    db: DbDep,
) -> dict[str, str]:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_access_project(principal, project):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        dismiss_suggestion(db, project, payload.risk_id, reason=payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"status": "dismissed", "risk_id": payload.risk_id}


@app.get("/api/notifications", response_model=list[schemas.NotificationRead])
def list_notifications(user_id: int, db: DbDep) -> list[schemas.NotificationRead]:
    entries = db.scalars(
        select(models.Notification)
        .where(models.Notification.recipient_user_id == user_id)
        .order_by(models.Notification.created_at.desc(), models.Notification.id.desc())
        .limit(100)
    ).all()
    return [schemas.NotificationRead.model_validate(e) for e in entries]


@app.post("/api/notifications/{notification_id}/read", response_model=schemas.NotificationRead)
def mark_notification_read(
    notification_id: int, db: DbDep
) -> schemas.NotificationRead:
    notification = db.get(models.Notification, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    notification.read = True
    db.commit()
    db.refresh(notification)
    return schemas.NotificationRead.model_validate(notification)


@app.post(
    "/api/imports",
    response_model=schemas.ImportInitiatedRead,
    dependencies=[Depends(require_roles(Role.SYSTEM_ADMIN, Role.PMO_LEAD))],
)
async def initiate_import(
    project_id: Annotated[int, Form()],
    db: DbDep,
    file: Annotated[UploadFile, File()],
) -> schemas.ImportInitiatedRead:
    if get_project(db, project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    data = await file.read()
    rows = parse_excel_bytes(data)
    if not rows:
        raise HTTPException(
            status_code=400,
            detail="Could not parse the uploaded file (unsupported or empty).",
        )
    headers = list(rows[0].keys())
    job = create_import_job(
        project_id,
        file.filename or "upload.xlsx",
        rows,
        headers,
    )
    return schemas.ImportInitiatedRead(
        import_id=job.id,
        file_name=job.file_name,
        columns=headers,
        suggested_mapping=suggest_mapping(headers),
        row_count=len(rows),
    )


@app.post(
    "/api/imports/{import_id}/confirm",
    response_model=schemas.ImportReportRead,
    dependencies=[Depends(require_roles(Role.SYSTEM_ADMIN, Role.PMO_LEAD))],
)
def confirm_import(
    import_id: str, payload: schemas.ImportConfirm, db: DbDep
) -> schemas.ImportReportRead:
    job = get_import_job(import_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Import job not found")
    if get_project(db, job.project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    report = run_import(db, job, payload.mapping)
    return schemas.ImportReportRead(
        imported=report.imported,
        skipped=report.skipped,
        errors=[
            schemas.ImportRowErrorRead(
                row=error.row, field=error.field, message=error.message
            )
            for error in report.errors
        ],
    )
