"""Same product under a vague name, found by its photo."""

import io

import httpx
from PIL import Image, ImageDraw

from app.adapters import Listing
from app.images import photo_key, same_photo, thumbnail
from app.market import compare

CASES = ("2", "9536", "9543")


def picture(kind: str, size: int = 800, quality: int = 80) -> bytes:
    im = Image.new("RGB", (800, 800), "white")
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([250, 120, 550, 700], 50, outline=(40, 40, 40), width=18, fill=(225, 225, 230))
    if kind == "ours":
        d.rounded_rectangle([280, 150, 400, 300], 30, fill=(60, 60, 60))   # camera bump top-left
    else:
        d.rounded_rectangle([400, 150, 520, 260], 30, fill=(30, 30, 30))   # another case
    out = io.BytesIO()
    im.resize((size, size)).save(out, "JPEG", quality=quality)
    return out.getvalue()


PHOTOS = {
    "/p/ours.jpg_120x120q80.jpg": picture("ours", 120),
    "/p/reupload.jpg_120x120q80.jpg": picture("ours", 120, quality=55),  # same photo, re-saved by another seller
    "/p/other.jpg_120x120q80.jpg": picture("other", 120),
}
CLIENT = httpx.Client(transport=httpx.MockTransport(
    lambda req: httpx.Response(200, content=PHOTOS[req.url.path]) if req.url.path in PHOTOS else httpx.Response(404)))
IMG = "https://static-01.daraz.com.bd/p/{}.jpg"
OURS = "For Nothing CMF Phone 2 Pro soft high hardness technology Eouro Silicone back cover"


def listing(i, title, price, image, cats=CASES):
    return Listing(f"i{i}-s{i}", title, price, seller=f"Seller {i}", rating=4.6, reviews=20,
                   image=IMG.format(image), categories=cats)


def test_thumbnails_and_photo_keys():
    assert thumbnail(IMG.format("ours")) == "https://static-01.daraz.com.bd/p/ours.jpg_120x120q80.jpg"
    assert photo_key(IMG.format("ours") + "_200x200q80.jpg") == photo_key(IMG.format("ours"))


def test_same_file_or_same_fingerprint_counts_a_different_photo_does_not():
    candidates = [
        listing(1, "Premium cover", 280, "ours"),       # same photo file, vague name
        listing(2, "Best quality cover", 270, "reupload"),  # same photo, uploaded again
        listing(3, "Premium cover", 260, "other"),      # a different case
    ]
    assert same_photo([IMG.format("ours")], candidates, client=CLIENT) == {"i1-s1", "i2-s2"}


def test_photo_matches_join_the_sellers_but_only_in_our_category_and_kind():
    from dataclasses import replace

    results = [
        replace(listing(1, "Premium soft cover for phone", 280, "ours"), photo_match=True),
        replace(listing(2, "Phone lens protector", 150, "ours", cats=("2", "9536", "9544")), photo_match=True),
        replace(listing(3, "Premium tempered protector", 260, "ours"), photo_match=True),  # different kind
        listing(4, "Premium soft cover for phone", 270, "other"),                          # no photo match
    ]
    market = compare(OURS, 299, "i543993100-s1", results, category="9543")
    assert [l["seller"] for l in market.listings if not l.get("alternative")] == ["Seller 1"]
    assert market.listings[0]["photo_match"] is True


def test_where_to_buy_says_why():
    from app.market import rank
    out = rank([{"seller": "A", "price": 280, "reviews": 20, "rating": 4.6, "photo_match": True}])
    assert "Same photo as yours" in out["ranked"][0]["notes"]


# ---- Generic titles (seen on Daraz, 2 Nov 2026): only the photo can tell which shoe it is ----------

SNEAKER = ("Sneakers Shoes For Men Summer Casual Lace Up Classic Fashion Sneakers Lightweight Comfort "
           "Shoes Soft Rubber Sole Plain Design White")
SHOES = ("1819", "1854", "1807", "1811")


