# 26: Suggestion acceptance through the shared catalog

- **Type:** AFK
- **Status:** DONE
- **Spec:** PRD #17; ADR 0001 (shared catalog)

## Parent

#17 — Risk Catalog + Project Risk instance — data model rebuild

## What to build

Change suggestion acceptance so that accepting a recurring risk creates a Project
Risk linked to a shared catalog Risk (reusing the existing entry when one exists),
instead of copying a historical row. Keep dismissal working so a dismissed or accepted
suggestion never reappears for that project.

## Acceptance criteria

- [x] Accepting a suggestion creates a Project Risk linked to a shared catalog Risk
- [x] The catalog entry is reused, not duplicated
- [x] Dismissal still prevents re-suggestion
- [x] Tests cover accept (new and reused catalog entry) and dismiss

## Blocked by

- #21 (attach risk to project)
