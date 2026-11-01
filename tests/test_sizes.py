"""Listings that come in several sizes (perfume 3ml…100ml). Built from a real Daraz listing checked on
1 Nov 2026: the 30 ML option sells for ৳699 (old price ৳1,200); search only shows the cheapest
option (6ML Roll ON, ৳240)."""

from pathlib import Path

import httpx
import pytest

from app.adapters import PriceNeeded
from app.adapters.daraz import DarazAdapter
from app.market import compare, our_size, rank, sizes_in

HERE = Path(__file__).parent / "fixtures"
PAGE = (HERE / "daraz_variant_page.html").read_text(encoding="utf-8")
SEARCH = (HERE / "daraz_search_vampire.json").read_text(encoding="utf-8")
BASE = "https://www.daraz.com.bd/products/vampire-blood-i575021547-s{}.html"
URL_30ML = BASE.format("12671878402")
URL_6ML = BASE.format("12632959914")
TITLE = ("Vampire Blood Euro Valley Super Premium 30 ML Perfume Oil – 12-Hour lasting Fragrance | "
         "Available in 100ML, 50ML, 30ML, 15ML, 6ML, 3ML Euro Valley")


def adapter():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/catalog/" in request.url.path:
            return httpx.Response(200, text=SEARCH)
        return httpx.Response(200, text=PAGE)
    return DarazAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_reads_the_chosen_size():
    data = DarazAdapter().parse(PAGE, URL_30ML)
    assert (data.variant, data.variant_count) == ("30 ML Spary", 5)
    assert data.price_unconfirmed is True
    data = DarazAdapter().parse(PAGE, URL_6ML)
    assert data.variant == "6ML Roll ON"


def test_never_uses_the_cheapest_sizes_price_for_another_size():
    with pytest.raises(PriceNeeded) as caught:
        adapter().fetch(URL_30ML)
    assert caught.value.variant == "30 ML Spary"
    assert caught.value.old_price == 1200
    assert "“30 ML Spary”" in str(caught.value)


def test_typed_price_is_used_with_the_old_price_from_the_page():
    data = adapter().fetch(URL_30ML, manual_price=699)
    assert (data.price, data.original_price, data.variant) == (699, 1200, "30 ML Spary")


def test_cheapest_size_still_gets_its_price_from_search():
    data = adapter().fetch(URL_6ML)
    assert (data.price, data.price_unconfirmed) == (240, False)


def test_size_detection():
    assert sizes_in(TITLE) == {"100ml", "50ml", "30ml", "15ml", "6ml", "3ml"}
    assert our_size(TITLE, "30 ML Spary") == "30ml"
    assert our_size(TITLE, None) is None                      # title names many sizes
    assert our_size("WishCare Roll On Serum 50ml", None) == "50ml"


def test_only_same_size_single_size_listings_are_compared():
    results = DarazAdapter().parse_search(SEARCH)
    market = compare(TITLE, 699, "i575021547-s12671878402", results, variant="30 ML Spary", own_original=1200)
    others = [l["seller"] for l in market.listings if not l["is_this"]]
    # The ৳88 / ৳89 / ৳99 listings sell many sizes, so their price is for a small one: left out.
    assert others == ["Attar House", "Scent Corner"]
    assert market.median == 685
    mine = next(l for l in market.listings if l["is_this"])
    assert (mine["price"], mine["original_price"]) == (699, 1200)   # not the ৳240 thumbnail
    best = rank(market.listings)["ranked"][0]
    assert best["seller"] == "Attar House"


def test_without_a_size_nothing_changes():
    results = DarazAdapter().parse_search(SEARCH)
    market = compare("Vampire Blood Euro Valley Perfume Oil", 99, "i1", results)
    assert market.count >= 3


