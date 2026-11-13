import argparse
import json
import openpyxl
from pathlib import Path

parser = argparse.ArgumentParser(description='Převede pracovní list adres na lokální JSON.')
parser.add_argument('workbook')
parser.add_argument('output')
args = parser.parse_args()
book = openpyxl.load_workbook(args.workbook, read_only=True, data_only=True)
sheet = book['List1']
rows = sheet.iter_rows(values_only=True)
headers = next(rows)
if str(headers[0]).strip() != '#' or not str(headers[2]).startswith('Adresa'):
    raise ValueError('Neočekávané sloupce zdrojového souboru.')
customers = []
for row in rows:
    if not row[0] or not row[1]:
        continue
    customers.append({'issue_id': int(row[0]), 'name': str(row[1]).strip(), 'address': str(row[2]).strip() if row[2] else '', 'poe': str(row[3]).strip() if row[3] else ''})
Path(args.output).write_text(json.dumps(customers, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Připraveno {len(customers)} záznamů; bez adresy {sum(not c["address"] for c in customers)}.')
