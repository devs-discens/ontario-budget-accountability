#!/usr/bin/env python3
"""
Cross-reference Ontario Public Accounts (Detailed Schedule of Payments)
against tracked organizations in our audit data.

Data source: https://data.ontario.ca/dataset/public-accounts-detailed-schedule-of-payments
Columns: Amount $, Ministry, Category, Payment Detail, Recipient, Statutory, Additional Detail

IMPORTANT: The Public Accounts disclose payments above a threshold (currently
$120,000 for most categories; historically $50,000). Payments below the
threshold are aggregated into "Accounts Under $X" line items. This means
smaller vendors may not appear individually.

Also note: Many large infrastructure contractors (transit, nuclear, highway)
are paid through crown agencies like Metrolinx, Infrastructure Ontario, or OPG,
NOT directly by ministries. So a company like Aecon or EllisDon may receive
billions via Metrolinx but appear with $0 or small amounts in Public Accounts
direct payments. This is a structural limitation of this dataset.

Uses ONLY Python standard library. No pandas.
"""

import csv
import json
import os
import re
import sys
from collections import defaultdict

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "raw-data", "public-accounts")
ORG_FILE = os.path.join(BASE_DIR, "audits", "2025-26", "data", "organizations.json")
RESULTS_FILE = os.path.join(DATA_DIR, "cross-reference-results.json")
TOP_RECIPIENTS_FILE = os.path.join(DATA_DIR, "top-recipients.json")

# CSV files to process (most recent first)
CSV_FILES = {
    "2024-25": os.path.join(DATA_DIR, "public-accounts-2024-25.csv"),
    "2023-24": os.path.join(DATA_DIR, "public-accounts-2023-24.csv"),
}

# ---------------------------------------------------------------------------
# Name-matching logic
# ---------------------------------------------------------------------------

def normalize(name):
    """Normalize a name for fuzzy comparison."""
    s = name.upper().strip()
    # Remove common suffixes
    for suffix in [
        " INC.", " INC", " LTD.", " LTD", " LIMITED", " CORP.", " CORP",
        " CORPORATION", " LP", " L.P.", " LLP", " CO.", " CO",
        " CANADA", " ONTARIO", " GROUP", " SERVICES",
        " CONSTRUCTION", " CONSULTING", " SOLUTIONS",
    ]:
        if s.endswith(suffix):
            s = s[: -len(suffix)].strip()
    # Remove punctuation
    s = re.sub(r"[^A-Z0-9 ]", "", s)
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def build_search_variants(org_name):
    """
    Build a list of search strings from an organization name.
    E.g. "AtkinsRealis (fka SNC-Lavalin)" ->
         ["ATKINSREALIS", "SNC-LAVALIN", "SNC LAVALIN", "ATKINS REALIS"]
    """
    variants = set()

    # Main name
    variants.add(normalize(org_name))

    # Also add the raw uppercase (before normalization strips suffixes)
    raw = org_name.upper().strip()
    variants.add(raw)

    # Handle parenthetical aliases: (fka X), (O/A X), (formerly X), etc.
    paren_match = re.findall(r"\(([^)]+)\)", org_name)
    for alias in paren_match:
        cleaned = re.sub(r"^(fka|formerly|o/a|aka)\s+", "", alias, flags=re.IGNORECASE).strip()
        variants.add(normalize(cleaned))
        variants.add(cleaned.upper().strip())

    # Handle slash-separated names: "Keel Digital Solutions / Get A-Head"
    if "/" in org_name:
        for part in org_name.split("/"):
            part = part.strip()
            if part and len(part) > 2:
                variants.add(normalize(part))

    # CamelCase splitting: "EllisDon" -> "ELLIS DON" and "ELLISDON"
    camel_split = re.sub(r"([a-z])([A-Z])", r"\1 \2", org_name)
    if camel_split != org_name:
        variants.add(normalize(camel_split))
        variants.add(normalize(org_name.replace(" ", "")))

    # Remove empty strings
    variants.discard("")

    return list(variants)


