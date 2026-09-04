#!/usr/bin/env python3
"""One-command Cars245 -> ELKADY AUTO Google Sheet pipeline."""
from __future__ import annotations

import argparse

from cars245_scraper import scrape_part
from google_sheets_sync import sync_to_sheet
from crossref_sheet_sync import sync_crossrefs


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Cars245 and sync to ELKADY AUTO CRM")
    parser.add_argument("part_number", help='Part number, e.g. "G 060 162 A2"')
    parser.add_argument("--max-products", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--no-sync", action="store_true", help="Scrape only; do not write to Google Sheets")
    args = parser.parse_args()

    _, clean_df = scrape_part(
        args.part_number,
        max_products=args.max_products,
        delay_seconds=args.delay,
        output_dir=args.output_dir,
    )
    if clean_df.empty:
        print("No usable Cars245 data found; nothing synced.")
        return

    if args.no_sync:
        print("Scrape complete; sync skipped.")
        return

    result = sync_to_sheet(clean_df, args.part_number)
    crossref_result = sync_crossrefs(clean_df, args.part_number)
    result.update(crossref_result)

    print("SYNC COMPLETE")
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
