# 24: Project close — guarded

- **Type:** AFK
- **Status:** DONE
- **Spec:** PRD #17; ADR 0002 (close/reopen)

## Parent

#17 — Risk Catalog + Project Risk instance — data model rebuild

## What to build

Add an explicit close action for a Project. Closing is blocked while any Project Risk
on the project is not yet Resolved or Closed, with a clear signal of which risks are
still open. Wire the endpoint, service, and a frontend close control.

## Acceptance criteria

- [x] Closing a project with open risks is blocked with a clear list of the open risks
- [x] Closing succeeds once all Project Risks are Resolved or Closed
- [x] Frontend provides a close control
- [x] Tests cover blocked and successful close

## Blocked by

- #22 (project risks read path)
