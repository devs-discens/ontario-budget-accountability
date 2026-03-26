#!/usr/bin/env python3
"""
Sunshine List Cross-Reference Tool

Cross-references Ontario Sunshine List salary disclosure data with our
people.json and appointments.json to find:
  1. Government appointees who later became lobbyists — what were they paid?
  2. People on our appointments list — what are they paid now?

Data sources:
  - GitHub community CSVs (1996-2020): https://github.com/pbeens/Sunshine-List-CSV
  - Ontario Open Data Portal (1996-2022): https://data.ontario.ca/
  - Ontario.ca interactive (2023-2024): HTML only, no bulk CSV

Usage:
    # Step 1: Download data (run once)
    python3 scripts/cross_reference_sunshine.py download

    # Step 2: Cross-reference
    python3 scripts/cross_reference_sunshine.py crossref

    # Step 3: Search for a specific name
    python3 scripts/cross_reference_sunshine.py search "Dean French"

All paths are relative to the project root (provincial/).
"""

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from datetime import date

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "raw-data", "sunshine-list")
PEOPLE_JSON = os.path.join(PROJECT_ROOT, "audits", "2025-26", "data", "people.json")
APPOINTMENTS_JSON = os.path.join(
    PROJECT_ROOT, "audits", "2025-26", "data", "appointments.json"
)
RESULTS_JSON = os.path.join(DATA_DIR, "cross-reference-results.json")

# ---------------------------------------------------------------------------
# Known data sources
# ---------------------------------------------------------------------------

# GitHub community CSVs: pbeens/Sunshine-List-CSV
# File naming convention observed: YYYY.csv (e.g., 1996.csv through 2020.csv)
# These are aggregated from ontario.ca data.
GITHUB_RAW_BASE = (
    "https://raw.githubusercontent.com/pbeens/Sunshine-List-CSV/main"
)
GITHUB_YEARS = list(range(1996, 2021))  # 1996-2020 inclusive

# Ontario Open Data Portal: direct CSV downloads
# These are the official government sources. Resource IDs change per year.
# The pattern is: https://data.ontario.ca/dataset/public-sector-salary-disclosure-YYYY
# Individual CSV resources have UUIDs. The ones below were verified from
# data.ontario.ca as of early 2025. If any fail, the script will skip them
# and log the error.
ONTARIO_DATA_URLS = {
    2021: "https://data.ontario.ca/dataset/public-sector-salary-disclosure-2021",
    2022: "https://data.ontario.ca/dataset/public-sector-salary-disclosure-2022",
}

# 2023-2024: Only available as interactive HTML search on ontario.ca
# NOT available as bulk CSV download.
# URL: https://www.ontario.ca/page/public-sector-salary-disclosure
# 2024: https://www.ontario.ca/public-sector-salary-disclosure/2024/all-sectors-and-seconded-employees/
HTML_ONLY_YEARS = [2023, 2024]

# ---------------------------------------------------------------------------
# Column name normalization
# ---------------------------------------------------------------------------

# Different years and sources use slightly different column names.
# We normalize to a standard set.
COLUMN_ALIASES = {
    "sector": ["sector"],
    "last_name": ["last name", "last_name", "surname", "lastname"],
    "first_name": ["first name", "first_name", "given name", "firstname"],
    "salary": [
        "salary paid",
        "salary_paid",
        "salary",
        "salary paid ($)",
        "salary_paid_in_dollars",
    ],
    "benefits": [
        "taxable benefits",
        "taxable_benefits",
        "benefits",
        "taxable benefits ($)",
        "taxable_benefits_in_dollars",
    ],
    "employer": ["employer", "organization", "employer name"],
    "title": ["title", "position", "job title", "job_title"],
    "year": ["calendar year", "calendar_year", "year"],
}


def normalize_columns(header_row):
    """Map actual CSV column names to our standard names."""
    mapping = {}
    for col_idx, col_name in enumerate(header_row):
        cleaned = col_name.strip().lower().replace("\ufeff", "")
        for standard_name, aliases in COLUMN_ALIASES.items():
            if cleaned in aliases:
                mapping[standard_name] = col_idx
                break
    return mapping


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------


