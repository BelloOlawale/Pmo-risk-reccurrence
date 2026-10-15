"""Shared pytest fixtures: in-memory SQLite session and TestClient."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from riskapp import models
from riskapp.cache import clear_caches
from riskapp.config import settings
from riskapp.db import get_db
from riskapp.main import app


@pytest.fixture(autouse=True)
def _force_test_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the API in header-based auth mode, independent of local .env.

    Enables the explicit ``allow_header_auth`` opt-in the test suite relies on
    and blanks Entra credentials so no test ever performs live token validation.
    Also blanks the Blob/Azure OpenAI config so no test calls live Azure.
    """
    monkeypatch.setattr(settings, "entra_tenant_id", "")
    monkeypatch.setattr(settings, "entra_client_id", "")
    monkeypatch.setattr(settings, "allow_header_auth", True)
    # Local sign-in is enabled in some developer .env files; default the flag
    # off so the "disabled" tests stay deterministic (test_local_login enables
    # it explicitly via the password_login_on fixture). A fixed test signing key
    # is always set so acknowledgement tokens can be minted without relying on
    # a production secret.
    monkeypatch.setattr(settings, "local_login_enabled", False)
    monkeypatch.setattr(settings, "local_login_secret", "test-signing-key-000000000000000000")
    monkeypatch.setattr(settings, "blob_account_name", "")
    monkeypatch.setattr(settings, "blob_account_key", "")
    monkeypatch.setattr(settings, "blob_container", "")
    # ACS: blank so build_notification_service() never attempts a real send.
    monkeypatch.setattr(settings, "acs_endpoint", "")
    monkeypatch.setattr(settings, "acs_access_key", "")
    monkeypatch.setattr(settings, "acs_sender_email", "")


@pytest.fixture(autouse=True)
def _clear_api_caches() -> Iterator[None]:
    """Start each test with empty in-process caches (no cross-test leakage)."""
    clear_caches()
    yield
    clear_caches()


@pytest.fixture()
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session: Session) -> Iterator[TestClient]:
    def override_get_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
