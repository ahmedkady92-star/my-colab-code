#!/usr/bin/env python3
import argparse, json, os, re
from collections import defaultdict

import google.auth
from googleapiclient.discovery import build

SPREADSHEET_ID = os.environ.get("ELKADY_SPREADSHEET_ID", "1A-8YoZkVIdelh2x3i7DmeFCERLeR1XREyEpK3Wrk6B0")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def norm(v):
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def year_int(v):
    m = re.search(r"(19|20)\d{2}", str(v or ""))
    return int(m.group(0)) if m else None


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


def summarize(rows):
    groups = {}
    makes, engines, all_years = [], [], []
    statuses = set()
    for row in rows:
        make = str(row.get("Vehicle_Make", "")).strip()
        model = str(row.get("Vehicle_Model", "")).strip()
        gen = str(row.get("Generation", "")).strip()
        yf = year_int(row.get("Year_From"))
        yt = year_int(row.get("Year_To"))
        code = str(row.get("Engine_Code", "")).strip()
        status = str(row.get("Fitment_Status", "")).strip()
        if make and make not in makes:
            makes.append(make)
        if code and code not in engines:
            engines.append(code)
        if yf: all_years.append(yf)
        if yt: all_years.append(yt)
        if status: statuses.add(status)
        key = (make, model, gen)
        g = groups.setdefault(key, {"from": [], "to": []})
        if yf: g["from"].append(yf)
        if yt: g["to"].append(yt)

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
    engine_preview = ", ".join(engines[:18])
    if len(engines) > 18:
        engine_preview += f" +{len(engines)-18} more"
    candidate = any("CANDIDATE" in s.upper() or "REVIEW" in s.upper() for s in statuses)
    return {
        "Vehicle_Make": "; ".join(makes),
        "Vehicle_Model": summary_text,
        "Year_From": min(all_years) if all_years else "",
        "Year_To": max(all_years) if all_years else "",
        "Engine": (f"Multiple engines: {engine_preview}. VIN/PR required for exact application" if engines else "VIN/PR required for exact application"),
        "candidate": candidate,
        "fitment_count": len(rows),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Write updates; default is dry-run")
    ap.add_argument("--report", default="automation_output/ai_fitment_backfill_report.json")
    args = ap.parse_args()

    svc = service()
    _, fitments = read_table(svc, "39_Vehicle_Fitment", "V")
    h41, ai_rows = read_table(svc, "41_AI_Product_Feed", "Y")

    fitment_index = defaultdict(list)
    for _, r in fitments:
        for key in {norm(r.get("Product_ID")), norm(r.get("Source_Record_ID"))}:
            if key:
                fitment_index[key].append(r)

    header_pos = {h: i for i, h in enumerate(h41)}
    updates = []
    report_rows = []
    skipped_no_key = skipped_no_fitment = skipped_invalid_ai = 0

    for rn, ai in ai_rows:
        ai_id = str(ai.get("AI_Feed_ID", "")).strip()
        if not ai_id:
            skipped_invalid_ai += 1
            continue
        keys = {norm(ai.get("Part_Number")), norm(ai.get("OEM_Number"))}
        keys.discard("")
        if not keys:
            skipped_no_key += 1
            continue
        matched = []
        seen = set()
        for key in keys:
            for r in fitment_index.get(key, []):
                sig = tuple(str(r.get(h, "")) for h in ("Product_ID","Vehicle_Make","Vehicle_Model","Generation","Year_From","Year_To","Engine_Code","Fitment_Status"))
                if sig not in seen:
                    seen.add(sig)
                    matched.append(r)
        if not matched:
            skipped_no_fitment += 1
            continue

        s = summarize(matched)
        fitment_note = f"Fitment summary from 39_Vehicle_Fitment: {s['Vehicle_Model']}."
        if s["candidate"]:
            fitment_note += " Candidate fitment only; confirm OEM/supersession and VIN/PR before final customer confirmation."
        else:
            fitment_note += " Confirm VIN/PR when the application is conditional."
        old_notes = str(ai.get("Notes", "")).strip()
        old_notes = re.sub(r"\s*\|\s*Fitment summary from 39_Vehicle_Fitment:.*$", "", old_notes, flags=re.I)
        notes = (old_notes + " | " + fitment_note).strip(" |")

        changes = {
            "Vehicle_Make": s["Vehicle_Make"],
            "Vehicle_Model": s["Vehicle_Model"],
            "Year_From": s["Year_From"],
            "Year_To": s["Year_To"],
            "Engine": s["Engine"],
            "Notes": notes,
        }
        current = {k: str(ai.get(k, "")) for k in changes}
        changed = any(str(changes[k]) != current[k] for k in changes)
        report_rows.append({
            "ai_row": rn,
            "ai_feed_id": ai_id,
            "part_number": ai.get("Part_Number", ""),
            "oem_number": ai.get("OEM_Number", ""),
            "fitment_count": s["fitment_count"],
            "vehicle_make": s["Vehicle_Make"],
            "vehicle_model": s["Vehicle_Model"],
            "year_from": s["Year_From"],
            "year_to": s["Year_To"],
            "candidate": s["candidate"],
            "changed": changed,
        })
        if not changed:
            continue

        row_values = [ai.get(h, "") for h in h41]
        for k, v in changes.items():
            if k in header_pos:
                row_values[header_pos[k]] = v
        updates.append({
            "range": f"'41_AI_Product_Feed'!A{rn}:{col_letter(len(h41))}{rn}",
            "values": [row_values],
        })

    if args.apply and updates:
        svc.spreadsheets().values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"valueInputOption": "RAW", "data": updates},
        ).execute()

    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    report = {
        "mode": "APPLY" if args.apply else "DRY_RUN",
        "ai_rows_scanned": len(ai_rows),
        "fitment_rows_scanned": len(fitments),
        "matched_ai_rows": len(report_rows),
        "rows_needing_update": len(updates),
        "rows_written": len(updates) if args.apply else 0,
        "skipped_invalid_ai": skipped_invalid_ai,
        "skipped_no_key": skipped_no_key,
        "skipped_no_fitment": skipped_no_fitment,
        "rows": report_rows,
    }
    with open(args.report, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
