#!/usr/bin/env python3
"""Extract source references without inferring commercial quotes or stock.

OCR-only references remain review candidates until independently supported.
Use stable source line IDs so repeated imports reconcile, rather than duplicate.
"""
import re,hashlib
from datetime import datetime
from urllib.parse import unquote
N=lambda v:re.sub(r'[^A-Z0-9]','',str(v or '').upper())

BRANDS={'ICER','METELLI','METELI','NGK','BOSCH','TRW','ATE','HF','APT','BBS','SWAG','FEBI','SACHS','LUCAS','MOPRO','VALENCIA','DENCKERMANN','DENKERMANN','GLASER','NISSENS','LEMFOERDER','LEMFORDER','ORIGINAL','OEM','VALEO','BERU','ELRING','TOPRAN'}

MPN_PREFIXES=('GDB','FDB','DMB','JTS','JTC','JRP','JAR','SKV','BKR','ZFR','PFR','FR','OE','A21','LP','ADG','ADJ','AC','X90')

PHONE=re.compile(r'(?<!\d)(?:\+?20[\s-]?)?0?1[0125](?:[\s-]?\d){8}(?!\d)')

VIN=re.compile(r'(?<![A-Z0-9])[A-HJ-NPR-Z0-9]{17}(?![A-Z0-9])',re.I)

MEDIA=re.compile(r'(?:IMG|VID|PTT|AUD|DOC)[-_]\d{8}[-_]WA\d+\.[a-z0-9]+',re.I)

PATTERNS=[
 ('OEM-LR',re.compile(r'(?<![A-Z0-9])L\s*R[\s.\-]*\d{6}(?![A-Z0-9])',re.I)),
 ('OEM-Jaguar',re.compile(r'(?<![A-Z0-9])(?:C2[CDPSZ]|T2[HPR]|JDE|J9C|XR)\s*\d{4,7}(?![A-Z0-9])',re.I)),
 ('OEM-JLR-Legacy',re.compile(r'(?<![A-Z0-9])(?:RNB|RPD|RNH|RQH|ANR|STC|SRB|FRC|LRB|QFS)\s*\d{5,6}(?![A-Z0-9])',re.I)),
 ('OEM-Mercedes',re.compile(r'(?<![A-Z0-9])A\s*\d{3}[\s.\-]*\d{3}[\s.\-]*\d{2}[\s.\-]*\d{2}(?![A-Z0-9])',re.I)),
 ('OEM-VAG',re.compile(r'(?<![A-Z0-9])(?:[0-9][A-Z0-9]{2}|P[A-Z]{2})[\s.]*\d{3}[\s.]*\d{3}(?:[A-Z]{1,6}[0-9]?|[\s.]+[A-Z]{1,3}[0-9]?)?(?![A-Z0-9])',re.I)),
 ('OEM-Fluid',re.compile(r'(?<![A-Z0-9])G[\s.]*\d{3}[\s.]*\d{3}[\s.]*[A-Z]\d(?![A-Z0-9])',re.I)),
 ('OEM-Numeric11',re.compile(r'(?<![A-Z0-9+])(?:\d{3}[\s.]*\d{3}[\s.]*\d{3}[\s.]*\d{2}|\d{2}[\s.]+\d{2}[\s.]+\d[\s.]+\d{3}[\s.]+\d{3})(?![A-Z0-9])',re.I)),
 ('Reference-Segmented',re.compile(r'(?<![A-Z0-9])(?:\d{2}[-.]\d{4}[-.]\d|P\s+\d{2}\s+\d{3}|\d{4,8}(?:[-/]\d{1,4})+)(?![A-Z0-9]|[-/][A-Z0-9])',re.I)),
 ('Reference-ShortMPN',re.compile(r'(?<![A-Z0-9])[A-Z]{1,3}\d{3,6}(?![A-Z0-9]|[-/][A-Z0-9])',re.I)),
 ('Reference-Mixed',re.compile(r'(?<![A-Z0-9])(?=[A-Z0-9\-/]{5,18}(?![A-Z0-9]))(?=[A-Z0-9\-/]*[A-Z])(?=[A-Z0-9\-/]*\d)[A-Z0-9]+(?:[-/][A-Z0-9]+)*(?![A-Z0-9])',re.I)),
 ('Reference-LooseNumeric',re.compile(r'(?<![A-Z0-9+])\d{9,13}(?![A-Z0-9])',re.I)),
 ('Reference-Numeric',re.compile(r'(?<![A-Z0-9+])\d{6,8}(?![A-Z0-9])',re.I))]

