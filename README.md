# ELKADY AUTO Cars245 Scraper

Organized from the original Colab notebook used for Cars245 research.

## What it does

- Searches Cars245 by part number.
- Collects product links under `/en/item/`.
- Extracts visible product name, brand, price/currency, OE/cross-reference text, compatibility text, tables, vehicle-related links and detected makes.
- Saves raw CSV, cleaned CSV and cleaned JSON outputs.
- Keeps a Colab launcher notebook in `cars245_scraper.ipynb`.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
python cars245_scraper.py "04E 121 600 BE"
```

Optional:

```bash
python cars245_scraper.py "G 060 162 A2" --max-products 20 --delay 1 --output-dir output
```

## Important fitment rule

Extracted catalog data is research data. Exact vehicle fitment should still be confirmed by VIN, engine/transmission code or another verified catalog record before customer confirmation.
