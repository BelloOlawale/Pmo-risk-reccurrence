# 28: Final cut-over — history re-key and drop the old table

- **Type:** AFK
- **Status:** DONE
- **Spec:** PRD #17

## Parent

#17 — Risk Catalog + Project Risk instance — data model rebuild

## What to build

Finish the migration. Re-key the append-only audit history from the old risk record to
the Project Risk instance, move the semantic embedding onto the catalog Risk, and — in
a separate, later migration — drop the obsolete risk table after a soak period. Verify
no data was lost across the whole transition.

## Acceptance criteria

- [x] Audit history is keyed to Project Risk
- [x] Embedding lives on the catalog Risk
- [x] The obsolete table is dropped in a separate migration
- [x] Full test suite is green
- [x] Verification confirms relationship/count parity and no data loss

## Blocked by

- #22 (project risks read path)
- #25 (project reopen)
- #26 (suggestion acceptance)
- #27 (bulk import)
