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


def stable_id(prefix, *parts):
    digest = hashlib.sha1("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:10].upper()
    return f"{prefix}-{digest}"


def merge_semicolon_values(*values):
    out, seen = [], set()
    for value in values:
        if isinstance(value, (list, tuple)):
            items = value
        else:
            items = str(value or "").split(";")
        for item in items:
            text = str(item).strip()
            key = norm(text)
            if text and key and key not in seen:
                seen.add(key)
                out.append(text)
    return "; ".join(out)


def service():
    creds, _ = google.auth.default(scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def read_table(svc, tab, end_col):
    values = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A1:{end_col}5000",
    ).execute().get("values", [])
    if not values:
        raise RuntimeError(f"Empty sheet: {tab}")
    headers = values[0]
    rows = []
    for i, row in enumerate(values[1:], start=2):
        row = row + [""] * (len(headers) - len(row))
        rows.append((i, dict(zip(headers, row))))
    return headers, rows


def col_letter(n):
    result = ""
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def append_row(svc, tab, headers, data):
    last = col_letter(len(headers))
    row = [data.get(h, "") for h in headers]
    svc.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A:{last}",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


def update_row(svc, tab, row_no, headers, data):
    last = col_letter(len(headers))
    current = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A{row_no}:{last}{row_no}",
    ).execute().get("values", [[]])[0]
    current = current + [""] * (len(headers) - len(current))
    pos = {h: i for i, h in enumerate(headers)}
    for k, v in data.items():
        if k in pos:
            current[pos[k]] = v
    svc.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A{row_no}:{last}{row_no}",
        valueInputOption="RAW",
        body={"values": [current[:len(headers)]]},
    ).execute()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--payload", required=True)
    args = parser.parse_args()

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
    n_part, n_oem = norm(supplier_part), norm(oem)
    base_verified_status = gate.get("verified_status", "Review Required")
    base_ai_eligible = bool(gate.get("ai_eligible"))
    review_reason = gate.get("review_reason", "")
    availability = gate.get("availability_text", "السعر معتمد، والتوافر يحتاج تأكيدًا من فريق ELKADY AUTO PARTS")
    now = datetime.now(timezone.utc)
    today, time_s = now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S UTC")

    svc = service()

    # 36 Supplier Offers: exact match first; never erase historical OEM aliases.
    h36, r36 = read_table(svc, "36_Supplier_Offers", "Z")
    exact_offer = next((
        (rn, r) for rn, r in r36
        if str(r.get("Supplier_Name", "")).upper().strip() == supplier
        and norm(r.get("Original_Part_Number")) == n_part
        and str(r.get("Brand", "")).upper().strip() == brand.upper()
        and num(r.get("Supplier_Cost")) == cost
    ), None)

    if exact_offer:
        offer_row, existing_offer = exact_offer
        offer_id = existing_offer.get("Supplier_Offer_ID") or stable_id("OFF-AUTO", supplier, n_part, brand, cost)
        merged_oems = merge_semicolon_values(existing_offer.get("OEM_Number", ""), oem, cars.get("oem_refs", []))
        update_row(svc, "36_Supplier_Offers", offer_row, h36, {
            "OEM_Number": merged_oems,
            "Verified_Status": base_verified_status,
            "Last_Checked_At": today,
            "Review_Reason": review_reason,
            "Product_Match_Status": "Matched by exact supplier/part/brand/cost" if base_ai_eligible else "Review Required",
        })
        offer_created, offer_updated = 0, 1
    else:
        offer_id = stable_id("OFF-AUTO", supplier, n_part, brand, cost, today)
        append_row(svc, "36_Supplier_Offers", h36, {
            "Supplier_Offer_ID": offer_id,
            "Supplier_ID": supplier_id,
            "Supplier_Name": supplier,
            "Product_ID": "",
            "Original_Part_Number": supplier_part,
            "Normalized_Part_Number": n_part,
            "OEM_Number": merge_semicolon_values(oem, cars.get("oem_refs", [])),
            "Brand": brand,
            "Part_Description": description,
            "Condition": "New",
            "Supplier_Cost": cost,
            "Currency": currency,
            "Availability": "Waiting Supplier Confirmation",
            "Offer_Date": today,
            "Extraction_Confidence": "High",
            "Extraction_Status": "Automated",
            "Product_Match_Status": "Exact OEM Cars245 verified" if base_ai_eligible else "Review Required",
            "Internal_Only": "TRUE",
            "Verified_Status": base_verified_status,
            "Last_Checked_At": today,
            "Review_Reason": review_reason,
            "Notes": "Created by GitHub Actions supplier automation",
        })
        offer_created, offer_updated = 1, 0

    # 37 historical supplier prices: append once per supplier/part/brand/cost/date.
    h37, r37 = read_table(svc, "37_Supplier_Price_History", "V")
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
            "OEM_Number": merge_semicolon_values(oem, cars.get("oem_refs", [])),
            "Brand": brand,
            "Part_Description": description,
            "Supplier_Cost": cost,
            "Currency": currency,
            "Price_Date": today,
            "Price_Time": time_s,
            "Extraction_Confidence": "High",
            "Extraction_Status": "Automated",
            "Internal_Only": "TRUE",
            "Verified_Status": base_verified_status,
            "Last_Checked_At": today,
            "Review_Reason": review_reason,
            "Notes": "Direct GitHub Actions -> Google Sheets via WIF",
        })

    # 13 Pricing: current customer price. History remains in 37.
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
        pricing_created, pricing_updated = 0, 1
    else:
        append_row(svc, "13_Pricing", h13, p_data)
        pricing_created, pricing_updated = 1, 0

    # 38: require an existing verified exact OEM master. Never invent Product_ID automatically.
    _, r38 = read_table(svc, "38_Product_Identifiers", "R")
    master_product_id = ""
    for _, r in r38:
        if n_oem and (norm(r.get("Normalized_Value")) == n_oem or norm(r.get("Original_Value")) == n_oem):
            if "OEM" in str(r.get("Identifier_Type", "")).upper() and str(r.get("Verified_Status", "")).upper().startswith("VERIFIED"):
                master_product_id = str(r.get("Product_ID", "")).strip()
                if master_product_id:
                    break

    effective_ai = bool(base_ai_eligible and master_product_id)
    effective_status = "Verified - VIN/PR Required" if effective_ai else "Review Required"
    effective_reason = "" if effective_ai else (review_reason or "No existing verified OEM Product_ID in 38_Product_Identifiers")

    # 41 AI feed: preserve existing fitment/model fields and historical OEM aliases on update.
    h41, r41 = read_table(svc, "41_AI_Product_Feed", "X")
    aimatch = next(((rn, r) for rn, r in r41 if str(r.get("Source_Record_ID", "")) == offer_id), None)
    existing_ai = aimatch[1] if aimatch else {}
    merged_ai_oems = merge_semicolon_values(existing_ai.get("OEM_Number", ""), oem, cars.get("oem_refs", []))
    notes = (
        f"السعر قبل الخصم: {before_discount:g} جنيه | السعر بعد الخصم: {customer_price:g} جنيه | "
        f"الخصم: {discount_rate*100:g}% | اعرض السعرين للعميل ولا تعرض سعر المورد أو الربح | "
        f"{availability} | اطلب VIN فقط عند الحاجة للتأكد من التوافق"
    )
    if effective_reason:
        notes += f" | Review: {effective_reason}"
    ai_data = {
        "AI_Feed_ID": existing_ai.get("AI_Feed_ID") or stable_id("AI-AUTO", offer_id),
        "Product_ID": offer_id,
        "Part_Number": supplier_part,
        "OEM_Number": merged_ai_oems,
        "Brand": brand,
        "Part_Name": existing_ai.get("Part_Name") or (description.split("|")[0].strip() if description else ""),
        "Description": existing_ai.get("Description") or description,
        "Condition": existing_ai.get("Condition") or "New",
        "Customer_Price": customer_price,
        "Currency": currency,
        "Stock_Status": "Availability Confirmation Required from ELKADY AUTO PARTS Team",
        "Availability": availability + ("." if not availability.endswith(".") else ""),
        "Warranty": existing_ai.get("Warranty") or "ضمان سنة ما لم يُذكر غير ذلك، ويؤكد فريق ELKADY AUTO PARTS التفاصيل النهائية",
        "Return_Policy": existing_ai.get("Return_Policy") or "الاسترجاع خلال 14 يومًا بشرط أن تكون القطعة غير مستخدمة ولم يتم تركيبها، وفق سياسة الاسترجاع",
        "Verified_Status": effective_status,
        "Last_Checked_At": today,
        "AI_Eligible": "TRUE" if effective_ai else "FALSE",
        "Source_Record_ID": offer_id,
        "Notes": notes,
    }
    if aimatch:
        update_row(svc, "41_AI_Product_Feed", aimatch[0], h41, ai_data)
        ai_created, ai_updated = 0, 1
    else:
        append_row(svc, "41_AI_Product_Feed", h41, ai_data)
        ai_created, ai_updated = 1, 0

    # 43 audit.
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
