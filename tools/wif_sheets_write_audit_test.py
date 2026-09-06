#!/usr/bin/env python3
import os
from datetime import datetime, timezone
import google.auth
from googleapiclient.discovery import build

SPREADSHEET_ID = os.environ["ELKADY_SPREADSHEET_ID"]
RUN_ID = os.environ.get("GITHUB_RUN_ID", "manual")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

credentials, _ = google.auth.default(scopes=SCOPES)
service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

now = datetime.now(timezone.utc)
audit_id = f"AUD-WIF-TEST-{RUN_ID}"
row = [[
    audit_id,
    now.strftime("%Y-%m-%d"),
    now.strftime("%H:%M:%S UTC"),
    "GitHub Actions",
    "Google Sheets",
    "WIF Connection Test",
    "Append Audit Test",
    RUN_ID,
    "43_Sync_Audit",
    "WIF repository-scoped identity",
    "Success",
    1,
    1,
    0,
    0,
    0,
    0,
    "",
    "GitHub Actions / ELKADY CRM Automation",
    f"WIF-TEST-{RUN_ID}",
    "Passed",
    "Safe one-row audit write test; no business data modified."
]]

result = service.spreadsheets().values().append(
    spreadsheetId=SPREADSHEET_ID,
    range="'43_Sync_Audit'!A:V",
    valueInputOption="RAW",
    insertDataOption="INSERT_ROWS",
    body={"values": row},
).execute()

updated = result.get("updates", {}).get("updatedRange", "")
if not updated:
    raise SystemExit("Audit append did not return updatedRange")

check = service.spreadsheets().values().get(
    spreadsheetId=SPREADSHEET_ID,
    range=updated,
).execute().get("values", [])
if not check or check[0][0] != audit_id:
    raise SystemExit("Audit write verification failed")

print(f"audit_id={audit_id}")
print(f"updated_range={updated}")
print("WIF_SHEETS_WRITE_TEST=SUCCESS")
