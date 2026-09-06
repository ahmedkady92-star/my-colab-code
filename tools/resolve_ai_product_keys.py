#!/usr/bin/env python3
import argparse, json, os, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.upsert_verified_fitment import svc, read_table, batch_update_fields, norm

SPREADSHEET_ID = os.environ.get("ELKADY_SPREADSHEET_ID", "1A-8YoZkVIdelh2x3i7DmeFCERLeR1XREyEpK3Wrk6B0")


def valid_oem(v):
    n = norm(v)
    if len(n) < 7 or not any(c.isdigit() for c in n):
        return False
    if n.isdigit() and len(n) < 9:
        return False
    return True


def first_oem(v):
    for t in re.split(r"[;|,\n]+", str(v or "")):
        t = t.strip()
        if valid_oem(t):
            return t
    return ""


def index_by(rows, fields):
    out = {}
    for _, r in rows:
        for field in fields:
            key = str(r.get(field, "")).strip()
            if key:
                out.setdefault(key, r)
    return out


def source_candidate(r):
    if not r:
        return "", ""
    oem = first_oem(r.get("OEM_Number"))
    original = first_oem(r.get("Original_Part_Number"))
    if oem:
        return oem, "OEM_Number"
    if original:
        return original, "Original_Part_Number"
    return "", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--report", default="automation_output/ai_key_recovery_report.json")
    args = ap.parse_args()

    s = svc()
    h41, r41 = read_table(s, "41_AI_Product_Feed", "Y")
    _, r36 = read_table(s, "36_Supplier_Offers", "AG")
    _, r37 = read_table(s, "37_Supplier_Price_History", "V")
    _, r38 = read_table(s, "38_Product_Identifiers", "R")

    i36 = index_by(r36, ["Supplier_Offer_ID", "Product_ID"])
    i37 = index_by(r37, ["Product_ID", "Price_History_ID"])
    ids_by_product = {}
    for _, r in r38:
        pid = str(r.get("Product_ID", "")).strip()
        val = str(r.get("Original_Value", "")).strip()
        typ = str(r.get("Identifier_Type", "")).upper()
        if pid and valid_oem(val) and ("OEM" in typ or str(r.get("Is_Primary", "")).upper() == "TRUE"):
            ids_by_product.setdefault(pid, val)

    updates = []
    recovered = []
    unresolved = []
    existing = 0
    for rn, row in r41:
        if first_oem(row.get("OEM_Number")) or first_oem(row.get("Part_Number")):
            existing += 1
            continue
        ai_id = str(row.get("AI_Feed_ID", "")).strip()
        if not ai_id.startswith("AI-"):
            continue
        refs = [str(row.get("Source_Record_ID", "")).strip(), str(row.get("Product_ID", "")).strip()]
        refs = [x for x in refs if x]
        target = source = field = ""
        for ref in refs:
            cand, f = source_candidate(i36.get(ref))
            if cand:
                target, source, field = cand, "36_Supplier_Offers", f; break
            cand, f = source_candidate(i37.get(ref))
            if cand:
                target, source, field = cand, "37_Supplier_Price_History", f; break
            cand = ids_by_product.get(ref, "")
            if cand:
                target, source, field = cand, "38_Product_Identifiers", "Original_Value"; break
        if not target:
            unresolved.append({"row": rn, "ai_id": ai_id, "product_id": row.get("Product_ID", ""), "source_record_id": row.get("Source_Record_ID", "")})
            continue
        changes = {}
        if not str(row.get("Part_Number", "")).strip():
            changes["Part_Number"] = target
        if not str(row.get("OEM_Number", "")).strip():
            changes["OEM_Number"] = target
        old_notes = str(row.get("Notes", "")).strip()
        marker = f"AI key recovered by exact link from {source}.{field}: {target}"
        if marker not in old_notes:
            changes["Notes"] = (old_notes + " | " + marker).strip(" |")
        updates.append((rn, changes))
        recovered.append({"row": rn, "ai_id": ai_id, "target": target, "source": source, "field": field})

    if args.apply:
        batch_update_fields(s, "41_AI_Product_Feed", h41, updates, False)

    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    report = {
        "mode": "APPLY" if args.apply else "DRY_RUN",
        "ai_rows": len(r41), "already_keyed": existing,
        "recoverable": len(recovered), "written": len(recovered) if args.apply else 0,
        "unresolved": len(unresolved), "recovered": recovered, "unresolved_rows": unresolved[:100]
    }
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("recovered","unresolved_rows")}, ensure_ascii=False))

if __name__ == "__main__":
    main()
