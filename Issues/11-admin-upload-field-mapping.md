# 11: Admin Bulk Import (Upload + Field Mapping)

- **Type:** AFK
- **Spec:** SPEC.md §8
- **Blocked by:** #03, #10 (admin role)

## What to build

The ongoing-import path for new Excel registers.

1. `POST /api/imports` — admin uploads `.xlsx`/`.csv`; server parses (reuse #03 parser) and returns detected headers + a suggested field mapping.
2. `POST /api/imports/{id}/confirm` — client sends the mapping; server imports valid rows, returns a report (imported / skipped with per-row errors).
3. Store `source_file_name` on Blob Storage and set `source_file_url` for citation traceability.
4. Restricted to PMO Lead / System Admin.

## Acceptance criteria

- [ ] Upload returns detected columns + proposed mapping
- [ ] Confirm imports valid rows into the target project's register
- [ ] Invalid rows reported with row number + field name, downloadable
- [ ] `risk_rating` computed for each imported row (3×3 matrix)
- [ ] Uploaded file stored in Blob; `source_file_url` set
- [ ] Non-admin receives 403
