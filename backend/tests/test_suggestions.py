"""Tests for the hybrid-retrieval + LLM suggestion service."""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.suggestions import generate_suggestions, retrieve_candidates


class FakeChat:
    """Deterministic chat provider for tests."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.messages: list[list[dict[str, str]]] = []

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.0,
        max_tokens: int = 1500,
    ) -> str:
        self.messages.append(messages)
        return self.text


class FakeEmbeddings:
    def __init__(self, vector: list[float]) -> None:
        self.vector = vector

    def embed_text(self, text: str) -> list[float]:
        return self.vector

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.vector] * len(texts)


def _project(
    db: Session,
    *,
    code: str,
    name: str,
    department: str,
    project_type: str,
) -> models.Project:
    dept = db.scalar(select(models.Department).where(models.Department.name == department))
    if dept is None:
        dept = models.Department(name=department)
        db.add(dept)
        db.flush()
    ptype = db.scalar(select(models.ProjectType).where(models.ProjectType.name == project_type))
    if ptype is None:
        ptype = models.ProjectType(name=project_type)
        db.add(ptype)
        db.flush()
    project = models.Project(name=name, project_code=code, status="Active")
    project.department = dept
    project.project_type = ptype
    db.add(project)
    db.flush()
    return project


def _risk(
    db: Session,
    project: models.Project,
    *,
    code: str,
    description: str,
    source_file: str,
    source_risk_id: str,
    category: str | None = None,
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
        source="Historical",
        status="Closed",
        source_file_name=source_file,
        source_risk_id=source_risk_id,
        embedding=embedding,
    )
    db.add(risk)
    db.flush()
    return risk


def _seed(db: Session) -> models.Project:
    """Seed two same-type historical risks and one cross-type risk."""
    historical = _project(
        db, code="PRJ-HIST", name="Old AWS Migration",
        department="Digital Advisory", project_type="Cloud Migration",
    )
    _risk(
        db, historical, code="RSK-1", description="Data loss during cutover",
        source_file="hist-a.xlsx", source_risk_id="R1",
        embedding=[0.0, 1.0, 0.0],
    )
    _risk(
        db, historical, code="RSK-2", description="Vendor lock-in",
        source_file="hist-b.xlsx", source_risk_id="R2",
        embedding=[0.0, 1.0, 0.0],
    )

    erp = _project(
        db, code="PRJ-ERP", name="SAP ERP rollout",
        department="SAP", project_type="ERP Implementation",
    )
    _risk(
        db, erp, code="RSK-3", description="AWS data migration failure",
        source_file="erp.xlsx", source_risk_id="R3",
        embedding=[1.0, 0.0, 0.0],
    )

    new_project = _project(
        db, code="PRJ-NEW", name="AWS Migration",
        department="Digital Advisory", project_type="Cloud Migration",
    )
    db.commit()
    return new_project


class TestRetrieveCandidates:
    def test_merges_exact_keyword_semantic_without_duplicates(
        self, db_session: Session
    ) -> None:
        project = _seed(db_session)
        candidates = retrieve_candidates(
            db_session, project, FakeEmbeddings([1.0, 0.0, 0.0])
        )
        # RSK-1, RSK-2 exact; RSK-3 keyword ("aws"/"migration"); RSK-3 semantic deduped.
        assert [c.risk_id for c in candidates] == ["RSK-1", "RSK-2", "RSK-3"]
        assert [c.match_type.value for c in candidates] == ["exact", "exact", "keyword"]

    def test_dismissed_risks_are_filtered(self, db_session: Session) -> None:
        project = _seed(db_session)
        db_session.add(
            models.SuggestionDismissal(
                project_id=project.id, historical_risk_key="RSK-1", reason="seen"
            )
        )
        db_session.commit()

        candidates = retrieve_candidates(
            db_session, project, FakeEmbeddings([1.0, 0.0, 0.0])
        )
        assert [c.risk_id for c in candidates] == ["RSK-2", "RSK-3"]


class TestGenerateSuggestions:
    def test_returns_overview_citations_and_groundedness(
        self, db_session: Session
    ) -> None:
        project = _seed(db_session)
        llm_json = json.dumps(
            {
                "overview": "Watch out for [RSK-3, erp.xlsx] migration issues.",
                "recommendations": ["Plan a rollback for [RSK-1, hist-a.xlsx]."],
                "analyses": [{"risk_id": "RSK-1", "analysis": "High cutover risk."}],
            }
        )
        chat = FakeChat(llm_json)
        result = generate_suggestions(
            db_session, project, chat, FakeEmbeddings([1.0, 0.0, 0.0])
        )

        assert result.project_id == project.id
        assert "[RSK-3](/files/erp.xlsx)" in result.overview
        assert len(result.recommendations) == 1
        assert [r["risk_id"] for r in result.suggested_risks] == [
            "RSK-1", "RSK-2", "RSK-3",
        ]
        assert result.suggested_risks[0]["citation"] == "[RSK-1, hist-a.xlsx]"
        assert result.suggested_risks[0]["analysis"] == "High cutover risk."
        assert result.evaluation["groundedness"] == 1.0

    def test_unverified_citation_lowers_groundedness(self, db_session: Session) -> None:
        project = _seed(db_session)
        chat = FakeChat(
            json.dumps(
                {
                    "overview": "Concern: [RSK-99, ghost.xlsx] is a real problem.",
                    "recommendations": [],
                    "analyses": [],
                }
            )
        )
        result = generate_suggestions(
            db_session, project, chat, FakeEmbeddings([1.0, 0.0, 0.0])
        )
        assert result.evaluation["groundedness"] == 0.0
        assert result.evaluation["unverified_citations"][0]["risk_id"] == "RSK-99"

    def test_llm_failure_falls_back_to_deterministic_summary(
        self, db_session: Session
    ) -> None:
        project = _seed(db_session)

        class BrokenChat:
            def complete(self, messages, **kwargs) -> str:
                raise RuntimeError("boom")

        result = generate_suggestions(
            db_session, project, BrokenChat(), FakeEmbeddings([1.0, 0.0, 0.0])
        )
        assert len(result.suggested_risks) == 3
        assert "3 historical risks" in result.overview
        assert result.recommendations == []
        assert result.evaluation["groundedness"] == 1.0  # no citations to verify
