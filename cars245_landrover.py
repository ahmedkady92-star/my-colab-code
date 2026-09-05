#!/usr/bin/env python3
"""Land Rover-only Cars245 wrapper.

Keeps cars245_strict.py unchanged. It reuses the existing strict parser,
switches the catalog search path only for this process, and adds Land Rover
brake-pad URL recognition without changing the shared parser.
"""
import cars245_strict

cars245_strict.SEARCH_PATH = "/en/catalog/car-landrover/?q={query}"

_original_product_type_from_url = cars245_strict.product_type_from_url

def _landrover_product_type_from_url(url: str) -> str:
    low = url.lower()
    if any(token in low for token in (
        "brake-pad-set",
        "brake-pads-for-disk-brake",
        "brake-pads-with",
        "brk-lining",
        "brake-pad",
    )):
        return "Brake Pad Set"
    return _original_product_type_from_url(url)

cars245_strict.product_type_from_url = _landrover_product_type_from_url

if __name__ == "__main__":
    cars245_strict.main()
