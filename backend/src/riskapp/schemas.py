"""Pydantic request/response schemas."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


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


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_code: str
    name: str
    customer: str | None
    department_name: str
    project_type_name: str
    status: str
    start_date: dt.date | None
    end_date: dt.date | None
    stage_gate: str | None
    risk_count: int = 0
    risk_ids: list[int] = Field(default_factory=list)
    risk_names: list[str] = Field(default_factory=list)


class RiskCreate(BaseModel):
    """Create a risk on a project.

    Either attach an existing catalog Risk (``catalog_risk_id``) or describe a
    brand-new risk (``description``); the service layer creates or reuses the
    shared catalog entry accordingly.
    """

    project_id: int
    catalog_risk_id: int | None = None
    description: str | None = Field(default=None, min_length=1)
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
    def _require_catalog_or_description(self) -> RiskCreate:
        if self.catalog_risk_id is None and not (self.description or "").strip():
            raise ValueError("Provide either catalog_risk_id or a description")
        return self


class RiskRead(BaseModel):
    """A tracked risk: a Project Risk joined to its catalog Risk."""

    id: int
    project_id: int
    risk_id: int
    name: str | None
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


class RiskCatalogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str | None
    description: str
    category: str | None
    subcategory: str | None
    risk_source: str | None
    created_at: dt.datetime


class ProjectRiskRead(BaseModel):
    """A Project Risk joined to its catalog Risk.

    Concept fields (name, description, category, subcategory, risk_source) come
    from the shared catalog entry; the rest is the per-project tracking state.
    """

    id: int
    project_id: int
    risk_id: int
    name: str | None
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
    raised_by: str | None
    identified_during: str | None
    risk_start_date: dt.date | None
    risk_end_date: dt.date | None
    sla_deadline: dt.datetime | None
    sla_acknowledged: bool
    sla_manual_override: bool
    created_at: dt.datetime


class ActiveRiskRead(BaseModel):
    """One row of the Active Risk Register.

    A Project Risk joined to its catalog Risk and its Project. Only risks on
    Active projects whose status is not Resolved/Closed/Dismissed appear.
    """

    id: int
    project_id: int
    risk_id: int
    name: str | None
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
    identified_during: str | None
    risk_start_date: dt.date | None
    risk_end_date: dt.date | None
    sla_deadline: dt.datetime | None
    sla_acknowledged: bool
    project_code: str
    project_name: str
    department_name: str
    project_type_name: str


class RiskCatalogCreate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=1)
    category: str | None = None
    subcategory: str | None = None
    risk_source: str | None = None


class RiskCatalogUpdate(BaseModel):
    """Partial update of a catalog risk (rename or re-categorize).

    Omitted fields are left unchanged; an explicit ``null`` clears a field.
    """

    name: str | None = None
    description: str | None = None
    category: str | None = None
    subcategory: str | None = None
    risk_source: str | None = None


class RiskCatalogMerge(BaseModel):
    """Merge ``absorbed_id`` into ``survivor_id``, re-pointing Project Risks."""

    survivor_id: int
    absorbed_id: int


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