def test_api_asks_for_the_price_then_accepts_it(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    fake, real_fetch = adapter(), DarazAdapter.fetch
    monkeypatch.setattr(DarazAdapter, "fetch", lambda self, url, manual_price=None: real_fetch(fake, url, manual_price))
    monkeypatch.setattr(DarazAdapter, "search", lambda self, q, host_url=None: fake.parse_search(SEARCH))
    with TestClient(app) as client:
        first = client.post("/api/track", json={"url": URL_30ML})
        assert first.status_code == 422
        body = first.json()
        assert body["need_price"] is True and body["variant"] == "30 ML Spary" and body["old_price"] == 1200
        assert "৳1,200" in body["detail"] and "old price" not in body["detail"]

        second = client.post("/api/track", json={"url": URL_30ML, "price": 699})
        assert second.status_code == 200
        r = second.json()
        assert r["variant"] == "30 ML Spary"
        assert (r["verdict"]["price"], r["verdict"]["original_price"]) == (699, 1200)
        assert [l["seller"] for l in r["market"]["listings"] if not l["is_this"]] == ["Attar House", "Scent Corner"]


def test_old_database_gets_the_new_column(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, inspect, text
    import app.db as db

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:  # a products table from before sizes existed
        conn.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, source VARCHAR(32), external_id VARCHAR(64), "
                          "url TEXT, title TEXT, image_url TEXT, currency VARCHAR(8), is_demo BOOLEAN, "
                          "created_at DATETIME, last_checked_at DATETIME)"))
    monkeypatch.setattr(db, "engine", engine)
    db.init_db()
    assert "variant" in {c["name"] for c in inspect(engine).get_columns("products")}


def test_confirming_the_listed_price_means_no_discount():
    """10ML Spray: Daraz lists ৳550 and that IS the price (no sale). Pressing "Yes, it's ৳550"
    must not invent a discount."""
    fake = adapter()
    data = DarazAdapter.fetch(fake, URL_30ML, manual_price=1200)
    assert (data.price, data.original_price) == (1200, None)


# ---- Your case (1 Nov 2026): one listing's 30 ML at ৳999, another listing's 30 ML at ৳699 ---------

OTHER_ID = "i1572297183-s12682492581"
OTHER_TITLE = "Vampire Blood Euro Valley 15 ml premium Long Lasting Attar premium perfume -3ml/6ml/12ML/30ml"


def _adapter_for_other_listings():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/catalog/" in request.url.path:
            return httpx.Response(200, text=SEARCH)
        if "i575021547" in request.url.path:
            return httpx.Response(200, text=PAGE)  # sells 30 ML; page only has its regular price ৳1,200
        return httpx.Response(200, text="<html>no sizes here</html>")
    return DarazAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_finds_the_30ml_option_of_a_listing_that_sells_many_sizes(monkeypatch):
    from fastapi.testclient import TestClient

    from app.adapters import ProductData
    from app.db import SessionLocal
    from app.main import app
    from app.services import save_snapshot, update_market

    fake, real_fetch, real_option = _adapter_for_other_listings(), DarazAdapter.fetch, DarazAdapter.size_option
    monkeypatch.setattr(DarazAdapter, "fetch", lambda self, url, manual_price=None: real_fetch(fake, url, manual_price))
    monkeypatch.setattr(DarazAdapter, "search", lambda self, q, host_url=None: fake.parse_search(SEARCH))
    monkeypatch.setattr(DarazAdapter, "size_option", lambda self, listing, wanted: real_option(fake, listing, wanted))

    with TestClient(app) as client, SessionLocal() as session:
        from app.models import Product
        for old in session.query(Product).filter(Product.external_id.in_([OTHER_ID, "i575021547-s12671878402"])):
            session.delete(old)  # start clean: other tests may have checked these already
        session.commit()
        # 1. You check the ৳999 listing (you typed 999; Daraz's old price ৳1,200).
        mine = save_snapshot(session, ProductData(
            source="daraz", external_id=OTHER_ID, url=f"https://www.daraz.com.bd/products/x-{OTHER_ID}.html",
            title=OTHER_TITLE, price=999, original_price=1200, variant="30ML spray", variant_count=5))
        update_market(session, mine, fake, force=True)
        listings = client.get(f"/api/products/{mine.id}").json()["market"]["listings"]
        other = next(l for l in listings if l["id"] == "i575021547-s12671878402")
        # Search showed that listing at ৳240 (its 6 ML). Now we see its 30 ML option instead.
        assert other["price"] == 1200 and other["price_unconfirmed"] is True
        assert other["url"].endswith("-i575021547-s12671878402.html")
        assert all(l["price"] != 240 for l in listings)

        # 2. You check that listing's 30 ML and type its sale price, ৳699.
        assert client.post("/api/track", json={"url": URL_30ML, "price": 699}).status_code == 200

        # 3. Back on the ৳999 listing: the other seller's 30 ML now shows ৳699, and the verdict says so.
        r = client.get(f"/api/products/{mine.id}").json()
        other = next(l for l in r["market"]["listings"] if l["id"] == "i575021547-s12671878402")
        assert (other["price"], other["original_price"], other["price_unconfirmed"]) == (699, 1200, False)
        assert other["confirmed_at"]
        everyone = r["market"]["where_to_buy"]["ranked"] + r["market"]["where_to_buy"]["unproven"]
        row = next(l for l in everyone if l["id"] == "i575021547-s12671878402")
        assert any("checked on this site" in n for n in row["notes"])


