"""API test for the suggestion endpoint (fakes injected via FastAPI deps)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.main import app, get_chat_provider, get_embedding_provider


class FakeChat:
    def __init__(self, risk_id: str) -> None:
        self.risk_id = risk_id

    def complete(self, messages, *, temperature=0.0, max_tokens=1500) -> str:
        return json.dumps(
            {
                "overview": f"Watch [{self.risk_id}, a.xlsx] closely.",
                "recommendations": [f"Mitigate [{self.risk_id}, a.xlsx]."],
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
    catalog = models.RiskCatalog(description="Data loss during cutover", embedding=[0.0, 1.0, 0.0])
    db_session.add(catalog)
    db_session.flush()
    risk = models.ProjectRisk(
        project_id=historical.id,
        risk_id=catalog.id,
        likelihood="Medium",
        impact="High",
        risk_rating="High",
        source="Historical",
        status="Closed",
        source_file_name="a.xlsx",
        source_risk_id="R1",
    )
    db_session.add(risk)
    db_session.commit()

    app.dependency_overrides[get_chat_provider] = lambda: FakeChat(str(risk.id))
    app.dependency_overrides[get_embedding_provider] = lambda: FakeEmbeddings()
    try:
        project = client.post(
            "/api/projects",
            json={
                "name": "AWS Migration",
                "department": "Digital Advisory",
                "project_type": "Cloud Migration",
            },
        ).json()

        resp = client.post(f"/api/projects/{project['id']}/suggest")
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == project["id"]
        assert data["suggested_risks"][0]["risk_id"] == str(risk.id)
        assert data["suggested_risks"][0]["citation"] == f"[{risk.id}, a.xlsx]"
        assert data["evaluation"]["groundedness"] == 1.0
    finally:
        app.dependency_overrides.pop(get_chat_provider, None)
        app.dependency_overrides.pop(get_embedding_provider, None)


def test_suggest_endpoint_404_for_missing_project(client: TestClient) -> None:
    resp = client.post("/api/projects/99999/suggest")
    assert resp.status_code == 404
