# #15 — Risk ⇄ Project Normalization (Risk_Project junction) — Impact Assessment & Migration Plan

> **Status:** PLANNING ONLY — nothing implemented.
> **Author:** analysis produced by codebase inspection.
> **Date:** 2026-09-02
>
> This document is the complete impact assessment and migration plan for
> normalizing the `Risk → Project` relationship into a `Risk ↔ Risk_Project ↔
> Project` model. It must not be executed until explicitly approved.
>
> **Open questions (blocking) are listed in §17.**

---

## Goal

Change the current model (a risk is directly tied to a project via a required
FK) into a normalized relational model:

```
PROJECT (project_id, project_name, department, project_status, ...)
RISK    (risk_id, risk_description, risk_category, response_strategy, risk_status, ...)
RISK_PROJECT (risk_id, project_id)
```

Active Risk Register derivation rule:

```
Project.Status = Active  AND  Risk.Status != Resolved  → show
```

Project lifecycle (independent from risk lifecycle):

- New projects → `Active`.
- PM explicitly closes a project.
- Resolving all risks must NOT auto-close a project.
- Adding a risk to a closed project must NOT reactivate it.

---

## 1. Current Data Model

FastAPI (SQLAlchemy) + React/TS + PostgreSQL/pgvector. Actual schema from
`backend/src/riskapp/models.py` and
`backend/migrations/versions/4fecc87133a1_initial_schema.py`.

Hierarchy:

```
department ──< project_type ──< project ──< risk ──< risk_audit_log (append-only)
```

### Tables

| Table | PK | Key columns | Relationships |
|---|---|---|---|
| `departments` | `id` | `name` (unique) | 1–N → projects |
| `project_types` | `id` | `name` (unique) | 1–N → projects |
| `users` | `id` | `upn` (unique), `display_name` | 1–N → projects (pm), risks (owner, practice_lead) |
| `projects` | `id` | `project_code` (unique), `name`, `customer`, `department_id` FK, `project_type_id` FK, `pm_user_id` FK, `start_date`, `end_date`, `stage_gate`, `status` (String, default `"Active"`) | 1–N → risks |
| `risks` | `id` | `risk_code` (unique), **`project_id` FK (NOT NULL, indexed)**, `description`, `category`, `subcategory`, `risk_source`, `likelihood`, `impact`, `risk_rating`, `response_strategy`, `response_plan`, `owner_user_id` FK, `practice_lead_user_id` FK, `status` (default `"Suggested"`), `source`, `raised_by`, `identified_during`, `source_file_name/url/source_risk_id`, `llm_analysis`, `embedding` (vector 1536), `sla_deadline`, `sla_acknowledged`, `sla_manual_override`, `risk_start_date`, `risk_end_date`, `accepted_date`, `resolved_date`, `closed_date`, `root_cause`, `what_worked`, `resolution_category`, timestamps | N–1 → project |
| `risk_audit_log` | `id` | `risk_id` FK, `user_id`, `action`, `field`, `old_value`, `new_value`, `snapshot_before/after`, `created_at` | append-only N–1 → risk |
| `practice_leads` | `id` | `practice` (unique), `email`, `user_id` | lookup |
| `settings` | `id` | `key` (unique), `value` | key/value |
| `suggestion_dismissals` | `id` | `project_id` FK, `historical_risk_key`, `reason` (unique project+key) | N–1 → project |
| `notifications` | `id` | `recipient_user_id`, `type`, `title`, `body`, `risk_id` FK, `project_id` FK, `read` | in-app |

### Current diagram

```
Department
   │ 1
   ▼
ProjectType ──(lookup)──┐
                        │
   Department ─────────┤ (department_id FK)
   ProjectType ────────┤ (project_type_id FK)
                        ▼
                     Project
                        │ 1
                        │ (risks.project_id FK, NOT NULL)
                        ▼
                      Risk ────► RiskAuditLog (append-only)
                        │
                        └──► User (owner, practice_lead)
```

### Key facts

- `risks.project_id` is a **required, indexed FK** → `projects.id`. A risk cannot
  exist without a project today.
- `projects.status` already exists (default `"Active"`) but is **never updated or
  filtered anywhere** — no close-project logic exists.
- `risks.status` drives the full lifecycle
  `Suggested → Open → In Progress → Escalated → Event → Resolved → Closed`
  (+ `Dismissed`), enforced by `domain/status.py`.

---

## 2. Current Project/Risk Relationship (exact mechanism)

A **foreign key on the risk table**: `risks.project_id → projects.id` (NOT NULL,
indexed). Implemented in:

