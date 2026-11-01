from datetime import datetime, timedelta, timezone

from app.verdict import MarketInfo, Point, analyze

NOW = datetime(2026, 11, 11, 12, tzinfo=timezone.utc)


def daily(prices, original=None):
    """prices[0] is the oldest, prices[-1] is today."""
    n = len(prices)
    return [
        Point(at=NOW - timedelta(days=n - 1 - i), price=p, original=(original[i] if isinstance(original, list) else original))
        for i, p in enumerate(prices)
    ]


def test_unconfirmed_without_history_or_sellers():
    r = analyze(daily([2000, 1990, 1800], original=2500))
    assert r.verdict == "unconfirmed"
    assert r.basis == "page"
    assert r.claimed_off_pct == 28.0
    assert "can't confirm" in r.headline


def test_big_claim_on_day_one_is_a_warning():
    r = analyze(daily([3590], original=7990))
    assert r.verdict == "unconfirmed"
    assert r.headline.startswith("Be careful. 55% off")


# ---- instant verdicts from other sellers (day one) ----

def test_day_one_fake_discount_from_other_sellers():
    r = analyze(daily([1790], original=2490), market=MarketInfo(count=5, median=1750, low=1690, high=1850))
    assert r.basis == "other_sellers"
    assert r.verdict == "fake_discount"
    assert "that's the normal price" in r.headline
    assert "5 other sellers on Daraz sell it for about ৳1,750 (৳1,690 to ৳1,850)" in r.reasons[0]


def test_day_one_good_price_from_other_sellers():
    r = analyze(daily([1500], original=2000), market=MarketInfo(count=3, median=1800))
    assert r.verdict == "real_deal"
    assert r.real_off_pct == 16.7


def test_day_one_cheaper_elsewhere():
    r = analyze(daily([2400]), market=MarketInfo(count=4, median=2000))
    assert r.verdict == "overpriced"
    assert "৳400 less than here" in r.reasons[0]


def test_day_one_claims_discount_but_costs_more_than_others():
    r = analyze(daily([2400], original=3200), market=MarketInfo(count=4, median=2000))
    assert r.verdict == "fake_discount"
    assert "sell it for less" in r.headline


def test_one_seller_is_not_enough():
    r = analyze(daily([1790], original=2490), market=MarketInfo(count=1, median=None))
    assert r.basis == "page"


def test_history_wins_once_there_is_a_week_of_it():
    r = analyze(daily([3200] * 40 + [2690], original=3500), market=MarketInfo(count=3, median=2700))
    assert r.basis == "history"
    assert r.verdict == "real_deal"
    assert any("Other sellers on Daraz charge about the same" in reason for reason in r.reasons)


def test_inflated_original_price_is_fake():
    r = analyze(daily([1850] * 40, original=3700))
    assert r.verdict == "fake_discount"
    assert r.claimed_off_pct == 50.0
    assert r.real_off_pct == 0.0


def test_price_pumped_before_sale_is_fake():
    prices = [2450] * 30 + [3999] * 7 + [2499]
    r = analyze(daily(prices, original=[2700] * 37 + [4999]))
    assert r.verdict == "fake_discount"
    assert any("went up to ৳3,999" in reason for reason in r.reasons)


def test_genuine_drop_is_a_real_deal():
    r = analyze(daily([3200] * 40 + [2690], original=3500))
    assert r.verdict == "real_deal"
    assert r.real_off_pct > 10


def test_everyday_price_is_fair():
    r = analyze(daily([1450] * 30, original=1600))
    assert r.verdict == "fair"
