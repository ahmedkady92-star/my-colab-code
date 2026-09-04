#!/usr/bin/env python3
"""ELKADY AUTO - Cars245 scraper/research helper.

Derived from the original Colab notebook uploaded by the user. It keeps the
same workflow in one reusable script:
1) search Cars245 by part number,
2) collect /en/item/ product links,
3) extract product/OE/compatibility text,
4) save raw and cleaned CSV files.

Use responsibly and verify exact vehicle fitment by VIN/transmission code.
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
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
VEHICLE_KEYWORDS = [
    "AUDI", "VOLKSWAGEN", "VW", "SKODA", "SEAT", "PORSCHE",
    "BENTLEY", "LAMBORGHINI", "BMW", "LAND ROVER", "JAGUAR",
]
AFTERMARKET_BRANDS = [
    "MEYLE", "VEMO", "VAICO", "INA", "SKF", "FEBI", "BILSTEIN",
    "TRISCAN", "TOPRAN", "SWAG", "MAGNETI MARELLI", "GATES",
    "CONTITECH", "PIERBURG", "BOSCH", "HEPU", "DAYCO", "METZGER",
]


def normalize_part_number(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).upper()


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    return session


def get_soup(session: requests.Session, url: str, timeout: int = 30) -> BeautifulSoup:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def search_product_links(session: requests.Session, part_number: str) -> list[str]:
    part = normalize_part_number(part_number)
    search_url = BASE_URL + SEARCH_PATH.format(query=quote(part))
    soup = get_soup(session, search_url)

    links: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        full_url = urljoin(BASE_URL, a["href"]).split("?")[0]
        if "/en/item/" not in full_url or full_url in seen:
            continue
        seen.add(full_url)
        links.append(full_url)
    return links


def extract_part_numbers(text: str) -> list[str]:
    patterns = [
        r"\b\d{2}[A-Z]\s?\d{3}\s?\d{3}\s?[A-Z]{1,3}\b",
        r"\b[A-Z0-9]{1,6}[-\s]?\d{3,10}[-\s]?[A-Z0-9]{0,6}\b",
    ]
    found: set[str] = set()
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = re.sub(r"\s+", " ", str(match).upper()).strip()
            if len(value) >= 5:
                found.add(value)
    return sorted(found)


def unique_text_blocks(soup: BeautifulSoup, keywords: list[str], max_len: int = 1500) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for element in soup.find_all(["tr", "td", "li", "p", "div", "span"]):
        value = element.get_text(" ", strip=True)
        if not value or len(value) > max_len:
            continue
        lower = value.lower()
        if not any(key in lower for key in keywords):
            continue
        if value not in seen:
            seen.add(value)
            values.append(value)
    return values


def detect_brand_from_text(text: str) -> str:
    upper = text.upper()
    for brand in AFTERMARKET_BRANDS:
        if brand in upper:
            return brand
    return ""


def detect_vehicle_makes(text: str) -> str:
    upper = text.upper()
    found: list[str] = []
    for brand in VEHICLE_KEYWORDS:
        if re.search(r"\b" + re.escape(brand) + r"\b", upper) and brand not in found:
            found.append(brand)
    return " | ".join(found)


def extract_product(session: requests.Session, product_url: str, search_part: str) -> dict:
    soup = get_soup(session, product_url)
    page_text = soup.get_text(" ", strip=True)
    title = soup.title.get_text(" ", strip=True) if soup.title else ""

    h1 = soup.find("h1")
    product_name = h1.get_text(" ", strip=True) if h1 else title
    brand = detect_brand_from_text(" ".join([title, product_name, page_text[:2500]]))

    price = ""
    currency = ""
    price_match = re.search(r"(?<!\d)(\d{1,6}(?:[.,]\d{1,2})?)\s*(EUR|USD|GBP|EGP|€|\$|£)", page_text, re.I)
    if price_match:
        price = price_match.group(1)
        currency = price_match.group(2)

    oe_data = unique_text_blocks(
        soup,
        ["oe number", "oem", "original", "alternative", "cross reference", "replacement"],
    )
    compatibility = unique_text_blocks(
        soup,
        [
            "compatibility", "compatible", "vehicle", "model", "engine", "year",
            "audi", "volkswagen", "skoda", "seat", "porsche", "bentley",
            "bmw", "land rover", "jaguar",
        ],
    )

    tables_text = [
        table.get_text(" | ", strip=True)
        for table in soup.find_all("table")
        if table.get_text(" | ", strip=True)
    ]

    vehicle_links: list[str] = []
    seen_links: set[str] = set()
    for a in soup.find_all("a", href=True):
        link_text = a.get_text(" ", strip=True)
        full_url = urljoin(BASE_URL, a["href"])
        combined = (link_text + " " + full_url).lower()
        if any(x in combined for x in [
            "audi", "volkswagen", "skoda", "seat", "porsche", "bentley",
            "bmw", "land-rover", "jaguar",
        ]):
            if full_url not in seen_links:
                seen_links.add(full_url)
                vehicle_links.append(full_url)

    part_numbers = extract_part_numbers(" || ".join([page_text, " ".join(oe_data)]))

    return {
        "Search_Part": normalize_part_number(search_part),
        "Product_Name": product_name,
        "Brand": brand,
        "Price": price,
        "Currency": currency,
        "Part_Numbers": " | ".join(part_numbers),
        "OE_Alternative": " || ".join(oe_data),
        "Compatibility": " || ".join(compatibility),
        "Tables": " || ".join(tables_text),
        "Vehicle_Links": " || ".join(vehicle_links),
        "Detected_Vehicles": detect_vehicle_makes(page_text),
        "Product_URL": product_url,
    }


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy().fillna("")
    df.columns = [re.sub(r"[^a-z0-9_]+", "_", str(c).lower()).strip("_") for c in df.columns]

    def clean_text(value: object) -> str:
        return re.sub(r"\s+", " ", str(value)).strip()

    for col in df.columns:
        df[col] = df[col].map(clean_text)

    all_text = df.astype(str).agg(" | ".join, axis=1)
    df["detected_vehicles"] = all_text.map(detect_vehicle_makes)
    df["detected_brand"] = all_text.map(detect_brand_from_text)

    def extract_urls(text: str) -> str:
        urls = re.findall(r"https?://cars245\.com/[^\s|]+", text)
        out: list[str] = []
        for url in urls:
            url = url.rstrip(".,;")
            if url not in out:
                out.append(url)
        return " | ".join(out)

    df["cars245_urls"] = all_text.map(extract_urls)
    return df.drop_duplicates().reset_index(drop=True)


def scrape_part(
    part_number: str,
    max_products: int = 20,
    delay_seconds: float = 1.0,
    output_dir: str | Path = ".",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    part = normalize_part_number(part_number)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    session = build_session()
    links = search_product_links(session, part)[:max_products]
    print(f"Cars245 product links found: {len(links)}")

    rows: list[dict] = []
    for index, url in enumerate(links, start=1):
        print(f"[{index}/{len(links)}] {url}")
        try:
            rows.append(extract_product(session, url, part))
        except Exception as exc:
            print(f"ERROR: {exc}")
        if delay_seconds > 0 and index < len(links):
            time.sleep(delay_seconds)

    raw_df = pd.DataFrame(rows)
    clean_df = clean_dataframe(raw_df) if not raw_df.empty else raw_df.copy()

    slug = re.sub(r"[^A-Z0-9]+", "_", part).strip("_").lower()
    raw_path = output_dir / f"cars245_{slug}_raw.csv"
    clean_path = output_dir / f"cars245_{slug}_clean.csv"
    json_path = output_dir / f"cars245_{slug}_clean.json"

    raw_df.to_csv(raw_path, index=False, encoding="utf-8-sig")
    clean_df.to_csv(clean_path, index=False, encoding="utf-8-sig")
    json_path.write_text(
        json.dumps(clean_df.to_dict(orient="records"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Raw CSV: {raw_path}")
    print(f"Clean CSV: {clean_path}")
    print(f"Clean JSON: {json_path}")
    return raw_df, clean_df


def main() -> None:
    parser = argparse.ArgumentParser(description="ELKADY AUTO Cars245 part researcher")
    parser.add_argument("part_number", help='Part number, e.g. "04E 121 600 BE"')
    parser.add_argument("--max-products", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()

    _, clean_df = scrape_part(
        args.part_number,
        max_products=args.max_products,
        delay_seconds=args.delay,
        output_dir=args.output_dir,
    )

    if not clean_df.empty:
        preview_cols = [c for c in [
            "search_part", "product_name", "brand", "part_numbers",
            "detected_vehicles", "product_url",
        ] if c in clean_df.columns]
        print("\nPREVIEW:\n")
        print(clean_df[preview_cols].head(20).to_string(index=False))


if __name__ == "__main__":
    main()
