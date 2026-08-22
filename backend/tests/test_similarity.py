"""Tests for the pure cosine similarity + ranking logic."""

from __future__ import annotations

import pytest

from riskapp.domain.similarity import cosine_similarity, rank_by_similarity


class TestCosineSimilarity:
    def test_identical_vectors_are_1(self) -> None:
        assert cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)

    def test_orthogonal_vectors_are_0(self) -> None:
        assert cosine_similarity([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]) == pytest.approx(0.0)

    def test_opposite_vectors_are_minus_1(self) -> None:
        assert cosine_similarity([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_known_example(self) -> None:
        # dot = 4 + 10 + 18 = 32; |a|=sqrt(14); |b|=sqrt(77)
        assert cosine_similarity([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]) == pytest.approx(
            32 / (14**0.5 * 77**0.5)
        )

    def test_zero_vector_returns_0(self) -> None:
        assert cosine_similarity([0.0, 0.0], [1.0, 2.0]) == pytest.approx(0.0)
        assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) == pytest.approx(0.0)

    def test_dimension_mismatch_raises(self) -> None:
        with pytest.raises(ValueError):
            cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])


class TestRankBySimilarity:
    def test_ranks_by_similarity_desc(self) -> None:
        query = [1.0, 0.0]
        items = [("low", [0.0, 1.0]), ("high", [1.0, 0.0]), ("mid", [0.7, 0.7])]
        ranked = rank_by_similarity(query, items)
        assert [r.key for r in ranked] == ["high", "mid", "low"]

    def test_threshold_filters_inclusive(self) -> None:
        query = [1.0, 0.0]
        items = [("exact", [1.0, 0.0]), ("edge", [0.75, 0.6614]), ("low", [0.0, 1.0])]
        ranked = rank_by_similarity(query, items, threshold=0.75)
        # edge vector has ~0.75 cosine with query
        assert [r.key for r in ranked] == ["exact", "edge"]

    def test_limit_caps_results(self) -> None:
        query = [1.0, 0.0]
        items = [(f"r{i}", [1.0 - 0.01 * i, 0.01 * i]) for i in range(10)]
        ranked = rank_by_similarity(query, items, limit=3)
        assert len(ranked) == 3

    def test_ties_broken_by_key_ascending(self) -> None:
        query = [1.0, 0.0]
        items = [("b", [1.0, 0.0]), ("a", [1.0, 0.0]), ("c", [1.0, 0.0])]
        ranked = rank_by_similarity(query, items)
        assert [r.key for r in ranked] == ["a", "b", "c"]

    def test_empty_items(self) -> None:
        assert rank_by_similarity([1.0, 0.0], []) == []
