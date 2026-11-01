"""'Where to buy': rank sellers by price AND buyer trust, so a cheap listing with no
reviews can't top the list. Field names follow a live Daraz search checked on 1 Nov 2026."""

import json

from app.adapters.daraz import DarazAdapter, parse_count
from app.market import rank, trusted_rating


def L(seller, price, rating=None, reviews=0, sold=0, mall=False, overseas=False, is_this=False):
    return {"seller": seller, "title": seller, "price": price, "rating": rating, "reviews": reviews,
            "sold": sold, "mall": mall, "overseas": overseas, "free_shipping": False, "is_this": is_this, "url": None}


def test_few_reviews_count_for_little():
    assert round(trusted_rating(5.0, 1), 2) == 3.67
    assert round(trusted_rating(4.6, 200), 2) == 4.56
    assert trusted_rating(None, 0) == 3.5


def test_cheap_with_no_reviews_goes_to_unproven():
    result = rank([
        L("No reviews shop", 1500),
        L("Trusted shop", 1700, rating=4.8, reviews=320, sold=1200),
        L("Okay shop", 1650, rating=4.2, reviews=40),
    ])
    assert [e["seller"] for e in result["ranked"]] == ["Trusted shop", "Okay shop"]
    assert [e["seller"] for e in result["unproven"]] == ["No reviews shop"]
    assert result["unproven"][0]["notes"][0] == "No reviews yet"
    assert result["ranked"][0]["notes"][:2] == ["4.8★ from 320 reviews", "1,200 sold"]


def test_much_cheaper_and_well_rated_beats_slightly_better_rated():
    result = rank([
        L("Pricey but loved", 2600, rating=4.9, reviews=500),
        L("Cheap and good", 1800, rating=4.6, reviews=150),
    ])
    assert result["ranked"][0]["seller"] == "Cheap and good"


def test_poorly_rated_and_few_reviews():
    result = rank([
        L("Bad", 1400, rating=3.1, reviews=60),
        L("New", 1450, rating=5.0, reviews=2),
        L("Good", 1600, rating=4.7, reviews=90),
    ])
    assert [e["seller"] for e in result["ranked"]] == ["Good"]
    # Unproven: not-yet-reviewed first, poorly rated last.
    assert [e["seller"] for e in result["unproven"]] == ["New", "Bad"]
    assert result["unproven"][0]["notes"][0] == "Only 2 reviews so far (5.0★)"
    assert result["unproven"][1]["notes"][0] == "Poorly rated: 3.1★ from 60 reviews"


def test_mall_store_counts_as_proven_and_overseas_is_flagged():
    result = rank([
        L("Official store", 1900, mall=True),
        L("Overseas shop", 1700, rating=4.7, reviews=30, overseas=True),
    ])
    names = [e["seller"] for e in result["ranked"]]
    assert set(names) == {"Official store", "Overseas shop"}
    overseas = next(e for e in result["ranked"] if e["seller"] == "Overseas shop")
    assert "Ships from overseas, so delivery is slow" in overseas["notes"]


def test_the_pasted_listing_is_ranked_too():
    result = rank([L("You pasted this", 2000, rating=4.5, reviews=20, is_this=True), L("Cheaper", 1600, rating=4.6, reviews=80)])
    assert result["ranked"][0]["seller"] == "Cheaper"
    assert result["ranked"][1]["is_this"] is True


def test_parse_count():
    assert [parse_count(v) for v in ["136 sold", "1.2K sold", "10K+ sold", "", None]] == [136, 1200, 10000, 0, 0]


def test_search_parser_reads_trust_signals():
    body = json.dumps({"mods": {"listItems": [
        {"itemId": "1", "skuId": "2", "name": "Redmi Buds 6 Active", "price": "3193", "originalPrice": "7512",
         "sellerName": "Buy More Save More Store", "ratingScore": "5.0", "review": "8", "itemSoldCntShow": "136 sold",
         "location": "Overseas", "inStock": "true",
         "icons": [{"bizType": "coins"}, {"bizType": "lazMall"}, {"bizType": "FreeshippingAndVoucherMax"}]},
        {"itemId": "3", "name": "Redmi Buds 6 Active", "price": "950", "ratingScore": "", "review": "", "location": "Dhaka"},
        {"itemId": "4", "name": "Sold out", "price": "900", "inStock": "false"},
    ]}})
    first, second = DarazAdapter().parse_search(body)
    assert (first.rating, first.reviews, first.sold) == (5.0, 8, 136)
    assert (first.mall, first.overseas, first.free_shipping) == (True, True, True)
    assert first.seller == "Buy More Save More Store"
    assert (second.rating, second.reviews, second.mall, second.overseas) == (None, 0, False, False)


def test_a_cheaper_well_rated_seller_beats_an_official_store_costing_more():
    result = rank([
        L("Official store", 1850, rating=4.8, reviews=530, sold=2400, mall=True),
        L("Electro Mart", 1720, rating=4.7, reviews=212, sold=1500),
    ])
    assert [e["seller"] for e in result["ranked"]] == ["Electro Mart", "Official store"]


def test_official_store_wins_when_the_price_is_close():
    result = rank([
        L("Official store", 1730, rating=4.8, reviews=530, mall=True),
        L("Electro Mart", 1720, rating=4.7, reviews=212),
    ])
    assert result["ranked"][0]["seller"] == "Official store"


def test_verdict_points_to_a_cheaper_trusted_seller():
    from app.services import point_to_better_seller
    from app.verdict import Report

    result = Report(verdict="real_deal", headline="Good price. It's 12% below what other sellers charge.", price=788)
    where = rank([
        L("Look Shop BD", 699, rating=4.7, reviews=99, mall=True),
        L("Well-being Distribution", 788, rating=4.5, reviews=26, mall=True, is_this=True),
    ])
    point_to_better_seller(result, where, "BDT")
    assert result.verdict == "real_deal"
    assert result.headline == "Good price, but Look Shop BD has it for even less: ৳699."
    assert result.reasons[0].startswith("Look Shop BD sells the same product for ৳699 (4.7★ from 99 reviews)")


def test_no_note_when_you_already_have_the_best_pick():
    from app.services import point_to_better_seller
    from app.verdict import Report

    result = Report(verdict="real_deal", headline="Good price.", price=699)
    where = rank([L("Look Shop BD", 699, rating=4.7, reviews=99, is_this=True), L("Other", 788, rating=4.5, reviews=26)])
    point_to_better_seller(result, where, "BDT")
    assert result.headline == "Good price." and result.reasons == []


def test_search_listing_keeps_its_photo():
    body = json.dumps({"mods": {"listItems": [
        {"itemId": "1", "name": "Streax Hair Serum 115ml", "price": "329", "image": "//img.example/serum.jpg"}]}})
    (listing,) = DarazAdapter().parse_search(body)
    assert listing.image == "https://img.example/serum.jpg"
