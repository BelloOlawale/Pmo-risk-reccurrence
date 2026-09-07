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
from riskapp.blob import AzureBlobStorage, BlobStorageProvider, register_blob_name
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
    close_project,
    create_catalog_risk,
    create_project,
    create_risk,
    de_escalate_risk,
    dismiss_risk,
    get_catalog_risk,
    get_or_create_department,
    get_or_create_project_type,
    get_or_create_user,
    get_project,
    get_risk,
    merge_catalog_risks,
    reopen_project,
    to_risk_read,
    update_catalog_risk,
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


def get_blob_provider() -> BlobStorageProvider:
    return AzureBlobStorage()


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

    # Risk counts + instance ids + catalog short names grouped by project — the
    # link from the projects table back to the register goes through Project Risk.
    risk_rows = db.execute(
        select(
            models.ProjectRisk.project_id,
            models.ProjectRisk.id,
            models.RiskCatalog.name,
        ).join(models.RiskCatalog, models.ProjectRisk.risk_id == models.RiskCatalog.id)
    ).all()
    counts: dict[int, int] = {}
    risk_ids: dict[int, list[int]] = {}
    risk_names: dict[int, list[str]] = {}
    for project_id, risk_id, risk_name in risk_rows:
        counts[project_id] = counts.get(project_id, 0) + 1
        risk_ids.setdefault(project_id, []).append(risk_id)
        risk_names.setdefault(project_id, []).append(risk_name or f"#{risk_id}")

    result: list[schemas.ProjectRead] = []
    for project in projects:
        item = schemas.ProjectRead.model_validate(project)
        item.risk_count = counts.get(project.id, 0)
        item.risk_ids = risk_ids.get(project.id, [])
        item.risk_names = risk_names.get(project.id, [])
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
        select(func.count(models.ProjectRisk.id)).where(
            models.ProjectRisk.project_id == project_id
        )
    ) or 0
    item = schemas.ProjectRead.model_validate(project)
    item.risk_count = int(risk_count)
    return item


@app.post(
    "/api/projects/{project_id}/close",
    response_model=schemas.ProjectRead,
    dependencies=[Depends(require_roles(Role.PROJECT_MANAGER, Role.PMO_LEAD, Role.SYSTEM_ADMIN))],
)
def close_project_endpoint(
    project_id: int, principal: PrincipalDep, db: DbDep
) -> schemas.ProjectRead:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_access_project(principal, project):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        closed = close_project(db, project)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return schemas.ProjectRead.model_validate(closed)


@app.post(
    "/api/projects/{project_id}/reopen",
    response_model=schemas.ProjectRead,
    dependencies=[Depends(require_roles(Role.PROJECT_MANAGER, Role.PMO_LEAD, Role.SYSTEM_ADMIN))],
)
def reopen_project_endpoint(
    project_id: int, principal: PrincipalDep, db: DbDep
) -> schemas.ProjectRead:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_access_project(principal, project):
        raise HTTPException(status_code=403, detail="Forbidden")
    return schemas.ProjectRead.model_validate(reopen_project(db, project))


@app.get("/api/catalog", response_model=list[schemas.RiskCatalogRead])
def list_catalog(principal: PrincipalDep, db: DbDep) -> list[schemas.RiskCatalogRead]:
    risks = db.scalars(select(models.RiskCatalog).order_by(models.RiskCatalog.id)).all()
    return [schemas.RiskCatalogRead.model_validate(r) for r in risks]


