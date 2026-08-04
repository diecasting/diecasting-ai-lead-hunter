"""Alembic migration test: `upgrade head` must create all four tables.

Runs against a throwaway SQLite database (no PostgreSQL required) so it can run
in CI / local dev. The database URL is injected into the Alembic env via the
shared ``app.config.settings`` object.
"""
import os

from sqlalchemy import create_engine, inspect


def test_alembic_upgrade_creates_tables(tmp_path, monkeypatch):
    db_path = tmp_path / "migrated.db"
    db_url = f"sqlite:///{db_path}"

    import app.config as config_mod

    monkeypatch.setattr(config_mod.settings, "database_url", db_url)

    from alembic import command
    from alembic.config import Config

    # Point Alembic at this project's migrations directory.
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(repo_root, "alembic.ini"))

    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected = {"company_leads", "search_results", "crawl_tasks", "ai_analysis"}
    assert expected.issubset(tables), f"missing tables: {expected - tables}"

    # A simple ORM insert/select round-trip proves the schema is usable.
    from sqlalchemy.orm import Session

    from app.models.lead import CompanyLead

    with Session(engine) as session:
        session.add(
            CompanyLead(name="Test Co", crawl_status="pending", pages_crawled=0)
        )
        session.commit()
        row = session.query(CompanyLead).first()
        assert row is not None
        assert row.name == "Test Co"
