"""Integration test for the native pgvector search path.

Runs only against a real PostgreSQL database with the pgvector extension.
Set ``RISKAPP_TEST_POSTGRES_URL`` to enable it (e.g. a local Docker Postgres
or an Azure Database for PostgreSQL Flexible Server).

This is the production code path: ``semantic_search`` must issue the pgvector
``<=>`` cosine-distance operator, not the Python fallback.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session, sessionmaker

from riskapp import models
from riskapp.vector_store import semantic_search

URL = os.environ.get("RISKAPP_TEST_POSTGRES_URL")

pytestmark = pytest.mark.skipif(
    not URL,
    reason="set RISKAPP_TEST_POSTGRES_URL to run the pgvector integration test",
)


@pytest.fixture()
def pg_session() -> Session:
    engine = create_engine(URL)
    with engine.begin() as conn:
        conn.execute(sql_text("CREATE EXTENSION IF NOT EXISTS vector"))
    models.Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        models.Base.metadata.drop_all(engine)
        engine.dispose()


def test_semantic_search_uses_pgvector(pg_session: Session) -> None:
    def catalog(description: str, embedding: list[float]) -> None:
        pg_session.add(
            models.RiskCatalog(description=description, embedding=embedding)
        )

    catalog("risk 1", [1.0, 0.0, 0.0])
    catalog("risk 2", [0.9, 0.1, 0.0])
    catalog("risk 3", [0.0, 1.0, 0.0])  # orthogonal → below threshold
    pg_session.commit()

    results = semantic_search(pg_session, [1.0, 0.0, 0.0])
    assert [r.risk_id for r in results] == ["1", "2"]
    assert results[0].similarity == pytest.approx(1.0, abs=1e-6)
