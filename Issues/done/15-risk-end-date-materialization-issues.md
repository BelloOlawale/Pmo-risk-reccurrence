# 15: Risk End Date → Materialized (Event) → Automatic Issue

- **Type:** AFK
- **Spec:** SPEC.md §3, §5, §6, §9, §11, §12
- **Blocked by:** #01, #02, #08, #09, #12
- **Status:** Done (see `progress.txt`)

## What was built

Automated the risk-lifecycle tail: once an unresolved risk passes its **Risk End
Date**, the system transitions it to `Event` (displayed as "Materialized") on the
backend and auto-creates one fully populated **Issue** under the project's Risk
Register. The existing SLA / status / audit / notification / RBAC architecture is
reused — nothing is duplicated.

1. **Issues data model** — `Issue` table (Alembic `c7d9e1f2a3b4`):
   - inherits the originating risk's business fields (description, category,
     subcategory, risk_source, likelihood/impact/risk_rating, response strategy
     + plan, owner, identified_during, risk start/end dates);
   - `source_risk_id` foreign key back to the risk, **unique** — exactly one
     Issue per materialized risk (idempotency guard);
   - `risk.issue` one-to-one relationship; the original risk is never deleted.
2. **Backend automation** (`scheduler.run_end_date_monitor`, Celery Beat hourly
   at :30 via `tasks.materialize_overdue_risks`):
   - finds risks with `status IN (Open, In Progress, Escalated)` and
     `risk_end_date < today` (business timezone — date-only, timezone-safe);
   - transitions each to `Event` through the existing status machine (audited as
     a `status_change`), marks it materialized, and creates the Issue
     (`services.ensure_issue_for_risk`, audited as `issue_created`);
   - a backfill sweep guarantees every `Event` risk has an Issue, so manual
     Event transitions are also covered and repeated runs never duplicate;
   - `Resolved` / `Closed` / `Dismissed` / `Suggested` risks are excluded.
3. **Notification + audit** — materialization notifies owner + PM + PMO Lead
   (email + in-app, `EVENT_MATERIALIZED`); the transition and Issue creation are
   recorded on the append-only `risk_audit_log`.
4. **API** — `GET /api/projects/{id}/issues`, `GET /api/issues/{id}`,
   `GET /api/risks/{id}/issue`; read access mirrors `can_access_risk`
   (PMO Lead / Admin all; project PMs and risk owners their own). Issue `status`
   is its *effective* status, following the materialized risk's lifecycle
   (`Event` → Open, then Resolved / Closed when the PMO Lead closes the risk).
5. **Frontend** — Issues section under each project's Risk Register (active and
   history), an Issue detail page (`/issues/{id}`) showing the inherited risk
   information plus a source-risk link, and a materialization banner linking
   risk detail → Issue. `Event` already renders as "Materialized" throughout.

## Acceptance criteria

- [x] Acknowledgement satisfies the SLA acknowledgement requirement and does not
      resolve the risk
- [x] Owner resolves before the Risk End Date → `Resolved`, no Event, no Issue
- [x] Hourly job materializes expired unresolved risks: status → `Event` +
      Materialized + Issue automatically created
- [x] Resolved / Closed risks are never materialized after their Risk End Date
- [x] Exactly one Issue per materialized risk — automation runs twice, no duplicate
- [x] Issue is linked to the originating risk (`source_risk_id`) and to the
      correct Risk Register/project (`project_id`)
- [x] Issue is fully populated from the originating risk (no blanked fields)
- [x] Issues table appears under each project's Risk Register; Issue detail shows
      the full inherited information and links back to the source risk
- [x] Original risk is retained for audit/history
- [x] Audit trail records the automatic Event transition and Issue creation
- [x] Materialized (`Event`) is not auto-closed; PMO Lead keeps sole closure authority
- [x] Timezone-safe: comparison is date-only in the business timezone (no early
      materialization across midnight/timezone boundaries)
- [x] Backend-persisted automation (Celery Beat), not a frontend date check

## Tests

- `backend/tests/test_materialization.py` — overdue detection, exclusions,
  idempotency, field inheritance, audit trail, notifications, all five
  lifecycle scenarios.
- `backend/tests/test_issues_api.py` — Issues endpoints, per-register scoping,
  row-level access (PM / PMO Lead / owner), risk→issue link, effective status.
- `backend/tests/test_notifications.py` — materialized recipient matrix.
