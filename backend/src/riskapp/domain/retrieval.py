"""Hybrid retrieval: merge, dedupe, and rank suggestion candidates.

Pure, deterministic logic with no I/O. SPEC §7 gathers candidate historical
risks from three retrieval strategies — exact (Department + ProjectType),
keyword (category/subcategory/description token match), and semantic
(pgvector embedding similarity) — then merges them into one ordered list.

Ranking contract:

1. **Exact** matches are always included first (they are the strongest signal),
   ordered by ``risk_id``.
2. **Keyword** matches are always included, ranked by ``match_count``
   descending, then ``risk_id`` for ties.
3. **Semantic** matches are included only at or above ``semantic_threshold``,
   ranked by ``similarity`` descending, then ``risk_id`` for ties.

Duplicates across the three sets are collapsed by a stable key of
``(source_file, source_risk_id)``, falling back to ``description`` (then
``risk_id``) when the source ID is missing. The first (highest-priority)
occurrence wins, so a risk present in both exact and semantic sets appears
once with ``match_type="exact"``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

DEFAULT_SEMANTIC_THRESHOLD = 0.75


class MatchType(str, Enum):  # noqa: UP042 — str+Enum is intentional (JSON-friendly values)
    """Provenance of a merged candidate."""

    EXACT = "exact"
    KEYWORD = "keyword"
    SEMANTIC = "semantic"


@dataclass(frozen=True)
class ExactMatch:
    """A historical risk matched on Department + ProjectType."""

    risk_id: str
    source_file: str
    source_risk_id: str | None = None
    description: str = ""


@dataclass(frozen=True)
class KeywordMatch:
    """A historical risk matched on category/subcategory/description tokens."""

    risk_id: str
    source_file: str
    match_count: int
    source_risk_id: str | None = None
    description: str = ""


@dataclass(frozen=True)
class SemanticMatch:
    """A historical risk matched by embedding similarity (score 0–1)."""

    risk_id: str
    source_file: str
    similarity: float
    source_risk_id: str | None = None
    description: str = ""


@dataclass(frozen=True)
class RetrievedCandidate:
    """A deduplicated, ranked candidate with its match provenance."""

    risk_id: str
    source_file: str
    match_type: MatchType
    source_risk_id: str | None = None
    description: str = ""
    match_count: int | None = None
    similarity: float | None = None


_Candidate = ExactMatch | KeywordMatch | SemanticMatch


def merge_candidates(
    exact: list[ExactMatch],
    keyword: list[KeywordMatch],
    semantic: list[SemanticMatch],
    *,
    semantic_threshold: float = DEFAULT_SEMANTIC_THRESHOLD,
) -> list[RetrievedCandidate]:
    """Merge and rank the three candidate sets into one deterministic order.

    Args:
        exact: Candidates matched on Department + ProjectType (always included).
        keyword: Candidates matched on tokens (ranked by match count).
        semantic: Candidates matched by embedding similarity (threshold-gated).
        semantic_threshold: Minimum similarity (inclusive) to keep a semantic match.

    Returns:
        The ordered, deduplicated candidate list: exact → keyword → semantic.
    """
    seen: set[tuple[str, str]] = set()
    merged: list[RetrievedCandidate] = []

    # 1. Exact matches — always included first, in stable risk_id order.
    for exact_candidate in sorted(exact, key=lambda c: c.risk_id):
        key = _dedup_key(exact_candidate)
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            RetrievedCandidate(
                risk_id=exact_candidate.risk_id,
                source_file=exact_candidate.source_file,
                match_type=MatchType.EXACT,
                source_risk_id=exact_candidate.source_risk_id,
                description=exact_candidate.description,
            )
        )

    # 2. Keyword matches — always included, ranked by match count (desc).
    for keyword_candidate in sorted(keyword, key=lambda c: (-c.match_count, c.risk_id)):
        key = _dedup_key(keyword_candidate)
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            RetrievedCandidate(
                risk_id=keyword_candidate.risk_id,
                source_file=keyword_candidate.source_file,
                match_type=MatchType.KEYWORD,
                source_risk_id=keyword_candidate.source_risk_id,
                description=keyword_candidate.description,
                match_count=keyword_candidate.match_count,
            )
        )

    # 3. Semantic matches — threshold-gated, ranked by similarity (desc).
    semantic_above = [c for c in semantic if c.similarity >= semantic_threshold]
    for semantic_candidate in sorted(
        semantic_above, key=lambda c: (-c.similarity, c.risk_id)
    ):
        key = _dedup_key(semantic_candidate)
        if key in seen:
            continue
        seen.add(key)
        merged.append(
            RetrievedCandidate(
                risk_id=semantic_candidate.risk_id,
                source_file=semantic_candidate.source_file,
                match_type=MatchType.SEMANTIC,
                source_risk_id=semantic_candidate.source_risk_id,
                description=semantic_candidate.description,
                similarity=semantic_candidate.similarity,
            )
        )

    return merged


def _dedup_key(candidate: _Candidate) -> tuple[str, str]:
    """Stable dedup key: (source_file, source_risk_id), falling back to description.

    Risks without a source ID (e.g. the TNL schema) use their description so
    distinct rows from the same file never collapse into one.
    """
    source_file = candidate.source_file or ""
    identity = candidate.source_risk_id or candidate.description or candidate.risk_id
    return (source_file, identity)
