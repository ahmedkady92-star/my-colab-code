#!/usr/bin/env python3
"""Enrich Cars245 strict JSON with brake-pad fitment safely.

Only Cars245 brake-pad pages that explicitly reference the searched OEM/part
number are allowed to contribute vehicle fitment. Compatibility parsing is
restricted to the vehicle application section so OE/brand lists above it cannot
be mistaken for a vehicle row.
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path
import requests
from bs4 import BeautifulSoup

HEADERS={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/139 Safari/537.36","Accept-Language":"en-US,en;q=0.9"}
VEHICLE_MAKES=("AUDI","VOLKSWAGEN","VW","SKODA","SEAT","PORSCHE","BENTLEY","BMW","LAND ROVER","JAGUAR")
MAKE_ALT="|".join(sorted((re.escape(x) for x in VEHICLE_MAKES),key=len,reverse=True))
FUEL_RE=r"(?:Petrol/Compressed Natural Gas \(CNG\)|Petrol/Ethanol|Petrol/Electric|Diesel/Electric|Petrol|Diesel|CNG|Electric)"
VEHICLE_ENTRY_RE=re.compile(rf"(?P<entry>\b(?P<make>{MAKE_ALT})\s+(?:(?!\bImportant\s+notes\s*:).){{1,260}}?\b{FUEL_RE}\b\s+\d{{1,2}}(?:[.,]\d+)?\s+\d{{2,4}}\s*hp\s+\d{{2,4}}\s*kw\s+(?P<year_from>(?:19|20)\d{{2}})\s*[-–]\s*(?P<year_to>(?:(?:19|20)\d{{2}}|now|current))\b)",re.I)
NEXT_VEHICLE_RE=re.compile(rf"\b(?:{MAKE_ALT})\s+",re.I)
APP_MARKER_RE=re.compile(r"Brand\s+Model\s+Engine\s+code\s+Fuel\s+Displacement\s+HP\s+KW\s+Year",re.I)

def clean(s): return re.sub(r"\s+"," ",str(s)).strip()
def norm(s): return re.sub(r"[^A-Z0-9]","",str(s).upper())
def normalize_make(make):
    make=make.upper().strip(); return "VOLKSWAGEN" if make=="VW" else make

def is_brake_pad_url(url):
    u=url.lower(); return any(x in u for x in ("brake-pad-set-disc-brake","brake-pads-for-disk-brake","brake-pads-with","brk-lining"))

def page_references_search_part(html,search_part):
    target=norm(search_part)
    if not target: return False
    soup=BeautifulSoup(html,"html.parser")
    return target in norm(" ".join(soup.stripped_strings))

def _following_notes(text,end):
    tail=text[end:end+1400].lstrip(" |:-")
    if not re.match(r"Important\s+notes\s*:",tail,re.I): return ""
    nxt=NEXT_VEHICLE_RE.search(tail,1)
    if nxt: tail=tail[:nxt.start()]
    return clean(tail[:1000])

def extract_text_fitments(html,url):
    soup=BeautifulSoup(html,"html.parser")
    text=clean(" ".join(soup.stripped_strings))
    # Critical safety rule: Cars245 pages can contain long OE/cross-reference
    # lists before the compatibility table. Parse only after the application
    # table header, otherwise an OEM token such as VW can become a fake make.
    marker=APP_MARKER_RE.search(text)
    if not marker:
        return []
    text=text[marker.end():]
    rows=[]; seen=set()
    for m in VEHICLE_ENTRY_RE.finditer(text):
        make=normalize_make(m.group("make")); entry=clean(m.group("entry"))
        # Reject any residual header/cross-reference contamination defensively.
        if "Brand Model Engine code".lower() in entry.lower(): continue
        notes=_following_notes(text,m.end()); combined=entry+(" | "+notes if notes else "")
        key=(make,combined.upper())
        if key in seen: continue
        seen.add(key)
        rows.append({"vehicle_make":make,"year_from":m.group("year_from"),"year_to":m.group("year_to").lower().replace("current","now"),"fitment_text":combined,"source_url":url})
    return rows

def enrich_file(path,session,max_urls):
    data=json.loads(path.read_text(encoding="utf-8")); search_part=str(data.get("search_part","")).strip()
    existing=list(data.get("fitments",[])); seen={(x.get("vehicle_make",""),x.get("fitment_text","").upper()) for x in existing}
    candidate_urls=[]
    for item in data.get("alternatives",[]):
        url=str(item.get("url","")).strip()
        if url and is_brake_pad_url(url) and url not in candidate_urls: candidate_urls.append(url)
    checked=matched=added=0
    for url in candidate_urls:
        if matched>=max_urls: break
        r=session.get(url,timeout=30); r.raise_for_status(); checked+=1
        if not page_references_search_part(r.text,search_part):
            print(f"FITMENT_SKIP {url}: searched_part_not_referenced"); continue
        matched+=1; extracted=extract_text_fitments(r.text,url)
        print(f"FITMENT_URL {url}: matched_search_part=yes extracted={len(extracted)}")
        for row in extracted:
            key=(row["vehicle_make"],row["fitment_text"].upper())
            if key in seen: continue
            seen.add(key); existing.append(row); added+=1
    if matched and data.get("allowed_product_family") in ("",None): data["allowed_product_family"]="brake-pad"
    data["fitments"]=existing; data["fitment_rows_found"]=len(existing)
    data["fitment_enrichment"]={"method":"Cars245 application section on brake-pad pages explicitly referencing searched OEM","candidate_urls_checked":checked,"matched_search_part_urls":matched,"rows_added":added}
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
    return checked,matched,added

def main():
    p=argparse.ArgumentParser(); p.add_argument("--input-dir",default="output"); p.add_argument("--max-urls",type=int,default=8); args=p.parse_args()
    s=requests.Session(); s.headers.update(HEADERS); files=sorted(Path(args.input_dir).glob("*_strict.json"))
    if not files: raise SystemExit("No *_strict.json files found")
    for f in files:
        checked,matched,added=enrich_file(f,s,args.max_urls); print(f"FITMENT_ENRICH {f.name}: checked={checked} matched={matched} added={added}")
if __name__=="__main__": main()
