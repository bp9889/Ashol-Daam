"""Daraz during a sale: the product page carries no price on its variants, only a tracking
price (pdt_price) that is the REGULAR price, with an empty discount label. The real sale price
is filled in later by scripts. Search results do carry it, so we confirm the price there.
The fixtures copy the structure of a real page checked on 1 Nov 2026 (৳2,999, was ৳4,500)."""

import json
from pathlib import Path

import httpx
import pytest

from app.adapters import AdapterError, Listing
from app.adapters.daraz import DarazAdapter

PAGE = (Path(__file__).parent / "fixtures" / "daraz_sale_page.html").read_text(encoding="utf-8")
URL = "https://www.daraz.com.bd/products/furniture-plus-smart-executive-office-chair-china-mesh-fp-m-20-i294279595-s1889585817.html"
SEARCH = {"mods": {"listItems": [{
    "itemId": "294279595", "skuId": "1889585817", "name": "Furniture Plus Smart Executive  office chair China mesh  FP-M-20",
    "price": "2999", "originalPrice": "4500", "priceShow": "৳ 2,999", "discount": "33% Off", "sellerName": "Furniture Plus ",
    "itemUrl": "//www.daraz.com.bd/products/furniture-plus-smart-executive-office-chair-china-mesh-fp-m-20-i294279595-s1889585817.html",
}]}}


def test_page_alone_is_marked_unconfirmed():
    data = DarazAdapter().parse(PAGE, URL)
    assert data.price == 4500             # all the page says...
    assert data.price_unconfirmed is True  # ...so it must be checked another way


def test_discount_label_when_present_gives_an_estimate():
    page = PAGE.replace('\\"pdt_discount\\":\\"\\"', '\\"pdt_discount\\":\\"-33%\\"')
    assert "-33%" in page
    data = DarazAdapter().parse(page, URL)
    assert (data.price, data.original_price, data.price_unconfirmed) == (3015, 4500, True)


def test_search_result_gives_the_exact_sale_price():
    data = DarazAdapter().parse(PAGE, URL)
    found = DarazAdapter.apply_search_price(data, [
        Listing("i111", "Some other chair", 2500),
        Listing("i294279595-s1889585817", "Furniture Plus chair", 2999, 4500),
    ])
    assert found
    assert (data.price, data.original_price, data.price_unconfirmed) == (2999, 4500, False)


def test_fetch_confirms_the_price_through_search():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if "/catalog/" in request.url.path:
            return httpx.Response(200, json=SEARCH)
        return httpx.Response(200, text=PAGE)

    adapter = DarazAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    data = adapter.fetch(URL)
    assert (data.price, data.original_price) == (2999, 4500)
    assert len(requests) == 2 and "catalog" in requests[1]


def test_fetch_refuses_to_guess_if_search_misses():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/catalog/" in request.url.path:
            return httpx.Response(200, json={"mods": {"listItems": []}})
        return httpx.Response(200, text=PAGE)

    adapter = DarazAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(AdapterError, match="sale price is running"):
        adapter.fetch(URL)


def test_price_on_the_variant_needs_no_search():
    page = PAGE.replace('"skuId":"1889585817","quantity":{}}}',
                        '"skuId":"1889585817","quantity":{},"price":{"salePrice":{"value":2999},"originalPrice":{"value":4500}}}}')
    data = DarazAdapter().parse(page, URL)
    assert (data.price, data.original_price, data.price_unconfirmed) == (2999, 4500, False)
