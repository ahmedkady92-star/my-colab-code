#!/usr/bin/env python3
"""Strict Cars245 parser for ELKADY AUTO.

Goal: produce only structured, reviewable records from Cars245:
Brand -> Part Number -> source URL, plus OEM references and fitment rows.
Avoid broad full-page regex that misclassifies horsepower, kW, years, prices, etc.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urljoin

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

OEM_RE = re.compile(r"\b(?:[0-9A-Z]{1,4}\s?){2,5}[0-9A-Z]{2,4}\b", re.I)
BAD_TOKEN_RE = re.compile(
    r"(?:\b\d{2,3}\s*KW\b|\b\d{2,3}\s*HP\b|\b19\d{2}-20\d{2}\b|\b20\d{2}-20\d{2}\b|"
    r"\bEUR\b|\bUSD\b|\bGBP\b|\bEGP\b|AWARDS|GUIDES|CARS245|ABOUT|BUDGET|YOUR|ASK|MID|BRAND|SHOCK$)",
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


def parse_product_heading(text: str) -> tuple[str, str, str]:
    text = re.sub(r"\s+", " ", text).strip()
    ptype = ""
    for t in sorted(PRODUCT_TYPES, key=len, reverse=True):
        if text.lower().endswith(t.lower()):
            ptype = t
            text = text[: -len(t)].strip()
            break
    # Last token before product type is usually manufacturer part number.
    m = re.match(r"^(.*?)\s+([A-Z0-9][A-Z0-9./_-]{2,})$", text, re.I)
    if not m:
        return "", "", ptype
    brand = m.group(1).strip()
    code = m.group(2).strip().upper()
    if not brand or BAD_TOKEN_RE.search(brand) or BAD_TOKEN_RE.search(code):
        return "", "", ptype
    return brand.upper(), code, ptype


def heading_from_soup(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(" ", strip=True)
    return soup.title.get_text(" ", strip=True) if soup.title else ""


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
    if len(compact) < 6 or len(compact) > 22:
        return False
    if not re.search(r"\d", compact):
        return False
    # reject engine/power/year-ish values
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
            # OEM family identifiers normally contain at least one letter, unless explicitly short manufacturer code.
            if n in seen:
                continue
            if not re.search(r"[A-Z]", n):
                continue
            seen.add(n)
            refs.append(value)
    return refs


def extract_linked_alternatives(soup: BeautifulSoup) -> list[dict]:
    """Use Cars245 item links and their human labels; this is much safer than page-wide number regex."""
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        full = urljoin(BASE_URL, a["href"]).split("?")[0]
        if "/en/item/" not in full:
            continue
        label = re.sub(r"\s+", " ", a.get_text(" ", strip=True)).strip()
        if not label:
            continue
        brand, code, ptype = parse_product_heading(label)
        if not brand or not code:
            # Sometimes link labels omit product type; try brand+code only.
            m = re.match(r"^(.*?)\s+([A-Z0-9][A-Z0-9./_-]{2,})$", label, re.I)
            if m:
                brand, code = m.group(1).strip().upper(), m.group(2).strip().upper()
                ptype = ""
        if not brand or not code or BAD_TOKEN_RE.search(brand) or BAD_TOKEN_RE.search(code):
            continue
        key = (brand, norm(code), full)
        if key in seen:
            continue
        seen.add(key)
        out.append({"brand": brand, "part_number": code, "product_type": ptype, "url": full})
    return out


def extract_brand_code_mentions(soup: BeautifulSoup, known_brands: set[str]) -> list[dict]:
    """Capture Cars245 text mentions like 'SACHS 312638' only for brands already seen in Cars245 link/title data."""
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    out, seen = [], set()
    for brand in sorted(known_brands, key=len, reverse=True):
        if len(brand) < 2:
            continue
        patt = re.compile(r"\b" + re.escape(brand) + r"\s+([A-Z0-9][A-Z0-9./_-]{2,20})\b", re.I)
        for m in patt.finditer(text):
            code = m.group(1).upper()
            if not valid_part_candidate(code):
                continue
            key = (brand.upper(), norm(code))
            if key in seen:
                continue
            seen.add(key)
            out.append({"brand": brand.upper(), "part_number": code, "product_type": "", "url": ""})
    return out


def extract_fitment_rows(soup: BeautifulSoup, product_url: str, brand: str, code: str) -> list[dict]:
    rows, seen = [], set()
    # Prefer table rows: Cars245 compatibility is often rendered as tabular text.
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
        key = tuple(cells)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "brand": brand,
            "part_number": code,
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
    products, alternatives, oem_refs, fitments = [], [], [], []
    known_brands: set[str] = set()

    soups = []
    for i, url in enumerate(links, 1):
        sp = soup_get(s, url)
        soups.append((url, sp))
        heading = heading_from_soup(sp)
        brand, code, ptype = parse_product_heading(heading)
        if brand and code:
            known_brands.add(brand)
            products.append({"brand": brand, "part_number": code, "product_type": ptype, "url": url})
            fitments.extend(extract_fitment_rows(sp, url, brand, code))
        for ref in extract_oem_refs(sp, part):
            if ref not in oem_refs:
                oem_refs.append(ref)
        for alt in extract_linked_alternatives(sp):
            known_brands.add(alt["brand"])
            alternatives.append(alt)
        if delay and i < len(links):
            time.sleep(delay)

    # Second pass lets us recognize brands discovered anywhere in Cars245 links/titles.
    for url, sp in soups:
        alternatives.extend(extract_brand_code_mentions(sp, known_brands))

    def dedupe(items, keyfn):
        out, seen = [], set()
        for x in items:
            k = keyfn(x)
            if k in seen:
                continue
            seen.add(k)
            out.append(x)
        return out

    products = dedupe(products, lambda x: (x["brand"], norm(x["part_number"]), x["url"]))
    alternatives = dedupe(alternatives, lambda x: (x["brand"], norm(x["part_number"])))
    fitments = dedupe(fitments, lambda x: (x["brand"], norm(x["part_number"]), x["fitment_text"]))

    # Search result products are themselves valid alternatives for the searched OEM number.
    merged_alts = dedupe(products + alternatives, lambda x: (x["brand"], norm(x["part_number"])))

    slug = re.sub(r"[^A-Z0-9]+", "_", part.upper()).strip("_").lower()
    pd.DataFrame(merged_alts).to_csv(Path(output_dir) / f"cars245_{slug}_alternatives.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(fitments).to_csv(Path(output_dir) / f"cars245_{slug}_fitment.csv", index=False, encoding="utf-8-sig")
    report = {
        "search_part": part.upper(),
        "product_links_found": len(links),
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
    print(f"alternatives_found={r['alternatives_found']}")
    print(f"fitment_rows_found={r['fitment_rows_found']}")
    print("oem_refs=" + " | ".join(r["oem_refs"]))
    for x in r["alternatives"]:
        print(f"ALT\t{x['brand']}\t{x['part_number']}\t{x.get('product_type','')}\t{x.get('url','')}")


if __name__ == "__main__":
    main()
