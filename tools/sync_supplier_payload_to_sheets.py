#!/usr/bin/env python3
import argparse, hashlib, json, os, re
from datetime import datetime, timezone
from pathlib import Path

import google.auth
from googleapiclient.discovery import build

SPREADSHEET_ID = os.environ.get("ELKADY_SPREADSHEET_ID", "1A-8YoZkVIdelh2x3i7DmeFCERLeR1XREyEpK3Wrk6B0")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def norm(v):
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def now_utc():
    return datetime.now(timezone.utc)


def sheet_service():
    creds, _ = google.auth.default(scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def read_table(svc, tab, cols):
    values = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A1:{cols}5000",
    ).execute().get("values", [])
    if not values:
        raise RuntimeError(f"Empty sheet: {tab}")
    headers = values[0]
    rows = []
    for i, row in enumerate(values[1:], start=2):
        row = row + [""] * (len(headers) - len(row))
        rows.append((i, dict(zip(headers, row))))
    return headers, rows


def append_row(svc, tab, headers, data):
    row = [data.get(h, "") for h in headers]
    return svc.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A:{chr(64 + min(len(headers), 26))}",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


def update_row(svc, tab, row_no, headers, data):
    current = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A{row_no}:{chr(64 + min(len(headers), 26))}{row_no}",
    ).execute().get("values", [[]])[0]
    current = current + [""] * (len(headers) - len(current))
    pos = {h: i for i, h in enumerate(headers)}
    for k, v in data.items():
        if k in pos:
            current[pos[k]] = v
    svc.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A{row_no}:{chr(64 + min(len(headers), 26))}{row_no}",
        valueInputOption="RAW",
        body={"values": [current[:len(headers)]]},
    ).execute()


