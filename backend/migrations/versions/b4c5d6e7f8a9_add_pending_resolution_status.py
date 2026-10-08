"""add Pending Resolution status to in-flight resolutions

The resolution workflow gained an explicit review step: a Risk Owner's
submitted resolution now sits in ``Pending Resolution`` until the Project
Manager accepts (``-> Resolved``) or rejects (``-> In Progress``) it.

Previously the owner's submission moved a risk straight to ``Resolved`` and an
accept kept it there, so pre-existing rows cannot be told apart from accepted
ones by status alone. This migration only flips the rows that are provably
awaiting review: status ``Resolved``, with a ``resolution_submitted`` audit
entry, and *no* ``resolution_accepted`` entry. Accepted and manually-resolved
risks are left untouched.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-10-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4c5d6e7f8a9"
down_revision: str | Sequence[str] | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_risks = sa.table(
    "risks",
    sa.column("id", sa.Integer),
    sa.column("status", sa.String(length=30)),
    sa.column("resolved_date", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)

_audit_log = sa.table(
    "risk_audit_log",
    sa.column("risk_id", sa.Integer),
    sa.column("user_id", sa.Integer),
    sa.column("action", sa.String(length=50)),
    sa.column("field", sa.String(length=100)),
    sa.column("old_value", sa.JSON),
    sa.column("new_value", sa.JSON),
)


def upgrade() -> None:
    """Move owner-submitted, not-yet-accepted resolutions to Pending Resolution.

    Idempotent: after the first pass no row matches (their audit trail now
    contains ``resolution_accepted`` or their status is no longer ``Resolved``).
    """
    bind = op.get_bind()
    submitted = (
        sa.select(_audit_log.c.risk_id)
        .where(_audit_log.c.action == "resolution_submitted")
        .scalar_subquery()
    )
    accepted = (
        sa.select(_audit_log.c.risk_id)
        .where(_audit_log.c.action == "resolution_accepted")
        .scalar_subquery()
    )
    risk_ids = list(
        bind.execute(
            sa.select(_risks.c.id).where(
                _risks.c.status == "Resolved",
                _risks.c.id.in_(submitted),
                _risks.c.id.not_in(accepted),
            )
        ).scalars()
    )
    if not risk_ids:
        return

    bind.execute(
        sa.update(_risks)
        .where(_risks.c.id.in_(risk_ids))
        .values(
            status="Pending Resolution",
            resolved_date=None,
            updated_at=sa.func.now(),
        )
    )
    bind.execute(
        sa.insert(_audit_log),
        [
            {
                "risk_id": risk_id,
                "user_id": None,
                "action": "status_change",
                "field": "status",
                "old_value": "Resolved",
                "new_value": "Pending Resolution",
            }
            for risk_id in risk_ids
        ],
    )


def downgrade() -> None:
    """No-op: a Pending Resolution cannot be safely turned back into Resolved.

    Reverting would either leave every in-flight submission stuck (if untouched)
    or falsely mark unreviewed resolutions as accepted. The status change is
    intentionally not undone.
    """
