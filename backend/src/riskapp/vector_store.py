"""Semantic search over the shared risk catalog's embeddings.

Embeddings live on ``risk_catalog.embedding`` (``vector(1536)``); the catalog is
the shared, deduplicated library, so semantic search runs over risk concepts
rather than per-project rows.

On PostgreSQL the search is executed entirely in the database with the native
pgvector cosine-distance operator (``<=>``). The pure
:mod:`riskapp.domain.similarity` path is kept as a fallback for non-Postgres
dialects (local SQLite development), where pgvector is unavailable.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.domain.retrieval import SemanticMatch
from riskapp.domain.similarity import rank_by_similarity
from riskapp.embeddings import EmbeddingProvider

DEFAULT_SEARCH_LIMIT = 20
DEFAULT_SIMILARITY_THRESHOLD = 0.75
DEFAULT_EMBED_BATCH_SIZE = 100

# pgvector cosine distance: similarity = 1 - (embedding <=> query)
_PGVECTOR_SQL = text(
    """
    SELECT * FROM (
        SELECT id,
               description,
               1 - (embedding <=> CAST(:query AS vector)) AS similarity
        FROM risk_catalog
        WHERE embedding IS NOT NULL
    ) ranked
    WHERE similarity >= :threshold
    ORDER BY similarity DESC, id ASC
    LIMIT :limit
    """
)


def build_embedding_text(catalog: models.RiskCatalog) -> str:
    """Build the text to embed for a catalog concept (description + category)."""
    category = catalog.category or ""
    subcategory = catalog.subcategory or ""
    category_text = f"{category} / {subcategory}" if subcategory else category

    parts = [catalog.description, f"Category: {category_text}" if category_text else ""]
    return " | ".join(part for part in parts if part)


def embed_all_risks(
    db: Session, client: EmbeddingProvider, *, batch_size: int = DEFAULT_EMBED_BATCH_SIZE
) -> int:
    """Embed every catalog entry without an embedding and persist the vectors.

    Idempotent: only entries whose ``embedding`` is NULL are processed. Returns
    the number of entries embedded.
    """
    catalogs = db.scalars(
        select(models.RiskCatalog)
        .where(models.RiskCatalog.embedding.is_(None))
        .order_by(models.RiskCatalog.id)
    ).all()

    if not catalogs:
        return 0

    texts = [build_embedding_text(catalog) for catalog in catalogs]
    vectors = _embed_in_batches(client, texts, batch_size)

    for catalog, vector in zip(catalogs, vectors, strict=True):
        catalog.embedding = vector

    db.commit()
    return len(catalogs)


def semantic_search(
    db: Session,
    query_vector: Sequence[float],
    *,
    limit: int = DEFAULT_SEARCH_LIMIT,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[SemanticMatch]:
    """Return catalog entries ranked by cosine similarity to ``query_vector``.

    Only matches at or above ``threshold`` are returned, ordered by similarity
    descending (ties broken by catalog id), capped at ``limit``.

    On PostgreSQL the ranking runs in pgvector (``<=>`` cosine distance,
    HNSW-accelerated). Non-Postgres dialects (SQLite dev) fall back to the
    deterministic Python ranking in :mod:`riskapp.domain.similarity`.
    """
    if db.get_bind().dialect.name == "postgresql":
        return _pgvector_search(db, query_vector, limit=limit, threshold=threshold)
    return _python_search(db, query_vector, limit=limit, threshold=threshold)


def _pgvector_search(
    db: Session,
    query_vector: Sequence[float],
    *,
    limit: int,
    threshold: float,
) -> list[SemanticMatch]:
    """Native pgvector search: cosine distance + HNSW index."""
    rows = db.execute(
        _PGVECTOR_SQL,
        {
            "query": _vector_literal(query_vector),
            "threshold": threshold,
            "limit": limit,
        },
    ).mappings().all()

    return [
        SemanticMatch(
            risk_id=str(row["id"]),
            source_file="",
            source_risk_id=None,
            description=row["description"],
            similarity=float(row["similarity"]),
        )
        for row in rows
    ]


def _python_search(
    db: Session,
    query_vector: Sequence[float],
    *,
    limit: int,
    threshold: float,
) -> list[SemanticMatch]:
    """Deterministic Python ranking (SQLite dev only; never production)."""
    catalogs = db.scalars(
        select(models.RiskCatalog)
        .where(models.RiskCatalog.embedding.is_not(None))
        .order_by(models.RiskCatalog.id)
    ).all()

    if not catalogs:
        return []

    items = [(str(catalog.id), catalog.embedding or []) for catalog in catalogs]
    ranked = rank_by_similarity(query_vector, items, threshold=threshold, limit=limit)

    by_id = {str(catalog.id): catalog for catalog in catalogs}
    results: list[SemanticMatch] = []
    for hit in ranked:
        catalog = by_id[hit.key]
        results.append(
            SemanticMatch(
                risk_id=str(catalog.id),
                source_file="",
                source_risk_id=None,
                description=catalog.description,
                similarity=hit.similarity,
            )
        )
    return results


def _vector_literal(vector: Sequence[float]) -> str:
    """Serialize a vector to pgvector's array literal, e.g. ``[1.0, 0.5]``."""
    return "[" + ",".join(str(float(x)) for x in vector) + "]"


def _embed_in_batches(
    client: EmbeddingProvider, texts: list[str], batch_size: int
) -> list[list[float]]:
    """Embed ``texts`` in chunks, preserving order."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        vectors.extend(client.embed_texts(batch))
    return vectors
