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
        (("مساعد", "shock absorber", "shock absorbers", "suspension strut", "strut"), "shock-absorber"),
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
    slug = urlparse(str(item.get("url", ""))).path.lower()
    for label, family in TYPE_FAMILY.items():
        if label.replace(" ", "-") in slug:
            return family
    return ""


def _reference_blocks(soup: BeautifulSoup):
    needles = ("oe number", "oem", "original number", "cross reference", "replacement", "replaces", "replaced by")
    for node in soup.find_all(["tr", "li", "section", "div", "p"]):
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
        low = text.lower()
        if text and len(text) <= 2500 and any(x in low for x in needles):
            yield text


def exact_oem_evidence(html: str, url: str, searched_oem: str) -> tuple[bool, str]:
    target = norm(searched_oem)
    if not target:
        return False, ""
    if target in norm(url):
        return True, "url"
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1 and target in norm(h1.get_text(" ", strip=True)):
        return True, "heading"
    for text in _reference_blocks(soup):
        if target in norm(text):
            return True, "oem_reference_block"
    return False, ""


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

    exact_pages = []
    errors = []
    for url, fam, item in candidates[:max_urls]:
        try:
            r = session.get(url, timeout=30)
            r.raise_for_status()
            ok, evidence = exact_oem_evidence(r.text, url, searched_oem)
            if ok:
                exact_pages.append({
                    "url": url,
                    "family": fam,
                    "evidence": evidence,
                    "brand": item.get("brand", ""),
                    "part_number": item.get("part_number", ""),
                })
        except Exception as exc:
            errors.append(f"{url}: {str(exc)[:120]}")

    family_counts = Counter(x["family"] for x in exact_pages if x["family"])
    validated_family = family_counts.most_common(1)[0][0] if family_counts else ""
    family_match = bool(expected and validated_family == expected)
    exact_urls = {x["url"] for x in exact_pages if x["family"] == validated_family}

    safe_fitments = []
    seen_fit = set()
    for row in report.get("fitments", []):
        source_urls = [x.strip() for x in str(row.get("source_url", "")).split("|") if x.strip()]
        if not source_urls or not any(x in exact_urls for x in source_urls):
            continue
        key = (str(row.get("vehicle_make", "")).upper(), str(row.get("fitment_text", "")).upper())
        if key in seen_fit:
            continue
        seen_fit.add(key)
        safe_fitments.append(row)

    return {
        "searched_oem": searched_oem,
        "normalized_oem": target,
        "expected_family": expected,
        "validated_family": validated_family,
        "family_match": family_match,
        "exact_oem_pages": len(exact_pages),
        "exact_oem_urls": sorted(exact_urls),
        "exact_page_evidence": exact_pages,
        "safe_fitments": safe_fitments,
        "safe_fitment_rows": len(safe_fitments),
        "candidate_urls_checked": min(len(candidates), max_urls),
        "errors": errors[:5],
    }
