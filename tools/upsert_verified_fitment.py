#!/usr/bin/env python3
import argparse, hashlib, json, os, re
from datetime import datetime, timezone
from pathlib import Path

import google.auth
from googleapiclient.discovery import build

SPREADSHEET_ID = os.environ.get("ELKADY_SPREADSHEET_ID", "1A-8YoZkVIdelh2x3i7DmeFCERLeR1XREyEpK3Wrk6B0")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
FUEL = r"Petrol/Compressed Natural Gas \(CNG\)|Petrol/Ethanol|Petrol/Electric|Diesel/Electric|Petrol|Diesel|CNG|Electric"


def norm(v):
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def stable_id(prefix, *parts):
    h = hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12].upper()
    return f"{prefix}-{h}"


def svc():
    creds, _ = google.auth.default(scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def read_table(s, tab, end_col):
    vals = s.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'!A1:{end_col}5000"
    ).execute().get("values", [])
    if not vals:
        raise RuntimeError(f"Empty sheet {tab}")
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


def append_rows(s, tab, headers, rows, dry):
    if dry or not rows:
        return
    last = col_letter(len(headers))
    values = [[data.get(h, "") for h in headers] for data in rows]
    s.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A:{last}",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": values},
    ).execute()


def append_row(s, tab, headers, data, dry):
    append_rows(s, tab, headers, [data], dry)


def batch_update_fields(s, tab, headers, updates, dry):
    """updates: list of (row_no, {field:value}). One Sheets write request total."""
    if dry or not updates:
        return
    data = []
    for row_no, fields in updates:
        for field, value in fields.items():
            if field not in headers:
                continue
            col = col_letter(headers.index(field) + 1)
            data.append({"range": f"'{tab}'!{col}{row_no}", "values": [[value]]})
    if data:
        s.spreadsheets().values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"valueInputOption": "RAW", "data": data},
        ).execute()


def update_fields(s, tab, row_no, headers, data, dry):
    batch_update_fields(s, tab, headers, [(row_no, data)], dry)


