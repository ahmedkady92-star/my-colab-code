#!/usr/bin/env python3
import argparse, hashlib, json, os, re, shutil, subprocess, sys
from pathlib import Path

import google.auth
from googleapiclient.discovery import build
from cars245_brands import BRANDS

SPREADSHEET_ID = os.environ.get("ELKADY_SPREADSHEET_ID", "1A-8YoZkVIdelh2x3i7DmeFCERLeR1XREyEpK3Wrk6B0")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DEFAULT_BASELINE_ROW = 1003


def norm(v):
    return re.sub(r"[^A-Z0-9]", "", str(v or "").upper())


def valid_part(v):
    n = norm(v)
    return len(n) >= 5 and any(ch.isdigit() for ch in n)


def stable_offer_id(row_no, supplier, part, brand, cost):
    h = hashlib.sha1(f"{row_no}|{supplier}|{part}|{brand}|{cost}".encode()).hexdigest()[:12].upper()
    return f"OFF-AUTO-{h}"


def service():
    creds, _ = google.auth.default(scopes=SCOPES)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def table(s, tab, start_row=1, end_row=None, end_col="Z"):
    meta = s.spreadsheets().get(spreadsheetId=SPREADSHEET_ID, fields="sheets.properties").execute()
    props = next(x["properties"] for x in meta["sheets"] if x["properties"]["title"] == tab)
    max_row = props["gridProperties"]["rowCount"]
    end_row = min(end_row or max_row, max_row)
    vals = s.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'!A{start_row}:{end_col}{end_row}"
    ).execute().get("values", [])
    return vals, max_row


def update_fields(s, tab, row_no, headers, changes):
    pos = {h: i for i, h in enumerate(headers)}
    data = []
    for key, value in changes.items():
        if key not in pos:
            continue
        col = pos[key]
        letters = ""
        n = col + 1
        while n:
            n, rem = divmod(n - 1, 26)
            letters = chr(65 + rem) + letters
        data.append({"range": f"'{tab}'!{letters}{row_no}", "values": [[value]]})
    if data:
        s.spreadsheets().values().batchUpdate(
            spreadsheetId=SPREADSHEET_ID,
            body={"valueInputOption":"RAW","data":data},
        ).execute()


def brand_priority(text):
    t = str(text or "").upper()
    out = []
    hints = [
        ("LAND ROVER", "landrover"), ("RANGE ROVER", "landrover"), ("DISCOVERY", "landrover"),
        ("JAGUAR", "jaguar"), ("MERCEDES", "mercedes"), ("BMW", "bmw"), ("VOLVO", "volvo"),
        ("PORSCHE", "porsche"), ("CAYENNE", "porsche"), ("MACAN", "porsche"), ("PANAMERA", "porsche"),
        ("BENTLEY", "bentley"), ("CUPRA", "cupra"), ("SKODA", "skoda"), ("SEAT", "seat"),
        ("VOLKSWAGEN", "volkswagen"), (" VW ", "volkswagen"), ("AUDI", "audi"),
    ]
    for token, key in hints:
        if token in t and key not in out:
            out.append(key)
    compact = norm(text)
    if compact.startswith("LR") and "landrover" not in out:
        out.insert(0, "landrover")
    if compact.startswith("A") and len(compact) >= 8 and compact[1:].isdigit() and "mercedes" not in out:
        out.insert(0, "mercedes")
    for key in ("audi","volkswagen","skoda","seat","cupra","porsche","bentley","landrover","jaguar","bmw","mercedes","volvo"):
        if key in BRANDS and key not in out:
            out.append(key)
    return out


def run_supplier_automation(offer, out_dir):
    import supplier_automation
    supplier_automation.SUPPORTED_SUPPLIERS.add(str(offer["supplier"]).upper().strip())
    input_path = out_dir.parent / f"{out_dir.name}_input.json"
    input_path.write_text(json.dumps(offer, ensure_ascii=False, indent=2), encoding="utf-8")
    old = sys.argv[:]
    try:
        sys.argv = ["supplier_automation.py", "--input", str(input_path), "--output-dir", str(out_dir)]
        supplier_automation.main()
    finally:
        sys.argv = old
    return json.loads((out_dir / "import_payload.json").read_text(encoding="utf-8"))


