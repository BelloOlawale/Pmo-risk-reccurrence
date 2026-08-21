"""Tests for the hybrid retrieval merge/dedupe/rank pure logic."""

from __future__ import annotations

import pytest

from riskapp.domain.retrieval import (
    DEFAULT_SEMANTIC_THRESHOLD,
    ExactMatch,
    KeywordMatch,
    MatchType,
    SemanticMatch,
    merge_candidates,
)


def _exact(risk_id: str, source_file: str, source_risk_id: str | None = None,
           description: str = "") -> ExactMatch:
    return ExactMatch(
        risk_id=risk_id, source_file=source_file,
        source_risk_id=source_risk_id, description=description,
    )


def _keyword(risk_id: str, match_count: int, source_risk_id: str | None = None,
             source_file: str = "a.xlsx", description: str = "") -> KeywordMatch:
    return KeywordMatch(
        risk_id=risk_id, source_file=source_file, match_count=match_count,
        source_risk_id=source_risk_id, description=description,
    )


def _semantic(risk_id: str, similarity: float, source_risk_id: str | None = None,
              source_file: str = "a.xlsx", description: str = "") -> SemanticMatch:
    return SemanticMatch(
        risk_id=risk_id, source_file=source_file, similarity=similarity,
        source_risk_id=source_risk_id, description=description,
    )


class TestExactMatches:
    def test_exact_always_included(self) -> None:
        merged = merge_candidates(
            [_exact("RSK-1", "a.xlsx", "R-1"), _exact("RSK-2", "b.xlsx", "R-2")],
            [],
            [],
        )
        assert [c.risk_id for c in merged] == ["RSK-1", "RSK-2"]
        assert all(c.match_type == MatchType.EXACT for c in merged)

    def test_exact_ordered_by_risk_id(self) -> None:
        merged = merge_candidates(
            [_exact("RSK-3", "a.xlsx"), _exact("RSK-1", "b.xlsx"), _exact("RSK-2", "c.xlsx")],
            [],
            [],
        )
        assert [c.risk_id for c in merged] == ["RSK-1", "RSK-2", "RSK-3"]


class TestDeduplication:
    def test_same_risk_across_all_sets_appears_once_as_exact(self) -> None:
        merged = merge_candidates(
            [_exact("RSK-1", "a.xlsx", "R-001", "desc")],
            [_keyword("RSK-1", 3, "R-001", "a.xlsx", "desc")],
            [_semantic("RSK-1", 0.95, "R-001", "a.xlsx", "desc")],
        )
        assert len(merged) == 1
        assert merged[0].match_type == MatchType.EXACT

    def test_duplicate_keyword_candidates_collapse(self) -> None:
        merged = merge_candidates(
            [],
            [_keyword("RSK-1", 2, "R-1"), _keyword("RSK-1", 5, "R-1")],
            [],
        )
        # Highest match_count wins the single slot.
        assert len(merged) == 1
        assert merged[0].match_count == 5

    def test_keyword_duplicate_of_exact_is_skipped(self) -> None:
        merged = merge_candidates(
            [_exact("RSK-1", "a.xlsx", "R-1")],
            [_keyword("RSK-1", 5, "R-1")],
            [],
        )
        assert len(merged) == 1
        assert merged[0].match_type == MatchType.EXACT

    def test_missing_source_id_falls_back_to_description(self) -> None:
        """Two ID-less rows in the same file must not collapse."""
        merged = merge_candidates(
            [
                _exact("RSK-1", "tnl.xlsx", None, "Delay in requirements"),
                _exact("RSK-2", "tnl.xlsx", None, "Scope creep"),
            ],
            [],
            [],
        )
        assert len(merged) == 2
        assert [c.risk_id for c in merged] == ["RSK-1", "RSK-2"]


class TestKeywordRanking:
    def test_ranked_by_match_count_desc(self) -> None:
        merged = merge_candidates(
            [],
            [_keyword("RSK-1", 1), _keyword("RSK-2", 9), _keyword("RSK-3", 4)],
            [],
        )
        assert [c.risk_id for c in merged] == ["RSK-2", "RSK-3", "RSK-1"]

    def test_tie_broken_by_risk_id(self) -> None:
        merged = merge_candidates(
            [],
            [_keyword("RSK-3", 4), _keyword("RSK-1", 4), _keyword("RSK-2", 4)],
            [],
        )
        assert [c.risk_id for c in merged] == ["RSK-1", "RSK-2", "RSK-3"]


class TestSemanticThreshold:
    def test_below_threshold_excluded(self) -> None:
        merged = merge_candidates([], [], [_semantic("RSK-1", 0.5)])
        assert merged == []

    def test_at_threshold_included(self) -> None:
        merged = merge_candidates(
            [], [], [_semantic("RSK-1", DEFAULT_SEMANTIC_THRESHOLD)]
        )
        assert [c.risk_id for c in merged] == ["RSK-1"]
        assert merged[0].match_type == MatchType.SEMANTIC

    def test_above_threshold_ranked_by_similarity(self) -> None:
        merged = merge_candidates(
            [],
            [],
            [_semantic("RSK-1", 0.8), _semantic("RSK-2", 0.95), _semantic("RSK-3", 0.9)],
        )
        assert [c.risk_id for c in merged] == ["RSK-2", "RSK-3", "RSK-1"]

    def test_custom_threshold(self) -> None:
        merged = merge_candidates(
            [], [], [_semantic("RSK-1", 0.8)], semantic_threshold=0.9
        )
        assert merged == []

    def test_semantic_tie_broken_by_risk_id(self) -> None:
        merged = merge_candidates(
            [],
            [],
            [_semantic("RSK-3", 0.9), _semantic("RSK-1", 0.9), _semantic("RSK-2", 0.9)],
        )
        assert [c.risk_id for c in merged] == ["RSK-1", "RSK-2", "RSK-3"]


class TestOverallOrdering:
    def test_exact_then_keyword_then_semantic(self) -> None:
        merged = merge_candidates(
            [_exact("RSK-10", "e.xlsx", "E-1")],
            [_keyword("RSK-20", 3, "K-1")],
            [_semantic("RSK-30", 0.9, "S-1")],
        )
        assert [c.match_type for c in merged] == [
            MatchType.EXACT, MatchType.KEYWORD, MatchType.SEMANTIC,
        ]

    def test_provenance_and_metadata_preserved(self) -> None:
        merged = merge_candidates(
            [_exact("RSK-1", "e.xlsx", "E-1", "exact desc")],
            [_keyword("RSK-2", 3, "K-1", "k.xlsx", "kw desc")],
            [_semantic("RSK-3", 0.88, "S-1", "s.xlsx", "sem desc")],
        )
        assert merged[0].match_count is None and merged[0].similarity is None
        assert merged[1].match_count == 3
        assert merged[2].similarity == pytest.approx(0.88)
        assert [c.source_file for c in merged] == ["e.xlsx", "k.xlsx", "s.xlsx"]
