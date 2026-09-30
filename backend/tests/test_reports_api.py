"""Reports API: the escalation trend reflects real escalated risks."""

from __future__ import annotations

from fastapi.testclient import TestClient

from riskapp.domain.status import RiskStatus


def _project(client: TestClient, name: str) -> dict:
    return client.post(
        "/api/projects",
        json={"name": name, "department": "D", "project_type": "T", "customer": "C"},
    ).json()


def _risk(client: TestClient, project_id: int, desc: str) -> dict:
    return client.post(
        "/api/risks",
        json={
            "project_id": project_id,
            "description": desc,
            "likelihood": "High",
            "impact": "High",
        },
    ).json()


def test_escalation_trend_empty_when_none(client: TestClient) -> None:
    resp = client.get("/api/reports/escalation-trend")
    assert resp.status_code == 200
    assert resp.json() == {"months": [], "values": []}


def test_escalation_trend_counts_real_escalations(client: TestClient) -> None:
    project = _project(client, "P")
    first = _risk(client, project["id"], "one")
    second = _risk(client, project["id"], "two")

    for risk in (first, second):
        assert (
            client.patch(
                f"/api/risks/{risk['id']}", json={"status": RiskStatus.ESCALATED.value}
            ).status_code
            == 200
        )

    body = client.get("/api/reports/escalation-trend").json()
    assert len(body["months"]) == 1
    assert body["values"] == [2]


def test_escalation_trend_scoped_to_project(client: TestClient) -> None:
    project_a = _project(client, "A")
    project_b = _project(client, "B")
    risk_a = _risk(client, project_a["id"], "a")
    risk_b = _risk(client, project_b["id"], "b")
    client.patch(f"/api/risks/{risk_a['id']}", json={"status": "Escalated"})
    client.patch(f"/api/risks/{risk_b['id']}", json={"status": "Escalated"})

    body = client.get(
        f"/api/reports/escalation-trend?project_id={project_a['id']}"
    ).json()
    assert body["values"] == [1]

    body_b = client.get(
        f"/api/reports/escalation-trend?project_id={project_b['id']}"
    ).json()
    assert body_b["values"] == [1]
