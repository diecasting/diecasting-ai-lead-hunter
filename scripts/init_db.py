"""Initialize the database schema (create_all)."""
from app.database import Base, engine
from app.models import lead  # noqa: F401  (register models on the Base metadata)


def init() -> None:
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Done.")


if __name__ == "__main__":
    init()
