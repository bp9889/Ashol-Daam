"""Daraz adapter.

Daraz product links look like:
    https://www.daraz.com.bd/products/some-name-i123456789-s987654321.html?spm=...

A product page carries its data in several places. We try them from most to least
detailed, so a small change on Daraz's side doesn't break everything at once:

    1. `__moduleData__`  - a big JSON blob with every variant (SKU) and its prices
    2. `pdpTrackingData` - a smaller JSON string with name and price
    3. JSON-LD           - the standard schema.org Product block search engines read
    4. Open Graph tags   - title and image only

Be polite: this module fetches one page per call. The collector spaces calls out and
only checks products that users asked to track.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import replace
from typing import Any, Callable
from urllib.parse import quote_plus, urlparse

import httpx
from bs4 import BeautifulSoup

from .base import Adapter, AdapterError, BlockedError, Listing, PriceNeeded, ProductData, UnsupportedUrlError

CURRENCY_BY_HOST = {
    "daraz.com.bd": "BDT",
    "daraz.pk": "PKR",
    "daraz.lk": "LKR",
    "daraz.com.np": "NPR",
}

# "…-i123-s456.html", or with no name before the id: "/products/i123-s456.html"
ID_PATTERN = re.compile(r"(?<=[-/])i(\d+)(?:-s(\d+))?\.html", re.IGNORECASE)
NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,bn;q=0.8",
}

BLOCK_MARKERS = ("x5secdata", "punish", "_____tmd_____", "slide to verify", "nc_1_n1z")


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def to_number(value: Any) -> float | None:
    """Turn 1299, "1299", "৳ 1,299" or "Tk. 1,299.00" into 1299.0."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    match = NUMBER_PATTERN.search(str(value))
    if not match:
        return None
    number = float(match.group().replace(",", ""))
    return number if number > 0 else None


