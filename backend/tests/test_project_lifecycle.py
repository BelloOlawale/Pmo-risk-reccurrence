"""Project lifecycle status tests.

Project Status (Active / Closed) is the source of truth for the Active Risk
Register. These tests pin the lifecycle and authorization rules so risk-level
state can never masquerade as project-level activity.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _headers(user_id: int | None, role: str) -> dict[str, str]:
    headers = {"X-User-Role": role}
    if user_id is not None:
        headers["X-User-Id"] = str(user_id)
    return headers


def _create_project(
    client: TestClient,
    name: str,
    *,
    user_id: int | None = None,
    role: str = "System Admin",
) -> dict:
    resp = client.post(
        "/api/projects",
        json={"name": name, "department": "D", "project_type": "T", "customer": "C"},
        headers=_headers(user_id, role),
    )
    assert resp.status_code == 201
    return resp.json()


def _active_project_ids(client: TestClient) -> set[int]:
    resp = client.get("/api/projects?status=Active", headers=_headers(None, "System Admin"))
    assert resp.status_code == 200
    return {p["id"] for p in resp.json()}


def test_new_project_defaults_to_active(client: TestClient) -> None:
    project = _create_project(client, "Fresh")
    assert project["status"] == "Active"
    assert project["id"] in _active_project_ids(client)


def test_active_project_with_zero_risks_stays_in_active_register(client: TestClient) -> None:
    project = _create_project(client, "Zero-risk")
    assert project["id"] in _active_project_ids(client)


def test_close_project_records_closure_and_leaves_active_register(client: TestClient) -> None:
    project = _create_project(client, "To Close", user_id=7, role="Project Manager")

    resp = client.post(
        f"/api/projects/{project['id']}/close",
        headers=_headers(7, "Project Manager"),
    )
    assert resp.status_code == 200
    closed = resp.json()
    assert closed["status"] == "Closed"
    assert closed["closed_date"] is not None
    assert closed["closed_by_user_id"] == 7

    assert project["id"] not in _active_project_ids(client)

    # Still available in the full Projects list.
    all_projects = client.get("/api/projects", headers=_headers(None, "System Admin")).json()
    assert any(p["id"] == project["id"] and p["status"] == "Closed" for p in all_projects)


def test_close_project_requires_assigned_project_manager(client: TestClient) -> None:
    project = _create_project(client, "Owned by 1", user_id=1, role="Project Manager")

    resp = client.post(
        f"/api/projects/{project['id']}/close",
        headers=_headers(2, "Project Manager"),
    )
    assert resp.status_code == 403

    # The project remains Active.
    assert project["id"] in _active_project_ids(client)


def test_pmo_lead_cannot_close_another_project(client: TestClient) -> None:
    """Closing is reserved for the assigned Project Manager (not PMO Lead)."""
    project = _create_project(client, "PMO cannot close", user_id=3, role="Project Manager")

    resp = client.post(
        f"/api/projects/{project['id']}/close",
        headers=_headers(None, "PMO Lead"),
    )
    assert resp.status_code == 403

    # The project remains Active.
    assert project["id"] in _active_project_ids(client)


def test_closing_already_closed_project_conflicts(client: TestClient) -> None:
    project = _create_project(client, "Already closed", user_id=4, role="Project Manager")
    assert (
        client.post(
            f"/api/projects/{project['id']}/close",
            headers=_headers(4, "Project Manager"),
        ).status_code
        == 200
    )

    resp = client.post(
        f"/api/projects/{project['id']}/close",
        headers=_headers(4, "Project Manager"),
    )
    assert resp.status_code == 409


def test_adding_risk_to_closed_project_reopens_it(client: TestClient) -> None:
    project = _create_project(client, "Closed reopened", user_id=5, role="Project Manager")
    assert (
        client.post(
            f"/api/projects/{project['id']}/close",
            headers=_headers(5, "Project Manager"),
        ).status_code
        == 200
    )

    risk = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "description": "Added after closure",
            "likelihood": "Low",
            "impact": "Low",
        },
        headers=_headers(None, "System Admin"),
    ).json()
    assert risk["id"] > 0

    # Adding a new risk to a closed register reopens it back to Active.
    assert project["id"] in _active_project_ids(client)
    read_back = client.get(
        f"/api/projects/{project['id']}", headers=_headers(None, "System Admin")
    ).json()
    assert read_back["status"] == "Active"


def test_close_blocked_while_unresolved_risks_exist(client: TestClient) -> None:
    project = _create_project(client, "Unresolved", user_id=8, role="Project Manager")
    client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "description": "Still open",
            "likelihood": "High",
            "impact": "High",
        },
        headers=_headers(8, "Project Manager"),
    )

    resp = client.post(
        f"/api/projects/{project['id']}/close",
        headers=_headers(8, "Project Manager"),
    )
    assert resp.status_code == 409
    assert "unresolved" in resp.json()["detail"].lower()

    # The register remains Active.
    assert project["id"] in _active_project_ids(client)


def test_close_allowed_after_all_risks_resolved(client: TestClient) -> None:
    project = _create_project(client, "All resolved", user_id=9, role="Project Manager")
    risk = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "description": "Resolve me",
            "likelihood": "Low",
            "impact": "Low",
        },
        headers=_headers(9, "Project Manager"),
    ).json()
    assert client.post(f"/api/risks/{risk['id']}/accept").status_code == 200
    assert (
        client.patch(
            f"/api/risks/{risk['id']}",
            json={"status": "Resolved"},
            headers=_headers(9, "Project Manager"),
        ).status_code
        == 200
    )

    resp = client.post(
        f"/api/projects/{project['id']}/close",
        headers=_headers(9, "Project Manager"),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "Closed"
    assert project["id"] not in _active_project_ids(client)


def test_risk_status_does_not_change_project_status(client: TestClient) -> None:
    project = _create_project(client, "Resolve all", user_id=6, role="Project Manager")

    # Create and resolve two risks. The project must remain Active throughout.
    risk_ids: list[int] = []
    for i in range(2):
        risk = client.post(
            "/api/risks",
            json={
                "project_id": project["id"],
                "description": f"risk {i}",
                "likelihood": "Low",
                "impact": "Low",
            },
            headers=_headers(6, "Project Manager"),
        ).json()
        risk_ids.append(risk["id"])
        assert client.post(f"/api/risks/{risk['id']}/accept").status_code == 200
        assert (
            client.patch(
                f"/api/risks/{risk['id']}",
                json={"status": "Resolved"},
                headers=_headers(6, "Project Manager"),
            ).status_code
            == 200
        )

    assert risk_ids
    assert project["id"] in _active_project_ids(client)
    read_back = client.get(
        f"/api/projects/{project['id']}", headers=_headers(None, "System Admin")
    ).json()
    assert read_back["status"] == "Active"
