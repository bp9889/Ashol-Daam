from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

from sqlalchemy.orm import Session, object_session

from . import config
from .adapters import Adapter, AdapterError, ProductData, get_adapter
from statistics import median

from .market import MATCH_VERSION, MIN_SELLERS, comparable, compare, rank, size_lookups, wants_size
from .models import Alert, MarketCheck, PriceSnapshot, Product, Visit
from .verdict import MarketInfo, Point, analyze, money

log = logging.getLogger("asol_dam.services")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def recently_checked(product: Product, hours: float | None = None) -> bool:
    hours = config.MIN_REFRESH_HOURS if hours is None else hours
    last = _aware(product.last_checked_at)
    return last is not None and datetime.now(timezone.utc) - last < timedelta(hours=hours)


def find_product(session: Session, source: str, external_id: str) -> Product | None:
    return session.scalar(select(Product).where(Product.source == source, Product.external_id == external_id))


def latest_market(product: Product) -> MarketCheck | None:
    return product.market_checks[-1] if product.market_checks else None


def market_outdated(product: Product) -> bool:
    """Seller lists saved with older matching rules (before photos, sizes…) get rebuilt."""
    last = latest_market(product)
    return bool(last and last.listings and last.listings[0].get("match_version") != MATCH_VERSION)


KNOWN_PRICE_DAYS = 3  # a price someone confirmed on this site is trusted for this long


def known_prices(session: Session | None, ids: set[str], skip: str | None = None) -> dict[str, PriceSnapshot]:
    """Latest price of each listing (one size/option) that someone checked on THIS site recently.
    Daraz doesn't publish every size's sale price, but people type or confirm it here, so a price
    confirmed for one listing helps everyone comparing other listings of the same product.
    Only products saved with size support (`variant` not None) count: older saves could hold the
    price of a different size."""
    ids = {i for i in ids if i and i != skip}
    if session is None or not ids:
        return {}
    since = datetime.now(timezone.utc) - timedelta(days=KNOWN_PRICE_DAYS)
    found = {}
    for product in session.scalars(select(Product).where(Product.external_id.in_(ids), Product.is_demo.is_(False))):
        latest = product.snapshots[-1] if product.snapshots else None
        if product.variant is not None and latest and _aware(latest.captured_at) >= since:
            found[product.external_id] = latest
    return found


def _use_known(listing, snapshot: PriceSnapshot):
    original = float(snapshot.original_price) if snapshot.original_price else None
    price = float(snapshot.price)
    return replace(listing, price=price, original_price=original if original and original > price else None,
                   price_unconfirmed=False, size_checked=True,
                   confirmed_at=_aware(snapshot.captured_at).isoformat())


def check_sizes(session: Session, product: Product, adapter: Adapter, results: list, price: float) -> list:
    """Replace multi-size listings with the option for our size (see market.size_lookups)."""
    picks = size_lookups(product.title, price, product.external_id, results, product.variant)
    if not picks:
        return results
    wanted = wants_size(product.title, product.variant)

    def look(listing):
        try:
            return adapter.size_option(listing, wanted)
        except AdapterError as exc:
            log.info("Couldn't open %s to check its size: %s", listing.url, exc)
            return None

    with ThreadPoolExecutor(max_workers=3) as pool:
        narrowed = dict(zip((id(r) for r in picks), pool.map(look, picks)))
    out = []
    for r in results:
        if id(r) not in narrowed:
            out.append(r)
        elif narrowed[id(r)] is not None:
            out.append(narrowed[id(r)])
        # else: doesn't sell our size (or couldn't be opened), so it's left out

    return out


PAGES_PER_CHECK = 6  # pages the hidden browser opens per seller comparison, at most


