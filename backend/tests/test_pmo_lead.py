"""PMO Lead role: risk closure authority.

The PMO Lead (final closure authority) — and System Admin (app superuser) — may
transition a risk to ``Closed``. Project Managers and other users must be
rejected server-side even if they try to set ``status = Closed`` directly.
Risk Register (project) closure stays with the assigned PM and is out of scope
here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _headers(user_id: int | None, role: str) -> dict[str, str]:
    headers = {"X-User-Role": role}
    if user_id is not None:
        headers["X-User-Id"] = str(user_id)
    return headers


def _create_project(client: TestClient, *, user_id: int) -> dict:
    resp = client.post(
        "/api/projects",
        json={
            "name": f"PMO Lead test {user_id}",
            "department": "D",
            "project_type": "T",
            "customer": "C",
        },
        headers=_headers(user_id, "Project Manager"),
    )
    assert resp.status_code == 201
    return resp.json()


def _resolved_risk(client: TestClient, project: dict, *, pm_user_id: int) -> dict:
    risk = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "description": "Resolve me first",
            "likelihood": "High",
            "impact": "Medium",
        },
        headers=_headers(pm_user_id, "Project Manager"),
    ).json()
    assert client.post(f"/api/risks/{risk['id']}/accept").status_code == 200
    resp = client.patch(
        f"/api/risks/{risk['id']}",
        json={"status": "Resolved"},
        headers=_headers(pm_user_id, "Project Manager"),
    )
    assert resp.status_code == 200
    return risk


def test_me_returns_role(client: TestClient) -> None:
    resp = client.get("/api/me", headers=_headers(7, "PMO Lead"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == 7
    assert "PMO Lead" in body["roles"]

    resp = client.get("/api/me", headers=_headers(8, "Project Manager"))
    assert "Project Manager" in resp.json()["roles"]


def test_pm_cannot_close_a_risk(client: TestClient) -> None:
    project = _create_project(client, user_id=7)
    risk = _resolved_risk(client, project, pm_user_id=7)

    resp = client.patch(
        f"/api/risks/{risk['id']}",
        json={"status": "Closed"},
        headers=_headers(7, "Project Manager"),
    )
    assert resp.status_code == 403
    assert "PMO Lead" in resp.json()["detail"]

    # The risk is still Resolved — nothing changed.
    read = client.get(f"/api/risks/{risk['id']}", headers=_headers(None, "System Admin")).json()
    assert read["status"] == "Resolved"


def test_other_pm_cannot_close_someone_elses_risk(client: TestClient) -> None:
    project = _create_project(client, user_id=7)
    risk = _resolved_risk(client, project, pm_user_id=7)

    resp = client.patch(
        f"/api/risks/{risk['id']}",
        json={"status": "Closed"},
        headers=_headers(9, "Project Manager"),
    )
    assert resp.status_code == 403


def test_pmo_lead_can_close_a_risk(client: TestClient) -> None:
    project = _create_project(client, user_id=7)
    risk = _resolved_risk(client, project, pm_user_id=7)

    resp = client.patch(
        f"/api/risks/{risk['id']}",
        json={"status": "Closed", "actor_user_id": 99},
        headers=_headers(99, "PMO Lead"),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "Closed"

    # Closure is persisted and audited.
    read = client.get(f"/api/risks/{risk['id']}", headers=_headers(None, "System Admin")).json()
    assert read["status"] == "Closed"
    history = client.get(
        f"/api/risks/{risk['id']}/history", headers=_headers(None, "System Admin")
    ).json()
    closure = [e for e in history if e["action"] == "status_change" and e["new_value"] == "Closed"]
    assert len(closure) == 1
    assert closure[0]["old_value"] == "Resolved"


def test_pmo_lead_sees_all_projects_and_risks(client: TestClient) -> None:
    p1 = _create_project(client, user_id=7)
    p2 = _create_project(client, user_id=8)
    _resolved_risk(client, p1, pm_user_id=7)

    projects = client.get("/api/projects", headers=_headers(99, "PMO Lead")).json()
    assert {p["id"] for p in projects} >= {p1["id"], p2["id"]}

    risks = client.get("/api/risks", headers=_headers(99, "PMO Lead")).json()
    assert all(r["status"] in {"Resolved", "Suggested"} for r in risks)
    # PMO Lead can also open the other PM's project register.
    resp = client.get(f"/api/projects/{p2['id']}", headers=_headers(99, "PMO Lead"))
    assert resp.status_code == 200


def test_system_admin_can_close_a_risk(client: TestClient) -> None:
    project = _create_project(client, user_id=7)
    risk = _resolved_risk(client, project, pm_user_id=7)

    resp = client.patch(
        f"/api/risks/{risk['id']}",
        json={"status": "Closed"},
        headers=_headers(None, "System Admin"),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "Closed"
