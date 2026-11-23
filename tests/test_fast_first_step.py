"""The first step of a check stays fast: Browserless is used through its web API (one web request,
no Playwright on the server), and when a price must be read in a browser the site first gets the
product's name and photo, then the verdict."""

import httpx
import pytest

from app import browser, config
from app.adapters import PriceReading
from app.adapters.daraz import DarazAdapter
from app.browser import SeenPrice

from .test_sizes import SEARCH, URL_30ML, adapter

PAGE_URL = "https://www.daraz.com.bd/products/thing-i1-s2.html"


@pytest.fixture
def web_api(monkeypatch):
    """A Browserless address, the browser on, no shared cache, and a clean browser state."""
    monkeypatch.setattr(config, "BROWSER_WS_URL", "wss://production-sfo.browserless.io?token=secret123")
    monkeypatch.setattr(config, "BROWSER_PRICES", True)
    monkeypatch.setattr(config, "BROWSER_API", "auto")
    monkeypatch.setattr(browser, "_saved_reads", lambda urls: {})
    monkeypatch.setattr(browser, "_save_reads", lambda seen: None)
    browser._cache.clear()
    monkeypatch.setattr(browser.state, "blocked", False)
    monkeypatch.setattr(browser.state, "last_error", None)
    monkeypatch.setattr(browser.state, "via", None)
    sent = []

    def answer(body):
        def post(url, json=None, timeout=None):
            sent.append((url, json))
            return body if isinstance(body, httpx.Response) else httpx.Response(200, json=body)
        monkeypatch.setattr(httpx, "post", post)
        return sent
    return answer


def test_browserless_is_called_through_its_web_api():
    config_before = (config.BROWSER_WS_URL, config.BROWSER_API)
    try:
        config.BROWSER_API = "auto"
        config.BROWSER_WS_URL = "wss://production-sfo.browserless.io?token=abc"
        assert browser._web_api() == "https://production-sfo.browserless.io/function?token=abc&timeout=45000"
        config.BROWSER_WS_URL = "wss://some-other-service.example?token=abc"
        assert browser._web_api() is None  # other services: Playwright over the address
        config.BROWSER_WS_URL, config.BROWSER_API = "wss://production-sfo.browserless.io?token=abc", "cdp"
        assert browser._web_api() is None  # forced back to Playwright
    finally:
        config.BROWSER_WS_URL, config.BROWSER_API = config_before


def test_one_web_request_reads_the_pages(web_api):
    sent = web_api({"robot": False, "results": {
        PAGE_URL: {"price": "৳ 560", "old": "৳ 3,200", "options": ["Black"], "fee": "৳ 90"},
        PAGE_URL + "?x": {"error": "Navigation timeout of 20000 ms exceeded"}}})
    seen = browser.read_prices([PAGE_URL, PAGE_URL + "?x"], fresh=True)
    assert seen == {PAGE_URL: SeenPrice(560, 3200, "Black", 90)}
    (url, body), = sent
    assert url.endswith("/function?token=secret123&timeout=45000")
    assert "export default async function" in body["code"] and "Network.setBlockedURLs" in body["code"]
    assert body["context"]["urls"] == [PAGE_URL, PAGE_URL + "?x"]
    assert browser.status()["via"] == "web API" and browser.state.last_error is None


def test_answers_wrapped_or_as_text_are_understood(web_api):
    page = {"price": "৳ 560", "old": "৳ 3,200", "options": [], "fee": "Free"}
    web_api({"data": {"robot": False, "results": {PAGE_URL: page}}, "type": "application/json"})
    assert browser.read_prices([PAGE_URL], fresh=True) == {PAGE_URL: SeenPrice(560, 3200, None, 0)}


def test_an_unexpected_answer_is_reported_in_the_status(web_api, monkeypatch):
    monkeypatch.setattr(browser, "_has_playwright", lambda: False)
    web_api(httpx.Response(200, text="<html>Not what we asked for</html>"))
    assert browser.read_prices([PAGE_URL], fresh=True) == {}
    assert "unexpected answer" in browser.state.last_error
    web_api({"robot": False, "results": {PAGE_URL: {"error": "page.createCDPSession is not a function"}}})
    browser._cache.clear()
    assert browser.read_prices([PAGE_URL], fresh=True) == {}
    assert "createCDPSession is not a function" in browser.state.last_error
    assert browser.status()["working"] is False


