"""Shared pytest fixtures (in-memory SQLite + dependency-overridden TestClient)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Patch the module-level engine + SessionLocal so code that does
    # `from app.database import SessionLocal` inside a test gets the SQLite
    # version instead of the configured (PostgreSQL) one.
    import app.database as db_mod

    orig_engine = db_mod.engine
    orig_session_local = db_mod.SessionLocal
    db_mod.engine = engine
    db_mod.SessionLocal = TestingSessionLocal

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
    db_mod.engine = orig_engine
    db_mod.SessionLocal = orig_session_local


@pytest.fixture
def db(client):
    """A SQLite session bound to the same in-memory engine as ``client``.

    Use this inside tests that need to operate on the DB directly (instead of
    `from app.database import SessionLocal`, which would point at PostgreSQL).
    """
    from app.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

