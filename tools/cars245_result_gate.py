#!/usr/bin/env python3
from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

TYPE_FAMILY = {
    "shock absorber": "shock-absorber",
    "suspension strut": "shock-absorber",
    "air suspension strut": "shock-absorber",
    "suspension strut complete": "shock-absorber",
    "air spring damper": "shock-absorber",
    "gas strut": "shock-absorber",
    "brake pad set": "brake-pad",
    "brake disc": "brake-disc",
    "water pump": "water-pump",
    "thermostat": "thermostat",
    "control arm": "control-arm",
    "wheel bearing": "wheel-bearing",
    "engine mounting": "engine-mount",
    "transmission mounting": "transmission-mount",
    "oil filter": "oil-filter",
    "air filter": "air-filter",
    "cabin filter": "cabin-filter",
    "fuel filter": "fuel-filter",
    "spark plug": "spark-plug",
    "ignition coil": "ignition-coil",
    "sensor": "sensor",
    "timing chain": "timing-chain",
    "timing belt set": "timing-belt",
    "belt tensioner": "belt-tensioner",
}


def norm(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def expected_family(description: str) -> str:
    text = str(description or "").lower()
    rules = [
        (("مساعد", "shock absorber", "shock absorbers", "suspension strut", "air suspension strut", "gas strut", "strut"), "shock-absorber"),
        (("تيل", "brake pad", "brake pads"), "brake-pad"),
        (("طنابير", "brake disc", "brake discs", "brake rotor", "rotor"), "brake-disc"),
        (("طلمبة مياه", "طلمبه مياه", "water pump"), "water-pump"),
        (("ثرموستات", "thermostat"), "thermostat"),
        (("مقص", "control arm"), "control-arm"),
        (("بلية عجل", "بليه عجل", "wheel bearing"), "wheel-bearing"),
        (("فلتر زيت", "oil filter"), "oil-filter"),
        (("فلتر هواء", "air filter"), "air-filter"),
        (("فلتر تكييف", "cabin filter"), "cabin-filter"),
        (("بوجيه", "spark plug"), "spark-plug"),
        (("كويل", "ignition coil"), "ignition-coil"),
    ]
    for tokens, family in rules:
        if any(token in text for token in tokens):
            return family
    return ""


def item_family(item: dict) -> str:
    ptype = str(item.get("product_type", "")).strip().lower()
    if ptype in TYPE_FAMILY:
        return TYPE_FAMILY[ptype]
    for label, family in TYPE_FAMILY.items():
        if label in ptype:
            return family
    slug = urlparse(str(item.get("url", ""))).path.lower()
    for label, family in TYPE_FAMILY.items():
        if label.replace(" ", "-") in slug:
            return family
    return ""


def _reference_blocks(soup: BeautifulSoup):
    needles = (
        "oe number", "oem", "original number", "cross reference", "alternative products",
        "replacement", "replaces", "replaced by"
    )
    for node in soup.find_all(["tr", "li", "section", "div", "p"]):
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
        low = text.lower()
        if text and len(text) <= 2500 and any(x in low for x in needles):
            yield text


def oem_evidence(html: str, url: str, searched_oem: str) -> tuple[bool, str]:
    target = norm(searched_oem)
    if not target:
        return False, ""
    if target in norm(url):
        return True, "direct_url"
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1 and target in norm(h1.get_text(" ", strip=True)):
        return True, "direct_heading"
    for text in _reference_blocks(soup):
        if target not in norm(text):
            continue
        low = text.lower()
        if any(x in low for x in ("replaced by", "replaces", "replacement")):
            return True, "supersession_reference"
        if any(x in low for x in ("oe number", "oem", "original number", "cross reference", "alternative products")):
            return True, "oem_cross_reference"
    return False, ""


def _dedupe_fitments(rows: list[dict]) -> list[dict]:
    out, seen = [], set()
    for row in rows:
        key = (str(row.get("vehicle_make", "")).upper(), str(row.get("fitment_text", "")).upper())
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def validate_report(report: dict, searched_oem: str, description: str, max_urls: int = 16) -> dict:
    expected = expected_family(description)
    target = norm(searched_oem)
    session = requests.Session()
    session.headers.update(HEADERS)

    candidates = []
    seen = set()
    for item in report.get("alternatives", []):
        url = str(item.get("url", "")).strip()
        if not url or url in seen:
            continue
        seen.add(url)
        fam = item_family(item)
        if expected and fam and fam != expected:
            continue
        candidates.append((url, fam, item))

    strong_pages = []
    candidate_pages = []
    errors = []
    for url, fam, item in candidates[:max_urls]:
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            ok, evidence = oem_evidence(r.text, url, searched_oem)
            page = {
                "url": url,
                "family": fam,
                "evidence": evidence or "same_family_catalog_result",
                "brand": item.get("brand", ""),
                "part_number": item.get("part_number", ""),
            }
            candidate_pages.append(page)
            if ok:
                strong_pages.append(page)
        except Exception as exc:
            errors.append(f"{url}: {str(exc)[:120]}")

    strong_family_counts = Counter(x["family"] for x in strong_pages if x["family"])
    validated_family = strong_family_counts.most_common(1)[0][0] if strong_family_counts else ""
    strong_family_match = bool(expected and validated_family == expected)
    strong_urls = {x["url"] for x in strong_pages if x["family"] == validated_family}

    candidate_family_counts = Counter(x["family"] for x in candidate_pages if x["family"])
    candidate_family = candidate_family_counts.most_common(1)[0][0] if candidate_family_counts else ""
    candidate_family_match = bool(expected and candidate_family == expected)
    candidate_urls = {x["url"] for x in candidate_pages if x["family"] == candidate_family}

    safe_fitments = []
    candidate_fitments = []
    for row in report.get("fitments", []):
        source_urls = [x.strip() for x in str(row.get("source_url", "")).split("|") if x.strip()]
        if not source_urls:
            continue
        if any(x in strong_urls for x in source_urls):
            safe_fitments.append(row)
        elif candidate_family_match and any(x in candidate_urls for x in source_urls):
            candidate_fitments.append(row)

    safe_fitments = _dedupe_fitments(safe_fitments)
    candidate_fitments = _dedupe_fitments(candidate_fitments)

    evidence_types = sorted({x["evidence"] for x in strong_pages})
    supersession_evidence = any(x == "supersession_reference" for x in evidence_types)
    exact_or_crossref_evidence = bool(strong_pages)
    catalog_mapped_candidate = bool(candidate_family_match and candidate_pages)

    return {
        "searched_oem": searched_oem,
        "normalized_oem": target,
        "expected_family": expected,
        "validated_family": validated_family,
        "family_match": strong_family_match,
        "exact_oem_pages": len(strong_pages),
        "exact_oem_urls": sorted(strong_urls),
        "exact_page_evidence": strong_pages,
        "evidence_types": evidence_types,
        "supersession_evidence": supersession_evidence,
        "exact_or_crossref_evidence": exact_or_crossref_evidence,
        "safe_fitments": safe_fitments,
        "safe_fitment_rows": len(safe_fitments),
        "candidate_family": candidate_family,
        "candidate_family_match": candidate_family_match,
        "candidate_pages": candidate_pages,
        "candidate_urls": sorted(candidate_urls),
        "candidate_fitments": candidate_fitments,
        "candidate_fitment_rows": len(candidate_fitments),
        "catalog_mapped_candidate": catalog_mapped_candidate,
        "candidate_urls_checked": min(len(candidates), max_urls),
        "errors": errors[:5],
    }
