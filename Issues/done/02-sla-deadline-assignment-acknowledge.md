# 02: SLA Deadline Assignment + Manual Override

- **Type:** AFK
- **Spec:** SPEC.md §6
- **Blocked by:** #01 (done)

## What to build

Wire SLA deadlines into the risk lifecycle, with defaults by rating and a manual override.

Defaults (via `domain/sla.py`):
- High = 24 hours, Medium = 48 hours, Low = 5 days (120 hours)

1. On risk creation, compute `sla_deadline = created_at + sla_hours(rating)`.
2. On `risk_rating` change (re-score), recompute the deadline — **unless** the deadline is manually overridden.
3. **Manual override:** a PM / PMO Lead sets a custom `sla_deadline`; the system sets `sla_manual_override = True`. While overridden, rating changes leave the deadline untouched.
4. **Reset:** clearing the override reverts to the auto-computed deadline.
5. Expose `sla_deadline` and `sla_manual_override` in `RiskRead`.

**Note:** role enforcement (PM / PMO Lead only for override) is wired in #10 (RBAC). The override fields are functional now; authorization is added there.

## Acceptance criteria

- [x] Creating a High risk sets `sla_deadline = created_at + 24h`
- [x] Medium → +48h; Low → +120h
- [x] Re-scoring (rating change) recomputes the deadline
- [x] Setting a custom `sla_deadline` sets `sla_manual_override = True`
- [x] While overridden, rating changes do NOT recompute the deadline
- [x] Reset clears `sla_manual_override` and recomputes from the rating
- [x] `sla_deadline` + `sla_manual_override` returned by `GET /api/risks/{id}`
- [x] Unit tests cover defaults, override, block-on-rescore, and reset
