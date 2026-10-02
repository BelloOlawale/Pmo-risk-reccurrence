"""Pydantic request/response schemas."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class DepartmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ProjectTypeCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ProjectTypeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class UserRead(BaseModel):
    """A directory user, for owner/PM pickers. Users are created on first sign-in."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    upn: str
    display_name: str
    # ``Internal`` (Entra directory) or ``External`` (PM-captured contact).
    owner_type: str = "Internal"
    is_active: bool = True


class ExternalOwnerCreate(BaseModel):
    """Payload for capturing an external Risk Owner."""

    full_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=3, max_length=255)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        # Import here to avoid a module-level import cycle with external.
        from riskapp.external import is_valid_email, normalize_email

        normalized = normalize_email(value)
        if not is_valid_email(normalized):
            raise ValueError("Enter a valid email address.")
        return normalized

    @field_validator("full_name")
    @classmethod
    def _name_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Full name is required.")
        return value


class TestLoginStatus(BaseModel):
    """Whether the non-Microsoft test login is available."""

    enabled: bool
    code_required: bool


class TestLoginRequest(BaseModel):
    """Sign in as a role without Microsoft (testing only)."""

    role: Literal["System Admin", "PMO Lead", "Project Manager"] = "System Admin"
    upn: str | None = None
    code: str | None = None


class TestLoginToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    upn: str
    display_name: str


class LoginOptions(BaseModel):
    """Which non-Microsoft sign-in methods the deployment offers."""

    password_enabled: bool
    test_login_enabled: bool
    test_code_required: bool


class PasswordLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class SetCredentialsRequest(BaseModel):
    """Admin onboarding: set (or reset) a user's local password and role."""

    password: str = Field(min_length=8, max_length=200)
    role: Literal["System Admin", "PMO Lead", "Project Manager"] | None = None


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    department: str = Field(min_length=1, max_length=100)
    project_type: str = Field(min_length=1, max_length=100)
    customer: str = Field(min_length=1, max_length=200)
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    stage_gate: str | None = None

    @model_validator(mode="after")
    def _end_date_not_before_start(self) -> ProjectCreate:
        # Project start dates may be backdated; the only date rule is ordering.
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError(
                "Project end date cannot be earlier than the project start date."
            )
        return self

    @field_validator("customer")
    @classmethod
    def _customer_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Customer is required.")
        return v


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_code: str
    name: str
    customer: str | None
    department_name: str
    project_type_name: str
    status: str
    pm_user_id: int | None = None
    start_date: dt.date | None
    end_date: dt.date | None
    stage_gate: str | None
    closed_date: dt.datetime | None = None
    closed_by_user_id: int | None = None
    risk_count: int = 0
    risk_ids: list[int] = Field(default_factory=list)
    risk_codes: list[str] = Field(default_factory=list)


class RiskCreate(BaseModel):
    project_id: int
    description: str = Field(min_length=1)
    category: str | None = None
    subcategory: str | None = None
    risk_source: Literal["Human", "Environmental", "Technical"] | None = None
    likelihood: Literal["Low", "Medium", "High"]
    impact: Literal["Low", "Medium", "High"]
    response_strategy: Literal["Mitigate", "Transfer", "Avoid", "Accept"] | None = None
    response_plan: str | None = None
    owner_user_id: int | None = None
    risk_start_date: dt.date | None = None
    risk_end_date: dt.date | None = None
    source: Literal["Historical", "Custom", "Kickoff"] | None = None
    identified_during: str | None = None

    @model_validator(mode="after")
    def _end_date_not_before_start(self) -> RiskCreate:
        if (
            self.risk_start_date is not None
            and self.risk_end_date is not None
            and self.risk_end_date < self.risk_start_date
        ):
            raise ValueError(
                "Risk end date cannot be earlier than the risk start date."
            )
        return self


class RiskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    risk_code: str
    project_id: int
    description: str
    category: str | None
    subcategory: str | None
    risk_source: str | None
    likelihood: str
    impact: str
    risk_rating: str
    response_strategy: str | None
    response_plan: str | None
    owner_user_id: int | None
    owner_name: str | None = None
    owner_email: str | None = None
    owner_type: str | None = None
    status: str
    source: str | None
    raised_by: str | None = None
    identified_during: str | None = None
    source_file_name: str | None = None
    source_file_url: str | None = None
    source_risk_id: str | None = None
    llm_analysis: str | None = None
    risk_start_date: dt.date | None
    risk_end_date: dt.date | None
    sla_deadline: dt.datetime | None
    sla_acknowledged: bool
    sla_manual_override: bool
    acknowledged_at: dt.datetime | None = None
    accepted_date: dt.datetime | None = None
    resolved_date: dt.datetime | None = None
    closed_date: dt.datetime | None = None
    root_cause: str | None = None
    what_worked: str | None = None
    resolution_category: str | None = None
    created_at: dt.datetime


class RiskUpdate(BaseModel):
    """Partial update of a risk. Omitted fields are left unchanged."""

    description: str | None = None
    category: str | None = None
    subcategory: str | None = None
    risk_source: Literal["Human", "Environmental", "Technical"] | None = None
    likelihood: Literal["Low", "Medium", "High"] | None = None
    impact: Literal["Low", "Medium", "High"] | None = None
    response_strategy: Literal["Mitigate", "Transfer", "Avoid", "Accept"] | None = None
    response_plan: str | None = None
    owner_user_id: int | None = None
    # Alternative to owner_user_id: resolve/create the user by UPN. Wins when set.
    owner_upn: str | None = None
    risk_start_date: dt.date | None = None
    risk_end_date: dt.date | None = None
    status: str | None = None
    actor_user_id: int | None = None
    identified_during: str | None = None


