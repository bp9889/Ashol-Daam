"""Reads prices the way you see them on Daraz: by opening the page in a hidden browser.

Daraz puts the sale price of each size/option on the page with scripts, after it loads. A plain
download (what the rest of the app does) only sees the regular price. So for the few pages where
that matters, we open them in a real browser: Microsoft Edge or Google Chrome already installed on
the computer (no extra download), or Playwright's own Chromium if neither is there.

Polite by design: only pages we need, at most 3 at a time, images/fonts not downloaded. If Daraz
shows a robot check we stop straight away and never try to get past it.
Turn it off with BROWSER_PRICES=0.

On Vercel (which can't run a browser) set BROWSER_WS_URL to a browser service's address, e.g.
Browserless: wss://production-sfo.browserless.io?token=YOUR_TOKEN
For Browserless the pages are read through its web API (/function): one web request runs the
reading code next to the browser, so no Playwright is needed here and nothing crosses the ocean
per page. Other services (or BROWSER_API=cdp) are driven with Playwright over the address itself.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import re
import threading
import time
from dataclasses import dataclass

from . import config

log = logging.getLogger("asol_dam.browser")

PRICE = ".pdp-price_type_normal"
OLD_PRICE = ".pdp-price_type_deleted"
CHOSEN_OPTION = ".sku-variable-name-selected"
DELIVERY_FEE = ".delivery-option-item__shipping-fee"  # "Free" or "৳ 60" (first = standard delivery)
ROBOT_CHECK = "#nc_1_n1z, .nc-container, #baxia-dialog-content, iframe[src*='punish']"
AT_ONCE = 4
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


@dataclass
class SeenPrice:
    price: float
    original: float | None = None
    option: str | None = None  # the size/option shown as chosen, e.g. "30 ML Spary"
    delivery: float | None = None  # standard delivery fee shown on the page (0 = free); None = not shown


class _State:
    blocked = False  # Daraz showed a robot check: no more browser reads until the server restarts
    broken: str | None = None  # couldn't start any browser
    last_error: str | None = None  # most recent failure, shown on /api/status
    via: str | None = None  # how the last read was done: "web API" or "Playwright"


state = _State()


def _has_playwright() -> bool:
    return importlib.util.find_spec("playwright") is not None


def _web_api() -> str | None:
    """Browserless's /function address (with the token) when the service is Browserless."""
    address = config.BROWSER_WS_URL
    if not address or config.BROWSER_API == "cdp":
        return None
    from urllib.parse import urlparse

    parsed = urlparse(address)
    if not parsed.hostname or (config.BROWSER_API != "web" and not parsed.hostname.endswith("browserless.io")):
        return None
    scheme = "http" if parsed.scheme in ("ws", "http") else "https"
    query = f"{parsed.query}&" if parsed.query else ""
    return f"{scheme}://{parsed.netloc}/function?{query}timeout=45000"


def available() -> bool:
    return (config.BROWSER_PRICES and not state.blocked and not state.broken
            and (_web_api() is not None or _has_playwright()))


def _hide_secrets(text: str) -> str:
    """Error messages can contain the service address; never show or log its token."""
    return re.sub(r"(token=)[^&\s\"']+", r"\1***", text)


def status() -> dict:
    """For /api/status: can this server read prices with a browser right now, and if not, why."""
    if not config.BROWSER_PRICES:
        why = "off (on Vercel, set BROWSER_WS_URL)" if config.ON_VERCEL else "off (BROWSER_PRICES=0)"
    elif _web_api() is None and not _has_playwright():
        why = "Playwright isn't installed"
    elif state.blocked:
        why = "paused: Daraz showed a robot check"
    elif state.broken:
        why = f"couldn't start: {state.broken}"
    else:
        why = None
    # Public, so it never describes the service address or its token (not even its length).
    return {"working": why is None and not state.last_error,
            "uses": "browser service" if config.BROWSER_WS_URL else "this computer's browser",
            "via": state.via or ("web API" if _web_api() else "Playwright"),
            "problem": why, "last_error": state.last_error}


def _describe(address: str) -> dict | None:
    """What the service address looks like, without revealing the token."""
    if not address:
        return None
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(address)
    token = (parse_qs(parsed.query).get("token") or [""])[0]
    return {"address": f"{parsed.scheme}://{parsed.hostname}", "has_token": bool(token),
            "token_length": len(token), "token_ends_with": token[-3:] if len(token) > 12 else None}


