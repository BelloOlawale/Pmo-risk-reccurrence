"""Database engine, session factory, and FastAPI dependency."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from riskapp.config import settings


def _build_engine() -> Engine:
    """Create the SQLAlchemy engine with connection-health settings.

    The database can live in a different region from the app, so a request that
    has to open a fresh connection pays a large, fixed round-trip cost. Two
    settings keep that off the hot path:

    * ``pool_pre_ping`` transparently replaces a connection the server has
      closed while idle, instead of surfacing a stale-connection error.
    * ``pool_recycle`` retires connections before the server's idle timeout,
      so the pool holds warm connections rather than reconnecting per request.

    ``pool_size``/``max_overflow`` only apply to queue-based pools; SQLite (used
    by the tests) uses a thread-local pool that rejects them.
    """
    kwargs: dict[str, object] = {"future": True, "pool_pre_ping": True}
    if not settings.database_url.startswith("sqlite"):
        kwargs.update(pool_recycle=1800, pool_size=5, max_overflow=10)
    return create_engine(settings.database_url, **kwargs)


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency yielding a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
