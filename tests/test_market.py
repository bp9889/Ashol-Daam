from pathlib import Path

import pytest

from app.adapters import BlockedError
from app.adapters.daraz import DarazAdapter
from app.market import build_query, compare

SEARCH = (Path(__file__).parent / "fixtures" / "daraz_search.json").read_text(encoding="utf-8")
adapter = DarazAdapter()


def test_parse_search_json():
    results = adapter.parse_search(SEARCH)
    assert len(results) == 7  # the item without a price is skipped
    first = results[0]
    assert first.external_id == "i123456789"
    assert first.price == 2499 and first.original_price == 4999
    assert first.seller == "Gadget Zone"
    assert first.url == "https://www.daraz.com.bd/products/redmi-buds-6-active-i123456789-s111.html"


def test_parse_search_from_page_data():
    page = f"<html><script>window.pageData = {SEARCH};</script></html>"
    assert len(adapter.parse_search(page)) == 7


def test_search_robot_check():
    with pytest.raises(BlockedError):
        adapter.parse_search('{"ret":["FAIL_SYS_USER_VALIDATE::RGV587_ERROR"],"data":{"url":"https://x/punish"}}')


def test_query_drops_noise_words():
    assert build_query("NEW Original Redmi Buds 6 Active TWS Earbuds Best Quality") == "redmi buds 6 active tws"


def test_compare_keeps_only_the_same_product():
    results = adapter.parse_search(SEARCH)
    market = compare("Redmi Buds 6 Active TWS Earbuds Bluetooth 5.4", 2499, "i123456789-s111", results)
    sellers = {listing["seller"] for listing in market.listings if not listing["is_this"]}
    # Not itself, not the ৳199 case, not the ৳5,200 Pro model, not a different brand.
    assert sellers == {"Mi Store BD", "Tech Haat", "Smart Deals"}
    # The pasted listing itself is kept (flagged) for the "where to buy" ranking only.
    assert [l["seller"] for l in market.listings if l["is_this"]] == ["Gadget Zone"]
    assert market.count == 3
    assert market.median == 1790
    assert (market.low, market.high) == (1750, 1850)
    assert market.listings[0]["price"] == 1750  # cheapest first


def test_variant_and_model_number_must_match():
    from app.adapters import Listing

    others = [
        Listing("i1", "Redmi Buds 6 Pro Earbuds Active TWS", 2400),   # adds "Pro"
        Listing("i2", "Redmi Buds 5 Active TWS Earbuds", 2400),       # different model number
        Listing("i3", "Redmi Buds 6 Active TWS Earbuds Blue", 2400),  # same thing
        Listing("i4", "Redmi Buds 6 Active Earbuds", 2350),           # same thing, shorter title
    ]
    market = compare("Redmi Buds 6 Active TWS Earbuds", 2499, "i9", others)
    assert [listing["title"] for listing in market.listings] == [
        "Redmi Buds 6 Active Earbuds",
        "Redmi Buds 6 Active TWS Earbuds Blue",
    ]


def test_compare_with_too_few_sellers():
    results = adapter.parse_search(SEARCH)[:2]
    market = compare("Redmi Buds 6 Active TWS Earbuds", 2499, "i123456789-s111", results)
    assert market.count == 1
    assert market.median is None


def test_same_product_matches_both_ways_despite_hyphens_and_units():
    # Real titles from Daraz (1 Nov 2026): one says "Fragrance-50ml", the other "50ml |".
    a = "WishCare Underarm Roll On Serum - 5% AHA, 3% Kojic Acid, HA, Licorice - Underarm Lightening & Odour Control - Long Lasting Aqua Fragrance-50ml"
    b = "WishCare Underarm Roll On Serum 50ml | 5% AHA & 3% Kojic Acid for Brightening & Odour Control - Roll On Deodorant"
    from app.market import key_words, same_model, similarity
    for ours, other in [(a, b), (b, a)]:
        words = key_words(ours)
        assert same_model(ours, words, other) and similarity(words, other) >= 0.67


def test_units_written_differently_still_match():
    from app.market import tokens
    assert tokens("Steam Iron 2200 Watt") == tokens("Steam Iron 2200W")
    assert tokens("Serum 50 ML") == tokens("serum 50ml")
    assert "1.8l" in tokens("1.8 Litre Rice Cooker")
    assert "5.4" in tokens("Bluetooth 5.4")


def test_different_sizes_do_not_match():
    from app.adapters import Listing
    from app.market import compare
    ours = "WishCare Underarm Roll On Serum 50ml"
    other = [Listing("i9-s9", "WishCare Underarm Roll On Serum 100ml", 700, seller="X")]
    assert compare(ours, 699, "i1-s1", other).listings == []


def test_real_wishcare_case_both_listings_give_the_same_picture():
    """Real search results (1 Nov 2026). Pasting either WishCare listing must find the other one."""
    from pathlib import Path
    from app.market import rank

    results = adapter.parse_search((Path(__file__).parent / "fixtures" / "daraz_search_wishcare.json").read_text(encoding="utf-8"))
    a = ("WishCare Underarm Roll On Serum - 5% AHA, 3% Kojic Acid, HA, Licorice - Underarm Lightening & Odour Control"
         " - Long Lasting Aqua Fragrance-50ml", 699, "i327665585-s1598953003")
    b = ("WishCare Underarm Roll On Serum 50ml | 5% AHA & 3% Kojic Acid for Brightening & Odour Control - Roll On Deo"
         " for Women & Men- Long Lasting Aqua Fragrance", 788, "i513895070-s2468511060")
    assert build_query(a[0]) == build_query(b[0]) == "wishcare underarm roll serum aha"
    for title, price, own in (a, b):
        market = compare(title, price, own, results)
        assert market.median == 750
        best = rank(market.listings)["ranked"][0]
        assert (best["seller"], best["price"]) == ("Look Shop BD", 699)
