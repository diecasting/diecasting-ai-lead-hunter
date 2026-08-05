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

    # Force provider-based features into hermetic (dry-run) mode regardless of
    # any real credentials present in a local .env: SMTP -> mock sender, IMAP
    # -> mock inbox, search -> google fallback. The live server process reads
    # .env directly and is unaffected.
    import app.config as config_mod

    cfg = config_mod.settings
    _saved = {
        k: getattr(cfg, k)
        for k in (
            "smtp_host", "smtp_username", "smtp_password", "smtp_from_email",
            "imap_host", "imap_username", "imap_password",
            "search_provider", "serpapi_key",
        )
    }
    cfg.smtp_host = ""
    cfg.smtp_username = ""
    cfg.smtp_password = ""
    cfg.smtp_from_email = ""
    cfg.imap_host = ""
    cfg.imap_username = ""
    cfg.imap_password = ""
    cfg.search_provider = "google"
    cfg.serpapi_key = ""

    # Phase 6.5: isolate the MX resolver so pre-send verification never hits the
    # real network during tests (deterministic + fast). The verifier unit tests
    # inject their own resolver / probe, so they are unaffected.
    import app.outreach.lead_email_verifier as lev_mod

    _saved_resolve_mx = lev_mod.resolve_mx
    lev_mod.resolve_mx = lambda domain, **kw: ["mx.example.com"]

    with TestClient(app) as c:
        yield c

    for k, v in _saved.items():
        setattr(cfg, k, v)
    lev_mod.resolve_mx = _saved_resolve_mx
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

