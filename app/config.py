import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # python-dotenv is optional
    pass

BASE_DIR = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# Running on Vercel? Its servers start and stop on demand and can't keep files, so there:
# the database must be Postgres (Neon), checks run from GitHub Actions, and no hidden browser.
ON_VERCEL = _env("VERCEL") == "1"

DATABASE_URL = (_env("DATABASE_URL") or _env("POSTGRES_URL")  # POSTGRES_URL: set by Vercel's Neon integration
                or (f"sqlite:////tmp/asol_dam.db" if ON_VERCEL else f"sqlite:///{BASE_DIR / 'asol_dam.db'}"))
# Hosts like Render/Neon hand out "postgres://..." URLs; SQLAlchemy wants the driver named.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgres://"):]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[len("postgresql://"):]

MIN_REFRESH_HOURS = float(_env("MIN_REFRESH_HOURS", "6"))
# How often to re-compare a product with other sellers (one Daraz search each time).
MARKET_REFRESH_HOURS = float(_env("MARKET_REFRESH_HOURS", "24"))
SEED_DEMO_DATA = _env("SEED_DEMO_DATA", "1") == "1"

# Read sale prices of sizes/options by opening the page in a hidden browser (Edge/Chrome).
# Daraz adds those prices with scripts, so plain downloads only see the regular price.
BROWSER_PRICES = _env("BROWSER_PRICES", "0" if ON_VERCEL else "1") == "1"
BROWSER_CHANNEL = _env("BROWSER_CHANNEL")  # "msedge", "chrome", or empty = try Edge, Chrome, then Chromium

# Polite delay range (seconds) between requests when the collector refreshes many products.
COLLECTOR_DELAY_RANGE = (4.0, 9.0)

# ---- Phase 2: automatic checks ----
# Run the price checks inside the web server at these local times (24h clock, comma separated).
SCHEDULER_ENABLED = _env("SCHEDULER_ENABLED", "0" if ON_VERCEL else "1") == "1"
CHECK_TIMES = [t.strip() for t in _env("CHECK_TIMES", "10:00,22:00").split(",") if t.strip()]
TIMEZONE = _env("TIMEZONE", "Asia/Dhaka")
# If the server starts and the last check is older than this, check right away (laptop was off).
CATCH_UP_AFTER_HOURS = float(_env("CATCH_UP_AFTER_HOURS", "20"))

# ---- Phase 2: Telegram alerts ----
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_BOT_USERNAME = _env("TELEGRAM_BOT_USERNAME").lstrip("@")
# "polling" (default, works on a laptop) or "webhook" (for a hosted site, see DEPLOY.md)
TELEGRAM_MODE = _env("TELEGRAM_MODE", "webhook" if ON_VERCEL else "polling")
TELEGRAM_WEBHOOK_SECRET = _env("TELEGRAM_WEBHOOK_SECRET")