def find_csv_files():
    """Find all Sunshine List CSV files in our data directory."""
    csvs = []
    if not os.path.isdir(DATA_DIR):
        return csvs
    for fname in sorted(os.listdir(DATA_DIR)):
        if fname.endswith(".csv"):
            csvs.append(os.path.join(DATA_DIR, fname))
    # Also check subdirectories (e.g., github-csv/)
    for subdir in sorted(os.listdir(DATA_DIR)):
        subpath = os.path.join(DATA_DIR, subdir)
        if os.path.isdir(subpath):
            for fname in sorted(os.listdir(subpath)):
                if fname.endswith(".csv"):
                    csvs.append(os.path.join(subpath, fname))
    return csvs


def extract_year_from_filename(filepath):
    """Try to extract the disclosure year from the filename."""
    basename = os.path.basename(filepath)
    match = re.search(r"(19|20)\d{2}", basename)
    if match:
        return int(match.group())
    return None


def load_csv(filepath):
    """Load a Sunshine List CSV file, returning normalized records."""
    records = []
    year_from_name = extract_year_from_filename(filepath)

    # Try different encodings
    for encoding in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
        try:
            with open(filepath, "r", encoding=encoding, errors="replace") as f:
                # Sniff delimiter
                sample = f.read(4096)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
                except csv.Error:
                    dialect = csv.excel

                reader = csv.reader(f, dialect)
                header = next(reader, None)
                if not header:
                    return records

                col_map = normalize_columns(header)
                if not col_map:
                    # Could not map any columns — wrong file format
                    return records

                for row in reader:
                    if not row or all(c.strip() == "" for c in row):
                        continue
                    record = {}
                    for std_name, col_idx in col_map.items():
                        if col_idx < len(row):
                            record[std_name] = row[col_idx].strip()
                        else:
                            record[std_name] = ""

                    # Ensure year field
                    if "year" not in record or not record["year"]:
                        record["year"] = str(year_from_name) if year_from_name else ""

                    # Parse salary to float
                    record["salary_num"] = parse_salary(record.get("salary", ""))
                    record["benefits_num"] = parse_salary(
                        record.get("benefits", "")
                    )
                    record["_source_file"] = filepath
                    records.append(record)
            break  # encoding worked
        except UnicodeDecodeError:
            continue

    return records


def parse_salary(val):
    """Parse a salary string like '$123,456.78' to a float."""
    if not val:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", val)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def load_all_sunshine_data():
    """Load all available Sunshine List CSV files."""
    csv_files = find_csv_files()
    all_records = []
    files_loaded = []
    files_failed = []

    for fpath in csv_files:
        try:
            recs = load_csv(fpath)
            if recs:
                all_records.extend(recs)
                files_loaded.append(
                    {"file": fpath, "records": len(recs)}
                )
            else:
                files_failed.append(
                    {"file": fpath, "error": "No records parsed"}
                )
        except Exception as e:
            files_failed.append({"file": fpath, "error": str(e)})

    return all_records, files_loaded, files_failed


# ---------------------------------------------------------------------------
# People & appointments loading
# ---------------------------------------------------------------------------


def load_people():
    """Load people.json."""
    if not os.path.isfile(PEOPLE_JSON):
        print(f"WARNING: {PEOPLE_JSON} not found")
        return []
    with open(PEOPLE_JSON, "r") as f:
        data = json.load(f)
    return data.get("people", [])


def load_appointments():
    """Load appointments.json."""
    if not os.path.isfile(APPOINTMENTS_JSON):
        print(f"WARNING: {APPOINTMENTS_JSON} not found")
        return []
    with open(APPOINTMENTS_JSON, "r") as f:
        data = json.load(f)
    return data.get("appointments", [])


# ---------------------------------------------------------------------------
# Name matching
# ---------------------------------------------------------------------------


def normalize_name(name):
    """Normalize a name for fuzzy matching."""
    name = name.lower().strip()
    # Remove common suffixes/prefixes
    name = re.sub(r"\b(dr|mr|mrs|ms|hon|rt hon)\b\.?", "", name)
    # Remove punctuation except hyphens
    name = re.sub(r"[^a-z\s\-]", "", name)
    # Collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()
    return name


def name_parts(name):
    """Split a name into parts."""
    return normalize_name(name).split()


