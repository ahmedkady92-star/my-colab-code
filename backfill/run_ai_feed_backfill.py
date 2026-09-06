#!/usr/bin/env python3
import argparse, csv, json, re, subprocess, sys
from pathlib import Path


def slug(v):
    return re.sub(r'[^A-Z0-9]+','_',v.upper()).strip('_').lower()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',default='backfill/ai_feed_backfill_20260906.csv')
    p.add_argument('--chunk',type=int,required=True)
    p.add_argument('--chunks',type=int,default=6)
    p.add_argument('--output-root',default='backfill-output')
    args=p.parse_args()
    rows=list(csv.DictReader(open(args.input,encoding='utf-8-sig')))
    selected=[r for i,r in enumerate(rows) if i % args.chunks == args.chunk]
    root=Path(args.output_root)/f'chunk-{args.chunk}'
    root.mkdir(parents=True,exist_ok=True)
    summary=[]
    for r in selected:
        q=r['query_part'].strip(); brand=r['brand_route'].strip(); d=root/slug(q); d.mkdir(parents=True,exist_ok=True)
        cmd=[sys.executable,'cars245_multibrand.py',brand,q,'--max-products','15','--delay','0.1','--output-dir',str(d)]
        item={'feed_ids':r['feed_ids'],'brand_route':brand,'query_part':q,'expected_family':r['expected_family'],'original_part':r['original_part'],'oem_number':r['oem_number'],'product_brand':r['product_brand'],'part_name':r['part_name'],'vehicle_make':r['vehicle_make'],'vehicle_model':r['vehicle_model']}
        try:
            cp=subprocess.run(cmd,text=True,capture_output=True,timeout=240)
            item['parser_returncode']=cp.returncode; item['parser_stdout']=cp.stdout[-3000:]; item['parser_stderr']=cp.stderr[-3000:]
            files=list(d.glob('*_strict.json'))
            if cp.returncode==0 and len(files)==1:
                data=json.load(open(files[0],encoding='utf-8'))
                if data.get('allowed_product_family')=='brake-pad':
                    ep=subprocess.run([sys.executable,'cars245_fitment_enrich.py','--input-dir',str(d),'--max-urls','6'],text=True,capture_output=True,timeout=240)
                    item['enrich_returncode']=ep.returncode; item['enrich_stdout']=ep.stdout[-3000:]; item['enrich_stderr']=ep.stderr[-3000:]
                    data=json.load(open(files[0],encoding='utf-8'))
                item.update({k:data.get(k) for k in ['product_links_found','allowed_product_family','alternatives_found','oem_refs','fitment_rows_found','fitment_enrichment']})
                expected=r['expected_family'].strip()
                if not data.get('product_links_found'):
                    item['preliminary_status']='Not Found'
                elif not expected:
                    item['preliminary_status']='Review Required'
                elif data.get('allowed_product_family')!=expected:
                    item['preliminary_status']='Review Required'
                    item['review_reason']='part-family mismatch'
                else:
                    item['preliminary_status']='Candidate - validate fitment'
            else:
                item['preliminary_status']='Review Required'; item['review_reason']='parser failed or output missing'
        except Exception as e:
            item['preliminary_status']='Review Required'; item['review_reason']=f'{type(e).__name__}: {e}'
        summary.append(item)
    json.dump(summary,open(root/'summary.json','w',encoding='utf-8'),ensure_ascii=False,indent=2)
    with open(root/'summary.csv','w',encoding='utf-8-sig',newline='') as f:
        fields=['feed_ids','brand_route','query_part','expected_family','product_links_found','allowed_product_family','alternatives_found','fitment_rows_found','preliminary_status','review_reason']
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(summary)
    print(json.dumps({'chunk':args.chunk,'selected':len(selected),'output':str(root)},ensure_ascii=False))

if __name__=='__main__': main()