class RiskDismiss(BaseModel):
    """Payload for dismissing a Suggested risk."""

    reason: str | None = None
    actor_user_id: int | None = None


class RiskDeEscalate(BaseModel):
    """Payload for de-escalating an Escalated risk back to In Progress."""

    rationale: str = Field(min_length=1)
    actor_user_id: int | None = None


class RiskAuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    risk_id: int
    user_id: int | None
    action: str
    field: str | None
    old_value: Any | None
    new_value: Any | None
    created_at: dt.datetime


class IssueRead(BaseModel):
    """An Issue raised from a materialized (Event) risk.

    ``source_risk_code`` / ``project_name`` / ``source_risk_status`` are
    denormalised for display and populated by the API from the relationships
    (the source of truth stays the ``source_risk_id`` foreign key).

    ``status`` is the Issue's *effective* status: Issues are born ``Open`` when
    a risk materializes, and resolution/closure of the materialized event is
    tracked on the originating risk (``Event -> Resolved -> Closed`` by the PMO
    Lead), so the API reports ``Resolved``/``Closed`` once the source risk
    reaches those statuses.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    issue_code: str
    project_id: int
    project_name: str = ""
    source_risk_id: int
    source_risk_code: str = ""
    source_risk_status: str = ""
    description: str
    category: str | None
    subcategory: str | None
    risk_source: str | None
    likelihood: str
    impact: str
    risk_rating: str
    response_strategy: str | None
    response_plan: str | None
    owner_user_id: int | None
    identified_during: str | None
    risk_start_date: dt.date | None
    risk_end_date: dt.date | None
    status: str
    created_at: dt.datetime


class SuggestedRiskRead(BaseModel):
    """A single suggested historical risk, ready for accept/edit/dismiss."""

    risk_id: str
    source_file: str
    source_file_url: str
    source_risk_id: str | None
    description: str
    match_type: str
    match_count: int | None = None
    similarity: float | None = None
    citation: str
    analysis: str | None = None
    likelihood: str | None = None
    impact: str | None = None
    risk_rating: str | None = None
    category: str | None = None


class SuggestionAccept(BaseModel):
    """Payload for accepting a suggested historical risk into a project."""

    risk_id: str = Field(min_length=1)
    likelihood: Literal["Low", "Medium", "High"] | None = None
    impact: Literal["Low", "Medium", "High"] | None = None
    # Optional LLM analysis shown alongside the suggestion, persisted on the
    # created risk so the detail page can display why it was suggested.
    analysis: str | None = None
    actor_user_id: int | None = None


class SuggestionDismiss(BaseModel):
    """Payload for dismissing a suggested historical risk for a project."""

    risk_id: str = Field(min_length=1)
    reason: str | None = None
    actor_user_id: int | None = None


class CitationRead(BaseModel):
    risk_id: str
    source_file: str


class SuggestionEvaluation(BaseModel):
    groundedness: float
    verified_citations: list[CitationRead]
    unverified_citations: list[CitationRead]
    # Present only when the chat deployment failed; the suggestions are then a
    # retrieval-only fallback and the UI should say so rather than implying the
    # LLM produced no analysis.
    llm_error: str | None = None
    # Present only when semantic (embedding) retrieval failed; the candidate set
    # then falls back to exact + keyword matches.
    semantic_error: str | None = None


class SuggestionRead(BaseModel):
    project_id: int
    overview: str
    recommendations: list[str]
    suggested_risks: list[SuggestedRiskRead]
    evaluation: SuggestionEvaluation


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recipient_user_id: int | None
    type: str
    title: str
    body: str
    risk_id: int | None
    project_id: int | None
    read: bool
    created_at: dt.datetime


class ImportInitiatedRead(BaseModel):
    import_id: str
    file_name: str
    columns: list[str]
    suggested_mapping: dict[str, str | None]
    row_count: int


class ImportConfirm(BaseModel):
    mapping: dict[str, str]
    actor_user_id: int | None = None


class EscalationTrendRead(BaseModel):
    """Escalated-risk trend: month buckets (``YYYY-MM``) with counts."""

    months: list[str]
    values: list[int]


class ExternalAcknowledgeRead(BaseModel):
    """Minimal, single-risk view returned to an external owner's ack link.

    Deliberately excludes anything not needed to acknowledge the assigned risk:
    no other risks, registers, projects, users or reports are reachable with the
    acknowledgement token.
    """

    risk_code: str
    description: str
    project_name: str
    category: str | None
    risk_rating: str
    likelihood: str
    impact: str
    status: str
    response_strategy: str | None
    response_plan: str | None
    risk_start_date: dt.date | None
    risk_end_date: dt.date | None
    sla_deadline: dt.datetime | None
    owner_name: str
    owner_email: str
    acknowledged: bool
    acknowledged_at: dt.datetime | None


class ImportRowErrorRead(BaseModel):
    row: int
    field: str
    message: str


class ImportReportRead(BaseModel):
    imported: int
    skipped: int
    errors: list[ImportRowErrorRead]
