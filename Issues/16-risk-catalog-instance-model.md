# #16 — Risk Catalog + Project Risk instance — Decided Model & Migration Plan

> **Status:** DESIGN DECIDED — not implemented.
> **Supersedes:** `Issues/15-risk-project-normalization-migration.md` and
> `Issues/15-risk-project-normalization-uml.md` (those assumed a simple junction
> table; the grilling session evolved the target into a full catalog/instance split).
> **Companion docs:** `CONTEXT.md` (glossary), `docs/adr/0001-*`, `docs/adr/0002-*`.
> **Date:** 2026-09-02

---

## 1. Decided domain model

```
PROJECT       Active ⇄ Closed
              (close blocked until all its Project Risks are Resolved/Closed;
               reopen is a separate action; risks can't be added while Closed)

RISK          shared catalog — one entry per risk concept
              (short name + description + category + subcategory + embedding)

PROJECT_RISK  the tracked occurrence — links Project + Risk
              (likelihood, impact, rating, strategy, plan, owner, practice lead,
               status, lifecycle phase, dates, SLA, closure fields, traceability)

HISTORY       the existing audit log, re-keyed to PROJECT_RISK
```

`PROJECT_RISK` **is** the junction — no separate link table is needed.

---

## 2. Decisions (locked during grilling)

1. **Do the full split now** — the app is pre-production and the data is
   re-seedable, so this is the cheapest moment; ship immediately when done.
2. **Shared catalog** — each risk concept is stored once and reused across
   projects. (ADR 0001)
3. **Build automatically, then clean up by hand** — auto-collapse by normalized
   description+category, then manual merge/rename with a short name.
4. **Active register** = Project is Active AND Project Risk is not
   Resolved/Closed/Dismissed.
5. **Project lifecycle** = explicit close (blocked while risks are unresolved),
   explicit reopen, no adding to a Closed project. (ADR 0002)
6. **Field placement** = split into `RISK` / `PROJECT_RISK`; no new tables beyond
   re-keying the existing audit log.
7. **User-facing identity** = the catalog's short name; the per-project code is
   hidden behind the scenes.

---

## 3. Field mapping (current → new)

**`projects` → `PROJECT`** (nearly 1:1): `id`→`project_id`, `name`→`project_name`,
`customer`→`customer_name`, `project_type_id`/`department_id`→`project_type`/`department`,
`start_date`/`end_date`, `status`→`project_status`. Keep `project_code` and `pm_user_id`.

**`risks` → splits:**

| → RISK (catalog) | → PROJECT_RISK (instance) |
|---|---|
| short name *(new)* | project_id (FK) + risk_id (FK) |
| description | likelihood, impact, risk_rating |
| category, subcategory | response_strategy, response_plan |
| risk_source | owner, practice_lead |
| embedding | status, lifecycle_phase |
| | risk_start_date, risk_end_date |
| | sla_deadline, sla_acknowledged, sla_manual_override |
| | accepted/resolved/closed_date, root_cause, what_worked, resolution_category |
| | source (Historical/Custom/Kickoff), llm_analysis, raised_by |
| | source_file_name/url/source_risk_id (traceability lives here because the catalog is shared) |

**`risk_audit_log` → `HISTORY`** — re-key `risk_id` → `project_risk_id`.

---

## 4. Migration plan (phases, NOT executed)

- **Phase 0 — Backup** (`pg_dump -Fc`, verify restore).
- **Phase 1 — Schema (non-breaking)** — add `RISK` + `PROJECT_RISK`; keep `risks`.
- **Phase 2 — Backfill catalog** — dedupe by normalized description+category; assign short names.
- **Phase 3 — Backfill instances** — `PROJECT_RISK` rows from current `risks`, linked to catalog.
- **Phase 4 — Backend/API rewrite** — models, schemas, services, suggestions, importers, auth, endpoints.
- **Phase 5 — Frontend rewrite** — types, Add Risk, Active Register, dashboards, detail page, close/reopen controls.
- **Phase 6 — Re-key history** — audit log → instance; move embedding to catalog.
- **Phase 7 — Testing** — update all tests; add backfill/register/close-reopen tests.
- **Phase 8 — Validation** — counts, register contents vs rule matrix, E2E.
- **Phase 9 — Drop `risks`** after a soak period.

---

## 5. Remaining implementation details (to specify at build time)

- Exact ID scheme (numeric catalog `risk_id` + numeric instance `project_risk_id`; catalog name shown to users).
- `risk_name` derivation for the ~272 historical risks (auto-truncate description, then manual cleanup).
- Citation format under the shared catalog (reference the catalog name + the specific historical source file).
- Whether `Suggested` (not-yet-accepted) shows in the Active register (leaning: exclude; it's pending, not live).

---

## 6. Status

**DESIGN DECIDED — NOT IMPLEMENTED.** Awaiting explicit approval to begin
implementation.
