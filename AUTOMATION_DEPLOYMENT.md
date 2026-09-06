# Supplier Sheet Auto Trigger

Production safeguards:
- Google Workload Identity Federation; no JSON key.
- Polls `36_Supplier_Offers` every 5 minutes.
- Safe baseline is row 1229; historical rows are not automatically processed.
- New rows require supplier, manufacturer brand, positive EGP cost, and a usable part/OEM number.
- Cars245 results must pass the existing safe family/evidence gate before identifiers/fitment are auto-verified.
- Unsupported or ambiguous fitment remains Review Required and is not AI-eligible.
- Verified identifiers and conditional fitment are upserted to tabs 38/39.
- Supplier history, pricing, AI feed and audit are synchronized and relinked to a master Product_ID.
- At most two new supplier candidates are processed per scheduled run.
