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

- [x] Migration creates the vector column + index (`9f8e7d6c5b4a`: `embedding vector(1536)` + HNSW cosine index)
- [x] All historical risks have embeddings persisted (`embed_all_risks`, idempotent)
- [x] `semantic_search` returns ranked results by cosine similarity
- [x] Threshold filtering (≥ 0.75) applied
- [x] Tests with a mocked embedding client (deterministic vectors) — 25 new tests

## Decisions (recorded 2026-08-21)

1. **Storage** — single nullable `risks.embedding` column typed `vector(1536)` (pgvector). The `Vector` type is SQLite-compatible in the ORM, so the test suite runs against in-memory SQLite while production uses real pgvector.
2. **Search** — `semantic_search` uses the **native pgvector `<=>` cosine-distance operator** (HNSW-accelerated) on PostgreSQL, filtering and ranking entirely in the database. The pure `domain/similarity.py` path is retained only as a fallback for non-Postgres dialects (SQLite dev), never in production.
3. **Migration is Postgres-only** — `CREATE EXTENSION vector` cannot run on the local SQLite dev DB; the model column is created there via `Base.metadata.create_all` in tests. Run `alembic upgrade head` against Postgres/pgvector in deployed environments.
4. **Embedding text** — description + category/subcategory + likelihood/impact/rating. Department/ProjectType are already covered by the exact-match leg of retrieval (issue #04), so they're not re-encoded.
5. **Client** — `AzureOpenAIEmbeddings` (openai SDK, `text-embedding-3-small`, 1536 dims) behind an `EmbeddingProvider` Protocol so tests inject deterministic vectors. Seed CLI: `python -m riskapp.embed`.
