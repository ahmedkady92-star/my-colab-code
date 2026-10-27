#!/usr/bin/env python3
"""Persist exact OEM fitment evidence that was retained behind a family review gate."""
import json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.sync_supplier_payload_to_sheets import service, read_table, append_row, norm, num

def main():
    svc = service()
    _, offers = read_table(svc, "36_Supplier_Offers", "Z")
    allowed = set()
    for _, row in offers:
        if not str(row.get("Supplier_Offer_ID", "")).startswith("OFF-KANO-XMATCH-20261027"):
            continue
        if "SOURCE_QUARANTINED" in str(row.get("Notes", "")):
            continue
        cost = num(row.get("Supplier_Cost"))
        part = norm(row.get("Original_Part_Number"))
        brand = str(row.get("Brand", "")).strip().upper()
        if part and brand and cost and cost > 0:
            allowed.add((part, brand, cost))
    results = []
    seen = set()
    for path in sorted(Path("kano_finalize_input").rglob("import_payload.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        offer = payload.get("offer_input", {})
        gate = payload.get("automation_gate", {})
        cars = payload.get("cars245", {})
        key = (norm(offer.get("supplier_part_number")), str(offer.get("manufacturer_brand", "")).strip().upper(), num(offer.get("supplier_cost")))
        if str(offer.get("supplier", "")).upper() != "KANO" or key not in allowed:
            continue
        if gate.get("ai_eligible") or (gate.get("catalog_mapped_candidate") and cars.get("candidate_fitments")):
            continue
        if not gate.get("exact_oem_evidence") or not cars.get("fitments"):
            continue
        evidence_key = (norm(offer.get("oem_number")), json.dumps(cars.get("fitments"), sort_keys=True))
        if evidence_key in seen:
            continue
        seen.add(evidence_key)
        output = subprocess.check_output([sys.executable, "tools/upsert_verified_fitment.py", "--payload", str(path)], text=True)
        result = json.loads(output)
        results.append({"part": offer.get("oem_number"), "input_fitments": len(cars["fitments"]), "result": result})
    now = datetime.now(timezone.utc)
    h43, _ = read_table(svc, "43_Sync_Audit", "V")
    append_row(svc, "43_Sync_Audit", h43, {
        "Audit_ID": "AUD-KANO-FINALIZE-" + os.environ.get("GITHUB_RUN_ID", "LOCAL"),
        "Sync_Date": now.strftime("%Y-%m-%d"), "Sync_Time": now.strftime("%H:%M:%S UTC"),
        "Source_System": "GitHub Actions / Cars245", "Destination_System": "Google Sheets",
        "Entity_Type": "KANO review fitment evidence", "Operation": "Persist exact OEM evidence with review lock",
        "Source_Record_ID": "KANO-XMATCH-20261027", "Destination_Record_ID": "38,39,67",
        "Match_Key": "Current audited supplier/part/brand/cost",
        "Sync_Status": "Success", "Records_Read": len(allowed),
        "Records_Created": sum(x["result"].get("fitments_created", 0) for x in results),
        "Records_Updated": sum(x["result"].get("fitments_promoted", 0) for x in results),
        "Records_Skipped": 0, "Records_Failed": 0, "Executed_By": "GitHub Actions",
        "Batch_ID": os.environ.get("GITHUB_RUN_ID", "LOCAL"),
        "Validation_Status": "Candidate review lock retained; customer prices untouched",
        "Notes": json.dumps([{"part": x["part"], "fitments": x["input_fitments"]} for x in results], ensure_ascii=False)
    })
    Path("kano_finalize_report.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"processed_evidence_sets": len(results), "results": results}, ensure_ascii=False))

if __name__ == "__main__":
    main()
