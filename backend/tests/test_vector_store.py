"""Tests for embedding persistence and semantic search."""

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


def _project(db: Session, code: str) -> models.Project:
    department = models.Department(name=f"D-{code}")
    project_type = models.ProjectType(name=f"T-{code}")
    db.add_all([department, project_type])
    db.flush()
    project = models.Project(name=f"P {code}", project_code=code, status="Active")
    project.department = department
    project.project_type = project_type
    db.add(project)
    db.flush()
    return project


def _risk(
    db: Session,
    project: models.Project,
    code: str,
    description: str,
    *,
    category: str | None = None,
    source_file: str | None = None,
    source_risk_id: str | None = None,
    embedding: list[float] | None = None,
) -> models.Risk:
    risk = models.Risk(
        project_id=project.id,
        risk_code=code,
        description=description,
        category=category,
        likelihood="Medium",
        impact="Medium",
        risk_rating="Medium",
        source_file_name=source_file,
        source_risk_id=source_risk_id,
        embedding=embedding,
    )
    db.add(risk)
    db.flush()
    return risk


class TestBuildEmbeddingText:
    def test_includes_description_and_category(self, db_session: Session) -> None:
        project = _project(db_session, "PRJ-TXT")
        risk = _risk(db_session, project, "RSK-1", "Vendor delay", category="Schedule")
        text = build_embedding_text(risk)
        assert "Vendor delay" in text
        assert "Schedule" in text
        assert "Medium" in text  # likelihood/impact/rating


class TestEmbedAllRisks:
    def test_persists_vectors_for_all_risks(self, db_session: Session) -> None:
        project = _project(db_session, "PRJ-EMB")
        _risk(db_session, project, "RSK-1", "Scope creep")
        _risk(db_session, project, "RSK-2", "Vendor delay")
        db_session.commit()

        fake = FakeEmbeddings(dim=3)
        assert embed_all_risks(db_session, fake) == 2

        risks = db_session.scalars(select(models.Risk).order_by(models.Risk.id)).all()
        assert all(r.embedding is not None for r in risks)
        assert all(len(r.embedding or []) == 3 for r in risks)

    def test_embeds_the_built_text(self, db_session: Session) -> None:
        project = _project(db_session, "PRJ-EMB")
        _risk(db_session, project, "RSK-1", "Scope creep")
        db_session.commit()

        fake = FakeEmbeddings(dim=3)
        embed_all_risks(db_session, fake)
        assert any("Scope creep" in text for text in fake.received[0])

    def test_idempotent_second_run_is_noop(self, db_session: Session) -> None:
        project = _project(db_session, "PRJ-EMB")
        _risk(db_session, project, "RSK-1", "Scope creep")
        db_session.commit()

        fake = FakeEmbeddings(dim=3)
        assert embed_all_risks(db_session, fake) == 1
        assert embed_all_risks(db_session, fake) == 0

    def test_batches_embedding_calls(self, db_session: Session) -> None:
        project = _project(db_session, "PRJ-EMB")
        for i in range(3):
            _risk(db_session, project, f"RSK-{i}", f"risk {i}")
        db_session.commit()

        fake = FakeEmbeddings(dim=3)
        embed_all_risks(db_session, fake, batch_size=1)
        assert len(fake.received) == 3  # three separate batches


class TestSemanticSearch:
    def _seeded(self, db_session: Session) -> None:
        project = _project(db_session, "PRJ-SEM")
        _risk(db_session, project, "RSK-1", "a", source_file="a.xlsx",
              source_risk_id="A", embedding=[1.0, 0.0, 0.0])
        _risk(db_session, project, "RSK-2", "b", source_file="b.xlsx",
              source_risk_id="B", embedding=[0.9, 0.1, 0.0])
        _risk(db_session, project, "RSK-3", "c", source_file="c.xlsx",
              source_risk_id="C", embedding=[0.0, 1.0, 0.0])
        db_session.commit()

    def test_ranks_by_cosine_similarity(self, db_session: Session) -> None:
        self._seeded(db_session)
        results = semantic_search(db_session, [1.0, 0.0, 0.0])
        assert [r.risk_id for r in results] == ["RSK-1", "RSK-2"]
        assert results[0].similarity == pytest.approx(1.0)
        assert results[0].source_file == "a.xlsx"
        assert results[1].source_risk_id == "B"

    def test_below_threshold_excluded(self, db_session: Session) -> None:
        self._seeded(db_session)
        # RSK-3 is orthogonal (0.0) and RSK-2 (~0.994) is below 0.995.
        results = semantic_search(db_session, [1.0, 0.0, 0.0], threshold=0.995)
        assert [r.risk_id for r in results] == ["RSK-1"]

    def test_limit_caps_results(self, db_session: Session) -> None:
        self._seeded(db_session)
        results = semantic_search(db_session, [1.0, 0.0, 0.0], limit=1)
        assert [r.risk_id for r in results] == ["RSK-1"]

    def test_ties_broken_by_risk_code(self, db_session: Session) -> None:
        project = _project(db_session, "PRJ-SEM")
        _risk(db_session, project, "RSK-2", "x", embedding=[1.0, 0.0, 0.0])
        _risk(db_session, project, "RSK-1", "y", embedding=[1.0, 0.0, 0.0])
        db_session.commit()

        results = semantic_search(db_session, [1.0, 0.0, 0.0])
        assert [r.risk_id for r in results] == ["RSK-1", "RSK-2"]

    def test_no_embeddings_returns_empty(self, db_session: Session) -> None:
        project = _project(db_session, "PRJ-SEM")
        _risk(db_session, project, "RSK-1", "no embedding")
        db_session.commit()
        assert semantic_search(db_session, [1.0, 0.0, 0.0]) == []
