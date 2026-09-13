#!/usr/bin/env python3
"""Build non-destructive ELKADY CRM fitment, demand and purchase intelligence.

Dry-run is the default.  Source tabs are always read-only.  --apply replaces only
the five derived tabs created for this workflow (54 through 58).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path


SPREADSHEET_ID = os.environ.get(
    "ELKADY_SPREADSHEET_ID", "1A-8YoZkVIdelh2x3i7DmeFCERLeR1XREyEpK3Wrk6B0"
)

SOURCE_TABS = {
    "requests": ("08_Part_Requests", "AE"),
    "catalog": ("12_Product_Catalog", "V"),
    "offers": ("36_Supplier_Offers", "AG"),
    "identifiers": ("38_Product_Identifiers", "Q"),
    "fitments": ("39_Vehicle_Fitment", "U"),
    "inventory": ("40_Inventory", "AE"),
    "ai_feed": ("41_AI_Product_Feed", "X"),
}

OUTPUT_TABS = {
    "fitment_groups": "54_Fitment_Groups",
    "product_map": "55_Product_Fitment_Map",
    "demand": "56_Demand_Intelligence",
    "recommendations": "57_Purchase_Recommendations",
    "quality": "58_Data_Quality_Review",
}

HEADERS = {
    "fitment_groups": ["Fitment_Group_ID", "Primary_OEM", "Normalized_Primary_OEM", "Vehicle_Brand_Family", "Part_Category", "Group_Status", "Verification_Source", "Source_Record_ID", "Verified_Status", "Last_Checked_At", "Notes"],
    "product_map": ["Map_ID", "Product_ID", "Fitment_Group_ID", "Product_Brand", "Product_MPN", "Relationship_Type", "Mapping_Status", "Verification_Source", "Source_Record_ID", "Last_Checked_At", "Notes"],
    "demand": ["Demand_Key", "Fitment_Group_ID", "Product_ID", "Part_Description", "Request_Count_30D", "Request_Count_90D", "Distinct_Customers_90D", "Distinct_Request_Dates_90D", "Requested_Qty_90D", "Confirmed_Count_90D", "Sold_Count_90D", "Lost_No_Stock_90D", "Website_No_Result_90D", "Demand_Score", "Demand_Class", "Last_Request_Date", "Match_Status", "Notes", "Last_Refresh"],
    "recommendations": ["Recommendation_ID", "Demand_Key", "Fitment_Group_ID", "Product_ID", "Part_Description", "Demand_Class", "Demand_Score", "Available_Qty", "Reserved_Qty", "Incoming_Qty", "Supplier_Offer_Count", "Best_Supplier", "Latest_Cost_EGP", "Supplier_Lead_Time_Days", "Suggested_Reorder_Qty", "Recommendation_Reason", "Decision_Status", "Owner_Approval", "Last_Refresh", "Notes"],
    "quality": ["Issue_ID", "Entity_Type", "Entity_ID", "Field_Name", "Issue_Type", "Severity", "Current_Value", "Candidate_Value", "Source", "Detected_At", "Issue_Status", "Resolution_Notes"],
}


def norm(value):
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def normalize_text(value):
    text = str(value or "").strip().lower()
    text = text.translate(str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"}))
    text = re.sub(r"[^0-9a-z\u0600-\u06ff]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def unusable_description(value):
    text = normalize_text(value)
    placeholders = {"طلب بدون وصف قطعه", "بدون وصف قطعه", "غير محدد", "غير معروف", "unknown", "n a", "na"}
    return not text or text in placeholders


def stable_id(prefix, *parts):
    raw = "|".join(str(x or "") for x in parts)
    return f"{prefix}-{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:12].upper()}"


def number(value, default=0.0):
    try:
        return float(str(value).replace(",", "").strip())
    except Exception:
        return default


def parse_date(value):
    if isinstance(value, (int, float)):
        return date(1899, 12, 30) + timedelta(days=int(value))
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    return None


def split_refs(value):
    return [x.strip() for x in re.split(r"[;|,\n]+", str(value or "")) if norm(x)]


def row_dicts(values):
    if not values:
        return []
    headers = values[0]
    return [dict(zip(headers, row + [""] * (len(headers) - len(row)))) for row in values[1:] if any(str(x).strip() for x in row)]


def col_letter(n):
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def preserve_manual_fields(current_rows, generated_rows, key_field, fields):
    current = {str(r.get(key_field, "")): r for r in current_rows if str(r.get(key_field, ""))}
    for row in generated_rows:
        old = current.get(str(row.get(key_field, "")), {})
        for field in fields:
            if str(old.get(field, "")).strip():
                row[field] = old[field]
    return generated_rows


def issue(entity_type, entity_id, field, kind, severity, current, candidate, source, today, note=""):
    return {
        "Issue_ID": stable_id("DQ", entity_type, entity_id, field, kind, current),
        "Entity_Type": entity_type,
        "Entity_ID": entity_id,
        "Field_Name": field,
        "Issue_Type": kind,
        "Severity": severity,
        "Current_Value": current,
        "Candidate_Value": candidate,
        "Source": source,
        "Detected_At": today.isoformat(),
        "Issue_Status": "Open",
        "Resolution_Notes": note,
    }


def build_intelligence(data, today=None):
    today = today or date.today()
    identifiers = data.get("identifiers", [])
    catalog = data.get("catalog", [])
    requests = data.get("requests", [])
    offers = data.get("offers", [])
    fitments = data.get("fitments", [])
    inventory = data.get("inventory", [])
    ai_feed = data.get("ai_feed", [])
    quality = []

    # Verified primary OEMs define groups. Cross-references never merge two groups silently.
    primary_by_product = defaultdict(set)
    primary_rows = []
    for r in identifiers:
        typ = str(r.get("Identifier_Type", "")).upper()
        status = str(r.get("Verified_Status", "")).upper()
        key = norm(r.get("Normalized_Value") or r.get("Original_Value"))
        if key and "OEM" in typ and "CROSS" not in typ and status.startswith("VERIFIED"):
            primary_by_product[str(r.get("Product_ID", "")).strip()].add(key)
            primary_rows.append((key, r))

    group_for_primary = {key: stable_id("FG", key) for key, _ in primary_rows}
    identifier_groups = defaultdict(set)
    product_groups = defaultdict(set)
    group_meta = {}

    for key, r in primary_rows:
        gid = group_for_primary[key]
        identifier_groups[key].add(gid)
        pid = str(r.get("Product_ID", "")).strip()
        if pid:
            product_groups[pid].add(gid)
        group_meta.setdefault(gid, {
            "Fitment_Group_ID": gid,
            "Primary_OEM": str(r.get("Original_Value") or key).strip(),
            "Normalized_Primary_OEM": key,
            "Vehicle_Brand_Family": str(r.get("Brand", "")).strip(),
            "Part_Category": "",
            "Group_Status": "Active",
            "Verification_Source": str(r.get("Source_Type", "")).strip(),
            "Source_Record_ID": str(r.get("Source_Record_ID", "")).strip(),
            "Verified_Status": "Verified",
            "Last_Checked_At": str(r.get("Last_Checked_At") or today.isoformat()),
            "Notes": "Generated from verified primary OEM; source data preserved",
        })

    for r in identifiers:
        typ = str(r.get("Identifier_Type", "")).upper()
        status = str(r.get("Verified_Status", "")).upper()
        key = norm(r.get("Normalized_Value") or r.get("Original_Value"))
        pid = str(r.get("Product_ID", "")).strip()
        if not key or not status.startswith("VERIFIED") or "CROSS" not in typ:
            continue
        groups = product_groups.get(pid, set())
        if len(groups) == 1:
            identifier_groups[key].update(groups)
        elif len(groups) > 1:
            quality.append(issue("Identifier", r.get("Identifier_ID"), "Normalized_Value", "Ambiguous verified cross-reference", "High", key, "Manual group selection", "38_Product_Identifiers", today, "Cross-reference belongs to a product with multiple primary OEM groups; no automatic merge"))

    for key, groups in identifier_groups.items():
        if len(groups) > 1:
            quality.append(issue("Identifier", key, "Normalized_Value", "Identifier maps to multiple fitment groups", "Critical", key, ";".join(sorted(groups)), "38_Product_Identifiers", today, "Do not auto-select the first Product_ID"))

    product_map = {}
    catalog_by_product = {}
    for r in catalog:
        pid = str(r.get("Product_ID", "")).strip()
        if not pid:
            continue
        catalog_by_product[pid] = r
        refs = split_refs(r.get("OEM_Number")) + split_refs(r.get("Part_Number"))
        matched = set()
        ambiguous = set()
        for ref in refs:
            groups = identifier_groups.get(norm(ref), set())
            if len(groups) == 1:
                matched.update(groups)
            elif len(groups) > 1:
                ambiguous.update(groups)
        if ambiguous:
            quality.append(issue("Product", pid, "OEM_Number", "Ambiguous product-to-fitment mapping", "Critical", r.get("OEM_Number", ""), ";".join(sorted(ambiguous)), "12_Product_Catalog", today))
        for gid in sorted(matched):
            map_id = stable_id("PFM", pid, gid)
            product_type = str(r.get("Product_Type", "")).upper()
            product_brand = str(r.get("Brand", "")).upper()
            product_map[map_id] = {
                "Map_ID": map_id,
                "Product_ID": pid,
                "Fitment_Group_ID": gid,
                "Product_Brand": str(r.get("Brand", "")).strip(),
                "Product_MPN": str(r.get("Part_Number") or r.get("OEM_Number") or "").strip(),
                "Relationship_Type": "OEM" if product_type in {"OEM", "ORIGINAL", "GENUINE"} or product_brand in {"ORIGINAL", "OEM", "GENUINE"} else "Aftermarket equivalent",
                "Mapping_Status": "Verified",
                "Verification_Source": "38_Product_Identifiers",
                "Source_Record_ID": pid,
                "Last_Checked_At": today.isoformat(),
                "Notes": "Many-to-many map; product price, brand and inventory remain separate",
            }
            product_groups[pid].add(gid)
            if not group_meta[gid]["Part_Category"]:
                group_meta[gid]["Part_Category"] = str(r.get("Category", "")).strip()

    # Keep canonical identifier Product_ID links too, but never mistake offer IDs for products.
    for pid, groups in product_groups.items():
        if not pid or pid.startswith("OFF-"):
            continue
        for gid in groups:
            map_id = stable_id("PFM", pid, gid)
            if map_id not in product_map:
                product_map[map_id] = {
                    "Map_ID": map_id, "Product_ID": pid, "Fitment_Group_ID": gid,
                    "Product_Brand": "", "Product_MPN": group_meta[gid]["Primary_OEM"],
                    "Relationship_Type": "Canonical identifier", "Mapping_Status": "Verified",
                    "Verification_Source": "38_Product_Identifiers", "Source_Record_ID": pid,
                    "Last_Checked_At": today.isoformat(), "Notes": "Compatibility identity; not assumed to be a sellable SKU",
                }

    # Data-quality checks preserve rows and only create review findings.
    for r in offers:
        oid = str(r.get("Supplier_Offer_ID", "")).strip()
        pid = str(r.get("Product_ID", "")).strip()
        refs = split_refs(r.get("OEM_Number")) + split_refs(r.get("Original_Part_Number"))
        candidate_groups = {g for ref in refs for g in identifier_groups.get(norm(ref), set())}
        candidate = ";".join(sorted(candidate_groups)) if len(candidate_groups) == 1 else "Review Required"
        if not pid:
            quality.append(issue("Supplier Offer", oid, "Product_ID", "Missing sellable Product_ID", "Medium", "", candidate, "36_Supplier_Offers", today, "Offer history is valid; link only after brand/MPN review"))
        elif pid.startswith("OFF-"):
            quality.append(issue("Supplier Offer", oid, "Product_ID", "Supplier_Offer_ID stored as Product_ID", "High", pid, candidate, "36_Supplier_Offers", today))

    for r in ai_feed:
        fid = str(r.get("AI_Feed_ID", "")).strip()
        pid = str(r.get("Product_ID", "")).strip()
        if not pid or pid.startswith("OFF-"):
            quality.append(issue("AI Feed", fid, "Product_ID", "AI feed lacks sellable Product_ID", "High", pid, "Review Required", "41_AI_Product_Feed", today, "AI must not publish conflicted or unconfirmed linkage"))

    fitment_seen = defaultdict(list)
    for r in fitments:
        relation = (
            str(r.get("Product_ID", "")).strip(), norm(r.get("Vehicle_Make")), norm(r.get("Vehicle_Model")),
            norm(r.get("Generation")), str(r.get("Year_From", "")), str(r.get("Year_To", "")),
            norm(r.get("Engine")), norm(r.get("Engine_Code")), norm(r.get("PR_Code")),
        )
        fitment_seen[relation].append(str(r.get("Fitment_ID", "")).strip())
    for relation, ids in fitment_seen.items():
        if relation[0] and len(ids) > 1:
            quality.append(issue("Vehicle Fitment", ids[0], "Exact_Relation_Key", "Exact technical fitment repeated", "Medium", str(len(ids)), "Keep one active relation after manual review", "39_Vehicle_Fitment", today, "Same part and same vehicle/engine/year/PR relation; no rows deleted"))

    inventory_by_product = defaultdict(lambda: {"available": 0.0, "reserved": 0.0})
    inventory_by_key = defaultdict(lambda: {"available": 0.0, "reserved": 0.0})
    for r in inventory:
        pid = str(r.get("Product_ID", "")).strip()
        key = norm(r.get("Part_Number"))
        vals = {"available": number(r.get("Available_Qty")), "reserved": number(r.get("Reserved_Qty"))}
        if pid:
            inventory_by_product[pid]["available"] += vals["available"]
            inventory_by_product[pid]["reserved"] += vals["reserved"]
        if key:
            inventory_by_key[key]["available"] += vals["available"]
            inventory_by_key[key]["reserved"] += vals["reserved"]

    offers_by_key = defaultdict(list)
    for r in offers:
        keys = {norm(x) for x in split_refs(r.get("OEM_Number")) + split_refs(r.get("Original_Part_Number"))}
        for key in keys:
            offers_by_key[key].append(r)

    demand_events = defaultdict(list)
    seen_request_ids = set()
    seen_demand_fingerprints = set()
    for r in requests:
        rid = str(r.get("Request_ID", "")).strip()
        if rid and rid in seen_request_ids:
            quality.append(issue("Part Request", rid, "Request_ID", "Duplicate Request_ID", "High", rid, "Keep separate only if assigned a new Request_ID", "08_Part_Requests", today))
            continue
        if rid:
            seen_request_ids.add(rid)
        exact_key = norm(r.get("OEM_Reference_Number") or r.get("Part_Number"))
        description_key = normalize_text(r.get("Requested_Part"))
        if not exact_key and unusable_description(r.get("Requested_Part")):
            quality.append(issue("Part Request", rid, "Requested_Part", "Unusable request description", "Medium", r.get("Requested_Part", ""), "Add part name and Part Number/VIN when available", "08_Part_Requests", today, "Excluded from demand score; source row preserved"))
            continue
        key = exact_key or (stable_id("TXT", description_key) if len(description_key) >= 4 else "")
        if not key:
            continue
        request_date = parse_date(r.get("Date_Created"))
        customer = str(r.get("Customer_ID", "")).strip()
        fingerprint = (key, customer or rid, request_date.isoformat() if request_date else str(r.get("Date_Created", "")))
        if fingerprint in seen_demand_fingerprints:
            quality.append(issue("Part Request", rid, "Demand_Event", "Potential duplicate demand event", "Medium", str(fingerprint), "Count once; preserve source row", "08_Part_Requests", today, "Same part/customer/date does not inflate demand"))
            continue
        seen_demand_fingerprints.add(fingerprint)
        demand_events[key].append(r)

    demand_rows = []
    recommendations = []
    for key, events in demand_events.items():
        recent30, recent90 = [], []
        score = 0.0
        for r in events:
            d = parse_date(r.get("Date_Created"))
            age = (today - d).days if d else 99999
            if age <= 30:
                recent30.append(r)
            if age <= 90:
                recent90.append(r)
            status = (str(r.get("Customer_Intent", "")) + "|" + str(r.get("Request_Status", ""))).upper()
            availability = str(r.get("Part_Availability", "")).upper()
            notes = str(r.get("Notes", "")).upper()
            lost_no_stock = "LOST" in status and ("UNAVAILABLE" in availability or "NO STOCK" in notes or "غير متوفر" in notes)
            base = 5 if "SOLD" in status else 4 if "CONFIRMED" in status else 3 if lost_no_stock else 2 if "PURCHASE PLANNED" in status else 1
            multiplier = 1.5 if age <= 30 else 1.0 if age <= 90 else 0.5
            score += base * multiplier

        dates90 = {parse_date(r.get("Date_Created")) for r in recent90 if parse_date(r.get("Date_Created"))}
        customers90 = {str(r.get("Customer_ID", "")).strip() for r in recent90 if str(r.get("Customer_ID", "")).strip()}
        qty90 = sum(max(1.0, number(r.get("Quantity"), 1.0)) for r in recent90)
        confirmed90 = sum(bool(re.search(r"CONFIRMED|SOLD", (str(r.get("Customer_Intent", "")) + "|" + str(r.get("Request_Status", ""))).upper())) for r in recent90)
        sold90 = sum("SOLD" in (str(r.get("Customer_Intent", "")) + "|" + str(r.get("Request_Status", ""))).upper() for r in recent90)
        lost90 = sum("LOST" in str(r.get("Request_Status", "")).upper() and ("UNAVAILABLE" in str(r.get("Part_Availability", "")).upper() or "NO STOCK" in str(r.get("Notes", "")).upper() or "غير متوفر" in str(r.get("Notes", ""))) for r in recent90)
        no_result90 = sum(str(r.get("Source", "")).upper() == "WEBSITE" and ("UNAVAILABLE" in str(r.get("Part_Availability", "")).upper() or "NO RESULT" in str(r.get("Notes", "")).upper() or "لم نجد" in str(r.get("Notes", ""))) for r in recent90)
        text_only = key.startswith("TXT-")
        groups = set() if text_only else identifier_groups.get(key, set())
        gid = next(iter(groups)) if len(groups) == 1 else ""
        match_status = "Matched" if len(groups) == 1 else "Conflict" if len(groups) > 1 else "Review Required" if text_only else "Unmatched"
        pids = sorted(pid for pid, gs in product_groups.items() if gid and gid in gs and pid in catalog_by_product)
        pid = pids[0] if len(pids) == 1 else ""
        stock = inventory_by_key[key].copy()
        if gid:
            for mapped_pid in pids:
                stock["available"] += inventory_by_product[mapped_pid]["available"]
                stock["reserved"] += inventory_by_product[mapped_pid]["reserved"]
        if (len(recent90) >= 3 and len(dates90) >= 2 and stock["available"] <= 0) or confirmed90 > stock["available"]:
            demand_class = "Purchase Priority"
        elif (len(recent90) >= 5 or sold90 >= 3) and len(dates90) >= 2:
            demand_class = "High Demand"
        elif (len(recent90) >= 3 or qty90 >= 3) and len(dates90) >= 2:
            demand_class = "Important"
        elif len(recent90) >= 2 and len(dates90) >= 2:
            demand_class = "Monitor"
        else:
            demand_class = "Normal"
        description = next((str(r.get("Requested_Part", "")).strip() for r in reversed(events) if str(r.get("Requested_Part", "")).strip()), "")
        last_date = max((parse_date(r.get("Date_Created")) for r in events if parse_date(r.get("Date_Created"))), default=None)
        demand_rows.append({
            "Demand_Key": key, "Fitment_Group_ID": gid, "Product_ID": pid, "Part_Description": description,
            "Request_Count_30D": len(recent30), "Request_Count_90D": len(recent90),
            "Distinct_Customers_90D": len(customers90), "Distinct_Request_Dates_90D": len(dates90),
            "Requested_Qty_90D": qty90, "Confirmed_Count_90D": confirmed90, "Sold_Count_90D": sold90,
            "Lost_No_Stock_90D": lost90, "Website_No_Result_90D": no_result90, "Demand_Score": round(score, 2),
            "Demand_Class": demand_class, "Last_Request_Date": last_date.isoformat() if last_date else "",
            "Match_Status": match_status,
            "Notes": "Text-only demand; Part Number/VIN required before purchasing" if text_only else "Multiple sellable alternatives" if len(pids) > 1 else ("Exact OEM/part key is not mapped yet" if not gid else ""),
            "Last_Refresh": today.isoformat(),
        })

        eligible_offers = [o for o in offers_by_key.get(key, []) if str(o.get("Currency", "")).upper() == "EGP" and str(o.get("Verified_Status", "")).upper().startswith(("CONFIRMED", "VERIFIED"))]
        eligible_offers.sort(key=lambda o: (number(o.get("Supplier_Cost"), 10**15), str(o.get("Offer_Date", ""))))
        best = eligible_offers[0] if eligible_offers else {}
        weekly = qty90 / 13.0
        target = math.ceil(weekly * 4 + (1 if demand_class in {"Important", "High Demand", "Purchase Priority"} else 0))
        suggested = 0 if text_only else max(0, target - int(stock["available"]))
        if demand_class in {"Important", "High Demand", "Purchase Priority"}:
            recommendations.append({
                "Recommendation_ID": stable_id("REC", key, today.isoformat()), "Demand_Key": key,
                "Fitment_Group_ID": gid, "Product_ID": pid, "Part_Description": description,
                "Demand_Class": demand_class, "Demand_Score": round(score, 2),
                "Available_Qty": stock["available"], "Reserved_Qty": stock["reserved"], "Incoming_Qty": 0,
                "Supplier_Offer_Count": len(eligible_offers), "Best_Supplier": str(best.get("Supplier_Name", "")),
                "Latest_Cost_EGP": number(best.get("Supplier_Cost"), "") if best else "",
                "Supplier_Lead_Time_Days": "", "Suggested_Reorder_Qty": suggested,
                "Recommendation_Reason": (f"{len(recent90)} requests / {len(dates90)} distinct dates; obtain Part Number/VIN before purchase" if text_only else f"{len(recent90)} requests / {len(dates90)} distinct dates / stock {stock['available']:g}"),
                "Decision_Status": "Review", "Owner_Approval": "Pending Review", "Last_Refresh": today.isoformat(),
                "Notes": "Recommendation only; confirm VIN, current supplier availability and cost before purchase",
            })

    demand_rows.sort(key=lambda r: (-r["Demand_Score"], r["Demand_Key"]))
    recommendations.sort(key=lambda r: (-r["Demand_Score"], r["Demand_Key"]))
    quality.sort(key=lambda r: ({"Critical": 0, "High": 1, "Medium": 2}.get(r["Severity"], 3), r["Issue_ID"]))
    return {
        "fitment_groups": list(group_meta.values()),
        "product_map": list(product_map.values()),
        "demand": demand_rows,
        "recommendations": recommendations,
        "quality": quality,
    }


def sheets_service():
    import google.auth
    from googleapiclient.discovery import build
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/spreadsheets"])
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def read_sources(service):
    out = {}
    for key, (tab, end_col) in SOURCE_TABS.items():
        values = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'!A1:{end_col}").execute(num_retries=5).get("values", [])
        out[key] = row_dicts(values)
    return out


def write_outputs(service, outputs):
    # Only derived tabs are replaced. Source/history tabs are never changed.
    preserve = {
        "fitment_groups": ("Fitment_Group_ID", ["Group_Status", "Notes"]),
        "product_map": ("Map_ID", ["Mapping_Status", "Notes"]),
        "recommendations": ("Recommendation_ID", ["Decision_Status", "Owner_Approval", "Notes"]),
        "quality": ("Issue_ID", ["Issue_Status", "Resolution_Notes"]),
    }
    for key, (id_field, fields) in preserve.items():
        tab = OUTPUT_TABS[key]
        last = col_letter(len(HEADERS[key]))
        existing = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'!A1:{last}").execute(num_retries=5).get("values", [])
        preserve_manual_fields(row_dicts(existing), outputs[key], id_field, fields)

    meta = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID, fields="sheets.properties").execute(num_retries=5)
    props = {s["properties"]["title"]: s["properties"] for s in meta.get("sheets", [])}
    resize = []
    for key, tab in OUTPUT_TABS.items():
        needed = len(outputs[key]) + 1
        current = int(props[tab]["gridProperties"]["rowCount"])
        if needed > current:
            resize.append({"appendDimension": {"sheetId": props[tab]["sheetId"], "dimension": "ROWS", "length": needed - current}})
    if resize:
        service.spreadsheets().batchUpdate(spreadsheetId=SPREADSHEET_ID, body={"requests": resize}).execute(num_retries=5)

    body = {"valueInputOption": "RAW", "data": []}
    for key, tab in OUTPUT_TABS.items():
        headers = HEADERS[key]
        last = col_letter(len(headers))
        service.spreadsheets().values().clear(spreadsheetId=SPREADSHEET_ID, range=f"'{tab}'!A2:{last}", body={}).execute(num_retries=5)
        rows = [[r.get(h, "") for h in headers] for r in outputs[key]]
        if rows:
            body["data"].append({"range": f"'{tab}'!A2", "values": rows})
    if body["data"]:
        service.spreadsheets().values().batchUpdate(spreadsheetId=SPREADSHEET_ID, body=body).execute(num_retries=5)


def main():
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Read and report only (default)")
    mode.add_argument("--apply", action="store_true", help="Write only derived tabs 54-58")
    ap.add_argument("--output-dir", default="crm_intelligence_output")
    args = ap.parse_args()
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    service = sheets_service()
    outputs = build_intelligence(read_sources(service))
    if args.apply:
        write_outputs(service, outputs)
    summary = {k: len(v) for k, v in outputs.items()}
    summary["mode"] = "APPLY_DERIVED_ONLY" if args.apply else "DRY_RUN_READ_ONLY"
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    for key, rows in outputs.items():
        (out_dir / f"{key}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
