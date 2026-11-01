"""Re-check the price of every tracked product.

Run it by hand:        python -m app.collector
It also runs on its own: inside the web server at CHECK_TIMES (app/scheduler.py),
or from GitHub Actions when the site is hosted (.github/workflows/check-prices.yml).
"""

from __future__ import annotations

import random
import threading
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import select

from . import config, telegram
from .adapters import AdapterError, BlockedError
from .db import SessionLocal, init_db
from .models import Product
from .services import recently_checked, refresh


def run(stop: threading.Event | None = None, log: Callable[[str], None] = print) -> dict:
    """Check every product that is due. Returns a small summary for the status page."""
    stop = stop or threading.Event()
    init_db()
    summary = {"started_at": datetime.now(timezone.utc).isoformat(), "due": 0, "checked": 0, "failed": 0, "blocked": False}

    with SessionLocal() as session:
        # Pick up "Start" presses from Telegram first, so brand-new alerts are linked
        # before we send anything (matters when running from GitHub Actions).
        if telegram.enabled() and config.TELEGRAM_MODE == "polling":
            try:
                telegram.process_updates(session, timeout=0)
            except telegram.TelegramError as exc:
                log(f"Telegram: {exc}")

        products = session.scalars(select(Product).where(Product.is_demo.is_(False))).all()
        due = [p for p in products if not recently_checked(p)]
        summary["due"] = len(due)
        log(f"{len(due)} of {len(products)} products are due for a check.")

        for number, product in enumerate(due, start=1):
            if stop.is_set():
                break
            try:
                refresh(session, product, force=True)
                summary["checked"] += 1
                log(f"[{number}/{len(due)}] {product.title[:60]}: {product.snapshots[-1].price}")
            except BlockedError as exc:
                summary["blocked"] = True
                log(f"Stopped: {exc}")
                break  # carrying on would only make the block worse
            except AdapterError as exc:
                summary["failed"] += 1
                log(f"[{number}/{len(due)}] skipped {product.url}: {exc}")
            if number < len(due):
                stop.wait(random.uniform(*config.COLLECTOR_DELAY_RANGE))

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    return summary


if __name__ == "__main__":
    run()
