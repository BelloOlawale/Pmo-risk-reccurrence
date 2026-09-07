# 17: Risk Catalog + Project Risk instance — data model rebuild

- **Type:** AFK
- **Spec:** CONTEXT.md (glossary), docs/adr/0001 (shared catalog), docs/adr/0002 (close/reopen)
- **Blocked by:** None — can start immediately
- **Status:** ready-for-agent
- **Supersedes:** Issues/15-risk-project-normalization-migration.md, Issues/15-risk-project-normalization-uml.md

---

## Problem Statement

Today a risk can only exist as a child of a single project: the `risks` table
carries a required `project_id` and mixes together two different ideas — "what the
risk is" and "how it is being tracked on this project." As a result:

- There is no reusable library of known risks, so the "recurrence" feature fakes it
  by copying historical rows instead of referencing a shared catalog.
- A risk cannot be understood or managed independently of the project it happens to
  sit under.
- The Active Risk Register ignores project status entirely, so a closed project can
  still surface its risks as "active."

The user needs the system to treat a **Risk** (a reusable, project-agnostic
concept) separately from a **Project Risk** (a specific occurrence of that Risk on a
specific Project), so that risks are shared, suggestions are first-class, and the
Active Risk Register reflects a project's real lifecycle.

## Solution

Split the single risk record into two linked entities:

- **RISK** — a shared, deduplicated catalog of risk concepts, each with a short name,
  description, category/subcategory, and (for semantic search) an embedding.
- **PROJECT_RISK** — the tracked occurrence, linking a Project to a Risk and carrying
  that project's likelihood, impact, rating, response strategy/plan, owner, status,
  lifecycle phase, dates, SLA, closure details, and source traceability.

A Project Risk is the junction between a Project and a Risk, so no separate link
table is needed. Projects gain a real lifecycle: a Project Manager explicitly closes
a project (blocked while any of its Project Risks are unresolved/unclosed) and
explicitly reopens it; risks cannot be added to a closed project. The Active Risk
Register is derived as: Project is Active AND its Project Risk is not Resolved,
Closed, or Dismissed.

## User Stories

### Risk catalog

1. As a Project Manager, I want to create a new Risk in the catalog, so that the same risk concept can be reused across projects instead of retyped.
2. As a Project Manager, I want to see a list of catalog Risks with their short names, categories, and descriptions, so that I can find a known risk to attach to my project.
3. As a Project Manager, I want to attach an existing catalog Risk to my Project, so that I start tracking it without duplicating the risk definition.
4. As a PMO Lead, I want to see one catalog entry per risk concept rather than near-duplicate copies, so that the risk library is clean and searchable.
5. As a PMO Lead, I want to rename or merge catalog Risks, so that near-duplicates introduced during import can be cleaned up by hand.
6. As a PMO Lead, I want each catalog Risk to have a short human-readable name, so that risks are easy to reference in lists, filters, and citations.
7. As a Project Manager, I want my project's risks to display their catalog short name rather than a raw code, so that I can recognise what a risk is at a glance.

### Risk creation & association

8. As a Project Manager, I want to add a brand-new risk to my Project, so that I can capture a risk that doesn't exist in the catalog yet.
9. As a Project Manager, I want adding a risk to also create (or reuse) a catalog entry and link it to my Project, so that the catalog and my register stay consistent.
10. As a Project Manager, I want to accept a suggested recurring risk and have it create a Project Risk linked to the shared catalog entry, so that suggestions stop copying historical rows.
11. As a System Admin, I want to import historical registers so that each source risk becomes a Project Risk linked to a deduplicated catalog Risk, so that historical data feeds the shared catalog.
12. As a Project Manager, I want a new project to start as Active automatically, so that I can begin adding risks without an extra step.

### Active Risk Register

13. As a Project Manager, I want the Active Risk Register to show only risks on Active projects, so that closed projects no longer appear active.
14. As a Project Manager, I want a Project Risk to disappear from the Active Risk Register once it is Resolved or Closed, so that finished risks stop cluttering the live view.
15. As a Project Manager, I want dismissed suggestions to be excluded from the Active Risk Register, so that rejected risks never show as live.
16. As a PMO Lead, I want the Active Risk Register derived from Projects joined to their Project Risks and catalog Risks, so that it is always consistent with the underlying data.
17. As a Project Manager, I want each row in the Active Risk Register to show the catalog short name, project, status, rating, owner, and SLA, so that I can triage live risks efficiently.

### Project lifecycle

18. As a Project Manager, I want to close a project when its work is done, so that it is no longer treated as active.
19. As a Project Manager, I want closing a project to be blocked while any of its Project Risks are still unresolved or unclosed, so that I don't close a project with live risks.
20. As a Project Manager, I want a clear signal of which risks are still open when I try to close a project, so that I can resolve or close them first.
21. As a Project Manager, I want to reopen a closed project as an explicit, separate action, so that closing and reopening are deliberate.
22. As a Project Manager, I want to be prevented from adding a new risk to a closed project, so that a closed project can never end up with an open risk.
23. As a Project Manager, I want a reopened project to appear in the Active Risk Register again once it has active risks, so that reopening visibly restores the project.
24. As a Project Manager, I want resolving or closing all of a project's risks to never auto-close the project, so that project closure remains my explicit decision.
25. As a Project Manager, I want adding a risk to a project to never automatically reactivate a closed project, so that lifecycle state is only changed by explicit actions.

### Risk lifecycle & history