**Backend**
- Model: `models.py` — `Risk.project_id`, `Risk.project`, `Project.risks`.
- Migration: `4fecc87133a1_initial_schema.py` (`ForeignKeyConstraint(['project_id'], ['projects.id'])`).
- Schemas: `schemas.py` — `RiskCreate.project_id` (required), `RiskRead.project_id`, `ProjectRead.risk_count/risk_ids/risk_codes`.
- Services: `services.py` — `create_risk`, `accept_risk` (`risk.project.pm_user_id`), `dismiss_risk` (`risk.project_id`).
- Suggestions: `suggestions.py` — `accept_suggestion`, `exact_candidates`/`keyword_candidates` (`risk.project.*`).
- Import: `import_pipeline/importer.py` (`_build_risk(project_id, ...)`), `import_api.py` (`models.Risk(project_id=...)`).
- Auth: `auth.py` — `can_access_risk` (`risk.project.pm_user_id`).

**API** (`main.py`)
- `POST /api/risks`, `GET /api/risks`, `GET /api/projects`, `GET /api/projects/{id}`,
  `GET /api/projects/{id}/risks`, `POST /api/projects/{id}/suggestions/accept`.

**Frontend**
- Types: `api/types.ts` — `Risk.project_id`, `RiskCreatePayload.project_id`, `Project.risk_*`.
- Components/pages: `AddRiskModal.tsx`, `ActiveRiskRegisterPage.tsx`, `ProjectsPage.tsx`,
  `PortfolioDashboardPage.tsx`, `RiskDetailPage.tsx`.
- Utils: `utils/aggregates.ts` — `riskByProject`, `heatmapData`.

---

## 3. Proposed Data Model

```
ProjectType ─┐
Department ──┤
             ▼
          Project ──┐
                     │ 1
                     ▼
               Risk_Project (junction: risk_id + project_id)
                     │ N
                     ▼
                   Risk
```

### Field disposition

| Disposition | Fields |
|---|---|
| **Remain** | `projects`: all columns. `risks`: all columns **except** `project_id`. |
| **Move** | `risks.project_id` → `risk_projects.project_id`. |
| **New** | `risk_projects` (`risk_id` FK, `project_id` FK, unique `(risk_id, project_id)`, optional `created_at`). |
| **Remove** | `risks.project_id` (after backfill), ORM `Risk.project` / `Project.risks` scalar relationships. |

### Relationships that change

- `Risk.project` (scalar, many-to-one) → `Risk.projects` (list, via junction).
- `Project.risks` (list, one-to-many) → `Project.risks` (list, via junction).
- **Cardinality:** current is strictly **one risk → one project**. The junction
  implies **many-to-many**. This is the single most important decision — see §17.

---

## 4. Data Migration Requirements

### Records affected
- ~272 historical risks / 21 projects (historical import; idempotent).
- 7 demo risks (project 1).
- Any user-created data in the live DB — **count unknown from repo** (DB is
  gitignored/remote).

### Step-by-step (proposed, NOT executed)
1. Backup (full DB snapshot / `pg_dump`).
2. Add `risk_projects` table (new migration): `risk_id` FK, `project_id` FK,
   unique `(risk_id, project_id)`, `created_at`.
3. Backfill: `INSERT INTO risk_projects (risk_id, project_id) SELECT id, project_id FROM risks;`.
4. Verify: `COUNT(risk_projects) == COUNT(risks)`.
5. App cut-over (read/write via junction) while `project_id` still exists, or
6. Drop `risks.project_id` in a later migration (keep nullable during rollback window).
7. Recreate indexes on `risk_projects.project_id` and `risk_projects.risk_id`.

### Duplicates / data loss / IDs / history
- **No duplicates** created by backfill (pure row copy).
- **No data loss** during backfill; the only loss risk is dropping `project_id`
  too early — mitigated by separate later migration.
- **IDs preserved** — no resequencing.
- **Historical relationships preserved** — every risk→project pairing becomes a
  junction row (1:1 copy today).

---

## 5. Seed Data Impact

- **Historical import**: `reference/Project/<Dept>/<ProjectType>/*.xlsx` (38 files),
  loaded by `import_pipeline/importer.py` (`import_directory`). Projects: one per
  `(department, project_type)` (21), named `"{dept} — {type}"`, status `"Active"`,
  risks `status="Closed"`, `source="Historical"`.
- **Demo seed**: `scripts/seed_demo_risks.py` (7 risks on project 1, statuses
  Open/In Progress/Escalated, subcategory `"Demo Seed"`).

Changes needed: `importer.py` (`_build_risk`, `_risk_exists`), `seed_demo_risks.py`,
`import_api.py` all stop writing `risk.project_id` and write a `risk_projects` row.
Existing seeded relationships are carried into the junction by the backfill.

