# 09: Notifications — Email + In-App

- **Type:** AFK
- **Spec:** SPEC.md §9
- **Blocked by:** #01

## What to build

The notification layer (email + in-app), replacing Power Automate mail.

1. **Email client** for Azure Communication Services (`send_email(to, cc, subject, body_html)`), with a stub for tests.
2. **In-app notifications:** a `Notification` model (recipient_user_id, type, title, body, risk_id, read, created_at) + endpoints to list and mark-read.
3. **Notification matrix** wiring (a `notify(...)` service used by #07, #08):
   - owner assignment → owner + PM + PMO Lead + Practice Lead (CC)
   - SLA warning → owner
   - breach/escalation → owner + PM + PMO Lead
   - risk start date → owner
   - weekly summary → PM + PMO Lead
4. **Email deep links:** email action buttons point to the React app routes (e.g. `/risks/{id}`).

## Acceptance criteria

- [ ] Emails sent via Azure Communication Services (stubbed in tests)
- [ ] In-app notifications stored, listable, and markable read
- [ ] Each matrix event produces the correct recipients
- [ ] Email contains a deep link to the risk in the app
- [ ] Unit tests cover the recipient matrix and deep-link generation
