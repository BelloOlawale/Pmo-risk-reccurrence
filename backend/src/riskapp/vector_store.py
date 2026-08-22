"""Semantic search over stored risk embeddings.

Replaces the legacy FAISS+Blob index with pgvector in Postgres. Embeddings
are persisted on ``risks.embedding`` (``vector(1536)``, see migration
``9f8e7d6c5b4a``) and searched with the native pgvector cosine-distance
operator (``<=>``) backed by the HNSW index.

On PostgreSQL the search is executed entirely in the database. The pure
:mod:`riskapp.domain.similarity` path is kept only as a fallback for
non-Postgres dialects (local SQLite development), where pgvector is
unavailable — it is never used in production.
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
        SELECT risk_code,
               source_file_name,
               source_risk_id,
               description,
               1 - (embedding <=> CAST(:query AS vector)) AS similarity
        FROM risks
        WHERE embedding IS NOT NULL
    ) ranked
    WHERE similarity >= :threshold
    ORDER BY similarity DESC, risk_code ASC
    LIMIT :limit
    """
)


def build_embedding_text(risk: models.Risk) -> str:
    """Build the text to embed for a risk (description + salient fields)."""
    category = risk.category or ""
    subcategory = risk.subcategory or ""
    category_text = f"{category} / {subcategory}" if subcategory else category

    parts = [
        risk.description,
        f"Category: {category_text}" if category_text else "",
        f"Likelihood: {risk.likelihood}",
        f"Impact: {risk.impact}",
        f"Rating: {risk.risk_rating}",
    ]
    return " | ".join(part for part in parts if part)


def embed_all_risks(
    db: Session, client: EmbeddingProvider, *, batch_size: int = DEFAULT_EMBED_BATCH_SIZE
) -> int:
    """Embed every risk without an embedding and persist the vectors.

    Idempotent: only risks whose ``embedding`` is NULL are processed. Returns
    the number of risks embedded.
    """
    risks = db.scalars(
        select(models.Risk)
        .where(models.Risk.embedding.is_(None))
        .order_by(models.Risk.id)
    ).all()

    if not risks:
        return 0

    texts = [build_embedding_text(risk) for risk in risks]
    vectors = _embed_in_batches(client, texts, batch_size)

    for risk, vector in zip(risks, vectors, strict=True):
        risk.embedding = vector

    db.commit()
    return len(risks)


def semantic_search(
    db: Session,
    query_vector: Sequence[float],
    *,
    limit: int = DEFAULT_SEARCH_LIMIT,
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> list[SemanticMatch]:
    """Return risks ranked by cosine similarity to ``query_vector``.

    Only matches at or above ``threshold`` are returned, ordered by
    similarity descending (ties broken by ``risk_code``), capped at ``limit``.

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
            risk_id=row["risk_code"],
            source_file=row["source_file_name"] or "",
            source_risk_id=row["source_risk_id"],
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
    risks = db.scalars(
        select(models.Risk)
        .where(models.Risk.embedding.is_not(None))
        .order_by(models.Risk.id)
    ).all()

    if not risks:
        return []

    items = [(risk.risk_code, risk.embedding or []) for risk in risks]
    ranked = rank_by_similarity(query_vector, items, threshold=threshold, limit=limit)

    by_code = {risk.risk_code: risk for risk in risks}
    results: list[SemanticMatch] = []
    for hit in ranked:
        risk = by_code[hit.key]
        results.append(
            SemanticMatch(
                risk_id=risk.risk_code,
                source_file=risk.source_file_name or "",
                source_risk_id=risk.source_risk_id,
                description=risk.description,
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