---

## 6. Project Creation Impact

- **Endpoint**: `POST /api/projects` (`main.py::add_project`).
- **Model**: `services.create_project` → `models.Project`.
- **Form**: `pages/OnboardProjectPage.tsx` → `ProjectCreatePayload`.
- **Fields saved**: name, department, project_type, customer, start_date, end_date,
  stage_gate, pm_upn (→ `pm_user_id`). `project_code` auto-generated.
  **`status` hardcoded to `"Active"`** in `create_project`.
- Project Status already exists; the gap is a **close endpoint/UI**.
- Default-to-Active already implemented — no change needed for default.

---

## 7. Risk Creation Workflow Impact

Current flow:
1. `components/AddRiskModal.tsx` (used by `RiskRegistersPage`, `ActiveRiskRegisterPage`).
2. Enters description/category/likelihood/impact/response etc.
3. Selects project → `form.project_id`.
4. `POST /api/risks` with `{ project_id, ... }`.
5. `main.py::add_risk` → `services.create_risk` → `models.Risk(project_id=..., status="Suggested")`.

Future flow:
```
Create Risk → create Risk record → create Risk_Project(risk_id, project_id) → associated
```
Changes: `RiskCreate.project_id` optional (or split create/associate);
`services.create_risk` writes junction; `AddRiskModal` may become multi-select if M:N.

---

## 8. Active Risk Register Impact

**Current**: client-side derivation in `pages/ActiveRiskRegisterPage.tsx`:
fetch `/api/projects` + `/api/risks`; group risks where `isActiveStatus(status)`
(Suggested/Open/In Progress/Escalated/Event) by `r.project_id`. **No project-status
filter; no dedicated endpoint.**

**Future rule**: `Project.Status = Active AND Risk.Status != Resolved`.
- Add project-status filtering (currently absent).
- Decide exclusion set (Resolved only vs terminal set).
- Prefer a backend derived endpoint/view (`GET /api/active-register`) joining
  `project + risk_project + risk`.

---

## 9. Project Closure Impact

- **Does not exist.** No close endpoint/service/migration/UI.
- `projects.status` exists (default `"Active"`), displayed in `ProjectsPage`, but
  **never changed by any code path**.
- Today nothing happens to risks or the register when a project would be "closed".
- **Net-new functionality needed**:
  - `PATCH /api/projects/{id}` (or `/close`).
  - `services.close_project`.
  - Frontend close control on `ProjectDashboardPage` / `ProjectsPage`.
  - Guardrails: resolving risks must not auto-close; adding risk must not reactivate.

---

## 10. Risk Resolution Impact

- **Where**: `PATCH /api/risks/{id}` → `services.update_risk` → `transition_risk`
  (validated by `domain/status.py`). "Resolved" valid from Open/In Progress/Escalated/Event.
- **Effect on project**: none today.
- **Effect on register**: risk drops out (isActiveStatus("Resolved") false).
- **Deletion/modification**: no deletion; status updated in place; audit-logged.
- **History preserved**: yes (append-only `risk_audit_log`).

Under proposed model: resolution is risk-only; `risk_projects` untouched; risk
drops from register when `status == Resolved` **and/or** project `Closed`.

---

## 11. Backend / API Impact

| File | Dependency | Impact |
|---|---|---|
| `models.py` | `Risk.project_id`, `Risk.project`, `Project.risks` | Rewrite relationships; add `RiskProject` model |
| `schemas.py` | `RiskCreate/RiskRead.project_id`, `ProjectRead.risk_*` | `project_id` optional / `project_ids` list |
| `services.py` | `create_risk`, `accept_risk`, `dismiss_risk` | Junction writes; resolve PM via link |
| `suggestions.py` | `accept_suggestion`, `exact/keyword` | Junction + retrieval traversal |
| `import_pipeline/importer.py` | `_build_risk`, `_risk_exists` | Junction writes/queries |
| `import_api.py` | `run_import` | Junction writes |
| `auth.py` | `can_access_risk` | Traverse junction |
| `main.py` | 6+ endpoints | Update queries/scoping |
| `scheduler.py` | status-only (no project status) | Minor: project-status awareness |
| `notifications.py` | `risk`/`project` deep links | Verify link resolution |
| Migrations | initial schema | New migrations |

---

## 12. API Impact (per endpoint)

