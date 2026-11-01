from pathlib import Path

from fastapi.testclient import TestClient

from app.adapters.daraz import DarazAdapter
from app.main import app

FIXTURE = (Path(__file__).parent / "fixtures" / "daraz_product.html").read_text(encoding="utf-8")
URL = "https://www.daraz.com.bd/products/wireless-earbuds-pro-x-i123456789-s111.html"


def test_samples_cover_every_verdict():
    with TestClient(app) as client:
        products = client.get("/api/products").json()
        verdicts = {p["verdict"]["verdict"] for p in products if p["is_demo"]}
        assert verdicts == {"fake_discount", "real_deal", "fair", "unconfirmed"}
        bases = {p["verdict"]["basis"] for p in products if p["is_demo"]}
        assert bases == {"history", "other_sellers", "page"}


def test_track_a_link_gives_an_instant_verdict(monkeypatch):
    search = (Path(__file__).parent / "fixtures" / "daraz_search.json").read_text(encoding="utf-8")
    monkeypatch.setattr(DarazAdapter, "fetch", lambda self, url, manual_price=None: self.parse(FIXTURE, url))
    monkeypatch.setattr(DarazAdapter, "search", lambda self, q, host_url=None: self.parse_search(search))
    page = FIXTURE.replace("Wireless Earbuds Pro X", "Redmi Buds 6 Active TWS Earbuds Bluetooth 5.4")
    monkeypatch.setattr(DarazAdapter, "fetch", lambda self, url, manual_price=None: self.parse(page, url))
    with TestClient(app) as client:
        first = client.post("/api/track", json={"url": URL}).json()
        assert first["title"] == "Redmi Buds 6 Active TWS Earbuds Bluetooth 5.4"
        # ৳2,499 "50% off ৳4,999", while 3 other sellers charge ৳1,750–1,850: a fake discount on day one.
        verdict = first["verdict"]
        assert (verdict["basis"], verdict["verdict"]) == ("other_sellers", "fake_discount")
        assert "sell it for less" in verdict["headline"]
        assert first["market"]["count"] == 3
        others = [s["seller"] for s in first["market"]["listings"] if not s["is_this"]]
        assert others == ["Smart Deals", "Mi Store BD", "Tech Haat"]
        assert "where_to_buy" in first["market"]
        # Same product again within the refresh window: no new snapshot.
        again = client.post("/api/track", json={"url": URL + "?spm=xyz"}).json()
        assert again["id"] == first["id"]
        assert len(again["history"]) == 1


def test_unsupported_link_gives_clear_error():
    with TestClient(app) as client:
        response = client.post("/api/track", json={"url": "https://www.amazon.com/dp/B0000000"})
        assert response.status_code == 400
        assert "Daraz" in response.json()["detail"]


def test_status_reports_schedule():
    with TestClient(app) as client:
        body = client.get("/api/status").json()
        assert body["check_times"] == ["10:00", "22:00"]
        assert body["alerts_enabled"] is False


def test_link_inside_shared_text(monkeypatch):
    seen = []

    def fake_fetch(self, url, manual_price=None):
        seen.append(url)
        return self.parse(FIXTURE, URL)

    monkeypatch.setattr(DarazAdapter, "fetch", fake_fetch)
    monkeypatch.setattr(DarazAdapter, "search", lambda self, q, host_url=None: [])
    with TestClient(app) as client:
        text = "Check out this product on Daraz! https://s.daraz.com.bd/s.YVQ56 Shop now."
        response = client.post("/api/track", json={"url": text})
        assert response.status_code == 200
        assert seen == ["https://s.daraz.com.bd/s.YVQ56"]


def test_old_seller_lists_are_rebuilt(monkeypatch):
    from app.db import SessionLocal
    from app.models import MarketCheck
    from app.services import find_product, update_market

    calls = []
    monkeypatch.setattr(DarazAdapter, "search", lambda self, q, host_url=None: calls.append(q) or [])
    with SessionLocal() as session:
        product = find_product(session, "daraz", "i123456789-s111")
        product.market_checks.append(MarketCheck(query="old", seller_count=1, listings=[{"seller": "x", "price": 1}]))
        session.commit()
        update_market(session, product, DarazAdapter())   # old list (no match_version) -> rebuilt
        update_market(session, product, DarazAdapter())   # fresh list -> left alone
    assert len(calls) == 1


def test_remove_a_product(monkeypatch):
    with TestClient(app) as client:
        products = client.get("/api/products").json()
        demo = next(p for p in products if p["is_demo"])
        assert client.delete(f"/api/products/{demo['id']}").status_code == 400
        real = next((p for p in products if not p["is_demo"]), None)
        if real:
            assert client.delete(f"/api/products/{real['id']}").json() == {"ok": True}
            assert client.get(f"/api/products/{real['id']}").status_code == 404
