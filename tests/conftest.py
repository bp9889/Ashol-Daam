"""Test settings. These run before any app module is imported."""

import os
from pathlib import Path

TEST_DB = Path(__file__).parent / "test.db"
if TEST_DB.exists():
    TEST_DB.unlink()

# Set TEST_DATABASE_URL to run the tests against PostgreSQL (its tables are wiped first).
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{TEST_DB}"
os.environ["SEED_DEMO_DATA"] = "1"
os.environ["SCHEDULER_ENABLED"] = "0"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["TELEGRAM_BOT_USERNAME"] = "AsolDamTestBot"
os.environ["TELEGRAM_MODE"] = "webhook"  # never start the real polling thread during tests
os.environ["BROWSER_PRICES"] = "0"  # tests that need the hidden browser turn it on themselves


def pytest_sessionstart(session):
    from app.db import Base, engine, init_db

    if os.getenv("TEST_DATABASE_URL"):
        init_db()
        Base.metadata.drop_all(engine)
    init_db()


def pytest_sessionfinish(session, exitstatus):
    from app.db import engine

    engine.dispose()
    if TEST_DB.exists():
        TEST_DB.unlink()
