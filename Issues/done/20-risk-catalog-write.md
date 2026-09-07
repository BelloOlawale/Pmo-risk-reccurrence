# 20: Risk catalog write — create, name, rename/merge

- **Type:** AFK
- **Status:** DONE
- **Spec:** PRD #17; ADR 0001 (shared catalog)

## Parent

#17 — Risk Catalog + Project Risk instance — data model rebuild

## What to build

Let users add to and clean up the Risk catalog. Add the ability to create a catalog
risk with a short name, rename a risk, and manually merge two near-duplicate catalog
entries into one (re-pointing any Project Risks to the surviving entry). Wire this
through the API and a minimal frontend form/action.

## Acceptance criteria

- [x] Create a catalog risk via API (name, description, category, subcategory, risk source)
- [x] Rename a catalog risk (short name)
- [x] Merge two catalog risks into one, re-pointing their Project Risks
- [x] Frontend supports create and rename/merge
- [x] Tests cover create, rename, and merge

## Blocked by

- #19 (catalog read)
