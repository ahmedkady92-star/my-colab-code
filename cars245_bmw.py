#!/usr/bin/env python3
"""BMW-only Cars245 wrapper.

Keeps cars245_strict.py unchanged. Reuses the shared parser and switches the
catalog search path only for this process. Adds BMW brake-pad URL recognition
without changing Audi/VW or Land Rover behavior.
"""
import cars245_strict

cars245_strict.SEARCH_PATH = "/en/catalog/car-bmw/?q={query}"

_original_product_type_from_url = cars245_strict.product_type_from_url

def _bmw_product_type_from_url(url: str) -> str:
    low = url.lower()
    if any(token in low for token in (
        "brake-pad-set",
        "repair-kit-brake-pads",
        "set-brake-pads",
        "brake-pads",
        "brake-pad",
    )):
        return "Brake Pad Set"
    return _original_product_type_from_url(url)

cars245_strict.product_type_from_url = _bmw_product_type_from_url

if __name__ == "__main__":
    cars245_strict.main()
