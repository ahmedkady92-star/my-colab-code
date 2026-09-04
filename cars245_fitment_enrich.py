#!/usr/bin/env python3
"""Enrich Cars245 strict JSON with fitment rows from brake-pad compatibility text.

Cars245 brake-pad pages expose vehicle compatibility in text that is often
concatenated inside HTML containers, for example:
SKODA SUPERB III (3V3)DPCA Petrol 1.5 150hp 110kw 2017-now
Important notes:Fitting Position: Rear Axle; For PR number: 1KU

This script reconstructs the page text, extracts only vehicle/application
records with fuel + hp + kW + year-range signatures, attaches the immediately
following Important notes, and writes the result back into *_strict.json before
final sanitization.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
VEHICLE_MAKES = (
    "AUDI", "VOLKSWAGEN", "VW", "SKODA", "SEAT", "PORSCHE", "BENTLEY",
    "BMW", "LAND ROVER", "JAGUAR",
)
MAKE_ALT = "|".join(sorted((re.escape(x) for x in VEHICLE_MAKES), key=len, reverse=True))
YEAR_RANGE_RE = re.compile(r"\b((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2}|NOW|CURRENT)\b", re.I)
FUEL_RE = r"(?:Petrol/Electric|Diesel/Electric|Petrol|Diesel|CNG|Electric)"

# Compatibility rows on Cars245 contain a vehicle make/model, engine/fuel,
# displacement, horsepower, kilowatts and a model-year range. Requiring all of
# those tokens prevents alternative-product/OEM lists from being mistaken for
# vehicle fitment.
VEHICLE_ENTRY_RE = re.compile(
    rf"(?P<entry>\b(?P<make>{MAKE_ALT})\s+"
    rf"(?:(?!\bImportant\s+notes\s*:).){{1,220}}?"
    rf"\b{FUEL_RE}\b\s+"
    rf"\d{{1,2}}(?:[.,]\d+)?\s+"
    rf"\d{{2,4}}\s*hp\s+\d{{2,4}}\s*kw\s+"
    rf"(?P<year_from>(?:19|20)\d{{2}})\s*[-–]\s*"
    rf"(?P<year_to>(?:(?:19|20)\d{{2}}|now|current))\b)",
    re.I,
)
NEXT_VEHICLE_RE = re.compile(rf"\b(?:{MAKE_ALT})\s+", re.I)


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


def normalize_make(make: str) -> str:
    make = make.upper().strip()
    return "VOLKSWAGEN" if make == "VW" else make


def is_brake_pad_url(url: str) -> bool:
    u = url.lower()
    return (
        "brake-pad-set-disc-brake" in u
        or "brake-pads-for-disk-brake" in u
        or "brake-pads-with" in u
        or "brk-lining" in u
    )


def _following_notes(text: str, end: int) -> str:
    """Return only the Important notes block immediately following an entry."""
    tail = text[end:end + 1200].lstrip(" |:-")
    if not re.match(r"Important\s+notes\s*:", tail, re.I):
        return ""

    # Stop before the next vehicle entry. This preserves PR codes, fitting
    # position, construction-year constraints and engine-number rules.
    nxt = NEXT_VEHICLE_RE.search(tail, 1)
    if nxt:
        tail = tail[:nxt.start()]
    # Defensive limit in case the source markup has lost separators.
    tail = tail[:900]
    return clean(tail)


def extract_text_fitments(html: str, url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    # Cars245 frequently splits one compatibility row across several HTML text
    # nodes. Joining stripped_strings recreates the visible sequence reliably.
    text = clean(" ".join(soup.stripped_strings))

    rows, seen = [], set()
    for m in VEHICLE_ENTRY_RE.finditer(text):
        make = normalize_make(m.group("make"))
        entry = clean(m.group("entry"))
        notes = _following_notes(text, m.end())
        combined = entry + (" | " + notes if notes else "")
        key = (make, combined.upper())
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "vehicle_make": make,
            "year_from": m.group("year_from"),
            "year_to": m.group("year_to").lower().replace("current", "now"),
            "fitment_text": combined,
            "source_url": url,
        })
    return rows


def enrich_file(path: Path, session: requests.Session, max_urls: int) -> tuple[int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    existing = list(data.get("fitments", []))
    seen = {
        (x.get("vehicle_make", ""), x.get("fitment_text", "").upper())
        for x in existing
    }

    urls = []
    for item in data.get("alternatives", []):
        url = str(item.get("url", "")).strip()
        if url and is_brake_pad_url(url) and url not in urls:
            urls.append(url)
        if len(urls) >= max_urls:
            break

    added = 0
    for url in urls:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        extracted = extract_text_fitments(r.text, url)
        print(f"FITMENT_URL {url}: extracted={len(extracted)}")
        for row in extracted:
            key = (row["vehicle_make"], row["fitment_text"].upper())
            if key in seen:
                continue
            seen.add(key)
            existing.append(row)
            added += 1

    if urls and (data.get("allowed_product_family") in ("", None)):
        data["allowed_product_family"] = "brake-pad"
    data["fitments"] = existing
    data["fitment_rows_found"] = len(existing)
    data["fitment_enrichment"] = {
        "method": "Cars245 reconstructed vehicle compatibility text",
        "brake_pad_urls_checked": len(urls),
        "rows_added": added,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(urls), added


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", default="output")
    p.add_argument("--max-urls", type=int, default=8)
    args = p.parse_args()

    s = requests.Session()
    s.headers.update(HEADERS)
    files = sorted(Path(args.input_dir).glob("*_strict.json"))
    if not files:
        raise SystemExit("No *_strict.json files found")
    for f in files:
        urls, added = enrich_file(f, s, args.max_urls)
        print(f"FITMENT_ENRICH {f.name}: urls={urls} added={added}")


if __name__ == "__main__":
    main()
