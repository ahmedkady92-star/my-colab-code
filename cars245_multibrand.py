#!/usr/bin/env python3
import argparse
import cars245_strict
from cars245_brands import BRANDS, BRAKE_PAD_URL_TOKENS

_original_product_type_from_url = cars245_strict.product_type_from_url

def configure_brand(brand: str) -> None:
    key = brand.lower().replace(" ", "")
    if key not in BRANDS:
        raise SystemExit(f"Unsupported brand: {brand}. Supported: {', '.join(sorted(BRANDS))}")
    cars245_strict.SEARCH_PATH = BRANDS[key]["search_path"]

    def product_type_from_url(url: str) -> str:
        low = url.lower()
        if any(token in low for token in BRAKE_PAD_URL_TOKENS):
            return "Brake Pad Set"
        return _original_product_type_from_url(url)

    cars245_strict.product_type_from_url = product_type_from_url


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("brand")
    args, rest = p.parse_known_args()
    configure_brand(args.brand)
    import sys
    sys.argv = [sys.argv[0]] + rest
    cars245_strict.main()

if __name__ == "__main__":
    main()
