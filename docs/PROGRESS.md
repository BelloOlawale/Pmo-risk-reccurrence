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
