"""Finds the same product from other sellers, so a verdict is possible on day one.

Daraz titles are noisy ("NEW Original Redmi Buds 6 Active TWS Bluetooth 5.4 Earbuds Best Quality"),
so we:
  1. build a short search query from the title's most meaningful words,
  2. keep results whose titles share most of those words,
  3. drop results with a very different price (accessories, cases, bundles),
  4. summarise what's left: median, lowest, highest.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from statistics import median

from .adapters import Listing

# Words that say nothing about *which* product it is.
NOISE = {
    "new", "original", "best", "quality", "premium", "hot", "sale", "offer", "latest", "top", "brand",
    "genuine", "authentic", "official", "high", "super", "free", "delivery", "shipping", "combo",
    "for", "with", "and", "the", "a", "an", "of", "in", "to", "on", "by", "pcs", "pc", "piece",
    "bd", "bangladesh", "edition", "version", "model", "type", "style", "fashion", "trendy",
    "100", "copy", "master", "imported", "china", "made", "good", "mini", "pro",
}
# "pro" and "mini" can matter, but they are also slapped on everything; they still count
# when they appear in the query below, because we only drop them from the *query*.
NOISE.discard("pro")
NOISE.discard("mini")

# Words are letters/digits; a dot inside a number stays ("5.4", "1.8"). Hyphens split words,
# so "Fragrance-50ml" becomes "fragrance" + "50ml".
TOKEN = re.compile(r"[a-z]*\d+\.\d+[a-z]*|[a-z0-9]+")

# Sizes are written many ways ("50 ml", "50ML", "2200 Watt", "1.8 Litre"). Glue the number to a
# standard unit so the same size always becomes the same word ("50ml", "2200w", "1.8l").
UNITS = {
    "ml": "ml", "l": "l", "ltr": "l", "litre": "l", "liter": "l", "litres": "l", "liters": "l",
    "g": "g", "gm": "g", "gram": "g", "grams": "g", "kg": "kg", "mg": "mg",
    "gb": "gb", "tb": "tb", "mb": "mb", "mah": "mah",
    "w": "w", "watt": "w", "watts": "w", "v": "v", "volt": "v",
    "inch": "inch", "inches": "inch", "mm": "mm", "cm": "cm",
}
SIZE = re.compile(r"(\d+(?:\.\d+)?)\s*(" + "|".join(sorted(UNITS, key=len, reverse=True)) + r")\b")

QUERY_WORDS = 6
MIN_MATCH = 0.66          # share of key words a result must contain (4 of 6)
PRICE_BAND = (0.45, 2.2)  # results outside this × our price are other things
MIN_SELLERS = 2           # need at least this many comparable listings


def normalise(title: str) -> str:
    text = title.lower().replace('"', " inch ")
    return SIZE.sub(lambda m: m.group(1) + UNITS[m.group(2)], text)


def tokens(title: str) -> list[str]:
    words = TOKEN.findall(normalise(title))
    seen, out = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out


def key_words(title: str, limit: int = QUERY_WORDS) -> list[str]:
    words = [w for w in tokens(title) if w not in NOISE and (len(w) > 1 or w.isdigit())]
    return words[:limit]


def match_words(title: str) -> list[str]:
    """Words another listing's title must share with ours. Sizes are left out: titles list sizes
    loosely ("15 ml … 3ml/6ml/12ML/30ml"), and the size is checked separately."""
    words = [w for w in key_words(title, limit=40) if not SIZE_WORD.fullmatch(w)]
    return words[:QUERY_WORDS]


SEARCH_WORDS = 5
SIZE_WORD = re.compile(r"\d+(?:\.\d+)?(?:" + "|".join(sorted(set(UNITS.values()), key=len, reverse=True)) + r")")


def build_query(title: str) -> str:
    """The words we type into the store's search box. Deliberately loose: sizes ("50ml") and
    percentages ("5% AHA") are left out, because the store's search is picky about them and can
    hide the very listings we want. Sizes are checked afterwards in `same_model`."""
    text = re.sub(r"\d+(?:\.\d+)?\s*%", " ", title)
    words = [w for w in key_words(text, limit=20) if not SIZE_WORD.fullmatch(w)]
    query = words[:SEARCH_WORDS]
    # Add what kind of item it is ("cover"), so the search returns covers, not every accessory
    # for that phone.
    kind = next((w for w in tokens(title) if any(w in names for names in KINDS.values())), None)
    if kind and kind not in query:
        query.append(kind)
    return " ".join(query)


def exact_query(title: str) -> str | None:
    """A longer search, for accessories: finds other sellers of exactly this item ("… soft high
    hardness technology eouro silicone back cover"), which the short search can miss."""
    if not kinds_in(title):
        return None
    words = [w for w in key_words(re.sub(r"\d+(?:\.\d+)?\s*%", " ", title), limit=40)
             if not SIZE_WORD.fullmatch(w)]
    query = " ".join(words[:10])
    return query if query != build_query(title) else None


@dataclass
class Market:
    query: str
    count: int
    median: float | None
    low: float | None
    high: float | None
    listings: list[dict]

    def as_dict(self) -> dict:
        return asdict(self)


# Words that turn one model into a different (usually pricier) one.
VARIANTS = {"pro", "max", "plus", "ultra", "lite", "mini", "se", "neo", "prime", "air", "fe"}


def similarity(query_words: list[str], title: str) -> float:
    if not query_words:
        return 0.0
    words = set(tokens(title))
    return sum(1 for w in query_words if w in words) / len(query_words)


def same_model(our_title: str, query_words: list[str], other_title: str) -> bool:
    """Model numbers (words with digits, like "6", "a15", "t110") must all match,
    and the other listing can't add or drop a variant word like "Pro" or "Lite"."""
    ours, theirs = set(tokens(our_title)), set(tokens(other_title))
    # Sizes ("30ml") are checked separately, against the option actually being sold.
    model_numbers = [w for w in query_words if any(c.isdigit() for c in w) and not SIZE_WORD.fullmatch(w)]
    if any(w not in theirs for w in model_numbers):
        return False
    return (ours & VARIANTS) == (theirs & VARIANTS)


# Kinds of item. Titles for accessories repeat the phone's name ("Nothing CMF Phone 2 Pro Camera Lens
# Protector"), so the model words match; the kind of item must match too. Words in one group mean
# the same kind; a listing is a different product if it shares no kind with ours.
KINDS = {
    # Words that clearly name a kind of item. Ambiguous ones are left out on purpose: "glass" (phones
    # say "Gorilla Glass"), "band" ("Mi Band 8"), "skin" (skin care), "replacement" (warranty text).
    "case": {"case", "cover", "pouch", "bumper", "backcover", "casing"},
    "protector": {"protector", "tempered", "film", "guard"},
    "charger": {"charger", "adapter", "adaptor"},
    "cable": {"cable", "cord"},
    "strap": {"strap", "belt"},
    "holder": {"holder", "stand", "mount", "tripod"},
    "sticker": {"sticker", "decal"},
    "refill": {"refill", "cartridge"},
}


def kinds_in(title: str) -> set[str]:
    words = set(tokens(title))
    return {kind for kind, names in KINDS.items() if words & names}


def same_kind(ours: str, theirs: str) -> bool:
    """A case is never compared with a screen protector. A product named without any accessory word
    (a phone, earbuds) is never compared with accessories for it ("case for Redmi Buds 6")."""
    a, b = kinds_in(ours), kinds_in(theirs)
    if a and b:
        return bool(a & b)
    return a == b  # both plain products, or both... (one side an accessory, the other not -> False)


PACK = re.compile(r"(?:pack|set|combo|box)\s*of\s*(\d+)|(\d+)\s*(?:pcs|pc|pieces|piece|pack|packs|pk|units)\b")


def pack_size(title: str) -> int:
    """'2 pcs', 'pack of 3', '3 Pack' -> 2, 3, 3. Anything else is 1."""
    match = PACK.search(title.lower())
    if not match:
        return 1
    count = int(match.group(1) or match.group(2))
    return count if 1 <= count <= 100 else 1


IDENTITY_WORDS = 4      # the rarest words of our title that identify the accessory itself
COMMON_SHARE = 0.5      # words in at least half the search results don't identify anything


def identity_words(title: str, results: list[Listing]) -> list[str]:
    """For accessories only. Every result for "Nothing CMF Phone 2 Pro cover" repeats the phone's
    name, so those words can't tell one cover from another. The words that do are the rare ones in
    our title ("eouro", "hardness"). Returns up to 4 of them, rarest first (or [] = no such check)."""
    if not kinds_in(title) or len(results) < 5:
        return []
    docs = [set(tokens(r.title)) for r in results]
    count = {w: sum(1 for d in docs if w in d) for w in tokens(title)}
    kind_words = set().union(*KINDS.values())
    rare = [w for w in tokens(title)
            if w not in NOISE and w not in kind_words and len(w) > 1 and not SIZE_WORD.fullmatch(w)
            and count[w] / len(docs) < COMMON_SHARE]
    rare.sort(key=lambda w: count[w])
    return rare[:IDENTITY_WORDS] if len(rare) >= 2 else []


def same_identity(identity: list[str], other_title: str) -> bool:
    """At least half of our identifying words appear in the other title."""
    if not identity:
        return True
    words = set(tokens(other_title))
    return sum(1 for w in identity if w in words) >= (len(identity) + 1) // 2


def same_category(ours: tuple[str, ...], theirs: tuple[str, ...], strong_match: bool) -> bool:
    """Same Daraz category (most specific level). Sellers sometimes file the same thing one level
    off (earbuds under 'Headphones' vs 'Wireless earbuds'); that's allowed only with an exact title
    match, never for the same phone's other accessories."""
    if not ours or not theirs:
        return True  # unknown: the other checks decide
    if ours[-1] == theirs[-1]:
        return True
    if not strong_match:
        return False
    if len(ours) == 1 or len(theirs) == 1:
        return True  # we don't know the level above, so the exact title match decides
    return ours[-2] == theirs[-2]


def sizes_in(text: str | None) -> set[str]:
    """Sizes mentioned in a title or option name: "50ml", "1.8l", "2200w"…"""
    return {w for w in tokens(text or "") if SIZE_WORD.fullmatch(w)}


def our_size(title: str, variant: str | None = None) -> str | None:
    """The size we're comparing. The chosen option wins ("30 ML Spray" -> "30ml"); otherwise the
    title, but only if it names exactly one size ("…Available in 100ML, 50ML, 30ML" names many)."""
    for text in (variant, title):
        found = sizes_in(text)
        if len(found) == 1:
            return next(iter(found))
        if text is variant and variant and found:
            return None
    return None


MAX_SIZE_LOOKUPS = 5  # multi-size listings we open per check, to find the price of our size


def size_lookups(title: str, price: float, own_id: str, results: list[Listing],
                 variant: str | None = None, category: tuple[str, ...] = (),
                 identity: list[str] | None = None) -> list[Listing]:
    """Listings of the same product that sell SEVERAL sizes (or don't say which). Search shows them
    at the price of their cheapest size, so we must open them to see the price of ours."""
    size = our_size(title, variant)
    if not size:
        return []
    words = match_words(title)
    own_item = own_id.split("-")[0]
    picks = []
    for r in results:
        found = sizes_in(r.title)
        if r.external_id.split("-")[0] == own_item or found == {size} or r.size_checked:
            continue
        if found and size not in found:
            continue  # names only other sizes
        if r.price > price * PRICE_BAND[1]:
            continue  # even its cheapest size costs far more
        if similarity(words, r.title) < MIN_MATCH or not same_model(title, words, r.title):
            continue
        if not same_kind(title, r.title) or pack_size(title) != pack_size(r.title):
            continue
        if not same_identity(identity_words(title, results) if identity is None else identity, r.title):
            continue
        if not same_category(category, r.categories, strong_match=similarity(words, r.title) >= 1.0):
            continue
        picks.append(r)
    # Titles that mention our size first, then the closest matches.
    picks.sort(key=lambda r: (size not in sizes_in(r.title), -similarity(words, r.title)))
    return picks[:MAX_SIZE_LOOKUPS]


def wants_size(title: str, variant: str | None = None):
    """For an option name ("30 ML Spary"), True if it is our size."""
    size = our_size(title, variant)
    return lambda option: bool(size) and size in sizes_in(option)


def comparable(title: str, price: float, r: Listing, variant: str | None = None,
               category: tuple[str, ...] = (), identity: list[str] | None = None) -> bool:
    """Is listing `r` the same product, of the same kind, in the same category, size and pack size,
    at a believable price?"""
    size = our_size(title, variant)
    words = match_words(title)
    if not same_kind(title, r.title) or pack_size(title) != pack_size(r.title):
        return False
    if not same_identity(identity or [], r.title):
        return False
    if not same_category(category, r.categories, strong_match=similarity(words, r.title) >= 1.0):
        return False
    lo, hi = price * PRICE_BAND[0], price * PRICE_BAND[1]
    if r.size_checked:
        # Already narrowed to our size by opening the listing. A regular (not sale) price can
        # sit above the usual band, so only a far-off price is dropped.
        if not lo <= r.price <= hi * 1.5:
            return False
    elif not lo <= r.price <= hi:
        return False
    if similarity(words, r.title) < MIN_MATCH or not same_model(title, words, r.title):
        return False
    if size and not r.size_checked and sizes_in(r.title) != {size}:
        return False  # a different size, several sizes, or no size given: its price isn't comparable
    return True


def category_path(own_id: str, results: list[Listing], category: str | None = None) -> tuple[str, ...]:
    """Our category path, from our own listing in the search results, or from any result filed
    under our category id (read from our product page)."""
    own_item = own_id.split("-")[0]
    for r in results:
        if r.external_id.split("-")[0] == own_item and r.categories:
            return r.categories
    if category:
        for r in results:
            if r.categories and r.categories[-1] == category:
                return r.categories
        return (category,)
    return ()


def compare(title: str, price: float, own_id: str, results: list[Listing],
            variant: str | None = None, own_original: float | None = None,
            own_delivery: float | None = None, category: str | None = None,
            identity: list[str] | None = None) -> Market:
    """Other sellers of the same product AND the same size. A listing that offers several sizes
    shows the price of its cheapest one, so it only counts if it clearly sells just our size."""
    query = build_query(title)
    own_item = own_id.split("-")[0]  # "i123-s456" -> "i123"

    path = category_path(own_id, results, category)
    identity = identity_words(title, results) if identity is None else identity
    matches, own = [], None
    for r in results:
        if r.external_id.split("-")[0] == own_item:
            own = own or r  # kept for the "where to buy" ranking, not for the price comparison
            continue
        if comparable(title, price, r, variant, path, identity):
            matches.append(r)

    matches.sort(key=lambda r: (r.price_unconfirmed, r.price))
    # Only prices we're sure of count toward "what most sellers charge".
    prices = sorted(r.price for r in matches if not r.price_unconfirmed)
    enough = len(prices) >= MIN_SELLERS
    kept = [_listing_dict(r) for r in matches[:MAX_LISTINGS]]
    if own is not None:
        mine = _listing_dict(own, is_this=True)
        # Search shows our listing's cheapest option; show the price of the option we're checking.
        mine["price"], mine["original_price"] = price, own_original
        if own_delivery is not None:
            mine["delivery"] = own_delivery
        kept.append(mine)
    return Market(
        query=query,
        count=len(prices),
        median=round(median(prices), 2) if enough else None,
        low=prices[0] if enough else None,
        high=prices[-1] if enough else None,
        listings=kept,
    )


MAX_LISTINGS = 15
# Bump when matching changes, so saved seller lists made with older rules get rebuilt.
MATCH_VERSION = 11


def _listing_dict(r: Listing, is_this: bool = False) -> dict:
    return {
        "id": r.external_id, "price_unconfirmed": r.price_unconfirmed, "confirmed_at": r.confirmed_at,
        "title": r.title, "price": r.price, "original_price": r.original_price, "seller": r.seller, "url": r.url,
        "rating": r.rating, "reviews": r.reviews, "sold": r.sold, "mall": r.mall,
        "overseas": r.overseas, "free_shipping": r.free_shipping, "is_this": is_this, "image": r.image,
        # Only the fee shown on the product page counts. Search's "free shipping" badge often means
        # free only with a voucher or a minimum spend (e.g. Daraz shows ৳90 on the page).
        "delivery": r.delivery,
        "match_version": MATCH_VERSION,
    }


# ---- "Where to buy": rank sellers by price AND how much buyers trust them -------------

PRIOR_RATING = 3.5    # what we assume about a listing before anyone has rated it
PRIOR_WEIGHT = 8      # how many reviews it takes before a listing's own rating dominates
MIN_REVIEWS = 5       # fewer than this -> "not enough reviews yet"
MIN_RATING = 3.8      # below this (with enough reviews) -> poorly rated
PRICE_WEIGHT = 0.5    # score = 0.5 × price + 0.5 × trust (+ small extras)
PRICE_SENSITIVITY = 3 # each 1% above the cheapest trusted seller costs 3% of the price score
# "Much cheaper than other sellers" only with enough same-size prices to know what's normal.
SUSPICIOUS_MIN_SELLERS = 3
SUSPICIOUS_SHARE = 0.55   # under 55% of the usual price for this size
SUSPICIOUS_REVIEWS = 20   # ...and fewer reviews than this (or rated under 4★)


def trusted_rating(rating: float | None, reviews: int) -> float:
    """Average rating pulled toward 3.5★ when there are few reviews (a Bayesian average).
    One 5★ review -> about 3.7★. Two hundred 4.6★ reviews -> about 4.6★."""
    n = reviews if rating else 0
    return (PRIOR_WEIGHT * PRIOR_RATING + n * (rating or 0)) / (PRIOR_WEIGHT + n)


def _when(iso: str) -> str:
    from datetime import date

    try:
        day = date.fromisoformat(iso[:10])
    except ValueError:
        return "recently"
    days = (date.today() - day).days
    return "today" if days <= 0 else "yesterday" if days == 1 else f"{days} days ago"


def rank(listings: list[dict]) -> dict:
    """Split listings into a ranked "where to buy" list and an "unproven" list.

    Ranked:   enough reviews with a good rating, or an official Daraz Mall store.
              Sorted by a score that balances price (cheaper = better) and trust.
    Unproven: no/too few reviews, or poorly rated. Sorted by price, each with a reason.
    """
    if not listings:
        return {"ranked": [], "unproven": []}

    def is_proven(item: dict) -> bool:
        reviews, rating = int(item.get("reviews") or 0), item.get("rating")
        poorly = rating is not None and reviews >= MIN_REVIEWS and rating < MIN_RATING
        return not poorly and (reviews >= MIN_REVIEWS or bool(item.get("mall")))

    # What you actually pay: price + delivery. When a listing's fee is unknown, assume the
    # typical fee of the others (or nothing, if no fee is known at all).
    fees = [float(item["delivery"]) for item in listings if item.get("delivery") is not None]
    typical_fee = median(fees) if fees else 0.0

    def total(item: dict) -> float:
        fee = item.get("delivery")
        return float(item["price"]) + (float(fee) if fee is not None else typical_fee)

    # Price is judged against the cheapest seller people can actually trust.
    trusted_totals = [total(item) for item in listings if is_proven(item) and not item.get("price_unconfirmed")]
    cheapest = min(trusted_totals or [total(item) for item in listings])

    # Same size, far cheaper than everyone else, and few/weak reviews: worth a careful look.
    sure = [float(item["price"]) for item in listings if not item.get("price_unconfirmed")]
    usual = median(sure) if len(sure) >= SUSPICIOUS_MIN_SELLERS else None

    ranked, unproven = [], []
    for item in listings:
        reviews = int(item.get("reviews") or 0)
        rating = item.get("rating")
        trust = (trusted_rating(rating, reviews) - 1) / 4  # 0..1
        price_score = max(0.0, 1 - PRICE_SENSITIVITY * (total(item) - cheapest) / cheapest)
        sold = int(item.get("sold") or 0)
        bonus = 0.04 * bool(item.get("mall")) + min(0.04, 0.01 * math.log10(sold + 1))
        penalty = 0.05 * bool(item.get("overseas"))
        score = PRICE_WEIGHT * price_score + (1 - PRICE_WEIGHT) * trust + bonus - penalty

        entry = dict(item, score=round(score, 3), trusted_rating=round(trusted_rating(rating, reviews), 2),
                     total=round(total(item), 2))
        extras = []
        if (usual and not item.get("price_unconfirmed") and item["price"] < usual * SUSPICIOUS_SHARE
                and (reviews < SUSPICIOUS_REVIEWS or (rating or 0) < 4.0)):
            extras.append("Much cheaper than other sellers of this size. Read the reviews before buying")
        if item.get("price_unconfirmed"):
            extras.append("Regular price for this size. It may be on sale for less")
        elif item.get("confirmed_at"):
            extras.append(f"Price checked on this site {_when(item['confirmed_at'])}")
        if item.get("mall"):
            extras.append("Official Daraz Mall store")
        if sold:
            extras.append(f"{sold:,} sold")
        if item.get("delivery") == 0:
            extras.append("Free delivery")
        if item.get("overseas"):
            extras.append("Ships from overseas, so delivery is slow")

        poorly_rated = rating is not None and reviews >= MIN_REVIEWS and rating < MIN_RATING
        proven = is_proven(item)
        if proven:
            rating_note = [f"{rating:.1f}★ from {reviews:,} review{'s' if reviews != 1 else ''}"] if rating and reviews else []
            entry["notes"] = rating_note + extras
            ranked.append(entry)
        else:
            if poorly_rated:
                why = f"Poorly rated: {rating:.1f}★ from {reviews:,} reviews"
            elif reviews == 0 or not rating:
                why = "No reviews yet"
            else:
                why = f"Only {reviews} review{'s' if reviews != 1 else ''} so far ({rating:.1f}★)"
            entry["notes"] = [why] + extras
            entry["poorly_rated"] = poorly_rated
            unproven.append(entry)

    ranked.sort(key=lambda e: (-e["score"], e["total"]))
    unproven.sort(key=lambda e: (e.get("poorly_rated", False), e["total"]))
    return {"ranked": ranked, "unproven": unproven}
