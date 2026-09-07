#!/usr/bin/env python3
"""Safer wrapper for the AI fitment backlog.

This keeps the existing enrichment logic intact while tightening candidate
selection and allowing one automatic retry for previously-audited items that
still have no stored fitment.
"""
import re

from tools import enrich_ai_fitment_backlog as base

MAX_AUTO_ATTEMPTS = 2
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
    """Auto-retry unresolved audited items once, then stop repeating them forever.

    Successful items are already skipped by the base script's fitment-key check,
    so this count applies only to rows that still have no stored fitment.
    """
    counts = {}
    for _, row in rows:
        if str(row.get("Source_System", "")).strip().upper() != base.AUDIT_SOURCE:
            continue
        rid = str(row.get("Source_Record_ID", "")).strip()
        if rid:
            counts[rid] = counts.get(rid, 0) + 1
    return {rid for rid, count in counts.items() if count >= MAX_AUTO_ATTEMPTS}


# Monkey-patch only the candidate/retry policy; preserve all existing write,
# scoring, Cars245, fitment safety, and audit behavior from the base module.
base.valid_part = valid_part
base.first_part = first_part
base.audit_done = audit_done


if __name__ == "__main__":
    base.main()
