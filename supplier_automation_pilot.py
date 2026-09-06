#!/usr/bin/env python3
import json, math, subprocess, sys
from pathlib import Path

TEST_OFFER = {
    "supplier": "KANO",
    "supplier_id": "SUP-000002",
    "manufacturer_brand": "ICER",
    "supplier_part_number": "22-0979-0",
    "oem_number": "8R0 698 151 B",
    "part_description": "تيل فرامل أمامي | Porsche Macan 2020",
    "supplier_cost": 2100.0,
    "currency": "EGP",
    "catalog_brand": "audi",
}

# Snapshot of active KANO progressive pricing rules from 44_KANO_Pricing_Rules.
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

def main():
    out = Path("pilot_output")
    out.mkdir(exist_ok=True)
    strict = out / "cars245"
    strict.mkdir(exist_ok=True)

    subprocess.run([
        sys.executable, "cars245_multibrand.py", TEST_OFFER["catalog_brand"],
        TEST_OFFER["oem_number"], "--max-products", "20", "--delay", "0",
        "--output-dir", str(strict)
    ], check=True)

    subprocess.run([
        sys.executable, "cars245_fitment_enrich.py", "--input-dir", str(strict), "--max-urls", "8"
    ], check=True)

    reports = list(strict.glob("*_strict.json"))
    if len(reports) != 1:
        raise SystemExit(f"Expected one strict report, got {len(reports)}")
    report = json.loads(reports[0].read_text(encoding="utf-8"))

    cost = TEST_OFFER["supplier_cost"]
    profit = progressive_profit(cost)
    price_after_discount = cost + profit
    raw_before_discount = price_after_discount / (1 - DISCOUNT_RATE)
    rounded_before_discount = round_up(raw_before_discount, ROUNDING_STEP)

    fit = report.get("fitment_enrichment", {})
    fitment_ok = bool(report.get("fitment_rows_found", 0)) and (
        fit.get("exact_oem_urls", 0) > 0 or fit.get("matched_search_part_urls", 0) >= 3
    )
    family_ok = report.get("allowed_product_family") == "brake-pad"
    ai_eligible = bool(fitment_ok and family_ok)

    payload = {
        "mode": "DRY_RUN_NO_SHEET_WRITE",
        "offer_input": TEST_OFFER,
        "normalized_oem": "".join(ch for ch in TEST_OFFER["oem_number"].upper() if ch.isalnum()),
        "pricing": {
            "supplier_cost": cost,
            "target_profit": round(profit, 2),
            "price_after_discount": round(price_after_discount, 2),
            "raw_price_before_discount": round(raw_before_discount, 2),
            "rounded_price_before_discount": rounded_before_discount,
            "discount_rate": DISCOUNT_RATE,
            "currency": "EGP",
        },
        "cars245": {
            "product_links_found": report.get("product_links_found", 0),
            "allowed_product_family": report.get("allowed_product_family", ""),
            "alternatives_found": report.get("alternatives_found", 0),
            "fitment_rows_found": report.get("fitment_rows_found", 0),
            "fitment_enrichment": fit,
        },
        "automation_gate": {
            "family_ok": family_ok,
            "fitment_ok": fitment_ok,
            "ai_eligible": ai_eligible,
            "verified_status": "Verified - VIN/PR Required" if ai_eligible else "Review Required",
            "availability_text": "السعر معتمد، والتوافر يحتاج تأكيدًا من فريق ELKADY AUTO PARTS",
        },
        "draft_targets": {
            "36_Supplier_Offers": "UPSERT offer + pricing formulas",
            "37_Supplier_Price_History": "APPEND immutable supplier price history",
            "38_Product_Identifiers": "UPSERT exact OEM + safe cross references only",
            "39_Vehicle_Fitment": "UPSERT verified conditional fitment only",
            "41_AI_Product_Feed": "UPSERT customer price + fitment gate + AI eligibility",
            "43_Sync_Audit": "APPEND run counts/status",
        },
    }
    (out / "pilot_result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    assert round(price_after_discount, 2) == 3390.00, price_after_discount
    assert rounded_before_discount == 3600, rounded_before_discount
    if not family_ok:
        raise SystemExit("Pilot failed: product family is not brake-pad")
    if not fitment_ok:
        raise SystemExit("Pilot failed: safe fitment evidence gate not satisfied")

if __name__ == "__main__":
    main()
