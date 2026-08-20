# 05: Semantic Embeddings + pgvector

- **Type:** AFK
- **Spec:** SPEC.md §7
- **Blocked by:** #03 (needs seeded data), #04
- **Port from:** `../risk_reccurrence_predictor/src/llm/vector_store.py` (FAISS → pgvector)

## What to build

Replace the old FAISS+Blob index with pgvector in Postgres.

1. Migration: add `embedding vector(1536)` (or a separate `risk_embeddings` table) + an ivfflat/HNSW index.
2. Embedding client: `text-embedding-3-small` via Azure OpenAI, `embed_text()` → 1536-dim vector.
3. Seed step: embed every historical risk's `description` (and category) and store the vector.
4. `semantic_search(query_vector, limit=20, threshold=0.75)` using pgvector cosine distance.

## Acceptance criteria

- [ ] Migration creates the vector column + index
- [ ] All historical risks have embeddings persisted
- [ ] `semantic_search` returns ranked results by cosine similarity
- [ ] Threshold filtering (≥ 0.75) applied
- [ ] Tests with a mocked embedding client (deterministic vectors)
