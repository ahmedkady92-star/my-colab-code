#!/usr/bin/env python3
import argparse, hashlib, json, os, re, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cars245_brands import BRANDS
from tools.process_new_supplier_rows import brand_priority, score
from tools.upsert_verified_fitment import (
    svc, read_table, append_rows, append_row, batch_update_fields,
    parse_fitment, stable_id, norm,
)

SPREADSHEET_ID = os.environ.get("ELKADY_SPREADSHEET_ID", "1A-8YoZkVIdelh2x3i7DmeFCERLeR1XREyEpK3Wrk6B0")
AUDIT_SOURCE = "AI FITMENT BACKFILL / CARS245"


def valid_part(v):
    n = norm(v)
    return len(n) >= 5 and any(ch.isdigit() for ch in n)


def first_part(value):
    for token in re.split(r"[;|,\n]+", str(value or "")):
        token = token.strip()
        if valid_part(token):
            return token
    return ""


def move_front(order, keys):
    out = []
    for k in keys:
        if k in BRANDS and k not in out:
            out.append(k)
    for k in order:
        if k in BRANDS and k not in out:
            out.append(k)
    return out


def catalog_priority(row, target):
    hint = " ".join([
        str(row.get("Vehicle_Make", "")), str(row.get("Vehicle_Model", "")),
        str(row.get("Description", "")), str(row.get("Part_Name", "")), target,
    ])
    order = brand_priority(hint)
    c = norm(target)
    front = []
    if c.startswith("LR"):
        front = ["landrover", "jaguar"]
    elif re.match(r"^A\d{8,}$", c):
        front = ["mercedes"]
    elif c.startswith(("9Y", "95B", "971", "970", "958", "987", "997", "991", "992")):
        front = ["porsche", "audi", "volkswagen"]
    elif c.startswith(("4M", "4G", "4H", "4F", "8K", "8W", "8R", "83A", "80A")):
        front = ["audi", "volkswagen", "porsche"]
    elif c.startswith(("5Q", "3Q", "5WA", "1K", "7L", "7P")):
        front = ["volkswagen", "audi", "skoda", "seat", "porsche"]
    return move_front(order, front)