def test_a_listing_without_our_size_is_left_out():
    from app.adapters import Listing

    fake = _adapter_for_other_listings()
    listing = Listing("i575021547-s12632959914", TITLE, 240, url="https://www.daraz.com.bd/products/x-i575021547.html")
    assert fake.size_option(listing, lambda option: "50ml" in sizes_in(option)) is None
    six = fake.size_option(listing, lambda option: "6ml" in sizes_in(option))
    assert (six.external_id, six.price, six.price_unconfirmed) == ("i575021547-s12632959914", 240, False)


def test_one_paste_is_enough(monkeypatch):
    """You paste only the ৳999 perfume. The other listing's 30 ML sale price (৳699) is read from its
    page by the hidden browser, and so is your own size's price. Nothing to type."""
    from fastapi.testclient import TestClient

    from app.browser import SeenPrice
    from app.db import SessionLocal
    from app.main import app
    from app.models import Product

    mine_url = f"https://www.daraz.com.bd/products/x-{OTHER_ID}.html"
    other_30ml = "https://www.daraz.com.bd/products/100ml-50ml-30ml-15ml-6ml-3ml-i575021547-s12671878402.html"
    shown = {mine_url: SeenPrice(999, 1200, "30ML spray"), other_30ml: SeenPrice(699, 1200, "30 ML Spary")}
    asked = []

    def see(self, urls):
        asked.append(sorted(urls))
        return {u: shown[u] for u in urls if u in shown}

    page_mine = PAGE.replace("575021547", "1572297183").replace("12671878402", "12682492581") \
                    .replace('"30 ML Spary"', '"30ML spray"').replace(TITLE, OTHER_TITLE)
    fake = _adapter_for_other_listings()

    def handler(request):
        if "i1572297183" in request.url.path:
            return httpx.Response(200, text=page_mine)
        return fake._client._transport.handle_request(request)

    fake2 = DarazAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    real_fetch, real_option = DarazAdapter.fetch, DarazAdapter.size_option
    monkeypatch.setattr(DarazAdapter, "see_prices", see)
    monkeypatch.setattr(DarazAdapter, "fetch", lambda self, url, manual_price=None: real_fetch(fake2, url, manual_price))
    monkeypatch.setattr(DarazAdapter, "search", lambda self, q, host_url=None: fake2.parse_search(SEARCH))
    monkeypatch.setattr(DarazAdapter, "size_option", lambda self, listing, wanted: real_option(fake2, listing, wanted))

    with TestClient(app) as client, SessionLocal() as session:
        for old in session.query(Product).filter(Product.external_id.in_([OTHER_ID, "i575021547-s12671878402"])):
            session.delete(old)
        session.commit()
        r = client.post("/api/track", json={"url": mine_url})
        assert r.status_code == 200, r.text
        r = r.json()
    assert (r["verdict"]["price"], r["verdict"]["original_price"]) == (999, 1200)
    other = next(l for l in r["market"]["listings"] if l["id"] == "i575021547-s12671878402")
    assert (other["price"], other["original_price"], other["price_unconfirmed"]) == (699, 1200, False)
    assert "৳699" in " ".join(r["verdict"]["reasons"])
    assert [mine_url] in asked  # our own price was read from the page too
