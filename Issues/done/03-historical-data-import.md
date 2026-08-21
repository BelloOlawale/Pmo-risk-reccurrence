# 03: Historical Data Import (Seed the Knowledge Base)

- **Type:** AFK
- **Spec:** SPEC.md §8
- **Blocked by:** #01
- **Port from:** `../risk_reccurrence_predictor/src/import_pipeline/`

## What to build

Port the tested import pipeline into the new app and seed Postgres from the existing registers.

1. Port `excel_parser.py` (detect headers, extract rows, skip OLE2/.xls gracefully) and `field_mapper.py` (map the ~9 known Excel schemas → canonical fields; H/M/L ↔ High/Medium/Low; RiskScore → rating).
2. Write `importer.py` that walks `Project/<Department>/<ProjectType>/<file>.xlsx`, and for each file:
   - `get_or_create` Department and ProjectType from the folder path,
   - create a Project (one per unique department+type engagement),
   - insert risks with `source="Historical"`, `status="Open"` (or "Closed" for historical?), and source traceability (`source_file_name`, `source_risk_id`).
3. Provide a CLI/script entry (`python -m riskapp.import_pipeline`) and mark the result counts.

**Note:** historical rows map Low/Med/High straight through as provisional. **Decision recorded: imported risks start `Closed`** (they are historical, not active) with `source="Historical"`.

## Decisions (recorded 2026-08-21)

1. **Status = `Closed`.** Historical rows are past learnings, not active risks; they never trigger SLA.
2. **`risk_rating` is always the 3×3 matrix result** (SPEC §4), computed from normalized likelihood × impact — never copied from an explicit "Risk Level"/"Risk Score" column.
3. **Missing likelihood/impact default to `Medium`** (legacy provisional default).
4. **Historical owner names are not persisted** — `Risk` has only an `owner_user_id` FK, no free-text owner. The names (e.g. "Punuka", "WACL") remain available in the pipeline's `MappedRisk.risk_owner` for a future user-matching step.
5. **Dedup key** = (project, `source_file_name`, `source_risk_id`). The TNL schema has no ID column, so those rows fall back to `description` as the dedup key (12 rows across 2 files).

## Acceptance criteria

- [x] 30 parsed files → 273 risks / 21 projects imported into Postgres (verified on local dev DB: 8 departments, 16 project types, 21 projects, 273 risks)
- [x] Departments and ProjectTypes reconstructed from folder hierarchy (data-driven lookup)
- [x] Each historical risk has `source_file_name`, `source_risk_id`, `project_id` (261/273 carry a source ID; TNL rows have none in the source)
- [x] Ratings mapped to Low/Medium/High; `risk_rating` computed via the 3×3 matrix
- [x] OLE2 (.xls) and corrupt files skipped without crashing (logged) — 4 files skipped
- [x] Idempotent: re-running doesn't duplicate (dedup by source_file + source_risk_id; verified 0 re-imports on second run)
- [x] Tests cover parser + field mapper + importer (ported + adapted; 151 total tests)

