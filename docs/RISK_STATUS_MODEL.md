# Risk Status Model (authoritative clarification)

This document is the single reference for the risk lifecycle as **actually
implemented**. It is grounded in:

- `backend/src/riskapp/domain/status.py` — states + transition table (source of truth)
- `backend/src/riskapp/services.py` — transition helpers and business guards
- `backend/src/riskapp/scheduler.py` — automatic transitions
- `backend/src/riskapp/auth.py` — who may perform each transition
- `frontend/src/utils/status.ts` — UI mirror of the transition table

> The backend is authoritative. The frontend only hides invalid options; every
> mutation is re-validated and audited on the server.

## 1. States

Exactly one status per risk at a time. Nine states:

| Status (stored value) | UI label | Meaning | Category |
|---|---|---|---|
| `Suggested` | Suggested | Created by an LLM/historical suggestion or Quick Add; not yet accepted | Pre-lifecycle |
| `Open` | Open | Accepted and live; awaiting first action | Active |
| `In Progress` | In Progress | Owner working the risk | Active |
| `Escalated` | Escalated | Owner failed to acknowledge by **End Date − 2 days**; owner + PM notified, **no Issue** | Active |
| `Event` | **Materialized** | Risk materialized (End Date passed unresolved, or manually marked) | Active (issue-bearing) |
| `Pending Resolution` | Pending Review | Owner proposed a resolution; PM must accept/reject | Active (under review) |
| `Resolved` | Resolved | PM accepted the resolution | Closed-ish (pre-close) |
| `Closed` | Closed | Formally closed, read-only | Terminal |
| `Dismissed` | Dismissed | A `Suggested` risk the PM rejected | Terminal |

`Event` is the only state with a **display-label override** (`Materialized`).
See `domain/status.py::DISPLAY_LABELS`.

## 2. Transition table (backend `_TRANSITIONS`)

| From | Allowed → | 
|---|---|
| `Suggested` | `Open`, `Dismissed` |
| `Open` | `In Progress`, `Escalated`, `Event`, `Pending Resolution` |
| `In Progress` | `Escalated`, `Event`, `Pending Resolution` |
| `Escalated` | `In Progress`, `Event`, `Pending Resolution` |
| `Event` | `Pending Resolution` |
| `Pending Resolution` | `Resolved`, `In Progress` |
| `Resolved` | `Closed` |
| `Closed` | *(none)* |
| `Dismissed` | *(none)* |

Any transition not in this table raises `InvalidTransitionError`
(`domain/status.py::ensure_transition`). The API maps this to **409** in
`PATCH /api/risks/{id}` and **422** in the resolution endpoints.

## 3. Who may trigger what

| Transition | Trigger | Server enforcement |
|---|---|---|
| `Suggested → Open` / `→ Dismissed` | PM accept / dismiss | `services.accept_risk` / `dismiss_risk` |
| `Open → In Progress` | **Risk Start Date arrives** | scheduler `run_start_date_activation`, and at create/edit when a start date at or before today is supplied. Owner assignment/acknowledgement do **not** advance the status |
| `Open`/`In Progress`/`Escalated`/`Event → Pending Resolution` | **Risk Owner** (external link) | `services.resolve_risk`, `main.external_resolve`; requires a non-empty **Resolution and Mitigation Summary** |
| `Pending Resolution → Resolved` | PM / PMO Lead / System Admin | `services.accept_resolution`, `can_review_resolution` |
| `Pending Resolution → In Progress` | PM / PMO Lead / System Admin | `services.reject_resolution`; **reason mandatory** |
| `Escalated → In Progress` | PM / PMO Lead | `services.de_escalate_risk` |
| `→ Event` (manual) | Anyone who can edit the risk | `services.update_risk`; creates the single Issue |
| `Resolved → Closed` | Project PM / PMO Lead / System Admin | `auth.can_close_risk` **and** `auth.can_finally_close_risk` (status must be `Resolved`) |
| **Owner close** | — | **Never allowed** |

### Closure rules (already implemented)
- A risk can only be closed when `status == "Resolved"` (i.e. the PM accepted
  the resolution). `Resolved → Closed` is the only path to `Closed`.
