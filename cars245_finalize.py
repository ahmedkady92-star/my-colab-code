#!/usr/bin/env python3
"""Final sanitizer for Cars245 strict-parser output.

Batch-safe, conservative Cars245-only enrichment. Every *_strict.json is
finalized independently. Uncertain/noisy values are dropped rather than written
as verified identifiers.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

PRODUCT_TYPE_WORDS = (
    "SHOCK ABSORBER", "SUSPENSION STRUT", "GAS SPRING", "BRAKE PAD SET",
    "DISC BRAKE", "BRAKE DISC", "WATER PUMP", "THERMOSTAT", "CONTROL ARM",
    "WHEEL BEARING", "ENGINE MOUNTING", "ENGINE MOUNT", "TRANSMISSION MOUNTING",
    "OIL FILTER", "AIR FILTER", "CABIN FILTER", "FUEL FILTER", "SPARK PLUG",
    "IGNITION COIL", "V-RIBBED BELT", "TIMING BELT SET", "TIMING CHAIN",
    "BELT TENSIONER",
)
BAD_WORDS = re.compile(
    r"(?:\bKW\b|\bHP\b|AWARDS|GUIDES|CARS245|ABOUT|BUDGET|YOUR|ASK|MID|UNKNOWN|\bOEM\b$)",
    re.I,
)
VEHICLE_OR_OE_BRANDS = {
    "AUDI", "VOLKSWAGEN", "VW", "SKODA", "SEAT", "PORSCHE", "BENTLEY",
    "BMW", "LAND ROVER", "JAGUAR", "AUDI / VOLKSWAGEN",
}
BRAND_NOISE = {
    "UNKNOWN", "SHOCK", "ABSORBER", "SUSPENSION", "STRUT", "ORIGINAL",
    "NUMBER", "REFERENCE", "REPLACEMENT", "OEM", "OE", "CONTACTS",
}

# Product-family terms that are reliable in Cars245 item URLs.
FAMILY_TOKENS = {
    "brake-pad": "brake-pad-set-disc-brake",
    "brake-disc": "brake-disc",
    "engine-mount": "engine-mount",
    "engine-mounting": "engine-mount",
    "shock-absorber": "shock-absorber",
    "suspension-strut": "suspension-strut",
    "gas-spring": "gas-spring",
    "water-pump": "water-pump",
    "thermostat": "thermostat",
    "wheel-bearing": "wheel-bearing",
}


def norm(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def clean_brand(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value).upper()).strip(" -_|,:;()")
    # Strip Cars245 product descriptors even when punctuation follows them,
    # e.g. "BOSCH BRAKE PAD SET, DISC BRAKE" -> "BOSCH".
    descriptor = re.compile(
        r"\s+(?:BRAKE PAD SET(?:,?\s*DISC BRAKE)?|MOUNTING,?\s*ENGINE|ENGINE MOUNTING|"
        r"SHOCK ABSORBER|SUSPENSION STRUT|GAS SPRING|BRAKE DISC|BRAKE KIT,?\s*DISC BRAKE)\s*$",
        re.I,
    )
    value = descriptor.sub("", value).strip(" -_|,:;()")
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


def url_slug(url: str) -> str:
    try:
        path = urlparse(url).path
        m = re.search(r"/item/([^/]+)/?", path, re.I)
        return (m.group(1) if m else "").lower()
    except Exception:
        return ""


def infer_family(direct_items: list[dict], allowed_family: str) -> str:
    af = str(allowed_family or "").lower().strip()
    for key, token in FAMILY_TOKENS.items():
        if key in af:
            return token
    counts = Counter()
    for item in direct_items:
        slug = url_slug(str(item.get("url", "")))
        for token in set(FAMILY_TOKENS.values()):
            if token in slug:
                counts[token] += 1
    return counts.most_common(1)[0][0] if counts else ""


def same_family(url: str, family: str) -> bool:
    if not family:
        return True
    slug = url_slug(url)
    if family == "engine-mount":
        return "engine-mount" in slug or "engine-mounting" in slug
    return family in slug


def brand_from_url(url: str, code: str, fallback: str) -> str:
    """Recover manufacturer from Cars245 URL when parser folded descriptors into brand.

    Typical URL: /item/bosch-0986494658-brake-pad-set-disc-brake/
    We locate the code token and use everything before it as the brand slug.
    """
    slug = url_slug(url)
    if not slug:
        return clean_brand(fallback)
    parts = slug.split("-")
    code_norm = norm(code).lower()
    # Try every boundary; part numbers can contain hyphens/slashes in display form.
    for i in range(1, min(len(parts), 5)):
        rest = "".join(parts[i:])
        if code_norm and rest.startswith(code_norm):
            return " ".join(parts[:i]).replace("_", " ").upper()
    return clean_brand(fallback)


def valid_alt(brand: str, code: str) -> bool:
    if not brand or not code or BAD_WORDS.search(brand) or BAD_WORDS.search(code):
        return False
    if brand in VEHICLE_OR_OE_BRANDS or brand in BRAND_NOISE:
        return False
    # Reject pseudo-brands that are clearly fragments of part numbers.
    if re.fullmatch(r"(?:P|P\s*\d{2}|8DB\s*355|8DD\s*355|VKBP|VKBD|V10|KT|WK)", brand, re.I):
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
    if len(n) < 9:
        return n
    return " ".join(x for x in (n[:3], n[3:6], n[6:9], n[9:]) if x)


def clean_oem_refs(primary: str, refs: list[str]) -> list[str]:
    p = norm(primary)
    vag = bool(re.fullmatch(r"[0-9A-Z]{3}\d{6}[0-9A-Z]{0,3}", p))
    base = p[:9] if vag else ""
    out, seen = [], {p}
    for raw in refs:
        raw = clean_code(raw)
        if vag:
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
            out.append({"brand": brand, "part_number": code, "product_type": "", "url": "",
                        "source": "Cars245", "relation": "cross_reference"})
    return out


def finalize_file(json_file: Path, output_path: Path) -> dict:
    report = json.loads(json_file.read_text(encoding="utf-8"))
    primary = report.get("search_part", "") or report.get("query_part_number", "")
    allowed_family = report.get("allowed_product_family", "")
    direct_count = int(report.get("product_links_found", 0) or 0)
    all_alts = list(report.get("alternatives", []))
    direct_items = all_alts[:direct_count]
    family = infer_family(direct_items, allowed_family)

    # Only direct Cars245 search results of the same product family are eligible
    # for automatic Verified status. This drops accessory/sibling products.
    direct_items = [x for x in direct_items if same_family(str(x.get("url", "")), family)]
    explicit_items = [x for x in all_alts[direct_count:] if not str(x.get("url", "")).strip()]

    cleaned_alts, seen_alts = [], set()
    for item in direct_items + explicit_items:
        code = clean_code(item.get("part_number", ""))
        url = str(item.get("url", "")).strip()
        brand = brand_from_url(url, code, item.get("brand", "")) if url else clean_brand(item.get("brand", ""))
        ptype = re.sub(r"\s+", " ", str(item.get("product_type", ""))).strip()
        if not valid_alt(brand, code):
            continue
        key = (brand, norm(code))
        if key in seen_alts:
            continue
        seen_alts.add(key)
        cleaned_alts.append({"brand": brand, "part_number": code, "product_type": ptype, "url": url,
                             "source": "Cars245", "relation": "direct_alternative" if url else "cross_reference"})

    for item in extract_branded_refs(report.get("oem_refs", [])):
        key = (item["brand"], norm(item["part_number"]))
        if key not in seen_alts:
            seen_alts.add(key)
            cleaned_alts.append(item)

    cleaned_fitments, seen_fit = [], set()
    for item in report.get("fitments", []):
        make = re.sub(r"\s+", " ", str(item.get("vehicle_make", "")).upper()).strip()
        text = re.sub(r"\s+", " ", str(item.get("fitment_text", ""))).strip()
        if not make or not text:
            continue
        key = (make, text.upper())
        if key in seen_fit:
            continue
        seen_fit.add(key)
        cleaned_fitments.append({"vehicle_make": make, "year_from": str(item.get("year_from", "")),
                                 "year_to": str(item.get("year_to", "")), "fitment_text": text,
                                 "source_url": str(item.get("source_url", "")), "source": "Cars245"})

    oem_refs = clean_oem_refs(primary, report.get("oem_refs", []))
    final = {
        "query_part_number": primary,
        "search_part": primary,
        "allowed_product_family": allowed_family,
        "inferred_product_family": family,
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
    (output_path / f"cars245_{slug}_final.json").write_text(json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
    return final


def finalize(input_dir: str, output_dir: str | None = None) -> list[dict]:
    input_path = Path(input_dir)
    output_path = Path(output_dir or input_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    json_files = sorted(input_path.glob("*_strict.json"))
    if not json_files:
        raise SystemExit("No *_strict.json found")
    results = []
    for jf in json_files:
        results.append(finalize_file(jf, output_path))
    return results


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", default="output")
    p.add_argument("--output-dir", default=None)
    args = p.parse_args()
    results = finalize(args.input_dir, args.output_dir)
    print(f"FINAL files={len(results)}")
    for r in results:
        print(f"FINAL part={r['search_part']}")
        print(f"FINAL inferred_product_family={r['inferred_product_family']}")
        print(f"FINAL alternatives_found={r['alternatives_found']}")
        print(f"FINAL oem_refs_found={r['oem_refs_found']}")
        print(f"FINAL fitment_rows_found={r['fitment_rows_found']}")
        print("FINAL oem_refs=" + " | ".join(r["oem_refs"]))
        for x in r["alternatives"]:
            print(f"FINAL_ALT\t{x['brand']}\t{x['part_number']}\t{x['product_type']}\t{x['relation']}")


if __name__ == "__main__":
    main()
