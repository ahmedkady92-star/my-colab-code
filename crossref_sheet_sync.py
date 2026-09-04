#!/usr/bin/env python3
"""Sync Cars245 OE/alternative references into 38_Product_Identifiers safely."""
from __future__ import annotations

import re
from datetime import date

import gspread
from google.auth import default

from cars245_crossrefs import extract_cross_references
from cars245_scraper import build_session, get_soup

SPREADSHEET_ID = "1A-8YoZkVIdelh2x3i7DmeFCERLeR1XREyEpK3Wrk6B0"
IDENTIFIERS_SHEET = "38_Product_Identifiers"


def compact(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def collect_crossrefs(clean_df, primary_part: str) -> list[dict]:
    session = build_session()
    refs = {}
    if "product_url" not in clean_df.columns:
        return []
    for url in clean_df["product_url"].dropna().astype(str).unique():
        if not url.startswith("http"):
            continue
        try:
            soup = get_soup(session, url)
            for ref in extract_cross_references(soup, primary_part):
                refs.setdefault(ref["normalized"], ref)
        except Exception as exc:
            print(f"Cross-reference extraction skipped for {url}: {exc}")
    return list(refs.values())


def sync_crossrefs(clean_df, primary_part: str) -> dict:
    refs = collect_crossrefs(clean_df, primary_part)
    if not refs:
        return {"crossrefs_found": 0, "crossrefs_added": 0}

    creds, _ = default(scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ])
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet(IDENTIFIERS_SHEET)
    rows = ws.get_all_records()

    product_id = primary_part.strip().upper()
    existing = {
        compact(r.get("Original_Value", ""))
        for r in rows
        if str(r.get("Product_ID", "")).strip().upper() == product_id
    }
    next_num = 1 + sum(
        1 for r in rows if str(r.get("Product_ID", "")).strip().upper() == product_id
    )

    values = []
    slug = compact(product_id)
    for ref in refs:
        if ref["normalized"] in existing:
            continue
        values.append([
            f"ID-{slug}-{next_num:02d}", product_id,
            "OEM/Cross-Reference", ref["value"], ref["normalized"], "",
            ref["source_type"], product_id, "Cars245", "",
            ref["verified_status"], ref["confidence"], "FALSE", "", "",
            date.today().isoformat(), ref["notes"],
        ])
        existing.add(ref["normalized"])
        next_num += 1

    if values:
        ws.append_rows(values, value_input_option="USER_ENTERED")
    return {"crossrefs_found": len(refs), "crossrefs_added": len(values)}
