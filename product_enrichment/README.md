# ELKADY Product Enrichment

Independent workflow for enriching automotive part records without modifying the existing vehicle-fitment workflow on `main`.

## Goal
Input a `part_number` and `brand`, then collect only approved product metadata from official manufacturer/distributor sources and prepare a safe record for WooCommerce/CRM review.

## Safety rule for images
An official website image is **not automatically licensed for commercial reuse**. Images may be marked publishable only when the source has an explicit reseller/distributor/media-feed permission recorded in `sources.json`.

Allowed statuses:
- `approved_commercial` -> image may be prepared for publishing.
- `reference_only` -> metadata may be stored, image must not be published.
- `unknown` -> block image publishing.

## Planned flow
`Part Number + Brand -> Official source lookup -> Product data -> Rights check -> Image status -> Existing fitment workflow -> CRM price/inventory -> WooCommerce draft`

## Initial brands
- ZF Aftermarket: LEMFORDER / TRW / SACHS
- Bosch
- MAHLE
- ATE
- Valeo

## Important
- No scraping from Cars245 for product images.
- No automatic publication to WooCommerce yet.
- No credentials or API keys are stored in this repository.
- Existing compatibility automation remains untouched.
