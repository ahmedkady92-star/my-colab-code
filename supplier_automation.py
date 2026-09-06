#!/usr/bin/env python3
import argparse, json, math, subprocess, sys
from pathlib import Path

TIERS = [
    (0, 500, .85),
    (500, 1000, .65),
    (1000, 2000, .50),
    (2000, 5000, .40),
    (5000, 10000, .30),
    (10000, 20000, .20),
    (20000, None, .14),
]
DISCOUNT_RATE = .05
ROUNDING_STEP = 50
SUPPORTED_SUPPLIERS = {"KANO"}

def progressive_profit(cost):
    total = 0.0
    for lo, hi, rate in TIERS:
        if cost <= lo:
            continue
        upper = cost if hi is None else min(cost, hi)
        total += max(0.0, upper - lo) * rate
    return total

def round_up(value, step):
    return math.ceil(value / step) * step

def normalize(value):
    return "".join(ch for ch in str(value).upper() if ch.isalnum())

def require(obj, key):
    value = obj.get(key)
    if value in (None, ""):
        raise SystemExit(f"Missing required input: {key}")
    return value

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="automation/offer_input.json")
    p.add_argument("--output-dir", default="automation_output")
    args = p.parse_args()

    offer = json.loads(Path(args.input).read_text(encoding="utf-8"))
    supplier = str(require(offer, "supplier")).upper().strip()
    if supplier not in SUPPORTED_SUPPLIERS:
        raise SystemExit(f"Supplier pricing rules not configured: {supplier}")
    cost = float(require(offer, "supplier_cost"))
    oem = str(require(offer, "oem_number")).strip()
    catalog_brand = str(require(offer, "catalog_brand")).strip().lower()

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    cars = out / "cars245"
    cars.mkdir(exist_ok=True)

    subprocess.run([
        sys.executable, "cars245_multibrand.py", catalog_brand, oem,
        "--max-products", "20", "--delay", "0", "--output-dir", str(cars)
    ], check=True)
    subprocess.run([
        sys.executable, "cars245_fitment_enrich.py", "--input-dir", str(cars), "--max-urls", "8"
    ], check=True)

    reports = list(cars.glob("*_strict.json"))
    if len(reports) != 1:
        raise SystemExit(f"Expected one Cars245 report, got {len(reports)}")
    report = json.loads(reports[0].read_text(encoding="utf-8"))

    profit = progressive_profit(cost)
    price_after_discount = cost + profit
    raw_before_discount = price_after_discount / (1 - DISCOUNT_RATE)
    rounded_before_discount = round_up(raw_before_discount, ROUNDING_STEP)

    fit = report.get("fitment_enrichment", {})
    family = report.get("allowed_product_family", "")
    family_ok = bool(family)
    fitment_ok = bool(report.get("fitment_rows_found", 0)) and (
        fit.get("exact_oem_urls", 0) > 0 or fit.get("matched_search_part_urls", 0) >= 3
    )
    ai_eligible = bool(family_ok and fitment_ok)

    payload = {
        "mode": "READY_FOR_SHEET_IMPORT",
        "offer_input": offer,
        "normalized_oem": normalize(oem),
        "pricing": {
            "supplier_cost": cost,
            "target_profit": round(profit, 2),
            "price_after_discount": round(price_after_discount, 2),
            "raw_price_before_discount": round(raw_before_discount, 2),
            "rounded_price_before_discount": rounded_before_discount,
            "discount_rate": DISCOUNT_RATE,
            "currency": offer.get("currency", "EGP"),
        },
        "cars245": {
            "product_links_found": report.get("product_links_found", 0),
            "allowed_product_family": family,
            "alternatives_found": report.get("alternatives_found", 0),
            "oem_refs": report.get("oem_refs", []),
            "fitment_rows_found": report.get("fitment_rows_found", 0),
            "fitments": report.get("fitments", []),
            "alternatives": report.get("alternatives", []),
            "fitment_enrichment": fit,
        },
        "automation_gate": {
            "family_ok": family_ok,
            "fitment_ok": fitment_ok,
            "ai_eligible": ai_eligible,
            "verified_status": "Verified - VIN/PR Required" if ai_eligible else "Review Required",
            "availability_text": "السعر معتمد، والتوافر يحتاج تأكيدًا من فريق ELKADY AUTO PARTS",
        },
        "sheet_plan": [
            "36_Supplier_Offers upsert",
            "37_Supplier_Price_History append",
            "38_Product_Identifiers upsert exact/safe IDs",
            "39_Vehicle_Fitment upsert only verified conditional fitment",
            "41_AI_Product_Feed upsert customer price and AI gate",
            "43_Sync_Audit append"
        ]
    }
    (out / "import_payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
