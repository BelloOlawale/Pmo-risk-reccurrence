"""FastAPI application entrypoint."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
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
    create_local_token,
    get_principal,
    require_roles,
)
from riskapp.blob import AzureBlobStorage, BlobStorageProvider, register_blob_name
from riskapp.config import settings
from riskapp.db import get_db
from riskapp.domain.status import InvalidTransitionError, RiskStatus
from riskapp.embeddings import AzureOpenAIEmbeddings, EmbeddingProvider
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
    build_notification_service,
)
from riskapp.security import hash_password, verify_password
from riskapp.services import (
    accept_risk,
    acknowledge_risk,
    close_project,
    create_project,
    create_risk,
    de_escalate_risk,
    dismiss_risk,
    get_or_create_department,
    get_or_create_project_type,
    get_or_create_user,
    get_project,
    get_risk,
    list_users,
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


@app.get("/api/auth/test-login/status", response_model=schemas.TestLoginStatus)
def test_login_status() -> schemas.TestLoginStatus:
    """Whether the local (non-Microsoft) test login is available. Public."""
    return schemas.TestLoginStatus(
        enabled=settings.test_login_enabled,
        code_required=bool(settings.test_login_code),
    )


@app.post("/api/auth/test-login", response_model=schemas.TestLoginToken)
def test_login(payload: schemas.TestLoginRequest, db: DbDep) -> schemas.TestLoginToken:
    """Issue a short-lived token for a role, without Microsoft sign-in.

    Testing aid only: disabled unless ``RISKAPP_TEST_LOGIN_ENABLED`` is set, and
    gated by ``RISKAPP_TEST_LOGIN_CODE`` when configured.
    """
    if not settings.test_login_enabled:
        raise HTTPException(status_code=404, detail="Test login is disabled")
    if settings.test_login_code and payload.code != settings.test_login_code:
        raise HTTPException(status_code=403, detail="Invalid access code")

    role = Role(payload.role)
    default_upn = f"test.{role.name.lower()}@test.local"
    upn = (payload.upn or "").strip() or default_upn
    display_name = f"Test {role.value}" if upn == default_upn else upn
    user = get_or_create_user(db, upn, display_name)
    db.commit()

    token = create_local_token(
        user_id=user.id, upn=user.upn, display_name=user.display_name, role=role
    )
    return schemas.TestLoginToken(
        access_token=token,
        expires_in=LOCAL_LOGIN_TTL_HOURS * 3600,
        role=role.value,
        upn=user.upn,
        display_name=user.display_name,
    )


@app.get("/api/auth/login-options", response_model=schemas.LoginOptions)
def login_options() -> schemas.LoginOptions:
    """Which non-Microsoft sign-in methods this deployment offers. Public."""
    return schemas.LoginOptions(
        password_enabled=settings.local_login_enabled,
        test_login_enabled=settings.test_login_enabled,
        test_code_required=bool(settings.test_login_code),
    )


@app.post("/api/auth/login", response_model=schemas.TestLoginToken)
def password_login(
    payload: schemas.PasswordLoginRequest, db: DbDep
) -> schemas.TestLoginToken:
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
    return schemas.TestLoginToken(
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
    appears after they have logged in at least once.
    """
    return [schemas.UserRead.model_validate(user) for user in list_users(db)]


@app.get("/api/risk-meta")
def risk_meta(db: DbDep) -> dict[str, object]:
    """Controlled option sets for the risk forms, derived from existing data.

    Categories and project-life-cycle values come from the values already used
    in the database (no invented taxonomy). Risk sources and response
    strategies are the application's existing literals.
    """
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
    # Assign the PM: an explicit pm_upn wins, otherwise the creating user.
    pm_user_id = principal.user_id
    if payload.pm_upn:
        pm_user_id = get_or_create_user(db, payload.pm_upn).id
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
            status_code=403, detail="Only the assigned Project Manager can close this project"
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


@app.patch("/api/projects/{project_id}", response_model=schemas.ProjectRead)
def patch_project(
    project_id: int, payload: schemas.ProjectUpdate, principal: AdminDep, db: DbDep
) -> schemas.ProjectRead:
    """Reassign a project's Project Manager (PMO Lead / System Admin only).

    Each register has its own PM, so this is how different projects get different
    managers — and how a manager is changed without recreating the project.
    """
    project = get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if payload.pm_upn:
        project.pm_user_id = get_or_create_user(db, payload.pm_upn).id
    elif "pm_user_id" in payload.model_fields_set:
        if payload.pm_user_id is not None:
            user = db.get(models.User, payload.pm_user_id)
            if user is None:
                raise HTTPException(status_code=422, detail="Unknown pm_user_id")
        project.pm_user_id = payload.pm_user_id

    db.commit()
    db.refresh(project)
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
    risk = create_risk(db, payload)
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
    stmt = select(models.Risk)
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


def _issue_stmt() -> Select[tuple[models.Issue]]:
    """Issue query with the relationships the read schema needs eagerly loaded."""
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
            detail="You are not authorized to close risks. Only a PMO Lead can close a risk.",
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
        .where(models.Risk.project_id == project_id)
        .order_by(models.Risk.created_at.desc(), models.Risk.id.desc())
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
