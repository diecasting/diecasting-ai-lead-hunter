"""Initialise the database schema.

Production uses Alembic migrations (``alembic upgrade head``) so the schema is
versioned. This script runs the migration when Alembic is available and falls
back to ``Base.metadata.create_all`` (handy for a quick local SQLite checkout).
"""
from app.database import Base, engine


def init() -> None:
    try:
        from alembic import command
        from alembic.config import Config

        print("Running Alembic migrations (upgrade head)...")
        cfg = Config("alembic.ini")
        command.upgrade(cfg, "head")
        print("Migrations applied.")
    except Exception as exc:  # pragma: no cover - depends on DB / alembic install
        print(f"[init_db] Alembic unavailable ({exc}); falling back to create_all.")
        print("Creating database tables...")
        Base.metadata.create_all(bind=engine)
        print("Done.")


if __name__ == "__main__":
    init()
