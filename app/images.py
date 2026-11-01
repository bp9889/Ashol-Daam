"""Same product, different (vague) name: compare product photos.

Sellers often copy the same product photo, even when their titles say little ("Premium cover").
Two checks, cheapest first:
  1. the same photo file (same address on Daraz's image server): no download needed;
  2. a "fingerprint" of each photo (a difference hash): the photo shrunk to 17x16 grey pixels, each
     bit saying whether a pixel is brighter than its neighbour. Re-uploaded, resized or re-saved
     copies of a photo give (nearly) the same 256 bits; different photos don't.
Only small thumbnails (120x120) are downloaded, a few at a time.
"""

from __future__ import annotations

import io
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import httpx

log = logging.getLogger("asol_dam.images")

GRID = 16                # fingerprint = GRID x GRID bits (256)
MAX_DIFFERENT_BITS = 14  # of 256: copies differ by ~5, different products by 29+
MAX_PHOTOS = 30          # photos compared per check, at most
AT_ONCE = 8
SIZE_SUFFIX = re.compile(r"(\.(?:jpe?g|png|webp))_\d+x\d+q\d+\.(?:jpe?g|png|webp)(?:_\.webp)?$", re.IGNORECASE)
DARAZ_IMAGE_HOSTS = ("daraz.com.bd", "daraz.pk", "daraz.lk", "daraz.com.np", "lazcdn.com", "slatic.net")

_cache: dict[str, int | None] = {}


def photo_key(url: str | None) -> str | None:
    """The photo file itself, without size suffixes or query strings, so copies compare equal."""
    if not url:
        return None
    parsed = urlparse(url if "://" in url else "https:" + url)
    path = SIZE_SUFFIX.sub(r"\1", parsed.path)
    return f"{parsed.hostname}{path}".lower()


def thumbnail(url: str) -> str:
    """Daraz's image server makes small copies on request: <photo>.jpg_120x120q80.jpg"""
    url = url if "://" in url else "https:" + url
    parsed = urlparse(url)
    if not any((parsed.hostname or "").endswith(h) for h in DARAZ_IMAGE_HOSTS):
        return url
    path = SIZE_SUFFIX.sub(r"\1", parsed.path)
    return f"https://{parsed.hostname}{path}_120x120q80.jpg"


def fingerprint(data: bytes) -> int | None:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as image:
            image = image.convert("RGBA")
            # Transparent parts count as white (product photos usually sit on white).
            background = Image.new("RGBA", image.size, (255, 255, 255, 255))
            grey = Image.alpha_composite(background, image).convert("L").resize((GRID + 1, GRID), Image.LANCZOS)
            pixels = grey.tobytes()  # one byte per grey pixel, row by row
    except Exception:
        return None
    bits = 0
    for row in range(GRID):
        for col in range(GRID):
            left, right = pixels[row * (GRID + 1) + col], pixels[row * (GRID + 1) + col + 1]
            bits = (bits << 1) | (left > right)
    return bits


def different_bits(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _download(client: httpx.Client, url: str) -> int | None:
    if url in _cache:
        return _cache[url]
    value = None
    try:
        response = client.get(thumbnail(url), follow_redirects=True)
        if response.status_code == 200 and len(response.content) < 3_000_000:
            value = fingerprint(response.content)
    except httpx.HTTPError as exc:
        log.info("Couldn't get photo %s: %s", url, exc)
    _cache[url] = value
    return value


def fingerprints(urls: list[str], client: httpx.Client | None = None) -> dict[str, int]:
    urls = list(dict.fromkeys(u for u in urls if u))[:MAX_PHOTOS + 2]
    if not urls:
        return {}
    own = client or httpx.Client(timeout=5, headers={"User-Agent": "Mozilla/5.0 (AsolDam price checker)"})
    try:
        with ThreadPoolExecutor(max_workers=AT_ONCE) as pool:
            values = dict(zip(urls, pool.map(lambda u: _download(own, u), urls)))
    finally:
        if client is None:
            own.close()
    return {u: v for u, v in values.items() if v is not None}


def photo_distances(ours: list[str], candidates: list, client: httpx.Client | None = None,
                    download: bool = True) -> dict[str, int]:
    """How different each candidate's photo is from ours, in bits (0 = the same photo file).
    download=False: only same-file matches (instant). Candidates without a result are left out."""
    ours = [u for u in ours if u]
    if not ours or not candidates:
        return {}
    keys = {photo_key(u) for u in ours}
    found = {c.external_id: 0 for c in candidates if photo_key(c.image) in keys}
    rest = [c for c in candidates if c.external_id not in found and c.image][:MAX_PHOTOS] if download else []
    if rest:
        prints = fingerprints(ours + [c.image for c in rest], client)
        mine = [prints[u] for u in ours if u in prints]
        for c in rest:
            theirs = prints.get(c.image)
            if theirs is not None and mine:
                found[c.external_id] = min(different_bits(theirs, m) for m in mine)
    return found


def same_photo(ours: list[str], candidates: list, client: httpx.Client | None = None,
               download: bool = True) -> set[str]:
    """external_ids of candidates whose photo is ours: the same file, or the same fingerprint."""
    return {i for i, d in photo_distances(ours, candidates, client, download).items() if d <= MAX_DIFFERENT_BITS}
