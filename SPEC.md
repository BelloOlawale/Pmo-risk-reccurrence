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
LLM analysis with citations), risks are captured quickly, scored simply, monitored on
SLA deadlines, escalated on breach, resolved, and closed — feeding learnings back so
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
| risk_start_date, risk_end_date | active window; `risk_start_date` is the SLA anchor and triggers an owner email |
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
Suggested ──► Open ──► In Progress ──► Escalated ──► Event ──► Resolved ──► Closed
```

| Status | Meaning |
|---|---|
| Suggested | Created by LLM suggestion or Quick Add; not yet accepted |
| Open | Accepted and live; owner + SLA assigned; awaiting first action |
| In Progress | Owner acknowledged / working |
| Escalated | SLA breached (no activity before deadline) |
| Event | Risk materialised (displays as "Materialized") |
| Resolved | Issue resolved; residual acceptable |
| Closed | Formally closed with root cause / lessons learned; read-only |

Special cases:
- **Dismissed** — a Suggested risk the PM rejects (tracked separately, never reappears for that project).
- Enforced valid transitions; no override without an audit-log entry.

---

## 6. SLA & Monitoring

| Rating | SLA deadline | Warning |
|---|---|---|
| High | 24 hours | 4 hours before |
| Medium | 48 hours | 12 hours before |
| Low | 5 days (120h) | 24 hours before |

- The deadline is computed from **`risk_start_date`** (midnight of that day +
  the rating's response window), **not** from when the risk was created. When a
  risk has no `risk_start_date`, it falls back to `created_at`.
- The anchor is **timezone-aware**: midnight is taken in the configured business
  timezone (env `RISKAPP_APP_TIMEZONE`, default `Africa/Lagos`) and stored as
  UTC. The SLA clock starts ticking when `risk_start_date` is reached.
- Changing `risk_rating` or `risk_start_date` recomputes the deadline unless it
  is manually overridden.
- Checked **hourly** (Celery Beat).
- **Activity** = any of: (a) an audit-log entry by the owner (field edit, status
  change, note), or (b) explicit **Acknowledge**. Once activity occurs, the SLA is
  **permanently satisfied** — no more reminders.
- **Breach** = deadline passed with no activity → status **Escalated**, notify
  Owner + PM + PMO Lead.
- **Escalation is SLA-driven only** (no Critical flag, no score-change triggers).
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
- Matrix (from the docs):
  - Owner assignment → owner + PM + PMO Lead + Practice Lead (CC)
  - SLA warning → owner
  - Breach / escalation → owner + PM + PMO Lead
  - Risk start date → owner (email + in-app, sent on `risk_start_date`)
  - Weekly summary (Mon 8 AM) → PM + PMO Lead
  - Closure confirmation → PM + PMO Lead

---

## 10. RBAC

Three permission roles (mapped to **Entra ID security groups**):

| Role | Permissions |
|---|---|
| System Admin | everything: users, config, imports, all data |
| PMO Lead | portfolio, de-escalate, escalation handling, settings, import |
| Project Manager | create projects; full control of *own* projects' risks |

Record-level assignments (NOT permission roles):
- **Risk Owner** — per-risk assignment (edit own assigned risks).
- **Practice Lead** — department → person mapping (notification recipient).

Row-level scoping: PMs see/edit only their own projects; owners only their assigned
risks; PMO Lead / Admin see all. Enforced in the API layer.

Dropped from MVP: PMO Analyst, Data Scientist, Information Security Manager.

---

## 11. Dashboards & Reporting

- **Project dashboard** (per project): KPI cards, donut (rating), bar (status),
  treemap (category), SLA countdown list, Risk Register table (conditional
  formatting, filters, sort) → drill-through to risk detail page.
- **Portfolio dashboard** (PMO Lead): project × category heatmap, risk-by-project
  bar, escalation trend line, portfolio KPIs.
- **Weekly summary email** (Celery, Mon 8 AM).
- **Deferred:** PDF export / scheduled PDF reports, deep trend analysis.

---

## 12. Background Jobs (Celery)

- Hourly SLA monitor (remind / escalate).
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
5. Status: Suggested → Open → In Progress → Escalated → Event → Resolved → Closed.
6. Escalation = SLA breach only.
7. Light treatment (Response Strategy + Response Plan), no residual scoring.
8. "Recurrence" = hybrid (exact + keyword + semantic) suggestion engine + LLM.
9. One-time seed + admin upload; defer API connectors.
10. Email (Azure Communication Services) + in-app; deep links; Entra ID SSO.
11. Roles: System Admin, PMO Lead, Project Manager (via Entra groups).
12. Dashboards in React (ECharts) + weekly email; defer PDF export.