def parse_count(value: Any) -> int:
    """'136 sold' -> 136, '1.2K sold' -> 1200, '10K+ sold' -> 10000, '' -> 0."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*([kKmM]?)", str(value or "").replace(",", ""))
    if not match:
        return 0
    number = float(match.group(1))
    multiplier = {"k": 1_000, "m": 1_000_000}.get(match.group(2).lower(), 1)
    return int(number * multiplier)


def _find_key(data: Any, key: str) -> Any:
    """Depth-first search for the first value stored under `key` in nested JSON."""
    stack = [data]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if key in current:
                return current[key]
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    return None


def _json_after(html: str, marker: str) -> Any:
    """Decode the JSON object that starts right after `marker` (e.g. `__moduleData__ =`)."""
    index = html.find(marker)
    if index == -1:
        return None
    start = html.find("{", index)
    if start == -1:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(html, start)
        return value
    except json.JSONDecodeError:
        return None


def same_option(shown: str | None, expected: str | None) -> bool:
    """The option the page shows as chosen is the one we asked for ("30 ML Spary" == "30ml spary")."""
    if not shown or not expected:
        return True
    squash = lambda text: re.sub(r"[^a-z0-9]", "", text.lower())  # noqa: E731
    return squash(expected) in squash(shown)


def _absolute_image(src: str | None) -> str | None:
    if not src:
        return None
    return "https:" + src if src.startswith("//") else src


class DarazAdapter(Adapter):
    source = "daraz"

    def __init__(self, client: httpx.Client | None = None, timeout: float = 15.0):
        self._client = client
        self._timeout = timeout

    # ---- link handling -------------------------------------------------

    def matches(self, url: str) -> bool:
        host = _host(url)
        return any(host == h or host.endswith("." + h) for h in CURRENCY_BY_HOST)

    def ids_from_url(self, url: str) -> tuple[str, str | None]:
        match = ID_PATTERN.search(urlparse(url).path)
        if not match:
            raise UnsupportedUrlError(
                "That doesn't look like a Daraz product page. Open the product on Daraz and copy the link from there."
            )
        return match.group(1), match.group(2)

    def product_key(self, url: str) -> str:
        item_id, sku_id = self.ids_from_url(url)
        return f"i{item_id}-s{sku_id}" if sku_id else f"i{item_id}"

    @staticmethod
    def clean_url(url: str) -> str:
        """Drop tracking parameters (?spm=...) so the same product always has the same link."""
        parsed = urlparse(url)
        return f"https://{parsed.hostname}{parsed.path}"

    # ---- fetching -------------------------------------------------------

    def _get(self, url: str, headers: dict | None = None) -> httpx.Response:
        headers = {**HEADERS, **(headers or {})}
        try:
            if self._client is not None:
                response = self._client.get(url, headers=headers, follow_redirects=True)
            else:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.get(url, headers=headers, follow_redirects=True)
        except httpx.HTTPError as exc:
            raise AdapterError(f"Couldn't reach Daraz ({exc.__class__.__name__}). Try again in a minute.") from exc
        if response.status_code == 404:
            raise AdapterError("Daraz says this product doesn't exist any more.")
        if response.status_code >= 400:
            raise AdapterError(f"Daraz answered with an error ({response.status_code}). Try again later.")
        if "punish" in str(response.url).lower():
            raise BlockedError("Daraz showed a robot check instead of the page. Wait a while before checking again.")
        return response

    def fetch(self, url: str, manual_price: float | None = None) -> ProductData:
        if not self.matches(url):
            raise UnsupportedUrlError("Only Daraz product links are supported right now.")
        response = self._get(url)
        if not ID_PATTERN.search(urlparse(str(response.url)).path):
            # Share links from the Daraz app (s.daraz.com.bd/s.XXXX) land on a small "bridge" page
            # that sends the browser on with a script. The real product link is inside that page.
            target = self.product_link_in(response.text)
            if target is None:
                raise UnsupportedUrlError(
                    "Couldn't find the product behind that link. Open it in your browser and copy the "
                    "address from the address bar instead."
                )
            response = self._get(target)
        response, page_url = self._keep_size(url, response)
        data = self.parse(response.text, page_url)
        if data.price_unconfirmed and not manual_price:
            self.confirm_price(data)  # a search; skipped when we already know the price
        if data.price_unconfirmed and not manual_price:
            self.read_shown_price(data)
        if data.price_unconfirmed and manual_price:
            # The person typed the price they see on Daraz. The page still tells us the old price.
            old = data.original_price or data.price
            data.price = float(manual_price)
            data.original_price = old if old and old > data.price else None
            data.price_unconfirmed = False
        if data.price_unconfirmed:
            # Better to ask than to guess: a wrong price would also spoil the product's history.
            # The page's price is the regular price. It's what you pay when no sale is running, and
            # the crossed-out price when one is. The page looks the same either way, so we ask.
            listed = data.original_price or data.price or None
            what = f"“{data.variant}”" if data.variant and data.variant_count > 1 else "this product"
            if listed:
                message = (f"Daraz lists {what} at ৳{listed:,.0f}, but its page doesn't say whether a sale "
                           "price is running. Is that the price you see on Daraz?")
            else:
                message = f"Daraz's page doesn't show the price of {what}. Type the price you see on Daraz."
            raise PriceNeeded(message, variant=data.variant, old_price=listed)
        return data

    def _keep_size(self, asked_url: str, response: httpx.Response) -> tuple[httpx.Response, str]:
        """Daraz sometimes redirects a link for one size (…-i123-s456.html) to the product's main page
        (…-i123.html), dropping the size. Ask again with the size in the address; if Daraz drops it
        again, still read the page as the size that was asked for."""
        asked = ID_PATTERN.search(urlparse(asked_url).path)
        landed = str(response.url)
        got = ID_PATTERN.search(urlparse(landed).path)
        if not asked or not asked.group(2) or not got or got.group(1) != asked.group(1) or got.group(2) == asked.group(2):
            return response, landed
        parsed = urlparse(landed)
        with_size = f"https://{parsed.hostname}" + ID_PATTERN.sub(
            f"i{asked.group(1)}-s{asked.group(2)}.html", parsed.path)
        try:
            again = self._get(with_size)
            if ID_PATTERN.search(urlparse(str(again.url)).path).group(2) == asked.group(2):
                return again, str(again.url)
        except (AdapterError, AttributeError):
            pass
        return response, with_size

    def product_link_in(self, html: str) -> str | None:
        """Find the real product page link inside a share-link bridge page."""
        soup = BeautifulSoup(html, "html.parser")
        candidates = [tag.get("href") for tag in soup.find_all("link", rel="origin")]
        candidates += [tag.get("content") for tag in soup.find_all("meta", property="og:url")]
        # Fall back to any product link in the page (possibly inside a script, possibly escaped).
        text = html.replace("\\/", "/")
        candidates += re.findall(r"https?://(?:www\.)?daraz\.[a-z.]+/products/[^\"'\s<>\\]+", text)
        for link in candidates:
            if link and self.matches(link) and ID_PATTERN.search(urlparse(link).path):
                return link
        return None

    def see_prices(self, urls: list[str]) -> dict:
        from .. import browser

        return browser.read_prices(urls)

    def read_shown_price(self, data: ProductData) -> bool:
        """Open the page in a hidden browser and read the price shown for this size/option."""
        seen = self.see_prices([data.url]).get(data.url)
        if seen is None or not same_option(seen.option, data.variant):
            return False
        data.price = seen.price
        data.original_price = seen.original
        data.delivery = seen.delivery
        data.price_unconfirmed = False
        return True

    def confirm_price(self, data: ProductData) -> None:
        """During a sale the product page doesn't contain the exact sale price, but Daraz's
        search results do. Look the product up by its title and copy the real price over."""
        query = re.sub(r"\s+", " ", data.title).strip()[:120]
        try:
            results = self.search(query, data.url)
        except AdapterError:
            return  # keep the estimate
        self.apply_search_price(data, results)

    @staticmethod
    def apply_search_price(data: ProductData, results: list[Listing]) -> bool:
        own_item = data.external_id.split("-")[0]
        # Search shows one price per listing: the one for its cheapest size/option. So it only
        # tells us OUR price if it's for exactly our option, or the listing has just one option.
        exact = [r for r in results if r.external_id == data.external_id]
        same_item = [r for r in results if r.external_id.split("-")[0] == own_item] if data.variant_count <= 1 else []
        for listing in exact or same_item:
                data.price = listing.price
                if listing.original_price and listing.original_price > listing.price:
                    data.original_price = listing.original_price
                data.price_unconfirmed = False
                return True
        return False

    def size_option(self, listing: Listing, wanted: Callable[[str], bool]) -> Listing | None:
        """Search shows a multi-size listing at the price of its CHEAPEST size. Open the listing, find
        the option for our size, and read that option's price. If the page only has its regular price
        (Daraz adds sale prices with scripts), the listing is marked price_unconfirmed."""
        if not listing.url:
            return None
        html = self._get(listing.url).text
        module = _json_after(html, "__moduleData__")
        sku_base = _find_key(module, "skuBase") if module else None
        if not isinstance(sku_base, dict):
            return None
        names = {}
        for prop in sku_base.get("properties") or []:
            for value in prop.get("values") or []:
                names[f"{prop.get('pid')}:{value.get('vid')}"] = str(value.get("name", ""))
        sku_id = None
        for sku in sku_base.get("skus") or []:
            label = " ".join(names.get(pair, "") for pair in str(sku.get("propPath") or "").split(";"))
            if wanted(label):
                sku_id = str(sku.get("skuId"))
                break
        if sku_id is None:
            return None
        item_id = listing.external_id.split("-")[0].lstrip("i")
        external_id = f"i{item_id}-s{sku_id}"
        if external_id == listing.external_id:
            # Our size IS the cheapest one, so the search price is exactly right.
            return replace(listing, size_checked=True)
        path = urlparse(listing.url).path
        url = f"https://{urlparse(listing.url).hostname}" + re.sub(r"-i\d+(?:-s\d+)?\.html", f"-i{item_id}-s{sku_id}.html", path)
        data = self.parse(self._get(url).text, url)
        if not data.in_stock:
            return None
        return replace(listing, external_id=external_id, url=data.url, price=data.price,
                       original_price=data.original_price, size_checked=True,
                       price_unconfirmed=data.price_unconfirmed)

    # ---- search (to compare with other sellers) ----------------------------

    def search(self, query: str, host_url: str | None = None) -> list[Listing]:
        host = urlparse(host_url).hostname if host_url else "www.daraz.com.bd"
        url = f"https://{host}/catalog/?q={quote_plus(query)}&ajax=true"
        response = self._get(url, {"Accept": "application/json, text/plain, */*", "X-Requested-With": "XMLHttpRequest"})
        return self.parse_search(response.text, host)

    def parse_search(self, body: str, host: str = "www.daraz.com.bd") -> list[Listing]:
        """Search results come as JSON (ajax=true) or as a page with `window.pageData = {...}`."""
        data: Any = None
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            data = _json_after(body, "pageData")

        if isinstance(data, dict):
            ret = " ".join(map(str, data.get("ret") or []))
            if "FAIL_SYS_USER_VALIDATE" in ret or "RGV587" in ret.upper():
                raise BlockedError("Daraz showed a robot check on search. Comparing with other sellers is paused.")
        elif any(marker in body.lower() for marker in BLOCK_MARKERS):
            raise BlockedError("Daraz showed a robot check on search. Comparing with other sellers is paused.")

        items = _find_key(data, "listItems") if data is not None else None
        if not isinstance(items, list):
            return []

        listings = []
        for item in items:
            if not isinstance(item, dict):
                continue
            price = to_number(item.get("price")) or to_number(item.get("priceShow"))
            title = item.get("name") or item.get("title")
            item_id = item.get("itemId") or item.get("nid")
            if not price or not title or not item_id:
                continue
            link = item.get("itemUrl") or item.get("productUrl")
            if link and link.startswith("//"):
                link = "https:" + link
            elif link and link.startswith("/"):
                link = f"https://{host}{link}"
            if str(item.get("inStock", "true")).lower() == "false":
                continue
            badges = {str(icon.get("bizType", "")).lower() for icon in item.get("icons") or [] if isinstance(icon, dict)}
            rating = to_number(item.get("ratingScore"))
            listings.append(
                Listing(
                    external_id=f"i{item_id}-s{item['skuId']}" if item.get("skuId") else f"i{item_id}",
                    title=str(title),
                    price=price,
                    original_price=to_number(item.get("originalPrice")),
                    seller=(item.get("sellerName") or "").strip() or None,
                    url=link.split("?")[0] if link else None,
                    rating=rating if rating and rating <= 5 else None,
                    reviews=int(to_number(item.get("review")) or 0),
                    sold=parse_count(item.get("itemSoldCntShow")),
                    mall="lazmall" in badges or "darazmall" in badges,
                    overseas=str(item.get("location", "")).strip().lower() == "overseas",
                    free_shipping=any("freeshipping" in b for b in badges),
                    image=_absolute_image(item.get("image")),
                    categories=tuple(str(c) for c in item.get("categories") or [] if c is not None),
                )
            )
        return listings

    # ---- parsing (pure, unit-tested) -------------------------------------

    def parse(self, html: str, url: str) -> ProductData:
        lowered = html.lower()
        item_id, sku_id = self.ids_from_url(url)

        title: str | None = None
        image: str | None = None
        variant: str | None = None
        variant_count = 1
        category: str | None = None
        price: float | None = None
        original: float | None = None
        in_stock = True
        # Daraz's tracking data has "pdt_price" and "pdt_discount". When a discount is running,
        # pdt_price is the regular (crossed-out) price, NOT what you pay; the sale price is
        # filled in later by the page's scripts. We keep both so we never mistake one for the other.
        listed_price: float | None = None
        discount_pct: float | None = None

        def read_tracking(layer: Any) -> None:
            nonlocal listed_price, discount_pct, title
            if not isinstance(layer, dict):
                return
            title = title or layer.get("pdt_name")
            shown_sku = str(layer.get("pdt_simplesku") or "")
            if sku_id and shown_sku and shown_sku != str(sku_id):
                return  # the page is showing a different size; its price isn't ours
            listed_price = listed_price or to_number(layer.get("pdt_price"))
            discount_pct = discount_pct or to_number(layer.get("pdt_discount"))  # "-33%" -> 33
            title = title or layer.get("pdt_name")

        # 1. __moduleData__
        module = _json_after(html, "__moduleData__")
        if module:
            sku = self._pick_sku(_find_key(module, "skuInfos"), sku_id)
            if sku:
                read_tracking(sku.get("dataLayer"))
                price_info = sku.get("price") or {}
                price = to_number((price_info.get("salePrice") or {}).get("value")) or to_number(
                    (price_info.get("salePrice") or {}).get("text")
                )
                original = to_number((price_info.get("originalPrice") or {}).get("value")) or to_number(
                    (price_info.get("originalPrice") or {}).get("text")
                )
                stock = sku.get("stock")
                if isinstance(stock, (int, float)):
                    in_stock = stock > 0
                image = image or _absolute_image(sku.get("image"))
                category = str(sku.get("categoryId") or "") or None
            product = _find_key(module, "product")
            if isinstance(product, dict):
                title = product.get("title") or title
            variant, variant_count = self._variant(_find_key(module, "skuBase"), sku_id)
            galleries = _find_key(module, "skuGalleries")
            if not image and isinstance(galleries, dict):
                first = next(iter(galleries.values()), None)
                if isinstance(first, list) and first and isinstance(first[0], dict):
                    image = _absolute_image(first[0].get("src"))

        # 2. pdpTrackingData (a JSON object stored inside a JS string)
        if price is None or title is None:
            match = re.search(r"pdpTrackingData\s*=\s*(\"(?:[^\"\\]|\\.)*\")", html)
            if match:
                try:
                    read_tracking(json.loads(json.loads(match.group(1))))
                except (json.JSONDecodeError, TypeError, AttributeError):
                    pass

        # Only a price read from the variant itself is certain. Daraz often leaves it out of the
        # page (it's filled in later by scripts) and its tracking price can be the regular,
        # crossed-out price, even when pdt_discount is empty. fetch() confirms through search.
        price_unconfirmed = price is None
        if price is None and listed_price:
            if discount_pct and 0 < discount_pct < 100:
                # Discount label present: the listed price is the crossed-out one; estimate the sale price.
                original = listed_price
                price = round(listed_price * (1 - discount_pct / 100))
            else:
                price = listed_price

        soup = BeautifulSoup(html, "html.parser")

        # 3. JSON-LD
        if price is None or title is None or image is None:
            for script in soup.find_all("script", type="application/ld+json"):
                try:
                    data = json.loads(script.string or "")
                except json.JSONDecodeError:
                    continue
                for node in data if isinstance(data, list) else [data]:
                    if not isinstance(node, dict) or node.get("@type") != "Product":
                        continue
                    title = title or node.get("name")
                    img = node.get("image")
                    image = image or _absolute_image(img[0] if isinstance(img, list) and img else img)
                    offers = node.get("offers") or {}
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    if not (sku_id and variant_count > 1):  # for one size of many, it's not our price
                        price = price or to_number(offers.get("price")) or to_number(offers.get("lowPrice"))
                    availability = str(offers.get("availability", ""))
                    if "OutOfStock" in availability:
                        in_stock = False

        # 4. Open Graph tags
        if title is None:
            tag = soup.find("meta", property="og:title")
            title = tag.get("content") if tag else None
        if image is None:
            tag = soup.find("meta", property="og:image")
            image = _absolute_image(tag.get("content")) if tag else None

        if price is None and sku_id and variant_count > 1 and title and not (
                any(marker in lowered for marker in BLOCK_MARKERS) or "captcha" in lowered):
            price, price_unconfirmed = 0.0, True  # one size of many, price unknown: confirmed in fetch()
        if price is None:
            if any(marker in lowered for marker in BLOCK_MARKERS) or "captcha" in lowered:
                raise BlockedError(
                    "Daraz showed a robot check instead of the product. Wait a while before checking again."
                )
            raise AdapterError("Couldn't find a price on that page. Daraz may have changed its layout.")

        # A crossed-out price that isn't higher than the real price is meaningless.
        if original is not None and original <= price:
            original = None

        return ProductData(
            source=self.source,
            external_id=f"i{item_id}-s{sku_id}" if sku_id else f"i{item_id}",
            url=self.clean_url(url),
            title=(title or "Untitled product").strip(),
            price=price,
            original_price=original,
            image_url=image,
            currency=CURRENCY_BY_HOST.get(_host(url), "BDT"),
            in_stock=in_stock,
            price_unconfirmed=price_unconfirmed,
            variant=variant,
            variant_count=variant_count,
            category=category,
        )

    @staticmethod
    def _variant(sku_base: Any, sku_id: str | None) -> tuple[str | None, int]:
        """Name of the size/option in the link (e.g. "30 ML Spary") and how many options exist.
        skuBase = {"properties": [{"pid", "name", "values": [{"vid", "name"}]}],
                   "skus": [{"skuId", "propPath": "pid:vid;pid:vid"}]}"""
        if not isinstance(sku_base, dict):
            return None, 1
        skus = [s for s in sku_base.get("skus") or [] if isinstance(s, dict)]
        if len(skus) <= 1:
            return None, max(len(skus), 1)
        names = {}
        for prop in sku_base.get("properties") or []:
            for value in prop.get("values") or []:
                names[(str(prop.get("pid")), str(value.get("vid")))] = str(value.get("name", "")).strip()
        chosen = next((s for s in skus if str(s.get("skuId")) == str(sku_id)), None)
        if chosen is None:
            return None, len(skus)
        parts = []
        for pair in str(chosen.get("propPath") or "").split(";"):
            pid, _, vid = pair.partition(":")
            if names.get((pid, vid)):
                parts.append(names[(pid, vid)])
        return (" / ".join(parts) or None), len(skus)

    @staticmethod
    def _pick_sku(sku_infos: Any, sku_id: str | None) -> dict | None:
        """Pick the variant from the link, else the default one ("0"), else the first."""
        if not isinstance(sku_infos, dict) or not sku_infos:
            return None
        if sku_id and isinstance(sku_infos.get(sku_id), dict):
            return sku_infos[sku_id]
        for key, value in sku_infos.items():
            if isinstance(value, dict) and str(value.get("skuId")) == sku_id:
                return value
        if isinstance(sku_infos.get("0"), dict):
            return sku_infos["0"]
        first = next(iter(sku_infos.values()))
        return first if isinstance(first, dict) else None


# ---- debugging from the terminal ---------------------------------------------
#   python -m app.adapters.daraz product https://www.daraz.com.bd/products/...
#   python -m app.adapters.daraz search "redmi buds 6 active"

if __name__ == "__main__":
    adapter = DarazAdapter()
    if len(sys.argv) == 3 and sys.argv[1] == "product":
        print(adapter.fetch(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == "search":
        results = adapter.search(sys.argv[2])
        print(f"{len(results)} results")
        for listing in results[:15]:
            print(f"  {listing.price:>9,.0f}  {listing.seller or '?':<24.24}  {listing.title[:70]}")
    else:
        print('Usage: python -m app.adapters.daraz product <url>  |  search "words"')