def read_pages(product: Product, adapter: Adapter, results: list, price: float) -> tuple[list, float | None]:
    """Open the pages worth opening in the hidden browser, all in one go:
    our own page (its delivery fee), sizes whose sale price isn't in the page data, and the
    cheapest matching sellers whose delivery fee we don't know. Returns (listings, our fee)."""
    own_item = product.external_id.split("-")[0]
    matches = [r for r in results if r.url and r.external_id.split("-")[0] != own_item
               and comparable(product.title, price, r, product.variant)]
    need_price = [r for r in matches if r.price_unconfirmed]
    need_fee = sorted((r for r in matches if not r.price_unconfirmed and r.delivery is None), key=lambda r: r.price)
    own = [product.url] if product.delivery is None else []  # our own fee, unless already known
    urls = own + [r.url for r in need_price + need_fee][: PAGES_PER_CHECK - len(own)]
    if not urls:
        return results, None
    seen = adapter.see_prices(urls)
    if not seen:
        return results, None
    wanted = wants_size(product.title, product.variant)
    out = []
    for r in results:
        shown = seen.get(r.url) if r.url in urls[len(own):] else None
        if shown is not None:
            if r.price_unconfirmed and (shown.option is None or wanted(shown.option)):
                r = replace(r, price=shown.price, original_price=shown.original, price_unconfirmed=False)
            if shown.delivery is not None:
                r = replace(r, delivery=shown.delivery)
        out.append(r)
    mine = seen.get(product.url)
    return out, (mine.delivery if mine else None)


def update_market(session: Session, product: Product, adapter: Adapter, force: bool = False,
                  detailed: bool = True) -> MarketCheck | None:
    """Search the store for the same product from other sellers (at most once per MARKET_REFRESH_HOURS).
    Never raises: if search fails, the verdict simply falls back to what the page says.

    detailed=False is the quick version (one search, a few seconds) used when you paste a link;
    detailed=True also opens sellers' pages: sizes, sale prices and delivery fees (10–30 s)."""
    last = latest_market(product)
    if last and not force and not market_outdated(product):
        age = datetime.now(timezone.utc) - _aware(last.checked_at)
        if age < timedelta(hours=config.MARKET_REFRESH_HOURS) and (last.detailed or not detailed):
            return last
    current = product.snapshots[-1] if product.snapshots else None
    if current is None:
        return last
    try:
        from .market import build_query

        results = adapter.search(build_query(product.title), product.url)
    except AdapterError as exc:
        log.warning("Couldn't compare %s with other sellers: %s", product.id, exc)
        return last
    own_fee = None
    if detailed:
        results = check_sizes(session, product, adapter, results, float(current.price))
        results, own_fee = read_pages(product, adapter, results, float(current.price))
        if own_fee is not None:
            product.delivery = own_fee
    if own_fee is None and product.delivery is not None:
        own_fee = float(product.delivery)
    # Still unsure? Use a price someone confirmed on this site recently.
    known = known_prices(session, {r.external_id for r in results if r.price_unconfirmed}, skip=product.external_id)
    results = [_use_known(r, known[r.external_id]) if r.external_id in known else r for r in results]
    market = compare(product.title, float(current.price), product.external_id, results,
                     variant=product.variant,
                     own_original=float(current.original_price) if current.original_price else None,
                     own_delivery=own_fee)
    check = MarketCheck(
        query=market.query,
        seller_count=market.count,
        median_price=market.median,
        low_price=market.low,
        high_price=market.high,
        listings=market.listings,
        detailed=detailed,
    )
    product.market_checks.append(check)
    session.commit()
    return check


def save_snapshot(session: Session, data: ProductData, adapter: Adapter | None = None,
                  detailed: bool = True) -> Product:
    """Create the product if it's new, update its details, record today's price,
    compare with other sellers (if an adapter is given) and send any alerts."""
    product = find_product(session, data.source, data.external_id)
    if product is None:
        product = Product(source=data.source, external_id=data.external_id, url=data.url, title=data.title)
        session.add(product)
    product.url = data.url
    product.title = data.title
    product.image_url = data.image_url or product.image_url
    if data.delivery is not None:
        product.delivery = data.delivery
    product.variant = data.variant or ""  # "" = read with size support, has no options; None = saved before it
    product.currency = data.currency
    product.last_checked_at = datetime.now(timezone.utc)
    product.snapshots.append(
        PriceSnapshot(price=data.price, original_price=data.original_price, in_stock=data.in_stock)
    )
    session.commit()
    session.refresh(product)

    if adapter is not None:
        update_market(session, product, adapter, detailed=detailed)

    # Tell people whose alerts this new price triggers.
    from . import alerts  # local import avoids a cycle

    try:
        alerts.check_product(session, product, report(product)["verdict"])
    except Exception:  # an alert problem must never lose the price we just saved
        logging.getLogger("asol_dam.alerts").exception("Alert check failed for product %s", product.id)
    return product


