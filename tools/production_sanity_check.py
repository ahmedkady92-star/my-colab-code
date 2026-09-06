#!/usr/bin/env python3
from pathlib import Path

required = [
    Path('.github/workflows/supplier-sheet-auto-trigger.yml'),
    Path('tools/process_new_supplier_rows.py'),
    Path('tools/upsert_verified_fitment.py'),
    Path('tools/relink_supplier_master_product.py'),
    Path('tools/sync_supplier_payload_to_sheets.py'),
    Path('supplier_automation.py'),
]
missing = [str(p) for p in required if not p.exists()]
if missing:
    raise SystemExit(f'Missing production files: {missing}')
workflow = Path('.github/workflows/supplier-sheet-auto-trigger.yml').read_text(encoding='utf-8')
assert "--baseline-row 1229" in workflow
assert "cron: '*/5 * * * *'" in workflow
assert 'id-token: write' in workflow
assert 'relink_supplier_master_product.py' in workflow
manual = Path('.github/workflows/supplier-automation.yml').read_text(encoding='utf-8')
assert 'upsert_verified_fitment.py' in manual
assert 'relink_supplier_master_product.py' in manual
assert '- volkswagen' in manual
print('PRODUCTION_SANITY_OK')
