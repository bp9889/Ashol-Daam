"""Share links from the Daraz app (s.daraz.com.bd/s.XXXX) open a "bridge" page that moves on
with a script, not a normal redirect. The real product link sits in <link rel="origin">.
The fixture copies the structure of a real bridge page checked on 1 Nov 2026."""

import httpx
import pytest

from app.adapters import UnsupportedUrlError
from app.adapters.daraz import DarazAdapter

SHORT = "https://s.daraz.com.bd/s.YVQ56"
TARGET = (
    "https://www.daraz.com.bd/products/wishcare-underarm-roll-on-serum-50ml-i327665585-s1598953003.html"
    "?dsource=share&amp;laz_share_info=4675325094_0_100&amp;sub_aff_id=social_share"
)
BRIDGE = f"""<html lang="en"><head>
<title>WishCare Underarm Roll On Serum</title>
<meta name="spm-id" content="a2a0e.share_bridge_page">
<meta property="al:android:url" content="{SHORT}">
<meta property="og:title" content="WishCare Underarm Roll On Serum">
<link rel="origin" href="{TARGET}">
</head><body><script>/* redirects with JavaScript */</script></body></html>"""

PRODUCT = """<html><script>var __moduleData__ = {"data":{"root":{"fields":{
  "product":{"title":"WishCare Underarm Roll On Serum 50ml"},
  "skuInfos":{"1598953003":{"skuId":"1598953003","price":{"salePrice":{"value":649},"originalPrice":{"value":899}}}}
}}}};</script></html>"""


def test_finds_the_product_link_in_the_bridge_page():
    link = DarazAdapter().product_link_in(BRIDGE)
    assert link.startswith("https://www.daraz.com.bd/products/wishcare-underarm-roll-on-serum-50ml-i327665585-s1598953003.html")
    assert "&amp;" not in link


def test_finds_an_escaped_link_inside_a_script():
    page = '<html><script>location.replace("https:\\/\\/www.daraz.com.bd\\/products\\/x-i42-s7.html?a=1")</script></html>'
    assert DarazAdapter().product_link_in(page) == "https://www.daraz.com.bd/products/x-i42-s7.html?a=1"


def test_fetch_follows_a_share_link_to_the_product():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        if request.url.host == "s.daraz.com.bd":
            return httpx.Response(200, text=BRIDGE)
        return httpx.Response(200, text=PRODUCT)

    adapter = DarazAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    data = adapter.fetch(SHORT)
    assert seen == ["s.daraz.com.bd", "www.daraz.com.bd"]
    assert data.external_id == "i327665585-s1598953003"
    assert (data.price, data.original_price) == (649, 899)
    # The saved link is the clean product page, not the share link with tracking parameters.
    assert data.url == "https://www.daraz.com.bd/products/wishcare-underarm-roll-on-serum-50ml-i327665585-s1598953003.html"


def test_bridge_page_without_a_product_gives_a_clear_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><head><title>Daraz</title></head></html>")

    adapter = DarazAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(UnsupportedUrlError, match="address bar"):
        adapter.fetch(SHORT)