def track(session: Session, url: str, manual_price: float | None = None) -> Product:
    """Start tracking a link, or return the existing product if it was checked recently."""
    # Sharing from the Daraz app copies a sentence with the link in it; take just the link.
    found = re.search(r"https?://\S+", url)
    url = (found.group(0) if found else url).strip().rstrip(".,;)")
    if not url.startswith("http"):
        url = "https://" + url
    adapter = get_adapter(url)
    try:
        existing = find_product(session, adapter.source, adapter.product_key(url))
    except AdapterError:
        existing = None  # e.g. a short share link: we only learn the id after following it
    # Saved before sizes were understood (no `variant`) but the link picks a size: read it again once.
    stale_size = existing is not None and not existing.is_demo and existing.variant is None and "-s" in existing.external_id
    if existing and recently_checked(existing) and not manual_price and not stale_size:
        if not existing.is_demo:
            update_market(session, existing, adapter, detailed=False)  # no-op unless the comparison is old
        return existing
    # Quick: the verdict comes back in seconds. The page then asks for details (add_details).
    return save_snapshot(session, adapter.fetch(url, manual_price), adapter, detailed=False)


def refresh(session: Session, product: Product, force: bool = False, detailed: bool = True) -> Product:
    if product.is_demo or (recently_checked(product) and not force):
        return product
    adapter = get_adapter(product.url)
    return save_snapshot(session, adapter.fetch(product.url), adapter, detailed=detailed)


def add_details(session: Session, product: Product) -> Product:
    """Second step after a quick check: open sellers' pages for sizes, sale prices and delivery fees.
    Does nothing if that was done recently."""
    if not product.is_demo:
        update_market(session, product, get_adapter(product.url), detailed=True)
    return product


def market_info(product: Product, listings: list[dict] | None = None) -> MarketInfo | None:
    """What other sellers charge. Worked out from the listings themselves (when they carry ids),
    so prices confirmed on this site since the last search count too."""
    check = latest_market(product)
    if check is None:
        return None
    as_float = lambda v: float(v) if v is not None else None  # noqa: E731
    others = [l for l in (listings or []) if not l.get("is_this")]
    if not others or not all("id" in l for l in others):
        # Older saved lists (or samples): use the numbers stored with the search.
        return MarketInfo(count=check.seller_count, median=as_float(check.median_price),
                          low=as_float(check.low_price), high=as_float(check.high_price))
    prices = sorted(float(l["price"]) for l in others if not l.get("price_unconfirmed"))
    enough = len(prices) >= MIN_SELLERS
    return MarketInfo(
        count=len(prices),
        median=round(median(prices), 2) if enough else None,
        low=prices[0] if enough else None,
        high=prices[-1] if enough else None,
        listed=len(others) - len(prices),
    )


def report(product: Product) -> dict:
    points = [
        Point(at=s.captured_at, price=float(s.price), original=float(s.original_price) if s.original_price else None)
        for s in product.snapshots
    ]
    check = latest_market(product)
    listings = with_known_prices(product, check.listings or []) if check is not None else []
    if product.delivery is not None:
        listings = [dict(l, delivery=float(product.delivery)) if l.get("is_this") and l.get("delivery") is None else l
                    for l in listings]
    result = analyze(points, product.currency, market_info(product, listings))
    latest = product.snapshots[-1] if product.snapshots else None
    where = rank(listings) if check is not None else {"ranked": [], "unproven": []}
    point_to_better_seller(result, where, product.currency)
    return {
        "id": product.id,
        "source": product.source,
        "title": product.title,
        "url": product.url,
        "image_url": product.image_url,
        "variant": product.variant or None,
        "delivery": float(product.delivery) if product.delivery is not None else None,
        "currency": product.currency,
        "is_demo": product.is_demo,
        "in_stock": latest.in_stock if latest else True,
        "last_checked_at": _aware(product.last_checked_at).isoformat() if product.last_checked_at else None,
        "verdict": result.__dict__,
        "history": [
            {"at": _aware(p.at).isoformat(), "price": p.price, "original": p.original} for p in points
        ],
        "market": None
        if check is None
        else {
            "checked_at": _aware(check.checked_at).isoformat(),
            "count": check.seller_count,
            "median": float(check.median_price) if check.median_price is not None else None,
            "low": float(check.low_price) if check.low_price is not None else None,
            "high": float(check.high_price) if check.high_price is not None else None,
            "listings": listings,
            "detailed": bool(check.detailed),
            # Ranked fresh each time, so tuning the formula in market.py applies to stored data too.
            "where_to_buy": where,
        },
    }


