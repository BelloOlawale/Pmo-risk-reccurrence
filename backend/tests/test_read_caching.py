"""Read-heavy endpoints are served from a short TTL cache.

The API is latency-bound by round-trips to a database in another region, so
``/api/users`` and ``/api/risk-meta`` are cached. These tests pin the caching
behaviour (and rely on the autouse fixture clearing caches between tests).
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from riskapp import cache, main


def test_users_endpoint_serves_repeat_request_from_cache(
    client: TestClient, monkeypatch
) -> None:
    calls = {"n": 0}
    real = main.list_users

    def counting(db: Session) -> object:
        calls["n"] += 1
        return real(db)

    monkeypatch.setattr(main, "list_users", counting)

    assert client.get("/api/users").status_code == 200
    assert client.get("/api/users").status_code == 200
    assert calls["n"] == 1


def test_risk_meta_endpoint_serves_repeat_request_from_cache(
    client: TestClient, monkeypatch
) -> None:
    calls = {"n": 0}
    real = main._compute_risk_meta

    def counting(db: Session) -> dict[str, object]:
        calls["n"] += 1
        return real(db)

    monkeypatch.setattr(main, "_compute_risk_meta", counting)

    assert client.get("/api/risk-meta").status_code == 200
    assert client.get("/api/risk-meta").status_code == 200
    assert calls["n"] == 1


def test_clearing_caches_forces_a_refetch(client: TestClient, monkeypatch) -> None:
    calls = {"n": 0}
    real = main.list_users

    def counting(db: Session) -> object:
        calls["n"] += 1
        return real(db)

    monkeypatch.setattr(main, "list_users", counting)

    client.get("/api/users")
    cache.clear_caches()
    client.get("/api/users")
    assert calls["n"] == 2
