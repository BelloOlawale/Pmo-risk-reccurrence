# 14: End-to-End Validation + Handoff Docs (HITL)

- **Type:** HITL
- **Spec:** SPEC.md §13
- **Blocked by:** #13

## What to build

Validate the full loop with real data and real users, then document.

1. End-to-end scenario: create project → suggestions → accept/dismiss → Quick Add → owner notification → hourly SLA check → escalate → de-escalate → materialize (Event) → resolve → close → knowledge base feed.
2. Seed historical data (#03) and confirm suggestions + citations are grounded.
3. Real email delivery test (owner, PM, PMO Lead, Practice Lead).
4. Handoff docs: runbook, architecture summary, admin guide, and a `CONTEXT.md`/`AGENTS.md` for future contributors.

## Acceptance criteria

- [ ] Full lifecycle (create → suggest → … → close) passes end-to-end
- [ ] Suggestions are grounded with correct citations on real data
- [ ] Emails delivered to real addresses; deep links open the app
- [ ] SLA monitor escalates a real idle risk
- [ ] Weekly summary email received Monday 8 AM
- [ ] Runbook + admin guide + architecture docs written
