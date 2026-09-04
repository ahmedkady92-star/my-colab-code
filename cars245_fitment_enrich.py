#!/usr/bin/env python3
"""Enrich Cars245 strict JSON with fitment rows from non-table application text.

Cars245 brake-pad pages often expose vehicle applications as plain text lines
rather than <tr> rows. This script reads every *_strict.json, re-fetches only
same-family brake-pad product URLs already discovered by Cars245, extracts
vehicle/application lines plus adjacent Important notes, and writes the rows
back into the strict JSON before final sanitization.
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
VEHICLE_MAKES = ("AUDI", "VOLKSWAGEN", "VW", "SKODA", "SEAT", "PORSCHE", "BENTLEY", "BMW", "LAND ROVER", "JAGUAR")
YEAR_RANGE_RE = re.compile(r"\b((?:19|20)\d{2})\s*[-–]\s*((?:19|20)\d{2}|NOW|CURRENT)\b", re.I)


def clean(s: str) -> str:
    return re.sub(r"\s+", " ", str(s)).strip()


def make_from(text: str) -> str:
    upper = text.upper()
    for make in VEHICLE_MAKES:
        if re.match(r"^\s*" + re.escape(make) + r"\b", upper):
            return "VOLKSWAGEN" if make == "VW" else make
    return ""


def is_brake_pad_url(url: str) -> bool:
    u = url.lower()
    return "brake-pad-set-disc-brake" in u or "brake-pads-for-disk-brake" in u or "brake-pads-with" in u


def extract_text_fitments(html: str, url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    strings = [clean(x) for x in soup.stripped_strings if clean(x)]
    rows, seen = [], set()
    i = 0
    while i < len(strings):
        text = strings[i]
        make = make_from(text)
        ym = YEAR_RANGE_RE.search(text)
        if not make or not ym:
            i += 1
            continue
        notes = ""
        if i + 1 < len(strings) and strings[i + 1].lower().startswith("important notes"):
            notes = strings[i + 1]
        combined = text + (" | " + notes if notes else "")
        key = (make, combined.upper())
        if key not in seen:
            seen.add(key)
            rows.append({
                "vehicle_make": make,
                "year_from": ym.group(1),
                "year_to": ym.group(2).lower().replace("current", "now"),
                "fitment_text": combined,
                "source_url": url,
            })
        i += 1
    return rows


def enrich_file(path: Path, session: requests.Session, max_urls: int) -> tuple[int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    existing = list(data.get("fitments", []))
    seen = {(x.get("vehicle_make", ""), x.get("fitment_text", "").upper()) for x in existing}

    # Only use Cars245 URLs already discovered for this part, and only brake-pad pages.
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
        for row in extract_text_fitments(r.text, url):
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
        "method": "Cars245 application text lines",
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