| Endpoint | Current | Future | Why |
|---|---|---|---|
| `POST /api/risks` | requires `project_id` | create risk + associate via junction | relationship moved |
| `GET /api/risks` | scope via `Risk.project.has(...)` | scope via junction join | traversal |
| `GET /api/risks/{id}` | returns `project_id` | returns `project_ids` (or scalar if 1:1) | schema |
| `PATCH /api/risks/{id}` | no project field | unchanged unless re-association added | low |
| `POST .../accept`, `/dismiss`, `/acknowledge`, `/de-escalate` | uses `risk.project`/`risk.project_id` | traverse junction | internals |
| `GET /api/projects` | group by `Risk.project_id` | join junction | moved |
| `GET /api/projects/{id}` | `risk_count` via `Risk.project_id` | count via junction | moved |
| `GET /api/projects/{id}/risks` | `where(Risk.project_id == id)` | join junction | moved |
| `POST .../suggestions/accept` | creates risk w/ project_id | risk + junction row | moved |
| `POST .../suggest`, `GET .../suggestions` | reads `risk.project.*` | traverse junction | moved |
| `POST /api/imports`, `/confirm` | imports onto project | associate via junction | moved |
| **NEW** `PATCH /api/projects/{id}` | n/a | close project | new lifecycle |
| **NEW** `GET /api/active-register` | n/a | derived register | new view |

---

## 13. Frontend Impact

| Component | Dependency | Change | Risk |
|---|---|---|---|
| `api/types.ts` | `Risk.project_id`, `Project.risk_*`, payloads | `project_ids` / new shape | Medium |
| `components/AddRiskModal.tsx` | sends `project_id` | multi-select / new API | Medium |
| `pages/ActiveRiskRegisterPage.tsx` | group by `r.project_id`, no project filter | add project filter / new endpoint | High |
| `pages/ProjectsPage.tsx` | `risk_ids`/`risk_codes` | junction-derived | Low-Med |
| `pages/PortfolioDashboardPage.tsx` | `riskByProject`/`heatmapData` | junction + project filter | High |
| `pages/ProjectDashboardPage.tsx` | `/projects/{id}/risks`; no close | add close control | Medium |
| `pages/RiskDetailPage.tsx` | back-link `risk.project_id` | multiple projects | Low-Med |
| `pages/RiskRegistersPage.tsx` | `GET /api/risks` | schema-only | Low |
| `components/RiskTable.tsx` | risk fields | none unless project col | Low |
| `components/SuggestionsPanel.tsx` | accept/dismiss | none (backend handles) | Low |
| `utils/aggregates.ts` | `riskByProject`, `heatmapData` | junction | Medium |
| `utils/status.ts` | risk statuses | add project-status notion | Low |
| `utils/colors.ts` | status labels/colors | "Closed" project color | Low |

---

## 14. Complete Dependency Map

```
risk.project_id (FK, NOT NULL, indexed)
│
├── Backend
│   ├── models.py
│   ├── schemas.py
│   ├── services.py
│   ├── suggestions.py
│   ├── auth.py
│   ├── main.py (6+ endpoints)
│   ├── import_pipeline/importer.py
│   ├── import_api.py
│   ├── scheduler.py (status-only, indirect)
│   ├── notifications.py (deep links)
│   └── migrations/
│
├── Frontend
│   ├── api/types.ts
│   ├── components/AddRiskModal.tsx, RiskTable.tsx (low), SuggestionsPanel.tsx (low)
│   ├── pages/ActiveRiskRegisterPage.tsx, ProjectsPage.tsx, PortfolioDashboardPage.tsx,
│   │       ProjectDashboardPage.tsx, RiskDetailPage.tsx, RiskRegistersPage.tsx (low)
│   └── utils/aggregates.ts, utils/status.ts
│
├── Seed / import
│   ├── scripts/seed_demo_risks.py
│   └── reference/Project/**/*.xlsx
│
└── Tests (275+)
    ├── test_models, test_risk_lifecycle, test_api, test_auth,
    ├── test_suggestions, test_suggestion_lifecycle, test_import_api, test_importer,
    ├── test_scheduler, test_notifications, test_pgvector_search, test_vector_store,
    └── test_schemas, test_status (all construct Risk with project_id)
```

---

## 15. Migration Risk Assessment

**Overall: MEDIUM-HIGH** (treat as HIGH for the relationship move).

Why: `risk.project_id` is a **required FK** referenced across ~10 backend files,
6+ endpoints, most frontend pages, both seed paths, and the majority of tests.

Highest-risk areas:
1. Existing data / relationship preservation (drop `project_id` too early = loss).
2. Active Risk Register (adds project-status behavior, not just schema).
3. Authorization `can_access_risk` (traverses `risk.project.pm_user_id`).
4. Suggestions/retrieval (`exact_candidates`/`keyword_candidates`).
5. Project closure (net-new correctness rules).
6. Cardinality ambiguity (M:N vs 1:1 ripples through UI).
7. Dashboards/reporting assume one project per risk.

