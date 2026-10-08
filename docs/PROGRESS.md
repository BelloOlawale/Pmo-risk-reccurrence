# Progress

## Issue #10 — RBAC / project ownership

- Project Managers and System Admins can create risk registers; creation records
  the authenticated creator as PM. The create request cannot specify another PM.
- Removed post-creation PM reassignment from the UI and endpoint. Existing
  registers retain their recorded PM; no creator history exists to reconstruct
  previous assignments.
- Project creation and ownership are covered by endpoint tests for bearer-token
  and dev identities, visibility, permissions, and reassignment rejection.
- Admins who create a register retain the ability to close their own register.

## Resolution workflow — Pending Resolution + shared risk history

- **Two-step resolution.** A Risk Owner's submission now sets status
  `Pending Resolution` instead of jumping straight to `Resolved`. The Project
  Manager (or PMO Lead / System Admin) accepts it (`Pending Resolution →
  Resolved`) or rejects it with a reason (`Pending Resolution → In Progress`).
  Once accepted the status is `Resolved`, so the accept/reject controls are no
  longer shown. Domain transitions, services, API, and the external owner page
  all reflect the new state.
- **Shared risk history.** Every Project Manager can now browse *all* closed
  registers via `GET /api/projects?scope=history` — including registers closed
  by other PMs and the imported historical corpus (which has no assigned PM).
  Read-only view helpers (`can_view_project` / `can_view_risk` /
  `can_view_issue`) grant read access to closed registers only; mutations stay
  row-scoped, so cross-register edits are still forbidden. Closed registers are
  rendered read-only for non-managers.
- Data migration `b4c5d6e7f8a9` moves owner-submitted, not-yet-accepted
  `Resolved` risks to `Pending Resolution`.
- Covered by `tests/test_resolution_workflow.py`, `tests/test_status.py`, and
  `tests/test_risk_history_access.py`.
