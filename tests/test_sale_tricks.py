"""Before-sale price rises, total cost with delivery, and the 'much cheaper' warning."""

from datetime import datetime, timedelta, timezone

from app.market import rank
from app.services import point_to_better_seller
from app.verdict import MarketInfo, Point, analyze

NOW = datetime(2026, 11, 9, 10, tzinfo=timezone.utc)


def at(days_ago: float) -> datetime:
    return NOW - timedelta(days=days_ago)


# ---- 1. price raised before the sale ---------------------------------------------------

def test_price_raised_then_discounted_is_fake_even_on_day_two():
    points = [Point(at(2), 700), Point(at(0), 999, original=1200)]  # "17% off" a raised price
    r = analyze(points)
    assert r.verdict == "fake_discount"
    assert r.headline == "Fake discount. It was ৳700 on 7 Nov. Now it's ৳999 with “17% off”."
    assert r.reasons[0].startswith("The price went up from ৳700 on 7 Nov to ৳999.")
    assert (r.usual_price, r.real_off_pct) == (700, -42.7)


def test_price_rise_without_a_discount_is_mentioned_not_called_fake():
    r = analyze([Point(at(3), 700), Point(at(0), 800)])
    assert r.verdict == "unconfirmed"
    assert r.headline == "The price went up recently. It was ৳700 on 6 Nov."


def test_small_wobbles_are_not_price_rises():
    r = analyze([Point(at(3), 700), Point(at(0), 720, original=900)])
    assert not any("went up" in reason for reason in r.reasons)


def test_rise_noticed_with_a_long_history_too():
    points = [Point(at(d), 700) for d in range(20, 2, -2)] + [Point(at(1), 900), Point(at(0), 900, original=1100)]
    r = analyze(points)
    assert r.verdict == "fake_discount"
    assert any("went up from ৳700" in reason for reason in r.reasons)


# ---- 2. total cost: price + delivery ----------------------------------------------------

def seller(name, price, delivery=None, reviews=200, rating=4.6, **kw):
    return {"seller": name, "price": price, "delivery": delivery, "reviews": reviews, "rating": rating, **kw}


def test_free_delivery_beats_a_slightly_lower_price():
    out = rank([seller("Cheap but ৳120 delivery", 400, 120), seller("Free delivery", 450, 0)])
    assert [e["seller"] for e in out["ranked"]] == ["Free delivery", "Cheap but ৳120 delivery"]
    assert out["ranked"][0]["total"] == 450 and out["ranked"][1]["total"] == 520


def test_unknown_fee_assumes_the_typical_one():
    out = rank([seller("A", 500, 60), seller("B", 520, None), seller("C", 600, 60)])
    totals = {e["seller"]: e["total"] for e in out["ranked"]}
    assert totals == {"A": 560, "B": 580, "C": 660}


def test_verdict_counts_delivery_when_pointing_to_another_seller():
    from app.verdict import Report

    where = rank([seller("Them", 450, 0), seller("Us", 470, 60, is_this=True)])
    result = Report(verdict="fair", headline="", price=470)
    point_to_better_seller(result, where, "BDT")
    assert result.reasons[0].startswith("Them sells the same product for ৳450 with free delivery")
    # Same price difference, but their delivery makes them dearer in total: no hint.
    where = rank([seller("Them", 450, 120), seller("Us", 470, 0, is_this=True)])
    result = Report(verdict="fair", headline="", price=470)
    point_to_better_seller(result, where, "BDT")
    assert result.reasons == []


# ---- 4. "much cheaper than other sellers of this size" ----------------------------------

WARNING = "Much cheaper than other sellers of this size. Read the reviews before buying"


def notes(out, name):
    return next(e["notes"] for e in out["ranked"] + out["unproven"] if e["seller"] == name)


def test_far_cheaper_with_few_reviews_gets_a_careful_note():
    out = rank([seller("A", 690), seller("B", 700), seller("C", 720), seller("Too cheap", 300, reviews=2, rating=5)])
    assert WARNING in notes(out, "Too cheap")
    assert WARNING not in notes(out, "A")


def test_far_cheaper_but_well_reviewed_is_fine():
    out = rank([seller("A", 690), seller("B", 700), seller("C", 720), seller("Bargain", 300, reviews=500, rating=4.7)])
    assert WARNING not in notes(out, "Bargain")


def test_no_warning_without_enough_sellers_or_with_regular_prices():
    out = rank([seller("A", 700), seller("Cheap", 300, reviews=1)])
    assert WARNING not in notes(out, "Cheap")
    out = rank([seller("A", 1200, price_unconfirmed=True), seller("B", 1200, price_unconfirmed=True),
                seller("C", 700), seller("Cheap", 300, reviews=1)])
    assert WARNING not in notes(out, "Cheap")  # regular prices don't tell us what's usual