def parse_fitment(row):
    text = str(row.get("fitment_text", "")).strip()
    make = str(row.get("vehicle_make", "")).strip().upper()
    base, _, notes = text.partition(" | Important notes:")
    rest = base
    if make and rest.upper().startswith(make + " "):
        rest = rest[len(make):].strip()
    pat = re.compile(rf"^(?P<prefix>.+?)\s+(?P<engine_code>[A-Z0-9-]{{2,10}})\s+(?P<fuel>{FUEL})\s+(?P<engine>\d{{1,2}}(?:[.,]\d+)?)\s+(?P<hp>\d{{2,4}})hp\s+(?P<kw>\d{{2,4}})kw\s+(?P<yf>\d{{4}})-(?P<yt>\d{{4}}|now|current)$", re.I)
    m = pat.match(rest)
    if not m:
        return {
            "make": make, "model": base, "generation": "", "engine_code": "", "fuel": "", "engine": "",
            "year_from": row.get("year_from", ""), "year_to": row.get("year_to", ""), "pr": "", "notes": text,
        }
    prefix = m.group("prefix").strip()
    generation = ""
    model = prefix
    pm = re.search(r"\s+((?:[A-Z]\d+|[IVX]+)\s+)?(\([^)]{2,40}\))$", prefix, re.I)
    if pm:
        candidate = (pm.group(1) or "") + pm.group(2)
        generation = candidate.strip()
        model = prefix[:pm.start()].strip()
    pr = ""
    prm = re.search(r"(?:For\s+)?PR\s+number\s*:\s*([^;|]+)", notes, re.I)
    if prm:
        pr = prm.group(1).strip()
    return {
        "make": make, "model": model, "generation": generation,
        "engine_code": m.group("engine_code").upper(), "fuel": m.group("fuel"),
        "engine": m.group("engine").replace(",", "."), "year_from": m.group("yf"),
        "year_to": m.group("yt").lower().replace("current", "now"), "pr": pr, "notes": text,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    gate = payload.get("automation_gate", {})
    cars = payload.get("cars245", {})
    offer = payload.get("offer_input", {})

    verified_mode = bool(gate.get("ai_eligible"))
    candidate_mode = bool(gate.get("catalog_mapped_candidate")) and bool(cars.get("candidate_fitments"))
    if not verified_mode and not candidate_mode:
        print(json.dumps({"status":"SKIPPED_REVIEW_GATE","reason":gate.get("review_reason","")}, ensure_ascii=False))
        return

    oem = str(offer.get("oem_number", "")).strip()
    if not norm(oem):
        raise SystemExit("Fitment gate has no OEM")
    supplier_part = str(offer.get("supplier_part_number", "")).strip()
    manufacturer_brand = str(offer.get("manufacturer_brand", "")).strip()
    catalog_brand = str(offer.get("catalog_brand", "")).strip().upper()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    s = svc()

    h38, r38 = read_table(s, "38_Product_Identifiers", "R")
    existing_tuple = next(((rn, r) for rn, r in r38 if norm(r.get("Original_Value")) == norm(oem) or norm(r.get("Normalized_Value")) == norm(oem)), None)
    existing = existing_tuple[1] if existing_tuple else None
    product_id = str(existing.get("Product_ID", "")).strip() if existing else oem
    created_ids = 0
    updated_ids = 0

    desired_identifier_status = "Verified" if verified_mode else "Review Required - Catalog Mapped"
    desired_identifier_conf = "High" if verified_mode else "Medium"
    desired_identifier_notes = (
        "Exact searched OEM or explicit Cars245 cross-reference/supersession evidence; safe fitment gate passed"
        if verified_mode else
        "Supplier-provided OEM matched to same-family Cars245 page that mentions searched OEM; exact OEM/supersession not yet proven; AI locked"
    )

    if not existing:
        append_row(s, "38_Product_Identifiers", h38, {
            "Identifier_ID": stable_id("ID-AUTO", product_id, "OEM", norm(oem)),
            "Product_ID": product_id,
            "Identifier_Type": "OEM",
            "Original_Value": oem,
            "Normalized_Value": norm(oem),
            "Brand": catalog_brand,
            "Source_Type": "Cars245",
            "Source_Record_ID": norm(oem),
            "Source_File": "Cars245 / GitHub Actions",
            "Verified_Status": desired_identifier_status,
            "Extraction_Confidence": desired_identifier_conf,
            "Is_Primary": "TRUE",
            "Last_Checked_At": today,
            "Notes": desired_identifier_notes,
        }, args.dry_run)
        created_ids += 1
    elif verified_mode and not str(existing.get("Verified_Status", "")).upper().startswith("VERIFIED"):
        update_fields(s, "38_Product_Identifiers", existing_tuple[0], h38, {
            "Verified_Status": "Verified",
            "Extraction_Confidence": "High",
            "Last_Checked_At": today,
            "Notes": desired_identifier_notes,
        }, args.dry_run)
        updated_ids += 1

    if verified_mode:
        found_mpn = any(norm(alt.get("part_number")) == norm(supplier_part) and norm(supplier_part) for alt in cars.get("alternatives", []))
        if found_mpn and not any(norm(r.get("Original_Value")) == norm(supplier_part) for _, r in r38):
            append_row(s, "38_Product_Identifiers", h38, {
                "Identifier_ID": stable_id("ID-AUTO", product_id, "MPN", norm(supplier_part)),
                "Product_ID": product_id,
                "Identifier_Type": "Manufacturer Part Number",
                "Original_Value": supplier_part,
                "Normalized_Value": norm(supplier_part),
                "Brand": manufacturer_brand,
                "Source_Type": "Cars245",
                "Source_Record_ID": norm(oem),
                "Source_File": "Cars245 / GitHub Actions",
                "Verified_Status": "Verified Cross-Reference",
                "Extraction_Confidence": "High",
                "Is_Primary": "FALSE",
                "Last_Checked_At": today,
                "Notes": "Exact supplier MPN returned by strongly evidenced Cars245 alternative list",
            }, args.dry_run)
            created_ids += 1

    h39, r39 = read_table(s, "39_Vehicle_Fitment", "V")
    existing_by_key = {}
    for rn, r in r39:
        key = (str(r.get("Product_ID", "")), norm(r.get("Vehicle_Make")), norm(r.get("Vehicle_Model")), norm(r.get("Engine_Code")), str(r.get("Year_From", "")), str(r.get("Year_To", "")), norm(r.get("PR_Code")))
        existing_by_key[key] = (rn, r)

    raw_fitments = cars.get("fitments", []) if verified_mode else cars.get("candidate_fitments", [])
    pending_rows = []
    promotion_updates = []
    created_fitments = 0
    promoted_fitments = 0

    for raw in raw_fitments:
        f = parse_fitment(raw)
        key = (product_id, norm(f["make"]), norm(f["model"]), norm(f["engine_code"]), str(f["year_from"]), str(f["year_to"]), norm(f["pr"]))
        source_url = str(raw.get("source_url", ""))
        if key in existing_by_key:
            rn, old = existing_by_key[key]
            if verified_mode and rn and "CANDIDATE" in str(old.get("Fitment_Status", "")).upper():
                promotion_updates.append((rn, {
                    "Fitment_Status": "Compatible - conditional",
                    "Verified_Status": "Verified source; exact variant conditional",
                    "Last_Checked_At": today,
                    "Notes": f["notes"] + (f" | Source: {source_url}" if source_url else "") + " | Promoted from candidate after strong OEM evidence",
                }))
                promoted_fitments += 1
            continue

        fitment_status = "Compatible - conditional" if verified_mode else "Candidate - Review Required"
        verified_status = "Verified source; exact variant conditional" if verified_mode else "Cars245 page mentions searched OEM; catalog mapping candidate; OEM/supersession not proven"
        vin_rule = (
            "Check VIN + PR/engine code before final confirmation when variant is conditional"
            if verified_mode else
            "MANDATORY REVIEW: confirm OEM/supersession and VIN/PR before customer fitment confirmation"
        )
        pending_rows.append({
            "Fitment_ID": stable_id("FIT-AUTO", *key),
            "Product_ID": product_id,
            "Vehicle_Make": f["make"],
            "Vehicle_Model": f["model"],
            "Generation": f["generation"],
            "Year_From": f["year_from"],
            "Year_To": f["year_to"],
            "Engine": f["engine"],
            "Engine_Code": f["engine_code"],
            "Transmission": "Verify exact transmission/variant by VIN when applicable",
            "Fuel_Type": f["fuel"],
            "Body_Type": "",
            "PR_Code": f["pr"],
            "VIN_Rule": vin_rule,
            "Fitment_Status": fitment_status,
            "Verification_Source": "Cars245",
            "Source_Record_ID": norm(oem),
            "Source_File": "Cars245 / GitHub Actions",
            "Verified_Status": verified_status,
            "Last_Checked_At": today,
            "Notes": f["notes"] + (f" | Source: {source_url}" if source_url else ""),
        })
        created_fitments += 1
        existing_by_key[key] = (0, {})

    # One API write for all new fitments and one API write for all promotions.
    # This avoids the Google Sheets 60 write-requests/minute/user quota.
    append_rows(s, "39_Vehicle_Fitment", h39, pending_rows, args.dry_run)
    batch_update_fields(s, "39_Vehicle_Fitment", h39, promotion_updates, args.dry_run)

    print(json.dumps({
        "status":"DRY_RUN" if args.dry_run else "SUCCESS",
        "mode":"verified" if verified_mode else "candidate",
        "product_id":product_id,
        "identifiers_created":created_ids,
        "identifiers_updated":updated_ids,
        "fitments_created":created_fitments,
        "fitments_promoted":promoted_fitments,
        "fitments_input":len(raw_fitments),
        "sheets_fitment_write_batches": int(bool(pending_rows)) + int(bool(promotion_updates)),
        "ai_eligible":verified_mode,
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
