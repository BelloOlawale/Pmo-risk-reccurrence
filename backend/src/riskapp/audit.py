"""Append-only audit logging helpers.

Audit rows are written in the same transaction as the mutation they describe.
Rows are never updated or deleted — the audit trail is immutable by convention.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from riskapp import models


def _json_safe(value: Any) -> Any:
    """Convert values to JSON-serializable types for the audit columns."""
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def record_change(
    db: Session,
    risk: models.ProjectRisk,
    *,
    action: str,
    field: str | None = None,
    old_value: Any = None,
    new_value: Any = None,
    actor_user_id: int | None = None,
) -> models.RiskAuditLog:
    """Append one immutable audit entry for a change to ``risk``."""
    entry = models.RiskAuditLog(
        risk_id=risk.id,
        user_id=actor_user_id,
        action=action,
        field=field,
        old_value=_json_safe(old_value),
        new_value=_json_safe(new_value),
    )
    db.add(entry)
    return entry
