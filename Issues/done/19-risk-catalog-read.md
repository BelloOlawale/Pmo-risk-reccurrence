# 19: Risk catalog read — list and view shared risks

- **Type:** AFK
- **Status:** DONE
- **Spec:** PRD #17

## Parent

#17 — Risk Catalog + Project Risk instance — data model rebuild

## What to build

Expose the shared Risk catalog for reading. Add the catalog ORM model and read
schema, endpoints to list all catalog risks and fetch a single risk, and a minimal
frontend list so users can browse the library. Risks show their short name, category,
and description.

## Acceptance criteria

- [ ] Catalog risks can be listed via API (short name, category, description)
- [ ] A single catalog risk can be fetched by id
- [ ] Frontend shows the catalog list
- [ ] Tests cover list and get

## Blocked by

- #18 (migration + backfill)
