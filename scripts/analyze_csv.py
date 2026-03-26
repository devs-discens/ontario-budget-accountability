#!/usr/bin/env python3
import csv
import json

for year, fname in [('2024-25', 'public-accounts-2024-25.csv'), ('2023-24', 'public-accounts-2023-24.csv')]:
    path = f'/home/nphilip/development/ontario/provincial/raw-data/public-accounts/{fname}'
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f'=== {year} ===')
    print(f'Columns: {reader.fieldnames}')
    print(f'Records: {len(rows)}')

    amounts = []
    for r in rows:
        try:
            raw = r.get('Amount $', '').replace(',','').strip()
            amt = int(raw)
            amounts.append((amt, r.get('Recipient',''), r.get('Ministry','')))
        except (ValueError, KeyError):
            pass

    amounts.sort(reverse=True)
    print(f'Parsed amounts: {len(amounts)}')
    if amounts:
        print(f'Min amount: ${amounts[-1][0]:,}')
        print(f'Max amount: ${amounts[0][0]:,}')
    print(f'\nTop 10 recipients:')
    for amt, recip, ministry in amounts[:10]:
        print(f'  ${amt:>15,}  {recip[:60]}  ({ministry})')

    recipients = set(r.get('Recipient','') for r in rows)
    ministries = set(r.get('Ministry','') for r in rows)
    categories = set(r.get('Category','') for r in rows)
    print(f'\nUnique recipients: {len(recipients)}')
    print(f'Unique ministries: {len(ministries)}')
    print(f'Categories: {categories}')
    print()
