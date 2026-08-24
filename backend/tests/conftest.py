"""Shared pytest fixtures: in-memory SQLite session and TestClient."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from riskapp import models
from riskapp.config import settings
from riskapp.db import get_db
from riskapp.main import app


@pytest.fixture(autouse=True)
def _force_dev_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the API in dev (header-based) auth mode, independent of local .env.

    Keeps the suite green even when Entra credentials are present in .env.
    """
    monkeypatch.setattr(settings, "entra_tenant_id", "")
    monkeypatch.setattr(settings, "entra_client_id", "")


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
