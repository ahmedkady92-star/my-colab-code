#!/usr/bin/env python3
"""Sync Cars245 research results into ELKADY AUTO CRM Knowledge Base.

Designed for Google Colab. Authentication uses the signed-in Google account
via google.colab.auth.authenticate_user(). No service-account secrets are
stored in GitHub.

Writes to:
- 38_Product_Identifiers
- 39_Vehicle_Fitment
- 41_AI_Product_Feed

Safety rules:
- Never overwrite supplier/customer prices.
- Existing AI customer price is preserved.
- New products are AI_Eligible=FALSE until a trusted price/fitment is confirmed.
- Ambiguous compatibility is stored as conditional/needs verification.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Iterable

import pandas as pd

SPREADSHEET_ID = "1A-8YoZkVIdelh2x3i7DmeFCERLeR1XREyEpK3Wrk6B0"
IDENTIFIERS_SHEET = "38_Product_Identifiers"
FITMENT_SHEET = "39_Vehicle_Fitment"
AI_FEED_SHEET = "41_AI_Product_Feed"


def _today() -> str:
    return dt.date.today().isoformat()


def normalize_part(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def canonical_part(value: str) -> str:
    return re.sub(r"\s+", " ", str(value).strip()).upper()


def _split_pipe(value: str) -> list[str]:
    out: list[str] = []
    for item in re.split(r"\s*\|\s*|\s*;\s*|\s*,\s*", str(value or "")):
        item = item.strip()
        if item and item not in out:
            out.append(item)
    return out


def _stable_id(prefix: str, *parts: str, length: int = 12) -> str:
    raw = "|".join(str(p) for p in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length].upper()
    return f"{prefix}-{digest}"


def _auth_service():
    try:
        from google.colab import auth  # type: ignore
        auth.authenticate_user()
    except ImportError:
        pass

    import google.auth
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds, _ = google.auth.default(scopes=scopes)
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _read_values(service, sheet_name: str) -> list[list[str]]:
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{sheet_name}'!A:Z",
    ).execute()
    return result.get("values", [])


def _rows_as_dicts(values: list[list[str]]) -> tuple[list[str], list[dict[str, str]]]:
    if not values:
        return [], []
    headers = values[0]
    rows = []
    for raw in values[1:]:
        padded = raw + [""] * (len(headers) - len(raw))
        rows.append(dict(zip(headers, padded[: len(headers)])))
    return headers, rows


def _append_dicts(service, sheet_name: str, headers: list[str], rows: Iterable[dict[str, object]]) -> int:
    payload = []
    for row in rows:
        payload.append([row.get(h, "") for h in headers])
    if not payload:
        return 0
    service.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{sheet_name}'!A1",
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": payload},
    ).execute()
    return len(payload)


def _update_row(service, sheet_name: str, row_number: int, headers: list[str], row: dict[str, object]) -> None:
    values = [[row.get(h, "") for h in headers]]
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{sheet_name}'!A{row_number}:{_column_letter(len(headers))}{row_number}",
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()


def _column_letter(n: int) -> str:
    result = ""
    while n:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _extract_years(text: str) -> tuple[str, str]:
    years = [int(x) for x in re.findall(r"\b(19\d{2}|20\d{2})\b", text)]
    if not years:
        return "", ""
    return str(min(years)), str(max(years))


def _extract_engine(text: str) -> str:
    matches = re.findall(r"\b(?:[1-8](?:\.\d)?\s*(?:TDI|TFSI|TSI|FSI|V6|V8|V10|V12)|\d{3,4}\s*cc)\b", text, flags=re.I)
    unique = []
    for m in matches:
        m = re.sub(r"\s+", " ", m.strip())
        if m not in unique:
            unique.append(m)
    return "; ".join(unique[:12])


def _extract_generation(text: str) -> str:
    gens = re.findall(r"\b(?:B[5-9]|C[4-9]|D[2-5]|8K|8W|4F|4G|4K|4M|FY|95B|958|9Y0|CR7|RC8)\b", text, flags=re.I)
    out = []
    for g in gens:
        g = g.upper()
        if g not in out:
            out.append(g)
    return "; ".join(out[:8])


def _guess_models(text: str) -> list[str]:
    patterns = [
        r"\bA[1-8]\b", r"\bQ[2-8]\b", r"\bRS\s?Q?\d\b", r"\bS[1-8]\b",
        r"\bTouareg\b", r"\bAmarok\b", r"\bCrafter\b", r"\bPhaeton\b",
        r"\bCayenne\b", r"\bMacan\b", r"\bPanamera\b",
        r"\bTiguan\b", r"\bPassat\b", r"\bGolf\b", r"\bJetta\b",
    ]
    out: list[str] = []
    for pattern in patterns:
        for m in re.findall(pattern, text, flags=re.I):
            value = re.sub(r"\s+", " ", str(m).upper()).strip()
            if value and value not in out:
                out.append(value)
    return out


def _identifier_rows(clean_df: pd.DataFrame, product_id: str) -> list[dict[str, object]]:
    candidates: dict[str, str] = {}
    candidates[normalize_part(product_id)] = canonical_part(product_id)
    for _, row in clean_df.iterrows():
        for value in _split_pipe(row.get("part_numbers", "")):
            norm = normalize_part(value)
            if len(norm) >= 5:
                candidates.setdefault(norm, canonical_part(value))

    rows = []
    primary_norm = normalize_part(product_id)
    for norm, original in candidates.items():
        primary = norm == primary_norm
        rows.append({
            "Identifier_ID": _stable_id("ID", product_id, norm),
            "Product_ID": product_id,
            "Identifier_Type": "OEM" if primary else "OEM Cross-Reference",
            "Original_Value": original,
            "Normalized_Value": norm,
            "Brand": "",
            "Source_Type": "Cars245",
            "Source_Record_ID": product_id,
            "Source_File": "Cars245 scraper",
            "Source_Message_ID": "",
            "Verified_Status": "Cars245 Source" if primary else "Cars245 Cross-Reference - review",
            "Extraction_Confidence": "High" if primary else "Medium",
            "Is_Primary": "TRUE" if primary else "FALSE",
            "Valid_From": "",
            "Valid_Until": "",
            "Last_Checked_At": _today(),
            "Notes": "Auto-synced from Cars245; cross-reference should be confirmed before final sale",
        })
    return rows


def _fitment_rows(clean_df: pd.DataFrame, product_id: str) -> list[dict[str, object]]:
    make_aliases = {
        "AUDI": "AUDI", "VOLKSWAGEN": "VOLKSWAGEN", "VW": "VOLKSWAGEN",
        "SKODA": "SKODA", "SEAT": "SEAT", "PORSCHE": "PORSCHE",
        "BENTLEY": "BENTLEY", "BMW": "BMW", "LAND ROVER": "LAND ROVER",
        "JAGUAR": "JAGUAR",
    }
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for _, record in clean_df.iterrows():
        text = " | ".join(str(record.get(c, "")) for c in [
            "compatibility", "tables", "detected_vehicles", "product_name", "oe_alternative"
        ])
        year_from, year_to = _extract_years(text)
        engine = _extract_engine(text)
        generation = _extract_generation(text)
        models = _guess_models(text) or ["Multiple / not parsed"]
        detected_makes = _split_pipe(record.get("detected_vehicles", ""))
        makes = []
        for raw_make in detected_makes:
            make = make_aliases.get(raw_make.upper(), raw_make.upper())
            if make and make not in makes:
                makes.append(make)
        if not makes:
            continue

        source_url = str(record.get("product_url", ""))
        for make in makes:
            for model in models:
                key = (make, model, generation, year_from, year_to)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "Fitment_ID": _stable_id("FIT", product_id, *key),
                    "Product_ID": product_id,
                    "Vehicle_Make": make,
                    "Vehicle_Model": model,
                    "Generation": generation,
                    "Year_From": year_from,
                    "Year_To": year_to,
                    "Engine": engine,
                    "Engine_Code": "",
                    "Transmission": "Verify exact transmission code",
                    "Fuel_Type": "",
                    "Body_Type": "",
                    "PR_Code": "",
                    "VIN_Rule": "Check VIN + engine/transmission code before final confirmation",
                    "Fitment_Status": "Compatible - conditional / auto-parsed",
                    "Verification_Source": "Cars245",
                    "Source_Record_ID": product_id,
                    "Source_File": source_url or "Cars245 scraper",
                    "Verified_Status": "Needs VIN / manual verification",
                    "Last_Checked_At": _today(),
                    "Notes": ("Auto-parsed Cars245 compatibility. Raw source retained in URL. "
                              "Do not promise exact fitment unless VIN/transmission matches."),
                })
    return rows


def sync_to_sheet(clean_df: pd.DataFrame, part_number: str) -> dict[str, int]:
    if clean_df is None or clean_df.empty:
        raise ValueError("No Cars245 rows to sync")

    product_id = canonical_part(part_number)
    service = _auth_service()

    id_values = _read_values(service, IDENTIFIERS_SHEET)
    id_headers, id_existing = _rows_as_dicts(id_values)
    existing_id_keys = {(r.get("Product_ID", ""), r.get("Normalized_Value", "")) for r in id_existing}
    new_ids = [r for r in _identifier_rows(clean_df, product_id)
               if (str(r["Product_ID"]), str(r["Normalized_Value"])) not in existing_id_keys]
    ids_added = _append_dicts(service, IDENTIFIERS_SHEET, id_headers, new_ids)

    fit_values = _read_values(service, FITMENT_SHEET)
    fit_headers, fit_existing = _rows_as_dicts(fit_values)
    existing_fit_ids = {r.get("Fitment_ID", "") for r in fit_existing}
    new_fit = [r for r in _fitment_rows(clean_df, product_id)
               if str(r["Fitment_ID"]) not in existing_fit_ids]
    fit_added = _append_dicts(service, FITMENT_SHEET, fit_headers, new_fit)

    ai_values = _read_values(service, AI_FEED_SHEET)
    ai_headers, ai_existing = _rows_as_dicts(ai_values)
    ai_index = None
    ai_row = None
    for idx, row in enumerate(ai_existing, start=2):
        if normalize_part(row.get("Product_ID", "")) == normalize_part(product_id) or \
           normalize_part(row.get("OEM_Number", "")) == normalize_part(product_id):
            ai_index, ai_row = idx, row
            break

    brands = [x for x in clean_df.get("brand", pd.Series(dtype=str)).astype(str).tolist() if x]
    makes = []
    models = []
    for _, r in clean_df.iterrows():
        makes.extend(_split_pipe(r.get("detected_vehicles", "")))
        models.extend(_guess_models(str(r.get("compatibility", "")) + " " + str(r.get("tables", ""))))
    makes = list(dict.fromkeys(makes))
    models = list(dict.fromkeys(models))

    years_text = " ".join(str(x) for x in clean_df.get("compatibility", pd.Series(dtype=str)).tolist())
    year_from, year_to = _extract_years(years_text)
    product_names = [x for x in clean_df.get("product_name", pd.Series(dtype=str)).astype(str).tolist() if x]

    if ai_row:
        updated = dict(ai_row)
        updated.update({
            "Part_Number": updated.get("Part_Number") or product_id,
            "OEM_Number": updated.get("OEM_Number") or product_id,
            "Brand": updated.get("Brand") or (brands[0] if brands else ""),
            "Part_Name": updated.get("Part_Name") or (product_names[0] if product_names else ""),
            "Description": (updated.get("Description") or "") + " | Cars245 compatibility enriched",
            "Vehicle_Make": " / ".join(makes[:12]) or updated.get("Vehicle_Make", ""),
            "Vehicle_Model": "; ".join(models[:20]) or updated.get("Vehicle_Model", ""),
            "Year_From": year_from or updated.get("Year_From", ""),
            "Year_To": year_to or updated.get("Year_To", ""),
            "Verified_Status": "Cars245 enriched; exact fitment conditional",
            "Last_Checked_At": _today(),
            "Source_Record_ID": product_id,
            "Notes": ((updated.get("Notes") or "") +
                      " | Cars245 sync: use 38_Product_Identifiers then 39_Vehicle_Fitment; request VIN/transmission if conditional.").strip(" |"),
        })
        # Critical: do NOT overwrite Customer_Price, Currency, Stock_Status or Availability.
        _update_row(service, AI_FEED_SHEET, ai_index, ai_headers, updated)
        ai_changed = 1
    else:
        new_ai = {
            "AI_Feed_ID": _stable_id("AI", product_id),
            "Product_ID": product_id,
            "Part_Number": product_id,
            "OEM_Number": product_id,
            "Brand": brands[0] if brands else "",
            "Part_Name": product_names[0] if product_names else "",
            "Description": "Cars245 auto-enriched product; verify fitment and pricing before customer display",
            "Condition": "New",
            "Vehicle_Make": " / ".join(makes[:12]),
            "Vehicle_Model": "; ".join(models[:20]),
            "Year_From": year_from,
            "Year_To": year_to,
            "Engine": "",
            "Customer_Price": "",
            "Currency": "EGP",
            "Stock_Status": "Availability Confirmation Required",
            "Availability": "التوافر يحتاج تأكيدًا من فريق ELKADY AUTO PARTS",
            "Warranty": "",
            "Return_Policy": "",
            "Verified_Status": "Cars245 enriched; price/fitment review required",
            "Last_Checked_At": _today(),
            "AI_Eligible": "FALSE",
            "Source_Record_ID": product_id,
            "Notes": "Do not quote price or exact compatibility until ELKADY AUTO PARTS confirms price and VIN/transmission fitment.",
        }
        _append_dicts(service, AI_FEED_SHEET, ai_headers, [new_ai])
        ai_changed = 1

    return {"identifiers_added": ids_added, "fitment_added": fit_added, "ai_feed_changed": ai_changed}
