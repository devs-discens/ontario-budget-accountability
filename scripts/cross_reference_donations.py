#!/usr/bin/env python3
"""
Elections Ontario Contributions Cross-Reference Tool
=====================================================
Cross-references Ontario political contribution data against tracked people
and organizations in our audit.

Data source:
  Downloaded from: https://finances.elections.on.ca/api/bulk-data/download?downloadToken=CS-en-AllYears
  File: raw-data/elections-ontario/Filed_Statement_Contributions.csv

  Bulk data API: https://finances.elections.on.ca/api/bulk-data
  Returns download tokens for each year and category.
  Categories: CS (Contribution Statements), RTD (likely Registration/Third-party Data)

CSV columns:
  Contributor, Recipient, Recipient Type, Electoral District, Party Abbreviation,
  Party Name, Event, Year, Data Source, Statement Type, Amount, Deposit Date,
  Disclosure Received, Aggregate Amount

Usage:
    # Download latest data (run when you need to refresh)
    python3 scripts/cross_reference_donations.py download

    # Cross-reference tracked people/orgs against contributions
    python3 scripts/cross_reference_donations.py crossref

    # Search for a specific contributor name
    python3 scripts/cross_reference_donations.py search "Gilgan"

    # Show all PC party donations above a threshold
    python3 scripts/cross_reference_donations.py pc [min_amount]

LIMITATIONS:
    - Corporate donations were banned in Ontario in September 2017.
      Pre-2017 donations include both personal and corporate contributions.
      Post-2017 donations are personal only (max $1,675/year).
    - The Elections Ontario CSV uses "Contributor" field which may be formatted
      as "LAST, FIRST" or "FIRSTNAME LAST" inconsistently.
    - "Ontario Proud" donations are NOT in this dataset. Ontario Proud is a
      third-party advertiser, not a political party, and uses a separate registry.

All paths are relative to the project root (provincial/).
"""

import argparse
import csv
import json
import os
import re
import sys
import urllib.request
import zipfile
import io
from collections import defaultdict

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
RAW_DATA_DIR = os.path.join(PROJECT_DIR, "raw-data", "elections-ontario")
AUDIT_DATA_DIR = os.path.join(PROJECT_DIR, "audits", "2025-26", "data")
CSV_PATH = os.path.join(RAW_DATA_DIR, "Filed_Statement_Contributions.csv")
OUTPUT_PATH = os.path.join(RAW_DATA_DIR, "cross_reference_results.json")

# Bulk download API
BULK_DATA_API = "https://finances.elections.on.ca/api/bulk-data"
BULK_DOWNLOAD_URL = "https://finances.elections.on.ca/api/bulk-data/download?downloadToken={token}"

# PC Party abbreviation in the data
PC_ABBREVIATIONS = {"PC", "PCP", "OPC"}  # Progressive Conservative Party of Ontario

# Names to search for (last name fragments, case-insensitive)
# Each entry: (search_term, description, who_they_are)
TRACKED_NAMES = [
    ("Gilgan", "Peter Gilgan / Mattamy Homes founder"),
    ("De Gasperis", "TACC / De Gasperis family (Greenbelt)"),
    ("Gasperis", "TACC / De Gasperis family alt spelling"),
    ("Fidani", "Nico Fidani-Diker / CMC Microsystems (Greenbelt)"),
    ("Remtulla", "Amir Remtulla (lobbyist, former Rob Ford CoS)"),
    ("Teneycke", "Kory Teneycke (Rubicon Strategy, Ford campaign mgr)"),
    ("Byrne", "Jenni Byrne (lobbyist, former Principal Secretary)"),
    ("Massoudi", "Amin Massoudi (Atlas Strategic Advisors)"),
    ("Lawson", "Mark Lawson (former Deputy CoS, Therme/Billy Bishop)"),
    ("Saunders", "Mark Saunders (Ontario Place special advisor)"),
    ("Miele", "Tony Miele (TACC Developments)"),
    ("Manziuk", "John Manziuk (various Ford-era connections)"),
    ("Rinaldi", "Rinaldi family (PC donors)"),
    ("Paletta", "Paletta family (Greenbelt developers)"),
    ("Silvio De Gasperis", "TACC founder"),
    ("Anthony De Gasperis", "TACC executive"),
    ("Marco De Gasperis", "TACC executive"),
    ("Harris Mike", "Mike Harris (Chartwell, former Premier)"),
    ("Harris, Mike", "Mike Harris alt format"),
]