def shoe(i, title, price, photo):
    return Listing(f"i{i}-s{i}", title, price, seller=f"Shop {i}", rating=4.4, reviews=200,
                   image=f"https://static-01.daraz.com.bd/p/{photo}.jpg", categories=SHOES)


SHOE_RESULTS = [
    shoe(1, SNEAKER, 480, "2174ffb1155d23667b74b6ce4ad3a1ff"),  # ours
    shoe(2, "Stlysh Running Sports Sneakers Casual Lace-Up Shoes Winter And Summer Men'S Shoes", 450, "176c9407"),
    shoe(3, "Sneakers For Men All Season PU Leather Casual Sports Style Lace-Up Comfortable Stylish Shoes", 530, "d4a58b0a"),
    shoe(4, "Canvas Sneakers Shoes For Men Summer Korean Style Slip On Casual Shoes Lightweight", 465, "c8e85b16"),
    shoe(5, SNEAKER, 399, "29ee48a3"),                          # same title, different photo file
    shoe(6, "Men casual shoes white", 420, "2174ffb1155d23667b74b6ce4ad3a1ff"),  # vague name, OUR photo file
]


def test_generic_titles_are_spotted():
    from app.market import is_bland
    assert is_bland(SNEAKER)
    assert not is_bland("YRZL Men Sports Running Black Jogging Shoes Casual Sneakers")
    assert not is_bland("Vampire Blood Euro Valley Super Premium 30 ML Perfume Oil")


def test_generic_title_matches_by_photo_only(monkeypatch):
    """Different sneakers with similar words are left out; only listings with our photo count."""
    from app.adapters import ProductData
    from app.adapters.daraz import DarazAdapter
    from app.db import SessionLocal
    from app.models import Product
    from app.services import save_snapshot

    monkeypatch.setattr(DarazAdapter, "search", lambda self, q, host_url=None: list(SHOE_RESULTS))
    with SessionLocal() as session:
        for old in session.query(Product).filter(Product.external_id == "i1-s1"):
            session.delete(old)
        session.commit()
        product = save_snapshot(session, ProductData(
            source="daraz", external_id="i1-s1", url="https://www.daraz.com.bd/products/x-i1-s1.html",
            title=SNEAKER, price=480, original_price=799, category="1811",
            image_url="https://static-01.daraz.com.bd/p/2174ffb1155d23667b74b6ce4ad3a1ff.jpg"),
            DarazAdapter(), detailed=False)  # quick step: same photo FILE only, nothing downloaded
        others = [l for l in product.market_checks[-1].listings if not l["is_this"] and not l.get("alternative")]
    assert [(l["seller"], l["photo_match"]) for l in others] == [("Shop 6", True)]


# ---- When nothing is the same product: look-alikes, clearly apart -----------------------------

RIDER = ("Running Sneakers Shoes For Men Casual Shoes Comfortable Sports Running And Motorbike Driving "
         "Safety Shoes - White Shoes")


def test_no_exact_match_gives_alternatives_closest_photo_first():
    from dataclasses import replace
    from app.market import rank

    results = [
        replace(shoe(11, "Stlysh Running Sports Sneakers Casual Lace-Up Shoes Winter And Summer Men'S Shoes", 450, "a"),
                photo_distance=90),
        replace(shoe(12, "Sneakers For Men All Season PU Leather Casual Sports Style Lace-Up Shoes", 599, "b"),
                photo_distance=31),  # looks a lot like ours
        shoe(13, "Running Sneakers Casual Lace-Up Shoes Summer Men's Shoes", 599, "c"),  # photo not compared
        shoe(14, "Kids school bag", 650, "d"),  # not similar at all
    ]
    market = compare(RIDER, 749, "i99-s99", results, category="1811")
    assert market.count == 0 and market.median is None  # nothing counts toward the verdict
    where = rank(market.listings)
    assert where["ranked"] == [] and where["unproven"] == []
    assert [a["seller"] for a in where["alternatives"]] == ["Shop 12", "Shop 11", "Shop 13"]
    assert where["alternatives"][0]["notes"][0] == "Looks similar"
