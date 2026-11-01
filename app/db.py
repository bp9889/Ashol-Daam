from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
# pool_pre_ping: hosted Postgres (Neon) closes idle connections; check before reusing one.
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_session():
    """FastAPI dependency: one session per request."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# Columns added after the first release. create_all() makes new tables but never changes
# existing ones, so older databases get these added here (works on SQLite and PostgreSQL).
ADDED_COLUMNS = {
    "products": {"variant": "VARCHAR(160)", "delivery": "NUMERIC(10,2)"},
    "market_checks": {"detailed": "BOOLEAN DEFAULT FALSE"},
}


def init_db():
    from . import models  # noqa: F401  (registers the tables)

    Base.metadata.create_all(engine)
    existing = inspect(engine)
    with engine.begin() as conn:
        for table, columns in ADDED_COLUMNS.items():
            have = {c["name"] for c in existing.get_columns(table)}
            for name, sql_type in columns.items():
                if name not in have:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}"))
