# 22: Project risks read path — join through Project Risk

- **Type:** AFK
- **Status:** DONE
- **Spec:** PRD #17

## Parent

#17 — Risk Catalog + Project Risk instance — data model rebuild

## What to build

Route project-level risk reads through the new Project Risk entity. The project risks
list and a project's risk count should join Project Risk to the catalog Risk, so the
project dashboard lists the Project Risks (with catalog short names) on that project.
Update types and the project dashboard accordingly.

## Acceptance criteria

- [x] Project risks list returns the Project Risks on a project via the join
- [x] Project risk count reflects Project Risk rows
- [x] Frontend project dashboard shows the risks (with short names)
- [x] Tests cover the project risks list and count

## Blocked by

- #21 (attach risk to project)
