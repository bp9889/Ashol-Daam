from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import alerts, config, telegram
from app.adapters import ProductData
from app.db import SessionLocal
from app.main import app
from app.models import Alert, Product
from app.services import save_snapshot

URL = "https://www.daraz.com.bd/products/rice-cooker-i777-s1.html"


@pytest.fixture
def bot(monkeypatch):
    """Pretend Telegram is set up; collect the messages instead of sending them."""
    sent = []
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:TEST")
    monkeypatch.setattr(config, "TELEGRAM_BOT_USERNAME", "AsolDamTestBot")
    monkeypatch.setattr(telegram, "send", lambda chat_id, text: sent.append((str(chat_id), text)))
    return sent


def price(value, external_id="i777-s1"):
    return ProductData(source="daraz", external_id=external_id, url=URL, title="Rice cooker <1.8L>", price=value)


def start(token, chat_id=42):
    return {"update_id": 1, "message": {"text": f"/start {token}", "chat": {"id": chat_id}}}


def test_should_fire_with_target():
    a = Alert(target_price=2500, baseline_price=3000)
    assert not alerts.should_fire(a, 2600)
    assert alerts.should_fire(a, 2500)
    a.last_notified_price = 2500
    assert not alerts.should_fire(a, 2500)  # don't repeat the same price
    assert alerts.should_fire(a, 2400)      # but do tell them about a further drop


def test_should_fire_without_target_needs_5_percent():
    a = Alert(target_price=None, baseline_price=3000)
    assert not alerts.should_fire(a, 2900)
    assert alerts.should_fire(a, 2850)


def test_full_flow_link_then_alert(bot):
    with SessionLocal() as session:
        product = save_snapshot(session, price(3000))
        alert = alerts.create(session, product, target_price=2600)

        # Not linked to a chat yet: nothing is sent even when the price drops.
        save_snapshot(session, price(2500))
        assert bot == []

        telegram.handle_update(session, start(alert.token))
        assert bot[-1][0] == "42"
        assert "Alert set" in bot[-1][1]
        assert "&lt;1.8L&gt;" in bot[-1][1]  # titles are escaped for Telegram's HTML mode

        save_snapshot(session, price(2550))
        assert "Now ৳2,550" in bot[-1][1]
        assert "was ৳3,000" in bot[-1][1]

        count = len(bot)
        save_snapshot(session, price(2550))
        assert len(bot) == count  # same price, no repeat

        telegram.handle_update(session, {"update_id": 2, "message": {"text": "/stop", "chat": {"id": 42}}})
        assert "Turned off 1 alert" in bot[-1][1]
        session.refresh(alert)
        assert alert.active is False


def test_unknown_token_gets_a_helpful_reply(bot):
    with SessionLocal() as session:
        telegram.handle_update(session, start("nope"))
    assert "expired" in bot[-1][1]


def test_api_creates_alert_link(bot):
    with TestClient(app) as client:
        with SessionLocal() as session:
            product = save_snapshot(session, price(1999, external_id="i888"))
        body = client.post(f"/api/products/{product.id}/alerts", json={"target_price": 1800}).json()
        assert body["link"].startswith("https://t.me/AsolDamTestBot?start=")

        demo = next(p for p in client.get("/api/products").json() if p["is_demo"])
        response = client.post(f"/api/products/{demo['id']}/alerts", json={})
        assert response.status_code == 400


def test_api_without_telegram_says_so():
    with TestClient(app) as client:
        products = client.get("/api/products").json()
        response = client.post(f"/api/products/{products[0]['id']}/alerts", json={})
        assert response.status_code == 503
        assert "aren't set up" in response.json()["detail"]


def test_process_updates_confirms_what_it_handled(bot, monkeypatch):
    calls = []

    def fake_call(method, http_timeout=15, **params):
        calls.append((method, params))
        if method == "getUpdates" and "offset" not in params:
            return [{"update_id": 7, "message": {"text": "/start", "chat": {"id": 5}}},
                    {"update_id": 8, "message": {"text": "/list", "chat": {"id": 5}}}]
        return []

    monkeypatch.setattr(telegram, "call", fake_call)
    with SessionLocal() as session:
        assert telegram.process_updates(session, timeout=0) == 2
    assert calls[-1] == ("getUpdates", {"offset": 9, "timeout": 0})
    assert "no active alerts" in bot[-1][1]
