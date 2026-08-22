"""Cosine similarity and similarity ranking — pure, deterministic logic.

The semantic retrieval path computes cosine similarity between an embedding
query vector and stored risk embeddings, then filters by threshold and ranks
descending. This module is dependency-free (stdlib only) so it can be
exhaustively unit-tested without a database or the pgvector extension.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class RankedSimilarity:
    """A single ranked hit: a candidate key and its cosine similarity."""

    key: str
    similarity: float


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Return the cosine similarity between two equal-length vectors.

    Both vectors must have the same non-zero dimension. The zero vector has
    no direction, so similarity against it is defined as 0.0.

    Raises:
        ValueError: if ``a`` and ``b`` have different lengths.
    """
    if len(a) != len(b):
        raise ValueError(
            f"Vector dimension mismatch: {len(a)} != {len(b)}"
        )

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def rank_by_similarity(
    query: Sequence[float],
    items: Iterable[tuple[str, Sequence[float]]],
    *,
    threshold: float = 0.0,
    limit: int = 20,
) -> list[RankedSimilarity]:
    """Rank ``(key, vector)`` candidates by cosine similarity to ``query``.

    Candidates at or above ``threshold`` are kept, sorted by similarity
    descending, and ties are broken by ``key`` ascending for determinism.
    At most ``limit`` results are returned.

    Raises:
        ValueError: if any candidate vector has a different length than ``query``.
    """
    ranked: list[RankedSimilarity] = []
    for key, vector in items:
        similarity = cosine_similarity(query, vector)
        if similarity >= threshold:
            ranked.append(RankedSimilarity(key=key, similarity=similarity))

    ranked.sort(key=lambda r: (-r.similarity, r.key))
    return ranked[:limit]
