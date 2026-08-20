# 01: Status Transitions + Append-Only Audit Trail

- **Type:** AFK
- **Spec:** SPEC.md §3 (audit log), §5 (lifecycle)
- **Blocked by:** #00 (done)

## What to build

Make the service layer enforce the status state machine and record every mutation.

1. A single `transition_risk(db, risk, target, actor)` service that:
   - Validates the transition via `domain/status.py` `can_transition` (reject with 409 otherwise).
   - Writes a `RiskAuditLog` row (`action="status_change"`, old/new values, snapshots).
2. A single `update_risk(db, risk, payload, actor)` service that:
   - Diffs incoming fields against current values.
   - Writes one `RiskAuditLog` row per changed field (`action="field_edit"`).
   - Computes `risk_rating` whenever `likelihood` or `impact` changes.
3. An `acknowledge_risk` action that sets `sla_acknowledged=True` and logs `action="acknowledge"`.
4. API endpoints: `PATCH /api/risks/{id}` (edit + optional transition), `POST /api/risks/{id}/acknowledge`.

No manual override can skip a status without an audit entry — the audit row and the mutation happen in the same transaction.

## Acceptance criteria

- [ ] Valid transitions (per `test_status.py`) succeed; invalid ones return 409
- [ ] Every status change writes exactly one `RiskAuditLog` row (old status, new status, actor, timestamp)
- [ ] Every field edit writes an audit row per changed field
- [ ] Editing `likelihood`/`impact` recomputes `risk_rating` and logs the change
- [ ] `acknowledge` sets `sla_acknowledged=True` and logs `action="acknowledge"`
- [ ] Audit rows are append-only (no update/delete path in the service)
- [ ] Unit tests cover the diff, transition, and acknowledge paths
