#!/usr/bin/env python3
"""Structured Cars245 OE / aftermarket / alternative extractor.

Cars245 is the only source used by this module. The extractor preserves the
manufacturer/brand together with each part number so ELKADY AUTO can use true
Brand -> Part Number interchange data rather than a flat list of codes.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse
from bs4 import BeautifulSoup

REFERENCE_HEADINGS = (
    "oe number", "oe numbers", "oem", "original number", "original numbers",
    "cross reference", "cross-reference", "alternative products",
    "alternative product", "replacement", "replaces", "replaced by",
    "analog", "analogue", "equivalent",
)

# Broad enough for OEM and aftermarket codes while still requiring a digit.
PART_RE = re.compile(r"\b[A-Z0-9][A-Z0-9 ._/-]{3,22}[A-Z0-9]\b", re.I)

GENERIC_WORDS = {
    "OE", "OEM", "ORIGINAL", "NUMBER", "NUMBERS", "CROSS", "REFERENCE",
    "ALTERNATIVE", "PRODUCT", "PRODUCTS", "REPLACEMENT", "REPLACES",
    "REPLACED", "BY", "ANALOG", "ANALOGUE", "EQUIVALENT", "ARTICLE",
    "PART", "NO", "NR", "CODE", "ITEM",
}


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).upper()


def _compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", _norm(value))


def _looks_like_part(value: str) -> bool:
    compact = _compact(value)
    if len(compact) < 5 or len(compact) > 24:
        return False
    if not re.search(r"\d", compact):
        return False
    # Reject common years, dimensions and prices.
    if re.fullmatch(r"(?:19|20)\d{2}", compact):
        return False
    if re.fullmatch(r"\d+(?:MM|CM|KG|KW|HP|EUR|USD)", compact):
        return False
    return True


def _part_candidates(text: str) -> list[str]:
    out: list[str] = []
    # Split first on visual separators used by Cars245 tables/cards.
    chunks = re.split(r"[|•;:\n\t]", str(text))
    for chunk in chunks:
        chunk = _norm(chunk)
        if not chunk or len(chunk) > 80:
            continue
        # Prefer compact code-like tokens and VAG-style spaced OEM numbers.
        patterns = [
            r"\b\d[A-Z0-9]{2}\s?\d{3}\s?\d{3}(?:\s?[A-Z]{1,3})?\b",
            r"\b[A-Z]{1,5}[- ]?\d[A-Z0-9./_-]{3,18}\b",
            r"\b\d{3,}[A-Z0-9./_-]{0,12}\b",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, chunk, flags=re.I):
                value = _norm(match)
                if _looks_like_part(value) and value not in out:
                    out.append(value)
    return out


def _brand_from_text(text: str, part_value: str = "") -> str:
    text = _norm(text)
    if part_value:
        text = text.replace(_norm(part_value), " ")
    # Remove reference labels, punctuation and obvious descriptions after code.
    tokens = re.findall(r"[A-Z][A-Z0-9&+.-]{1,24}", text)
    kept: list[str] = []
    for token in tokens:
        if token in GENERIC_WORDS or re.search(r"\d", token):
            continue
        kept.append(token)
        if len(kept) >= 3:
            break
    return " ".join(kept)


def _brand_from_item_url(url: str) -> str:
    """Infer manufacturer from Cars245 item slug, e.g. /item/sachs-313569-..."""
    try:
        slug = urlparse(url).path.rstrip("/").split("/")[-1]
    except Exception:
        return ""
    parts = [p for p in slug.split("-") if p]
    brand_tokens: list[str] = []
    for token in parts:
        if re.search(r"\d", token):
            break
        if token.lower() in {"en", "item"}:
            continue
        brand_tokens.append(token.upper())
        if len(brand_tokens) >= 3:
            break
    return " ".join(brand_tokens)


def extract_main_product_reference(soup: BeautifulSoup, product_url: str, primary_part: str) -> dict | None:
    """Return the Cars245 result product itself as Brand -> manufacturer part no."""
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = soup.find("h1")
    h1_text = h1.get_text(" ", strip=True) if h1 else ""
    text = f"{h1_text} | {title}"
    candidates = _part_candidates(text)
    primary_norm = _compact(primary_part)
    part = next((p for p in candidates if _compact(p) != primary_norm), "")
    if not part:
        return None
    brand = _brand_from_item_url(product_url) or _brand_from_text(text, part)
    if not brand:
        return None
    return {
        "value": part,
        "normalized": _compact(part),
        "brand": brand,
        "identifier_type": "Aftermarket / Alternative Product",
        "source_type": "Cars245 Product Result",
        "verified_status": "Cars245 Listed Alternative",
        "confidence": "High",
        "product_url": product_url,
        "notes": "Manufacturer and part number captured from Cars245 product result linked to the searched OE number.",
    }


def extract_cross_references(soup: BeautifulSoup, primary_part: str, product_url: str = "") -> list[dict]:
    primary_compact = _compact(primary_part)
    refs: dict[tuple[str, str], dict] = {}

    main_ref = extract_main_product_reference(soup, product_url, primary_part) if product_url else None
    if main_ref:
        refs[(main_ref["normalized"], main_ref["brand"])] = main_ref

    # Cars245 OE/reference/alternative blocks.
    for node in soup.find_all(["tr", "li", "p", "div", "section", "article"]):
        text = node.get_text(" ", strip=True)
        lower = text.lower()
        if not text or len(text) > 2200:
            continue
        if not any(h in lower for h in REFERENCE_HEADINGS):
            continue

        if "alternative product" in lower or "analog" in lower or "equivalent" in lower:
            identifier_type = "Aftermarket / Alternative Product"
            source_type = "Cars245 Alternative Product"
        elif "replaced by" in lower or "replaces" in lower:
            identifier_type = "OEM Supersession"
            source_type = "Cars245 Supersession"
        else:
            identifier_type = "OEM Cross-Reference"
            source_type = "Cars245 OE Reference"

        linked_items = []
        for a in node.find_all("a", href=True):
            label = a.get_text(" ", strip=True)
            href = a.get("href", "")
            linked_items.append((label, href))

        candidates: list[tuple[str, str, str]] = []  # part, brand, url
        for label, href in linked_items:
            for part in _part_candidates(label):
                brand = _brand_from_item_url(href) or _brand_from_text(label, part)
                candidates.append((part, brand, href))
        for part in _part_candidates(text):
            candidates.append((part, _brand_from_text(text, part), ""))

        for value, brand, href in candidates:
            compact = _compact(value)
            if compact == primary_compact or not _looks_like_part(value):
                continue
            # OEM refs may legitimately have no separate aftermarket brand.
            if identifier_type.startswith("OEM") and not brand:
                brand = "AUDI / VOLKSWAGEN"
            key = (compact, brand)
            refs.setdefault(key, {
                "value": _norm(value),
                "normalized": compact,
                "brand": brand,
                "identifier_type": identifier_type,
                "source_type": source_type,
                "verified_status": "Cars245 Source",
                "confidence": "High",
                "product_url": href or product_url,
                "notes": "Extracted only from Cars245 OE/reference/alternative section. Brand is kept with its part number.",
            })

    return list(refs.values())
