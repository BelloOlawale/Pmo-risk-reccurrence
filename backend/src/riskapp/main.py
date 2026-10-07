"""FastAPI application entrypoint."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, selectinload

from riskapp import models, schemas
from riskapp.auth import (
    LOCAL_LOGIN_TTL_HOURS,
    Principal,
    PrincipalDep,
    Role,
    authenticate_local,
    can_access_issue,
    can_access_project,
    can_access_risk,
    can_close_project,
    can_close_risk,
    can_delete_risk,
    can_review_resolution,
    create_local_token,
    get_principal,
    require_roles,
)
from riskapp.blob import AzureBlobStorage, BlobStorageProvider, register_blob_name
from riskapp.cache import TtlCache
from riskapp.config import settings
from riskapp.db import get_db
from riskapp.domain.sla import as_naive_utc
from riskapp.domain.status import InvalidTransitionError, RiskStatus
from riskapp.embeddings import AzureOpenAIEmbeddings, EmbeddingProvider
from riskapp.excel_export import (
    build_risk_register_workbook,
    risk_register_filename,
)
from riskapp.external import (
    EXTERNAL,
    acknowledgement_url,
    decode_acknowledgement_token,
    get_or_create_external_owner,
)
from riskapp.import_api import (
    create_import_job,
    get_import_job,
    run_import,
    suggest_mapping,
)
from riskapp.import_pipeline.excel_parser import parse_excel_bytes
from riskapp.llm.chat import AzureOpenAIChat, ChatProvider
from riskapp.notifications import (
    EVENT_MATERIALIZED,
    EVENT_OWNER_ASSIGNMENT,
    EVENT_RESOLUTION_REJECTED,
    EVENT_RESOLVED,
    build_notification_service,
    resolution_rejected_email,
)
from riskapp.security import hash_password, verify_password
from riskapp.services import (
    accept_resolution,
    accept_risk,
    acknowledge_risk,
    close_project,
    create_project,
    create_risk,
    de_escalate_risk,
    delete_risk,
    dismiss_risk,
    get_or_create_department,
    get_or_create_project_type,
    get_or_create_user,
    get_project,
    get_risk,
    list_users,
    reject_resolution,
    resolve_risk,
    update_risk,
)
from riskapp.suggestions import (
    accept_suggestion,
    dismiss_suggestion,
    generate_suggestions,
    list_suggestions,
)

app = FastAPI(title="WRAGBY RiskIntel — PMO Risk Management")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Let the browser read the download filename on the Excel export.
    expose_headers=["Content-Disposition"],
)

DbDep = Annotated[Session, Depends(get_db)]

# Small, slow-changing option sets that every register/form page loads. Caching
# them removes a cross-region DB round-trip from the common page load.
_users_cache = TtlCache(ttl_seconds=60)
_risk_meta_cache = TtlCache(ttl_seconds=300)


def get_chat_provider() -> ChatProvider:
    return AzureOpenAIChat()


def get_embedding_provider() -> EmbeddingProvider:
    return AzureOpenAIEmbeddings()


def get_blob_provider() -> BlobStorageProvider:
    return AzureBlobStorage()


# Role-gated dependencies (dev mode defaults to System Admin, so these are no-ops
# locally; production resolves roles from the Entra token).
ProjectManagerDep = Annotated[
    Principal,
    Depends(require_roles(Role.PROJECT_MANAGER, Role.PMO_LEAD, Role.SYSTEM_ADMIN)),
]
AdminDep = Annotated[
    Principal, Depends(require_roles(Role.SYSTEM_ADMIN, Role.PMO_LEAD))
]


def _project_read(db: Session, project: models.Project) -> schemas.ProjectRead:
    """Serialize a project with its risk count (shared by GET / PATCH)."""
    risk_count = db.scalar(
        select(func.count(models.Risk.id)).where(models.Risk.project_id == project.id)
    ) or 0
    item = schemas.ProjectRead.model_validate(project)
    item.risk_count = int(risk_count)
    return item


def _notify_owner_assignment(db: Session, risk: models.Risk) -> None:
    """Tell a newly-assigned owner (in-app + email) that the risk is theirs."""
    if risk.owner_user_id is None:
        return
    owners = "" if not risk.owner else f" ({risk.owner.display_name})"
    deadline = (
        f" The SLA deadline is {risk.sla_deadline:%Y-%m-%d %H:%M} UTC."
        if risk.sla_deadline
        else ""
    )
    build_notification_service().notify(
        db,
        event=EVENT_OWNER_ASSIGNMENT,
        title=f"Risk assigned: {risk.risk_code}",
        body=(
            f"Risk {risk.risk_code}{owners} has been assigned to you.{deadline} "
            "Open the app to review and acknowledge it."
        ),
        risk=risk,
    )
    db.commit()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/auth/login-options", response_model=schemas.LoginOptions)
def login_options() -> schemas.LoginOptions:
    """Which sign-in methods this deployment offers. Public."""
    return schemas.LoginOptions(
        password_enabled=settings.local_login_enabled,
    )


def _resolve_external_risk(db: Session, token: str) -> models.Risk:
    """Resolve a signed acknowledgement token to its single external-owner risk.

    Any failure (bad signature, expiry, wrong owner, non-external or inactive
    owner) is reported as a 404 so the link leaks nothing about the risk.
    """
    claims = decode_acknowledgement_token(token)
    if claims is None:
        raise HTTPException(
            status_code=404, detail="This acknowledgement link is invalid or has expired."
        )
    try:
        owner_id = int(claims["sub"])
        risk_id = int(claims["risk_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=404, detail="This acknowledgement link is invalid or has expired."
        ) from exc

    risk = db.scalar(
        select(models.Risk)
        .options(selectinload(models.Risk.owner), selectinload(models.Risk.project))
        .where(models.Risk.id == risk_id)
    )
    owner = risk.owner if risk is not None else None
    if (
        risk is None
        or risk.owner_user_id != owner_id
        or owner is None
        or owner.owner_type != EXTERNAL
        or not owner.is_active
    ):
        raise HTTPException(
            status_code=404, detail="This acknowledgement link is invalid or has expired."
        )
    return risk


def _latest_rejection_reason(db: Session, risk: models.Risk) -> str | None:
    """Reason from the last resolution review, only when it was a rejection."""
    last = db.scalar(
        select(models.RiskAuditLog)
        .where(
            models.RiskAuditLog.risk_id == risk.id,
            models.RiskAuditLog.action.in_(
                ["resolution_submitted", "resolution_rejected", "resolution_accepted"]
            ),
        )
        .order_by(models.RiskAuditLog.id.desc())
        .limit(1)
    )
    if last is not None and last.action == "resolution_rejected":
        return str(last.new_value) if last.new_value is not None else None
    return None


def _external_ack_read(
    db: Session, risk: models.Risk
) -> schemas.ExternalAcknowledgeRead:
    owner = risk.owner
    return schemas.ExternalAcknowledgeRead(
        risk_code=risk.risk_code,
        description=risk.description,
        project_name=risk.project.name if risk.project else "",
        category=risk.category,
        risk_rating=risk.risk_rating,
        likelihood=risk.likelihood,
        impact=risk.impact,
        status=risk.status,
        response_strategy=risk.response_strategy,
        response_plan=risk.response_plan,
        risk_start_date=risk.risk_start_date,
        risk_end_date=risk.risk_end_date,
        sla_deadline=risk.sla_deadline,
        owner_name=owner.display_name if owner else "",
        owner_email=owner.upn if owner else "",
        project_manager=risk.project.pm_name or "" if risk.project else "",
        acknowledged=risk.sla_acknowledged,
        acknowledged_at=risk.acknowledged_at,
        resolution_rejected_reason=_latest_rejection_reason(db, risk),
    )


@app.get(
    "/api/external/acknowledge/{token}",
    response_model=schemas.ExternalAcknowledgeRead,
)
def external_acknowledge_info(
    token: str, db: DbDep
) -> schemas.ExternalAcknowledgeRead:
    """Public: show the single risk behind an external acknowledgement link."""
    return _external_ack_read(db, _resolve_external_risk(db, token))


@app.post(
    "/api/external/acknowledge/{token}",
    response_model=schemas.ExternalAcknowledgeRead,
)
def external_acknowledge(token: str, db: DbDep) -> schemas.ExternalAcknowledgeRead:
    """Public: acknowledge the assigned risk (idempotent) for an external owner."""
    risk = _resolve_external_risk(db, token)
    if not risk.sla_acknowledged:
        risk = acknowledge_risk(db, risk, actor_user_id=risk.owner_user_id)
    return _external_ack_read(db, risk)


@app.post(
    "/api/external/acknowledge/{token}/resolve",
    response_model=schemas.ExternalAcknowledgeRead,
)
def external_resolve(token: str, db: DbDep) -> schemas.ExternalAcknowledgeRead:
    """Public: Risk Owner marks the assigned risk Resolved (awaits PM review).

    The owner may only move the risk into ``Resolved`` — never ``Closed``. The
    Project Manager is notified to review the proposed resolution.
    """
    risk = _resolve_external_risk(db, token)
    if risk.status == RiskStatus.RESOLVED.value:
        return _external_ack_read(db, risk)  # idempotent re-submission
    try:
        risk = resolve_risk(db, risk, actor_user_id=risk.owner_user_id)
    except (InvalidTransitionError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    build_notification_service().notify(
        db,
        event=EVENT_RESOLVED,
        title=f"Resolution submitted: {risk.risk_code}",
        body=(
            f"Risk {risk.risk_code} was marked Resolved by its Risk Owner and "
            "now awaits your review (accept or reject the resolution)."
        ),
        risk=risk,
    )
    db.commit()
    return _external_ack_read(db, risk)


@app.post("/api/auth/login", response_model=schemas.LoginToken)
def password_login(
    payload: schemas.PasswordLoginRequest, db: DbDep
) -> schemas.LoginToken:
    """Sign in with an app-managed email + password.

    Passwords are independent of Entra (which cannot validate a tenant password
    from an app). Disabled unless ``RISKAPP_LOCAL_LOGIN_ENABLED`` is set.
    """
    if not settings.local_login_enabled:
        raise HTTPException(status_code=404, detail="Password login is disabled")

    principal = authenticate_local(db, payload.email, payload.password)
    if principal is None or principal.user_id is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    user = db.get(models.User, principal.user_id)
    if user is None:  # pragma: no cover - authenticated user must exist
        raise HTTPException(status_code=401, detail="Invalid email or password")
    role = next(iter(principal.roles), Role.PROJECT_MANAGER)
    token = create_local_token(
        user_id=user.id, upn=user.upn, display_name=user.display_name, role=role
    )
    return schemas.LoginToken(
        access_token=token,
        expires_in=LOCAL_LOGIN_TTL_HOURS * 3600,
        role=role.value,
        upn=user.upn,
        display_name=user.display_name,
    )


@app.post("/api/auth/change-password")
def change_password(
    payload: schemas.ChangePasswordRequest, principal: PrincipalDep, db: DbDep
) -> dict[str, str]:
    """Change your own local password (local accounts only)."""
    if principal.user_id is None:
        raise HTTPException(status_code=403, detail="No local account for this session")
    user = db.get(models.User, principal.user_id)
    if user is None or not user.password_hash:
        raise HTTPException(status_code=403, detail="This account has no local password")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"status": "ok"}


@app.post("/api/users/{user_id}/credentials", response_model=schemas.UserRead)
def set_user_credentials(
    user_id: int, payload: schemas.SetCredentialsRequest, principal: AdminDep, db: DbDep
) -> schemas.UserRead:
    """Onboard/reset a user's local password (and optionally their role).

    System Admin / PMO Lead only — this is how local accounts are created.
    """
    user = db.get(models.User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.owner_type == EXTERNAL:
        raise HTTPException(
            status_code=409,
            detail="External risk owners cannot be granted application access.",
        )
    user.password_hash = hash_password(payload.password)
    if payload.role is not None:
        user.role = payload.role
    db.commit()
    db.refresh(user)
    return schemas.UserRead.model_validate(user)


@app.get("/api/me")
def me(principal: PrincipalDep) -> dict[str, object]:
    """The current caller's identity and roles (used by the UI for role-aware controls)."""
    return {
        "user_id": principal.user_id,
        "upn": principal.upn,
        "roles": sorted(role.value for role in principal.roles),
    }


