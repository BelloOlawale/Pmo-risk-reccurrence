# Weekly PMO Lead Report — Counting Rules (authoritative clarification)

Source of truth: `backend/src/riskapp/reports.py` (`build_weekly_report`,
`render_html`, `render_text`, `run_weekly_report`). Schedule:
`celery_app.py` → `tasks.weekly_summary` → `scheduler.run_weekly_summary`.
API: `GET /api/reports/weekly`, `POST /api/reports/weekly/send`.

## 1. Scope

- **Unit of scope:** projects, each with its risks.
- **In-scope risks** are those whose status is in `IN_SCOPE_STATUSES`:
  `Open`, `In Progress`, `Pending Resolution`, `Escalated`, `Event`,
  `Resolved`, `Closed`.
- **Excluded risks** and reported only as a note: `Suggested`, `Dismissed`.
- **PM scoping:** a Project Manager receives a report containing only projects
  where `project.pm_user_id == their user id`. PMO Lead / System Admin receive
  the whole portfolio.

## 2. Period

- **Window:** the trailing seven days ending on `today`, inclusive —
  `period_start = today − 6 days`, `period_end = today`.
- `today` is passed in by callers. **Known inconsistency (to fix):** the Celery
  task and the API both use server-local `dt.date.today()`, whereas
  reminders/escalation/materialization use `tasks._today()` in the business
  timezone (`settings.tz`). The report should use the business timezone too.
- `resolved_this_period` = in-scope risks whose `resolved_date` (date part) falls
  in `[period_start, period_end]`. This is the **only** "change during the
  period" metric today.

## 3. Counts — one bucket per status, no double counting

Each in-scope risk contributes to **exactly one** column. Totals are the sum of
the buckets: `total_risks == Σ counts`, and per-project counts sum to the same
totals (`test_totals_reconcile_with_project_counts`).

| Column label | Matches status | Meaning |
|---|---|---|
| Open | `Open` | Accepted, awaiting first action |
| In Progress | `In Progress` | Owner working |
| Pending Review | `Pending Resolution` | Awaiting PM accept/reject |
| Escalated | `Escalated` | Unacknowledged at End Date − 2 |
| Events | `Event` (UI "Materialized") | Materialized; has one Issue |
| Resolved | `Resolved` | Resolution accepted, not yet closed |
| Closed | `Closed` | Formally closed |

Exec-summary metrics additionally show: **Projects covered**,
**Risks in scope**, and **Resolved this period**.

### Overlap / non-exclusivity notes (important)
- The **status columns are mutually exclusive** — a risk is in one and only one.
- **"Risks requiring attention" is a separate, overlapping view**: a risk can be
  simultaneously overdue, escalated and materialized. It still appears **once**
  in the detail table, with one or more reason tags.
- **"Resolved this period" overlaps the `Resolved` column** (a risk resolved this
  week is counted in both). Do not add the two together.
- **Escalated status does not imply an Issue.** Only `Event` risks have Issues.
- `Suggested` and `Dismissed` are never counted in any column and are surfaced
  only in the "Not counted" footnote.

## 4. "Risks requiring attention"

A risk row is included in the attention detail table when **any** of:

| Reason tag | Rule |
|---|---|
| `overdue` | status in `Open`/`In Progress`/`Escalated` **and** `risk_end_date < today` |
| `awaiting review` | status == `Pending Resolution` |
| `escalated` | status == `Escalated` |
| `materialized` | status == `Event` |

Ordering: overdue rows first, then by status, then risk code. Fields shown: Risk
Code (links to `/risks/{id}`), Description, Project, Risk Owner, Current Status,
Rating, Risk End Date, Resolution Summary (truncated to 240 chars, `—` if none).

## 5. Grouping & identity

- Hierarchy: **Project Manager → project → risk**.
- Projects are grouped by `project.pm_user_id`; projects with no PM (or an
  external user as PM) go to a single **"Unassigned Project Manager"** section.
  Sections are ordered with the unassigned bucket last, then by name.
- Every project is associated with exactly one PM via `pm_user_id`; risk rows do
  not hide project ownership.

## 6. Recipients & delivery

- **PMO Lead:** full portfolio, sent to `Setting("pmo_lead_email")` when set.
- **Each Project Manager:** a scoped copy covering only their projects, sent to
  their UPN (in-app + email).
- **Risk Owner / other roles:** no portfolio report access (403 on the API);
  owners act only through their signed single-risk link.
- Both HTML (`render_html`, inline CSS, ≤720px) and plain-text
  (`render_text`) parts are produced.

## 7. Idempotency & scheduling

- `Setting("last_weekly_report_on")` stores the last run date (ISO). A second run
  on the same day is skipped unless `force=true`, preventing duplicate emails
  and in-app notifications.
- Beat schedule: `weekly-summary-monday`, `crontab(day_of_week=0, hour=8,
  minute=0)` (UTC). The schedule itself is unchanged by this work.

## 8. Subject line

- Email subject (current):
  `PMO Risk Intelligence — Weekly Portfolio Risk Report (<period_end>)`.
- API subject (current): `PMO Risk Intelligence — Weekly Portfolio Risk Report`
  (no period).
- **Requested format:** `PMO Risk Intelligence | Weekly Portfolio Risk Report |
  [Reporting Period]` — i.e. include the full `period_start – period_end`.
  This is a cosmetic change; decide the exact date format (`dd Mmm yyyy` is used
  elsewhere).

## 9. Gaps vs. the requested report (need a decision)

1. **"Significant changes during the reporting period":** only
   `resolved_this_period` exists. Proposed additions (all derivable from
   `RiskAuditLog` / dates, no new tables): newly **raised** risks
   (`created_at` in window), newly **escalated** and newly **materialized**
   (audit `status_change` rows in window). Definitions must be agreed so nothing
   is hardcoded and no metric is shown when data is absent.
2. **Timezone:** switch report `today` to the business timezone (align with
   `tasks._today()`), for all three entry points (task, API GET, API send).
3. **Subject:** include the full reporting period (see §8).
4. **Legacy `weekly_summary_data`** in `scheduler.py` (counts `Resolved` +
   `Closed` as "closed", `resolution_rate`) is used only by
   `tests/test_scheduler.py`. The authoritative report path is
   `run_weekly_report`. Either retire the legacy helper or document it as
   non-authoritative.
