#!/usr/bin/env python3
"""Post-parse safety guard for ELKADY AUTO Cars245 batches."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlparse

CATEGORY_FAMILIES = {
    "Brake Parts": {"brake-pad", "brake-disc"},
    "Brake Wear Sensor": {"brake-wear-sensor"},
    "Engine Parts": {"engine-mount", "transmission-mount", "belt", "timing-belt", "timing-chain", "belt-tensioner"},
    "Suspension/Chassis": {"shock-absorber", "control-arm", "wheel-bearing"},
    "Suspension/Steering": {"shock-absorber", "control-arm", "wheel-bearing"},
    "Filters": {"oil-filter", "air-filter", "cabin-filter", "fuel-filter"},
    "Sensors": {"sensor"},
    "Wipers": {"wiper-blade"},
    "CV Boot": {"cv-boot"},
    "Stabilizer Link": {"stabilizer-link"},
    "Cooling System": {"coolant-expansion-tank"},
    "Valves": {"change-over-valve"},
}

PART_CATEGORY = {
    "95834105100": "Suspension/Chassis",
    "95834105300": "Suspension/Chassis",
    "95834105400": "Suspension/Chassis",
    "95534703222": "Suspension/Steering",
    "95534703122": "Suspension/Steering",
    "95534306900": "Suspension/Chassis",
    "5QA199555C": "Engine Parts",
    "8K0698451A": "Brake Parts",
    "8R0698151B": "Brake Parts",
    "95B615301M": "Brake Parts",
    "4G0698451H": "Brake Parts",
    "95B615601G": "Brake Parts",
    "99735193809": "Brake Parts",
    "982698451B": "Brake Parts",
    "98735240101": "Brake Parts",
    "9Y0399153B": "Engine Parts",
    "95840715100": "Suspension/Chassis",
    "PAB19937110": "Engine Parts",
    "99735193810": "Brake Parts",
    "99735193804": "Brake Parts",
    "99735193811": "Brake Parts",
    "98135193904": "Brake Parts",
    "98735293901": "Brake Parts",
    "98735293903": "Brake Parts",
    "99160916500": "Brake Wear Sensor",
    "98160916300": "Brake Wear Sensor",
    "99157237100": "Filters",
    "982129620A": "Filters",
    "8R0698151AA": "Brake Parts",
    "8R0698151AB": "Brake Parts",
    "8R0698151C": "Brake Parts",
    "8R0698151D": "Brake Parts",
    "4H0698451A": "Brake Parts",
    "4H0698451C": "Brake Parts",
    "4H0698451D": "Brake Parts",
    "4H0615601K": "Brake Parts",
    "4G0615301Q": "Brake Parts",
    "4G0615301AF": "Brake Parts",
    "8R0698151E": "Brake Parts",
    "8R0698151G": "Brake Parts",
    "8R0698151H": "Brake Parts",
    "8R0698151J": "Brake Parts",
    "8R0698151K": "Brake Parts",
    "4H0698451K": "Brake Parts",
    "4H0698451L": "Brake Parts",
    "4H0698451M": "Brake Parts",
    "4H0615601H": "Brake Parts",
    "4H0615601Q": "Brake Parts",
    "4G0615301G": "Brake Parts",
    "4G0615301": "Brake Parts",
    "8W0615601E": "Brake Parts",
    "8W0615601K": "Brake Parts",
    "L80D615601": "Brake Parts",
    "PAB698451": "Brake Parts",
    "PAC698151": "Brake Parts",
    "9P1819631": "Filters",
    "982129620B": "Filters",
    "0PC115466": "Filters",

    # Remaining 34 ready identifiers
    "95B998001A": "Wipers",
    "971955427A": "Wipers",
    "8K0407151F": "Suspension/Chassis",
    "8K0407151G": "Suspension/Chassis",
    "8K0407152F": "Suspension/Chassis",
    "8K0407152G": "Suspension/Chassis",
    "8K0407283B": "CV Boot",
    "8K0407285E": "CV Boot",
    "99735193806": "Brake Parts",
    "4M0199372D": "Engine Parts",
    "4M0199372FG": "Engine Parts",
    "4M0199372FM": "Engine Parts",
    "4M0199372FE": "Engine Parts",
    "4M0199372GL": "Engine Parts",
    "4M0199372GM": "Engine Parts",
    "4M0199372HA": "Engine Parts",
    "9Y0399153": "Engine Parts",
    "PAB407151": "Suspension/Chassis",
    "4M0407151D": "Suspension/Chassis",
    "4M0407151F": "Suspension/Chassis",
    "4M0407151H": "Suspension/Chassis",
    "4M0411317": "Stabilizer Link",
    "4H0411317A": "Stabilizer Link",
    "4H0411317B": "Stabilizer Link",
    "4M0411317J": "Stabilizer Link",
    "4M0411317L": "Stabilizer Link",
    "4M0121403H": "Cooling System",
    "4M0121403D": "Cooling System",
    "4M0121403F": "Cooling System",
    "9P1411317A": "Stabilizer Link",
    "9P1411318A": "Stabilizer Link",
    "7PP906270B": "Valves",
    "9A210722500": "Filters",
    "PAB19937210": "Engine Parts",
}

SLUG_FAMILY_HINTS = {
    "warning-contact-brake-pad-wear": "brake-wear-sensor",
    "shock-absorber": "shock-absorber",
    "suspension-strut": "shock-absorber",
    "gas-spring": "gas-spring",
    "brake-pad-set": "brake-pad",
    "brake-pads": "brake-pad",
    "brake-disc": "brake-disc",
    "water-pump": "water-pump",
    "thermostat": "thermostat",
    "control-arm": "control-arm",
    "wheel-bearing": "wheel-bearing",
    "engine-mounting": "engine-mount",
    "transmission-mounting": "transmission-mount",
    "oil-filter": "oil-filter",
    "air-filter": "air-filter",
    "cabin-filter": "cabin-filter",
    "fuel-filter": "fuel-filter",
    "spark-plug": "spark-plug",
    "ignition-coil": "ignition-coil",
    "sensor": "sensor",
    "v-ribbed-belt": "belt",
    "timing-belt": "timing-belt",
    "timing-chain": "timing-chain",
    "belt-tensioner": "belt-tensioner",
    "wiper-blade": "wiper-blade",
    "windscreen-wiper": "wiper-blade",
    "wiper": "wiper-blade",
    "bellow-drive-shaft": "cv-boot",
    "cv-joint-bellow": "cv-boot",
    "drive-shaft-bellow": "cv-boot",
    "stabiliser-link": "stabilizer-link",
    "stabilizer-link": "stabilizer-link",
    "rod-strut-stabiliser": "stabilizer-link",
    "coolant-expansion-tank": "coolant-expansion-tank",
    "expansion-tank-coolant": "coolant-expansion-tank",
    "change-over-valve": "change-over-valve",
    "changeover-valve": "change-over-valve",
}

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
    "Wiper Blade": "wiper-blade",
    "Bellow, drive shaft": "cv-boot",
    "CV Joint Bellow": "cv-boot",
    "Rod/Strut, stabiliser": "stabilizer-link",
    "Stabilizer Link": "stabilizer-link",
    "Expansion Tank, coolant": "coolant-expansion-tank",
    "Coolant Expansion Tank": "coolant-expansion-tank",
    "Change-Over Valve": "change-over-valve",
}


def norm(v: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(v).upper())


def family_from_item(item: dict) -> str:
    ptype = str(item.get("product_type", "")).strip()
    if ptype in TYPE_FAMILY:
        return TYPE_FAMILY[ptype]
    url = str(item.get("url", "")).lower()
    slug = urlparse(url).path.rstrip("/").split("/")[-1]
    for token, fam in SLUG_FAMILY_HINTS.items():
        if token in slug:
            return fam
    return ""


def guard_file(path: Path) -> tuple[int, int, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    part = norm(data.get("search_part", ""))
    category = PART_CATEGORY.get(part)
    if not category:
        data["family_guard"] = {"status": "no_rule", "part": part}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0, 0, 0

    allowed = CATEGORY_FAMILIES[category]
    original_alts = list(data.get("alternatives", []))
    original_products = list(data.get("products", []))

    kept_alts, kept_products = [], []
    allowed_urls = set()
    rejected = []

    for item in original_products:
        fam = family_from_item(item)
        if fam in allowed:
            kept_products.append(item)
            if item.get("url"):
                allowed_urls.add(str(item["url"]).split("?")[0])
        else:
            rejected.append({"kind": "product", "family": fam, "url": item.get("url", ""), "brand": item.get("brand", ""), "part_number": item.get("part_number", "")})

    for item in original_alts:
        fam = family_from_item(item)
        url = str(item.get("url", "")).split("?")[0]
        if fam in allowed or (url and url in allowed_urls):
            kept_alts.append(item)
        else:
            rejected.append({"kind": "alternative", "family": fam, "url": item.get("url", ""), "brand": item.get("brand", ""), "part_number": item.get("part_number", "")})

    original_fitments = list(data.get("fitments", []))
    kept_fitments = []
    for row in original_fitments:
        url = str(row.get("source_url", "")).split("?")[0]
        if url and url in allowed_urls:
            kept_fitments.append(row)

    data["products"] = kept_products
    data["alternatives"] = kept_alts
    data["fitments"] = kept_fitments
    data["alternatives_found"] = len(kept_alts)
    data["fitment_rows_found"] = len(kept_fitments)

    surviving_families = sorted({family_from_item(x) for x in kept_products + kept_alts if family_from_item(x)})
    data["allowed_product_family"] = surviving_families[0] if len(surviving_families) == 1 else "category:" + category
    data["family_guard"] = {
        "status": "applied",
        "crm_category": category,
        "allowed_families": sorted(allowed),
        "products_before": len(original_products),
        "products_after": len(kept_products),
        "alternatives_before": len(original_alts),
        "alternatives_after": len(kept_alts),
        "fitments_before": len(original_fitments),
        "fitments_after": len(kept_fitments),
        "rejected_count": len(rejected),
        "rejected_sample": rejected[:25],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FAMILY_GUARD {part}: category={category} products {len(original_products)}->{len(kept_products)} alts {len(original_alts)}->{len(kept_alts)} fitments {len(original_fitments)}->{len(kept_fitments)}")
    return len(rejected), len(kept_alts), len(kept_fitments)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", default="output")
    args = p.parse_args()
    files = sorted(Path(args.input_dir).glob("*_strict.json"))
    if not files:
        raise SystemExit("No *_strict.json files found")
    total_rejected = 0
    for f in files:
        rejected, _, _ = guard_file(f)
        total_rejected += rejected
    print("family_guard_total_rejected=", total_rejected)


if __name__ == "__main__":
    main()
