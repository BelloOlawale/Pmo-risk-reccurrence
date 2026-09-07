# PMO Risk Recurrence Predictor

Domain model for the Wragby PMO risk-management application. This file is a
glossary of the domain's core terms — it is intentionally free of implementation
details (tables, columns, code). See `docs/adr/` for decisions.

## Language

**Risk**:
A reusable, project-agnostic description of a potential problem (e.g. "vendor
onboarding paperwork outstanding"). Stored once and shared across projects.
Identified by a short name and a longer description.
_Avoid_: risk register entry, issue

**Project Risk**:
A specific occurrence of a Risk on a specific Project — the row that is actively
tracked, carrying that project's likelihood, impact, rating, response strategy,
owner, status, and dates.
_Avoid_: risk (when meaning the tracked occurrence)

**Project**:
A client engagement being delivered (e.g. "NHIA AWS Migration").
_Avoid_: account, engagement

**Active Risk Register**:
The derived list of risks currently needing attention: a Project Risk on an
Active Project whose status is not yet Resolved, Closed, or Dismissed.
_Avoid_: open risks list, live register

**Project Status**:
The lifecycle state of a Project: Active (being delivered) or Closed (formally
finished). A project may only be Closed once all its Project Risks are Resolved
or Closed; returning to Active is a separate, explicit reopen action.
