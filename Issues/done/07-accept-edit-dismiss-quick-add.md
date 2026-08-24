# 07: Accept / Edit / Dismiss Suggestions + Quick Add

- **Type:** AFK
- **Spec:** SPEC.md §5 (Suggested → Open/Dismissed), §8
- **Blocked by:** #01, #06

## What to build

The suggestion lifecycle and the fast-capture path.

1. `POST /api/risks/{id}/accept` — transition `Suggested → Open`, assign owner (default PM), assign SLA deadline (#02), notify.
2. `POST /api/risks/{id}/dismiss` — transition `Suggested → Dismissed`, record in `suggestion_dismissals` (project_id + historical_risk_key) so it never reappears.
3. `POST /api/risks` already supports manual entry; add a **Quick Add** payload variant (description + likelihood + impact only; category/owner optional; rating auto-computed; `source="Kickoff"`).
4. Filter dismissed risks out of subsequent suggestion runs for the same project.

## Acceptance criteria

- [ ] Accept transitions `Suggested → Open` with owner + SLA deadline
- [ ] Dismiss transitions `Suggested → Dismissed` and is tracked per project
- [ ] Dismissed risks never reappear for the same project
- [ ] Quick Add creates a risk in seconds with rating auto-computed
- [ ] Cross-project isolation: dismissing for project A doesn't affect project B
- [ ] Unit tests for accept/dismiss/quick-add and dismissal filtering
