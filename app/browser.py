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
SKIP = {"image", "font", "media"}
AT_ONCE = 3
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


state = _State()


def available() -> bool:
    return (config.BROWSER_PRICES and not state.blocked and not state.broken
            and importlib.util.find_spec("playwright") is not None)


def _number(text: str | None) -> float | None:
    match = NUMBER.search(text or "")
    return float(match.group(0).replace(",", "")) if match else None


CACHE_SECONDS = 600  # a page read in the last 10 minutes isn't opened again
_cache: dict[str, tuple[float, SeenPrice]] = {}


def read_prices(urls: list[str], timeout_s: float = 25) -> dict[str, SeenPrice]:
    """Open each page and read the price shown. Pages that fail are simply missing from the result."""
    urls = list(dict.fromkeys(u for u in urls if u))
    if not urls or not available():
        return {}
    now = time.monotonic()
    cached = {u: hit[1] for u in urls if (hit := _cache.get(u)) and now - hit[0] < CACHE_SECONDS}
    urls = [u for u in urls if u not in cached]
    if not urls:
        return cached
    result: dict[str, SeenPrice] = {}

    def run() -> None:
        try:
            result.update(asyncio.run(asyncio.wait_for(_read_all(urls), timeout_s + 15)))
        except Exception as exc:  # the browser is a bonus: never break a price check because of it
            log.warning("Browser price check failed: %s", exc)

    # Run in a fresh thread so it never clashes with an event loop already running here.
    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout_s + 20)
    for url, seen in result.items():
        _cache[url] = (time.monotonic(), seen)
    return {**cached, **result}


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


async def _read_all(urls: list[str]) -> dict[str, SeenPrice]:
    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await _launch(pw)
        try:
            context = await browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})

            async def skip_heavy(route):
                if route.request.resource_type in SKIP:
                    await route.abort()
                else:
                    await route.continue_()

            try:
                await context.route("**/*", skip_heavy)
            except Exception:  # some remote browsers don't allow this; pages just load a bit slower
                pass
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
                        found = await _read_page(page, url)
                        if found:
                            seen[url] = found
                    except Exception as exc:
                        log.info("Couldn't read the price on %s: %s", url, str(exc).splitlines()[0])
                    finally:
                        await page.close()

            await asyncio.gather(*(one(u) for u in urls))
            return seen
        finally:
            await browser.close()


async def _read_page(page, url: str) -> SeenPrice | None:
    await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
    price = page.locator(PRICE).first
    robot = page.locator(ROBOT_CHECK).first
    # Whichever shows up first: the price, or a robot check.
    for _ in range(60):
        if "punish" in page.url.lower() or await robot.count():
            state.blocked = True
            log.warning("Daraz showed a robot check. Reading sale prices with the browser is paused "
                        "until the server restarts.")
            return None
        if await price.count() and (await price.inner_text()).strip():
            break
        await page.wait_for_timeout(250)
    else:
        return None
    now = _number(await price.inner_text())
    if not now:
        return None
    old_node = page.locator(OLD_PRICE).first
    old = _number(await old_node.inner_text()) if await old_node.count() else None
    chosen = page.locator(CHOSEN_OPTION)
    option = " / ".join(t.strip() for t in await chosen.all_inner_texts() if t.strip()) or None
    delivery = None
    fee = page.locator(DELIVERY_FEE).first
    try:
        await fee.wait_for(timeout=4000)  # the delivery box loads a moment after the price
        text = (await fee.inner_text()).strip()
        delivery = 0.0 if "free" in text.lower() else _number(text)
    except Exception:
        pass
    return SeenPrice(price=now, original=old if old and old > now else None, option=option, delivery=delivery)
