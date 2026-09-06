#!/usr/bin/env python3
import argparse, json, os, re
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


def read_table(service, tab, end_col):
    values = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A1:{end_col}5000",
    ).execute().get("values", [])
    if not values:
        raise RuntimeError(f"Empty sheet: {tab}")
    headers = values[0]
    rows = []
    for rn, row in enumerate(values[1:], start=2):
        row = row + [""] * (len(headers) - len(row))
        rows.append((rn, dict(zip(headers, row))))
    return headers, rows


def col_letter(n):
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def update_row(service, tab, row_no, headers, changes):
    last = col_letter(len(headers))
    current = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A{row_no}:{last}{row_no}",
    ).execute().get("values", [[]])[0]
    current += [""] * (len(headers) - len(current))
    pos = {h: i for i, h in enumerate(headers)}
    for key, value in changes.items():
        if key in pos:
            current[pos[key]] = value
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{tab}'!A{row_no}:{last}{row_no}",
        valueInputOption="RAW",
        body={"values": [current[:len(headers)]]},
    ).execute()


def year_int(v):
    m = re.search(r"(19|20)\d{2}", str(v or ""))
    return int(m.group(0)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--payload", required=True)
    args = ap.parse_args()

    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    offer = payload["offer_input"]
    part = str(offer.get("supplier_part_number", "")).strip()
    oem = str(offer.get("oem_number", "")).strip()
    targets = {x for x in (norm(part), norm(oem)) if x}
    if not targets:
        raise RuntimeError("No part/OEM target in payload")

    service = svc()
    _, fitments = read_table(service, "39_Vehicle_Fitment", "V")
    h41, ai_rows = read_table(service, "41_AI_Product_Feed", "Y")

    matched_fitments = []
    for _, row in fitments:
        product_key = norm(row.get("Product_ID"))
        source_key = norm(row.get("Source_Record_ID"))
        if product_key in targets or source_key in targets:
            matched_fitments.append(row)

    ai_match = None
    for rn, row in ai_rows:
        row_keys = {
            norm(row.get("Part_Number")),
            norm(row.get("OEM_Number")),
        }
        if targets & row_keys:
            ai_match = (rn, row)
            break

    if not ai_match:
        raise RuntimeError(f"No AI feed row found for {part or oem}")

    rn, ai = ai_match
    if not matched_fitments:
        print(f"FITMENT_SUMMARY_SKIP no fitments for {part or oem}")
        return

    groups = {}
    makes = []
    engine_codes = []
    all_years = []
    statuses = set()

    for row in matched_fitments:
        make = str(row.get("Vehicle_Make", "")).strip()
        model = str(row.get("Vehicle_Model", "")).strip()
        gen = str(row.get("Generation", "")).strip()
        yf = year_int(row.get("Year_From"))
        yt = year_int(row.get("Year_To"))
        code = str(row.get("Engine_Code", "")).strip()
        status = str(row.get("Fitment_Status", "")).strip()

        if make and make not in makes:
            makes.append(make)
        if code and code not in engine_codes:
            engine_codes.append(code)
        if yf:
            all_years.append(yf)
        if yt:
            all_years.append(yt)
        if status:
            statuses.add(status)

        key = (make, model, gen)
        g = groups.setdefault(key, {"from": [], "to": []})
        if yf:
            g["from"].append(yf)
        if yt:
            g["to"].append(yt)

    summaries = []
    for (make, model, gen), yrs in groups.items():
        if not make or not model:
            continue
        start = min(yrs["from"]) if yrs["from"] else None
        end = max(yrs["to"]) if yrs["to"] else None
        name = " ".join(x for x in (make, model, gen) if x)
        if start and end:
            name += f" {start}-{end}"
        summaries.append(name)

    summary_text = "; ".join(summaries[:12])
    engine_preview = ", ".join(engine_codes[:18])
    if len(engine_codes) > 18:
        engine_preview += f" +{len(engine_codes)-18} more"

    candidate = any("CANDIDATE" in s.upper() or "REVIEW" in s.upper() for s in statuses)
    fitment_note = f"Fitment summary from 39_Vehicle_Fitment: {summary_text}."
    if candidate:
        fitment_note += " Candidate fitment only; confirm OEM/supersession and VIN/PR before final customer confirmation."
    else:
        fitment_note += " Confirm VIN/PR when the application is conditional."

    old_notes = str(ai.get("Notes", "")).strip()
    old_notes = re.sub(r"\s*\|\s*Fitment summary from 39_Vehicle_Fitment:.*$", "", old_notes, flags=re.I)
    notes = (old_notes + " | " + fitment_note).strip(" |")

    changes = {
        "Vehicle_Make": "; ".join(makes),
        "Vehicle_Model": summary_text,
        "Year_From": min(all_years) if all_years else "",
        "Year_To": max(all_years) if all_years else "",
        "Engine": (f"Multiple engines: {engine_preview}. VIN/PR required for exact application" if engine_codes else "VIN/PR required for exact application"),
        "Notes": notes,
    }
    update_row(service, "41_AI_Product_Feed", rn, h41, changes)
    print(json.dumps({
        "part": part,
        "fitment_rows": len(matched_fitments),
        "ai_row": rn,
        "vehicle_make": changes["Vehicle_Make"],
        "vehicle_model": changes["Vehicle_Model"],
        "year_from": changes["Year_From"],
        "year_to": changes["Year_To"],
        "candidate": candidate,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