def with_known_prices(product: Product, listings: list[dict]) -> list[dict]:
    """Prices confirmed on this site AFTER the seller list was built (e.g. you just checked the
    other listing and typed its sale price) are shown straight away, without a new search."""
    if product.is_demo:
        return listings
    known = known_prices(object_session(product), {l.get("id") for l in listings if not l.get("is_this")},
                         skip=product.external_id)
    check = latest_market(product)
    built = _aware(check.checked_at) if check is not None and check.checked_at else None
    out = []
    for l in listings:
        snap = known.get(l.get("id"))
        newer = snap is not None and (built is None or _aware(snap.captured_at) > built)
        if (snap is not None and not l.get("is_this") and (l.get("price_unconfirmed") or newer)
                and _aware(snap.captured_at).isoformat() != l.get("confirmed_at")):
            price = float(snap.price)
            original = float(snap.original_price) if snap.original_price else None
            l = dict(l, price=price, original_price=original if original and original > price else None,
                     price_unconfirmed=False, confirmed_at=_aware(snap.captured_at).isoformat())
        out.append(l)
    return out


def point_to_better_seller(result, where: dict, currency: str) -> None:
    """If a trusted seller sells the same product for clearly less, say so in the verdict,
    so the verdict and the "Where to buy" list never disagree."""
    best = where["ranked"][0] if where.get("ranked") else None
    price = result.price
    if not best or best.get("is_this") or best.get("price_unconfirmed") or price is None:
        return
    # Compare what you'd actually pay: price + delivery (same fee assumed when ours is unknown).
    mine = next((l for l in where.get("ranked", []) + where.get("unproven", []) if l.get("is_this")), None)
    their_fee = best.get("delivery")
    our_fee = mine.get("delivery") if mine else None
    if our_fee is None or their_fee is None:
        our_fee = their_fee = 0.0
    if best["price"] + their_fee > (price + our_fee) * 0.97:
        return
    who = best.get("seller") or "Another seller"
    trust = f"{best['rating']:.1f}★ from {best['reviews']:,} reviews" if best.get("rating") and best.get("reviews") else "an official store"
    cost = money(best["price"], currency)
    if best.get("delivery"):
        cost += f" + {money(best['delivery'], currency)} delivery"
    elif best.get("delivery") == 0:
        cost += " with free delivery"
    result.reasons.insert(0, f"{who} sells the same product for {cost} ({trust}). See “Where to buy”.")
    if result.verdict == "real_deal":
        # Still cheaper than usual, so the verdict stays, but the headline points to the better buy.
        result.headline = f"Good price, but {who} has it for even less: {money(best['price'], currency)}."


def summary(product: Product) -> dict:
    """Lighter version for the list of tracked products (sparkline only needs prices)."""
    full = report(product)
    full["history"] = [h["price"] for h in full["history"]][-60:]
    full["market"] = None
    return full


# ---- Each visitor's own "Recently checked" list -------------------------------------------


def remember(session: Session, visitor: str, product: Product) -> None:
    """Put the product on this visitor's list (or move it to the top)."""
    if product.is_demo:
        return
    visit = session.scalar(select(Visit).where(Visit.visitor == visitor, Visit.product_id == product.id))
    if visit is None:
        session.add(Visit(visitor=visitor, product_id=product.id))
    else:
        visit.added_at = datetime.now(timezone.utc)
    session.commit()


def visitor_products(session: Session, visitor: str) -> list[Product]:
    """This visitor's checked products, newest first, then the sample products (if any)."""
    mine = session.scalars(
        select(Product).join(Visit, Visit.product_id == Product.id)
        .where(Visit.visitor == visitor).order_by(Visit.added_at.desc())
    ).all()
    samples = session.scalars(select(Product).where(Product.is_demo.is_(True)).order_by(Product.id)).all()
    return list(mine) + list(samples)


def forget(session: Session, visitor: str, product: Product) -> bool:
    """Take a product off this visitor's list. If nobody else has it on their list and nobody has an
    alert on it, delete it (and its price history) too. False if it wasn't on their list."""
    visit = session.scalar(select(Visit).where(Visit.visitor == visitor, Visit.product_id == product.id))
    if visit is None:
        return False
    session.delete(visit)
    session.flush()
    others = session.scalar(select(Visit.id).where(Visit.product_id == product.id).limit(1))
    alerts = session.scalar(select(Alert.id).where(Alert.product_id == product.id).limit(1))
    if others is None and alerts is None:
        session.delete(product)
    session.commit()
    return True
