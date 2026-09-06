#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone

import google.auth
from googleapiclient.discovery import build

SPREADSHEET_ID = os.environ["ELKADY_SPREADSHEET_ID"]
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
TAB = "43_Sync_Audit"


def col_letter(n):
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def main():
    creds, project_id = google.auth.default(scopes=SCOPES)
    svc = build("sheets", "v4", credentials=creds, cache_discovery=False)

    meta = svc.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    title = meta["properties"]["title"]
    tabs = [s["properties"]["title"] for s in meta.get("sheets", [])]
    if title != "ELKADY AUTO CRM Knowledge Base":
        raise SystemExit(f"Unexpected spreadsheet title: {title}")
    if TAB not in tabs:
        raise SystemExit(f"Missing tab: {TAB}")

    headers = svc.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{TAB}'!A1:V1",
    ).execute().get("values", [[]])[0]
    if not headers:
        raise SystemExit("43_Sync_Audit has no headers")

    now = datetime.now(timezone.utc)
    run_id = os.environ.get("GITHUB_RUN_ID", "unknown")
    data = {
        "Audit_ID": f"AUD-WIF-TEST-{run_id}",
        "Sync_Date": now.strftime("%Y-%m-%d"),
        "Sync_Time": now.strftime("%H:%M:%S UTC"),
        "Source_System": "GitHub Actions WIF Smoke Test",
        "Destination_System": "Google Sheets",
        "Entity_Type": "Authentication Test",
        "Operation": "Read + Append",
        "Source_Record_ID": run_id,
        "Destination_Record_ID": "43_Sync_Audit",
        "Match_Key": "WIF|GitHub|GoogleSheets",
        "Sync_Status": "Success",
        "Notes": "Live connectivity proof. No supplier/product rows modified.",
    }
    row = [data.get(h, "") for h in headers]
    end_col = col_letter(len(headers))
    svc.spreadsheets().values().append(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{TAB}'!A:{end_col}",
        valueInputOption="RAW",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()

    result = {
        "ok": True,
        "spreadsheet_title": title,
        "tab_count": len(tabs),
        "audit_id": data["Audit_ID"],
        "google_project_id": project_id,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
