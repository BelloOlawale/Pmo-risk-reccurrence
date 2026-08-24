# 10: RBAC + Entra ID SSO

- **Type:** AFK
- **Spec:** SPEC.md §10
- **Blocked by:** None (independent)

## What to build

Authentication and row-level authorization.

1. Entra ID OIDC login (FastAPI dependency decoding the access token; groups in claims).
2. Role resolution → one of: System Admin, PMO Lead, Project Manager (from Entra groups). Risk Owner / Practice Lead are record-level assignments, not roles.
3. Row-level scoping in the API:
   - PM sees/edits only their own projects' risks,
   - Risk Owner sees/edits their assigned risks,
   - PMO Lead / System Admin see everything.
4. Project creation limited to PM / System Admin; de-escalation limited to PM / PMO Lead.

## Acceptance criteria

- [ ] Endpoints require a valid Entra token (401 otherwise)
- [ ] Roles resolved from Entra group claims
- [ ] A PM cannot read/edit another PM's project risks
- [ ] A Risk Owner can edit only their assigned risks
- [ ] PMO Lead / Admin bypass scoping (see all)
- [ ] De-escalation restricted to PM / PMO Lead
- [ ] Tests with a fake auth dependency (no live Entra needed)
