# 21: Attach a risk to a project (core association)

- **Type:** AFK
- **Status:** DONE
- **Spec:** PRD #17; ADR 0001 (shared catalog)

## Parent

#17 — Risk Catalog + Project Risk instance — data model rebuild

## What to build

Implement the core write path: adding a risk to a project now creates (or reuses) a
catalog **Risk** and creates a **Project Risk** linking it to the project. A brand-new
risk creates both; attaching an existing catalog risk creates only the link. Update
the add-risk request/response shapes, the service layer, the add-risk endpoint, and
the frontend "Add risk" flow. New projects continue to default to Active.

## Acceptance criteria

- [x] Adding a brand-new risk creates a catalog Risk and a Project Risk on the project
- [x] Attaching an existing catalog risk creates only the Project Risk link
- [x] New projects default to Active
- [x] Frontend "Add risk" flow performs the association correctly
- [x] Tests cover new-risk and existing-risk association

## Blocked by

- #20 (catalog write)
