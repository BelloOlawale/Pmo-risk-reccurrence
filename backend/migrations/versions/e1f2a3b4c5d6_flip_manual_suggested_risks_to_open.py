"""flip manually-added Suggested risks to Open

Manually captured risks (source ``Custom`` / ``Kickoff``) used to be created in
the ``Suggested`` status and required an explicit accept step. They are now
created directly as ``Open`` (``create_risk`` default changed), so this
one-off data migration brings pre-existing rows in line with the new behaviour.

Only rows where ``source`` is ``Custom`` or ``Kickoff`` are touched — genuine
historical suggestions (``source = 'Historical'``) legitimately sit in
``Suggested`` until a PM accepts or dismisses them, and must not be flipped.

Each changed risk also gets an append-only audit entry recording the
``Suggested -> Open`` transition, matching the trail the application writes.

Revision ID: e1f2a3b4c5d6
Revises: d8e9f0a1b2c3
Create Date: 2026-09-29 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = "d8e9f0a1b2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Sources written by manual capture (the API/quick-add path). Historical corpus
# rows use source="Historical" and are excluded on purpose.
_MANUAL_SOURCES = ("Custom", "Kickoff")

_risks = sa.table(
    "risks",
    sa.column("id", sa.Integer),
    sa.column("status", sa.String(length=30)),
    sa.column("source", sa.String(length=30)),
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
    """Transition manually-added risks stuck in Suggested to Open.

    Idempotent: re-running after the first pass finds no matching rows.
    """
    bind = op.get_bind()
    risk_ids = list(
        bind.execute(
            sa.select(_risks.c.id).where(
                _risks.c.status == "Suggested",
                _risks.c.source.in_(_MANUAL_SOURCES),
            )
        ).scalars()
    )
    if not risk_ids:
        return

    bind.execute(
        sa.update(_risks)
        .where(_risks.c.id.in_(risk_ids))
        .values(status="Open", updated_at=sa.func.now())
    )
    bind.execute(
        sa.insert(_audit_log),
        [
            {
                "risk_id": risk_id,
                "user_id": None,
                "action": "status_change",
                "field": "status",
                "old_value": "Suggested",
                "new_value": "Open",
            }
            for risk_id in risk_ids
        ],
    )


def downgrade() -> None:
    """No-op: the migrated rows cannot be told apart from natively-Open ones.

    Reverting would put freshly captured risks back into an ambiguous
    ``Suggested`` state, so the status change is intentionally not undone.
    """