def stable_id(prefix, *parts):
    digest = hashlib.sha1("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:10].upper()
    return f"{prefix}-{digest}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", required=True)
    args = ap.parse_args()

    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    offer = payload["offer_input"]
    pricing = payload["pricing"]
    gate = payload["automation_gate"]
    cars = payload["cars245"]

    supplier = str(offer.get("supplier", "")).upper().strip()
    supplier_id = str(offer.get("supplier_id", "")).strip()
    brand = str(offer.get("manufacturer_brand", "")).strip()
    supplier_part = str(offer.get("supplier_part_number", "")).strip()
    oem = str(offer.get("oem_number", "")).strip()
    description = str(offer.get("part_description", "")).strip()
    cost = float(pricing["supplier_cost"])
    currency = str(pricing.get("currency", "EGP"))
    customer_price = float(pricing["price_after_discount"])
    before_discount = float(pricing["rounded_price_before_discount"])
    discount_rate = float(pricing.get("discount_rate", 0.05))
    n_part = norm(supplier_part)
    n_oem = norm(oem)
    verified_status = gate.get("verified_status", "Review Required")
    ai_eligible = bool(gate.get("ai_eligible"))
    review_reason = gate.get("review_reason", "")
    availability = gate.get("availability_text", "السعر معتمد، والتوافر يحتاج تأكيدًا من فريق ELKADY AUTO PARTS")
    now = now_utc()
    today = now.strftime("%Y-%m-%d")
    time_s = now.strftime("%H:%M:%S UTC")

    svc = sheet_service()

    h36, r36 = read_table(svc, "36_Supplier_Offers", "Z")
    exact_offer = None
    for row_no, r in r36:
        if (str(r.get("Supplier_Name", "")).upper().strip() == supplier
            and norm(r.get("Original_Part_Number")) == n_part
            and str(r.get("Brand", "")).upper().strip() == brand.upper()
            and num(r.get("Supplier_Cost")) == cost):
            exact_offer = (row_no, r)
            break

    if exact_offer:
        offer_row, existing_offer = exact_offer
        offer_id = existing_offer.get("Supplier_Offer_ID") or stable_id("OFF-AUTO", supplier, n_part, brand, cost)
        offer_created = 0
        offer_updated = 1
        update_row(svc, "36_Supplier_Offers", offer_row, h36, {
            "OEM_Number": oem,
            "Verified_Status": verified_status,
            "Last_Checked_At": today,
            "Review_Reason": review_reason,
            "Product_Match_Status": "Matched by exact supplier/part/brand/cost" if ai_eligible else "Review Required",
        })
    else:
        offer_id = stable_id("OFF-AUTO", supplier, n_part, brand, cost, today)
        offer_created = 1
        offer_updated = 0
        append_row(svc, "36_Supplier_Offers", h36, {
            "Supplier_Offer_ID": offer_id,
            "Supplier_ID": supplier_id,
            "Supplier_Name": supplier,
            "Product_ID": "",
            "Original_Part_Number": supplier_part,
            "Normalized_Part_Number": n_part,
            "OEM_Number": oem,
            "Brand": brand,
            "Part_Description": description,
            "Condition": "New",
            "Supplier_Cost": cost,
            "Currency": currency,
            "Availability": "Waiting Supplier Confirmation",
            "Offer_Date": today,
            "Extraction_Confidence": "High",
            "Extraction_Status": "Automated",
            "Product_Match_Status": "Review Required" if not ai_eligible else "Exact OEM Cars245 verified",
            "Internal_Only": "TRUE",
            "Verified_Status": verified_status,
            "Last_Checked_At": today,
            "Review_Reason": review_reason,
            "Notes": "Created by GitHub Actions supplier automation",
        })

    # Price history: append once per unique offer/cost/date.
    h37, r37 = read_table(svc, "37_Supplier_Price_History", "Z")
    history_exists = any(
        str(r.get("Supplier_Name", "")).upper().strip() == supplier
        and norm(r.get("Original_Part_Number")) == n_part
        and str(r.get("Brand", "")).upper().strip() == brand.upper()
        and num(r.get("Supplier_Cost")) == cost
        and str(r.get("Price_Date", "")) == today
        for _, r in r37
    )
    history_created = 0
    if not history_exists:
        history_created = 1
        append_row(svc, "37_Supplier_Price_History", h37, {
            "Price_History_ID": stable_id("PH-AUTO", offer_id, cost, today),
            "Supplier_ID": supplier_id,
            "Supplier_Name": supplier,
            "Product_ID": offer_id,
            "Original_Part_Number": supplier_part,
            "Normalized_Part_Number": n_part,
            "OEM_Number": oem,
            "Brand": brand,
            "Part_Description": description,
            "Supplier_Cost": cost,
            "Currency": currency,
            "Price_Date": today,
            "Price_Time": time_s,
            "Extraction_Confidence": "High",
            "Extraction_Status": "Automated",
            "Internal_Only": "TRUE",
            "Verified_Status": verified_status,
            "Last_Checked_At": today,
            "Review_Reason": review_reason,
            "Notes": "Direct GitHub Actions -> Google Sheets via WIF",
        })

    # Pricing upsert by offer ID. This preserves previous prices in 37.
    h13, r13 = read_table(svc, "13_Pricing", "K")
    pmatch = next(((rn, r) for rn, r in r13 if str(r.get("Product_ID", "")) == offer_id), None)
    p_data = {
        "Product_ID": offer_id,
        "Cost_Price": cost,
        "Selling_Price": customer_price,
        "Old_Price": before_discount,
        "Discount": round(before_discount - customer_price, 2),
        "Discount_Percentage": round(discount_rate * 100, 2),
        "Currency": currency,
        "Price_Valid_From": today,
        "Supplier": supplier,
        "Notes": "KANO progressive marginal pricing rule | automated by GitHub Actions",
    }
    if pmatch:
        update_row(svc, "13_Pricing", pmatch[0], h13, p_data)
        pricing_created = 0
        pricing_updated = 1
    else:
        append_row(svc, "13_Pricing", h13, p_data)
        pricing_created = 1
        pricing_updated = 0

    # Find exact verified OEM master in identifiers. Do not invent fitment identity when absent.
    h38, r38 = read_table(svc, "38_Product_Identifiers", "R")
    master_product_id = ""
    if n_oem:
        for _, r in r38:
            if norm(r.get("Normalized_Value")) == n_oem or norm(r.get("Original_Value")) == n_oem:
                if "OEM" in str(r.get("Identifier_Type", "")).upper() and str(r.get("Verified_Status", "")).upper().startswith("VERIFIED"):
                    master_product_id = str(r.get("Product_ID", "")).strip()
                    if master_product_id:
                        break

    # AI Feed upsert by Source_Record_ID (offer ID). If no trusted master, AI remains review-only.
    effective_ai = bool(ai_eligible and master_product_id)
    effective_status = "Verified - VIN/PR Required" if effective_ai else "Review Required"
    effective_reason = "" if effective_ai else (review_reason or "No existing verified OEM Product_ID in 38_Product_Identifiers")
    h41, r41 = read_table(svc, "41_AI_Product_Feed", "X")
    aimatch = next(((rn, r) for rn, r in r41 if str(r.get("Source_Record_ID", "")) == offer_id), None)
    oem_refs = cars.get("oem_refs", [])
    oem_text = "; ".join(dict.fromkeys([oem] + [str(x) for x in oem_refs if str(x).strip()]))
    notes = (
        f"السعر قبل الخصم: {before_discount:g} جنيه | السعر بعد الخصم: {customer_price:g} جنيه | "
        f"الخصم: {discount_rate*100:g}% | اعرض السعرين للعميل ولا تعرض سعر المورد أو الربح | "
        f"{availability} | اطلب VIN فقط عند الحاجة للتأكد من التوافق"
    )
    if effective_reason:
        notes += f" | Review: {effective_reason}"
    ai_data = {
        "AI_Feed_ID": (aimatch[1].get("AI_Feed_ID") if aimatch else stable_id("AI-AUTO", offer_id)),
        "Product_ID": offer_id,
        "Part_Number": supplier_part,
        "OEM_Number": oem_text,
        "Brand": brand,
        "Part_Name": description.split("|")[0].strip() if description else "",
        "Description": description,
        "Condition": "New",
        "Customer_Price": customer_price,
        "Currency": currency,
        "Stock_Status": "Availability Confirmation Required from ELKADY AUTO PARTS Team",
        "Availability": availability + ("." if not availability.endswith(".") else ""),
        "Warranty": "ضمان سنة ما لم يُذكر غير ذلك، ويؤكد فريق ELKADY AUTO PARTS التفاصيل النهائية",
        "Return_Policy": "الاسترجاع خلال 14 يومًا بشرط أن تكون القطعة غير مستخدمة ولم يتم تركيبها، وفق سياسة الاسترجاع",
        "Verified_Status": effective_status,
        "Last_Checked_At": today,
        "AI_Eligible": "TRUE" if effective_ai else "FALSE",
        "Source_Record_ID": offer_id,
        "Notes": notes,
    }
    if aimatch:
        update_row(svc, "41_AI_Product_Feed", aimatch[0], h41, ai_data)
        ai_created = 0
        ai_updated = 1
    else:
        append_row(svc, "41_AI_Product_Feed", h41, ai_data)
        ai_created = 1
        ai_updated = 0

    # Audit every direct sync.
    h43, _ = read_table(svc, "43_Sync_Audit", "V")
    batch = os.environ.get("GITHUB_RUN_ID", stable_id("LOCAL", offer_id, today))
    created = offer_created + history_created + pricing_created + ai_created
    updated = offer_updated + pricing_updated + ai_updated
    append_row(svc, "43_Sync_Audit", h43, {
        "Audit_ID": f"AUD-SUPPLIER-AUTO-{batch}",
        "Sync_Date": today,
        "Sync_Time": time_s,
        "Source_System": "GitHub Actions / Cars245",
        "Destination_System": "Google Sheets",
        "Entity_Type": "Supplier Offer / Pricing / AI Product Feed",
        "Operation": "Direct WIF Sync",
        "Source_Record_ID": offer_id,
        "Destination_Record_ID": "36,37,13,41",
        "Match_Key": f"{supplier}|{n_part}|{brand}|{cost}",
        "Sync_Status": "Success" if effective_ai else "Partial Success - Review Required",
        "Records_Read": 1,
        "Records_Created": created,
        "Records_Updated": updated,
        "Records_Skipped": 0,
        "Duplicates_Detected": 1 if exact_offer else 0,
        "Records_Failed": 0,
        "Error_Message": "",
        "Executed_By": "GitHub Actions / ELKADY CRM Automation",
        "Batch_ID": str(batch),
        "Validation_Status": "Passed" if effective_ai else "Passed with review gate",
        "Notes": f"Cars245 family={cars.get('allowed_product_family','')}; fitment_rows={cars.get('fitment_rows_found',0)}; master_product_id={master_product_id or 'NONE'}",
    })

    print(json.dumps({
        "offer_id": offer_id,
        "master_product_id": master_product_id,
        "effective_ai_eligible": effective_ai,
        "created": created,
        "updated": updated,
        "history_created": history_created,
        "status": "SUCCESS",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