def test_a_robot_check_pauses_the_browser(web_api):
    web_api({"robot": True, "results": {PAGE_URL: {"robot": True}}})
    assert browser.read_prices([PAGE_URL], fresh=True) == {}
    assert browser.state.blocked is True
    assert browser.read_prices([PAGE_URL], fresh=True) == {}  # no more tries


def test_a_failing_service_never_breaks_a_check_or_shows_the_token(web_api, monkeypatch):
    monkeypatch.setattr(browser, "_has_playwright", lambda: False)
    web_api(httpx.Response(401, text="Bad token=secret123"))
    assert browser.read_prices([PAGE_URL], fresh=True) == {}
    assert "401" in browser.state.last_error and "secret123" not in browser.state.last_error


def test_quick_answer_first_then_the_price_without_downloading_again(monkeypatch):
    fake = adapter()
    downloads = []
    real_get = DarazAdapter._get
    monkeypatch.setattr(DarazAdapter, "_get", lambda self, url, headers=None: downloads.append(url) or real_get(self, url, headers))
    monkeypatch.setattr(DarazAdapter, "can_read_shown_price", lambda self: True)
    monkeypatch.setattr(DarazAdapter, "see_prices",
                        lambda self, urls, fresh=False: {u: SeenPrice(699, 1200, "30 ML Spary", 0) for u in urls})
    with pytest.raises(PriceReading) as quick:
        fake.fetch(URL_30ML, quick=True)
    assert quick.value.preview["title"].startswith("Vampire Blood")
    assert quick.value.preview["variant"] == "30 ML Spary" and quick.value.preview["listed_price"] == 1200
    before = len(downloads)
    data = fake.fetch(URL_30ML)  # the follow-up: only the browser step is left
    assert (data.price, data.original_price, data.variant) == (699, 1200, "30 ML Spary")
    assert len(downloads) == before  # the page wasn't downloaded or searched again


def test_api_answers_202_with_the_product_then_the_verdict(monkeypatch):
    from fastapi.testclient import TestClient

    from app.db import SessionLocal
    from app.main import app
    from app.models import Product

    fake, real_fetch = adapter(), DarazAdapter.fetch
    monkeypatch.setattr(DarazAdapter, "fetch",
                        lambda self, url, manual_price=None, quick=False: real_fetch(fake, url, manual_price, quick))
    monkeypatch.setattr(DarazAdapter, "search", lambda self, q, host_url=None: fake.parse_search(SEARCH))
    monkeypatch.setattr(DarazAdapter, "can_read_shown_price", lambda self: True)
    monkeypatch.setattr(DarazAdapter, "see_prices",
                        lambda self, urls, fresh=False: {u: SeenPrice(699, 1200, "30 ML Spary", 0) for u in urls})
    with TestClient(app) as client, SessionLocal() as session:
        for old in session.query(Product).filter(Product.external_id == "i575021547-s12671878402"):
            session.delete(old)
        session.commit()
        first = client.post("/api/track", json={"url": URL_30ML, "quick": True})
        assert first.status_code == 202, first.text
        assert first.json()["reading_price"] is True
        assert first.json()["preview"]["title"].startswith("Vampire Blood")
        second = client.post("/api/track", json={"url": URL_30ML})
        assert second.status_code == 200, second.text
        assert (second.json()["verdict"]["price"], second.json()["verdict"]["original_price"]) == (699, 1200)
        # Leave the database as other tests expect it (they check this product from scratch).
        for made in session.query(Product).filter(Product.external_id == "i575021547-s12671878402"):
            session.delete(made)
        session.commit()


def test_without_a_browser_quick_still_asks_for_the_price(monkeypatch):
    from app.adapters import PriceNeeded

    monkeypatch.setattr(DarazAdapter, "can_read_shown_price", lambda self: False)
    with pytest.raises(PriceNeeded):
        adapter().fetch(URL_30ML, quick=True)


def test_request_addresses_with_tokens_are_never_logged(caplog):
    """httpx logs each request's address at INFO; Browserless's and Telegram's carry the token."""
    import logging

    import app.config  # noqa: F401  (sets the levels)

    with caplog.at_level(logging.INFO):
        logging.getLogger("httpx").info("HTTP Request: POST https://production-sfo.browserless.io/function?token=secret123")
    assert "secret123" not in caplog.text