def parse_amount(amount_str):
    """Parse '$1,234.56' -> 1234.56"""
    if not amount_str or amount_str.strip() in ('', '-', 'N/A'):
        return 0.0
    cleaned = re.sub(r'[,$]', '', amount_str.strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def load_csv():
    """Load the contributions CSV, yielding row dicts."""
    if not os.path.exists(CSV_PATH):
        print(f"ERROR: CSV not found at {CSV_PATH}", file=sys.stderr)
        print("Run: python3 scripts/cross_reference_donations.py download", file=sys.stderr)
        sys.exit(1)

    with open(CSV_PATH, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            yield row


def cmd_download(args):
    """Download the latest bulk contributions data from Elections Ontario."""
    os.makedirs(RAW_DATA_DIR, exist_ok=True)

    print("Fetching bulk data index from Elections Ontario...")
    headers = {
        'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)',
        'Accept': 'application/json',
        'Referer': 'https://finances.elections.on.ca/en/bulk-data'
    }
    req = urllib.request.Request(BULK_DATA_API, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        index = json.loads(r.read())

    print(f"Available categories: {[d['category'] for d in index]}")
    for category in index:
        print(f"\nCategory: {category['category']}")
        for f in category['files']:
            print(f"  {f['name']}: {f['fileSizeKb']} KB  (token: {f['downloadToken']})")

    # Download CS (Contribution Statements) All Years
    cs_all = None
    for category in index:
        if category['category'] == 'CS':
            for f in category['files']:
                if f['name'] == 'All Years':
                    cs_all = f
                    break

    if not cs_all:
        print("ERROR: Could not find 'CS All Years' download token", file=sys.stderr)
        sys.exit(1)

    token = cs_all['downloadToken']
    size_kb = cs_all['fileSizeKb']
    url = BULK_DOWNLOAD_URL.format(token=token)

    print(f"\nDownloading {token} (~{size_kb} KB compressed)...")
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Accept': '*/*',
        'Referer': 'https://finances.elections.on.ca/en/bulk-data'
    })
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()

    print(f"Downloaded {len(data):,} bytes (zip)")

    z = zipfile.ZipFile(io.BytesIO(data))
    for name in z.namelist():
        outpath = os.path.join(RAW_DATA_DIR, name.replace('/', '_'))
        with open(outpath, 'wb') as f:
            f.write(z.read(name))
        print(f"Extracted: {outpath} ({os.path.getsize(outpath):,} bytes)")

    print("\nDone. Run 'crossref' to cross-reference against tracked people.")


def cmd_search(args):
    """Search for a contributor name in the CSV."""
    query = args.query.lower()
    matches = []

    for row in load_csv():
        contributor = row.get('Contributor', '').lower()
        if query in contributor:
            matches.append(row)

    if not matches:
        print(f"No results for '{args.query}'")
        return

    # Group by party
    by_party = defaultdict(list)
    for m in matches:
        party = m.get('Party Name', m.get('Party Abbreviation', 'Unknown'))
        by_party[party].append(m)

    print(f"\n{len(matches)} contributions by contributors matching '{args.query}':\n")
    for party, rows in sorted(by_party.items(), key=lambda x: -sum(parse_amount(r.get('Amount', '0')) for r in x[1])):
        total = sum(parse_amount(r.get('Amount', '0')) for r in rows)
        print(f"  {party}: {len(rows)} contributions, total ${total:,.2f}")
        for r in sorted(rows, key=lambda x: -parse_amount(x.get('Amount', '0')))[:10]:
            print(f"    {r.get('Year','?')} | {r.get('Contributor','?')[:40]} -> {r.get('Recipient','?')[:40]} | ${parse_amount(r.get('Amount','0')):,.2f}")


def cmd_pc(args):
    """Show PC Party donations above threshold."""
    min_amount = float(args.min_amount) if hasattr(args, 'min_amount') and args.min_amount else 1000.0

    pc_donations = []
    for row in load_csv():
        abbrev = row.get('Party Abbreviation', '').upper().strip()
        if abbrev not in PC_ABBREVIATIONS:
            continue
        amount = parse_amount(row.get('Amount', '0'))
        if amount < min_amount:
            continue
        pc_donations.append(row)

    # Sort by amount descending
    pc_donations.sort(key=lambda r: -parse_amount(r.get('Amount', '0')))

    print(f"\nPC Party donations >= ${min_amount:,.0f}: {len(pc_donations)} contributions\n")
    for r in pc_donations[:50]:
        amt = parse_amount(r.get('Amount', '0'))
        print(f"  {r.get('Year','?')} | ${amt:>10,.2f} | {r.get('Contributor','?')[:45]} -> {r.get('Recipient','?')[:35]}")


def cmd_crossref(args):
    """Cross-reference tracked people/orgs against contribution data."""
    # Load tracked people and organizations
    with open(os.path.join(AUDIT_DATA_DIR, 'people.json')) as f:
        people_data = json.load(f)
    with open(os.path.join(AUDIT_DATA_DIR, 'organizations.json')) as f:
        orgs_data = json.load(f)

    # Build search terms from people.json
    search_terms = list(TRACKED_NAMES)  # Start with manually curated list

    # Add all people from people.json
    for person in people_data.get('people', []):
        name = person.get('name', '')
        if name:
            # Add last name as search term
            parts = name.split()
            if len(parts) >= 2:
                last_name = parts[-1]
                if len(last_name) > 3:  # avoid short names
                    search_terms.append((last_name, f"From people.json: {name}"))

    # Collect all PC contributions (for name matching)
    print("Loading contributions data...")
    all_contributions = []
    pc_only = []
    for row in load_csv():
        all_contributions.append(row)
        abbrev = row.get('Party Abbreviation', '').upper().strip()
        if abbrev in PC_ABBREVIATIONS:
            pc_only.append(row)

    print(f"Total contributions: {len(all_contributions):,}")
    print(f"PC Party contributions: {len(pc_only):,}")

    # Build contributor index (lowercase -> rows)
    contributor_index = defaultdict(list)
    for row in all_contributions:
        contrib_lower = row.get('Contributor', '').lower()
        contributor_index[contrib_lower].append(row)

    results = {}

    for search_term, description in search_terms:
        search_lower = search_term.lower()
        matches = []
        for contrib_name, rows in contributor_index.items():
            if search_lower in contrib_name:
                matches.extend(rows)

        if not matches:
            continue

        # Group by party
        by_party = defaultdict(lambda: {'count': 0, 'total': 0.0, 'rows': []})
        for row in matches:
            party = row.get('Party Abbreviation', 'UNK').upper().strip()
            party = party if party else 'UNK'
            amount = parse_amount(row.get('Amount', '0'))
            by_party[party]['count'] += 1
            by_party[party]['total'] += amount
            by_party[party]['rows'].append({
                'year': row.get('Year', '?'),
                'contributor': row.get('Contributor', '?'),
                'recipient': row.get('Recipient', '?'),
                'party': row.get('Party Name', '?'),
                'amount': amount
            })

        pc_total = sum(by_party[p]['total'] for p in PC_ABBREVIATIONS if p in by_party)
        all_total = sum(v['total'] for v in by_party.values())

        results[search_term] = {
            'description': description,
            'total_all_parties': round(all_total, 2),
            'total_pc': round(pc_total, 2),
            'by_party': {
                party: {
                    'count': data['count'],
                    'total': round(data['total'], 2),
                    'top_donations': sorted(data['rows'], key=lambda x: -x['amount'])[:5]
                }
                for party, data in by_party.items()
            }
        }

    # Write results
    output = {
        'generated': '2026-03-24',
        'source': 'Elections Ontario bulk data: https://finances.elections.on.ca/api/bulk-data',
        'note': 'Corporate donations banned in Ontario from September 2017. Pre-2017 entries include corporate donors.',
        'results': results
    }
    with open(OUTPUT_PATH, 'w') as f:
        json.dump(output, f, indent=2)
    print(f"\nResults saved to: {OUTPUT_PATH}")

    # Print summary
    print("\n=== CROSS-REFERENCE RESULTS ===\n")
    pc_found = [(term, data) for term, data in results.items() if data['total_pc'] > 0]
    pc_found.sort(key=lambda x: -x[1]['total_pc'])

    for term, data in pc_found:
        print(f"{term} ({data['description'][:50]})")
        print(f"  PC total: ${data['total_pc']:>10,.2f}  |  All parties: ${data['total_all_parties']:,.2f}")
        if 'PC' in data['by_party']:
            for d in data['by_party']['PC']['top_donations'][:3]:
                print(f"    {d['year']} | ${d['amount']:>9,.2f} | {d['contributor'][:40]} -> {d['recipient'][:30]}")
        print()


def main():
    parser = argparse.ArgumentParser(description='Elections Ontario cross-reference tool')
    subparsers = parser.add_subparsers(dest='command')

    dl_parser = subparsers.add_parser('download', help='Download bulk contributions data')

    search_parser = subparsers.add_parser('search', help='Search by contributor name')
    search_parser.add_argument('query', help='Name to search for')

    pc_parser = subparsers.add_parser('pc', help='Show large PC Party donations')
    pc_parser.add_argument('min_amount', nargs='?', default='5000', help='Minimum amount (default: 5000)')

    crossref_parser = subparsers.add_parser('crossref', help='Cross-reference tracked people/orgs')

    args = parser.parse_args()

    if args.command == 'download':
        cmd_download(args)
    elif args.command == 'search':
        cmd_search(args)
    elif args.command == 'pc':
        cmd_pc(args)
    elif args.command == 'crossref':
        cmd_crossref(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == '__main__':
    main()