26. As a Project Manager, I want a Project Risk to move through its lifecycle (Suggested → Open → In Progress → Escalated → Materialized → Resolved → Closed), so that its status reflects how it is being managed.
27. As a Project Manager, I want the risk status to live on the Project Risk rather than the shared catalog Risk, so that the same catalog Risk can be in different states on different projects.
28. As a Project Manager, I want the risk's likelihood, impact, rating, response strategy, and plan to be per-project, so that each project tracks its own treatment of the same risk.
29. As a Project Manager, I want the audit history to record changes to a Project Risk over time, so that I can see who changed what and when.
30. As a PMO Lead, I want the audit history keyed to the Project Risk rather than the shared catalog entry, so that each project's handling of a risk is tracked separately.

### Portfolio & reporting

31. As a PMO Lead, I want the portfolio dashboards to aggregate by Project Risk and project status, so that closed projects and resolved risks don't skew the numbers.
32. As a PMO Lead, I want the weekly summary to reflect active risks only, so that reported resolution rates are accurate.
33. As a Project Manager, I want source-file traceability to live on the Project Risk, so that I can still see which register a risk originally came from even though the catalog is shared.

## Implementation Decisions

- **Two new entities, one junction.** Introduce a shared **Risk** catalog and a
  **Project Risk** instance. `Project Risk` is itself the junction (it holds both the
  project and the catalog-risk reference); no separate link table.
- **Shared catalog.** Each risk concept is stored once and reused across projects
  (ADR 0001). Per-source-file traceability therefore moves from the catalog down to
  the Project Risk instance.
- **Catalog identity is a short name.** The short human-readable name is the
  user-facing identifier; numeric identifiers (catalog id and instance id) remain
  behind the scenes.
- **Deduplication strategy.** Historical risks are auto-collapsed into catalog entries
  by normalized description + category, then manually merged/renamed with short names
  afterward.
- **Field placement.** Catalog: short name, description, category, subcategory,
  risk source, and embedding. Instance: likelihood, impact, rating, response
  strategy/plan, owner, practice lead, status, lifecycle phase, start/end dates, SLA
  fields, accepted/resolved/closed dates, closure fields, source, LLM analysis,
  raised-by, and source-file traceability.
- **Active Risk Register rule.** Derived as: Project is Active AND Project Risk status
  is not Resolved, Closed, or Dismissed. Prefer a backend-derived view/endpoint rather
  than client-side filtering.
- **Project lifecycle.** Explicit close (blocked while any Project Risk is unresolved
  or unclosed) and explicit reopen (ADR 0002). Risks cannot be added to a Closed
  project; resolving risks never auto-closes a project; adding risks never auto-reopens
  one.
- **Risk status machine unchanged.** The existing lifecycle
  (`Suggested → Open → In Progress → Escalated → Event → Resolved → Closed`, plus
  `Dismissed`) moves onto the Project Risk entity; the catalog Risk has no status.
- **History re-keyed.** The existing append-only audit log is re-pointed from the old
  risk record to the Project Risk instance.
- **Embedding moves to the catalog.** Semantic search runs over the shared library, so
  the vector column lives on the Risk entity.
- **API shape.** Risk creation accepts an optional project to associate with (creating
  the Risk and its Project Risk link together); a new endpoint (or project patch) is
  added for close and reopen; the Active Risk Register is exposed as a derived read.
  Existing project/risk list endpoints join through the Project Risk entity.
- **Migration is two-phase and reversible.** First add the new entities and backfill
  from existing data while the old column still exists; later, after the application
  has cut over and soaked, drop the obsolete structure in a separate migration.
- **IDs preserved.** Existing project and risk identifiers are carried through the
  backfill unchanged; no resequencing.

## Testing Decisions

- **Test external behavior, not internals.** Assert on API responses and observable
  outcomes (what is shown/blocked/allowed), not on ORM internals or query shape.
- **Primary seam: the HTTP API.** Feature behavior is tested by driving the `/api`
  endpoints through the FastAPI test client and asserting on the responses: create a
  project, create/attach a risk, read the active register, close/reopen a project,
  resolve a risk.
- **Secondary seam: the data migration.** One dedicated test runs the migration
  against a seeded database and asserts (a) every existing project↔risk pairing is
  preserved as a Project Risk row and (b) the catalog was deduplicated to the expected
  number of entries. This is the only seam that cannot be exercised through the API.
- **Modules tested.** Risk catalog and Project Risk CRUD, the Active Risk Register
  derivation, project close/reopen guardrails, risk association (including suggestion
  acceptance and bulk import), and the audit history re-key.
- **Prior art.** Follow the existing API test style (FastAPI `TestClient`, seeded
  test database fixtures), the importer tests for the migration backfill, and the
  existing model/schema tests for entity round-trips.

## Out of Scope

- ML recurrence classification, PDF report export, and trend analysis (already
  deferred in the spec).
- Regenerating risk embeddings against Azure OpenAI (a separate human/Azure task).
- Jira / Azure DevOps / MS Project API connectors.
- Enum-like lookup tables for category, strategy, status, and phase — these remain
  plain strings, matching the existing pattern.
- Data Scientist / Information Security Manager roles and the full FRD treatment
  workflow (residual risk scoring, management sign-off).

## Further Notes

- This is the product requirement that supersedes the earlier junction-table analysis
  (Issues/15-*); the decided model is captured in Issues/16 and the glossary/ADRs.
- The application is pre-production and the historical data is re-seedable, so the
  migration can ship immediately once built and green — there is no live production
  data to preserve in place.
- The exact numeric identifier scheme and the initial short-name derivation for the
  ~272 historical risks are build-time details to be finalised during implementation,
  consistent with the decisions above.
