from pathlib import Path

import pytest

from app.adapters import BlockedError, UnsupportedUrlError, get_adapter
from app.adapters.daraz import DarazAdapter, to_number

FIXTURE = (Path(__file__).parent / "fixtures" / "daraz_product.html").read_text(encoding="utf-8")
URL = "https://www.daraz.com.bd/products/wireless-earbuds-pro-x-i123456789-s111.html?spm=a2a0e.searchlist"
adapter = DarazAdapter()


def test_matches_daraz_hosts_only():
    assert adapter.matches(URL)
    assert adapter.matches("https://daraz.pk/products/x-i1.html")
    assert not adapter.matches("https://www.amazon.com/dp/B000")
    assert not adapter.matches("https://notdaraz.com.bd.evil.com/products/x-i1.html")


def test_product_key_and_clean_url():
    assert adapter.product_key(URL) == "i123456789-s111"
    assert adapter.clean_url(URL) == "https://www.daraz.com.bd/products/wireless-earbuds-pro-x-i123456789-s111.html"


def test_rejects_non_product_links():
    with pytest.raises(UnsupportedUrlError):
        adapter.product_key("https://www.daraz.com.bd/catalog/?q=earbuds")
    with pytest.raises(UnsupportedUrlError):
        get_adapter("https://www.example.com/item")


def test_parses_default_sku_from_module_data():
    data = adapter.parse(FIXTURE, URL)
    assert data.title == "Wireless Earbuds Pro X"
    assert data.price == 2499
    assert data.original_price == 4999
    assert data.in_stock is True
    assert data.image_url == "https://img.example/gallery.jpg"
    assert data.currency == "BDT"


def test_parses_the_variant_in_the_link():
    data = adapter.parse(FIXTURE, URL.replace("-s111", "-s222"))
    assert data.price == 2899
    assert data.original_price == 5499
    assert data.in_stock is False
    assert data.image_url == "https://img.example/blue.jpg"


def test_falls_back_to_json_ld():
    html = FIXTURE.replace("__moduleData__", "__somethingElse__")
    data = adapter.parse(html, URL)
    assert data.title == "JSON-LD Earbuds"
    assert data.price == 2399
    assert data.original_price is None
    assert data.image_url == "https://img.example/ld.jpg"


def test_falls_back_to_tracking_data():
    html = (
        '<html><script>var pdpTrackingData = "{\\"pdt_name\\":\\"Rice Cooker\\",\\"pdt_price\\":\\"৳ 3,190\\"}";</script></html>'
    )
    data = adapter.parse(html, "https://www.daraz.com.bd/products/rice-cooker-i42.html")
    assert data.title == "Rice Cooker"
    assert data.price == 3190
    assert data.external_id == "i42"


def test_detects_robot_check():
    html = "<html><body>Please slide to verify. x5secdata=abc</body></html>"
    with pytest.raises(BlockedError):
        adapter.parse(html, URL)


@pytest.mark.parametrize(
    "raw, expected",
    [(1299, 1299.0), ("1299", 1299.0), ("৳ 1,299", 1299.0), ("Tk. 1,299.50", 1299.5), ("", None), (0, None), (None, None)],
)
def test_to_number(raw, expected):
    assert to_number(raw) == expected
