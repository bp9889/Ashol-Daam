"""Runs the price checks automatically while the web server is running.

Times come from CHECK_TIMES (default 10:00 and 22:00) in TIMEZONE (default Asia/Dhaka).
If the server starts after a long gap (say your laptop was off), it checks once right away.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from . import collector, config
from .db import SessionLocal
from .models import Product

log = logging.getLogger("asol_dam.scheduler")

state: dict = {"enabled": False, "running": False, "next_run_at": None, "last_run": None}
_stop = threading.Event()
_thread: threading.Thread | None = None


def parse_times(times: list[str]) -> list[tuple[int, int]]:
    parsed = []
    for t in times:
        hour, _, minute = t.partition(":")
        h, m = int(hour), int(minute or 0)
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError(f"Bad time in CHECK_TIMES: {t!r}")
        parsed.append((h, m))
    return sorted(set(parsed))


def next_run(now: datetime, times: list[str], tz_name: str) -> datetime:
    """The next moment (timezone-aware) that matches one of `times` in `tz_name`."""
    tz = ZoneInfo(tz_name)
    local = now.astimezone(tz)
    for day in range(0, 2):
        date = (local + timedelta(days=day)).date()
        for h, m in parse_times(times):
            candidate = datetime(date.year, date.month, date.day, h, m, tzinfo=tz)
            if candidate > local:
                return candidate
    raise RuntimeError("CHECK_TIMES is empty")


def _last_check_age_hours() -> float | None:
    with SessionLocal() as session:
        last = session.scalar(select(func.max(Product.last_checked_at)).where(Product.is_demo.is_(False)))
    if last is None:
        return None
    last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - last).total_seconds() / 3600


def _run_once(reason: str) -> None:
    state["running"] = True
    log.info("Price check started (%s)", reason)
    try:
        state["last_run"] = collector.run(stop=_stop, log=log.info) | {"reason": reason}
    except Exception:  # never let one bad run kill the scheduler
        log.exception("Price check crashed")
        state["last_run"] = {"reason": reason, "error": True, "finished_at": datetime.now(timezone.utc).isoformat()}
    finally:
        state["running"] = False


def _loop() -> None:
    age = _last_check_age_hours()
    if age is not None and age >= config.CATCH_UP_AFTER_HOURS and not _stop.wait(30):
        _run_once("catch-up after a long gap")

    while not _stop.is_set():
        upcoming = next_run(datetime.now(timezone.utc), config.CHECK_TIMES, config.TIMEZONE)
        state["next_run_at"] = upcoming.isoformat()
        wait = (upcoming - datetime.now(timezone.utc)).total_seconds()
        if _stop.wait(max(wait, 0)):
            break
        _run_once("scheduled")


def start() -> None:
    global _thread
    if not config.SCHEDULER_ENABLED or (_thread and _thread.is_alive()):
        return
    parse_times(config.CHECK_TIMES)  # fail fast on a typo
    _stop.clear()
    state["enabled"] = True
    state["next_run_at"] = next_run(datetime.now(timezone.utc), config.CHECK_TIMES, config.TIMEZONE).isoformat()
    _thread = threading.Thread(target=_loop, name="price-checks", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
