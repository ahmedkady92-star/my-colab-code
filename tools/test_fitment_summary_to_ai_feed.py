#!/usr/bin/env python3
# Lightweight regression for the expected AI summary semantics.
from collections import defaultdict

rows = [
    {"Vehicle_Make":"AUDI","Vehicle_Model":"Q7","Generation":"(4LB)","Year_From":"2006","Year_To":"2010","Engine_Code":"BAR","Fitment_Status":"Candidate - Review Required"},
    {"Vehicle_Make":"AUDI","Vehicle_Model":"Q7","Generation":"(4LB)","Year_From":"2007","Year_To":"2015","Engine_Code":"CASA","Fitment_Status":"Candidate - Review Required"},
    {"Vehicle_Make":"PORSCHE","Vehicle_Model":"CAYENNE","Generation":"(9PA)","Year_From":"2002","Year_To":"2010","Engine_Code":"M 48.51","Fitment_Status":"Candidate - Review Required"},
    {"Vehicle_Make":"VOLKSWAGEN","Vehicle_Model":"VW TOUAREG","Generation":"(7LA, 7L6, 7L7)","Year_From":"2002","Year_To":"2010","Engine_Code":"BKS","Fitment_Status":"Candidate - Review Required"},
]

groups = defaultdict(lambda: {"from": [], "to": []})
for r in rows:
    g = groups[(r["Vehicle_Make"], r["Vehicle_Model"], r["Generation"])]
    g["from"].append(int(r["Year_From"]))
    g["to"].append(int(r["Year_To"]))

summary = "; ".join(
    f"{make} {model} {gen} {min(v['from'])}-{max(v['to'])}"
    for (make, model, gen), v in groups.items()
)
assert "AUDI Q7 (4LB) 2006-2015" in summary
assert "PORSCHE CAYENNE (9PA) 2002-2010" in summary
assert "VOLKSWAGEN VW TOUAREG (7LA, 7L6, 7L7) 2002-2010" in summary
print("FITMENT_SUMMARY_OK", summary)