def name_matches(recipient_name, search_variants):
    """
    Check if a Public Accounts recipient name matches any of our search variants.
    Returns True if any variant is a substring of the normalized recipient, or vice versa.
    Uses conservative matching to avoid false positives.
    """
    norm_recipient = normalize(recipient_name)
    recipient_upper = recipient_name.upper().strip()

    for variant in search_variants:
        if not variant or len(variant) < 3:
            continue

        # Exact normalized match
        if norm_recipient == variant:
            return True

        # Variant is contained within the recipient name (or vice versa)
        # Only if variant is long enough to be meaningful (>=5 chars)
        if len(variant) >= 5:
            if variant in norm_recipient or variant in recipient_upper:
                return True
            if norm_recipient in variant:
                return True

    return False


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def load_csv(filepath):
    """Load a Public Accounts CSV file. Returns list of dicts."""
    rows = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Parse amount
            raw_amt = row.get("Amount $", "").replace(",", "").strip()
            try:
                row["_amount"] = int(raw_amt)
            except ValueError:
                row["_amount"] = 0
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Load organizations
    with open(ORG_FILE, "r") as f:
        org_data = json.load(f)
    organizations = org_data.get("organizations", [])
    print(f"Loaded {len(organizations)} organizations from {ORG_FILE}")

    # Load CSV data
    all_rows = {}  # year -> rows
    for year, path in CSV_FILES.items():
        if not os.path.exists(path):
            print(f"WARNING: CSV not found for {year}: {path}")
            continue
        rows = load_csv(path)
        all_rows[year] = rows
        print(f"Loaded {len(rows)} records for {year} from {path}")

    if not all_rows:
        print("ERROR: No CSV data loaded. Cannot proceed.")
        sys.exit(1)

    # --- Step 1: Cross-reference organizations against Public Accounts ---
    print("\n=== Cross-referencing organizations against Public Accounts ===\n")

    cross_ref_results = []

    for org in organizations:
        org_id = org["id"]
        org_name = org["name"]
        org_type = org.get("org_type", "unknown")
        total_gov_value = org.get("total_gov_value")

        search_variants = build_search_variants(org_name)

        matches_by_year = {}
        for year, rows in all_rows.items():
            year_matches = []
            for row in rows:
                recipient = row.get("Recipient", "")
                if name_matches(recipient, search_variants):
                    year_matches.append({
                        "recipient_name": recipient,
                        "amount": row["_amount"],
                        "ministry": row.get("Ministry", ""),
                        "category": row.get("Category", "").strip(),
                        "payment_detail": row.get("Payment Detail", ""),
                    })
            if year_matches:
                matches_by_year[year] = year_matches

        if matches_by_year:
            total_paid_all_years = 0
            yearly_totals = {}
            for year, matches in matches_by_year.items():
                year_total = sum(m["amount"] for m in matches)
                yearly_totals[year] = year_total
                total_paid_all_years += year_total

            result = {
                "org_id": org_id,
                "org_name": org_name,
                "org_type": org_type,
                "total_gov_value_in_our_data": total_gov_value,
                "search_variants_used": search_variants,
                "matches_by_year": {},
                "yearly_totals": yearly_totals,
                "total_paid_all_years_found": total_paid_all_years,
                "consistency_note": None,
            }

            for year, matches in matches_by_year.items():
                result["matches_by_year"][year] = matches

            # Consistency check
            if total_gov_value and total_gov_value > 0:
                # Our total_gov_value is lifetime contract value;
                # Public Accounts shows annual payments.
                # Flag if annual payments seem unusually high or if there's a
                # notable discrepancy.
                max_annual = max(yearly_totals.values()) if yearly_totals else 0
                if max_annual > total_gov_value:
                    result["consistency_note"] = (
                        f"REVIEW: Annual payment ({max_annual:,}) exceeds total "
                        f"contract value ({total_gov_value:,}). Contract value "
                        f"may be understated or payment includes related entities."
                    )
                elif total_paid_all_years == 0 and total_gov_value > 10_000_000:
                    result["consistency_note"] = (
                        f"NOTE: Our data shows ${total_gov_value:,} in contract "
                        f"value but no direct Public Accounts payments found. "
                        f"Payments may flow through crown agencies (Metrolinx, "
                        f"IO, OPG) rather than direct ministry payments."
                    )
                else:
                    result["consistency_note"] = (
                        f"Annual public accounts payments found. Our contract "
                        f"value: ${total_gov_value:,}. Public Accounts total "
                        f"across loaded years: ${total_paid_all_years:,}."
                    )
            else:
                if total_paid_all_years > 0:
                    result["consistency_note"] = (
                        f"Public Accounts payments found (${total_paid_all_years:,}) "
                        f"but no total_gov_value set in our data."
                    )

            cross_ref_results.append(result)

            # Print summary
            print(f"  MATCH: {org_name}")
            for year, total in yearly_totals.items():
                n = len(matches_by_year[year])
                print(f"    {year}: ${total:>15,} across {n} payment line(s)")
                for m in matches_by_year[year][:3]:
                    print(f"      -> {m['recipient_name'][:50]}  ${m['amount']:,}  ({m['ministry']})")
                if n > 3:
                    print(f"      ... and {n - 3} more")

    # Organizations with no matches
    matched_ids = {r["org_id"] for r in cross_ref_results}
    no_match_orgs = [o for o in organizations if o["id"] not in matched_ids]

    # Separate: those with gov value but no match (possibly paid via crown agencies)
    no_match_with_value = [
        o for o in no_match_orgs
        if o.get("total_gov_value") and o["total_gov_value"] > 0
    ]

    print(f"\n=== Summary ===")
    print(f"Organizations matched in Public Accounts: {len(cross_ref_results)} / {len(organizations)}")
    print(f"Organizations with contract value but NO Public Accounts match: {len(no_match_with_value)}")
    if no_match_with_value:
        print("  These are likely paid through crown agencies (Metrolinx, IO, OPG), not directly:")
        for o in no_match_with_value:
            print(f"    - {o['name']} (contract value: ${o['total_gov_value']:,})")

    # --- Step 2: Top 50 recipients across all years ---
    print("\n=== Building top 50 recipients list ===\n")

    # Aggregate payments by recipient across all years
    recipient_totals = defaultdict(lambda: {"total": 0, "years": {}, "ministries": set()})

    for year, rows in all_rows.items():
        for row in rows:
            recip = row.get("Recipient", "").strip()
            if not recip:
                continue
            amt = row["_amount"]
            entry = recipient_totals[recip]
            entry["total"] += amt
            entry["years"].setdefault(year, 0)
            entry["years"][year] += amt
            entry["ministries"].add(row.get("Ministry", ""))

    # Sort by total descending
    sorted_recipients = sorted(
        recipient_totals.items(), key=lambda x: x[1]["total"], reverse=True
    )

    top_50 = []
    for rank, (recip, data) in enumerate(sorted_recipients[:50], 1):
        top_50.append({
            "rank": rank,
            "recipient": recip,
            "total_all_years": data["total"],
            "by_year": data["years"],
            "ministries": sorted(data["ministries"]),
        })
        print(f"  #{rank:2d}  ${data['total']:>18,}  {recip[:65]}")

    # --- Step 3: Save results ---
    print(f"\n=== Saving results ===")

    # Build full results object
    full_results = {
        "_metadata": {
            "description": "Cross-reference of tracked organizations against Ontario Public Accounts Detailed Schedule of Payments",
            "source_url": "https://data.ontario.ca/dataset/public-accounts-detailed-schedule-of-payments",
            "csv_files_loaded": {
                year: os.path.basename(path)
                for year, path in CSV_FILES.items()
                if os.path.exists(path)
            },
            "records_per_year": {
                year: len(rows) for year, rows in all_rows.items()
            },
            "disclosure_threshold_note": (
                "As of 2024-25, the disclosure threshold appears to be $120,000 "
                "(payments below this are aggregated). In earlier years it was $50,000."
            ),
            "structural_caveat": (
                "IMPORTANT: Most large infrastructure contractors (transit, nuclear, "
                "highway construction) are paid through crown agencies like Metrolinx, "
                "Infrastructure Ontario, or OPG -- not directly by ministries. These "
                "payments will NOT appear in this dataset. The Public Accounts show "
                "the lump-sum transfers to those crown agencies (e.g., $8.7B to "
                "Metrolinx in 2024-25) but not the downstream payments to contractors."
            ),
            "generated_date": "2026-03-24",
            "organizations_searched": len(organizations),
            "organizations_matched": len(cross_ref_results),
        },
        "matched_organizations": cross_ref_results,
        "unmatched_organizations_with_contract_value": [
            {
                "org_id": o["id"],
                "org_name": o["name"],
                "org_type": o.get("org_type"),
                "total_gov_value": o.get("total_gov_value"),
                "note": (
                    "No direct Public Accounts payments found. Likely paid "
                    "through crown agencies or payments below disclosure threshold."
                ),
            }
            for o in no_match_with_value
        ],
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(full_results, f, indent=2)
    print(f"  Saved cross-reference results to {RESULTS_FILE}")

    # Save top recipients
    top_recipients_output = {
        "_metadata": {
            "description": "Top 50 largest recipients in Ontario Public Accounts (Detailed Schedule of Payments)",
            "source_url": "https://data.ontario.ca/dataset/public-accounts-detailed-schedule-of-payments",
            "years_included": list(all_rows.keys()),
            "note": (
                "Amounts are summed across all loaded fiscal years. "
                "Some 'recipients' are aggregate categories (e.g., physician payments, "
                "bond interest) rather than individual vendors."
            ),
            "generated_date": "2026-03-24",
        },
        "top_50_recipients": top_50,
    }

    with open(TOP_RECIPIENTS_FILE, "w") as f:
        json.dump(top_recipients_output, f, indent=2)
    print(f"  Saved top 50 recipients to {TOP_RECIPIENTS_FILE}")

    print("\nDone.")


if __name__ == "__main__":
    main()
