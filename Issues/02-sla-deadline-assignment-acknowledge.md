# 02: SLA Deadline Assignment on Risk Creation

- **Type:** AFK
- **Spec:** SPEC.md §6
- **Blocked by:** #01

## What to build

Wire SLA deadlines into the risk lifecycle.

1. On risk creation, compute `sla_deadline = created_at + sla_hours(rating)` via `domain/sla.py`.
2. On `risk_rating` change (re-score), recompute the deadline from the new rating.
3. Expose `sla_deadline` in `RiskRead`.
4. Ensure `RiskRead` includes the `risk_start_date` / `risk_end_date` fields (added to spec) and the new `status` field is always present.

## Acceptance criteria

- [ ] Creating a High risk sets `sla_deadline = created_at + 24h`
- [ ] Creating a Medium risk sets `+ 48h`; Low sets `+ 120h`
- [ ] Re-scoring (rating change) recomputes the deadline
- [ ] `sla_deadline` returned by `GET /api/risks/{id}`
- [ ] `risk_start_date` / `risk_end_date` are persisted and returned
