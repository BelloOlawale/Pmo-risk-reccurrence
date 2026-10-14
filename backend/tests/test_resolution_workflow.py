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

# Resolution Summary used across the resolution tests.
_SUMMARY = "Mitigated and monitored."


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
        resolved = client.post(f"/api/external/acknowledge/{token}/resolve",
            json={"resolution_summary": _SUMMARY})
        assert resolved.status_code == 200, resolved.text
        # The owner's proposal is not final: it awaits the Project Manager.
        assert resolved.json()["status"] == "Pending Resolution"

        # The same persistent link now shows the current state.
        view = client.get(f"/api/external/acknowledge/{token}")
        assert view.status_code == 200
        assert view.json()["status"] == "Pending Resolution"

    def test_resolve_is_idempotent(self, client: TestClient, db_session: Session) -> None:
        _pm, _p, _r, _o, token = self._setup(client, db_session)
        assert client.post(f"/api/external/acknowledge/{token}/resolve",
            json={"resolution_summary": _SUMMARY}).status_code == 200
        again = client.post(f"/api/external/acknowledge/{token}/resolve",
            json={"resolution_summary": _SUMMARY})
        assert again.status_code == 200
        assert again.json()["status"] == "Pending Resolution"

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
        client.post(f"/api/external/acknowledge/{token}/resolve",
            json={"resolution_summary": _SUMMARY})
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
        client.post(f"/api/external/acknowledge/{token}/resolve",
            json={"resolution_summary": _SUMMARY})
        return pm, project, risk, owner, token

    def test_pm_accept_marks_resolved(self, client: TestClient, db_session: Session) -> None:
        pm, _p, risk, _o, _t = self._resolved(client, db_session)
        resp = client.post(
            f"/api/risks/{risk['id']}/resolution/accept",
            headers=_headers(pm.id, "Project Manager"),
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "Resolved"
        history = client.get(f"/api/risks/{risk['id']}/history").json()
        assert any(h["action"] == "resolution_accepted" for h in history)

    def test_review_is_no_longer_possible_after_accept(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Once accepted the risk is Resolved, so accept/reject stop applying."""
        pm, _p, risk, _o, _t = self._resolved(client, db_session)
        client.post(
            f"/api/risks/{risk['id']}/resolution/accept",
            headers=_headers(pm.id, "Project Manager"),
        )

        # Accepting again is rejected: there is nothing left to review.
        again = client.post(
            f"/api/risks/{risk['id']}/resolution/accept",
            headers=_headers(pm.id, "Project Manager"),
        )
        assert again.status_code == 422
        # Rejecting an accepted resolution is also rejected.
        reject = client.post(
            f"/api/risks/{risk['id']}/resolution/reject",
            json={"reason": "Too late."},
            headers=_headers(pm.id, "Project Manager"),
        )
        assert reject.status_code == 422
        # The risk stays Resolved throughout.
        current = client.get(
            f"/api/risks/{risk['id']}", headers=_headers(pm.id, "Project Manager")
        )
        assert current.json()["status"] == "Resolved"

    def test_reject_after_accept_uses_the_transition_not_a_status_guard(
        self, client: TestClient, db_session: Session
    ) -> None:
        """The reject endpoint relies on the transition engine, not a bespoke
        "only a ... can be rejected" status guard, so the guard message is gone."""
        pm, _p, risk, _o, _t = self._resolved(client, db_session)
        client.post(
            f"/api/risks/{risk['id']}/resolution/accept",
            headers=_headers(pm.id, "Project Manager"),
        )
        reject = client.post(
            f"/api/risks/{risk['id']}/resolution/reject",
            json={"reason": "Too late."},
            headers=_headers(pm.id, "Project Manager"),
        )
        assert reject.status_code == 422
        assert reject.json()["detail"] == "Cannot transition from Resolved to In Progress"

    def test_pm_can_see_the_resolution_history(
        self, client: TestClient, db_session: Session
    ) -> None:
        """The project manager can read the full audit trail for their risk."""
        pm, _p, risk, _o, _t = self._resolved(client, db_session)
        resp = client.get(
            f"/api/risks/{risk['id']}/history",
            headers=_headers(pm.id, "Project Manager"),
        )
        assert resp.status_code == 200, resp.text
        actions = [entry["action"] for entry in resp.json()]
        assert "resolution_submitted" in actions

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
        again = client.post(f"/api/external/acknowledge/{token}/resolve",
            json={"resolution_summary": _SUMMARY})
        assert again.status_code == 200
        assert again.json()["status"] == "Pending Resolution"
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


class TestResolutionSummary:
    """The Resolution Summary is mandatory and auditable."""

    def _assigned(self, client: TestClient, db: Session, email: str = "sum@ext.com"):
        pm = _user(db, f"pm-{email}", "Pat Manager")
        project = _project(client, pm)
        risk = _risk(client, project, pm)
        owner = _external_owner(client, email)
        _assign(client, risk, owner, pm)
        token = create_acknowledgement_token(owner_user_id=owner["id"], risk_id=risk["id"])
        return pm, risk, owner, token

    def test_empty_summary_is_rejected_on_the_api(
        self, client: TestClient, db_session: Session
    ) -> None:
        _pm, risk, _owner, token = self._assigned(client, db_session)
        resp = client.post(
            f"/api/external/acknowledge/{token}/resolve",
            json={"resolution_summary": "   "},
        )
        assert resp.status_code == 422
        assert "Resolution Summary" in resp.json()["detail"]
        # The risk stays in its current status until a summary is supplied.
        view = client.get(f"/api/external/acknowledge/{token}").json()
        assert view["status"] == "In Progress"
        assert view["resolution_summary"] is None

    def test_missing_summary_is_rejected_on_the_api(
        self, client: TestClient, db_session: Session
    ) -> None:
        _pm, _risk_, _owner, token = self._assigned(client, db_session)
        resp = client.post(f"/api/external/acknowledge/{token}/resolve")
        assert resp.status_code == 422
        assert "Resolution Summary" in resp.json()["detail"]

    def test_summary_is_saved_and_visible_to_the_project_manager(
        self, client: TestClient, db_session: Session
    ) -> None:
        pm, risk, _owner, token = self._assigned(client, db_session)
        summary = "Replaced the failing interface and added a nightly reconciliation job."
        resp = client.post(
            f"/api/external/acknowledge/{token}/resolve",
            json={"resolution_summary": summary},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["resolution_summary"] == summary
        assert resp.json()["status"] == "Pending Resolution"

        seen = client.get(
            f"/api/risks/{risk['id']}", headers=_headers(pm.id, "Project Manager")
        ).json()
        assert seen["resolution_summary"] == summary
        history = client.get(f"/api/risks/{risk['id']}/history").json()
        assert any(
            h["action"] == "resolution_summary_updated" and h["new_value"] == summary
            for h in history
        )

    def test_resubmission_retains_the_previous_summary_in_history(
        self, client: TestClient, db_session: Session
    ) -> None:
        pm, risk, _owner, token = self._assigned(client, db_session)
        first = "First attempt at a fix."
        second = "Second, more thorough fix."
        client.post(
            f"/api/external/acknowledge/{token}/resolve",
            json={"resolution_summary": first},
        )
        client.post(
            f"/api/risks/{risk['id']}/resolution/reject",
            json={"reason": "Not sufficient."},
            headers=_headers(pm.id, "Project Manager"),
        )
        resubmitted = client.post(
            f"/api/external/acknowledge/{token}/resolve",
            json={"resolution_summary": second},
        )
        assert resubmitted.status_code == 200
        assert resubmitted.json()["resolution_summary"] == second

        history = client.get(
            f"/api/risks/{risk['id']}/history",
            headers=_headers(pm.id, "Project Manager"),
        ).json()
        updates = [h for h in history if h["action"] == "resolution_summary_updated"]
        assert len(updates) == 2
        # The first submission is preserved as the old_value of the second.
        assert updates[0]["new_value"] == first
        assert updates[1]["old_value"] == first
        assert updates[1]["new_value"] == second

    def test_pm_cannot_accept_a_resolution_without_a_summary(
        self, client: TestClient, db_session: Session
    ) -> None:
        """Defence in depth: no risk reaches Resolved without a summary."""
        pm, risk, _owner, _token = self._assigned(client, db_session)
        # Force the status to Pending Resolution on the record directly, without
        # a summary, to prove the accept path is guarded independently of the
        # submission path.
        row = db_session.get(models.Risk, risk["id"])
        assert row is not None
        row.status = "Pending Resolution"
        row.resolution_summary = None
        db_session.commit()

        resp = client.post(
            f"/api/risks/{risk['id']}/resolution/accept",
            headers=_headers(pm.id, "Project Manager"),
        )
        assert resp.status_code == 422
        assert "Resolution Summary" in resp.json()["detail"]
