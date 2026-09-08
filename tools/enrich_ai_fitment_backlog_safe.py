#!/usr/bin/env python3
"""Safer wrapper for the AI fitment backlog.

This keeps the existing enrichment logic intact while tightening candidate
selection and allowing controlled retries for explicitly selected unresolved
Porsche rows.
"""
import re
import sys
from pathlib import Path

# When this file is executed directly as tools/<script>.py, Python adds the
# tools directory (not the repository root) to sys.path. Add only the repo root
# so the existing `tools` package can be imported without changing old logic.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import enrich_ai_fitment_backlog as base

MAX_AUTO_ATTEMPTS = 2
# Controlled extra attempt for these five unresolved Porsche AI feed rows only.
# audit_done() intentionally excludes these IDs from the done set; successful
# rows remain protected by the base script's existing fitment-key check.
EXTRA_RETRY_IDS = {
    "AI-KANO-0178",      # PAB 199 371 10
    "AI-KANO-0185",      # 991 572 371 00
    "AI-KANO-0190",      # 9P1 411 318 A
    "AI-KANO-CHAT-0002", # 7PP 199 331 A
    "AI-KANO-MAN-0008",  # PAB 819 439 00
}
SUPPLIER_CODE_RE = re.compile(r"^\d{3}[A-Z]{2}$", re.I)
SUPPLIER_PREFIX_WITH_OEM_RE = re.compile(r"^\s*\d{3}[A-Z]{2}\s+(.+?)\s*$", re.I)


def valid_part(value):
    n = base.norm(value)
    if len(n) < 5 or not any(ch.isdigit() for ch in n):
        return False
    if SUPPLIER_CODE_RE.fullmatch(n):
        return False
    return True


def first_part(value):
    for token in re.split(r"[;|,\n]+", str(value or "")):
        token = token.strip()
        if not token:
            continue
        m = SUPPLIER_PREFIX_WITH_OEM_RE.match(token)
        if m:
            candidate = m.group(1).strip()
            if valid_part(candidate):
                return candidate
        if valid_part(token):
            return token
    return ""


def audit_done(rows):
    """Keep normal two-attempt ceiling, but reopen only selected Porsche IDs."""
    counts = {}
    for _, row in rows:
        if str(row.get("Source_System", "")).strip().upper() != base.AUDIT_SOURCE:
            continue
        rid = str(row.get("Source_Record_ID", "")).strip()
        if rid:
            counts[rid] = counts.get(rid, 0) + 1

    done = set()
    for rid, count in counts.items():
        # Explicit test rows are allowed through candidate selection regardless
        # of their old audit count. Once fitment is found, fit_keys skips them.
        if rid in EXTRA_RETRY_IDS:
            continue
        if count >= MAX_AUTO_ATTEMPTS:
            done.add(rid)
    return done


# Patch only candidate parsing/retry policy. All Cars245 research, scoring,
# safety gates and write logic remain in the existing base implementation.
base.valid_part = valid_part
base.first_part = first_part
base.audit_done = audit_done


if __name__ == "__main__":
    base.main()
