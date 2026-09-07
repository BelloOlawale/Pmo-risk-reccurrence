# 23: Active Risk Register — backend-derived

- **Type:** AFK
- **Status:** DONE
- **Spec:** PRD #17; CONTEXT.md (Active Risk Register)

## Parent

#17 — Risk Catalog + Project Risk instance — data model rebuild

## What to build

Derive the Active Risk Register from Projects joined to their Project Risks and
catalog Risks. The rule: a Project Risk appears when its Project is Active AND its
status is not Resolved, Closed, or Dismissed. Expose this as a backend-derived read
and update the register page to consume it (replacing client-side filtering).

## Acceptance criteria

- [x] Active register endpoint returns only Active projects' non-finished risks
- [x] Resolved, Closed, and Dismissed risks are excluded
- [x] Frontend register page consumes the derived register
- [x] Tests cover the derivation rule (including the four project/risk combinations)

## Blocked by

- #22 (project risks read path)
