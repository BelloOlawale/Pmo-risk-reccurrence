"""Pydantic request/response schemas."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from riskapp.config import settings


def _today() -> dt.date:
    """Today's date in the application business timezone."""
    return dt.datetime.now(settings.tz).date()


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


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    department: str = Field(min_length=1, max_length=100)
    project_type: str = Field(min_length=1, max_length=100)
    customer: str | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    stage_gate: str | None = None
    pm_upn: str | None = None

    @field_validator("start_date")
    @classmethod
    def _start_date_not_past(cls, v: dt.date | None) -> dt.date | None:
        if v is not None and v < _today():
            raise ValueError("Project start date cannot be in the past")
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

    @field_validator("risk_start_date")
    @classmethod
    def _risk_start_date_not_past(cls, v: dt.date | None) -> dt.date | None:
        if v is not None and v < _today():
            raise ValueError("Risk start date cannot be in the past")
        return v


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
    risk_start_date: dt.date | None = None
    risk_end_date: dt.date | None = None
    sla_deadline: dt.datetime | None = None
    reset_sla_deadline: bool = False
    status: str | None = None
    actor_user_id: int | None = None
    identified_during: str | None = None

    @field_validator("risk_start_date")
    @classmethod
    def _risk_start_date_not_past(cls, v: dt.date | None) -> dt.date | None:
        if v is not None and v < _today():
            raise ValueError("Risk start date cannot be in the past")
        return v


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


class ImportRowErrorRead(BaseModel):
    row: int
    field: str
    message: str


class ImportReportRead(BaseModel):
    imported: int
    skipped: int
    errors: list[ImportRowErrorRead]
