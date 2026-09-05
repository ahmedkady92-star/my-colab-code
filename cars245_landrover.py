#!/usr/bin/env python3
"""Land Rover-only Cars245 wrapper.

Keeps cars245_strict.py unchanged. It reuses the existing strict parser but
switches the catalog search path only for this process.
"""
import cars245_strict

cars245_strict.SEARCH_PATH = "/en/catalog/car-landrover/?q={query}"

if __name__ == "__main__":
    cars245_strict.main()
