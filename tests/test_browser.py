"""The hidden browser reads the price a shopper sees. Tested on small local pages built like Daraz's:
the price only appears after the page's scripts run (as on Daraz), and one page is a robot check."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

pytest.importorskip("playwright")

from app import browser, config  # noqa: E402

PRODUCT = """<!doctype html><html><body><div class="pdp-product-price"></div>
<div class="sku-prop"><span class="sku-variable-name-selected">30 ML Spary</span></div>
<script>
  // Like Daraz: the sale price arrives a moment after the page loads.
  setTimeout(() => {
    document.querySelector('.pdp-product-price').innerHTML =
      '<span class="pdp-price pdp-price_type_normal">৳ 699</span>' +
      '<span class="pdp-price pdp-price_type_deleted">৳ 1,200</span>';
  }, 400);
  setTimeout(() => {  // the delivery box loads a little later
    document.body.insertAdjacentHTML('beforeend', '<div class="delivery-option-item__shipping-fee">৳ 60</div>');
  }, 900);
</script></body></html>"""
NO_SALE = """<!doctype html><html><body>
<span class="pdp-price pdp-price_type_normal">৳ 550</span>
<span class="sku-variable-name-selected">10ML Spray</span>
<div class="delivery-option-item__shipping-fee no-subtitle">Free</div></body></html>"""
ROBOT = """<!doctype html><html><body><div class="nc-container">Slide to verify</div></body></html>"""


@pytest.fixture()
def site(tmp_path, monkeypatch):
    (tmp_path / "p30.html").write_text(PRODUCT, encoding="utf-8")
    (tmp_path / "p10.html").write_text(NO_SALE, encoding="utf-8")
    (tmp_path / "robot.html").write_text(ROBOT, encoding="utf-8")
    handler = partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(config, "BROWSER_PRICES", True)
    monkeypatch.setattr(browser.state, "blocked", False)
    monkeypatch.setattr(browser.state, "broken", None)
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_reads_the_sale_price_after_scripts_add_it(site):
    seen = browser.read_prices([f"{site}/p30.html", f"{site}/p10.html"])
    if browser.state.broken:
        pytest.skip(f"no browser here: {browser.state.broken}")
    assert (seen[f"{site}/p30.html"].price, seen[f"{site}/p30.html"].original) == (699, 1200)
    assert seen[f"{site}/p30.html"].option == "30 ML Spary"
    assert (seen[f"{site}/p10.html"].price, seen[f"{site}/p10.html"].original) == (550, None)
    assert (seen[f"{site}/p30.html"].delivery, seen[f"{site}/p10.html"].delivery) == (60, 0)


def test_stops_at_a_robot_check(site):
    seen = browser.read_prices([f"{site}/robot.html"])
    if browser.state.broken:
        pytest.skip(f"no browser here: {browser.state.broken}")
    assert seen == {} and browser.state.blocked is True
    assert browser.read_prices([f"{site}/p30.html"]) == {}  # paused, no more tries


def test_off_switch(site, monkeypatch):
    monkeypatch.setattr(config, "BROWSER_PRICES", False)
    assert browser.read_prices([f"{site}/p30.html"]) == {}


def test_uses_a_remote_browser_when_given_one(site, monkeypatch):
    """Like Browserless on Vercel: connect to a browser running elsewhere instead of starting one."""
    import socket
    import subprocess
    import time

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        exe = pw.chromium.executable_path
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    proc = subprocess.Popen([exe, "--headless=new", f"--remote-debugging-port={port}", "--no-sandbox",
                             "--user-data-dir=" + str(__import__("tempfile").mkdtemp()), "about:blank"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1.5)
        monkeypatch.setattr(config, "BROWSER_WS_URL", f"http://127.0.0.1:{port}")
        browser._cache.clear()
        seen = browser.read_prices([f"{site}/p30.html"])
        assert (seen[f"{site}/p30.html"].price, seen[f"{site}/p30.html"].delivery) == (699, 60)
    finally:
        proc.terminate()


def test_status_never_shows_the_token():
    from app.browser import _hide_secrets
    msg = "BrowserType.connect_over_cdp: WebSocket error: wss://production-sfo.browserless.io?token=abc123&x=1 403"
    assert "abc123" not in _hide_secrets(msg) and "token=***" in _hide_secrets(msg)