@app.get(
    "/api/users",
    response_model=list[schemas.UserRead],
    dependencies=[Depends(get_principal)],
)
def list_directory_users(db: DbDep) -> list[schemas.UserRead]:
    """Directory of known users for owner / PM pickers.

    Any authenticated caller may read it (it is an internal colleague list);
    rows are created automatically on first sign-in, so a brand-new user only
    appears after they have logged in at least once. The list is stable for the
    life of a page, so it is served from a short TTL cache.
    """

    def load() -> list[schemas.UserRead]:
        return [schemas.UserRead.model_validate(user) for user in list_users(db)]

    return _users_cache.get_or_set(load)


@app.post(
    "/api/external-owners",
    response_model=schemas.UserRead,
    status_code=status.HTTP_201_CREATED,
)
def add_external_owner(
    payload: schemas.ExternalOwnerCreate, principal: ProjectManagerDep, db: DbDep
) -> schemas.UserRead:
    """Capture an external Risk Owner (a non-Wragby person) for assignment.

    PM / PMO Lead / System Admin only. Email is normalized and validated, and a
    repeat email returns the existing external owner instead of duplicating it.
    """
    try:
        owner = get_or_create_external_owner(
            db,
            full_name=payload.full_name,
            email=payload.email,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # The owner directory is TTL-cached; drop it so the new person is pickable.
    _users_cache.clear()
    return schemas.UserRead.model_validate(owner)


@app.get("/api/risk-meta")
def risk_meta(db: DbDep) -> dict[str, object]:
    """Controlled option sets for the risk forms, derived from existing data.

    Categories and project-life-cycle values come from the values already used
    in the database (no invented taxonomy). Risk sources and response
    strategies are the application's existing literals. Derived from the whole
    register, so it changes slowly and is served from a TTL cache.
    """
    return _risk_meta_cache.get_or_set(lambda: _compute_risk_meta(db))


def _canonical_departments(names: Iterable[str | None]) -> list[str]:
    """One option per department, case-insensitively deduped.

    The register carries mixed casing from historical imports (``DATAZONE`` vs
    ``Datazone``). Offering both in the picker is noise, so collapse them to a
    single representative, preferring a mixed/Title-case value over ALL-CAPS.
    """
    by_lower: dict[str, str] = {}
    for raw in names:
        if raw is None:
            continue
        name = str(raw).strip()
        if not name:
            continue
        key = name.lower()
        current = by_lower.get(key)
        if current is None or (current.isupper() and not name.isupper()):
            by_lower[key] = name
    return sorted(by_lower.values(), key=str.lower)


def _compute_risk_meta(db: Session) -> dict[str, object]:
    categories = sorted(
        {str(category) for category in db.scalars(
            select(models.Risk.category).where(
                models.Risk.category.is_not(None), models.Risk.category != ""
            )
        ).all() if category},
        key=str.lower,
    )

    # Life cycle: the values recorded on risks (identified_during) plus the
    # stage-gate values used on projects, normalised to title case.
    raw_lifecycle = set(
        db.scalars(
            select(models.Risk.identified_during).where(
                models.Risk.identified_during.is_not(None),
                models.Risk.identified_during != "",
            )
        ).all()
    ) | set(
        db.scalars(
            select(models.Project.stage_gate).where(
                models.Project.stage_gate.is_not(None), models.Project.stage_gate != ""
            )
        ).all()
    )
    titled = {str(value).strip().title() for value in raw_lifecycle if str(value).strip()}
    lifecycle_order = ["Discovery", "Initiation", "Planning", "Execution", "Closure"]
    lifecycle = [phase for phase in lifecycle_order if phase in titled] + sorted(
        titled - set(lifecycle_order)
    )

    return {
        "categories": categories,
        "departments": _canonical_departments(
            db.scalars(select(models.Department.name)).all()
        ),
        "lifecycle": lifecycle,
        "risk_sources": ["Human", "Environmental", "Technical"],
        "response_strategies": ["Mitigate", "Transfer", "Avoid", "Accept"],
    }


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
    pm_user_id = principal.user_id
    if pm_user_id is None:
        if not principal.upn:
            raise HTTPException(status_code=401, detail="Authenticated user has no identity")
        pm_user_id = get_or_create_user(db, principal.upn).id
    return schemas.ProjectRead.model_validate(
        create_project(db, payload, pm_user_id=pm_user_id)
    )


@app.get("/api/projects", response_model=list[schemas.ProjectRead])
def list_projects(
    principal: PrincipalDep, db: DbDep, status: str | None = None
) -> list[schemas.ProjectRead]:
    stmt = select(models.Project).options(
        selectinload(models.Project.department),
        selectinload(models.Project.project_type),
        selectinload(models.Project.pm_user),
    )
    if status is not None:
        stmt = stmt.where(models.Project.status == status)
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


@app.post(
    "/api/projects/{project_id}/close",
    response_model=schemas.ProjectRead,
)
def close_project_endpoint(
    project_id: int, principal: PrincipalDep, db: DbDep
) -> schemas.ProjectRead:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_close_project(principal, project):
        raise HTTPException(
            status_code=403, detail="Only the assigned PM or System Admin can close this project"
        )
    try:
        closed = close_project(db, project, actor_user_id=principal.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return schemas.ProjectRead.model_validate(closed)


@app.get("/api/projects/{project_id}", response_model=schemas.ProjectRead)
def read_project(
    project_id: int, principal: PrincipalDep, db: DbDep
) -> schemas.ProjectRead:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_access_project(principal, project):
        raise HTTPException(status_code=403, detail="Forbidden")
    return _project_read(db, project)


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
    try:
        risk = create_risk(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # Reopen a closed register when a new risk is added to it: the register
    # becomes Active again and reappears under Active Risk.
    if project.status == "Closed":
        project.status = "Active"
        project.closed_date = None
        project.closed_by_user_id = None
        db.commit()
        db.refresh(project)
    _notify_owner_assignment(db, risk)
    return schemas.RiskRead.model_validate(risk)


@app.get("/api/risks", response_model=list[schemas.RiskRead])
def list_risks(principal: PrincipalDep, db: DbDep) -> list[schemas.RiskRead]:
    """Global risk register: every risk in the system, across all projects.

    Row-level scoping mirrors ``can_access_risk``: PMO Lead / Admin see all
    risks; owners see the risks assigned to them; PMs see the risks of their
    own projects.
    """
    stmt = select(models.Risk).options(
        selectinload(models.Risk.owner), selectinload(models.Risk.project)
    )
    if not principal.is_pmo_or_admin:
        stmt = stmt.where(
            or_(
                models.Risk.owner_user_id == principal.user_id,
                models.Risk.project.has(models.Project.pm_user_id == principal.user_id),
            )
        )
    # Newest risks first (created_at desc, id desc as a stable tiebreaker for
    # rows that share a timestamp, e.g. a batch import committed in one txn).
    risks = db.scalars(
        stmt.order_by(models.Risk.created_at.desc(), models.Risk.id.desc())
    ).all()
    return [schemas.RiskRead.model_validate(r) for r in risks]


@app.get("/api/risks/{risk_id}", response_model=schemas.RiskRead)
def read_risk(risk_id: int, principal: PrincipalDep, db: DbDep) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    if not can_access_risk(principal, risk):
        raise HTTPException(status_code=403, detail="Forbidden")
    return schemas.RiskRead.model_validate(risk)


_ISSUE_LOADS = (
    selectinload(models.Issue.source_risk),
    selectinload(models.Issue.project),
    selectinload(models.Issue.owner),
)


def _issue_status(issue: models.Issue) -> str:
    """Effective Issue status, tracked on the originating materialized risk.

    Issues are born ``Open`` when a risk materializes (Event). The materialized
    event stays open until the risk itself is resolved (``Event -> Resolved``)
    and finally closed by the PMO Lead (``-> Closed``), so the Issue's effective
    status follows that lifecycle rather than a frozen ``Open`` column value.
    """
    src_status = issue.source_risk.status
    if src_status in (RiskStatus.RESOLVED.value, RiskStatus.CLOSED.value):
        return src_status
    return "Open"


def _serialize_issue(issue: models.Issue) -> schemas.IssueRead:
    """Build the read schema, denormalising the source risk + project info."""
    item = schemas.IssueRead.model_validate(issue)
    item.source_risk_code = issue.source_risk.risk_code
    item.source_risk_status = issue.source_risk.status
    item.project_name = issue.project.name
    item.status = _issue_status(issue)
    return item


def _issue_stmt() -> Select[Any]:
    """Issue query with the relationships the read schema needs eagerly loaded.

    SQLAlchemy 2.1 changed ``Select``'s generic parameter from the row tuple
    (``Select[tuple[Issue]]``) to the ORM entity (``Select[Issue]``), so keep
    the parameter as ``Any`` to type-check under both 2.0 and 2.1.
    """
    return select(models.Issue).options(*_ISSUE_LOADS)


@app.get("/api/projects/{project_id}/issues", response_model=list[schemas.IssueRead])
def list_project_issues(
    project_id: int, principal: PrincipalDep, db: DbDep
) -> list[schemas.IssueRead]:
    """Issues raised from materialized risks within one project's Risk Register."""
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_access_project(principal, project):
        raise HTTPException(status_code=403, detail="Forbidden")
    issues = db.scalars(
        _issue_stmt()
        .where(models.Issue.project_id == project_id)
        .order_by(models.Issue.created_at.desc(), models.Issue.id.desc())
    ).all()
    return [_serialize_issue(issue) for issue in issues]


@app.get("/api/issues/{issue_id}", response_model=schemas.IssueRead)
def read_issue(issue_id: int, principal: PrincipalDep, db: DbDep) -> schemas.IssueRead:
    issue = db.scalar(
        _issue_stmt().where(models.Issue.id == issue_id)
    )
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    if not can_access_issue(principal, issue):
        raise HTTPException(status_code=403, detail="Forbidden")
    return _serialize_issue(issue)


@app.get("/api/risks/{risk_id}/issue", response_model=schemas.IssueRead)
def read_risk_issue(risk_id: int, principal: PrincipalDep, db: DbDep) -> schemas.IssueRead:
    """The single Issue raised from a materialized risk (404 when not materialized)."""
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    if not can_access_risk(principal, risk):
        raise HTTPException(status_code=403, detail="Forbidden")
    issue = db.scalar(
        _issue_stmt().where(models.Issue.source_risk_id == risk_id)
    )
    if issue is None:
        raise HTTPException(status_code=404, detail="Risk has not materialized into an Issue")
    return _serialize_issue(issue)


@app.patch("/api/risks/{risk_id}", response_model=schemas.RiskRead)
def patch_risk(
    risk_id: int, payload: schemas.RiskUpdate, principal: PrincipalDep, db: DbDep
) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    if not can_access_risk(principal, risk):
        raise HTTPException(status_code=403, detail="Forbidden")
    # Closing a risk (status -> Closed) is reserved for the PMO Lead (final
    # closure authority). System Admin may also close as the app's superuser.
    # Enforced here, not just hidden in the UI.
    if payload.status == RiskStatus.CLOSED.value and not can_close_risk(principal):
        raise HTTPException(
            status_code=403,
            detail=(
                "You are not authorized to close risks. Only a PMO Lead can "
                "finally close a risk."
            ),
        )
    # Sending a Resolved risk back to In Progress is the PM's review decision;
    # it is not a generic status edit available to the Risk Owner.
    if (
        risk.status == RiskStatus.RESOLVED.value
        and payload.status == RiskStatus.IN_PROGRESS.value
        and not can_review_resolution(principal, risk)
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Only the Project Manager or PMO Lead can send a resolution back "
                "to In Progress."
            ),
        )
    was_event = risk.status == RiskStatus.EVENT.value
    owner_before = risk.owner_user_id
    try:
        updated = update_risk(db, risk, payload, actor_user_id=payload.actor_user_id)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Tell the new owner (in-app + email) when the assignment changed.
    if updated.owner_user_id is not None and updated.owner_user_id != owner_before:
        _notify_owner_assignment(db, updated)

    # A manual transition to Event materializes the risk the same way the hourly
    # job does: update_risk has already created the single Issue, so mirror the
    # materialization notification to the owner, PM, and PMO Lead.
    if not was_event and updated.status == RiskStatus.EVENT.value:
        issue = updated.issue
        assert issue is not None  # update_risk created it for the new Event risk
        build_notification_service().notify(
            db,
            event=EVENT_MATERIALIZED,
            title=f"Risk materialized: {updated.risk_code}",
            body=(
                f"Risk {updated.risk_code} was marked as an Event (materialized) and "
                f"Issue {issue.issue_code} has been created from the materialized risk."
            ),
            risk=updated,
        )
        db.commit()
        db.refresh(updated)
    return schemas.RiskRead.model_validate(updated)


@app.post("/api/risks/{risk_id}/acknowledge", response_model=schemas.RiskRead)
def acknowledge(
    risk_id: int, principal: PrincipalDep, db: DbDep
) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    if not can_access_risk(principal, risk):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        acknowledged = acknowledge_risk(
            db, risk, actor_user_id=principal.user_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return schemas.RiskRead.model_validate(acknowledged)


@app.post(
    "/api/risks/{risk_id}/resolution/accept", response_model=schemas.RiskRead
)
def accept_risk_resolution(
    risk_id: int, principal: PrincipalDep, db: DbDep
) -> schemas.RiskRead:
    """Project Manager accepts the Risk Owner's resolution (risk stays Resolved)."""
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    if not can_access_risk(principal, risk):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not can_review_resolution(principal, risk):
        raise HTTPException(
            status_code=403,
            detail="Only the Project Manager or PMO Lead can review a resolution.",
        )
    try:
        updated = accept_resolution(db, risk, actor_user_id=principal.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return schemas.RiskRead.model_validate(updated)


@app.post(
    "/api/risks/{risk_id}/resolution/reject", response_model=schemas.RiskRead
)
def reject_risk_resolution(
    risk_id: int,
    payload: schemas.ResolutionReject,
    principal: PrincipalDep,
    db: DbDep,
) -> schemas.RiskRead:
    """Project Manager rejects the resolution: risk returns to In Progress.

    A reason is mandatory; the Risk Owner is emailed it together with their
    persistent link so they can continue working the risk.
    """
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    if not can_access_risk(principal, risk):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not can_review_resolution(principal, risk):
        raise HTTPException(
            status_code=403,
            detail="Only the Project Manager or PMO Lead can review a resolution.",
        )
    reason = payload.reason.strip()
    try:
        updated = reject_resolution(
            db,
            risk,
            reason=reason,
            actor_user_id=payload.actor_user_id or principal.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    owner = updated.owner
    email_body = None
    if owner is not None and owner.owner_type == EXTERNAL:
        link = acknowledgement_url(updated)
        if link:
            email_body = resolution_rejected_email(updated, reason, link)
    build_notification_service().notify(
        db,
        event=EVENT_RESOLUTION_REJECTED,
        title=f"Resolution rejected: {updated.risk_code}",
        body=(
            f"Your proposed resolution for risk {updated.risk_code} was rejected by "
            f"the Project Manager. Reason: {reason}"
        ),
        risk=updated,
        email_body=email_body,
    )
    db.commit()
    db.refresh(updated)
    return schemas.RiskRead.model_validate(updated)


@app.delete("/api/risks/{risk_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_risk(risk_id: int, principal: PrincipalDep, db: DbDep) -> None:
    """Delete a risk and its related records (PM / PMO Lead / System Admin)."""
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    if not can_access_risk(principal, risk):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not can_delete_risk(principal, risk):
        raise HTTPException(
            status_code=403,
            detail="Only the project PM, a PMO Lead, or a System Admin can delete a risk.",
        )
    delete_risk(db, risk)


@app.post("/api/risks/{risk_id}/accept", response_model=schemas.RiskRead)
def accept(risk_id: int, db: DbDep) -> schemas.RiskRead:
    risk = get_risk(db, risk_id)
    if risk is None:
        raise HTTPException(status_code=404, detail="Risk not found")
    owner_before = risk.owner_user_id
    try:
        accepted = accept_risk(db, risk)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if accepted.owner_user_id is not None and accepted.owner_user_id != owner_before:
        _notify_owner_assignment(db, accepted)
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
        .options(selectinload(models.Risk.owner), selectinload(models.Risk.project))
        .where(models.Risk.project_id == project_id)
        .order_by(models.Risk.created_at.desc(), models.Risk.id.desc())
    ).all()
    return [schemas.RiskRead.model_validate(r) for r in risks]


@app.get("/api/projects/{project_id}/risks/export")
def export_project_risks(
    project_id: int, principal: PrincipalDep, db: DbDep
) -> Response:
    """Download this Risk Register as a formatted .xlsx workbook.

    Exports the current database rows for the register (never mocked data),
    including internal/external owner details and acknowledgement state.
    """
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_access_project(principal, project):
        raise HTTPException(status_code=403, detail="Forbidden")
    risks = list(
        db.scalars(
            select(models.Risk)
            .options(selectinload(models.Risk.owner))
            .where(models.Risk.project_id == project_id)
            .order_by(models.Risk.created_at.desc(), models.Risk.id.desc())
        ).all()
    )
    content = build_risk_register_workbook(project, risks)
    filename = risk_register_filename(project.name)
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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


@app.get(
    "/api/reports/escalation-trend",
    response_model=schemas.EscalationTrendRead,
)
def escalation_trend_report(
    principal: PrincipalDep,
    db: DbDep,
    project_id: int | None = None,
    days: int | None = None,
) -> schemas.EscalationTrendRead:
    """Escalated-risk counts per month, derived from the real audit trail.

    Every transition *into* ``Escalated`` is recorded in the append-only audit
    log, so aggregating those entries by month yields the true escalation trend
    (no mocked or rating-derived values). Scoped to the caller's visibility and
    optionally to one project / a trailing number of days.
    """
    stmt = (
        select(models.RiskAuditLog, models.Risk.project_id)
        .join(models.Risk, models.Risk.id == models.RiskAuditLog.risk_id)
        .join(models.Project, models.Project.id == models.Risk.project_id)
        .where(models.RiskAuditLog.action == "status_change")
    )
    if project_id is not None:
        stmt = stmt.where(models.Risk.project_id == project_id)
    if not principal.is_pmo_or_admin:
        stmt = stmt.where(models.Project.pm_user_id == principal.user_id)

    cutoff = (
        dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(days=days)
        if days is not None
        else None
    )
    buckets: dict[str, int] = {}
    for entry, _project_id in db.execute(stmt).all():
        if str(entry.new_value) != RiskStatus.ESCALATED.value:
            continue
        escalated_at = as_naive_utc(entry.created_at)
        if cutoff is not None and escalated_at < cutoff:
            continue
        key = f"{escalated_at.year:04d}-{escalated_at.month:02d}"
        buckets[key] = buckets.get(key, 0) + 1

    months = sorted(buckets)
    return schemas.EscalationTrendRead(
        months=months, values=[buckets[month] for month in months]
    )


@app.post(
    "/api/projects/{project_id}/suggest",
    response_model=schemas.SuggestionRead,
)
def suggest_risks(
    project_id: int,
    principal: PrincipalDep,
    db: DbDep,
    chat: Annotated[ChatProvider, Depends(get_chat_provider)],
    embeddings: Annotated[EmbeddingProvider, Depends(get_embedding_provider)],
) -> schemas.SuggestionRead:
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if not can_access_project(principal, project):
        raise HTTPException(status_code=403, detail="Forbidden")
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
            analysis=payload.analysis,
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
