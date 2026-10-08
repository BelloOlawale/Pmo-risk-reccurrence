"""System-wide (read-only) Risk History access for Project Managers.

A Project Manager owns their own active risk registers, but the *history* of
closed registers is shared knowledge: every Project Manager (and PMO Lead /
System Admin) can browse all closed registers and the historical risks embedded
in them, no matter who closed them or whether a register ever had a PM (the
imported historical corpus has none).

Mutations stay row-scoped: reading another PM's closed register is allowed, but
editing it is not.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from riskapp import models

PM = {"X-User-Role": "Project Manager"}
PMO = {"X-User-Role": "PMO Lead"}


def _user(db: Session, upn: str) -> models.User:
    user = models.User(upn=upn, display_name=upn)
    db.add(user)
    db.flush()
    return user


def _project(
    db: Session,
    code: str,
    pm: models.User | None,
    *,
    status: str = "Active",
    source: str | None = None,
) -> models.Project:
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
        name=f"P-{code}",
        project_code=code,
        status=status,
        created_source=source,
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
    *,
    status: str = "Closed",
) -> models.Risk:
    risk = models.Risk(
        project_id=project.id,
        risk_code=code,
        description=f"risk {code}",
        likelihood="Medium",
        impact="Medium",
        risk_rating="Medium",
        status=status,
    )
    db.add(risk)
    db.flush()
    return risk


class TestHistoryScopeListing:
    def test_pm_sees_every_closed_register_not_just_their_own(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        alice_closed = _project(db_session, "PRJ-A-CLOSED", alice, status="Closed")
        bob_closed = _project(db_session, "PRJ-B-CLOSED", bob, status="Closed")
        _project(db_session, "PRJ-B-ACTIVE", bob, status="Active")
        db_session.commit()

        resp = client.get(
            "/api/projects?scope=history",
            headers={"X-User-Id": str(alice.id), **PM},
        )
        assert resp.status_code == 200, resp.text
        codes = {p["project_code"] for p in resp.json()}
        assert codes == {alice_closed.project_code, bob_closed.project_code}

    def test_history_scope_hides_other_pms_active_registers(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        _project(db_session, "PRJ-A-CLOSED", alice, status="Closed")
        _project(db_session, "PRJ-B-ACTIVE", bob, status="Active")
        db_session.commit()

        resp = client.get(
            "/api/projects?scope=history",
            headers={"X-User-Id": str(alice.id), **PM},
        )
        codes = {p["project_code"] for p in resp.json()}
        assert "PRJ-B-ACTIVE" not in codes
        assert codes == {"PRJ-A-CLOSED"}

    def test_imported_historical_project_without_a_pm_is_visible(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        _project(
            db_session,
            "PRJ-HIST",
            None,
            status="Closed",
            source="Historical",
        )
        db_session.commit()

        resp = client.get(
            "/api/projects?scope=history",
            headers={"X-User-Id": str(alice.id), **PM},
        )
        assert resp.status_code == 200
        codes = {p["project_code"] for p in resp.json()}
        assert "PRJ-HIST" in codes


class TestReadingAnotherPmsHistory:
    def test_pm_can_open_another_pms_closed_register(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        closed = _project(db_session, "PRJ-B-CLOSED", bob, status="Closed")
        db_session.commit()

        resp = client.get(
            f"/api/projects/{closed.id}",
            headers={"X-User-Id": str(alice.id), **PM},
        )
        assert resp.status_code == 200, resp.text

    def test_pm_can_list_another_pms_closed_register_risks(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        closed = _project(db_session, "PRJ-B-CLOSED", bob, status="Closed")
        _risk(db_session, "RSK-B-1", closed)
        db_session.commit()

        resp = client.get(
            f"/api/projects/{closed.id}/risks",
            headers={"X-User-Id": str(alice.id), **PM},
        )
        assert resp.status_code == 200, resp.text
        assert [r["risk_code"] for r in resp.json()] == ["RSK-B-1"]

    def test_pm_can_read_and_trace_a_risk_in_another_pms_closed_register(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        closed = _project(db_session, "PRJ-B-CLOSED", bob, status="Closed")
        risk = _risk(db_session, "RSK-B-1", closed)
        db_session.commit()

        detail = client.get(
            f"/api/risks/{risk.id}",
            headers={"X-User-Id": str(alice.id), **PM},
        )
        assert detail.status_code == 200, detail.text

        history = client.get(f"/api/risks/{risk.id}/history")
        assert history.status_code == 200

    def test_pm_can_list_issues_of_another_pms_closed_register(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        closed = _project(db_session, "PRJ-B-CLOSED", bob, status="Closed")
        db_session.commit()

        resp = client.get(
            f"/api/projects/{closed.id}/issues",
            headers={"X-User-Id": str(alice.id), **PM},
        )
        assert resp.status_code == 200, resp.text


class TestActiveRegistersStayScoped:
    """The shared history must not widen access to other PMs' live work."""

    def test_pm_cannot_open_another_pms_active_register(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        active = _project(db_session, "PRJ-B-ACTIVE", bob, status="Active")
        db_session.commit()

        resp = client.get(
            f"/api/projects/{active.id}",
            headers={"X-User-Id": str(alice.id), **PM},
        )
        assert resp.status_code == 403

    def test_pm_cannot_read_or_edit_another_pms_active_risk(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        active = _project(db_session, "PRJ-B-ACTIVE", bob, status="Active")
        risk = _risk(db_session, "RSK-B-1", active, status="Open")
        db_session.commit()

        read = client.get(
            f"/api/risks/{risk.id}",
            headers={"X-User-Id": str(alice.id), **PM},
        )
        assert read.status_code == 403

        edit = client.patch(
            f"/api/risks/{risk.id}",
            json={"description": "hijack"},
            headers={"X-User-Id": str(alice.id), **PM},
        )
        assert edit.status_code == 403

    def test_pm_cannot_edit_a_closed_register_risk(
        self, client: TestClient, db_session: Session
    ) -> None:
        alice = _user(db_session, "alice@example.com")
        bob = _user(db_session, "bob@example.com")
        closed = _project(db_session, "PRJ-B-CLOSED", bob, status="Closed")
        risk = _risk(db_session, "RSK-B-1", closed)
        db_session.commit()

        resp = client.patch(
            f"/api/risks/{risk.id}",
            json={"description": "hijack"},
            headers={"X-User-Id": str(alice.id), **PM},
        )
        assert resp.status_code == 403
