#!/usr/bin/env python3
"""Final sanitizer for Cars245 strict-parser output.

Produces Sheet-safe Cars245-only data:
- direct search-result alternatives,
- branded aftermarket references found in Cars245 reference blocks,
- clean OEM revisions/supersessions,
- unique fitment rows.

The sanitizer is conservative: uncertain values are dropped rather than written
into the CRM as verified identifiers.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

PRODUCT_TYPE_WORDS = (
    "SHOCK ABSORBER", "SUSPENSION STRUT", "GAS SPRING", "BRAKE PAD SET",
    "BRAKE DISC", "WATER PUMP", "THERMOSTAT", "CONTROL ARM", "WHEEL BEARING",
    "ENGINE MOUNTING", "TRANSMISSION MOUNTING", "OIL FILTER", "AIR FILTER",
    "CABIN FILTER", "FUEL FILTER", "SPARK PLUG", "IGNITION COIL",
    "V-RIBBED BELT", "TIMING BELT SET", "TIMING CHAIN", "BELT TENSIONER",
)
BAD_WORDS = re.compile(
    r"(?:\bKW\b|\bHP\b|AWARDS|GUIDES|CARS245|ABOUT|BUDGET|YOUR|ASK|MID|UNKNOWN|\bOEM\b$)",
    re.I,
)
VEHICLE_OR_OE_BRANDS = {
    "AUDI", "VOLKSWAGEN", "VW", "SKODA", "SEAT", "PORSCHE", "BENTLEY",
    "BMW", "LAND ROVER", "JAGUAR",
}
BRAND_NOISE = {
    "UNKNOWN", "SHOCK", "ABSORBER", "SUSPENSION", "STRUT", "ORIGINAL",
    "NUMBER", "REFERENCE", "REPLACEMENT", "OEM", "OE",
}


def norm(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def clean_brand(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value).upper()).strip(" -_|,:;()")
    changed = True
    while changed:
        changed = False
        for phrase in PRODUCT_TYPE_WORDS:
            if value.endswith(" " + phrase):
                value = value[: -(len(phrase) + 1)].strip()
                changed = True
            elif value == phrase:
                return ""
    return value


def clean_code(value: str) -> str:
    value = str(value).upper().strip()
    value = re.sub(r"^[\s(\[{<]+|[\s)\]}>]+$", "", value)
    value = re.sub(r"\s+", " ", value).strip(" |,;:")
    if re.fullmatch(r"(?:\d{2,6}\s+){1,3}\d{2,6}", value):
        value = value.replace(" ", "")
    return value


def valid_alt(brand: str, code: str) -> bool:
    if not brand or not code or BAD_WORDS.search(brand) or BAD_WORDS.search(code):
        return False
    if brand in VEHICLE_OR_OE_BRANDS or brand in BRAND_NOISE:
        return False
    compact = norm(code)
    if len(compact) < 4 or len(compact) > 24 or not re.search(r"\d", compact):
        return False
    if re.search(r"\b(?:19|20)\d{2}[-/]?(?:19|20)\d{2}\b", code):
        return False
    if re.fullmatch(r"\d{2,3}(?:KW|HP).*", compact):
        return False
    return True


def format_vag(n: str) -> str:
    """Format compact VAG OE number, e.g. 4F0413031AA -> 4F0 413 031 AA."""
    if len(n) < 9:
        return n
    return " ".join(x for x in (n[:3], n[3:6], n[6:9], n[9:]) if x)


def clean_oem_refs(primary: str, refs: list[str]) -> list[str]:
    """Recover high-confidence OE revisions from noisy Cars245 block text."""
    p = norm(primary)
    vag = bool(re.fullmatch(r"[0-9A-Z]{3}\d{6}[0-9A-Z]{0,3}", p))
    base = p[:9] if vag else ""
    out, seen = [], {p}

    for raw in refs:
        raw = clean_code(raw)
        if vag:
            # Cars245 block text often prefixes the OE number with AUDI/VOLKSWAGEN.
            nraw = norm(raw)
            m = re.search(re.escape(base) + r"[0-9A-Z]{0,3}", nraw)
            if not m:
                continue
            n = m.group(0)
            if n in seen:
                continue
            seen.add(n)
            out.append(format_vag(n))
            continue

        n = norm(raw)
        if not n or n in seen or BAD_WORDS.search(raw):
            continue
        if len(n) < 6 or len(n) > 18 or not re.search(r"\d", n):
            continue
        if len(raw.split()) > 4:
            continue
        seen.add(n)
        out.append(raw)
    return out


def extract_branded_refs(refs: list[str]) -> list[dict]:
    """Recover Cars245 aftermarket references such as SACHS 312638.

    The input is already restricted by the strict parser to OE/cross-reference/
    alternative blocks. This function only turns clear BRAND + CODE pairs into
    aftermarket records and ignores vehicle/OE brands.
    """
    out, seen = [], set()
    pattern = re.compile(
        r"\b([A-Z][A-Z&.+-]*(?:\s+[A-Z][A-Z&.+-]*){0,2})\s+"
        r"([A-Z0-9][A-Z0-9./_-]{3,20})\b",
        re.I,
    )
    for raw in refs:
        text = re.sub(r"^\s*\d{1,3}\s+", "", str(raw).upper()).strip()
        for m in pattern.finditer(text):
            brand = clean_brand(m.group(1))
            code = clean_code(m.group(2))
            # Trim accidental leading descriptor words from a brand phrase.
            bt = brand.split()
            while bt and bt[0] in BRAND_NOISE:
                bt.pop(0)
            brand = " ".join(bt)
            if not valid_alt(brand, code):
                continue
            key = (brand, norm(code))
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "brand": brand,
                "part_number": code,
                "product_type": "",
                "url": "",
                "source": "Cars245",
                "relation": "cross_reference",
            })
    return out


def finalize(input_dir: str, output_dir: str | None = None) -> dict:
    input_path = Path(input_dir)
    output_path = Path(output_dir or input_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    json_files = sorted(input_path.glob("*_strict.json"))
    if not json_files:
        raise SystemExit("No *_strict.json found")
    report = json.loads(json_files[0].read_text(encoding="utf-8"))
    primary = report.get("search_part", "")
    allowed_family = report.get("allowed_product_family", "")
    direct_count = int(report.get("product_links_found", 0) or 0)

    # The strict parser stores direct search-result products first. These are the
    # strongest Cars245 alternatives for the searched number. Do not carry over
    # the later same-family carousel/sibling links automatically.
    direct_items = list(report.get("alternatives", []))[:direct_count]
    explicit_items = [
        x for x in report.get("alternatives", [])[direct_count:]
        if not str(x.get("url", "")).strip()
    ]

    cleaned_alts = []
    seen_alts = set()
    for item in direct_items + explicit_items:
        brand = clean_brand(item.get("brand", ""))
        code = clean_code(item.get("part_number", ""))
        ptype = re.sub(r"\s+", " ", str(item.get("product_type", ""))).strip()
        url = str(item.get("url", "")).strip()
        if not valid_alt(brand, code):
            continue
        key = (brand, norm(code))
        if key in seen_alts:
            continue
        seen_alts.add(key)
        cleaned_alts.append({
            "brand": brand,
            "part_number": code,
            "product_type": ptype,
            "url": url,
            "source": "Cars245",
            "relation": "direct_alternative" if url else "cross_reference",
        })

    # Add clear Brand -> Code references found in Cars245 reference blocks.
    for item in extract_branded_refs(report.get("oem_refs", [])):
        key = (item["brand"], norm(item["part_number"]))
        if key in seen_alts:
            continue
        seen_alts.add(key)
        cleaned_alts.append(item)

    cleaned_fitments = []
    seen_fit = set()
    for item in report.get("fitments", []):
        make = re.sub(r"\s+", " ", str(item.get("vehicle_make", "")).upper()).strip()
        text = re.sub(r"\s+", " ", str(item.get("fitment_text", ""))).strip()
        if not make or not text:
            continue
        key = (make, text.upper())
        if key in seen_fit:
            continue
        seen_fit.add(key)
        cleaned_fitments.append({
            "vehicle_make": make,
            "year_from": str(item.get("year_from", "")),
            "year_to": str(item.get("year_to", "")),
            "fitment_text": text,
            "source_url": str(item.get("source_url", "")),
            "source": "Cars245",
        })

    oem_refs = clean_oem_refs(primary, report.get("oem_refs", []))
    final = {
        "search_part": primary,
        "allowed_product_family": allowed_family,
        "direct_product_links": direct_count,
        "alternatives_found": len(cleaned_alts),
        "oem_refs_found": len(oem_refs),
        "fitment_rows_found": len(cleaned_fitments),
        "oem_refs": oem_refs,
        "alternatives": cleaned_alts,
        "fitments": cleaned_fitments,
        "source": "Cars245",
        "sheet_safe": True,
    }

    slug = re.sub(r"[^A-Z0-9]+", "_", primary.upper()).strip("_").lower()
    pd.DataFrame(cleaned_alts).to_csv(output_path / f"cars245_{slug}_alternatives_final.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(cleaned_fitments).to_csv(output_path / f"cars245_{slug}_fitment_final.csv", index=False, encoding="utf-8-sig")
    (output_path / f"cars245_{slug}_final.json").write_text(
        json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return final


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", default="output")
    p.add_argument("--output-dir", default=None)
    args = p.parse_args()
    r = finalize(args.input_dir, args.output_dir)
    print(f"FINAL direct_product_links={r['direct_product_links']}")
    print(f"FINAL alternatives_found={r['alternatives_found']}")
    print(f"FINAL oem_refs_found={r['oem_refs_found']}")
    print(f"FINAL fitment_rows_found={r['fitment_rows_found']}")
    print("FINAL oem_refs=" + " | ".join(r["oem_refs"]))
    for x in r["alternatives"]:
        print(f"FINAL_ALT\t{x['brand']}\t{x['part_number']}\t{x['product_type']}\t{x['relation']}")


if __name__ == "__main__":
    main()
