"""SQLAlchemy engine, session factory and declarative base."""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# PostgreSQL does not need special connect args; SQLite (tests) does.
connect_args = {}
if settings.sqlalchemy_database_uri.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(settings.sqlalchemy_database_uri, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