@app.get("/api/catalog/{risk_id}", response_model=schemas.RiskCatalogRead)
def read_catalog(risk_id: int, principal: PrincipalDep, db: DbDep) -> schemas.RiskCatalogRead:
    risk = db.get(models.RiskCatalog, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    return schemas.RiskCatalogRead.model_validate(risk)


@app.post(
    "/api/catalog",
    response_model=schemas.RiskCatalogRead,
    status_code=status.HTTP_201_CREATED,
)
def add_catalog_risk(
    payload: schemas.RiskCatalogCreate, principal: AdminDep, db: DbDep
) -> schemas.RiskCatalogRead:
    return schemas.RiskCatalogRead.model_validate(create_catalog_risk(db, payload))


@app.patch("/api/catalog/{risk_id}", response_model=schemas.RiskCatalogRead)
def patch_catalog_risk(
    risk_id: int,
    payload: schemas.RiskCatalogUpdate,
    principal: AdminDep,
    db: DbDep,
) -> schemas.RiskCatalogRead:
    risk = get_catalog_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    return schemas.RiskCatalogRead.model_validate(update_catalog_risk(db, risk, payload))


@app.post("/api/catalog/merge", response_model=schemas.RiskCatalogRead)
def merge_catalog(
    payload: schemas.RiskCatalogMerge, principal: AdminDep, db: DbDep
) -> schemas.RiskCatalogRead:
    survivor = get_catalog_risk(db, payload.survivor_id)
    absorbed = get_catalog_risk(db, payload.absorbed_id)
    if survivor is None or absorbed is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    if survivor.id == absorbed.id:
        raise HTTPException(status_code=422, detail="Cannot merge a risk into itself")
    return schemas.RiskCatalogRead.model_validate(merge_catalog_risks(db, survivor, absorbed))


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
    if project.status == "Closed":
        raise HTTPException(
            status_code=409, detail="Cannot add a risk to a Closed project"
        )
    try:
        return to_risk_read(create_risk(db, payload))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/risks", response_model=list[schemas.RiskRead])
def list_risks(principal: PrincipalDep, db: DbDep) -> list[schemas.RiskRead]:
    """Global risk register: every risk in the system, across all projects.

    Row-level scoping mirrors ``can_access_risk``: PMO Lead / Admin see all
    risks; owners see the risks assigned to them; PMs see the risks of their
    own projects.
    """
    stmt = select(models.ProjectRisk).options(
        selectinload(models.ProjectRisk.catalog_risk),
        selectinload(models.ProjectRisk.project),
    )
    if not principal.is_pmo_or_admin:
        stmt = stmt.where(
            or_(
                models.ProjectRisk.owner_user_id == principal.user_id,
                models.ProjectRisk.project.has(models.Project.pm_user_id == principal.user_id),
            )
        )
    instances = db.scalars(stmt.order_by(models.ProjectRisk.id)).all()
    return [to_risk_read(i) for i in instances]


@app.get("/api/risks/{risk_id}", response_model=schemas.RiskRead)
def read_risk(risk_id: int, principal: PrincipalDep, db: DbDep) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    if not can_access_risk(principal, risk):
        raise HTTPException(status_code=403, detail="Forbidden")
    return to_risk_read(risk)


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
    return to_risk_read(updated)


@app.post("/api/risks/{risk_id}/acknowledge", response_model=schemas.RiskRead)
def acknowledge(risk_id: int, db: DbDep) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    return to_risk_read(acknowledge_risk(db, risk))


@app.post("/api/risks/{risk_id}/accept", response_model=schemas.RiskRead)
def accept(risk_id: int, db: DbDep) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    try:
        accepted = accept_risk(db, risk)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return to_risk_read(accepted)


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
    return to_risk_read(dismissed)


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


def _project_risk_read(instance: models.ProjectRisk) -> schemas.ProjectRiskRead:
    """Flatten a Project Risk + its catalog Risk into the read shape."""
    catalog = instance.catalog_risk
    return schemas.ProjectRiskRead(
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
        risk_start_date=instance.risk_start_date,
        risk_end_date=instance.risk_end_date,
        sla_deadline=instance.sla_deadline,
        sla_acknowledged=instance.sla_acknowledged,
        sla_manual_override=instance.sla_manual_override,
        created_at=instance.created_at,
    )


@app.get(
    "/api/projects/{project_id}/risks", response_model=list[schemas.ProjectRiskRead]
)
def list_project_risks(
    project_id: int, principal: PrincipalDep, db: DbDep
) -> list[schemas.ProjectRiskRead]:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_access_project(principal, project):
        raise HTTPException(status_code=403, detail="Forbidden")
    instances = db.scalars(
        select(models.ProjectRisk)
        .options(selectinload(models.ProjectRisk.catalog_risk))
        .where(models.ProjectRisk.project_id == project_id)
        .order_by(models.ProjectRisk.id)
    ).all()
    return [_project_risk_read(i) for i in instances]


_ACTIVE_EXCLUDED_STATUSES = ("Resolved", "Closed", "Dismissed")


def _active_risk_read(instance: models.ProjectRisk) -> schemas.ActiveRiskRead:
    """Flatten a Project Risk + catalog + project into an Active Register row."""
    catalog = instance.catalog_risk
    project = instance.project
    return schemas.ActiveRiskRead(
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
        identified_during=instance.identified_during,
        risk_start_date=instance.risk_start_date,
        risk_end_date=instance.risk_end_date,
        sla_deadline=instance.sla_deadline,
        sla_acknowledged=instance.sla_acknowledged,
        project_code=project.project_code,
        project_name=project.name,
        department_name=project.department.name,
        project_type_name=project.project_type.name,
    )


@app.get("/api/active-register", response_model=list[schemas.ActiveRiskRead])
def active_register(
    principal: PrincipalDep, db: DbDep
) -> list[schemas.ActiveRiskRead]:
    """The Active Risk Register: Project Risks on Active projects whose status is
    not Resolved, Closed, or Dismissed, derived in the backend."""
    stmt = (
        select(models.ProjectRisk)
        .options(
            selectinload(models.ProjectRisk.catalog_risk),
            selectinload(models.ProjectRisk.project).selectinload(
                models.Project.department
            ),
            selectinload(models.ProjectRisk.project).selectinload(
                models.Project.project_type
            ),
        )
        .join(models.Project, models.ProjectRisk.project_id == models.Project.id)
        .where(
            models.Project.status == "Active",
            models.ProjectRisk.status.not_in(_ACTIVE_EXCLUDED_STATUSES),
        )
        .order_by(models.ProjectRisk.project_id, models.ProjectRisk.id)
    )
    if not principal.is_pmo_or_admin:
        stmt = stmt.where(models.Project.pm_user_id == principal.user_id)
    instances = db.scalars(stmt).all()
    return [_active_risk_read(i) for i in instances]


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
    return to_risk_read(updated)


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
    return to_risk_read(risk)


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
def list_notifications(principal: PrincipalDep, db: DbDep) -> list[schemas.NotificationRead]:
    """List the caller's own in-app notifications (scoped to their identity)."""
    if principal.user_id is None:
        return []
    entries = db.scalars(
        select(models.Notification)
        .where(models.Notification.recipient_user_id == principal.user_id)
        .order_by(models.Notification.created_at.desc(), models.Notification.id.desc())
        .limit(100)
    ).all()
    return [schemas.NotificationRead.model_validate(e) for e in entries]


@app.post("/api/notifications/{notification_id}/read", response_model=schemas.NotificationRead)
def mark_notification_read(
    notification_id: int, principal: PrincipalDep, db: DbDep
) -> schemas.NotificationRead:
    notification = db.get(models.Notification, notification_id)
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if notification.recipient_user_id != principal.user_id:
        raise HTTPException(status_code=403, detail="Forbidden")
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
    blob: Annotated[BlobStorageProvider, Depends(get_blob_provider)],
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
    # Persist the uploaded register to Blob so imported risks carry a durable
    # source_file_url. No-op (None) when Blob is not configured.
    job.source_file_url = blob.upload_bytes(
        register_blob_name(project_id, job.id, job.file_name),
        data,
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
