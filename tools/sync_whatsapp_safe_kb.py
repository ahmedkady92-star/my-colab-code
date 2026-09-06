#!/usr/bin/env python3
import argparse, hashlib, json, os, re
from pathlib import Path

import google.auth
from googleapiclient.discovery import build

SOURCE_ID = os.environ.get("ELKADY_SOURCE_SPREADSHEET_ID", "1A-8YoZkVIdelh2x3i7DmeFCERLeR1XREyEpK3Wrk6B0")
TARGET_ID = os.environ.get("ELKADY_SAFE_SPREADSHEET_ID", "1d3J25P1L6oBOMCb6O3_xdRXie-FV-qvRbWEBv53jgYs")
TAB = "41_AI_Product_Feed"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

CUSTOMER_AVAILABILITY = "السعر معتمد، والتوافر يحتاج تأكيدًا من فريق ELKADY AUTO PARTS."
HEADERS = [
    "AI_Feed_ID", "Product_ID", "Part_Number", "OEM_Number", "Brand", "Part_Name",
    "Description", "Condition", "Vehicle_Make", "Vehicle_Model", "Year_From", "Year_To",
    "Engine", "Customer_Price", "Currency", "Stock_Status", "Availability", "Warranty",
    "Return_Policy", "Verified_Status", "Last_Checked_At", "AI_Eligible", "Source_Record_ID", "Notes",
]
BLOCKED_TOKENS = [
    "supplier", "kano", "ksg", "cost", "profit", "margin", "github", "source_record",
    "supplier_cost", "target profit", "raw pre-discount", "internal calculated",
]


def service():
    creds, _ = google.auth.default(scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def read_values(svc, spreadsheet_id, rng):
    return svc.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=rng).execute().get("values", [])


def clean_text(v):
    return str(v or "").strip()


def safe_id(original):
    digest = hashlib.sha256(clean_text(original).encode("utf-8")).hexdigest()[:12].upper()
    return f"WAI-{digest}"


def safe_notes(row):
    src = clean_text(row.get("Notes"))
    segments = [x.strip() for x in src.split("|") if x.strip()]
    parts = []
    for label in ("السعر قبل الخصم", "السعر بعد الخصم", "الخصم"):
        prefix = label + ":"
        seg = next((x for x in segments if x.startswith(prefix)), "")
        if seg:
            parts.append(seg)
    if not any(x.startswith("السعر بعد الخصم:") for x in parts) and clean_text(row.get("Customer_Price")):
        price = clean_text(row.get("Customer_Price"))
        currency = clean_text(row.get("Currency")) or "EGP"
        parts.append(f"السعر المعتمد: {price} {currency}")
    parts.append(CUSTOMER_AVAILABILITY)
    status = clean_text(row.get("Verified_Status")).upper()
    eligible = clean_text(row.get("AI_Eligible")).upper()
    vehicle = clean_text(row.get("Vehicle_Model"))
    if vehicle:
        parts.append(f"توافقات السيارات المسجلة: {vehicle}")
    if "REVIEW" in status or eligible != "TRUE":
        parts.append("التوافق يحتاج مراجعة VIN/PR قبل التأكيد النهائي للعميل.")
    else:
        parts.append("اطلب VIN فقط عند الحاجة لتأكيد النسخة أو المحرك أو PR Code.")
    return " | ".join(parts)


def sanitize_row(headers, vals):
    vals = vals + [""] * (len(headers) - len(vals))
    row = dict(zip(headers, vals))
    out = {h: clean_text(row.get(h)) for h in HEADERS}
    sid = safe_id(out["AI_Feed_ID"] or out["Product_ID"] or out["Part_Number"] or out["OEM_Number"])
    out["AI_Feed_ID"] = sid
    out["Product_ID"] = sid
    out["Source_Record_ID"] = ""
    out["Availability"] = CUSTOMER_AVAILABILITY
    out["Stock_Status"] = "Availability Confirmation Required from ELKADY AUTO PARTS Team"
    out["Notes"] = safe_notes(row)
    for field in ("Description", "Notes"):
        txt = out[field]
        for token in BLOCKED_TOKENS:
            txt = re.sub(re.escape(token), "", txt, flags=re.I)
        out[field] = re.sub(r"\s{2,}", " ", txt).strip(" |")
    return [out[h] for h in HEADERS]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="automation_output/whatsapp_safe_sync_report.json")
    args = ap.parse_args()

    svc = service()
    src = read_values(svc, SOURCE_ID, f"'{TAB}'!A1:Y5000")
    if not src:
        raise RuntimeError("Source AI feed is empty")
    source_headers = src[0]
    missing = [h for h in HEADERS if h not in source_headers]
    if missing:
        raise RuntimeError(f"Source AI feed missing headers: {missing}")

    idx = {h: source_headers.index(h) for h in HEADERS}
    safe_rows = []
    invalid = 0
    for raw in src[1:]:
        padded = raw + [""] * (len(source_headers) - len(raw))
        ordered = [padded[idx[h]] for h in HEADERS]
        if not clean_text(ordered[0]).startswith("AI-"):
            invalid += 1
            continue
        safe_rows.append(sanitize_row(HEADERS, ordered))

    leakage = []
    for rnum, row in enumerate(safe_rows, start=2):
        joined = " | ".join(str(x) for x in row)
        for token in BLOCKED_TOKENS:
            if token.lower() in joined.lower():
                leakage.append({"row": rnum, "token": token})
    if leakage:
        raise RuntimeError(f"Unsafe data detected after sanitization: {leakage[:10]}")

    target = read_values(svc, TARGET_ID, f"'{TAB}'!A1:Y5000")
    target_existing_rows = max(0, len(target) - 1)

    if args.apply:
        body = {"valueInputOption": "RAW", "data": [
            {"range": f"'{TAB}'!A1:X{len(safe_rows)+1}", "values": [HEADERS] + safe_rows},
        ]}
        svc.spreadsheets().values().batchUpdate(spreadsheetId=TARGET_ID, body=body).execute()
        if target_existing_rows > len(safe_rows):
            svc.spreadsheets().values().clear(
                spreadsheetId=TARGET_ID,
                range=f"'{TAB}'!A{len(safe_rows)+2}:X{target_existing_rows+1}",
                body={},
            ).execute()

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    report = {
        "mode": "APPLY" if args.apply else "DRY_RUN",
        "source_rows": len(src) - 1,
        "safe_rows": len(safe_rows),
        "invalid_source_rows_skipped": invalid,
        "target_existing_rows": target_existing_rows,
        "leakage_detected": len(leakage),
        "internal_ids_replaced": True,
        "source_record_ids_removed": True,
        "notes_sanitized": True,
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
