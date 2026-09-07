"""Tests for embedding persistence and semantic search over the catalog."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.vector_store import (
    build_embedding_text,
    embed_all_risks,
    semantic_search,
)


class FakeEmbeddings:
    """Deterministic embedding provider for tests."""

    def __init__(self, dim: int = 3) -> None:
        self.dim = dim
        self.received: list[list[str]] = []

    def embed_text(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.received.append(list(texts))
        return [[float(len(t))] * self.dim for t in texts]


def _catalog(
    db: Session,
    description: str,
    *,
    category: str | None = None,
    embedding: list[float] | None = None,
) -> models.RiskCatalog:
    catalog = models.RiskCatalog(
        description=description, category=category, embedding=embedding
    )
    db.add(catalog)
    db.flush()
    return catalog


class TestBuildEmbeddingText:
    def test_includes_description_and_category(self, db_session: Session) -> None:
        catalog = _catalog(db_session, "Vendor delay", category="Schedule")
        text = build_embedding_text(catalog)
        assert "Vendor delay" in text
        assert "Schedule" in text


class TestEmbedAllRisks:
    def test_persists_vectors_for_all_risks(self, db_session: Session) -> None:
        _catalog(db_session, "Scope creep")
        _catalog(db_session, "Vendor delay")
        db_session.commit()

        fake = FakeEmbeddings(dim=3)
        assert embed_all_risks(db_session, fake) == 2

        catalogs = db_session.scalars(
            select(models.RiskCatalog).order_by(models.RiskCatalog.id)
        ).all()
        assert all(c.embedding is not None for c in catalogs)
        assert all(len(c.embedding or []) == 3 for c in catalogs)

    def test_embeds_the_built_text(self, db_session: Session) -> None:
        _catalog(db_session, "Scope creep")
        db_session.commit()

        fake = FakeEmbeddings(dim=3)
        embed_all_risks(db_session, fake)
        assert any("Scope creep" in text for text in fake.received[0])

    def test_idempotent_second_run_is_noop(self, db_session: Session) -> None:
        _catalog(db_session, "Scope creep")
        db_session.commit()

        fake = FakeEmbeddings(dim=3)
        assert embed_all_risks(db_session, fake) == 1
        assert embed_all_risks(db_session, fake) == 0

    def test_batches_embedding_calls(self, db_session: Session) -> None:
        for i in range(3):
            _catalog(db_session, f"risk {i}")
        db_session.commit()

        fake = FakeEmbeddings(dim=3)
        embed_all_risks(db_session, fake, batch_size=1)
        assert len(fake.received) == 3  # three separate batches


class TestSemanticSearch:
    def _seeded(self, db_session: Session) -> None:
        _catalog(db_session, "a", embedding=[1.0, 0.0, 0.0])
        _catalog(db_session, "b", embedding=[0.9, 0.1, 0.0])
        _catalog(db_session, "c", embedding=[0.0, 1.0, 0.0])
        db_session.commit()

    def test_ranks_by_cosine_similarity(self, db_session: Session) -> None:
        self._seeded(db_session)
        results = semantic_search(db_session, [1.0, 0.0, 0.0])
        assert [r.risk_id for r in results] == ["1", "2"]
        assert results[0].similarity == pytest.approx(1.0)
        assert results[0].description == "a"

    def test_below_threshold_excluded(self, db_session: Session) -> None:
        self._seeded(db_session)
        # entry "c" is orthogonal (0.0) and "b" (~0.994) is below 0.995.
        results = semantic_search(db_session, [1.0, 0.0, 0.0], threshold=0.995)
        assert [r.risk_id for r in results] == ["1"]

    def test_limit_caps_results(self, db_session: Session) -> None:
        self._seeded(db_session)
        results = semantic_search(db_session, [1.0, 0.0, 0.0], limit=1)
        assert [r.risk_id for r in results] == ["1"]

    def test_ties_broken_by_catalog_id(self, db_session: Session) -> None:
        _catalog(db_session, "x", embedding=[1.0, 0.0, 0.0])
        _catalog(db_session, "y", embedding=[1.0, 0.0, 0.0])
        db_session.commit()

        results = semantic_search(db_session, [1.0, 0.0, 0.0])
        assert [r.risk_id for r in results] == ["1", "2"]

    def test_no_embeddings_returns_empty(self, db_session: Session) -> None:
        _catalog(db_session, "no embedding")
        db_session.commit()
        assert semantic_search(db_session, [1.0, 0.0, 0.0]) == []
