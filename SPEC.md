# PMO Risk Recurrence Predictor — Consolidated Build Spec

> Result of the design grill session (2026-08-20).
> This merges two source documents:
> - `project_brief/PMO_Risk_Recurrence_Predictor_FRD_v1.0.docx` (enterprise vision)
> - `Pmo-risk-reccurrence/PMO_Risk_Management_Document.docx` (pragmatic SharePoint/LLM spec)
>
> Where they conflict, the decisions below are authoritative. Where a previous
> implementation exists (`../risk_reccurrence_predictor`), its pure logic (LLM layer,
> import pipeline, scoring) is ported; its SharePoint/Function-App scaffolding is not.

---

## 1. Product Definition

A **standalone web application** that automates project risk management: a PM creates
a project, the system suggests recurring risks from historical data (hybrid search +
LLM analysis with citations), risks are captured quickly, scored simply, monitored with
daily owner reminders, escalated when unacknowledged, materialized into an Issue when
unresolved past the Risk End Date, resolved, and closed — feeding learnings back so
future suggestions improve.

**Explicitly NOT used:** SharePoint, Power Apps, Power BI, Power Automate.

**Purpose:** production use by the Wragby PMO. MVP first, expanding later.

---

## 2. Technology Stack

| Concern | Choice |
|---|---|
| Backend | Python + **FastAPI** (single modular monolith) |
| Frontend | **React + TypeScript**, charts via **Apache ECharts** |
| Database | **PostgreSQL** (Azure Database for PostgreSQL Flexible Server) + **pgvector** |
| Background jobs | **Celery + Redis (Azure Cache for Redis) + Celery Beat** |
| File storage | **Azure Blob Storage** (uploaded registers, citation links) |
| Email | **Azure Communication Services** |
| LLM | **Azure OpenAI** (GPT-4o-mini chat + text-embedding-3-small) |
| Auth | **Entra ID (M365) SSO** via OIDC |
| Secrets | **Azure Key Vault** |
| Compute | **Azure Container Apps** (web app + Celery worker + Beat) |
| CI/CD | GitHub Actions → Azure Container Registry → Container Apps |
| Environments | **dev + prod** (no staging) |

---

## 3. Data Model

Hierarchy (derived from the actual `Project/<DEPARTMENT>/<PROJECT TYPE>/` folder layout):

```
department (e.g. "Digital Advisory", "SAP", "Software Engineering")
   └── project_type (data-driven lookup, ~20 values, NOT an enum)
         └── project (a specific client engagement, e.g. "NHIA AWS")
               └── risk_register (implicit per project)
                     └── risk
```

Core entities:
- **department** — top-level org axis. "Portfolio" = across departments.
- **project_type** — lookup table (Cloud Migration, ERP Implementation, etc.)
- **project** — id, name, type, customer, department, PM, start date, stage gate, status.
- **risk** — current-state record (fields below).
- **risk_audit_log** — **append-only, immutable**. Every mutation writes a row
  (field, old_value, new_value, user, timestamp; JSONB before/after snapshot).
  Source of truth for change history, activity detection, and the audit trail.
- **issue** — raised automatically when an unresolved risk passes its **Risk End
  Date** (status → `Event`, displayed as "Materialized"). Inherits the originating
  risk's business fields (description, category, source, likelihood/impact/
  rating, response, owner, dates) and keeps a foreign key back to it;
  `source_risk_id` is **unique**, so a materialized risk generates **exactly one**
  Issue (idempotent by construction).