def match_names(search_name, record_first, record_last):
    """
    Check if a search name matches a Sunshine List record's first/last name.

    Returns a confidence score:
      - 1.0: exact match (first + last)
      - 0.8: last name match + first name initial match
      - 0.0: no match
    """
    parts = name_parts(search_name)
    if len(parts) < 2:
        return 0.0

    rec_first = normalize_name(record_first)
    rec_last = normalize_name(record_last)

    # Try "First Last" order
    search_first = parts[0]
    search_last = parts[-1]

    # Exact match
    if search_first == rec_first and search_last == rec_last:
        return 1.0

    # Handle hyphenated last names
    if "-" in search_last or "-" in rec_last:
        if search_last in rec_last or rec_last in search_last:
            if search_first == rec_first:
                return 0.95

    # Last name match + first initial
    if search_last == rec_last and rec_first and search_first[0] == rec_first[0]:
        return 0.8

    # Middle name situations: "First Middle Last"
    if len(parts) >= 3:
        search_last_2 = parts[-1]
        search_first_2 = parts[0]
        if search_last_2 == rec_last and search_first_2 == rec_first:
            return 1.0

    return 0.0


# ---------------------------------------------------------------------------
# Cross-reference logic
# ---------------------------------------------------------------------------


def cross_reference(people, appointments, sunshine_records):
    """
    Cross-reference people/appointments against Sunshine List data.

    Returns a dict of results keyed by person ID.
    """
    results = {}

    for person in people:
        person_id = person["id"]
        person_name = person["name"]
        person_type = person.get("type", "")

        # Skip if name is clearly not a person's full name
        if "(" in person_name:
            # e.g., "Padulo (Ontario Shipyards CEO)" — not searchable
            continue

        matches = []
        for rec in sunshine_records:
            score = match_names(
                person_name,
                rec.get("first_name", ""),
                rec.get("last_name", ""),
            )
            if score >= 0.8:
                matches.append(
                    {
                        "year": rec.get("year", ""),
                        "employer": rec.get("employer", ""),
                        "title": rec.get("title", ""),
                        "salary": rec.get("salary", ""),
                        "salary_num": rec.get("salary_num", 0),
                        "benefits": rec.get("benefits", ""),
                        "benefits_num": rec.get("benefits_num", 0),
                        "sector": rec.get("sector", ""),
                        "match_confidence": score,
                    }
                )

        if matches:
            # Sort by year descending, then salary descending
            matches.sort(
                key=lambda m: (m.get("year", ""), m.get("salary_num", 0)),
                reverse=True,
            )

            # Determine analysis category
            categories = []
            if person_type in ("lobbyist-insider", "lobbyist"):
                categories.append("government-to-lobbyist")
            if person_type in ("politician", "insider"):
                categories.append("appointee-current-salary")

            # Check if person is on appointments list
            person_appointments = [
                a for a in appointments if a.get("person") == person_id
            ]
            if person_appointments:
                categories.append("government-appointee")

            results[person_id] = {
                "name": person_name,
                "type": person_type,
                "categories": categories,
                "appointments": [
                    {
                        "position": a.get("position", ""),
                        "organization": a.get("organization", ""),
                        "date": a.get("date"),
                    }
                    for a in person_appointments
                ],
                "sunshine_matches": matches,
                "total_matches": len(matches),
                "years_found": sorted(
                    set(m["year"] for m in matches if m["year"]), reverse=True
                ),
            }

    return results


# ---------------------------------------------------------------------------
# Search command
# ---------------------------------------------------------------------------


def search_name(name, sunshine_records):
    """Search for a specific name in the Sunshine List data."""
    matches = []
    for rec in sunshine_records:
        score = match_names(
            name, rec.get("first_name", ""), rec.get("last_name", "")
        )
        if score >= 0.8:
            matches.append(
                {
                    "year": rec.get("year", ""),
                    "first_name": rec.get("first_name", ""),
                    "last_name": rec.get("last_name", ""),
                    "employer": rec.get("employer", ""),
                    "title": rec.get("title", ""),
                    "salary": rec.get("salary", ""),
                    "salary_num": rec.get("salary_num", 0),
                    "benefits": rec.get("benefits", ""),
                    "sector": rec.get("sector", ""),
                    "match_confidence": score,
                }
            )

    matches.sort(
        key=lambda m: (m.get("year", ""), m.get("salary_num", 0)),
        reverse=True,
    )
    return matches


# ---------------------------------------------------------------------------
# Download helper
# ---------------------------------------------------------------------------


