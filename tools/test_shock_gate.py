#!/usr/bin/env python3
import json, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import supplier_automation

CASES = [
    {"name":"front","supplier":"KANO","supplier_id":"SUP-000002","manufacturer_brand":"Lucas","supplier_part_number":"7L8 616 039 G","oem_number":"7L8 616 039 G","part_description":"مساعدين امامي / Front shock absorbers","supplier_cost":75000,"currency":"EGP"},
    {"name":"rear","supplier":"KANO","supplier_id":"SUP-000002","manufacturer_brand":"Lucas","supplier_part_number":"7L8 616 019 C","oem_number":"7L8 616 019 C","part_description":"مساعدين خلفي / Rear shock absorbers","supplier_cost":70000,"currency":"EGP"},
]
BRANDS = ["audi","volkswagen","porsche","skoda","seat","cupra","bentley","landrover"]


def run_case(case):
    root = Path("shock_gate_test_output") / case["name"]
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    attempts=[]
    for brand in BRANDS:
        data=dict(case, catalog_brand=brand)
        ip=root/f"{brand}.json"; out=root/brand
        ip.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        old=sys.argv[:]
        try:
            sys.argv=["supplier_automation.py","--input",str(ip),"--output-dir",str(out)]
            supplier_automation.main()
            payload=json.loads((out/"import_payload.json").read_text(encoding="utf-8"))
            gate=payload.get("automation_gate",{})
            cars=payload.get("cars245",{})
            attempts.append({
                "brand":brand,
                "ai_eligible":gate.get("ai_eligible"),
                "expected_family":gate.get("expected_family"),
                "validated_family":gate.get("validated_family"),
                "family_match":gate.get("family_match"),
                "exact_oem_pages":gate.get("exact_oem_pages"),
                "fitment_rows":cars.get("fitment_rows_found"),
                "review_reason":gate.get("review_reason"),
            })
        except Exception as exc:
            attempts.append({"brand":brand,"error":str(exc)[:200]})
        finally:
            sys.argv=old
    return attempts


def main():
    result={case["oem_number"]:run_case(case) for case in CASES}
    Path("shock_gate_test_output/summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    for attempts in result.values():
        for a in attempts:
            if a.get("ai_eligible"):
                assert a.get("validated_family")=="shock-absorber"
                assert a.get("expected_family")=="shock-absorber"
                assert a.get("family_match") is True
                assert int(a.get("exact_oem_pages") or 0)>0
                assert int(a.get("fitment_rows") or 0)>0
    print("SHOCK_GATE_REGRESSION_OK")

if __name__=="__main__": main()
