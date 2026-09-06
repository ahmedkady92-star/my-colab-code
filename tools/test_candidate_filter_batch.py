#!/usr/bin/env python3
import json, shutil, subprocess, sys
from pathlib import Path

cases=[
 ("front","7L8 616 039 G","مساعدين امامي / Front shock absorbers",75000),
 ("rear","7L8 616 019 C","مساعدين خلفي / Rear shock absorbers",70000),
]
root=Path("candidate_filter_test_output")
shutil.rmtree(root,ignore_errors=True); root.mkdir(parents=True)
summary={}
for name,part,desc,cost in cases:
    inp=root/f"{name}.json"; out=root/name
    inp.write_text(json.dumps({"supplier":"KANO","supplier_id":"SUP-000002","manufacturer_brand":"Lucas","supplier_part_number":part,"oem_number":part,"part_description":desc,"supplier_cost":cost,"currency":"EGP","catalog_brand":"audi"},ensure_ascii=False),encoding="utf-8")
    subprocess.run([sys.executable,"supplier_automation.py","--input",str(inp),"--output-dir",str(out)],check=True)
    p=json.loads((out/"import_payload.json").read_text(encoding="utf-8"))
    g=p["automation_gate"]; c=p["cars245"]
    summary[part]={"ai_eligible":g.get("ai_eligible"),"status":g.get("verified_status"),"candidate_pages":len(c.get("strict_validation",{}).get("candidate_pages",[])),"candidate_fitments":c.get("candidate_fitment_rows_found"),"candidate_alternatives":c.get("candidate_alternatives_found"),"safe_fitments":c.get("fitment_rows_found"),"safe_alternatives":c.get("alternatives_found")}
    assert g.get("expected_family")=="shock-absorber"
    assert g.get("ai_eligible") is False
    assert c.get("alternatives_found")==0
    if g.get("catalog_mapped_candidate"):
        assert c.get("candidate_fitment_rows_found",0)>0
        # unrelated Land Rover rows must not survive for these VW/Audi OEM searches
        assert not any(str(x.get("vehicle_make","")).upper()=="LAND ROVER" for x in c.get("candidate_fitments",[]))
(root/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(summary,ensure_ascii=False,indent=2))
print("CANDIDATE_FILTER_BATCH_OK")
