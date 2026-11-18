"""Speed and safety changes: old seller lists pruned, status hides the browser service, webhook secret."""

from fastapi.testclient import TestClient

from app import config, telegram
from app.adapters.daraz import DarazAdapter
from app.db import SessionLocal
from app.main import app
from app.models import MarketCheck
from app.services import KEEP_MARKET_CHECKS, find_product, latest_market, update_market


def test_only_the_newest_seller_lists_are_kept(monkeypatch):
    monkeypatch.setattr(DarazAdapter, "fetch", lambda self, url, manual_price=None: self.parse(
        open("tests/fixtures/daraz_product.html", encoding="utf-8").read(), url))
    monkeypatch.setattr(DarazAdapter, "search", lambda self, q, host_url=None: [])
    url = "https://www.daraz.com.bd/products/wireless-earbuds-pro-x-i123456789-s111.html"
    with TestClient(app) as client:
        assert client.post("/api/track", json={"url": url}).status_code == 200
    with SessionLocal() as session:
        product = find_product(session, "daraz", "i123456789-s111")
        for _ in range(KEEP_MARKET_CHECKS + 2):
            newest = update_market(session, product, DarazAdapter(), force=True)
        count = session.query(MarketCheck).filter_by(product_id=product.id).count()
        assert count == KEEP_MARKET_CHECKS
        assert latest_market(product).id == newest.id


def test_status_never_describes_the_browser_service(monkeypatch):
    monkeypatch.setattr(config, "BROWSER_WS_URL", "wss://production-sfo.browserless.io?token=abcdef123456789")
    with TestClient(app) as client:
        body = client.get("/api/status").json()
    assert "service" not in body["browser"]
    assert "abcdef" not in str(body) and "789" not in str(body)


def test_webhook_secret_comes_from_the_token(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:abc")
    secret = telegram.webhook_secret()
    assert len(secret) == 40 and "abc" not in secret
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    assert telegram.webhook_secret() == ""  # no bot: the webhook address doesn't exist
