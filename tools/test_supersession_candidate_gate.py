#!/usr/bin/env python3
import json, shutil, subprocess, sys
from pathlib import Path

CASES = [
    {"name":"front","part":"7L8 616 039 G","description":"مساعدين امامي / Front shock absorbers","cost":75000},
    {"name":"rear","part":"7L8 616 019 C","description":"مساعدين خلفي / Rear shock absorbers","cost":70000},
]

root = Path("candidate_gate_test_output")
shutil.rmtree(root, ignore_errors=True)
root.mkdir(parents=True, exist_ok=True)
summary = {}

for case in CASES:
    inp = root / f"{case['name']}.json"
    out = root / case["name"]
    inp.write_text(json.dumps({
        "supplier":"KANO",
        "supplier_id":"SUP-000002",
        "manufacturer_brand":"Lucas",
        "supplier_part_number":case["part"],
        "oem_number":case["part"],
        "part_description":case["description"],
        "supplier_cost":case["cost"],
        "currency":"EGP",
        "catalog_brand":"audi"
    }, ensure_ascii=False), encoding="utf-8")
    subprocess.run([sys.executable, "supplier_automation.py", "--input", str(inp), "--output-dir", str(out)], check=True)
    payload = json.loads((out / "import_payload.json").read_text(encoding="utf-8"))
    gate = payload["automation_gate"]
    cars = payload["cars245"]
    row = {
        "ai_eligible":gate.get("ai_eligible"),
        "verified_status":gate.get("verified_status"),
        "expected_family":gate.get("expected_family"),
        "validated_family":gate.get("validated_family"),
        "candidate_family":gate.get("candidate_family"),
        "exact_oem_pages":gate.get("exact_oem_pages"),
        "supersession_evidence":gate.get("supersession_evidence"),
        "evidence_types":gate.get("evidence_types"),
        "catalog_mapped_candidate":gate.get("catalog_mapped_candidate"),
        "fitment_rows_found":cars.get("fitment_rows_found"),
        "candidate_fitment_rows_found":cars.get("candidate_fitment_rows_found"),
        "alternatives_found":cars.get("alternatives_found"),
        "candidate_alternatives_found":cars.get("candidate_alternatives_found"),
        "review_reason":gate.get("review_reason"),
    }
    summary[case["part"]] = row
    assert gate.get("expected_family") == "shock-absorber"
    assert cars.get("allowed_product_family") in ("shock-absorber", "")
    if gate.get("ai_eligible"):
        assert int(gate.get("exact_oem_pages") or 0) > 0
        assert int(cars.get("fitment_rows_found") or 0) > 0
    else:
        # A non-verified Cars245 match may be retained only as a review-locked candidate.
        if gate.get("catalog_mapped_candidate"):
            assert gate.get("verified_status") == "Catalog Mapped - Review Required"
            assert cars.get("alternatives_found") == 0

(root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))
print("SUPERSESSION_CANDIDATE_GATE_OK")
