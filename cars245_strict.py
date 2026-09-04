#!/usr/bin/env python3
"""Strict Cars245 parser for ELKADY AUTO.

Produces reviewable Cars245-only records:
Brand -> Part Number -> Product Type -> source URL, OEM references, and
unique vehicle fitment rows.

The parser deliberately avoids page-wide number extraction and filters linked
alternatives to the same part family as the searched item.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://cars245.com"
SEARCH_PATH = "/en/catalog/car-audi/?q={query}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

PRODUCT_TYPES = (
    "Shock Absorber", "Suspension Strut", "Gas Spring", "Brake Pad Set",
    "Brake Disc", "Water Pump", "Thermostat", "Control Arm", "Wheel Bearing",
    "Engine Mounting", "Transmission Mounting", "Oil Filter", "Air Filter",
    "Cabin Filter", "Fuel Filter", "Spark Plug", "Ignition Coil", "Sensor",
    "V-Ribbed Belt", "Timing Belt Set", "Timing Chain", "Belt Tensioner",
)

TYPE_FAMILY = {
    "Shock Absorber": "shock-absorber",
    "Suspension Strut": "shock-absorber",
    "Gas Spring": "gas-spring",
    "Brake Pad Set": "brake-pad",
    "Brake Disc": "brake-disc",
    "Water Pump": "water-pump",
    "Thermostat": "thermostat",
    "Control Arm": "control-arm",
    "Wheel Bearing": "wheel-bearing",
    "Engine Mounting": "engine-mount",
    "Transmission Mounting": "transmission-mount",
    "Oil Filter": "oil-filter",
    "Air Filter": "air-filter",
    "Cabin Filter": "cabin-filter",
    "Fuel Filter": "fuel-filter",
    "Spark Plug": "spark-plug",
    "Ignition Coil": "ignition-coil",
    "Sensor": "sensor",
    "V-Ribbed Belt": "belt",
    "Timing Belt Set": "timing-belt",
    "Timing Chain": "timing-chain",
    "Belt Tensioner": "belt-tensioner",
}

OEM_RE = re.compile(r"\b(?:[0-9A-Z]{1,4}\s?){2,5}[0-9A-Z]{2,4}\b", re.I)
BAD_TOKEN_RE = re.compile(
    r"(?:\b\d{2,3}\s*KW\b|\b\d{2,3}\s*HP\b|\b19\d{2}-20\d{2}\b|\b20\d{2}-20\d{2}\b|"
    r"\bEUR\b|\bUSD\b|\bGBP\b|\bEGP\b|AWARDS|GUIDES|CARS245|ABOUT|BUDGET|YOUR|ASK|MID|BRAND)",
    re.I,
)
VEHICLE_MAKES = ("AUDI", "VOLKSWAGEN", "VW", "SKODA", "SEAT", "PORSCHE", "BENTLEY", "BMW", "LAND ROVER", "JAGUAR")


def norm(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


def soup_get(s: requests.Session, url: str) -> BeautifulSoup:
    r = s.get(url, timeout=30)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def search_links(s: requests.Session, part: str) -> list[str]:
    url = BASE_URL + SEARCH_PATH.format(query=quote(part))
    soup = soup_get(s, url)
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        full = urljoin(BASE_URL, a["href"]).split("?")[0]
        if "/en/item/" in full and full not in seen:
            seen.add(full)
            out.append(full)
    return out


def _strip_product_type(text: str) -> tuple[str, str]:
    text = re.sub(r"\s+", " ", text).strip()
    for t in sorted(PRODUCT_TYPES, key=len, reverse=True):
        if text.lower().endswith(t.lower()):
            return text[: -len(t)].strip(), t
    return text, ""


def _split_brand_code(base: str) -> tuple[str, str]:
    """Split titles such as 'SACHS 312 638' and 'KYB 341822' safely."""
    tokens = base.split()
    if len(tokens) < 2:
        return "", ""

    # Join a trailing run of 2-4 purely numeric chunks: SACHS 312 638,
    # TOPRAN 112 038, MEYLE 126 625 0005.
    numeric_run = 0
    for tok in reversed(tokens):
        if re.fullmatch(r"\d{2,6}", tok):
            numeric_run += 1
        else:
            break
    if 2 <= numeric_run <= 4 and len(tokens) > numeric_run:
        brand = " ".join(tokens[:-numeric_run]).strip()
        code = "".join(tokens[-numeric_run:]).upper()
        if re.search(r"[A-Z]", brand, re.I):
            return brand.upper(), code

    # Normal case: final token is the part code, including alphanumeric codes.
    code = tokens[-1].upper()
    brand = " ".join(tokens[:-1]).strip().upper()
    if not re.search(r"[A-Z]", brand, re.I):
        return "", ""
    if not re.search(r"\d", code):
        return "", ""
    return brand, code


def parse_product_heading(text: str) -> tuple[str, str, str]:
    base, ptype = _strip_product_type(text)
    brand, code = _split_brand_code(base)
    if not brand or not code or BAD_TOKEN_RE.search(brand) or BAD_TOKEN_RE.search(code):
        return "", "", ptype
    return brand, code, ptype


def heading_from_soup(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)
    return soup.title.get_text(" ", strip=True) if soup.title else ""


def type_family(ptype: str) -> str:
    return TYPE_FAMILY.get(ptype, "")


def product_type_from_url(url: str) -> str:
    slug = urlparse(url).path.lower().rstrip("/").split("/")[-1]
    for ptype in sorted(PRODUCT_TYPES, key=len, reverse=True):
        token = ptype.lower().replace(" ", "-")
        if slug.endswith("-" + token) or slug == token:
            return ptype
    return ""


def block_texts_near_headings(soup: BeautifulSoup, words: tuple[str, ...]) -> list[str]:
    out, seen = [], set()
    for node in soup.find_all(["tr", "li", "section", "div", "p"]):
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
        low = text.lower()
        if not text or len(text) > 2200 or not any(w in low for w in words):
            continue
        if text not in seen:
            seen.add(text)
            out.append(text)
    return out


def clean_candidate(value: str) -> str:
    return re.sub(r"\s+", " ", value.upper()).strip(" |,;:")


def valid_part_candidate(value: str) -> bool:
    if not value or BAD_TOKEN_RE.search(value):
        return False
    compact = norm(value)
    if len(compact) < 6 or len(compact) > 22 or not re.search(r"\d", compact):
        return False
    if re.fullmatch(r"\d{2,3}(KW|HP)\d{4}\d{4}", compact):
        return False
    if re.fullmatch(r"\d{8,}", compact) and len(compact) >= 12:
        return False
    return True


def extract_oem_refs(soup: BeautifulSoup, primary: str) -> list[str]:
    refs, seen = [], {norm(primary)}
    blocks = block_texts_near_headings(soup, ("oe number", "oem", "original number", "cross reference", "replacement", "replaces", "replaced by"))
    for text in blocks:
        for raw in OEM_RE.findall(text):
            value = clean_candidate(raw)
            if not valid_part_candidate(value):
                continue
            n = norm(value)
            if n in seen or not re.search(r"[A-Z]", n):
                continue
            seen.add(n)
            refs.append(value)
    return refs


def extract_linked_alternatives(soup: BeautifulSoup, allowed_family: str) -> list[dict]:
    """Only Cars245 item links matching the searched part family are retained."""
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        full = urljoin(BASE_URL, a["href"]).split("?")[0]
        if "/en/item/" not in full:
            continue
        ptype_url = product_type_from_url(full)
        if allowed_family and type_family(ptype_url) != allowed_family:
            continue
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        brand = code = ptype = ""
        if label:
            brand, code, ptype = parse_product_heading(label)
            if not ptype:
                ptype = ptype_url
        if not brand or not code:
            continue
        key = (brand, norm(code), full)
        if key in seen:
            continue
        seen.add(key)
        out.append({"brand": brand, "part_number": code, "product_type": ptype, "url": full})
    return out


def extract_reference_brand_codes(soup: BeautifulSoup, known_brands: set[str]) -> list[dict]:
    """Capture brand/code mentions only inside reference/alternative blocks, never whole-page text."""
    blocks = block_texts_near_headings(soup, (
        "alternative", "cross reference", "replacement", "oe number", "oem", "original number"
    ))
    out, seen = [], set()
    for text in blocks:
        for brand in sorted(known_brands, key=len, reverse=True):
            if len(brand) < 2:
                continue
            # Accept one compact code or 2-4 numeric chunks after the brand.
            patt = re.compile(
                r"\b" + re.escape(brand) + r"\s+((?:\d{2,6}\s+){1,3}\d{2,6}|[A-Z0-9][A-Z0-9./_-]{2,20})\b",
                re.I,
            )
            for m in patt.finditer(text):
                raw = re.sub(r"\s+", "", m.group(1)).upper()
                if not valid_part_candidate(raw):
                    continue
                key = (brand.upper(), norm(raw))
                if key in seen:
                    continue
                seen.add(key)
                out.append({"brand": brand.upper(), "part_number": raw, "product_type": "", "url": ""})
    return out


def extract_fitment_rows(soup: BeautifulSoup, product_url: str) -> list[dict]:
    rows, seen = [], set()
    for tr in soup.find_all("tr"):
        cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
        if len(cells) < 2:
            continue
        text = " | ".join(cells)
        upper = text.upper()
        make = next((m for m in VEHICLE_MAKES if re.search(r"\b" + re.escape(m) + r"\b", upper)), "")
        years = re.findall(r"\b(19\d{2}|20\d{2})\b", text)
        if not make or not years:
            continue
        normalized_text = re.sub(r"\s+", " ", text).strip().upper()
        key = ("VOLKSWAGEN" if make == "VW" else make, normalized_text)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "vehicle_make": "VOLKSWAGEN" if make == "VW" else make,
            "year_from": min(years),
            "year_to": max(years),
            "fitment_text": text,
            "source_url": product_url,
        })
    return rows


def scrape_strict(part: str, max_products: int = 50, delay: float = 0.4, output_dir: str = "output") -> dict:
    s = session()
    links = search_links(s, part)[:max_products]
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    products, alternatives, oem_refs, all_fitments = [], [], [], []
    known_brands: set[str] = set()
    soups = []

    # First pass: parse search-result products and determine the dominant part family.
    parsed_search = []
    for url in links:
        sp = soup_get(s, url)
        heading = heading_from_soup(sp)
        brand, code, ptype = parse_product_heading(heading)
        if not ptype:
            ptype = product_type_from_url(url)
        parsed_search.append((url, sp, brand, code, ptype))
    families = [type_family(x[4]) for x in parsed_search if type_family(x[4])]
    allowed_family = Counter(families).most_common(1)[0][0] if families else ""

    for i, (url, sp, brand, code, ptype) in enumerate(parsed_search, 1):
        soups.append((url, sp))
        if allowed_family and type_family(ptype) != allowed_family:
            continue
        if brand and code:
            known_brands.add(brand)
            products.append({"brand": brand, "part_number": code, "product_type": ptype, "url": url})
            all_fitments.extend(extract_fitment_rows(sp, url))
        for ref in extract_oem_refs(sp, part):
            if ref not in oem_refs:
                oem_refs.append(ref)
        for alt in extract_linked_alternatives(sp, allowed_family):
            known_brands.add(alt["brand"])
            alternatives.append(alt)
        if delay and i < len(parsed_search):
            time.sleep(delay)

    # Second pass: brand/code mentions only inside reference/alternative blocks.
    for _, sp in soups:
        alternatives.extend(extract_reference_brand_codes(sp, known_brands))

    def dedupe(items, keyfn):
        out, seen = [], set()
        for x in items:
            k = keyfn(x)
            if k in seen:
                continue
            seen.add(k)
            out.append(x)
        return out

    products = dedupe(products, lambda x: (x["brand"], norm(x["part_number"])))
    alternatives = dedupe(alternatives, lambda x: (x["brand"], norm(x["part_number"])))
    merged_alts = dedupe(products + alternatives, lambda x: (x["brand"], norm(x["part_number"])))

    # Fitment is product-level knowledge, so dedupe across aftermarket brands/URLs.
    fitments = dedupe(all_fitments, lambda x: (x["vehicle_make"], x["fitment_text"].upper()))

    slug = re.sub(r"[^A-Z0-9]+", "_", part.upper()).strip("_").lower()
    pd.DataFrame(merged_alts).to_csv(Path(output_dir) / f"cars245_{slug}_alternatives.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(fitments).to_csv(Path(output_dir) / f"cars245_{slug}_fitment.csv", index=False, encoding="utf-8-sig")
    report = {
        "search_part": part.upper(),
        "product_links_found": len(links),
        "allowed_product_family": allowed_family,
        "alternatives_found": len(merged_alts),
        "oem_refs": oem_refs,
        "fitment_rows_found": len(fitments),
        "alternatives": merged_alts,
        "fitments": fitments,
    }
    (Path(output_dir) / f"cars245_{slug}_strict.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("part_number")
    p.add_argument("--max-products", type=int, default=50)
    p.add_argument("--delay", type=float, default=0.4)
    p.add_argument("--output-dir", default="output")
    args = p.parse_args()
    r = scrape_strict(args.part_number, args.max_products, args.delay, args.output_dir)
    print(f"product_links_found={r['product_links_found']}")
    print(f"allowed_product_family={r['allowed_product_family']}")
    print(f"alternatives_found={r['alternatives_found']}")
    print(f"fitment_rows_found={r['fitment_rows_found']}")
    print("oem_refs=" + " | ".join(r["oem_refs"]))
    for x in r["alternatives"]:
        print(f"ALT\t{x['brand']}\t{x['part_number']}\t{x.get('product_type','')}\t{x.get('url','')}")


if __name__ == "__main__":
    main()
