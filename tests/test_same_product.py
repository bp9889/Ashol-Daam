"""Only the SAME product counts as another seller. Built from Daraz search results seen on 1 Nov 2026:
searching for a CMF Phone 2 Pro back cover also returns camera-lens protectors for that phone, which
share almost every word of the title but are a different product (and cost less)."""

from app.adapters import Listing
from app.market import build_query, compare, pack_size, same_kind

OURS = "For Nothing CMF Phone 2 Pro soft high hardness technology Eouro Silicone back cover"
OWN_ID = "i543993100-s2567123120"
CASES = ("2", "9536", "9543")


def item(i, title, price, cats, reviews=20, rating=4.6):
    return Listing(f"i{i}-s{i}", title, price, seller=f"Seller {i}", url=f"https://www.daraz.com.bd/products/x-i{i}.html",
                   rating=rating, reviews=reviews, categories=cats)


# Real listings from Daraz search on 1 Nov 2026 (titles, prices, categories as shown there).
RESULTS = [
    item(543993100, OURS, 299, CASES),
    # The same Eouro cover from another seller.
    item(1600029726, "For Nothing CMF Phone 2 Pro soft high hardness technology Eouro Silicone back cover", 263, CASES),
    # Other covers for the same phone: different products.
    item(533369241, "Nothing CMF Phone 2 Pro / CMF Phone 2 Premium Silicone Case Crystal Clear Soft TPU Ultra-Thin "
                    "Transparent Flexible Protective Mobile Phone Back Cover", 119, CASES),
    item(571362637, "Nothing CMF Phone 2 Pro Premium Case Soft Sandstone Slim Matte Cover Eouro Brand", 274, CASES),
    item(534436931, "Nothing Phone CMF 2 Pro Back Cover Soft Tranparent Premium SIlicone Soft Case Tpu Transparent "
                    "CMF2 Pro Phone Case", 105, CASES),
    item(546600438, "Nothing CMF Phone 2 Pro Anti Yellow Hard MagSafe Compatible Shockproof Transparent Slim Fit "
                    "Wireless Charging supported Phone Back Case Mobile Cover", 264, CASES),
    item(533259974, "For Nothing CMF Phone 2 Pro Phone Case Soft Slim Micro Matte Flexible Silicone Protective with "
                    "Anti-fingerprint Skin-like for Nothing CMF Phone 2Pro Cover", 220, CASES),
    item(1572557856, "For Nothing CMF Phone 2 Pro PULOKA protective soft back cover With leather texture Back Cover", 280, CASES),
    # Camera-lens protectors for the same phone.
    item(4, "For Nothing CMF Phone 2 Pro Camera Lens Protector Tempered Glass", 150, ("2", "9536", "9544")),
    item(5, "Nothing CMF Phone 2 Pro Lens Protectors Metal Ring", 200, ("240", "8217", "8220", "9601")),
    item(6, "Premium Camera Lens Protector Film For Nothing CMF Phone 2 Pro soft high hardness", 140, ("2", "9536", "9544")),
    # A 2-pack of the same cover isn't one cover.
    item(8, "For Nothing CMF Phone 2 Pro soft high hardness technology Eouro Silicone back cover 2 pcs", 480, CASES),
]


def test_only_the_same_cover_counts_not_other_covers_or_lens_protectors():
    market = compare(OURS, 299, OWN_ID, RESULTS, category="9543")
    sellers = [l["title"] for l in market.listings if not l["is_this"]]
    assert sellers == [RESULTS[1].title]


def test_category_from_our_own_page_when_we_are_not_in_the_search():
    market = compare(OURS, 299, OWN_ID, RESULTS[1:], category="9543")
    assert [l["title"] for l in market.listings] == [RESULTS[1].title]


def test_search_asks_for_the_kind_of_item():
    assert build_query(OURS).endswith(" cover")
    assert "cover" not in build_query("Xiaomi Redmi Buds 6 Active TWS Earbuds")


def test_a_phone_is_never_compared_with_its_cases():
    phone = "Xiaomi Redmi Note 13 8GB 256GB Smartphone"
    assert not same_kind(phone, "Xiaomi Redmi Note 13 Back Cover Silicone Case")
    assert same_kind(phone, "Redmi Note 13 8GB 256GB Official")
    assert same_kind("Galaxy A15 Back Case", "Galaxy A15 Silicone Cover")


def test_earbuds_filed_one_level_off_still_count_when_the_title_matches():
    ours = "Redmi Buds 6 Active TWS Bluetooth Earphone"
    results = [item(10, "Redmi Buds 6 Active TWS Bluetooth Earphone Black", 3193, ("147", "148", "154", "155")),
               item(11, "Redmi Buds 6 Active Case Cover Silicone", 250, ("147", "148", "154", "155"))]
    market = compare(ours, 3299, "i99-s99", results, category="9708")
    assert [l["title"] for l in market.listings] == [results[0].title]


def test_pack_sizes():
    assert pack_size("Nivea Roll On 50ml 2 pcs") == 2
    assert pack_size("Pack of 3 Face Masks") == 3
    assert pack_size("Nivea Men Roll On 50ml") == 1
    assert pack_size("Dettol Soap 3 Pack") == 3


def test_perfumes_still_match_on_the_shared_words():
    """No accessory word, so no 'rare words' check: every seller's Vampire Blood counts."""
    from app.market import identity_words
    perfumes = [item(i, f"Vampire Blood Euro Valley Perfume Oil 30ml by Seller{i}", 650 + i, ("1438", "1580", "10002065"))
                for i in range(6)]
    assert identity_words("Vampire Blood Euro Valley Premium Perfume Oil 30ml", perfumes) == []


def test_the_longer_search_finds_the_exact_copy(monkeypatch):
    """The short search ("… cover") returns other covers; the longer one finds the ৳263 copy."""
    from app.adapters import ProductData
    from app.adapters.daraz import DarazAdapter
    from app.db import SessionLocal
    from app.models import Product
    from app.services import save_snapshot

    short = [r for r in RESULTS if r.external_id != "i1600029726-s1600029726"]
    exact = [RESULTS[0], RESULTS[1]]
    queries = []

    def search(self, q, host_url=None):
        queries.append(q)
        return list(exact if "eouro" in q else short)

    monkeypatch.setattr(DarazAdapter, "search", search)
    with SessionLocal() as session:
        for old in session.query(Product).filter(Product.external_id == OWN_ID):
            session.delete(old)
        session.commit()
        product = save_snapshot(session, ProductData(
            source="daraz", external_id=OWN_ID, url=f"https://www.daraz.com.bd/products/x-{OWN_ID}.html",
            title=OURS, price=299, original_price=650, category="9543"), DarazAdapter(), detailed=False)
        listings = product.market_checks[-1].listings
    assert sorted(queries) == ["nothing cmf phone 2 pro cover", "nothing cmf phone 2 pro soft hardness technology eouro silicone"]
    assert [(l["seller"], l["price"]) for l in listings if not l["is_this"]] == [("Seller 1600029726", 263)]
