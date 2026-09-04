#!/usr/bin/env python3
"""Cars245 OE / cross-reference extractor for ELKADY AUTO.

Extracts identifiers only from OE/reference/alternative sections so generic
numbers from prices, engines, dimensions, etc. are not treated as part numbers.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

REFERENCE_HEADINGS = (
    "oe number", "oe numbers", "oem", "original number", "original numbers",
    "cross reference", "cross-reference", "alternative products",
    "alternative product", "replacement", "replaces", "replaced by",
)

PART_RE = re.compile(
    r"\b(?:[A-Z0-9]{1,4}[ -]?){1,4}[A-Z0-9]{2,8}\b",
    re.I,
)


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).upper()


def _looks_like_part(value: str) -> bool:
    compact = re.sub(r"[^A-Z0-9]", "", value.upper())
    if len(compact) < 6 or len(compact) > 24:
        return False
    # Require both letters and digits to avoid years/prices/measurements.
    return bool(re.search(r"[A-Z]", compact) and re.search(r"\d", compact))


def extract_cross_references(soup: BeautifulSoup, primary_part: str) -> list[dict]:
    primary_compact = re.sub(r"[^A-Z0-9]", "", primary_part.upper())
    refs: dict[str, dict] = {}

    # Restrict extraction to rows/blocks explicitly describing OE/reference data.
    for node in soup.find_all(["tr", "li", "p", "div", "section"]):
        text = node.get_text(" ", strip=True)
        lower = text.lower()
        if not text or len(text) > 1800:
            continue
        if not any(h in lower for h in REFERENCE_HEADINGS):
            continue

        source_type = "Cars245 Cross-Reference"
        if "alternative product" in lower:
            source_type = "Cars245 Alternative Product"
        elif "replaced by" in lower or "replaces" in lower:
            source_type = "Cars245 Supersession"
        elif "oe" in lower or "oem" in lower or "original" in lower:
            source_type = "Cars245 OE Reference"

        # Prefer linked product codes because Cars245 alternative-product rows
        # commonly expose the manufacturer code in their link/text.
        candidates = []
        for a in node.find_all("a", href=True):
            label = a.get_text(" ", strip=True)
            if label:
                candidates.extend(PART_RE.findall(label))
        candidates.extend(PART_RE.findall(text))

        for candidate in candidates:
            value = _norm(candidate)
            compact = re.sub(r"[^A-Z0-9]", "", value)
            if compact == primary_compact or not _looks_like_part(value):
                continue
            refs.setdefault(compact, {
                "value": value,
                "normalized": compact,
                "source_type": source_type,
                "verified_status": "Cars245 source - verify interchangeability",
                "confidence": "Medium",
                "notes": "Extracted only from Cars245 OE/reference/alternative section; confirm exact VIN/variant before customer fitment confirmation.",
            })

    return list(refs.values())
