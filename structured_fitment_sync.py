#!/usr/bin/env python3
"""Cars245-only structured vehicle fitment extraction and Sheet sync.

Reads each Cars245 product page, extracts fitment table/list rows as individual
records, parses make/model/generation/year/engine fields where present, and
preserves the full Cars245 row text in Notes so no source detail is lost.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date

import gspread
from google.auth import default

from cars245_scraper import build_session, get_soup

SPREADSHEET_ID = "1A-8YoZkVIdelh2x3i7DmeFCERLeR1XREyEpK3Wrk6B0"
FITMENT_SHEET = "39_Vehicle_Fitment"

MAKES = [
    "AUDI", "VOLKSWAGEN", "VW", "SKODA", "SEAT", "CUPRA", "PORSCHE",
    "BENTLEY", "LAMBORGHINI", "BMW", "MINI", "MERCEDES-BENZ", "MERCEDES",
    "LAND ROVER", "RANGE ROVER", "JAGUAR",
]

MODEL_PATTERNS = [
    r"\bA[1-8]\b", r"\bS[1-8]\b", r"\bRS\s?[1-8]\b", r"\bQ[2-8]\b", r"\bRS\s?Q[3-8]\b",
    r"\bA4\s+ALLROAD\b", r"\bA6\s+ALLROAD\b",
    r"\bGOLF\b", r"\bPASSAT\b", r"\bTIGUAN\b", r"\bTOUAREG\b", r"\bJETTA\b", r"\bPOLO\b",
    r"\bOCTAVIA\b", r"\bSUPERB\b", r"\bKODIAQ\b", r"\bKAROQ\b", r"\bRAPID\b",
    r"\bCAYENNE\b", r"\bMACAN\b", r"\bPANAMERA\b", r"\b911\b",
    r"\bPHAETON\b", r"\bAMAROK\b", r"\bCRAFTER\b",
]

GEN_RE = re.compile(r"\b(?:B[5-9]|C[4-9]|D[2-5]|4F[0-9A-Z]*|4G[0-9A-Z]*|4K[0-9A-Z]*|4M[0-9A-Z]*|8K[0-9A-Z]*|8W[0-9A-Z]*|8V[0-9A-Z]*|8Y[0-9A-Z]*|FY|95B|958|9Y0|9PA|7L|7P|CR7|5N|AD1)\b", re.I)
YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
ENGINE_RE = re.compile(r"\b(?:[0-9]\.[0-9]\s*(?:TDI|TFSI|TSI|FSI|TFSIe?|V6|V8|V10|V12)?|[A-Z]{3,5}\b|\d{3,4}\s*cc)\b", re.I)


def compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def stable_id(part: str, raw: str) -> str:
    digest = hashlib.sha1((compact(part) + "|" + raw).encode("utf-8")).hexdigest()[:14].upper()
    return f"FIT-{digest}"


def _make(text: str) -> str:
    upper = text.upper()
    for make in MAKES:
        if re.search(r"\b" + re.escape(make) + r"\b", upper):
            if make == "VW":
                return "VOLKSWAGEN"
            if make == "MERCEDES":
                return "MERCEDES-BENZ"
            return make
    return ""


def _model(text: str) -> str:
    upper = text.upper()
    # Prefer longer/compound model names first.
    for pattern in MODEL_PATTERNS:
        m = re.search(pattern, upper, flags=re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip().title()
    return ""


def _years(text: str) -> tuple[str, str]:
    ys = [int(y) for y in YEAR_RE.findall(text)]
    return (str(min(ys)), str(max(ys))) if ys else ("", "")


def _generation(text: str) -> str:
    vals = []
    for m in GEN_RE.findall(text):
        value = str(m).upper()
        if value not in vals:
            vals.append(value)
    return "; ".join(vals[:5])


def _engine(text: str) -> str:
    vals = []
    for m in ENGINE_RE.findall(text):
        value = re.sub(r"\s+", " ", str(m).upper()).strip()
        # Exclude make/model-like tokens and years.
        if value in MAKES or re.fullmatch(r"(?:19|20)\d{2}", value):
            continue
        if value not in vals:
            vals.append(value)
    return "; ".join(vals[:20])


def _looks_like_fitment(text: str) -> bool:
    upper = text.upper()
    has_make = any(re.search(r"\b" + re.escape(m) + r"\b", upper) for m in MAKES)
    has_year = bool(YEAR_RE.search(text))
    has_model = any(re.search(p, upper, flags=re.I) for p in MODEL_PATTERNS)
    # Cars245 sometimes omits make in repeated rows, so model + year is enough.
    return has_make or (has_model and has_year)


def extract_fitment_rows(soup, product_url: str) -> list[dict]:
    raw_rows: list[str] = []
    seen = set()

    # Prefer real HTML table rows: they preserve Cars245's row-level relationships.
    for tr in soup.find_all("tr"):
        cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)).strip() for c in tr.find_all(["th", "td"])]
        text = " | ".join(c for c in cells if c)
        if text and len(text) <= 1200 and _looks_like_fitment(text) and text not in seen:
            seen.add(text)
            raw_rows.append(text)

    # Fallback for Cars245 pages rendering compatibility as lists/cards.
    for node in soup.find_all(["li", "article", "div"]):
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        if not text or len(text) > 700 or text in seen:
            continue
        if _looks_like_fitment(text) and ("engine" in text.lower() or YEAR_RE.search(text)):
            seen.add(text)
            raw_rows.append(text)

    out = []
    inherited_make = ""
    for raw in raw_rows:
        make = _make(raw) or inherited_make
        if make:
            inherited_make = make
        model = _model(raw)
        y1, y2 = _years(raw)
        out.append({
            "make": make,
            "model": model,
            "generation": _generation(raw),
            "year_from": y1,
            "year_to": y2,
            "engine": _engine(raw),
            "raw": raw,
            "url": product_url,
        })
    return out


def collect_fitments(clean_df) -> list[dict]:
    if "product_url" not in clean_df.columns:
        return []
    session = build_session()
    rows = {}
    for url in clean_df["product_url"].dropna().astype(str).unique():
        if not url.startswith("http"):
            continue
        try:
            soup = get_soup(session, url)
            for row in extract_fitment_rows(soup, url):
                key = row["raw"]
                rows.setdefault(key, row)
        except Exception as exc:
            print(f"Fitment extraction skipped for {url}: {exc}")
    return list(rows.values())


def sync_structured_fitments(clean_df, primary_part: str) -> dict:
    fitments = collect_fitments(clean_df)
    if not fitments:
        return {"structured_fitments_found": 0, "structured_fitments_added": 0}

    creds, _ = default(scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ])
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet(FITMENT_SHEET)
    headers = ws.row_values(1)
    existing_rows = ws.get_all_records()
    existing_ids = {str(r.get("Fitment_ID", "")) for r in existing_rows}

    part = primary_part.strip().upper()
    values = []
    for f in fitments:
        fid = stable_id(part, f["raw"])
        if fid in existing_ids:
            continue
        row = {
            "Fitment_ID": fid,
            "Product_ID": part,
            "Vehicle_Make": f["make"],
            "Vehicle_Model": f["model"] or "See Cars245 raw row",
            "Generation": f["generation"],
            "Year_From": f["year_from"],
            "Year_To": f["year_to"],
            "Engine": f["engine"],
            "Engine_Code": "",
            "Transmission": "",
            "Fuel_Type": "",
            "Body_Type": "",
            "PR_Code": "",
            "VIN_Rule": "Use VIN when exact variant matters",
            "Fitment_Status": "Cars245 listed compatibility",
            "Verification_Source": "Cars245",
            "Source_Record_ID": compact(part),
            "Source_File": f["url"],
            "Verified_Status": "Cars245 source",
            "Last_Checked_At": date.today().isoformat(),
            "Notes": "Cars245 raw fitment row: " + f["raw"],
        }
        values.append([row.get(h, "") for h in headers])
        existing_ids.add(fid)

    if values:
        ws.append_rows(values, value_input_option="USER_ENTERED")
    return {
        "structured_fitments_found": len(fitments),
        "structured_fitments_added": len(values),
    }
