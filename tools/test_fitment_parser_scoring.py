#!/usr/bin/env python3
from tools.upsert_verified_fitment import parse_fitment, clean_fitment_text
from tools.process_new_supplier_rows import score

porsche = {
    "vehicle_make": "PORSCHE",
    "fitment_text": "PORSCHE CAYENNE (9PA) M 48.51 Petrol 4.8 500hp 368kw 2007-2010 | Important notes: Spring Type: for vehicles with air suspension; Suspension: electronic | Additional info Manufacturer information JAPKO +39 000 Our customers also viewed: foo"
}
r = parse_fitment(porsche)
assert r["model"] == "CAYENNE", r
assert r["generation"] == "(9PA)", r
assert r["engine_code"] == "M 48.51", r
assert r["engine"] == "4.8", r
assert r["year_from"] == "2007" and r["year_to"] == "2010", r
assert "Manufacturer information" not in r["notes"], r["notes"]
assert len(r["notes"]) <= 900

vag = {
    "vehicle_make": "AUDI",
    "fitment_text": "AUDI Q7 (4LB) CASA Diesel 3.0 240hp 176kw 2007-2015"
}
r2 = parse_fitment(vag)
assert r2["model"] == "Q7", r2
assert r2["generation"] == "(4LB)", r2
assert r2["engine_code"] == "CASA", r2

candidate_payload = {
    "automation_gate": {"ai_eligible": False, "catalog_mapped_candidate": True},
    "cars245": {
        "candidate_fitment_rows_found": 10,
        "fitment_rows_found": 0,
        "product_links_found": 1,
        "strict_validation": {"candidate_pages": [{"url":"x"}]},
        "fitment_enrichment": {"exact_oem_urls": 0, "matched_search_part_urls": 0},
    },
}
broad_payload = {
    "automation_gate": {"ai_eligible": False, "catalog_mapped_candidate": False},
    "cars245": {
        "candidate_fitment_rows_found": 0,
        "fitment_rows_found": 0,
        "product_links_found": 50,
        "strict_validation": {"candidate_pages": []},
        "fitment_enrichment": {"exact_oem_urls": 0, "matched_search_part_urls": 3},
    },
}
assert score(candidate_payload) > score(broad_payload), (score(candidate_payload), score(broad_payload))
print("FITMENT_PARSER_SCORING_OK", r, score(candidate_payload), score(broad_payload))
