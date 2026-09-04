#!/usr/bin/env python3
"""One-command Cars245 -> ELKADY AUTO Google Sheet pipeline.

For every part number this pipeline now performs:
1) Cars245 search + product collection
2) core/AI feed sync
3) structured OEM + aftermarket alternatives with Brand -> Part Number
4) structured Cars245 vehicle fitment rows

Cars245 remains the source for alternatives and compatibility.
"""
from __future__ import annotations

import argparse

from cars245_scraper import scrape_part
from google_sheets_sync import sync_to_sheet
from crossref_sheet_sync import sync_crossrefs
from structured_fitment_sync import sync_structured_fitments


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape Cars245 and sync to ELKADY AUTO CRM")
    parser.add_argument("part_number", help='Part number, e.g. "4F0 413 031 AL"')
    parser.add_argument("--max-products", type=int, default=50,
                        help="Maximum Cars245 product results to inspect; default raised to 50 to capture more aftermarket brands")
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
    result.update(sync_crossrefs(clean_df, args.part_number))
    result.update(sync_structured_fitments(clean_df, args.part_number))

    print("SYNC COMPLETE")
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