- `can_close_risk` answers "may this caller close risks for this project?"
  (project PM, or PMO Lead / System Admin).
- `can_finally_close_risk` additionally requires `status == "Resolved"`, and is
  what the API uses to give a precise 409 reason otherwise.
- Closing an individual risk does **not** close its project/register.

## 4. Automatic transitions (scheduler)

All run in the **business timezone** (`settings.tz`, default `Africa/Lagos`),
via Celery Beat (`celery_app.py`) → `tasks.py` → `scheduler.py`. Source `today`
comes from `tasks._today()`.

| Job | Beat (UTC) | Rule | Result |
|---|---|---|---|
| `run_start_date_activation` | 06:05 | `status == Open` AND start set AND `start ≤ today` | `→ In Progress`; owner + PM notified |
| `send_daily_reminders` | 06:00 | `status in (Open, In Progress)` AND start & end set AND unacknowledged AND `start ≤ today ≤ end−3` | reminder email (no status change) |
| `escalate_unacknowledged_risks` | 06:15 | `status in (Open, In Progress)` AND end set AND unacknowledged AND `today ≥ end−2` | `→ Escalated`; owner + PM notified; **no Issue** |
| `materialize_overdue_risks` | 06:30 | `status in (Open, In Progress, Escalated)` AND end set AND `end < today` | `→ Event` + exactly one `Issue` |
| `weekly_summary` | Mon 08:00 | see `WEEKLY_REPORT_RULES.md` | report email |

Idempotency guards:
- Reminders: `Risk.last_reminder_on == today` check.
- Materialization: `Issue.source_risk_id` is UNIQUE; `ensure_issue_for_risk` +
  `find_event_risks_without_issue` backfill.
- Escalation: transition table prevents re-escalating an already-`Escalated`
  risk; job only scans `Open`/`In Progress`.

## 5. Concepts that are *not* status

| Concept | Stored as | Notes |
|---|---|---|
| **Acknowledgement** | `Risk.sla_acknowledged` (bool) + `acknowledged_at` | Independent of status. Acknowledgement never changes status by itself. |
| **Resolution summary** | `Risk.resolution_summary` + `resolution_submitted_at` / `_by_user_id` | Mandatory before `→ Pending Resolution` and before `→ Resolved`. Retained across rejections; history is append-only. |
| **Materialized Issue** | `Issue` row (1:1, unique `source_risk_id`) | `Issue.status` is its own lifecycle (`Open`…). Created only for `Event` risks. Escalation never creates an Issue. |
| **Audit trail** | `RiskAuditLog` (append-only) | Every status change writes `action="status_change"` with old/new/user. |

## 6. Confirmed behaviour (decisions signed off)

1. **SLA / Risk End Date is PM-defined, not rating-derived (D1 = keep).**
   `domain/sla.py`: the Risk Start Date is the SLA start and the **Risk End Date
   *is* the SLA deadline**. `risk_rating` expresses severity only and drives
   neither deadline nor cadence. KEEP as-is.

2. **`Open → In Progress` is gated on the Risk Start Date (D2).**
   Owner assignment and acknowledgement no longer advance a risk. It activates:
   - immediately when created/edited with a start date at or before today, and
   - by the daily `run_start_date_activation` job for start dates that arrive
     later. The job also catches up after downtime.

3. **No start date ⇒ the risk stays `Open` with no monitoring (D3).**
   Reminders require start *and* end; escalation/materialization require end. A
   risk without a start date is therefore never activated, reminded, escalated
   or materialized until a start date is set.

4. **Risk dates cannot precede the project start (D4).**
   Both the Risk Start Date **and** the Risk End Date must be `>=` the project
   Start Date (`services.validate_risk_within_project`), enforced on create and
   edit at the service layer (never only in the form). Back-dating is a
   *project*-level allowance; a risk may still start in the past, but never
   before its project.

5. **Monitors ignore risks without dates** (reminders need start + end;
   escalation/materialization need end). Consistent, and unchanged.

6. **`Event` can be set manually** as well as by the scheduler; both paths create
   the single Issue.