---

## 16. Backup / Rollback Strategy

Before any migration:
1. Full `pg_dump -Fc` (custom format) of entire DB (incl. `risk_audit_log`,
   `suggestion_dismissals`, `notifications`, `embeddings`).
2. Plain-SQL `pg_dump` as secondary copy.
3. Record `alembic current` + row counts of `projects`, `risks`.
4. Verify backup restores into a scratch DB.

Reversibility: two migrations —
- **A**: add `risk_projects`, backfill, **keep** `risks.project_id` (reversible).
- **B**: drop `risks.project_id` (reversible only while junction holds mappings).

Rollback: restore snapshot, or `alembic downgrade` (A then B); restore if B applied.

No-data-loss verification: after A assert `COUNT(risk_projects) == COUNT(risks)`
and zero NULLs on `risks LEFT JOIN risk_projects`; after B, reverse assertion.

---

## 17. Open Questions (blocking — need answers before implementation)

1. **Live DB state** — DB type/URL and whether real data exists beyond 272
   historical + 7 demo records (need row counts or `pg_dump`; no `.db` in repo;
   prod is Azure PostgreSQL).
2. **Cardinality** — is `Risk_Project` **many-to-many** (risk belongs to multiple
   projects) or a normalized **one-to-one** (one project per risk)?
3. **Active Risk Register exclusion set** — `Resolved` only, or also
   `Closed`/`Dismissed` (current UI excludes all three)?
4. **Project status vocabulary** — only `Active`/`Closed`? Should imported/
   historical projects become `Closed`?
5. **Seed strategy** — keep `seed_demo_risks.py` + historical import, or replace
   with a production data cut?

---

## 18. Proposed Migration Plan (NOT executed)

- **Phase 0 — Backup** (`pg_dump -Fc`, verify restore, record counts/revision).
- **Phase 1 — Schema (non-breaking)** — add `risk_projects` + indexes; keep `project_id`.
- **Phase 2 — Data migration** — backfill junction; assert count parity.
- **Phase 3 — Backend/API** — add `RiskProject` model; update services, suggestions,
  importers, auth, endpoints; keep `RiskRead.project_id` compatibility field during transition.
- **Phase 4 — Frontend** — update types/pages; add project-status filter; close control.
- **Phase 5 — Active Risk Register** — backend derivation (`GET /api/active-register`
  or add project-status to queries).
- **Phase 6 — Project closure** — new endpoint/service/UI with guardrails.
- **Phase 7 — Testing** — update tests constructing `Risk(project_id=...)`; add
  junction/backfill/auth/register tests.
- **Phase 8 — Validation** — counts, E2E, register contents vs rule matrix.
- **Phase 9 — Remove obsolete structure** — separate migration to drop `project_id`
  after soak period.

---

## 19. Potential Breaking Changes

| What | Why | Prevention | Test |
|---|---|---|---|
| Orphaned risks | drop `project_id` before backfill | backfill first; two-phase | count parity |
| Access-control leaks/hides | `can_access_risk` traverses `risk.project` | rewrite + unit tests | `test_auth.py` |
| Register shows closed projects | no project filter | add filter same change | register E2E |
| Suggestions fail | `exact/keyword` read `risk.project.*` | junction join | `test_suggestions.py` |
| Dashboard miscounts | `riskByProject`/`heatmapData` 1-project assumption | junction + `project_ids` | aggregates tests |
| `RiskRead` contract mismatch | scalar vs list | compatibility field + version | `test_schemas.py` |
| Import/seed break | `_build_risk`/`run_import` write `project_id` | junction writes | `test_importer.py`, `test_import_api.py` |
| Closure regressions | new auto-close/reactivate logic | explicit guardrails | new lifecycle tests |

---

## 20. Pre-Implementation Checklist

- [ ] Confirm live DB + record counts (or re-seed acceptable).
- [ ] Confirm cardinality (M:N vs 1:1).
- [ ] Confirm register exclusion set.
- [ ] Confirm project status vocabulary + historical projects → Closed?
- [ ] Take full DB snapshot and verify restore.
- [ ] Record current Alembic revision and row counts.
- [ ] Freeze release branch; CI runs pytest + ruff + mypy + `npm run typecheck`.
- [ ] Write migrations (add+backfill first; drop later).
- [ ] Update/verify all tests before cut-over.

---

## Final status

**ADDITIONAL INFORMATION REQUIRED** — see §17. Cannot safely implement until the
five open questions (especially live DB state and cardinality) are resolved.
