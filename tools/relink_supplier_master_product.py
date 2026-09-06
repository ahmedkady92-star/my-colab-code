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


def svc():
    creds, _ = google.auth.default(scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def read_table(s, tab, end_col):
    vals = s.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'!A1:{end_col}5000"
    ).execute().get("values", [])
    if not vals:
        raise RuntimeError(f"Empty sheet: {tab}")
    headers = vals[0]
    rows = []
    for rn, row in enumerate(vals[1:], 2):
        row = row + [""] * (len(headers) - len(row))
        rows.append((rn, dict(zip(headers, row))))
    return headers, rows


def col_letter(n):
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def update_cell(s, tab, row_no, headers, field, value):
    if field not in headers:
        return False
    col = col_letter(headers.index(field) + 1)
    s.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!{col}{row_no}",
        valueInputOption="RAW",
        body={"values": [[value]]},
    ).execute()
    return True


def append_row(s, tab, headers, data):
    last = col_letter(len(headers))
    row = [data.get(h, "") for h in headers]
    s.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A:{last}",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", required=True)
    args = ap.parse_args()
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    offer = payload.get("offer_input", {})
    pricing = payload.get("pricing", {})
    cars = payload.get("cars245", {})
    oem = str(offer.get("oem_number", "")).strip()
    n_oem = norm(oem)
    if not n_oem:
        print(json.dumps({"status":"SKIPPED","reason":"missing OEM"}))
        return

    s = svc()
    h38, r38 = read_table(s, "38_Product_Identifiers", "R")
    master_id = ""
    for _, r in r38:
        if n_oem in {norm(r.get("Original_Value")), norm(r.get("Normalized_Value"))}:
            if "OEM" in str(r.get("Identifier_Type", "")).upper() and str(r.get("Verified_Status", "")).upper().startswith("VERIFIED"):
                master_id = str(r.get("Product_ID", "")).strip()
                if master_id:
                    break
    if not master_id:
        print(json.dumps({"status":"SKIPPED","reason":"no verified OEM master"}))
        return

    supplier = str(offer.get("supplier", "")).upper().strip()
    part = str(offer.get("supplier_part_number", "")).strip()
    n_part = norm(part)
    brand = str(offer.get("manufacturer_brand", "")).strip()
    cost = float(pricing.get("supplier_cost", offer.get("supplier_cost", 0)) or 0)
    updated = 0
    source_offer_ids = set()

    h36, r36 = read_table(s, "36_Supplier_Offers", "Z")
    for rn, r in r36:
        if str(r.get("Supplier_Name", "")).upper().strip() != supplier:
            continue
        if norm(r.get("Original_Part_Number")) not in {n_part, n_oem} and norm(r.get("OEM_Number")) != n_oem:
            continue
        if brand and str(r.get("Brand", "")).upper().strip() != brand.upper():
            continue
        try:
            row_cost = float(str(r.get("Supplier_Cost", "")).replace(",", ""))
        except Exception:
            row_cost = None
        if cost and row_cost is not None and row_cost != cost:
            continue
        oid = str(r.get("Supplier_Offer_ID", "")).strip()
        if oid:
            source_offer_ids.add(oid)
        if str(r.get("Product_ID", "")) != master_id:
            updated += int(update_cell(s, "36_Supplier_Offers", rn, h36, "Product_ID", master_id))

    for tab, end_col in (("37_Supplier_Price_History", "V"), ("13_Pricing", "K")):
        headers, rows = read_table(s, tab, end_col)
        for rn, r in rows:
            current = str(r.get("Product_ID", "")).strip()
            if current in source_offer_ids and current != master_id:
                updated += int(update_cell(s, tab, rn, headers, "Product_ID", master_id))

    h41, r41 = read_table(s, "41_AI_Product_Feed", "X")
    for rn, r in r41:
        if str(r.get("Source_Record_ID", "")).strip() in source_offer_ids:
            if str(r.get("Product_ID", "")).strip() != master_id:
                updated += int(update_cell(s, "41_AI_Product_Feed", rn, h41, "Product_ID", master_id))

    now = datetime.now(timezone.utc)
    run_id = os.environ.get("GITHUB_RUN_ID", "LOCAL")
    h43, r43 = read_table(s, "43_Sync_Audit", "V")
    audit_id = f"AUD-MASTER-LINK-{run_id}-{hashlib.sha1(n_oem.encode()).hexdigest()[:8].upper()}"
    if not any(str(r.get("Audit_ID", "")) == audit_id for _, r in r43):
        append_row(s, "43_Sync_Audit", h43, {
            "Audit_ID": audit_id,
            "Sync_Date": now.strftime("%Y-%m-%d"),
            "Sync_Time": now.strftime("%H:%M:%S UTC"),
            "Source_System": "GitHub Actions / Cars245",
            "Destination_System": "Google Sheets",
            "Entity_Type": "Identifiers / Fitment / Supplier / Pricing / AI Link",
            "Operation": "Master Product_ID Relink",
            "Source_Record_ID": ";".join(sorted(source_offer_ids)) or n_oem,
            "Destination_Record_ID": master_id,
            "Match_Key": n_oem,
            "Sync_Status": "Success",
            "Records_Read": 1,
            "Records_Created": 0,
            "Records_Updated": updated,
            "Records_Skipped": 0,
            "Duplicates_Detected": 0,
            "Records_Failed": 0,
            "Error_Message": "",
            "Executed_By": "GitHub Actions / ELKADY CRM Automation",
            "Batch_ID": str(run_id),
            "Validation_Status": "Passed",
            "Notes": f"Unified Product_ID={master_id}; Cars245 family={cars.get('allowed_product_family','')}; fitment_rows={cars.get('fitment_rows_found',0)}",
        })

    print(json.dumps({"status":"SUCCESS","master_product_id":master_id,"records_updated":updated}, ensure_ascii=False))

if __name__ == "__main__":
    main()
