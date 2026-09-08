#!/usr/bin/env python3
"""Safer wrapper for the AI fitment backlog.

This keeps the existing enrichment logic intact while tightening candidate
selection and allowing one automatic retry for previously-audited items that
still have no stored fitment.
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
# One controlled extra attempt for five unresolved Porsche rows only. This is
# deliberately keyed by AI_Feed_ID so no other audited rows are reopened.
EXTRA_RETRY_IDS = {
    "AI-KANO-0178",      # PAB 199 371 10
    "AI-KANO-0185",      # 991 572 371 00
    "AI-KANO-0190",      # 9P1 411 318 A
    "AI-KANO-CHAT-0002", # 7PP 199 331 A
    "AI-KANO-MAN-0008",  # PAB 819 439 00
}
EXTRA_RETRY_ATTEMPTS = 3
SUPPLIER_CODE_RE = re.compile(r"^\d{3}[A-Z]{2}$", re.I)
SUPPLIER_PREFIX_WITH_OEM_RE = re.compile(r"^\s*\d{3}[A-Z]{2}\s+(.+?)\s*$", re.I)


def valid_part(value):
    n = base.norm(value)
    if len(n) < 5 or not any(ch.isdigit() for ch in n):
        return False
    # Known supplier-style short codes such as 291AD / 065AK / 133AT are not OEMs.
    if SUPPLIER_CODE_RE.fullmatch(n):
        return False
    return True


def first_part(value):
    for token in re.split(r"[;|,\n]+", str(value or "")):
        token = token.strip()
        if not token:
            continue
        # Some supplier cells contain a supplier code followed by the real OEM,
        # e.g. "133AC 06A121132R". Prefer the OEM portion.
        m = SUPPLIER_PREFIX_WITH_OEM_RE.match(token)
        if m:
            candidate = m.group(1).strip()
            if valid_part(candidate):
                return candidate
        if valid_part(token):
            return token
    return ""


def audit_done(rows):
    """Retry unresolved audited rows once, plus one controlled Porsche re-check.

    Successful items are already skipped by the base script's fitment-key check.
    The five explicit Porsche rows get exactly one extra audit attempt; all other
    rows keep the existing two-attempt ceiling.
    """
    counts = {}
    for _, row in rows:
        if str(row.get("Source_System", "")).strip().upper() != base.AUDIT_SOURCE:
            continue
        rid = str(row.get("Source_Record_ID", "")).strip()
        if rid:
            counts[rid] = counts.get(rid, 0) + 1
    done = set()
    for rid, count in counts.items():
        limit = EXTRA_RETRY_ATTEMPTS if rid in EXTRA_RETRY_IDS else MAX_AUTO_ATTEMPTS
        if count >= limit:
            done.add(rid)
    return done


# Monkey-patch only the candidate/retry policy; preserve all existing write,
# scoring, Cars245, fitment safety, and audit behavior from the base module.
base.valid_part = valid_part
base.first_part = first_part
base.audit_done = audit_done


if __name__ == "__main__":
    base.main()
