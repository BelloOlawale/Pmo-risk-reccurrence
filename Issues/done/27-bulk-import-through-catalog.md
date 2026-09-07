# 27: Bulk import through the shared catalog

- **Type:** AFK
- **Status:** DONE
- **Spec:** PRD #17; ADR 0001 (shared catalog)

## Parent

#17 — Risk Catalog + Project Risk instance — data model rebuild

## What to build

Route the historical-register import (and the admin upload import) through the new
entities: each imported source risk becomes a Project Risk linked to a deduplicated
catalog Risk. Source-file traceability (file, URL, source risk id) lands on the
Project Risk. The import stays idempotent — re-running produces no duplicate catalog
entries.

## Acceptance criteria

- [x] Imported source risks become Project Risks linked to deduplicated catalog entries
- [x] Re-running the import is idempotent (no duplicate catalog entries)
- [x] Source traceability is recorded on the Project Risk
- [x] Tests cover import, dedup, and idempotency

## Blocked by

- #21 (attach risk to project)
