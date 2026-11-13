"""Offline suggestions from an official, locally downloaded RÚIAN CSV ZIP.
Requires pyproj. Results are suggestions requiring human verification.
"""
import argparse
import csv
import io
import json
import re
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path
from pyproj import Transformer

def norm(value):
    return re.sub(r'[^a-z0-9]+', '', unicodedata.normalize('NFKD', value.casefold()).encode('ascii', 'ignore').decode())

def parse_address(address):
    parts = address.split(',')
    if len(parts) < 2:
        return None
    m = re.fullmatch(r'\s*(.*?)\s+(\d+)(?:/(\d+\s*[a-zA-Z]?))?\s*', parts[0])
    psc = re.search(r'\b(\d{3})\s*(\d{2})\b', ','.join(parts[1:]))
    if not m or not psc:
        return None
    return norm(m[1]), m[2], norm(m[3] or ''), ''.join(psc.groups())

def run(customers, archive):
    desired = defaultdict(list)
    for c in customers:
        parsed = parse_address(c.get('address', ''))
        if parsed:
            desired[(parsed[0],parsed[3])].append((c,parsed[1],parsed[2]))
    matches = defaultdict(list)
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if not name.lower().endswith('.csv'): continue
            with z.open(name) as raw:
                reader = csv.reader(io.TextIOWrapper(raw, encoding='cp1250', newline=''), delimiter=';')
                next(reader, None)
                for row in reader:
                    if len(row) < 19 or not row[16] or not row[17]: continue
                    key=(norm(row[10] or row[8]), row[15].replace(' ',''))
                    for c,house,orient in desired.get(key, []):
                        number_ok = row[12] == house and (not orient or norm(row[13]+row[14]) == orient)
                        # A single number may denote either house or orientation number.
                        if not orient and norm(row[13]+row[14]) == house: number_ok = True
                        if number_ok:
                            matches[c['issue_id']].append(row)
    date_match = re.search(r'(\d{4})(\d{2})(\d{2})', Path(archive).name)
    date = '-'.join(date_match.groups()) if date_match else 'datum nezjištěn'
    transformer=Transformer.from_crs('EPSG:5514','EPSG:4326',always_xy=True)
    for c in customers:
        rows=matches[c['issue_id']]
        if len(rows)==1:
            row=rows[0]
            lon,lat=transformer.transform(-float(row[16].replace(',','.')), -float(row[17].replace(',','.')))
            if 48 <= lat <= 52 and 12 <= lon <= 19:
                c['candidate_location']=[round(lat,6),round(lon,6)]
                c['candidate_source']=f'RÚIAN {date} · shoda ulice/části obce, čísla a PSČ; ověřit'
                c['candidate_ruian_id']=row[0]
    return customers

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('customers');p.add_argument('archive');p.add_argument('output');args=p.parse_args()
    data=json.loads(Path(args.customers).read_text(encoding='utf-8'))
    data=run(data,args.archive)
    Path(args.output).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Jednoznačných kandidátů k ověření:',sum('candidate_location' in c for c in data),'z',len(data))
