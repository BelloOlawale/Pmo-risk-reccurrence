"""External Risk Owners: creation, dedup, assignment, acknowledgement, workflow."""

from __future__ import annotations

import datetime as dt

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from riskapp import models
from riskapp.domain.status import RiskStatus
from riskapp.external import create_acknowledgement_token


def _project(client: TestClient, name: str = "P") -> dict:
    resp = client.post(
        "/api/projects",
        json={"name": name, "department": "D", "project_type": "T", "customer": "C"},
    )
    assert resp.status_code == 201
    return resp.json()


def _risk(client: TestClient, project_id: int) -> dict:
    resp = client.post(
        "/api/risks",
        json={
            "project_id": project_id,
            "description": "Risk",
            "likelihood": "High",
            "impact": "High",
            "risk_start_date": dt.date.today().isoformat(),
            "risk_end_date": (dt.date.today() + dt.timedelta(days=3)).isoformat(),
        },
    )
    assert resp.status_code == 201
    return resp.json()


def _external_owner(
    client: TestClient,
    *,
    name: str = "Jane Smith",
    email: str = "jane.smith@abc.com",
    organization: str = "ABC Consulting",
) -> dict:
    resp = client.post(
        "/api/external-owners",
        json={"full_name": name, "email": email, "organization": organization},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestCreateExternalOwner:
    def test_creates_an_external_owner(self, client: TestClient) -> None:
        owner = _external_owner(client)
        assert owner["owner_type"] == "External"
        assert owner["display_name"] == "Jane Smith"
        assert owner["upn"] == "jane.smith@abc.com"
        assert owner["organization"] == "ABC Consulting"
        assert owner["is_active"] is True

    def test_duplicate_email_returns_existing_owner(self, client: TestClient) -> None:
        first = _external_owner(client)
        second = _external_owner(client, name="Jane S", email="JANE.SMITH@ABC.COM")
        assert second["id"] == first["id"]

    def test_invalid_email_is_rejected(self, client: TestClient) -> None:
        resp = client.post(
            "/api/external-owners",
            json={"full_name": "Bad", "email": "not-an-email"},
        )
        assert resp.status_code == 422

    def test_email_belonging_to_internal_user_is_rejected(
        self, client: TestClient, db_session: Session
    ) -> None:
        db_session.add(models.User(upn="internal@wragby.com", display_name="Internal"))
        db_session.commit()
        resp = client.post(
            "/api/external-owners",
            json={"full_name": "Same", "email": "internal@wragby.com"},
        )
        assert resp.status_code == 409

    def test_appears_in_owner_directory(self, client: TestClient) -> None:
        owner = _external_owner(client)
        users = client.get("/api/users").json()
        match = next(u for u in users if u["id"] == owner["id"])
        assert match["owner_type"] == "External"

    def test_external_owner_cannot_be_granted_app_access(
        self, client: TestClient
    ) -> None:
        owner = _external_owner(client)
        resp = client.post(
            f"/api/users/{owner['id']}/credentials",
            json={"password": "supersecret1", "role": "System Admin"},
        )
        assert resp.status_code == 409


class TestExternalOwnerAssignment:
    def test_assignment_moves_risk_to_in_progress_and_exposes_owner_type(
        self, client: TestClient
    ) -> None:
        project = _project(client)
        risk = _risk(client, project["id"])
        owner = _external_owner(client)

        resp = client.patch(
            f"/api/risks/{risk['id']}", json={"owner_user_id": owner["id"]}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == RiskStatus.IN_PROGRESS.value
        assert body["owner_type"] == "External"
        assert body["owner_name"] == "Jane Smith"
        assert body["owner_email"] == "jane.smith@abc.com"


class TestExternalAcknowledgement:
    def _assigned(self, client: TestClient) -> tuple[dict, dict]:
        project = _project(client)
        risk = _risk(client, project["id"])
        owner = _external_owner(client)
        client.patch(f"/api/risks/{risk['id']}", json={"owner_user_id": owner["id"]})
        return risk, owner

    def test_public_view_and_acknowledge(self, client: TestClient) -> None:
        risk, owner = self._assigned(client)
        token = create_acknowledgement_token(owner_user_id=owner["id"], risk_id=risk["id"])

        view = client.get(f"/api/external/acknowledge/{token}")
        assert view.status_code == 200
        body = view.json()
        assert body["risk_code"] == risk["risk_code"]
        assert body["owner_email"] == "jane.smith@abc.com"
        assert body["acknowledged"] is False

        ack = client.post(f"/api/external/acknowledge/{token}")
        assert ack.status_code == 200
        acked = ack.json()
        assert acked["acknowledged"] is True
        assert acked["acknowledged_at"] is not None

        # Idempotent: a second acknowledgement is a no-op success.
        again = client.post(f"/api/external/acknowledge/{token}")
        assert again.status_code == 200
        assert again.json()["acknowledged"] is True

    def test_acknowledgement_is_persisted(self, client: TestClient) -> None:
        risk, owner = self._assigned(client)
        token = create_acknowledgement_token(owner_user_id=owner["id"], risk_id=risk["id"])
        client.post(f"/api/external/acknowledge/{token}")

        stored = client.get(f"/api/risks/{risk['id']}").json()
        assert stored["sla_acknowledged"] is True
        assert stored["acknowledged_at"] is not None

    def test_token_for_another_owner_is_rejected(self, client: TestClient) -> None:
        risk, _owner = self._assigned(client)
        other = _external_owner(client, name="Other", email="other@abc.com")
        token = create_acknowledgement_token(owner_user_id=other["id"], risk_id=risk["id"])
        assert client.get(f"/api/external/acknowledge/{token}").status_code == 404

    def test_garbage_token_is_rejected(self, client: TestClient) -> None:
        assert client.get("/api/external/acknowledge/not-a-token").status_code == 404

    def test_internal_owner_has_no_acknowledgement_link(
        self, client: TestClient, db_session: Session
    ) -> None:
        from riskapp.external import acknowledgement_url

        project = _project(client)
        risk = _risk(client, project["id"])
        owner = models.User(upn="i@wragby.com", display_name="Internal")
        db_session.add(owner)
        db_session.commit()
        client.patch(f"/api/risks/{risk['id']}", json={"owner_user_id": owner.id})

        stored = db_session.get(models.Risk, risk["id"])
        assert stored is not None
        assert acknowledgement_url(stored) is None


class TestExternalOwnerWorkflow:
    def test_unacknowledged_external_owner_escalates_on_sla_breach(
        self, client: TestClient, db_session: Session
    ) -> None:
        from riskapp.notifications import NotificationService
        from riskapp.scheduler import run_sla_monitor

        project = _project(client)
        risk = _risk(client, project["id"])
        owner = _external_owner(client)
        client.patch(f"/api/risks/{risk['id']}", json={"owner_user_id": owner["id"]})

        stored = db_session.get(models.Risk, risk["id"])
        assert stored is not None
        # Move the deadline into the past and run the monitor.
        stored.sla_deadline = dt.datetime.now(dt.UTC).replace(tzinfo=None) - dt.timedelta(hours=1)
        db_session.commit()

        run_sla_monitor(
            db_session,
            NotificationService(),
            dt.datetime.now(dt.UTC).replace(tzinfo=None),
        )
        db_session.refresh(stored)
        assert stored.status == RiskStatus.ESCALATED.value
        issue = db_session.query(models.Issue).filter_by(source_risk_id=stored.id).one()
        assert issue is not None

    def test_acknowledged_external_owner_materializes_after_end_date(
        self, client: TestClient, db_session: Session
    ) -> None:
        from riskapp.notifications import NotificationService
        from riskapp.scheduler import run_end_date_monitor

        project = _project(client)
        risk = _risk(client, project["id"])
        owner = _external_owner(client)
        client.patch(f"/api/risks/{risk['id']}", json={"owner_user_id": owner["id"]})

        stored = db_session.get(models.Risk, risk["id"])
        assert stored is not None
        stored.sla_acknowledged = True
        stored.risk_end_date = dt.date.today() - dt.timedelta(days=1)
        db_session.commit()

        run_end_date_monitor(
            db_session, NotificationService(), dt.date.today()
        )
        db_session.refresh(stored)
        assert stored.status == RiskStatus.EVENT.value