def normalize_unicode(t):return str(t).translate(str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹','01234567890123456789'))

def extract_references(text,source_type="CHAT_TEXT",explicit_code_column=False,known_parts=()):
 known_set=set(known_parts)
 text=normalize_unicode(unquote(str(text)))
 text=MEDIA.sub(' ',text)
 negatives=[(m.start(),m.end(),'PHONE') for m in PHONE.finditer(text)]+[(m.start(),m.end(),'VIN') for m in VIN.finditer(text)]
 spans=[];out=[]
 for kind,pat in PATTERNS:
  for m in pat.finditer(text):
   a,b=m.span();raw=m[0].strip();code=N(raw)
   if any(a<y and b>x for x,y in spans):continue
   if any(a<y and b>x for x,y,_ in negatives):continue
   if not 4<=len(code)<=18 or len(code)==17 or sum(c.isdigit() for c in code)<3:continue
   # Do not turn date/phone fragments, filenames, currency, car descriptions or
   # commercial 'brand+price' strings into new part numbers.
   if code.startswith(('IMG','VID','WA','HTTP','HTTPS','WWW','PTT','AUD','EK')):continue
   if re.fullmatch(r'(?:L\d{3}|W\d{3}|EA\d{3}|MK\d+|BMW\d+)',code):continue
   if re.fullmatch(r'(19|20)\d{6}',code):continue
   if any(code.startswith(br) and code[len(br):].isdigit() and len(code[len(br):])<=5 for br in BRANDS):continue
   if re.fullmatch(r'\d+(?:HP|KW|EGP|USD|EUR|CC|TDI|TSI|TFSI)',code):continue
   if kind=='OEM-VAG':
    last=raw.split()[-1].upper()
    if last in BRANDS and len(raw.split())>1:
     raw=raw[:raw.upper().rfind(last)].strip();code=N(raw)
    if code.isdigit() and code not in known_set:kind='Reference-Numeric'
   if kind=='OEM-Numeric11':
    allowed={'11','12','13','16','17','18','21','22','23','24','26','27','28','31','32','33','34','35','36','37','41','51','52','53','54','61','62','63','64','65','66','67','71','72','73','81','82','83','84','85','94','95','96','97','98','99'}
    if len(code)!=11 or code[:2] not in allowed:continue
   context=text[max(0,a-80):min(len(text),b+80)]
   if code.isdigit() and re.search(r'حساب|فاتور|تليفون|تلفون|موبايل|واتس|شاسيه|رقم\s*السري|verification|password|phone|invoice|iban|account|VIN',context,re.I):continue
   known=code in known_set
   trusted=kind.startswith('OEM-')
   if kind=='Reference-Segmented':trusted=known or explicit_code_column or bool(re.fullmatch(r'\d{2}[-.]\d{4}[-.]\d|P\s+\d{2}\s+\d{3}',raw,re.I)) or any(re.search(r'\b'+re.escape(br)+r'\b',context,re.I) for br in BRANDS)
   if kind=='Reference-ShortMPN':
    trusted=known or code.startswith(MPN_PREFIXES) or explicit_code_column
    if not trusted and source_type=='IMAGE_OCR':continue
   if kind=='Reference-LooseNumeric':
    if len(code)==13 or code.startswith(('0','20')):continue
    if not (known or explicit_code_column or text.strip()==raw or re.search(r'(?:part|oem|article|رقم\s*القطعه|كود)',context,re.I)):continue
    trusted=known or explicit_code_column
   if kind=='Reference-Mixed':
    if re.fullmatch(r'[A-Z]{1,3}\d{1,3}',code):continue
    trusted=known or code.startswith(MPN_PREFIXES) or bool(explicit_code_column)
    if source_type=='IMAGE_OCR' and not known and (len(code)<7 or sum(c.isdigit() for c in code)<4):continue
   if kind=='Reference-Numeric':
    if not (known or explicit_code_column or re.search(r'(?:part|oem|article|رقم\s*القطعه|رقم\s*القطعة|كود)\s*[:#]?',context,re.I)):continue
    trusted=known or explicit_code_column
   # OCR-only identities always need visual/source verification, even when
   # their character pattern looks like an OEM number.
   if source_type=='IMAGE_OCR':trusted=False
   spans.append((a,b));out.append(dict(code=code,raw=raw,kind=kind,trusted=trusted,context=context))
 return out

def parse_messages(text):
 msgs=[];rx=re.compile(r'^(\d{1,2}/\d{1,2}/\d{2,4}), (\d{1,2}:\d{2}) - (.*)$')
 for ln,line in enumerate(text.splitlines(),1):
  m=rx.match(line)
  if m:
   sender,sep,body=m[3].partition(': ')
   if not sep:body=m[3];sender='SYSTEM'
   try:date=datetime.strptime(m[1],'%m/%d/%y').strftime('%Y-%m-%d')
   except ValueError:date=m[1]
   msgs.append(dict(source_id=f'KANO-TXT-L{ln}',line=ln,date=date,time=m[2],sender=sender,role='OWNER' if sender.startswith('Elkady') else ('SYSTEM' if sender=='SYSTEM' else 'SUPPLIER'),text=body))
  elif msgs:msgs[-1]['text']+='\n'+line
 return msgs

def occurrence_id(source_id,part_number):
 return "KANO-OCC-"+hashlib.sha256((source_id+"|"+N(part_number)).encode()).hexdigest()[:20].upper()