def _number(text: str | None) -> float | None:
    match = NUMBER.search(text or "")
    return float(match.group(0).replace(",", "")) if match else None


CACHE_SECONDS = 600  # a page read in the last 10 minutes isn't opened again
_cache: dict[str, tuple[float, SeenPrice]] = {}


SHARED_CACHE_HOURS = 3  # a page any server read this recently (saved in the database) isn't opened again


def _saved_reads(urls: list[str]) -> dict[str, SeenPrice]:
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from .db import SessionLocal
    from .models import PageRead

    since = datetime.now(timezone.utc) - timedelta(hours=SHARED_CACHE_HOURS)
    found = {}
    try:
        with SessionLocal() as session:
            for row in session.scalars(select(PageRead).where(PageRead.url.in_(urls))):
                read_at = row.read_at if row.read_at.tzinfo else row.read_at.replace(tzinfo=timezone.utc)
                if read_at >= since:
                    found[row.url] = SeenPrice(
                        price=float(row.price), option=row.option,
                        original=float(row.original_price) if row.original_price is not None else None,
                        delivery=float(row.delivery) if row.delivery is not None else None)
    except Exception as exc:  # the shared cache is a bonus: never break a check because of it
        log.info("Couldn't read saved page reads: %s", exc)
    return found


def _save_reads(seen: dict[str, SeenPrice]) -> None:
    from .db import SessionLocal
    from .models import PageRead, utcnow

    try:
        with SessionLocal() as session:
            for url, s in seen.items():
                session.merge(PageRead(url=url, price=s.price, original_price=s.original, option=s.option,
                                       delivery=s.delivery, read_at=utcnow()))
            session.commit()
    except Exception as exc:  # e.g. two servers saving the same page at once: fine to skip
        log.info("Couldn't save page reads: %s", exc)


def read_prices(urls: list[str], timeout_s: float = 25, fresh: bool = False) -> dict[str, SeenPrice]:
    """Open each page and read the price shown. Pages that fail are simply missing from the result.
    fresh=True: always open the page (the product being checked itself, so its price is current)."""
    urls = list(dict.fromkeys(u for u in urls if u))
    if not urls or not available():
        return {}
    cached: dict[str, SeenPrice] = {}
    if not fresh:
        now = time.monotonic()
        cached = {u: hit[1] for u in urls if (hit := _cache.get(u)) and now - hit[0] < CACHE_SECONDS}
        cached.update(_saved_reads([u for u in urls if u not in cached]))
    urls = [u for u in urls if u not in cached]
    if not urls:
        return cached
    result: dict[str, SeenPrice] = {}
    if _web_api():
        try:
            result = _read_with_web_api(urls, timeout_s)
            state.via, state.last_error = "web API", None
        except Exception as exc:  # the browser is a bonus: never break a price check because of it
            _note_failure(exc)
            if not _has_playwright():
                return cached
            log.warning("Trying Playwright instead of the web API.")
            result = _read_with_playwright(urls, timeout_s)
    else:
        result = _read_with_playwright(urls, timeout_s)
    for url, seen in result.items():
        _cache[url] = (time.monotonic(), seen)
    if result:
        _save_reads(result)
    return {**cached, **result}


def _note_failure(exc: Exception) -> None:
    first_line = str(exc).splitlines()[0] if str(exc) else ""
    state.last_error = _hide_secrets(f"{type(exc).__name__}: {first_line}")[:300]
    log.warning("Browser price check failed: %s", state.last_error)


def _read_with_playwright(urls: list[str], timeout_s: float) -> dict[str, SeenPrice]:
    result: dict[str, SeenPrice] = {}

    def run() -> None:
        try:
            result.update(asyncio.run(asyncio.wait_for(_read_all(urls), timeout_s + 15)))
            state.via, state.last_error = "Playwright", None
        except Exception as exc:
            _note_failure(exc)

    # Run in a fresh thread so it never clashes with an event loop already running here.
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout_s + 20)
    return dict(result)


