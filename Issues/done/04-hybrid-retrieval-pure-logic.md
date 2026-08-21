# 04: Hybrid Retrieval — Merge / Dedupe / Rank (Pure Logic)

- **Type:** AFK
- **Spec:** SPEC.md §7
- **Blocked by:** None (pure logic — can start now)

## What to build

`domain/retrieval.py` — the deterministic candidate-merge logic for the suggestion engine, with no I/O.

1. Define candidate types:
   - `ExactMatch` (matched on Department + ProjectType),
   - `KeywordMatch` (matched category/subcategory/description tokens, with match count),
   - `SemanticMatch` (embedding similarity score 0–1).
2. `merge_candidates(exact, keyword, semantic, *, semantic_threshold=0.75)`:
   - Dedupe by a stable key (source_file + source_risk_id, falling back to description).
   - Rank: exact always included first; keyword ranked by match count; semantic above threshold ranked by similarity.
   - Return a single ordered list with match provenance.
3. Deterministic tie-breaking (e.g., by risk id).

## Acceptance criteria

- [x] Exact matches always included regardless of keyword/semantic score
- [x] Duplicate risks (same key across the three sets) appear once
- [x] Semantic matches below the threshold are excluded
- [x] Ordering is stable and deterministic (exact → keyword → semantic)
- [x] Unit tests cover merge, dedup, threshold, and tie-breaking (15 new tests)