- **user / role** — Entra ID identity + role mapping.
- **practice_lead** — department → person mapping (auto-CC on notifications).
- **settings** — key/value config (PMO Lead email, Head of PM email, SLA thresholds).
- **suggestion_dismissal** — per-project exclusions (dismissed suggestions don't reappear).

### Risk record fields (merged from both docs)

| Field | Notes |
|---|---|
| id | auto-generated, e.g. `RSK-001` |
| project_id | FK |
| description | required |
| category, subcategory | |
| risk_source | Human / Environmental / Technical (FRD) |
| likelihood | **Low / Medium / High** |
| impact | **Low / Medium / High** |
| risk_rating | **Low / Medium / High** (computed, see §4) |
| response_strategy | Mitigate / Transfer / Avoid / Accept |
| response_plan | text |
| owner | user (defaults to PM) |
| practice_lead | auto-looked-up by department |
| status | lifecycle (see §5) |
| source | Historical / Custom / Kickoff |
| raised_by, identified_during | |
| source_file_name, source_file_url, source_risk_id | traceability to original register |
| llm_analysis | text |
| sla_deadline, sla_acknowledged | |
| risk_start_date, risk_end_date | active window; `risk_start_date` is the SLA anchor and triggers an owner email; **`risk_end_date` is the materialization deadline** (start date + SLA window) |
| accepted_date, resolved_date, closed_date | |
| root_cause, what_worked, resolution_category | closure fields |
| created_at, updated_at | |

---

## 4. Scoring (simple 3-level, no Critical flag, no 1–25, no 5 dimensions)

Risk Rating is computed from Likelihood × Impact via the standard 3×3 matrix:

| Likelihood ↓ / Impact → | High | Medium | Low |
|---|---|---|---|
| **High** | High | High | Medium |
| **Medium** | High | Medium | Low |
| **Low** | Medium | Low | Low |

- Pure, deterministic, exhaustively unit-tested function.
- No Critical band. No numeric 1–25 score. No CIA/Regulatory/Strategic dimensions.

---

## 5. Status Lifecycle

```
Suggested ──► Open ──► In Progress ──► Escalated ──► Event ──► Pending Resolution ──► Resolved ──► Closed
```

| Status | Meaning |
|---|---|
| Suggested | Created by an LLM/historical suggestion; not yet accepted |
| Open | Live (accepted or manually added); SLA assigned, owner assigned manually; awaiting first action |
| In Progress | Owner acknowledged / working |
| Escalated | Acknowledgement not received by two days before the Risk End Date; owner + PM notified, no Issue created |
| Event | Risk materialised (displays as "Materialized"); set **automatically** when the Risk End Date passes with the risk still unresolved, or **deliberately** when the owner/PM changes the status to Event |
| Pending Resolution | The Risk Owner proposed a resolution; the Project Manager reviews it |
| Resolved | The Project Manager accepted the proposed resolution; residual acceptable |
| Closed | Formally closed with root cause / lessons learned; read-only |

Special cases:
- **Dismissed** — a Suggested risk the PM rejects (tracked separately, never reappears for that project).
- Enforced valid transitions; no override without an audit-log entry.

### Acknowledgement vs resolution vs materialization

These are three distinct concepts:

- **Acknowledged** — the owner has responded; the SLA acknowledgement
  requirement is permanently satisfied. The risk stays active.
- **Pending Resolution** — the owner proposed a resolution; status `Pending
  Resolution`, awaiting the Project Manager's accept/reject. No materialization,
  no Issue.
- **Resolved** — the Project Manager accepted the owner's resolution; status
  `Resolved`. No materialization, no Issue.
- **Materialized** — the risk was **not** resolved by its Risk End Date, or the
  owner/PM deliberately marked it as having occurred; status → `Event`
  (displays as "Materialized"), one Issue is auto-created.

Both materialization paths behave identically and are **backend** operations —
never a frontend client-side date check:

1. **Automatic (end date)** — an hourly job fires when `risk_end_date` has
   fully passed (business timezone) and the status is still
   `Open` / `In Progress` / `Escalated`.
2. **Manual** — a user with risk access transitions the status to `Event`
   directly; the transition creates the single Issue immediately (no waiting
   for the hourly sweep).

`Resolved` / `Closed` / `Dismissed` / `Suggested` risks never materialize, the
original risk is never deleted, and `Event` is **not** `Closed` — only the PMO
Lead may perform the final closure (unchanged).

---

## 6. Monitoring, reminders & escalation

Monitoring is **day-based** (Celery Beat, daily) in the configured business
timezone (env `RISKAPP_APP_TIMEZONE`, default `Africa/Lagos`). Dates are compared
date-only, so risks are never acted on early because of a timezone or
midnight-boundary skew. The **Risk End Date is both the SLA deadline and the
resolution deadline** (end of that day).

Given `start` = Risk Start Date and `end` = Risk End Date:

1. **Daily acknowledgement reminders** — from `start` up to and including
   `end − 3 days`, the Risk Owner is emailed **once per day** while the risk is
   unacknowledged. Reminders stop as soon as the owner acknowledges. Each send
   is stamped on the risk (`last_reminder_on`) so re-runs are idempotent.
2. **Escalation** — from `end − 2 days`, a risk that is still **unacknowledged**
   is escalated: status → `Escalated` and an escalation email is sent to the
   **Risk Owner and the Project Manager**. Escalated risks keep their owner and
   are worked as normal; **escalation never creates an Issue** and an escalated
   risk **does not appear in the Issues table**.
3. **Materialization** — once `end` has passed (`end < today`) and the risk is
   still **unresolved** (`Open` / `In Progress` / `Escalated`), status → `Event`
   (displays as "Materialized"), the **Project Manager** is emailed the risk and
   owner details, and exactly one **Issue** is created. The risk then appears in
   the Issues table. `Resolved` / `Closed` / `Dismissed` / `Suggested` risks
   never materialize.

- **Acknowledgement** (in-app or from the emailed secure link) permanently
  satisfies the acknowledgement requirement and stops reminders; it does not
  resolve the risk.
- **Activity** no longer stops the clock: only acknowledgement does.
- Escalation is time-driven only (no Critical flag, no score-change triggers).
- De-escalation: PM or PMO Lead only, with written rationale (audit-logged).

---

## 7. Risk Suggestions & "Recurrence"

"Recurrence" = the suggestion engine. No probability classifier, no SHAP, no 0–100% score.

On project creation, retrieve candidate historical risks via **full hybrid search**:
1. **Exact** — Department + ProjectType match (always included).
2. **Keyword** — category / subcategory / description token match.
3. **Semantic** — pgvector embedding similarity.

Merge, dedupe, rank. Then **Azure OpenAI** generates the risk-landscape overview,
per-risk analysis, and recommendations with **grounded citations** (`[RiskID, file.xlsx]`).
Every citation is **audited** against the retrieved payload before display (the
existing `evaluation.py` groundedness check is ported).

---

## 8. Data Ingestion

- **One-time seed:** port the existing import pipeline (`excel_parser.py` →
  `field_mapper.py` → `importer.py`) to load the ~273 historical risks / 21 projects
  into Postgres. Legacy Low/Med/High text maps straight through (provisional).
- **Admin upload UI:** PMO Lead / System Admin uploads `.xlsx`, field-mapping +
  preview, import (reuses the tested field mapper).
- **Deferred:** Jira / Azure DevOps / MS Project API connectors.

---

## 9. Notifications

- Channels: **email (Azure Communication Services) + in-app** (React bell + unread count).
- Email action buttons = **deep links** into the React app (not SharePoint forms).
- Risk Owners (internal and external) act from a **signed, single-risk link**
  emailed to them — they are not expected to sign in to the app. Staff
  notifications link into the React app as deep links.
- Matrix:
  - Owner assignment → owner (secure link) + PM + PMO Lead + Practice Lead (CC)
  - Daily acknowledgement reminder → owner (secure link)
  - Escalation (unacknowledged at `end − 2 days`) → owner (secure link) + PM
  - **Materialization (Event → Issue created) → PM (email) + PMO Lead (CC)**, with
    the risk and owner details
  - Weekly summary (Mon 8 AM) → PM + PMO Lead
  - Closure confirmation → PM + PMO Lead

> Owner-specific emails (assignment, reminder, escalation) are sent to the owner
> separately from the staff notification so the owner receives the signed
> single-risk link and staff receive the in-app deep link.

---

## 10. RBAC

Three permission roles (mapped to **Entra ID security groups**):

| Role | Permissions |
|---|---|
| System Admin | everything: users, config, imports, all data |
| PMO Lead | portfolio, de-escalate, escalation handling, settings, import |
| Project Manager | create projects (automatically assigned as PM); full control of *own* projects' risks |

Record-level assignments (NOT permission roles):
- **Risk Owner** — per-risk assignment (edit own assigned risks).
- **Practice Lead** — department → person mapping (notification recipient).

Row-level scoping: PMs see/edit only their own projects; owners only their assigned
risks; PMO Lead / Admin see all. Enforced in the API layer.
System Admins may also create registers and are assigned as PM when they do.
The PM is fixed at creation; reassignment is not available. Existing registers
retain their recorded PM.
The assigned creator (Project Manager or System Admin) can close the register.

Dropped from MVP: PMO Analyst, Data Scientist, Information Security Manager.

---

## 11. Dashboards & Reporting

- **Project dashboard** (per project): KPI cards, donut (rating), bar (status),
  treemap (category), SLA countdown list, Risk Register table (conditional
  formatting, filters, sort) → drill-through to risk detail page, and an
  **Issues table** beneath the register listing Issues created from materialized
  risks (issue code, description, source risk, rating, status, owner, created)
  → drill-through to an issue detail page.
- **Portfolio dashboard** (PMO Lead): project × category heatmap, risk-by-project
  bar, escalation trend line, portfolio KPIs.
- **Weekly summary email** (Celery, Mon 8 AM).
- **Deferred:** PDF export / scheduled PDF reports, deep trend analysis.

---

## 12. Background Jobs (Celery)

- Daily **owner reminder** job (and daily **escalation** job at `end − 2 days`).
- Daily **end-date monitor**: materialize overdue unresolved risks —
  `risk_end_date` passed and status still `Open` / `In Progress` / `Escalated`
  — to `Event`, email the PM, and auto-create one Issue per risk (idempotent; also backfills an
  Issue for any Event risk that lacks one).
- Daily start-date check — email the owner when `risk_start_date` is today.
- Weekly summary (Monday 8 AM).
- Async email sending.
- Async LLM suggestion generation.
- Admin bulk import.

---

## 13. Build Phases

**Phase 1 — MVP (deterministic spine + suggestions):**
1. Repo scaffolding, FastAPI + Postgres schema + migrations, Entra SSO.
2. Pure domain logic TDD-first: 3×3 scoring, status state machine, SLA deadline +
   activity detection, hybrid-search retrieval.
3. Project creation + register; manual risk entry; Quick Add.
4. Historical seed import (ported pipeline) + admin upload UI.
5. Suggestions: hybrid retrieval + pgvector + LLM analysis + citation audit.
6. Accept / Edit / Dismiss; SLA monitoring + Celery; email + in-app notifications.
7. Project + portfolio dashboards; weekly summary.
8. Deploy (dev + prod).

**Deferred (later phases):** ML recurrence classifier, PDF reports, trend analysis,
API connectors (Jira/Azure DevOps), Data Scientist / InfoSec roles, full FRD
treatment workflow (residual risk scoring, management sign-off).

---

## 14. Key Decisions (quick index)

1. Standalone app; no SharePoint/Power Apps/Power BI.
2. Python/FastAPI + React/TS + PostgreSQL (+ pgvector) + Azure.
3. Celery + Redis + Beat for all background work (scale now, not APScheduler).
4. 3-level scoring (Low/Med/High); no Critical flag, no 1–25, no 5 dimensions.
5. Status: Suggested → Open → In Progress → Escalated → Event → Pending Resolution → Resolved → Closed.
6. Escalation = unacknowledged two days before the Risk End Date only.
7. Light treatment (Response Strategy + Response Plan), no residual scoring.
8. "Recurrence" = hybrid (exact + keyword + semantic) suggestion engine + LLM.
9. One-time seed + admin upload; defer API connectors.
10. Email (Azure Communication Services) + in-app; deep links; Entra ID SSO.
11. Roles: System Admin, PMO Lead, Project Manager (via Entra groups).
12. Dashboards in React (ECharts) + weekly email; defer PDF export.
13. Acknowledgement satisfies the SLA acknowledgement requirement only; it does
    not resolve the risk (acknowledged risks still materialize if unresolved at
    the Risk End Date).
14. Materialization = `risk_end_date` passed (business timezone) + risk
    unresolved → status `Event` ("Materialized") + exactly one auto-created
    Issue; a manual status change to `Event` materializes identically;
    backend-only and idempotent; resolved/closed risks never materialize;
    the PMO Lead keeps sole closure authority.
