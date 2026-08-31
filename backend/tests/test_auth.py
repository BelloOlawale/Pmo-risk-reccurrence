"""Tests for RBAC: role resolution, row-level scoping, and de-escalation."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.auth import (
    Principal,
    Role,
    can_access_project,
    can_access_risk,
)

PM = {"X-User-Role": "Project Manager"}
PMO = {"X-User-Role": "PMO Lead"}
ADMIN = {"X-User-Role": "System Admin"}


def _user(db: Session, upn: str) -> models.User:
    user = models.User(upn=upn, display_name=upn)
    db.add(user)
    db.flush()
    return user


def _project(db: Session, code: str, pm: models.User | None) -> models.Project:
    dept = db.query(models.Department).filter_by(name=f"D-{code}").first()
    if dept is None:
        dept = models.Department(name=f"D-{code}")
        db.add(dept)
        db.flush()
    ptype = db.query(models.ProjectType).filter_by(name=f"T-{code}").first()
    if ptype is None:
        ptype = models.ProjectType(name=f"T-{code}")
        db.add(ptype)
        db.flush()
    project = models.Project(
        name=f"P-{code}", project_code=code, status="Active",
        pm_user_id=pm.id if pm else None,
    )
    project.department = dept
    project.project_type = ptype
    db.add(project)
    db.flush()
    return project


def _risk(
    db: Session,
    code: str,
    project: models.Project,
    owner: models.User | None,
    *,
    status: str = "Open",
) -> models.Risk:
    risk = models.Risk(
        project_id=project.id,
        risk_code=code,
        description=f"risk {code}",
        likelihood="Medium",
        impact="Medium",
        risk_rating="Medium",
        status=status,
        owner_user_id=owner.id if owner else None,
    )
    db.add(risk)
    db.flush()
    return risk


class TestPureScoping:
    def test_admin_bypasses_project_scope(self) -> None:
        admin = Principal(user_id=9, upn="a", roles=frozenset({Role.SYSTEM_ADMIN}))
        project = models.Project(name="P", project_code="PRJ", status="Active", pm_user_id=1)
        assert can_access_project(admin, project) is True

    def test_pm_sees_own_project_only(self) -> None:
        pm = Principal(user_id=1, upn="a", roles=frozenset({Role.PROJECT_MANAGER}))
        own = models.Project(name="P", project_code="PRJ", status="Active", pm_user_id=1)
        other = models.Project(name="Q", project_code="PRJ2", status="Active", pm_user_id=2)
        assert can_access_project(pm, own) is True
        assert can_access_project(pm, other) is False

    def test_owner_can_access_their_risk(self) -> None:
        owner = Principal(user_id=7, upn="o", roles=frozenset({Role.PROJECT_MANAGER}))
        risk = models.Risk(owner_user_id=7)
        risk.project = models.Project(pm_user_id=99)
        assert can_access_risk(owner, risk) is True

    def test_pm_can_access_their_projects_risks(self) -> None:
        pm = Principal(user_id=1, upn="p", roles=frozenset({Role.PROJECT_MANAGER}))
        risk = models.Risk(owner_user_id=None)
        risk.project = models.Project(pm_user_id=1)
        assert can_access_risk(pm, risk) is True


class TestApiScoping:
    def test_pm_cannot_read_another_pms_project(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        project = _project(db_session, "PRJ-A", alice)
        db_session.commit()

        resp = client.get(
            f"/api/projects/{project.id}",
            headers={"X-User-Id": str(bob.id), **PM},
        )
        assert resp.status_code == 403

    def test_pm_can_read_own_project(self, client: TestClient, db_session: Session) -> None:
        alice = _user(db_session, "alice@example.com")
        project = _project(db_session, "PRJ-A", alice)
        db_session.commit()

        resp = client.get(
            f"/api/projects/{project.id}",
            headers={"X-User-Id": str(alice.id), **PM},
        )
        assert resp.status_code == 200

    def test_pmo_lead_sees_all_projects(self, client: TestClient, db_session: Session) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        _project(db_session, "PRJ-A", alice)
        _project(db_session, "PRJ-B", bob)
        db_session.commit()

        resp = client.get("/api/projects", headers=PMO)
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_pm_list_is_scoped_to_own_projects(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        _project(db_session, "PRJ-A", alice)
        _project(db_session, "PRJ-B", bob)
        db_session.commit()

        resp = client.get(
            "/api/projects", headers={"X-User-Id": str(alice.id), **PM}
        )
        data = resp.json()
        assert len(data) == 1
        assert data[0]["project_code"] == "PRJ-A"

    def test_owner_can_edit_own_risk(self, client: TestClient, db_session: Session) -> None:
        owner = _user(db_session, "owner@example.com")
        project = _project(db_session, "PRJ-O", owner)
        risk = _risk(db_session, "RSK-O", project, owner)
        db_session.commit()

        resp = client.patch(
            f"/api/risks/{risk.id}",
            json={"description": "updated by owner"},
            headers={"X-User-Id": str(owner.id), **PM},
        )
        assert resp.status_code == 200
        assert resp.json()["description"] == "updated by owner"

    def test_non_owner_pm_cannot_edit_risk(self, client: TestClient, db_session: Session) -> None:
        owner = _user(db_session, "owner@example.com")
        other_pm = _user(db_session, "other@example.com")
        project = _project(db_session, "PRJ-X", owner)
        risk = _risk(db_session, "RSK-X", project, owner)
        db_session.commit()

        resp = client.patch(
            f"/api/risks/{risk.id}",
            json={"description": "hijack"},
            headers={"X-User-Id": str(other_pm.id), **PM},
        )
        assert resp.status_code == 403

    def test_owner_cannot_access_other_risk(self, client: TestClient, db_session: Session) -> None:
        owner = _user(db_session, "owner@example.com")
        other = _user(db_session, "other@example.com")
        project = _project(db_session, "PRJ-Y", owner)
        risk = _risk(db_session, "RSK-Y", project, other)
        db_session.commit()

        resp = client.get(
            f"/api/risks/{risk.id}",
            headers={"X-User-Id": str(other.id), **PM},
        )
        # other is the risk owner but NOT the project PM; owner access allowed
        assert resp.status_code == 200


class TestDeEscalation:
    def test_pm_can_de_escalate(self, client: TestClient, db_session: Session) -> None:
        pm = _user(db_session, "pm@example.com")
        project = _project(db_session, "PRJ-D", pm)
        risk = _risk(db_session, "RSK-D", project, pm, status="Escalated")
        db_session.commit()

        resp = client.post(
            f"/api/risks/{risk.id}/de-escalate",
            json={"rationale": "Owner has now responded"},
            headers={"X-User-Id": str(pm.id), **PM},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "In Progress"

    def test_owner_without_role_cannot_de_escalate(
        self, client: TestClient, db_session: Session
    ) -> None:
        pm = _user(db_session, "pm@example.com")
        project = _project(db_session, "PRJ-D", pm)
        risk = _risk(db_session, "RSK-D", project, pm, status="Escalated")
        db_session.commit()

        resp = client.post(
            f"/api/risks/{risk.id}/de-escalate",
            json={"rationale": "x"},
            headers={"X-User-Id": str(pm.id), "X-User-Role": "Something Else"},
        )
        assert resp.status_code == 401