# Runs on Browserless, next to the browser (its /function API, with Puppeteer): opens the pages a
# few at a time, blocks pictures and trackers, reads each with READ_PAGE_JS, sends it all back.
WEB_API_CODE = """
export default async function ({ page, context }) {
  const read = %(read)s;
  const browser = page.browser();
  const results = {};
  let robot = false;
  const one = async (url) => {
    if (robot) return;
    const tab = await browser.newPage();
    try {
      try {
        const cdp = tab.createCDPSession ? await tab.createCDPSession() : await tab.target().createCDPSession();
        await cdp.send("Network.enable");
        await cdp.send("Network.setBlockedURLs", { urls: context.blocked });
      } catch (e) {}
      await tab.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
      const found = await tab.evaluate(read, context.selectors);
      if (found && found.robot) robot = true;
      results[url] = found;
    } catch (e) {
      const at = tab.url() || "";
      if (at.toLowerCase().includes("punish")) { robot = true; results[url] = { robot: true }; }
      else results[url] = { error: String((e && e.message) || e).slice(0, 200) };
    } finally {
      await tab.close().catch(() => {});
    }
  };
  const queue = [...context.urls];
  const workers = Array.from({ length: Math.min(context.atOnce, queue.length) }, async () => {
    while (queue.length && !robot) await one(queue.shift());
  });
  await Promise.all(workers);
  return { data: { results, robot }, type: "application/json" };
}
"""


def web_api_request(urls: list[str]) -> dict:
    """The body sent to Browserless's /function: the code above and what it needs."""
    return {"code": WEB_API_CODE % {"read": READ_PAGE_JS.strip()},
            "context": {"urls": urls, "atOnce": AT_ONCE, "blocked": BLOCKED_URLS,
                        "selectors": {"price": PRICE, "old": OLD_PRICE, "chosen": CHOSEN_OPTION,
                                      "fee": DELIVERY_FEE, "robot": ROBOT_CHECK}}}


def seen_from_web_api(body) -> dict[str, SeenPrice]:
    """Browserless's answer as prices. A robot check pauses the browser, as with Playwright.
    Raises (with what came back, never the token) if the answer isn't what our code returns,
    and notes in /api/status why pages couldn't be read."""
    import json

    if isinstance(body, str):  # the JSON sent as text, or something else entirely
        try:
            body = json.loads(body)
        except ValueError:
            raise RuntimeError(_hide_secrets(f"unexpected answer from the browser service: {body[:160]}")) from None
    if isinstance(body, dict) and "results" not in body and isinstance(body.get("data"), (dict, str)):
        body = body["data"] if isinstance(body["data"], dict) else json.loads(body["data"])  # wrapped once more
    if not isinstance(body, dict) or not isinstance(body.get("results"), dict):
        shape = sorted(body)[:8] if isinstance(body, dict) else type(body).__name__
        raise RuntimeError(_hide_secrets(f"unexpected answer from the browser service: {shape} {str(body)[:160]}"))
    if body.get("robot"):
        _robot_seen()
    seen, problems = {}, []
    for url, found in body["results"].items():
        if isinstance(found, dict) and found.get("error"):
            problems.append(_hide_secrets(str(found["error"]))[:160])
            log.info("Couldn't read the price on %s: %s", url, problems[-1])
            continue
        price = _to_seen(found)
        if price:
            seen[url] = price
        elif not (isinstance(found, dict) and found.get("robot")):
            problems.append(f"no price on the page ({str(found)[:100]})")
    if problems and not seen:
        raise RuntimeError(f"web API read none of {len(body['results'])} pages; first problem: {problems[0]}")
    return seen


def _read_with_web_api(urls: list[str], timeout_s: float) -> dict[str, SeenPrice]:
    """One web request to Browserless reads every page. Raises if the service can't be used."""
    import httpx

    response = httpx.post(_web_api(), json=web_api_request(urls), timeout=timeout_s + 20)
    if response.status_code != 200:
        raise RuntimeError(f"the browser service answered {response.status_code}: {response.text[:150]}")
    try:
        body = response.json()
    except ValueError:
        body = response.text  # not JSON: seen_from_web_api says what came back
    return seen_from_web_api(body)


async def _launch(pw):
    if config.BROWSER_WS_URL:
        # A browser rented from an online service (e.g. Browserless), for hosts like Vercel that
        # can't run one themselves. A failure here may be temporary, so we don't give up for good.
        return await pw.chromium.connect_over_cdp(config.BROWSER_WS_URL, timeout=20_000)
    channels = [config.BROWSER_CHANNEL] if config.BROWSER_CHANNEL else ["msedge", "chrome", None]
    errors = []
    for channel in channels:
        try:
            return await pw.chromium.launch(headless=True, channel=channel or None)
        except Exception as exc:
            errors.append(f"{channel or 'chromium'}: {str(exc).splitlines()[0]}")
    state.broken = "; ".join(errors)
    log.warning("Couldn't start a browser to read sale prices (%s). Install Edge or Chrome, or run "
                "`python -m playwright install chromium`.", state.broken)
    raise RuntimeError(state.broken)


