#!/usr/bin/env python3
"""Research source-registered parts without requiring, creating or approving prices.

Only explicitly admitted source references run. OCR/ambiguous tokens and supplier
SKUs without OEM mapping remain visible review tasks. Results are initial evidence,
not a claim of exhaustive Cars245 coverage or approved supplier-brand fitment.
"""
import argparse,json,os,re,sys,time
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

def eligible(row):
    part=re.sub(r'[^A-Z0-9]','',str(row.get('Part_Number','')).upper())
    return (row.get('Status')=='Pending' and row.get('Source_Confidence')=='Source Confirmed'
            and 4<=len(part)<=18 and len(part)!=17 and sum(c.isdigit() for c in part)>=3
            and not part.startswith('APT') and int(row.get('Attempt_Count') or 0)<2)

def main():
    from tools.enrich_ai_fitment_backlog import (catalog_priority,run_research,classify_payload,product_id_for_target,write_identifier,write_fitments)
    from tools.upsert_verified_fitment import svc,read_table,batch_update_fields,append_row,stable_id,norm,parse_fitment
    p=argparse.ArgumentParser();p.add_argument('--max-items',type=int,default=3);p.add_argument('--max-catalogs',type=int,default=2);p.add_argument('--scan-only',action='store_true');a=p.parse_args()
    s=svc();hq,rq=read_table(s,'71_Part_Enrichment_Queue','X')
    pending=sorted([(rn,r) for rn,r in rq if eligible(r)],key=lambda x:(int(x[1].get('Priority') or 100),x[1].get('Part_Number','')))
    summary={'queue_rows':len(rq),'pending':len(pending),'processed':[],'price_writes':0,'customer_feed_writes':0}
    out=ROOT/'automation_output';out.mkdir(exist_ok=True)
    if a.scan_only:
        summary['preview']=[{'part':r['Part_Number'],'priority':r.get('Priority')} for _,r in pending[:10]]
        (out/'source_part_queue_report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary));return
    h38,r38=read_table(s,'38_Product_Identifiers','Q');h39,r39=read_table(s,'39_Vehicle_Fitment','U');h43,r43=read_table(s,'43_Sync_Audit','V')
    started=time.monotonic();today=datetime.now(timezone.utc).strftime('%Y-%m-%d')
    for rn,row in pending[:a.max_items]:
        if time.monotonic()-started>2400:break
        target=row['Part_Number'];fake={'Part_Number':target,'OEM_Number':target,'Brand':row.get('Brand_Hint',''),'Part_Name':row.get('Description_Hint',''),'Description':row.get('Description_Hint','')}
        order=catalog_priority(fake,target);hint=row.get('Catalog_Hint','')
        if hint:order=[hint]+[x for x in order if x!=hint]
        best=None;attempts=[]
        for cat in order[:a.max_catalogs]:
            try:
                folder=out/('source_parts/'+norm(target)+'_'+cat);folder.parent.mkdir(parents=True,exist_ok=True)
                payload=run_research(fake,target,cat,folder);mode,rows=classify_payload(payload)
                # Source-only imports never create unconditional/AI-safe claims.
                if mode=='AI_SAFE':mode='STRONG_REVIEW'
                rank={'NO_FITMENT_EVIDENCE':0,'CANDIDATE_REVIEW':1,'STRONG_REVIEW':2}[mode]
                attempts.append({'catalog':cat,'mode':mode,'rows':len(rows)})
                if best is None or (rank,len(rows))>(best[0],len(best[3])):best=(rank,cat,mode,rows,payload)
                if rank>=1:break
            except Exception as exc:attempts.append({'catalog':cat,'error':str(exc)[:180]})
        now=datetime.now(timezone.utc).isoformat(timespec='seconds');fields={'Attempt_Count':int(row.get('Attempt_Count') or 0)+1,'Last_Attempt_At':now,'Last_Updated_At':today,'Research_Run':os.getenv('GITHUB_RUN_ID','local')}
        created=0
        if best and best[0]>0:
            _,cat,mode,raw,payload=best;pid=product_id_for_target(r38,target)
            write_identifier(s,h38,r38,pid,target,cat,mode,today)
            created=write_fitments(s,h39,r39,pid,target,mode,raw,today)
            for rawrow in raw:
                f=parse_fitment(rawrow)
                r39.append((0,{'Product_ID':pid,'Vehicle_Make':f['make'],'Vehicle_Model':f['model'],'Engine_Code':f['engine_code'],'Year_From':f['year_from'],'Year_To':f['year_to'],'PR_Code':f['pr']}))
            urls=sorted({str(x.get('source_url','')) for x in raw if x.get('source_url')})
            fields.update(Status='Evidence Collected - Review Required',Research_Mode=mode,Resolved_Family=payload.get('automation_gate',{}).get('validated_family') or payload.get('automation_gate',{}).get('candidate_family',''),Fitments_Created=created,Identifiers_Updated=1,Research_Source_URLs='; '.join(urls),Coverage_Status='Initial evidence only - full source coverage not certified',Next_Action='Review manufacturer/OEM mapping and complete source coverage; approve technical application separately',Review_Reason='Source identity and technical evidence retained; no price, stock or customer-display approval')
        else:
            fields.update(Status='Research Review Required',Research_Mode='NO_EVIDENCE' if best else 'ERROR',Coverage_Status='Unresolved - not complete',Next_Action='Review catalog, original part number and source image; retry only after correcting input',Review_Reason='No usable exact/source-supported fitment from attempted catalogs')
        batch_update_fields(s,'71_Part_Enrichment_Queue',hq,[(rn,fields)],False)
        summary['processed'].append({'queue_id':row['Queue_ID'],'part':target,'status':fields['Status'],'fitments_created':created,'attempts':attempts})
    now=datetime.now(timezone.utc)
    append_row(s,'43_Sync_Audit',h43,{'Audit_ID':stable_id('AUD-SOURCE-QUEUE',os.getenv('GITHUB_RUN_ID','local'),now.isoformat()),'Sync_Date':today,'Sync_Time':now.strftime('%H:%M:%S UTC'),'Source_System':'KANO SOURCE PART ENRICHMENT','Destination_System':'ELKADY CRM','Entity_Type':'Source Part Research Queue','Operation':'Research without prices','Source_Record_ID':os.getenv('GITHUB_RUN_ID','local'),'Sync_Status':'Success','Records_Read':len(summary['processed']),'Records_Created':sum(x['fitments_created'] for x in summary['processed']),'Records_Updated':len(summary['processed']),'Records_Failed':0,'Executed_By':'GitHub Actions','Batch_ID':'KANO-SOURCE-PART-QUEUE','Validation_Status':'Source gates retained; no customer-price writes','Notes':'Initial research only; full coverage and supplier-brand approval remain separate.'},False)
    # Artifacts contain summaries only, never the source chat or personal context.
    (out/'source_part_queue_report.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
