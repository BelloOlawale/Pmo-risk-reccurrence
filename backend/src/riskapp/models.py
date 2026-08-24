"""SQLAlchemy ORM models.

Schema follows SPEC.md §3. See Alembic migrations for the versioned schema.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Department(TimestampMixin, Base):
    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)

    projects: Mapped[list[Project]] = relationship(back_populates="department")


class ProjectType(TimestampMixin, Base):
    __tablename__ = "project_types"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)

    projects: Mapped[list[Project]] = relationship(back_populates="project_type")


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upn: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))


class Project(TimestampMixin, Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    customer: Mapped[str | None] = mapped_column(String(200), nullable=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    project_type_id: Mapped[int] = mapped_column(ForeignKey("project_types.id"), index=True)
    pm_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    stage_gate: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="Active", nullable=False)

    department: Mapped[Department] = relationship(back_populates="projects")
    project_type: Mapped[ProjectType] = relationship(back_populates="projects")
    pm_user: Mapped[User | None] = relationship(foreign_keys=[pm_user_id])
    risks: Mapped[list[Risk]] = relationship(back_populates="project")

    @property
    def department_name(self) -> str:
        return self.department.name

    @property
    def project_type_name(self) -> str:
        return self.project_type.name


class Risk(TimestampMixin, Base):
    __tablename__ = "risks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    risk_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)

    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(100), nullable=True)
    risk_source: Mapped[str | None] = mapped_column(String(30), nullable=True)

    likelihood: Mapped[str] = mapped_column(String(10), nullable=False)
    impact: Mapped[str] = mapped_column(String(10), nullable=False)
    risk_rating: Mapped[str] = mapped_column(String(10), nullable=False)

    response_strategy: Mapped[str | None] = mapped_column(String(30), nullable=True)
    response_plan: Mapped[str | None] = mapped_column(Text, nullable=True)

    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    practice_lead_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    status: Mapped[str] = mapped_column(
        String(30), default="Suggested", nullable=False, index=True
    )
    source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    raised_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    identified_during: Mapped[str | None] = mapped_column(String(100), nullable=True)

    source_file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_file_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    source_risk_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    llm_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Semantic embedding of the risk text (text-embedding-3-small, 1536 dims).
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)

    sla_deadline: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sla_manual_override: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    risk_start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    risk_end_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    accepted_date: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_date: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_date: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    what_worked: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolution_category: Mapped[str | None] = mapped_column(String(100), nullable=True)

    project: Mapped[Project] = relationship(back_populates="risks")
    owner: Mapped[User | None] = relationship(foreign_keys=[owner_user_id])
    practice_lead: Mapped[User | None] = relationship(foreign_keys=[practice_lead_user_id])
    audit_log: Mapped[list[RiskAuditLog]] = relationship(back_populates="risk")


class RiskAuditLog(Base):
    """Append-only audit trail. Rows are never updated or deleted."""

    __tablename__ = "risk_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    risk_id: Mapped[int] = mapped_column(ForeignKey("risks.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    field: Mapped[str | None] = mapped_column(String(100), nullable=True)
    old_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    new_value: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    snapshot_before: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    snapshot_after: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    risk: Mapped[Risk] = relationship(back_populates="audit_log")


class PracticeLead(TimestampMixin, Base):
    """Maps a practice (skill area) to a lead's email/user, for notification CC."""

    __tablename__ = "practice_leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    practice: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class Setting(TimestampMixin, Base):
    """Key/value system configuration (PMO Lead email, SLA thresholds, etc.)."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text)


class SuggestionDismissal(Base):
    """Per-project exclusions: a dismissed suggestion never reappears for that project."""

    __tablename__ = "suggestion_dismissals"
    __table_args__ = (UniqueConstraint("project_id", "historical_risk_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    historical_risk_key: Mapped[str] = mapped_column(String(500), index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Notification(TimestampMixin, Base):
    """In-app notification for a user (bell + unread count in the frontend)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipient_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    risk_id: Mapped[int | None] = mapped_column(ForeignKey("risks.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id"), nullable=True, index=True
    )
    read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