def run_research(row, target, catalog, out_dir):
    offer = {
        "supplier": "AI-BACKFILL",
        "supplier_id": "AI-BACKFILL",
        "manufacturer_brand": str(row.get("Brand", "") or "Research"),
        "supplier_part_number": str(row.get("Part_Number", "") or target),
        "oem_number": target,
        "part_description": " | ".join(x for x in [str(row.get("Part_Name", "")).strip(), str(row.get("Description", "")).strip()] if x),
        "supplier_cost": 1,
        "currency": "EGP",
        "catalog_brand": catalog,
    }
    input_path = out_dir.parent / f"{out_dir.name}_input.json"
    input_path.write_text(json.dumps(offer, ensure_ascii=False, indent=2), encoding="utf-8")
    subprocess.run(
        [sys.executable, "supplier_automation.py", "--input", str(input_path), "--output-dir", str(out_dir)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=150,
    )
    return json.loads((out_dir / "import_payload.json").read_text(encoding="utf-8"))


def classify_payload(payload):
    gate = payload.get("automation_gate", {})
    cars = payload.get("cars245", {})
    safe = list(cars.get("fitments", []) or [])
    cand = list(cars.get("candidate_fitments", []) or [])
    expected = str(gate.get("expected_family", ""))
    family_match = bool(gate.get("family_match"))
    strong = bool(gate.get("exact_oem_evidence")) and bool(safe)
    if gate.get("ai_eligible") and safe:
        return "AI_SAFE", safe
    if strong and (family_match or not expected):
        return "STRONG_REVIEW", safe
    if gate.get("catalog_mapped_candidate") and cand:
        return "CANDIDATE_REVIEW", cand
    return "NO_FITMENT_EVIDENCE", []


def existing_fitment_keys(rows):
    keys = set()
    for _, r in rows:
        for v in (r.get("Product_ID"), r.get("Source_Record_ID")):
            n = norm(v)
            if n:
                keys.add(n)
    return keys


def audit_done(rows):
    done = set()
    for _, r in rows:
        if str(r.get("Source_System", "")).strip().upper() == AUDIT_SOURCE:
            rid = str(r.get("Source_Record_ID", "")).strip()
            if rid:
                done.add(rid)
    return done


def product_id_for_target(id_rows, target):
    t = norm(target)
    for _, r in id_rows:
        if norm(r.get("Original_Value")) == t or norm(r.get("Normalized_Value")) == t:
            pid = str(r.get("Product_ID", "")).strip()
            if pid:
                return pid
    return target


def write_identifier(s, headers, id_rows, product_id, target, catalog, mode, today, dry=False):
    t = norm(target)
    existing = next(((rn, r) for rn, r in id_rows if norm(r.get("Original_Value")) == t or norm(r.get("Normalized_Value")) == t), None)
    if existing:
        rn, r = existing
        if mode in ("AI_SAFE", "STRONG_REVIEW") and not str(r.get("Verified_Status", "")).upper().startswith("VERIFIED"):
            batch_update_fields(s, "38_Product_Identifiers", headers, [(rn, {
                "Verified_Status": "Verified" if mode == "AI_SAFE" else "Verified Source - AI Review Required",
                "Extraction_Confidence": "High",
                "Last_Checked_At": today,
                "Notes": "Cars245 backlog enrichment: exact OEM/cross-reference evidence with vehicle fitment; AI safety gate preserved",
            })], dry)
        return 0
    status = "Verified" if mode == "AI_SAFE" else ("Verified Source - AI Review Required" if mode == "STRONG_REVIEW" else "Review Required - Catalog Mapped")
    conf = "High" if mode in ("AI_SAFE", "STRONG_REVIEW") else "Medium"
    append_row(s, "38_Product_Identifiers", headers, {
        "Identifier_ID": stable_id("ID-AIBF", product_id, "OEM", t),
        "Product_ID": product_id,
        "Identifier_Type": "OEM",
        "Original_Value": target,
        "Normalized_Value": t,
        "Brand": catalog.upper(),
        "Source_Type": "Cars245",
        "Source_Record_ID": t,
        "Source_File": "Cars245 / AI fitment backlog",
        "Verified_Status": status,
        "Extraction_Confidence": conf,
        "Is_Primary": "TRUE",
        "Last_Checked_At": today,
        "Notes": "Backlog enrichment; fitment evidence stored with VIN/PR guard",
    }, dry)
    return 1


def write_fitments(s, headers, fit_rows, product_id, target, mode, raw_rows, today, dry=False):
    existing = set()
    for _, r in fit_rows:
        key = (str(r.get("Product_ID", "")), norm(r.get("Vehicle_Make")), norm(r.get("Vehicle_Model")), norm(r.get("Engine_Code")), str(r.get("Year_From", "")), str(r.get("Year_To", "")), norm(r.get("PR_Code")))
        existing.add(key)
    pending = []
    for raw in raw_rows:
        f = parse_fitment(raw)
        key = (product_id, norm(f["make"]), norm(f["model"]), norm(f["engine_code"]), str(f["year_from"]), str(f["year_to"]), norm(f["pr"]))
        if key in existing or not f["make"] or not f["model"]:
            continue
        if mode == "AI_SAFE":
            fit_status = "Compatible - conditional"
            verified = "Verified source; exact variant conditional"
            vin_rule = "Check VIN + PR/engine code before final confirmation when variant is conditional"
        elif mode == "STRONG_REVIEW":
            fit_status = "Evidence-backed - Review Required"
            verified = "Exact OEM/cross-reference evidence; AI family policy review required"
            vin_rule = "MANDATORY REVIEW: confirm VIN/PR before final customer fitment confirmation"
        else:
            fit_status = "Candidate - Review Required"
            verified = "Cars245 page mentions searched OEM; catalog mapping candidate; exact OEM/supersession not proven"
            vin_rule = "MANDATORY REVIEW: confirm OEM/supersession and VIN/PR before customer fitment confirmation"
        source_url = str(raw.get("source_url", ""))
        pending.append({
            "Fitment_ID": stable_id("FIT-AIBF", *key),
            "Product_ID": product_id,
            "Vehicle_Make": f["make"], "Vehicle_Model": f["model"], "Generation": f["generation"],
            "Year_From": f["year_from"], "Year_To": f["year_to"], "Engine": f["engine"],
            "Engine_Code": f["engine_code"], "Transmission": "Verify exact transmission/variant by VIN when applicable",
            "Fuel_Type": f["fuel"], "Body_Type": "", "PR_Code": f["pr"], "VIN_Rule": vin_rule,
            "Fitment_Status": fit_status, "Verification_Source": "Cars245", "Source_Record_ID": norm(target),
            "Source_File": "Cars245 / AI fitment backlog", "Verified_Status": verified, "Last_Checked_At": today,
            "Notes": f["notes"] + (f" | Source: {source_url}" if source_url else ""),
        })
        existing.add(key)
    append_rows(s, "39_Vehicle_Fitment", headers, pending, dry)
    return len(pending)


def append_audit(s, headers, ai_id, target, mode, catalog, fit_count, status, note, dry=False):
    now = datetime.now(timezone.utc)
    append_row(s, "43_Sync_Audit", headers, {
        "Audit_ID": stable_id("AUD-AIBF", ai_id, target, now.isoformat()),
        "Sync_Date": now.strftime("%Y-%m-%d"), "Sync_Time": now.strftime("%H:%M:%S UTC"),
        "Source_System": AUDIT_SOURCE, "Destination_System": "Google Sheets",
        "Entity_Type": "AI Product Fitment", "Operation": "Cars245 Backlog Enrichment",
        "Source_Record_ID": ai_id, "Destination_Record_ID": target, "Match_Key": norm(target),
        "Sync_Status": status, "Records_Read": "1", "Records_Created": str(fit_count),
        "Records_Updated": "1" if fit_count else "0", "Records_Skipped": "0", "Duplicates_Detected": "0",
        "Records_Failed": "0" if status != "Failed" else "1", "Error_Message": "",
        "Executed_By": "GitHub Actions", "Batch_ID": "AI-FITMENT-BACKFILL",
        "Validation_Status": mode, "Notes": f"catalog={catalog} | {note}"[:900],
    }, dry)


def update_ai_note(s, headers, rn, row, target, mode, catalog, today, dry=False):
    old = str(row.get("Notes", "")).strip()
    old = re.sub(r"\s*\|\s*AI fitment backlog check:.*$", "", old, flags=re.I)
    msg = f"AI fitment backlog check: {mode}; OEM={target}; catalog={catalog}; Cars245 checked {today}"
    batch_update_fields(s, "41_AI_Product_Feed", headers, [(rn, {
        "Last_Checked_At": today,
        "Notes": (old + " | " + msg).strip(" |")[:45000],
    })], dry)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-items", type=int, default=5)
    ap.add_argument("--max-brands", type=int, default=5)
    ap.add_argument("--scan-only", action="store_true")
    ap.add_argument("--retry-audited", action="store_true")
    args = ap.parse_args()

    s = svc()
    h41, r41 = read_table(s, "41_AI_Product_Feed", "Y")
    h38, r38 = read_table(s, "38_Product_Identifiers", "R")
    h39, r39 = read_table(s, "39_Vehicle_Fitment", "V")
    h43, r43 = read_table(s, "43_Sync_Audit", "V")
    fit_keys = existing_fitment_keys(r39)
    done = set() if args.retry_audited else audit_done(r43)

    backlog = []
    invalid = 0
    already_fit = 0
    already_attempted = 0
    for rn, row in r41:
        ai_id = str(row.get("AI_Feed_ID", "")).strip()
        if not ai_id.startswith("AI-"):
            invalid += 1; continue
        target = first_part(row.get("OEM_Number")) or first_part(row.get("Part_Number"))
        if not target:
            invalid += 1; continue
        if norm(target) in fit_keys:
            already_fit += 1; continue
        if ai_id in done:
            already_attempted += 1; continue
        backlog.append((rn, row, ai_id, target))

    summary = {
        "mode": "SCAN_ONLY" if args.scan_only else "APPLY",
        "ai_rows": len(r41), "fitment_rows": len(r39), "backlog_remaining": len(backlog),
        "already_has_fitment": already_fit, "already_attempted": already_attempted, "invalid_or_no_key": invalid,
        "processed": []
    }
    if args.scan_only:
        summary["preview"] = [{"row": rn, "ai_id": ai, "target": target, "part": row.get("Part_Name", ""), "vehicle_hint": row.get("Vehicle_Make", "")} for rn, row, ai, target in backlog[:20]]
        Path("automation_output").mkdir(exist_ok=True)
        Path("automation_output/ai_fitment_backlog_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2)); return

    work = Path("ai_fitment_backlog_output")
    shutil.rmtree(work, ignore_errors=True); work.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for rn, row, ai_id, target in backlog[:args.max_items]:
        attempts = []; best = None
        priorities = catalog_priority(row, target)[:args.max_brands]
        for catalog in priorities:
            out = work / f"{rn}_{catalog}"
            try:
                payload = run_research(row, target, catalog, out)
                sc = score(payload)
                mode, fit_rows = classify_payload(payload)
                attempts.append({"catalog": catalog, "score": sc, "mode": mode, "fitments": len(fit_rows)})
                rank = {"NO_FITMENT_EVIDENCE":0, "CANDIDATE_REVIEW":1, "STRONG_REVIEW":2, "AI_SAFE":3}[mode]
                if best is None or (rank, sc) > (best[0], best[1]):
                    best = (rank, sc, catalog, payload, fit_rows, mode, out / "import_payload.json")
                if rank >= 2 or (rank == 1 and len(fit_rows) > 0):
                    break
            except Exception as exc:
                attempts.append({"catalog": catalog, "error": str(exc)[:220]})

        if best is None:
            mode = "ERROR"; catalog = ""; fit_count = 0
            update_ai_note(s, h41, rn, row, target, mode, catalog, today)
            append_audit(s, h43, ai_id, target, mode, catalog, 0, "Failed", "No Cars245 catalog attempt completed")
            summary["processed"].append({"ai_id":ai_id,"target":target,"mode":mode,"attempts":attempts}); continue

        _, _, catalog, payload, raw_fitments, mode, payload_path = best
        fit_count = 0
        if mode != "NO_FITMENT_EVIDENCE":
            product_id = product_id_for_target(r38, target)
            write_identifier(s, h38, r38, product_id, target, catalog, mode, today)
            # Refresh identifiers after possible insert so later items with same OEM share the same master.
            h38, r38 = read_table(s, "38_Product_Identifiers", "R")
            product_id = product_id_for_target(r38, target)
            h39, r39 = read_table(s, "39_Vehicle_Fitment", "V")
            fit_count = write_fitments(s, h39, r39, product_id, target, mode, raw_fitments, today)
            if fit_count:
                subprocess.run([sys.executable, "tools/sync_fitment_summary_to_ai_feed.py", "--payload", str(payload_path)], check=True, stdout=subprocess.DEVNULL)
        update_ai_note(s, h41, rn, row, target, mode, catalog, today)
        status = "Success" if fit_count else "Review Required"
        append_audit(s, h43, ai_id, target, mode, catalog, fit_count, status, f"attempts={attempts}")
        summary["processed"].append({"ai_id": ai_id, "target": target, "mode": mode, "catalog": catalog, "fitments_written": fit_count, "attempts": attempts})

    Path("automation_output").mkdir(exist_ok=True)
    Path("automation_output/ai_fitment_backlog_report.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
