#!/usr/bin/env python3
import argparse, json, math, subprocess, sys
from pathlib import Path

from tools.cars245_result_gate import validate_report

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
# Kept only as a compatibility hook for the sheet scanner; pricing itself is global.
SUPPORTED_SUPPLIERS = set()
# Families allowed to pass automatically only after the strict OEM/family gate below.
AUTO_VERIFIED_FAMILIES = {"brake-pad", "shock-absorber"}


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
    p.add_argument("--input", required=True)
    p.add_argument("--output-dir", default="automation_output")
    args = p.parse_args()

    offer = json.loads(Path(args.input).read_text(encoding="utf-8"))
    supplier = str(require(offer, "supplier")).upper().strip()
    cost = float(require(offer, "supplier_cost"))
    oem = str(require(offer, "oem_number")).strip()
    description = str(offer.get("part_description", "") or "").strip()
    catalog_brand = str(require(offer, "catalog_brand")).strip().lower()
    currency = str(offer.get("currency", "EGP") or "EGP").upper().strip()
    if currency != "EGP":
        raise SystemExit(f"Automatic customer pricing currently requires EGP supplier cost: {currency}")

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

    # Strict post-parse validation. Search-result volume is never enough by itself:
    # the exact OEM must be evidenced on a product page and its family must match
    # the supplier description (e.g. shock absorber must not become an A/C part).
    validation = validate_report(report, oem, description)
    family = validation.get("validated_family", "")
    expected_family = validation.get("expected_family", "")
    exact_oem_pages = int(validation.get("exact_oem_pages", 0))
    family_match = bool(validation.get("family_match"))
    safe_fitments = list(validation.get("safe_fitments", []))
    exact_urls = set(validation.get("exact_oem_urls", []))

    # Only alternatives whose own Cars245 page carries exact searched-OEM evidence
    # are allowed downstream. This blocks unrelated cross-reference contamination.
    safe_alternatives = []
    seen_alt = set()
    for alt in report.get("alternatives", []):
        url = str(alt.get("url", "")).strip()
        if not url or url not in exact_urls:
            continue
        key = (str(alt.get("brand", "")).upper(), normalize(alt.get("part_number", "")))
        if key in seen_alt:
            continue
        seen_alt.add(key)
        safe_alternatives.append(alt)

    profit = progressive_profit(cost)
    price_after_discount = cost + profit
    raw_before_discount = price_after_discount / (1 - DISCOUNT_RATE)
    rounded_before_discount = round_up(raw_before_discount, ROUNDING_STEP)

    family_supported = family in AUTO_VERIFIED_FAMILIES
    exact_oem_evidence = exact_oem_pages > 0
    safe_fitment_evidence = len(safe_fitments) > 0
    fitment_ok = bool(expected_family and family_match and family_supported and exact_oem_evidence and safe_fitment_evidence)
    ai_eligible = fitment_ok

    if not expected_family:
        review_reason = "Part description family not resolved; manual review required"
    elif not exact_oem_evidence:
        review_reason = "Exact searched OEM not evidenced on a Cars245 product page"
    elif not family:
        review_reason = "Cars245 exact-OEM product family not resolved"
    elif not family_match:
        review_reason = f"Cars245 family mismatch: expected {expected_family}, got {family}"
    elif not family_supported:
        review_reason = f"Family {family} has no auto-verification policy yet"
    elif not safe_fitment_evidence:
        review_reason = "Exact-OEM page found but no fitment rows from that exact page"
    else:
        review_reason = ""

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
            "currency": currency,
            "pricing_rule": "ELKADY progressive marginal pricing",
            "supplier": supplier,
        },
        "cars245": {
            "product_links_found": report.get("product_links_found", 0),
            "allowed_product_family": family,
            "raw_dominant_product_family": report.get("allowed_product_family", ""),
            "alternatives_found": len(safe_alternatives),
            # Do not propagate broad scraped OEM lists. The exact searched OEM is the
            # only identifier trusted automatically; extra aliases stay manual-review.
            "oem_refs": [oem],
            "fitment_rows_found": len(safe_fitments),
            "fitments": safe_fitments,
            "alternatives": safe_alternatives,
            "fitment_enrichment": report.get("fitment_enrichment", {}),
            "strict_validation": validation,
        },
        "automation_gate": {
            "expected_family": expected_family,
            "validated_family": family,
            "family_match": family_match,
            "family_supported": family_supported,
            "exact_oem_evidence": exact_oem_evidence,
            "exact_oem_pages": exact_oem_pages,
            "safe_fitment_evidence": safe_fitment_evidence,
            "fitment_ok": fitment_ok,
            "ai_eligible": ai_eligible,
            "verified_status": "Verified - VIN/PR Required" if ai_eligible else "Review Required",
            "review_reason": review_reason,
            "availability_text": "السعر معتمد، والتوافر يحتاج تأكيدًا من فريق ELKADY AUTO PARTS",
        },
        "sheet_plan": [
            "36_Supplier_Offers upsert",
            "37_Supplier_Price_History append",
            "38_Product_Identifiers upsert exact/safe IDs",
            "39_Vehicle_Fitment upsert only verified conditional fitment",
            "13_Pricing upsert",
            "41_AI_Product_Feed upsert customer price and AI gate",
            "43_Sync_Audit append"
        ]
    }
    (out / "import_payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
