# 08: Celery + Scheduler — SLA Monitor, Start-Date Email, Weekly Summary

- **Type:** AFK
- **Spec:** SPEC.md §6, §12
- **Blocked by:** #01, #02

## What to build

Replace Power Automate with Celery + Redis + Beat.

1. Celery app + worker configuration (broker = Redis), Beat schedule.
2. **Hourly SLA monitor task:**
   - query risks `status IN (Open, In Progress)`,
   - `evaluate_sla(...)` per risk (`domain/sla.py`),
   - `warning` → queue owner reminder; `breach` → transition to `Escalated` (#01) + notify (#09).
3. **Daily start-date task:** email the owner for risks where `risk_start_date == today`.
4. **Weekly summary task:** Monday 8 AM, aggregate counts by status/rating, resolution rate, SLA compliance → email PM + PMO Lead.
5. Local dev: Redis + worker + beat runnable via a documented command.

## Acceptance criteria

- [ ] Hourly task transitions an idle, breached risk to `Escalated`
- [ ] Warning reminder sent inside the warning window (4h High / 12h Medium / 24h Low)
- [ ] Activity (edit/status change/acknowledge) → task skips the risk permanently
- [ ] Start-date email fires on `risk_start_date`
- [ ] Weekly summary aggregates correctly (counts, resolution rate, SLA compliance)
- [ ] Beat schedule configured for hourly + daily + weekly (Mon 8 AM)
- [ ] Task logic unit-tested (mock the DB/notifier)
