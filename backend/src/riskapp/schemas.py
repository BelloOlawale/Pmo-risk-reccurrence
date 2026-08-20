"""Pydantic request/response schemas."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    risk_start_date: dt.date | None
    risk_end_date: dt.date | None
    sla_deadline: dt.datetime | None
    created_at: dt.datetime
