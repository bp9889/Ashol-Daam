"""Decides whether a discount is real. Every product gets a verdict straight away.

What the verdict is based on (`basis`), strongest first:
    history        - at least a week of this product's own prices
    other_sellers  - no history yet, but other sellers on Daraz sell the same product
    page           - nothing to compare with yet; only what the product page itself says

Verdicts:
    real_deal      - genuinely cheaper than usual / than other sellers
    fair           - the normal price; the "discount" is just the everyday price
    fake_discount  - the claimed discount is a trick (inflated "was" price, or price
                     pumped up shortly before the sale and then "discounted" back)
    overpriced     - other sellers sell the same thing for clearly less
    unconfirmed    - basis "page": we can't confirm the discount either way yet
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median

SYMBOLS = {"BDT": "৳", "PKR": "Rs ", "LKR": "Rs ", "NPR": "Rs "}

MIN_DAYS = 7
MIN_CHECKS = 4
PUMP_WINDOW_DAYS = 21


@dataclass
class Point:
    at: datetime
    price: float
    original: float | None = None


@dataclass
class Report:
    verdict: str
    headline: str
    reasons: list[str] = field(default_factory=list)
    price: float | None = None
    original_price: float | None = None
    usual_price: float | None = None
    lowest: float | None = None
    highest: float | None = None
    claimed_off_pct: float | None = None
    real_off_pct: float | None = None
    tracked_days: int = 0
    checks: int = 0
    basis: str = "page"
    sellers: int = 0
    sellers_median: float | None = None


@dataclass
class MarketInfo:
    count: int
    median: float | None
    low: float | None = None
    high: float | None = None
    listed: int = 0  # other listings of this size whose price we don't know for sure yet


def group_south_asian(value: float) -> str:
    """1234567 -> '12,34,567' (lakh/crore grouping, as used in Bangladesh)."""
    digits = str(int(round(value)))
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def money(value: float, currency: str = "BDT") -> str:
    return f"{SYMBOLS.get(currency, currency + ' ')}{group_south_asian(value)}"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


MARKET_MIN_SELLERS = 2
BIG_CLAIM = 40  # % off; on its own, a claim this big is a warning sign


def _instant(report: Report, market: MarketInfo | None, m) -> Report:
    """Verdict for a product without a week of history: compare with other sellers,
    or, failing that, judge only what the page says."""
    price, original, claimed_off = report.price, report.original_price, report.claimed_off_pct
    history_note = (
        f"We've checked this product {'once' if report.checks == 1 else f'{report.checks} times'} so far. "
        "After a week we'll also compare it with its own past prices."
    )

    if market and market.count >= MARKET_MIN_SELLERS and market.median:
        others = market.median
        report.basis = "other_sellers"
        report.usual_price = others
        report.real_off_pct = round(100 * (others - price) / others, 1)
        seller_line = f"{market.count} other sellers on Daraz sell it for about {m(others)}"
        if market.low and market.high and market.low != market.high:
            seller_line += f" ({m(market.low)} to {m(market.high)})"
        inflated = original is not None and original > others * 1.25

        if price <= others * 0.9:
            report.verdict = "real_deal"
            report.headline = f"Good price. It's {report.real_off_pct:.0f}% below what other sellers charge."
            report.reasons.append(seller_line + ".")
            if inflated:
                report.reasons.append(
                    f"Daraz shows an old price of {m(original)}, but that's exaggerated. Most sellers charge "
                    f"about {m(others)}, so you save less than the label says."
                )
        elif price > others * 1.1 and not (claimed_off and claimed_off >= 15):
            report.verdict = "overpriced"
            report.headline = f"Cheaper elsewhere. Other sellers charge about {m(others)}."
            report.reasons.append(seller_line + f", {m(price - others)} less than here.")
        elif claimed_off is not None and (claimed_off >= 15 or inflated):
            report.verdict = "fake_discount"
            if price > others * 1.05:
                report.headline = f"Fake discount. It says {claimed_off:.0f}% off, but other sellers sell it for less."
            else:
                report.headline = f"Fake discount. It says {claimed_off:.0f}% off, but that's the normal price."
            report.reasons.append(seller_line + ".")
            if inflated:
                report.reasons.append(
                    f"Daraz shows an old price of {m(original)}, but that's exaggerated. Most sellers charge "
                    f"about {m(others)}, so “{claimed_off:.0f}% off” isn't a real saving."
                )
        else:
            report.verdict = "fair"
            report.headline = "Normal price. Other sellers charge about the same."
            report.reasons.append(seller_line + ".")
        report.reasons.append(history_note)
        return report

    report.basis = "page"
    report.verdict = "unconfirmed"
    report.real_off_pct = None
    report.usual_price = None
    if claimed_off is not None and claimed_off >= BIG_CLAIM:
        report.headline = f"Be careful. {claimed_off:.0f}% off is unusually big. Often the old price is made up."
    elif claimed_off is not None:
        report.headline = f"It says {claimed_off:.0f}% off. We can't confirm that yet."
    else:
        report.headline = "No discount claimed. We can't compare the price yet."
    if market and market.count:
        known = "one other seller's price" if market.count == 1 else f"{market.count} other sellers' prices"
        report.reasons.append(f"So far we know {known} for this exact product. We need at least "
                              f"{MARKET_MIN_SELLERS} to work out the usual price.")
    elif market and market.listed:
        report.reasons.append("Other sellers list this size, but Daraz doesn't show their sale prices. "
                              "Press “Check its price” under “Where to buy” to add them.")
    else:
        report.reasons.append("We couldn't find other sellers of this exact product to compare prices with.")
    report.reasons.append(history_note)
    return report


def analyze(points: list[Point], currency: str = "BDT", market: MarketInfo | None = None) -> Report:
    if not points:
        return Report(verdict="unconfirmed", headline="No prices recorded yet.")

    points = sorted(points, key=lambda p: _aware(p.at))
    current = points[-1]
    now = _aware(current.at)
    m = lambda v: money(v, currency)  # noqa: E731

    last90 = [p.price for p in points if _aware(p.at) >= now - timedelta(days=90)]
    last30 = [p.price for p in points if _aware(p.at) >= now - timedelta(days=30)]
    usual = median(last30)
    lowest, highest = min(last90), max(last90)
    highest_ever = max(p.price for p in points)
    tracked_days = (now - _aware(points[0].at)).days

    price = current.price
    original = current.original if current.original and current.original > price else None
    claimed_off = round(100 * (original - price) / original, 1) if original else None
    real_off = round(100 * (usual - price) / usual, 1) if usual else None

    report = Report(
        verdict="fair",
        headline="",
        price=price,
        original_price=original,
        usual_price=round(usual, 2),
        lowest=lowest,
        highest=highest,
        claimed_off_pct=claimed_off,
        real_off_pct=real_off,
        tracked_days=tracked_days,
        checks=len(points),
        basis="history",
    )
    if market and market.count:
        report.sellers = market.count
        report.sellers_median = market.median

    rise = recent_rise(points)

    # Less than a week of our own prices: answer instantly from other sellers / the page.
    if tracked_days < MIN_DAYS or len(points) < MIN_CHECKS:
        return _flag_rise(_instant(report, market, m), rise, m)

    # Signals
    inflated = original is not None and highest_ever < original * 0.9
    recent = [
        p.price for p in points[:-1] if _aware(p.at) >= now - timedelta(days=PUMP_WINDOW_DAYS)
    ]
    pumped = bool(recent) and max(recent) > usual * 1.10 and price >= usual * 0.97
    at_low = price <= lowest * 1.01
    genuinely_cheaper = real_off is not None and (real_off >= 10 or (at_low and real_off >= 5))

    if genuinely_cheaper:
        report.verdict = "real_deal"
        report.headline = f"Real deal. It's {real_off:.0f}% below its usual price."
        report.reasons.append(f"It usually sells for about {m(usual)}. Today it's {m(price)}.")
        if at_low:
            report.reasons.append(f"This is the lowest price we've seen in {min(tracked_days, 90)} days.")
        if inflated:
            report.reasons.append(
                f"Daraz shows an old price of {m(original)}, but that's exaggerated. We never saw it sell above {m(highest_ever)}."
            )
    elif inflated or pumped or (claimed_off is not None and claimed_off >= 15):
        report.verdict = "fake_discount"
        if claimed_off is not None and (real_off or 0) < 1:
            report.headline = f"Fake discount. It says {claimed_off:.0f}% off, but it's no cheaper than usual."
        elif claimed_off is not None:
            report.headline = f"Fake discount. It says {claimed_off:.0f}% off, but it's really {real_off:.0f}%."
        else:
            report.headline = "Fake discount. The price was raised before being cut back to normal."
        if inflated:
            report.reasons.append(
                f"Daraz shows an old price of {m(original)}, but in {tracked_days} days it never sold above {m(highest_ever)}."
            )
        if pumped:
            report.reasons.append(
                f"The price went up to {m(max(recent))} in the last {PUMP_WINDOW_DAYS} days, "
                f"then came back down to about its usual {m(usual)}."
            )
        if not inflated and not pumped:
            report.reasons.append(f"{m(price)} is what it normally costs. The usual price is about {m(usual)}.")
    else:
        report.verdict = "fair"
        report.headline = "Normal price. Not a special deal, but not a trick either."
        report.reasons.append(f"It usually sells for about {m(usual)}, and today it's {m(price)}.")
        if price > lowest * 1.05:
            report.reasons.append(f"It has been as low as {m(lowest)}. Waiting might pay off.")

    # Other sellers add context to a history-based verdict.
    if market and market.count >= MARKET_MIN_SELLERS and market.median:
        if price > market.median * 1.1:
            report.reasons.append(f"Other sellers on Daraz sell it for about {m(market.median)}, less than here.")
        elif price < market.median * 0.9:
            report.reasons.append(f"Other sellers on Daraz charge about {m(market.median)}, so this is cheaper.")
        else:
            report.reasons.append(f"Other sellers on Daraz charge about the same ({m(market.median)}).")

    return _flag_rise(report, rise, m)


RISE_WINDOW_DAYS = 30
RISE_SHARE = 1.05  # 5% or more above its recent low counts as a price rise


def recent_rise(points: list[Point]) -> tuple[float, datetime] | None:
    """Has the price gone UP lately? Sellers often raise prices in the days before a big sale
    (11.11, 12.12), so the "discount" on sale day is taken off a raised price.
    Returns (the recent lower price, when it was last that low), or None."""
    if len(points) < 2:
        return None
    points = sorted(points, key=lambda p: _aware(p.at))
    now, price = _aware(points[-1].at), points[-1].price
    earlier = [p for p in points[:-1] if _aware(p.at) >= now - timedelta(days=RISE_WINDOW_DAYS)]
    if not earlier:
        return None
    low = min(p.price for p in earlier)
    if price < low * RISE_SHARE:
        return None
    when = max(_aware(p.at) for p in earlier if p.price == low)
    return low, when


def _flag_rise(report: Report, rise: tuple[float, datetime] | None, m) -> Report:
    if rise is None or report.verdict == "real_deal" or report.price is None:
        return report
    low, when = rise
    day = f"{when.day} {when:%b}"
    claimed = report.claimed_off_pct
    report.reasons.insert(0, f"The price went up from {m(low)} on {day} to {m(report.price)}. Sellers often "
                             "raise prices before a sale, so wait if you can.")
    if claimed is not None and claimed >= 10:
        report.verdict = "fake_discount"
        if report.basis == "page":
            report.basis = "history"
        report.headline = f"Fake discount. It was {m(low)} on {day}. Now it's {m(report.price)} with “{claimed:.0f}% off”."
        if report.real_off_pct is None:  # no usual price yet: measure against the recent lower price
            report.usual_price = low
            report.real_off_pct = round(100 * (low - report.price) / low, 1)
    elif report.verdict == "unconfirmed":
        report.headline = f"The price went up recently. It was {m(low)} on {day}."
    return report
