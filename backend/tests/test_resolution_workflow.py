"""Risk Owner resolution → PM review → PMO Lead closure workflow.

Covers: owner resolve, PM accept/reject (with reason), notifications, the
persistent (non-expiring) owner link, and revocation on reassignment.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.external import create_acknowledgement_token, decode_acknowledgement_token


def _headers(user_id: int | None = None, role: str = "System Admin") -> dict[str, str]:
    headers = {"X-User-Role": role}
    if user_id is not None:
        headers["X-User-Id"] = str(user_id)
    return headers


def _user(db: Session, upn: str, name: str) -> models.User:
    user = models.User(upn=upn, display_name=name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _project(client: TestClient, pm: models.User) -> dict:
    resp = client.post(
        "/api/projects",
        json={
            "name": "Resolution project",
            "department": "D",
            "project_type": "T",
            "customer": "C",
            "start_date": "2026-10-01",
        },
        headers=_headers(pm.id, "Project Manager"),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _risk(client: TestClient, project: dict, pm: models.User) -> dict:
    resp = client.post(
        "/api/risks",
        json={
            "project_id": project["id"],
            "description": "Risk to resolve",
            "likelihood": "High",
            "impact": "High",
            "risk_start_date": "2026-10-01",
            "risk_end_date": "2026-11-01",
        },
        headers=_headers(pm.id, "Project Manager"),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _external_owner(client: TestClient, email: str = "owner@ext.com") -> dict:
    resp = client.post(
        "/api/external-owners", json={"full_name": "Risk Owner", "email": email}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _assign(client: TestClient, risk: dict, owner: dict, pm: models.User) -> dict:
    resp = client.patch(
        f"/api/risks/{risk['id']}",
        json={"owner_user_id": owner["id"]},
        headers=_headers(pm.id, "Project Manager"),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestOwnerResolve:
    def _setup(self, client: TestClient, db: Session, email: str = "owner@ext.com"):
        pm = _user(db, "pm@wragby.com", "Pat Manager")
        project = _project(client, pm)
        risk = _risk(client, project, pm)
        owner = _external_owner(client, email)
        assigned = _assign(client, risk, owner, pm)
        assert assigned["status"] == "In Progress"
        token = create_acknowledgement_token(owner_user_id=owner["id"], risk_id=risk["id"])
        return pm, project, risk, owner, token

    def test_owner_acknowledges_then_resolves(
        self, client: TestClient, db_session: Session
    ) -> None:
        _pm, _project_, _risk_, _owner, token = self._setup(client, db_session)

        assert client.post(f"/api/external/acknowledge/{token}").status_code == 200
        resolved = client.post(f"/api/external/acknowledge/{token}/resolve")
        assert resolved.status_code == 200, resolved.text
        assert resolved.json()["status"] == "Resolved"

        # The same persistent link now shows the current state.
        view = client.get(f"/api/external/acknowledge/{token}")
        assert view.status_code == 200
        assert view.json()["status"] == "Resolved"

    def test_resolve_is_idempotent(self, client: TestClient, db_session: Session) -> None:
        _pm, _p, _r, _o, token = self._setup(client, db_session)
        assert client.post(f"/api/external/acknowledge/{token}/resolve").status_code == 200
        again = client.post(f"/api/external/acknowledge/{token}/resolve")
        assert again.status_code == 200
        assert again.json()["status"] == "Resolved"

    def test_owner_has_no_close_action(self, client: TestClient, db_session: Session) -> None:
        _pm, _p, _r, _o, token = self._setup(client, db_session)
        # There is deliberately no owner close endpoint.
        assert client.post(f"/api/external/acknowledge/{token}/close").status_code == 404
        assert client.get(f"/api/external/acknowledge/{token}").json()["status"] == "In Progress"

    def test_link_has_no_expiry_claim(self, client: TestClient, db_session: Session) -> None:
        _pm, _p, _r, _o, token = self._setup(client, db_session)
        claims = decode_acknowledgement_token(token)
        assert claims is not None
        assert "exp" not in claims

    def test_resolve_notifies_the_project_manager(
        self, client: TestClient, db_session: Session
    ) -> None:
        pm, _p, _r, _o, token = self._setup(client, db_session)
        client.post(f"/api/external/acknowledge/{token}/resolve")
        rows = db_session.scalars(
            select(models.Notification).where(
                models.Notification.recipient_user_id == pm.id,
                models.Notification.type == "resolution_submitted",
            )
        ).all()
        assert len(rows) == 1


class TestPmReview:
    def _resolved(self, client: TestClient, db: Session, email: str = "owner@ext.com"):
        pm = _user(db, "pm@wragby.com", "Pat Manager")
        project = _project(client, pm)
        risk = _risk(client, project, pm)
        owner = _external_owner(client, email)
        _assign(client, risk, owner, pm)
        token = create_acknowledgement_token(owner_user_id=owner["id"], risk_id=risk["id"])
        client.post(f"/api/external/acknowledge/{token}/resolve")
        return pm, project, risk, owner, token

    def test_pm_accept_keeps_resolved(self, client: TestClient, db_session: Session) -> None:
        pm, _p, risk, _o, _t = self._resolved(client, db_session)
        resp = client.post(
            f"/api/risks/{risk['id']}/resolution/accept",
            headers=_headers(pm.id, "Project Manager"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "Resolved"
        history = client.get(f"/api/risks/{risk['id']}/history").json()
        assert any(h["action"] == "resolution_accepted" for h in history)

    def test_pm_reject_returns_to_in_progress_with_reason(
        self, client: TestClient, db_session: Session
    ) -> None:
        pm, _p, risk, owner, token = self._resolved(client, db_session)
        resp = client.post(
            f"/api/risks/{risk['id']}/resolution/reject",
            json={"reason": "Mitigation is incomplete."},
            headers=_headers(pm.id, "Project Manager"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "In Progress"

        # Reason is recorded and surfaced to the owner's link.
        history = client.get(f"/api/risks/{risk['id']}/history").json()
        rejected = [h for h in history if h["action"] == "resolution_rejected"]
        assert rejected and rejected[-1]["new_value"] == "Mitigation is incomplete."
        view = client.get(f"/api/external/acknowledge/{token}").json()
        assert view["resolution_rejected_reason"] == "Mitigation is incomplete."
        assert view["status"] == "In Progress"

        # The owner receives a rejection notification in-app.
        rows = db_session.scalars(
            select(models.Notification).where(
                models.Notification.recipient_user_id == owner["id"],
                models.Notification.type == "resolution_rejected",
            )
        ).all()
        assert len(rows) == 1

    def test_owner_can_resolve_again_after_rejection(
        self, client: TestClient, db_session: Session
    ) -> None:
        pm, _p, risk, _o, token = self._resolved(client, db_session)
        client.post(
            f"/api/risks/{risk['id']}/resolution/reject",
            json={"reason": "Try again."},
            headers=_headers(pm.id, "Project Manager"),
        )
        again = client.post(f"/api/external/acknowledge/{token}/resolve")
        assert again.status_code == 200
        assert again.json()["status"] == "Resolved"
        # After re-submission the stale rejection reason is no longer shown.
        assert again.json()["resolution_rejected_reason"] is None

    def test_reason_is_required(self, client: TestClient, db_session: Session) -> None:
        pm, _p, risk, _o, _t = self._resolved(client, db_session)
        resp = client.post(
            f"/api/risks/{risk['id']}/resolution/reject",
            json={"reason": ""},
            headers=_headers(pm.id, "Project Manager"),
        )
        assert resp.status_code == 422

    def test_unrelated_pm_cannot_review(self, client: TestClient, db_session: Session) -> None:
        _pm, _p, risk, _o, _t = self._resolved(client, db_session)
        other = _user(db_session, "other@wragby.com", "Other PM")
        resp = client.post(
            f"/api/risks/{risk['id']}/resolution/reject",
            json={"reason": "No."},
            headers=_headers(other.id, "Project Manager"),
        )
        assert resp.status_code == 403


class TestLinkRevocation:
    def test_reassigning_the_risk_revokes_the_previous_owner_link(
        self, client: TestClient, db_session: Session
    ) -> None:
        pm = _user(db_session, "pm@wragby.com", "Pat Manager")
        project = _project(client, pm)
        risk = _risk(client, project, pm)
        owner_a = _external_owner(client, "owner.a@ext.com")
        _assign(client, risk, owner_a, pm)
        token_a = create_acknowledgement_token(owner_user_id=owner_a["id"], risk_id=risk["id"])
        assert client.get(f"/api/external/acknowledge/{token_a}").status_code == 200

        owner_b = _external_owner(client, "owner.b@ext.com")
        _assign(client, risk, owner_b, pm)

        # Owner A's link is now revoked; Owner B gets a working link.
        assert client.get(f"/api/external/acknowledge/{token_a}").status_code == 404
        token_b = create_acknowledgement_token(owner_user_id=owner_b["id"], risk_id=risk["id"])
        assert client.get(f"/api/external/acknowledge/{token_b}").status_code == 200
