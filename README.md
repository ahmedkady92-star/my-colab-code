# ELKADY AUTO Cars245 Scraper

Organized from the original Colab notebook used for Cars245 research.

## What it does

- Searches Cars245 by part number.
- Collects product links under `/en/item/`.
- Extracts visible product name, brand, price/currency, OE/cross-reference text, compatibility text, tables, vehicle-related links and detected makes.
- Saves raw CSV, cleaned CSV and cleaned JSON outputs.
- Syncs research results into **ELKADY AUTO CRM Knowledge Base**.

## Google Sheet sync

The pipeline writes only to these tabs:

- `38_Product_Identifiers` — primary OEM and Cars245 cross-reference numbers.
- `39_Vehicle_Fitment` — auto-parsed make/model/year/engine hints, always marked conditional when exact VIN/transmission is not confirmed.
- `41_AI_Product_Feed` — enriches the AI record while preserving any existing customer price, stock and availability fields.

### Safety behavior

- Supplier cost and customer price are never overwritten by the Cars245 sync.
- Existing `Customer_Price` is preserved.
- New products are created with `AI_Eligible=FALSE` until ELKADY AUTO confirms price and fitment.
- Cars245 auto-parsed fitment is marked `Needs VIN / manual verification` when exact application is not certain.
- Duplicate identifiers and fitment rows are skipped using normalized IDs.

## Install

```bash
pip install -r requirements.txt
```

## Scrape only

```bash
python cars245_scraper.py "04E 121 600 BE"
```

## Scrape + sync to ELKADY CRM

In Google Colab, run:

```bash
python run_and_sync.py "G 060 162 A2"
```

On the first sync Colab asks you to authorize your Google account. The code uses that session to write to the existing ELKADY AUTO CRM spreadsheet; no Google password or service-account secret is stored in GitHub.

Optional:

```bash
python run_and_sync.py "04E 121 600 BE" --max-products 20 --delay 1 --output-dir output
```

## Important fitment rule

Extracted catalog data is research data. Exact vehicle fitment should still be confirmed by VIN, engine/transmission code or another verified catalog record before customer confirmation.