def download_data():
    """
    Download Sunshine List CSV data.

    Uses curl to fetch files. This function is a helper — if it fails,
    see DATA_SOURCES.md for manual download instructions.
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    print("=" * 70)
    print("SUNSHINE LIST DATA DOWNLOADER")
    print("=" * 70)
    print()

    # --- GitHub community CSVs (1996-2020) ---
    print("Source 1: GitHub community CSVs (pbeens/Sunshine-List-CSV)")
    print("-" * 50)

    # Try cloning the repo first
    github_dir = os.path.join(DATA_DIR, "github-csv")
    if os.path.isdir(github_dir):
        print(f"  Already exists: {github_dir}")
        print("  Skipping clone. Delete directory to re-download.")
    else:
        print(f"  Cloning to: {github_dir}")
        try:
            result = subprocess.run(
                [
                    "git",
                    "clone",
                    "--depth",
                    "1",
                    "https://github.com/pbeens/Sunshine-List-CSV.git",
                    github_dir,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                print("  SUCCESS: Repository cloned.")
            else:
                print(f"  FAILED: {result.stderr.strip()}")
                print("  Falling back to individual file downloads...")
                _download_github_individual(github_dir)
        except FileNotFoundError:
            print("  git not found. Falling back to individual downloads...")
            _download_github_individual(github_dir)
        except subprocess.TimeoutExpired:
            print("  Timeout. Falling back to individual downloads...")
            _download_github_individual(github_dir)

    print()

    # --- Ontario Open Data Portal (2021-2022) ---
    print("Source 2: Ontario Open Data Portal (2021-2022)")
    print("-" * 50)
    print("  These require navigating to the data portal to find CSV resource IDs.")
    print("  URLs to visit manually:")
    for year, url in sorted(ONTARIO_DATA_URLS.items()):
        target = os.path.join(DATA_DIR, f"sunshine-{year}.csv")
        if os.path.isfile(target):
            print(f"  {year}: Already downloaded ({target})")
        else:
            print(f"  {year}: {url}")
            print(f"        Save CSV as: {target}")

    print()

    # --- HTML-only years (2023-2024) ---
    print("Source 3: Ontario.ca interactive search (2023-2024)")
    print("-" * 50)
    print("  These years are ONLY available as interactive HTML search.")
    print("  NO bulk CSV download available.")
    print("  URL: https://www.ontario.ca/page/public-sector-salary-disclosure")
    print()
    print("  To get specific records, use the interactive search at:")
    print("  2024: https://www.ontario.ca/public-sector-salary-disclosure/2024/all-sectors-and-seconded-employees/")
    print("  2023: https://www.ontario.ca/public-sector-salary-disclosure/2023/all-sectors-and-seconded-employees/")
    print()
    print("  For targeted lookups of our people of interest, you can manually")
    print("  search each name and save results. See the 'manual-lookups' command.")
    print()

    # Summary
    print("=" * 70)
    print("DOWNLOAD SUMMARY")
    print("=" * 70)
    csv_files = find_csv_files()
    print(f"  CSV files found: {len(csv_files)}")
    for f in csv_files[:10]:
        print(f"    {f}")
    if len(csv_files) > 10:
        print(f"    ... and {len(csv_files) - 10} more")


def _download_github_individual(target_dir):
    """Download individual CSV files from GitHub using curl."""
    os.makedirs(target_dir, exist_ok=True)
    # Focus on recent years most relevant to our analysis (2018-2020)
    priority_years = [2018, 2019, 2020]

    for year in priority_years:
        url = f"{GITHUB_RAW_BASE}/{year}.csv"
        target = os.path.join(target_dir, f"{year}.csv")
        if os.path.isfile(target):
            print(f"  {year}: Already exists")
            continue
        print(f"  Downloading {year}...")
        try:
            result = subprocess.run(
                ["curl", "-sL", "--max-time", "60", "-o", target, url],
                capture_output=True,
                text=True,
                timeout=90,
            )
            if result.returncode == 0 and os.path.isfile(target):
                size = os.path.getsize(target)
                if size > 1000:
                    print(f"  {year}: OK ({size:,} bytes)")
                else:
                    print(f"  {year}: File too small ({size} bytes) — may have failed")
                    os.remove(target)
            else:
                print(f"  {year}: curl failed: {result.stderr.strip()}")
        except Exception as e:
            print(f"  {year}: Error: {e}")


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def print_results(results, files_loaded, files_failed):
    """Print cross-reference results to stdout."""
    print("=" * 70)
    print("SUNSHINE LIST CROSS-REFERENCE RESULTS")
    print(f"Generated: {date.today().isoformat()}")
    print("=" * 70)
    print()

    # Data summary
    print("DATA LOADED:")
    total_records = sum(f["records"] for f in files_loaded)
    print(f"  Files: {len(files_loaded)}")
    print(f"  Total records: {total_records:,}")
    if files_failed:
        print(f"  Failed files: {len(files_failed)}")
        for f in files_failed:
            print(f"    {f['file']}: {f['error']}")
    print()

    if not results:
        print("NO MATCHES FOUND.")
        print()
        print("This likely means no CSV data has been downloaded yet.")
        print("Run: python3 scripts/cross_reference_sunshine.py download")
        return

    # --- Category 1: Government to Lobbyist ---
    print("=" * 70)
    print("CATEGORY 1: GOVERNMENT STAFF WHO BECAME LOBBYISTS")
    print("What were they paid in government before lobbying?")
    print("=" * 70)
    print()

    gov_to_lobby = {
        k: v
        for k, v in results.items()
        if "government-to-lobbyist" in v.get("categories", [])
    }
    if gov_to_lobby:
        for pid, data in sorted(gov_to_lobby.items()):
            _print_person_matches(data)
    else:
        print("  No matches found in available data.")
    print()

    # --- Category 2: Current Appointees ---
    print("=" * 70)
    print("CATEGORY 2: GOVERNMENT APPOINTEES")
    print("What are appointees paid (if appearing on Sunshine List)?")
    print("=" * 70)
    print()

    appointees = {
        k: v
        for k, v in results.items()
        if "government-appointee" in v.get("categories", [])
    }
    if appointees:
        for pid, data in sorted(appointees.items()):
            _print_person_matches(data)
    else:
        print("  No matches found in available data.")
    print()

    # --- All other matches ---
    print("=" * 70)
    print("ALL MATCHES")
    print("=" * 70)
    print()
    for pid, data in sorted(results.items()):
        _print_person_matches(data)


def _print_person_matches(data):
    """Print matches for a single person."""
    print(f"  {data['name']} ({data['type']})")
    if data.get("appointments"):
        for a in data["appointments"]:
            print(f"    Appointment: {a['position']} at {a['organization']}")
    print(f"    Years found on Sunshine List: {', '.join(data['years_found'])}")
    print(f"    Total records: {data['total_matches']}")
    for match in data["sunshine_matches"][:5]:  # Show top 5
        conf = match["match_confidence"]
        conf_label = "EXACT" if conf >= 1.0 else f"LIKELY ({conf:.0%})"
        print(
            f"    [{conf_label}] {match['year']}: "
            f"{match['employer']} — {match['title']} — "
            f"Salary: {match['salary']} / Benefits: {match['benefits']}"
        )
    if data["total_matches"] > 5:
        print(f"    ... and {data['total_matches'] - 5} more records")
    print()


# ---------------------------------------------------------------------------
# Save results
# ---------------------------------------------------------------------------


def save_results(results, files_loaded, files_failed):
    """Save results to JSON."""
    os.makedirs(os.path.dirname(RESULTS_JSON), exist_ok=True)

    output = {
        "generated": date.today().isoformat(),
        "data_summary": {
            "files_loaded": files_loaded,
            "files_failed": files_failed,
            "total_records": sum(f["records"] for f in files_loaded),
        },
        "data_availability": {
            "csv_available": {
                "1996-2020": {
                    "source": "GitHub: pbeens/Sunshine-List-CSV",
                    "url": "https://github.com/pbeens/Sunshine-List-CSV",
                    "format": "CSV",
                    "status": "available" if files_loaded else "not downloaded",
                },
                "2021-2022": {
                    "source": "Ontario Open Data Portal",
                    "url": "https://data.ontario.ca/",
                    "format": "CSV (via data portal)",
                    "status": "requires manual download — navigate to portal and export",
                },
            },
            "html_only": {
                "2023": {
                    "source": "ontario.ca interactive",
                    "url": "https://www.ontario.ca/public-sector-salary-disclosure/2023/all-sectors-and-seconded-employees/",
                    "format": "HTML (interactive search only)",
                    "status": "no bulk CSV available",
                },
                "2024": {
                    "source": "ontario.ca interactive",
                    "url": "https://www.ontario.ca/public-sector-salary-disclosure/2024/all-sectors-and-seconded-employees/",
                    "format": "HTML (interactive search only)",
                    "status": "no bulk CSV available",
                },
            },
        },
        "matches": {},
        "notes": [],
    }

    if not results:
        output["notes"].append(
            "No matches found. This likely means CSV data has not been downloaded yet. "
            "Run: python3 scripts/cross_reference_sunshine.py download"
        )
    else:
        # Separate into categories
        for pid, data in sorted(results.items()):
            # Remove non-serializable fields
            clean_matches = []
            for m in data["sunshine_matches"]:
                clean_matches.append(
                    {
                        "year": m["year"],
                        "employer": m["employer"],
                        "title": m["title"],
                        "salary": m["salary"],
                        "benefits": m["benefits"],
                        "sector": m["sector"],
                        "match_confidence": m["match_confidence"],
                    }
                )
            output["matches"][pid] = {
                "name": data["name"],
                "type": data["type"],
                "categories": data["categories"],
                "appointments": data.get("appointments", []),
                "years_found": data["years_found"],
                "total_matches": data["total_matches"],
                "sunshine_records": clean_matches,
            }

    with open(RESULTS_JSON, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults saved to: {RESULTS_JSON}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Cross-reference Ontario Sunshine List with people of interest"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # download command
    subparsers.add_parser("download", help="Download Sunshine List CSV data")

    # crossref command
    subparsers.add_parser(
        "crossref", help="Run cross-reference against people.json"
    )

    # search command
    search_parser = subparsers.add_parser(
        "search", help="Search for a specific name"
    )
    search_parser.add_argument("name", help="Name to search for")

    # status command
    subparsers.add_parser("status", help="Show data availability status")

    args = parser.parse_args()

    if args.command == "download":
        download_data()

    elif args.command == "crossref":
        print("Loading Sunshine List data...")
        sunshine_records, files_loaded, files_failed = load_all_sunshine_data()
        print(f"  Loaded {len(sunshine_records):,} records from {len(files_loaded)} files")
        if files_failed:
            print(f"  Failed to load {len(files_failed)} files")

        print("Loading people.json...")
        people = load_people()
        print(f"  {len(people)} people")

        print("Loading appointments.json...")
        appointments = load_appointments()
        print(f"  {len(appointments)} appointments")

        print("Running cross-reference...")
        results = cross_reference(people, appointments, sunshine_records)

        print_results(results, files_loaded, files_failed)
        save_results(results, files_loaded, files_failed)

    elif args.command == "search":
        print("Loading Sunshine List data...")
        sunshine_records, files_loaded, files_failed = load_all_sunshine_data()
        print(f"  Loaded {len(sunshine_records):,} records from {len(files_loaded)} files")

        print(f"\nSearching for: {args.name}")
        matches = search_name(args.name, sunshine_records)
        if matches:
            print(f"Found {len(matches)} records:\n")
            for m in matches:
                conf = m["match_confidence"]
                conf_label = "EXACT" if conf >= 1.0 else f"LIKELY ({conf:.0%})"
                print(
                    f"  [{conf_label}] {m['year']}: "
                    f"{m['first_name']} {m['last_name']} — "
                    f"{m['employer']} — {m['title']} — "
                    f"Salary: {m['salary']} / Benefits: {m['benefits']}"
                )
        else:
            print("No matches found.")
            if not files_loaded:
                print(
                    "\nNo data loaded. Run 'download' command first:"
                    "\n  python3 scripts/cross_reference_sunshine.py download"
                )

    elif args.command == "status":
        print("=" * 70)
        print("SUNSHINE LIST DATA STATUS")
        print("=" * 70)
        print()
        csv_files = find_csv_files()
        if csv_files:
            print(f"CSV files found: {len(csv_files)}")
            for f in csv_files:
                year = extract_year_from_filename(f)
                size = os.path.getsize(f)
                print(f"  {f} (year: {year}, size: {size:,} bytes)")
        else:
            print("No CSV files found in:")
            print(f"  {DATA_DIR}")
            print()
            print("Run: python3 scripts/cross_reference_sunshine.py download")

        print()
        print("DATA AVAILABILITY BY YEAR:")
        print("  1996-2020: CSV available from GitHub (pbeens/Sunshine-List-CSV)")
        print("  2021-2022: CSV available from Ontario Open Data Portal")
        print("             https://data.ontario.ca/")
        print("  2023:      HTML only (interactive search on ontario.ca)")
        print("  2024:      HTML only (interactive search on ontario.ca)")
        print()
        print("PEOPLE OF INTEREST FOR SUNSHINE LIST LOOKUP:")
        people = load_people()
        for p in people:
            ptype = p.get("type", "")
            relevance = ""
            if ptype in ("lobbyist-insider", "insider"):
                relevance = " <-- likely on Sunshine List during government service"
            elif ptype == "politician":
                relevance = " <-- likely on Sunshine List as elected official"
            print(f"  {p['name']} ({ptype}){relevance}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
