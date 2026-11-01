from .base import Adapter, AdapterError, BlockedError, Listing, PriceNeeded, ProductData, UnsupportedUrlError
from .daraz import DarazAdapter

# To support a new store later (Amazon via its official Creators API, Pickaboo, ...),
# write a new Adapter subclass and add it to this list. Nothing else has to change.
ADAPTERS: list[Adapter] = [DarazAdapter()]


def get_adapter(url: str) -> Adapter:
    for adapter in ADAPTERS:
        if adapter.matches(url):
            return adapter
    raise UnsupportedUrlError("Only Daraz product links are supported right now.")


__all__ = [
    "ADAPTERS",
    "Adapter",
    "AdapterError",
    "BlockedError",
    "Listing",
    "PriceNeeded",
    "ProductData",
    "UnsupportedUrlError",
    "get_adapter",
]
