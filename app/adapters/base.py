"""Every store gets an adapter. Adapters all return the same ProductData,
so the database, verdict logic and website never care which store a product came from."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable


@dataclass
class ProductData:
    source: str
    external_id: str
    url: str
    title: str
    price: float
    original_price: float | None = None
    image_url: str | None = None
    currency: str = "BDT"
    in_stock: bool = True
    # True when the page didn't state the exact price you pay (Daraz often fills it in with
    # scripts later). The adapter then confirms it another way, e.g. through search results.
    price_unconfirmed: bool = False
    # Listings often come in several sizes/options. `variant` is the one in the link ("30 ML Spray").
    variant: str | None = None
    variant_count: int = 1
    delivery: float | None = None  # standard delivery fee shown on the page (0 = free), when read
    category: str | None = None    # the store's category id for this product (most specific level)


@dataclass
class Listing:
    """One search result: the same (or a similar) product from another seller."""

    external_id: str
    title: str
    price: float
    original_price: float | None = None
    seller: str | None = None
    url: str | None = None
    # Buyer trust signals for this listing (None/0 when the store doesn't show them)
    rating: float | None = None   # average stars, 1-5
    reviews: int = 0              # number of ratings/reviews
    sold: int = 0                 # "136 sold"
    mall: bool = False            # official / Daraz Mall store
    overseas: bool = False        # ships from abroad (slow delivery)
    free_shipping: bool = False
    delivery: float | None = None # standard delivery fee read from the page (0 = free); None = unknown
    # The store's category path, broadest first, e.g. ["2", "9536", "9543"] (Mobile accessories > Phone cases)
    categories: tuple[str, ...] = ()
    photo_match: bool = False      # its photo is our product's photo (same file or same fingerprint)
    photo_distance: int | None = None  # how different its photo is from ours (0-256 bits); None = not compared
    image: str | None = None      # product photo for this listing
    # Set when this listing was narrowed to one size/option (search shows only the cheapest one).
    size_checked: bool = False
    # True when we only know this option's regular price; Daraz may sell it for less right now.
    price_unconfirmed: bool = False
    confirmed_at: str | None = None  # when someone confirmed this price on our site (ISO date)


class AdapterError(Exception):
    """Something went wrong reading a product. The message is shown to the user."""


class UnsupportedUrlError(AdapterError):
    pass


class PriceNeeded(AdapterError):
    """The store doesn't publish the sale price of this size/option. Ask the person to type it."""

    def __init__(self, message: str, variant: str | None = None, old_price: float | None = None):
        super().__init__(message)
        self.variant = variant
        self.old_price = old_price


class BlockedError(AdapterError):
    """The store showed a captcha / bot check instead of the product page."""


class Adapter(ABC):
    source: str = ""

    @abstractmethod
    def matches(self, url: str) -> bool:
        """True if this adapter can handle the given link."""

    @abstractmethod
    def product_key(self, url: str) -> str:
        """Stable id for the product, taken from the link (no network call)."""

    @abstractmethod
    def fetch(self, url: str, manual_price: float | None = None) -> ProductData:
        """Download the product page and return its current data. `manual_price` is a price the
        person typed, used only when the store doesn't publish the price itself."""

    def size_option(self, listing: Listing, wanted: Callable[[str], bool]) -> Listing | None:
        """A listing that sells several sizes, narrowed to the size `wanted` accepts (by option name).
        None if it doesn't sell that size. Stores without this just return None."""
        return None

    def see_prices(self, urls: list[str]) -> dict:
        """Prices as a shopper sees them on each page ({url: SeenPrice}), for pages whose data doesn't
        include the sale price. Stores that don't need this return nothing."""
        return {}

    def search(self, query: str, host_url: str | None = None) -> list[Listing]:
        """Search the store. Used to compare a product with other sellers.
        Stores without search support just return nothing."""
        return []