def score(payload):
    cars = payload.get("cars245", {})
    fit = cars.get("fitment_enrichment", {})
    gate = payload.get("automation_gate", {})
    return (
        1000000 * int(bool(gate.get("ai_eligible")))
        + 100000 * int(fit.get("exact_oem_urls", 0) > 0)
        + 10000 * min(int(fit.get("matched_search_part_urls", 0)), 9)
        + 10 * int(cars.get("fitment_rows_found", 0))
        + int(cars.get("product_links_found", 0))
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline-row", type=int, default=DEFAULT_BASELINE_ROW)
    ap.add_argument("--max-candidates", type=int, default=2)
    ap.add_argument("--scan-only", action="store_true")
    args = ap.parse_args()

    s = service()
    vals, max_row = table(s, "36_Supplier_Offers", 1, None, "Z")
    if not vals:
        raise SystemExit("36_Supplier_Offers is empty")
    headers = vals[0]
    rows = []
    for rn, row in enumerate(vals[1:], start=2):
        row = row + [""] * (len(headers) - len(row))
        rows.append((rn, dict(zip(headers, row))))

    audit_vals, _ = table(s, "43_Sync_Audit", 1, None, "V")
    processed = set()
    if audit_vals:
        ah = audit_vals[0]
        for row in audit_vals[1:]:
            row = row + [""] * (len(ah) - len(row))
            d = dict(zip(ah, row))
            if "GITHUB ACTIONS / CARS245" in str(d.get("Source_System", "")).upper():
                rid = str(d.get("Source_Record_ID", "")).strip()
                if rid:
                    processed.add(rid)

    candidates = []
    for rn, r in rows:
        if rn <= args.baseline_row:
            continue
        supplier = str(r.get("Supplier_Name", "")).strip()
        brand = str(r.get("Brand", "")).strip()
        original = str(r.get("Original_Part_Number", "")).strip()
        oem_field = str(r.get("OEM_Number", "")).strip()
        oem = next((x.strip() for x in re.split(r"[;|]", oem_field) if valid_part(x)), "") or (original if valid_part(original) else "")
        cost_raw = str(r.get("Supplier_Cost", "")).replace(",", "").strip()
        try:
            cost = float(cost_raw)
        except Exception:
            cost = 0
        offer_id = str(r.get("Supplier_Offer_ID", "")).strip()
        if not offer_id and supplier and brand and cost and oem:
            offer_id = stable_offer_id(rn, supplier, original or oem, brand, cost)
            if not args.scan_only:
                update_fields(s, "36_Supplier_Offers", rn, headers, {"Supplier_Offer_ID": offer_id})
        if offer_id in processed:
            continue
        if not (supplier and brand and cost > 0 and valid_part(oem)):
            continue
        candidates.append((rn, r, offer_id, oem, cost))

    summary = {"baseline_row": args.baseline_row, "sheet_max_row": max_row, "candidate_count": len(candidates), "processed": []}
    if args.scan_only:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    work = Path("supplier_sheet_trigger_output")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    for rn, r, offer_id, oem, cost in candidates[:args.max_candidates]:
        supplier = str(r.get("Supplier_Name", "")).strip()
        supplier_part = str(r.get("Original_Part_Number", "")).strip() or oem
        manufacturer_brand = str(r.get("Brand", "")).strip()
        currency = str(r.get("Currency", "EGP") or "EGP").strip().upper()
        description = str(r.get("Part_Description", "")).strip()
        if currency != "EGP":
            update_fields(s, "36_Supplier_Offers", rn, headers, {
                "Product_Match_Status":"Review Required", "Review_Reason":"Automatic pricing currently requires EGP supplier cost",
                "Extraction_Status":"Auto Review Required"
            })
            summary["processed"].append({"row":rn,"offer_id":offer_id,"status":"REVIEW_CURRENCY"})
            continue

        base_offer = {
            "supplier": supplier,
            "supplier_id": str(r.get("Supplier_ID", "")).strip(),
            "manufacturer_brand": manufacturer_brand,
            "supplier_part_number": supplier_part,
            "oem_number": oem,
            "part_description": description,
            "supplier_cost": cost,
            "currency": currency,
        }
        priorities = brand_priority(" ".join([oem, supplier_part, description]))
        best = None
        attempts = []
        for key in priorities:
            offer = dict(base_offer, catalog_brand=key)
            out = work / f"row_{rn}_{key}"
            try:
                payload = run_supplier_automation(offer, out)
                sc = score(payload)
                attempts.append({"brand":key,"score":sc,"ai_eligible":payload.get("automation_gate",{}).get("ai_eligible"),"fitments":payload.get("cars245",{}).get("fitment_rows_found",0)})
                if best is None or sc > best[0]:
                    best = (sc, key, out / "import_payload.json", payload)
                if payload.get("automation_gate", {}).get("ai_eligible"):
                    break
            except Exception as e:
                attempts.append({"brand":key,"error":str(e)[:200]})

        if best is None:
            update_fields(s, "36_Supplier_Offers", rn, headers, {
                "Product_Match_Status":"Review Required", "Review_Reason":"Cars245 automatic brand detection returned no usable result",
                "Extraction_Status":"Auto Review Required"
            })
            summary["processed"].append({"row":rn,"offer_id":offer_id,"status":"REVIEW_NOT_FOUND","attempts":attempts})
            continue

        _, selected_brand, payload_path, payload = best
        subprocess.run([sys.executable, "tools/upsert_verified_fitment.py", "--payload", str(payload_path)], check=True)
        subprocess.run([sys.executable, "tools/sync_supplier_payload_to_sheets.py", "--payload", str(payload_path)], check=True)
        update_fields(s, "36_Supplier_Offers", rn, headers, {
            "Normalized_Part_Number": norm(supplier_part),
            "Extraction_Status":"Automated",
            "Last_Checked_At": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%d"),
            "Notes": (str(r.get("Notes", "")).strip() + f" | Auto trigger processed via Cars245 catalog={selected_brand}").strip(" |"),
        })
        summary["processed"].append({
            "row":rn,"offer_id":offer_id,"status":"SUCCESS","catalog_brand":selected_brand,
            "ai_eligible":payload.get("automation_gate",{}).get("ai_eligible"),"attempts":attempts,
        })

    Path("supplier_sheet_trigger_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
