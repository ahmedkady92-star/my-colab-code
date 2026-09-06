#!/usr/bin/env python3
import os
import google.auth
from googleapiclient.discovery import build

SPREADSHEET_ID = os.environ["ELKADY_SPREADSHEET_ID"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

credentials, project_id = google.auth.default(scopes=SCOPES)
service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

meta = service.spreadsheets().get(
    spreadsheetId=SPREADSHEET_ID,
    fields="properties.title,sheets.properties.title"
).execute()

title = meta["properties"]["title"]
tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]

print(f"spreadsheet_title={title}")
print(f"project_id={project_id}")
print(f"tab_count={len(tabs)}")
print("tabs=" + " | ".join(tabs))

required = {"36_Supplier_Offers", "37_Supplier_Price_History", "38_Product_Identifiers", "39_Vehicle_Fitment", "41_AI_Product_Feed", "43_Sync_Audit"}
missing = sorted(required.difference(tabs))
if missing:
    raise SystemExit("Missing required tabs: " + ", ".join(missing))

sample = service.spreadsheets().values().get(
    spreadsheetId=SPREADSHEET_ID,
    range="'43_Sync_Audit'!A1:C3"
).execute().get("values", [])
print(f"sync_audit_sample_rows={len(sample)}")
print("WIF_SHEETS_READ_TEST=SUCCESS")
