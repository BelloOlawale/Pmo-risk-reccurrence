"""API test for the suggestion endpoint (fakes injected via FastAPI deps)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.main import app, get_chat_provider, get_embedding_provider


class FakeChat:
    def complete(self, messages, *, temperature=0.0, max_tokens=1500) -> str:
        return json.dumps(
            {
                "overview": "Watch [RSK-1, a.xlsx] closely.",
                "recommendations": ["Mitigate [RSK-1, a.xlsx]."],
                "analyses": [],
            }
        )


class FakeEmbeddings:
    def embed_text(self, text: str) -> list[float]:
        return [0.0, 1.0, 0.0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_text(t) for t in texts]


def test_suggest_endpoint_returns_grounded_risks(
    client: TestClient, db_session: Session
) -> None:
    # Seed a historical risk directly into the test DB.
    dept = models.Department(name="Digital Advisory")
    ptype = models.ProjectType(name="Cloud Migration")
    db_session.add_all([dept, ptype])
    db_session.flush()
    historical = models.Project(name="Old", project_code="PRJ-OLD", status="Active")
    historical.department = dept
    historical.project_type = ptype
    db_session.add(historical)
    db_session.flush()
    db_session.add(
        models.Risk(
            project_id=historical.id,
            risk_code="RSK-1",
            description="Data loss during cutover",
            likelihood="Medium",
            impact="High",
            risk_rating="High",
            source="Historical",
            status="Closed",
            source_file_name="a.xlsx",
            source_risk_id="R1",
            embedding=[0.0, 1.0, 0.0],
        )
    )
    db_session.commit()

    app.dependency_overrides[get_chat_provider] = lambda: FakeChat()
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbeddings()
    try:
        project = client.post(
            "/api/projects",
            json={
                "name": "AWS Migration",
                "department": "Digital Advisory",
                "project_type": "Cloud Migration",
                "customer": "C",
            },
        ).json()

        resp = client.post(f"/api/projects/{project['id']}/suggest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == project["id"]
        assert data["suggested_risks"][0]["risk_id"] == "RSK-1"
        assert data["suggested_risks"][0]["citation"] == "[RSK-1, a.xlsx]"
        assert data["evaluation"]["groundedness"] == 1.0
    finally:
        app.dependency_overrides.pop(get_chat_provider, None)
        app.dependency_overrides.pop(get_embedding_provider, None)


def test_suggest_endpoint_404_for_missing_project(client: TestClient) -> None:
    resp = client.post("/api/projects/99999/suggest")
    assert resp.status_code == 404


def test_accept_suggestion_returns_201_when_risk_codes_have_gaps(
    client: TestClient, db_session: Session
) -> None:
    """Accepting a suggestion as a PM must not 500 on a duplicate risk code.

    Regression: the live DB had deleted rows, so the highest risk code
    exceeded the risk count; count-based allocation reused an existing code
    and the accept endpoint raised an uncaught IntegrityError (HTTP 500).
    """
    dept = models.Department(name="SAP")
    ptype = models.ProjectType(name="ERP")
    db_session.add_all([dept, ptype])
    db_session.flush()

    def make(code: str) -> models.Project:
        p = models.Project(name=f"Project {code}", project_code=code, status="Active")
        p.department = dept
        p.project_type = ptype
        db_session.add(p)
        db_session.flush()
        return p

    historical = make("PRJ-GAP-H")
    target = make("PRJ-GAP-T")
    for code, description in (
        ("RSK-001", "Data migration delay"),
        ("RSK-003", "Vendor lock-in"),  # RSK-002 absent -> gap
    ):
        db_session.add(
            models.Risk(
                project_id=historical.id,
                risk_code=code,
                description=description,
                likelihood="Medium",
                impact="High",
                risk_rating="High",
                source="Historical",
                status="Closed",
                source_file_name="a.xlsx",
                source_risk_id="1",
            )
        )
    db_session.commit()

    resp = client.post(
        f"/api/projects/{target.id}/suggestions/accept",
        json={"risk_id": "RSK-001"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["risk_code"] == "RSK-004"
