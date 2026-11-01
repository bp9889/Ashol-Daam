"""Sample products so the site isn't empty on first run. They're clearly marked as samples.
Turn off with SEED_DEMO_DATA=0."""

from __future__ import annotations

import random
from statistics import median
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .market import MATCH_VERSION
from .models import MarketCheck, PriceSnapshot, Product


def _series(days, usual, noise, rng, overrides=None):
    """Daily prices around `usual`; `overrides` maps days-ago -> price."""
    overrides = overrides or {}
    out = []
    for ago in range(days, -1, -1):
        if ago in overrides:
            out.append((ago, overrides[ago]))
        else:
            out.append((ago, round(usual + rng.uniform(-noise, noise), -1)))
    return out


def _seller(seller, title, price, original=None, rating=None, reviews=0, sold=0, mall=False,
            overseas=False, free_shipping=False, is_this=False):
    return {"seller": seller, "title": title, "price": price, "original_price": original, "url": None,
            "rating": rating, "reviews": reviews, "sold": sold, "mall": mall, "overseas": overseas,
            "free_shipping": free_shipping, "delivery": 0.0 if free_shipping else 70.0,
            "is_this": is_this, "match_version": MATCH_VERSION}


# Made-up sellers for the sample steam iron, covering every case in the "where to buy" ranking.
STEAM_IRON_SELLERS = [
    _seller("Cheap Gadget Store", "Steam Iron 2200W Original Best Quality", 1599, 2999, rating=5.0, reviews=1, overseas=True),
    _seller("Budget House", "Steam Iron 2200 Watt", 1650, 2400, rating=3.1, reviews=47, sold=120),
    _seller("Home Needs BD", "Steam Iron 2200W Non-stick Soleplate", 1690, 2200),
    _seller("Electro Mart", "2200 Watt Steam Iron with Spray", 1720, rating=4.7, reviews=212, sold=1500, free_shipping=True),
    _seller("Daily Bazar Online", "Steam Iron 2200W, Self Clean", 1750, 1990, rating=4.5, reviews=64, sold=230),
    _seller("Ghorer Bazar Official", "Steam Iron 2200 W Anti-drip", 1850, 2100, rating=4.8, reviews=530, sold=2400, mall=True),
    _seller("Smart Home Shop", "Steam Iron 2200W Ceramic Plate", 1790, 2490, rating=4.4, reviews=18, sold=60, is_this=True),
]


def seed_demo(session: Session) -> None:
    rng = random.Random(1111)
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    pumped = {ago: 3999 for ago in range(4, 11)}
    pumped[0] = 2499
    samples = [
        # Price raised to ৳3,999 a week before the sale, then "50% off ৳4,999" back to ৳2,499.
        ("Wireless earbuds with noise cancelling", _series(75, 2450, 60, rng, pumped), {0: 4999}, None),
        # Genuinely cheaper than ever.
        ("1.8 litre electric rice cooker", _series(80, 3200, 80, rng, {0: 2690, 1: 3190}), {0: 3500}, None),
        # Always ~৳1,850, but always "50% off ৳3,700".
        ("Smart watch with heart-rate monitor", _series(70, 1850, 40, rng, {0: 1850}), "always:3700", None),
        # Normal everyday price.
        ("Waterproof laptop backpack, 30 litres", _series(60, 1450, 50, rng, {0: 1450}), {0: 1600}, None),
        # Just pasted, but 5 other sellers sell it: instant verdict.
        ("Steam iron, 2200 watt", [(0, 1790)], {0: 2490}, STEAM_IRON_SELLERS),
        # Just pasted, nobody else sells it: verdict from the page only.
        ("56 inch ceiling fan with remote", [(0, 3590)], {0: 7990}, []),
    ]

    for index, (title, series, originals, sellers) in enumerate(samples, start=1):
        external_id = f"sample-{index}"
        product = session.scalar(select(Product).where(Product.external_id == external_id, Product.is_demo.is_(True)))
        if product is None:
            product = Product(
                source="daraz",
                external_id=external_id,
                url="https://www.daraz.com.bd/",
                title=title,
                is_demo=True,
                created_at=now - timedelta(days=series[0][0]),
                last_checked_at=now,
            )
            for ago, price in series:
                if originals == "always:3700":
                    original = 3700
                else:
                    original = originals.get(ago, round(price * 1.12, -1))
                product.snapshots.append(
                    PriceSnapshot(price=price, original_price=original, captured_at=now - timedelta(days=ago))
                )
            session.add(product)
        elif sellers is not None and product.snapshots and len(product.snapshots) > 1:
            continue  # an older sample with history; leave it alone

        # Older sample databases have sellers without ratings; refresh them so the ranking shows.
        if sellers and product.market_checks and "reviews" not in (product.market_checks[-1].listings or [{}])[0]:
            product.market_checks.clear()
        if sellers is not None and not product.market_checks:
            prices = sorted(s["price"] for s in sellers if not s.get("is_this"))
            product.market_checks.append(
                MarketCheck(
                    query=title,
                    seller_count=len(prices),
                    median_price=median(prices) if prices else None,
                    low_price=prices[0] if prices else None,
                    high_price=prices[-1] if prices else None,
                    listings=sellers,
                    checked_at=now,
                )
            )
    session.commit()