# Blocked inside the browser itself (no trip back to us per request, which matters when the browser
# is a service on another continent): pictures, fonts, video, and trackers the price doesn't need.
BLOCKED_URLS = [
    "*.jpg*", "*.jpeg*", "*.png*", "*.webp*", "*.gif*", "*.svg*", "*.ico*", "*.avif*",
    "*.woff*", "*.ttf*", "*.otf*", "*.mp4*", "*.webm*",
    "*google-analytics.com*", "*googletagmanager.com*", "*doubleclick.net*", "*facebook.net*",
    "*facebook.com/tr*", "*mmstat.com*", "*hotjar*", "*clarity.ms*",
]


async def _block_heavy(page) -> None:
    try:
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("Network.enable")
        await cdp.send("Network.setBlockedURLs", {"urls": BLOCKED_URLS})
    except Exception:  # some browsers don't allow it; the page just loads a bit slower
        pass


async def _read_all(urls: list[str]) -> dict[str, SeenPrice]:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await _launch(pw)
        try:
            context = await browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
            gate = asyncio.Semaphore(AT_ONCE)
            seen: dict[str, SeenPrice] = {}

            async def one(url: str) -> None:
                if state.blocked:
                    return
                async with gate:
                    if state.blocked:
                        return
                    page = await context.new_page()
                    try:
                        await _block_heavy(page)
                        found = await _read_page(page, url)
                        if found:
                            seen[url] = found
                    except Exception as exc:
                        log.info("Couldn't read the price on %s: %s", url, _hide_secrets(str(exc).splitlines()[0]))
                    finally:
                        await page.close()

            await asyncio.gather(*(one(u) for u in urls))
            return seen
        finally:
            await browser.close()


# Runs inside the page: waits for the price (or a robot check), then for the delivery box, and
# returns everything at once. One call instead of dozens of small ones, each a trip to the browser.
READ_PAGE_JS = """
async ({price, old, chosen, fee, robot}) => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const text = (el) => (el && el.innerText ? el.innerText.trim() : "");
  const blocked = () => location.href.toLowerCase().includes("punish") || !!document.querySelector(robot);
  let start = Date.now();
  while (!text(document.querySelector(price))) {
    if (blocked()) return { robot: true };
    if (Date.now() - start > 15000) return null;
    await wait(150);
  }
  if (blocked()) return { robot: true };
  window.scrollBy(0, 400);  // in case the delivery box loads when seen
  start = Date.now();
  while (!text(document.querySelector(fee)) && Date.now() - start < 3000) await wait(150);
  return {
    price: text(document.querySelector(price)),
    old: text(document.querySelector(old)),
    options: [...document.querySelectorAll(chosen)].map(text).filter(Boolean),
    fee: text(document.querySelector(fee)),
  };
}
"""


def _robot_seen() -> None:
    state.blocked = True
    log.warning("Daraz showed a robot check. Reading sale prices with the browser is paused "
                "until the server restarts.")


async def _read_page(page, url: str) -> SeenPrice | None:
    await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
    try:
        found = await page.evaluate(READ_PAGE_JS, {"price": PRICE, "old": OLD_PRICE, "chosen": CHOSEN_OPTION,
                                                    "fee": DELIVERY_FEE, "robot": ROBOT_CHECK})
    except Exception:
        # The page went somewhere else while we read it: a robot check, or just a failed read.
        if "punish" in page.url.lower():
            _robot_seen()
            return None
        raise
    if found and found.get("robot"):
        _robot_seen()
        return None
    return _to_seen(found)


def _to_seen(found: dict | None) -> SeenPrice | None:
    """What READ_PAGE_JS read from a page, as numbers."""
    if not found or found.get("robot"):
        return None
    now = _number(found.get("price"))
    if not now:
        return None
    old = _number(found.get("old"))
    option = " / ".join(found.get("options") or []) or None
    fee_text = found.get("fee") or ""
    delivery = (0.0 if "free" in fee_text.lower() else _number(fee_text)) if fee_text else None
    return SeenPrice(price=now, original=old if old and old > now else None, option=option, delivery=delivery)
