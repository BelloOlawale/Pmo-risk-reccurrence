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

**Note:** historical rows map Low/Med/High straight through as provisional. Decide and record whether imported risks start `Open` or `Closed` (recommend `Closed` — they are historical, not active).

## Acceptance criteria

- [ ] 30 parsed files → ~273 risks / ~21 projects imported into Postgres
- [ ] Departments and ProjectTypes reconstructed from folder hierarchy (data-driven lookup)
- [ ] Each historical risk has `source_file_name`, `source_risk_id`, `project_id`
- [ ] Ratings mapped to Low/Medium/High; `risk_rating` computed via the 3×3 matrix
- [ ] OLE2 (.xls) and corrupt files skipped without crashing (logged)
- [ ] Idempotent: re-running doesn't duplicate (dedup by source_file + source_risk_id)
- [ ] Tests cover parser + field mapper + importer (ported + adapted)
