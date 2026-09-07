# 25: Project reopen — explicit, with add-risk guard

- **Type:** AFK
- **Status:** DONE
- **Spec:** PRD #17; ADR 0002 (close/reopen)

## Parent

#17 — Risk Catalog + Project Risk instance — data model rebuild

## What to build

Add an explicit reopen action that returns a Closed project to Active. Enforce the
related guardrails: risks cannot be added to a Closed project, resolving risks never
auto-closes a project, and adding risks never auto-reopens one. Wire the endpoint,
service, and a frontend reopen control.

## Acceptance criteria

- [x] Reopening returns a project to Active (explicit action)
- [x] Adding a risk to a Closed project is blocked
- [x] Resolving all risks does not auto-close the project
- [x] Adding a risk does not auto-reopen a Closed project
- [x] Tests cover reopen and the guardrails

## Blocked by

- #24 (project close)
