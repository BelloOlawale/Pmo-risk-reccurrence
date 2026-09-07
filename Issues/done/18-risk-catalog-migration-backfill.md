# 18: Migration + backfill — introduce Risk catalog and Project Risk

- **Type:** AFK
- **Status:** DONE
- **Spec:** PRD #17; ADR 0001 (shared catalog)

## Parent

#17 — Risk Catalog + Project Risk instance — data model rebuild

## What to build

Add the two new entities — a shared **Risk** catalog and a **Project Risk**
instance — as a non-breaking schema change. Write a migration that backfills both
from the existing risk table: deduplicate the catalog by normalized description +
category (one entry per risk concept), and create one Project Risk row per existing
project↔risk pairing. Keep the old table live so nothing breaks yet.

## Acceptance criteria

- [ ] Migration creates the Risk catalog and Project Risk tables (plus indexes)
- [ ] Backfill produces one catalog entry per unique risk concept (deduplicated)
- [ ] Every existing project↔risk pairing is preserved as a Project Risk row
- [ ] A migration test asserts relationship preservation and dedup counts
- [ ] Existing test suite still passes (old table untouched)

## Blocked by

None — can start immediately
