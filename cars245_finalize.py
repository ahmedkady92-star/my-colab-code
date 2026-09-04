#!/usr/bin/env python3
"""Final sanitizer for Cars245 strict-parser output.

Takes the strict JSON/CSV files and produces Sheet-safe Cars245-only data:
- clean Brand -> Part Number records,
- conservative OEM references,
- unique fitment rows.

The sanitizer is deliberately conservative: uncertain values are dropped rather
than written to the CRM as verified identifiers.
"""
from __future__ import annotations

import argparse
import glob
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
    r"(?:\bKW\b|\bHP\b|AWARDS|GUIDES|CARS245|ABOUT|BUDGET|YOUR|ASK|MID|\bOEM\b$)",
    re.I,
)


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
    # Numeric manufacturer codes are often displayed as grouped chunks.
    if re.fullmatch(r"(?:\d{2,6}\s+){1,3}\d{2,6}", value):
        value = value.replace(" ", "")
    return value


def valid_alt(brand: str, code: str) -> bool:
    if not brand or not code or BAD_WORDS.search(brand) or BAD_WORDS.search(code):
        return False
    compact = norm(code)
    if len(compact) < 4 or len(compact) > 24 or not re.search(r"\d", compact):
        return False
    if re.search(r"\b(?:19|20)\d{2}[-/]?(?:19|20)\d{2}\b", code):
        return False
    if re.fullmatch(r"\d{2,3}(?:KW|HP).*", compact):
        return False
    return True


def clean_oem_refs(primary: str, refs: list[str]) -> list[str]:
    """Keep only high-confidence OE references.

    For VAG-style numbers, require the same 9-character base as the searched
    number. This keeps revisions/supersessions such as 4F0413031AA/AB/AQ while
    rejecting page text such as '05 SACHS 312638'.

    For other formats, use a conservative structural filter and reject values
    containing obvious brand/description words.
    """
    p = norm(primary)
    vag = bool(re.fullmatch(r"[0-9A-Z]{3}\d{6}[0-9A-Z]{0,3}", p))
    base = p[:9] if vag else ""
    out, seen = [], {p}

    for raw in refs:
        raw = clean_code(raw)
        n = norm(raw)
        if not n or n in seen:
            continue
        if BAD_WORDS.search(raw):
            continue
        if vag:
            if not n.startswith(base):
                continue
            if not re.fullmatch(re.escape(base) + r"[0-9A-Z]{0,3}", n):
                continue
        else:
            if len(n) < 6 or len(n) > 18 or not re.search(r"\d", n):
                continue
            # Reject phrases that clearly contain manufacturer names/text.
            if len(raw.split()) > 4:
                continue
        seen.add(n)
        out.append(raw)
    return out


def finalize(input_dir: str, output_dir: str | None = None) -> dict:
    input_path = Path(input_dir)
    output_path = Path(output_dir or input_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    json_files = sorted(input_path.glob("*_strict.json"))
    if not json_files:
        raise SystemExit("No *_strict.json found")
    src = json_files[0]
    report = json.loads(src.read_text(encoding="utf-8"))
    primary = report.get("search_part", "")
    allowed_family = report.get("allowed_product_family", "")

    cleaned_alts = []
    seen_alts = set()
    for item in report.get("alternatives", []):
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
        })

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
    print(f"FINAL alternatives_found={r['alternatives_found']}")
    print(f"FINAL oem_refs_found={r['oem_refs_found']}")
    print(f"FINAL fitment_rows_found={r['fitment_rows_found']}")
    print("FINAL oem_refs=" + " | ".join(r["oem_refs"]))
    for x in r["alternatives"]:
        print(f"FINAL_ALT\t{x['brand']}\t{x['part_number']}\t{x['product_type']}")


if __name__ == "__main__":
    main()
