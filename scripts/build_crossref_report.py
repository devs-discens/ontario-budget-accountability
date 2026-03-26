#!/usr/bin/env python3
"""
Cross-Reference Report Builder
================================
Joins all four data sources (Elections Ontario, Public Accounts, Sunshine List,
Lobbyist Registry) against the tracked organizations and people to produce a
unified accountability view.

Output: raw-data/cross-reference-report.json + audits/2025-26/research/cross-reference-report.md

Usage:
    python3 scripts/build_crossref_report.py
"""

import json
import os
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DATA_DIR = PROJECT_DIR / "audits" / "2025-26" / "data"
RAW_DIR = PROJECT_DIR / "raw-data"
REPORT_DIR = PROJECT_DIR / "audits" / "2025-26" / "research"

# ============================================================================
# LOAD ALL DATA SOURCES
# ============================================================================

def load_json(path):
    if not path.exists():
        print(f"  WARNING: {path} not found")
        return None
    with open(path) as f:
        return json.load(f)


def load_all_sources():
    """Load and return all data sources."""
    sources = {}

    # Core audit data
    sources["organizations"] = load_json(DATA_DIR / "organizations.json")
    sources["people"] = load_json(DATA_DIR / "people.json")
    sources["relationships"] = load_json(DATA_DIR / "relationships.json")
    sources["contracts"] = load_json(DATA_DIR / "contracts.json")

    # Cross-reference results
    sources["elections"] = load_json(RAW_DIR / "elections-ontario" / "cross_reference_results.json")
    sources["payments"] = load_json(RAW_DIR / "public-accounts" / "cross-reference-results.json")
    sources["sunshine"] = load_json(RAW_DIR / "sunshine-list" / "cross-reference-results.json")
    sources["lobbyist_orgs"] = load_json(RAW_DIR / "lobbyist-registry" / "org_search_results.json")
    sources["lobbyist_people"] = load_json(RAW_DIR / "lobbyist-registry" / "people_search_results.json")

    return sources


# ============================================================================
# BUILD ORGANIZATION PROFILES
# ============================================================================

def build_org_profiles(sources):
    """Build a unified profile for each organization."""
    orgs_data = sources["organizations"]
    if not orgs_data:
        return []

    # Index payment data by org_id
    payment_index = {}
    if sources["payments"]:
        for org in sources["payments"].get("matched_organizations", []):
            payment_index[org["org_id"]] = org

    # Index lobbyist data by org_id
    lobbyist_index = {}
    if sources["lobbyist_orgs"]:
        for entry in sources["lobbyist_orgs"]:
            lobbyist_index[entry.get("org_id", "")] = entry

    # Index contracts by ID
    contract_index = {}
    if sources["contracts"]:
        for c in sources["contracts"].get("contracts", []):
            contract_index[c["id"]] = c

    # Index relationships by org
    rel_by_org = {}
    if sources["relationships"]:
        for rel in sources["relationships"].get("relationships", []):
            to_id = rel.get("to", "")
            if to_id not in rel_by_org:
                rel_by_org[to_id] = []
            rel_by_org[to_id].append(rel)

    profiles = []

    for org in orgs_data["organizations"]:
        org_id = org["id"]
        profile = {
            "id": org_id,
            "name": org["name"],
            "org_type": org.get("org_type", "unknown"),
            "connection_strength": org.get("connection_strength", "none"),
            "contracts": [],
            "total_contract_value": 0,
            "public_accounts": None,
            "lobbyist_registrations": [],
            "lobbyist_count": 0,
            "relationships": [],
            "flags": [],
        }

        # Contracts
        for cid in org.get("contracts", []):
            if cid in contract_index:
                c = contract_index[cid]
                profile["contracts"].append({
                    "id": cid,
                    "name": c.get("name", cid),
                    "value": c.get("value"),
                    "decision_type": c.get("decision_type", ""),
                    "ag_flagged": c.get("ag_flagged", False),
                })
                if c.get("value"):
                    profile["total_contract_value"] += c["value"]

        # Public Accounts payments
        if org_id in payment_index:
            pa = payment_index[org_id]
            profile["public_accounts"] = {
                "total_paid": pa.get("total_paid_all_years_found", 0),
                "yearly_totals": pa.get("yearly_totals", {}),
                "top_ministries": _top_ministries(pa),
            }

        # Lobbyist registrations
        if org_id in lobbyist_index:
            entry = lobbyist_index[org_id]
            for r in entry.get("results", []):
                profile["lobbyist_registrations"].append({
                    "lobbyist_name": r.get("lobbyist_name", ""),
                    "firm": r.get("firm", ""),
                    "status": r.get("status", ""),
                    "registration_no": r.get("registration_no", ""),
                })
            profile["lobbyist_count"] = entry.get("result_count", 0)

        # Relationships
        if org_id in rel_by_org:
            for rel in rel_by_org[org_id]:
                profile["relationships"].append({
                    "from": rel.get("from", ""),
                    "type": rel.get("type", ""),
                    "evidence": rel.get("evidence", ""),
                })

        # Flags
        if profile["connection_strength"] in ("strong", "very-strong"):
            profile["flags"].append(f"connection_strength: {profile['connection_strength']}")
        if any(c.get("ag_flagged") for c in profile["contracts"]):
            profile["flags"].append("auditor_general_flagged")
        if profile["lobbyist_count"] >= 5:
            profile["flags"].append(f"heavy_lobbying: {profile['lobbyist_count']} registrations")

        profiles.append(profile)

    return profiles


def _top_ministries(pa_entry):
    """Extract top ministries from public accounts data."""
    ministry_totals = {}
    for year_data in pa_entry.get("matches_by_year", {}).values():
        if isinstance(year_data, list):
            for match in year_data:
                ministry = match.get("ministry", "Unknown")
                amount = match.get("amount", 0)
                if isinstance(amount, (int, float)):
                    ministry_totals[ministry] = ministry_totals.get(ministry, 0) + amount
    return sorted(
        [{"ministry": k, "total": v} for k, v in ministry_totals.items()],
        key=lambda x: -x["total"]
    )[:5]


# ============================================================================
# BUILD PEOPLE PROFILES
# ============================================================================

def build_people_profiles(sources):
    """Build a unified profile for each tracked person."""
    people_data = sources["people"]
    if not people_data:
        return []

    # Index elections data by last name (fuzzy — these are surname-keyed)
    elections = {}
    if sources["elections"]:
        elections = sources["elections"].get("results", {})

    # Index sunshine data by person ID
    sunshine_index = {}
    if sources["sunshine"]:
        sunshine_index = sources["sunshine"].get("matches", {})

    # Index lobbyist people data by person ID
    lobbyist_index = {}
    if sources["lobbyist_people"]:
        for entry in sources["lobbyist_people"]:
            lobbyist_index[entry.get("person_id", "")] = entry

    # Index relationships by person
    rel_by_person = {}
    if sources["relationships"]:
        for rel in sources["relationships"].get("relationships", []):
            from_id = rel.get("from", "")
            if from_id not in rel_by_person:
                rel_by_person[from_id] = []
            rel_by_person[from_id].append(rel)

    profiles = []

    for person in people_data["people"]:
        pid = person["id"]
        name = person["name"]
        last_name = name.split()[-1] if name else ""

        profile = {
            "id": pid,
            "name": name,
            "type": person.get("type", ""),
            "firm": person.get("firm"),
            "integrity_violations": person.get("integrity_violations", False),
            "timeline": person.get("timeline", []),
            "donations": None,
            "sunshine": None,
            "lobbyist_registrations": [],
            "lobbyist_client_count": 0,
            "relationships": [],
            "flags": [],
        }

        # Elections Ontario donations — match by last name
        # Use exact key matches from the elections results
        matched_election_key = None
        for key in elections:
            # Try exact last name match
            if key.lower() == last_name.lower():
                matched_election_key = key
                break
            # Try hyphenated names (e.g., Fidani-Diker)
            if key.lower().replace("-", " ") == last_name.lower().replace("-", " "):
                matched_election_key = key
                break

        if matched_election_key:
            e = elections[matched_election_key]
            profile["donations"] = {
                "total_pc": e.get("total_pc", 0),
                "total_all_parties": e.get("total_all_parties", 0),
                "top_donations": e.get("by_party", {}).get("PCP", {}).get("top_donations", [])[:5],
            }

        # Sunshine List
        if pid in sunshine_index:
            s = sunshine_index[pid]
            records = s.get("sunshine_records", [])
            profile["sunshine"] = {
                "total_matches": s.get("total_matches", 0),
                "years_found": s.get("years_found", []),
                "top_salary": max(
                    (r for r in records if r.get("salary")),
                    key=lambda r: float(r["salary"].replace("$", "").replace(",", "")) if r.get("salary") else 0,
                    default=None
                ),
                "employers": list(set(r.get("employer", "") for r in records if r.get("employer"))),
            }

        # Lobbyist registrations (as lobbyist)
        if pid in lobbyist_index:
            entry = lobbyist_index[pid]
            for r in entry.get("results", []):
                profile["lobbyist_registrations"].append({
                    "client": r.get("client", ""),
                    "firm": r.get("firm", ""),
                    "status": r.get("status", ""),
                })
            profile["lobbyist_client_count"] = entry.get("result_count", 0)

        # Relationships
        if pid in rel_by_person:
            for rel in rel_by_person[pid]:
                profile["relationships"].append({
                    "to": rel.get("to", ""),
                    "type": rel.get("type", ""),
                    "amount": rel.get("amount"),
                    "evidence": rel.get("evidence", ""),
                })

        # Flags
        if profile["integrity_violations"]:
            profile["flags"].append("integrity_violations")
        if profile["type"] == "lobbyist-insider":
            profile["flags"].append("revolving_door")
        if profile["donations"] and profile["donations"]["total_pc"] > 10000:
            profile["flags"].append(f"major_pc_donor: ${profile['donations']['total_pc']:,.0f}")
        if profile["lobbyist_client_count"] >= 10:
            profile["flags"].append(f"prolific_lobbyist: {profile['lobbyist_client_count']}+ clients")

        profiles.append(profile)

    return profiles


# ============================================================================
# GENERATE MARKDOWN REPORT
# ============================================================================

def generate_markdown(org_profiles, people_profiles, sources):
    """Generate the human-readable cross-reference report."""
    lines = []
    lines.append("# Cross-Reference Report: Ontario Budget Accountability")
    lines.append(f"\n*Generated: {datetime.now().strftime('%Y-%m-%d')}*")
    lines.append("")
    lines.append("This report joins four public data sources against the 129 organizations and 42 people")
    lines.append("tracked in the Ontario Budget Accountability audit.")
    lines.append("")
    lines.append("**Data sources:**")
    lines.append("- Elections Ontario: 429,434 contribution records (2014-present)")
    lines.append("- Public Accounts: Detailed payment schedules (2023-25)")
    lines.append("- Sunshine List: Public sector salary disclosure (1996-2020, 2M+ records)")
    lines.append("- Ontario Lobbyist Registry: Active and inactive registrations")
    lines.append("")

    # ---- SUMMARY STATISTICS ----
    orgs_with_lobbyists = [o for o in org_profiles if o["lobbyist_count"] > 0]
    orgs_with_payments = [o for o in org_profiles if o["public_accounts"]]
    orgs_flagged = [o for o in org_profiles if o["flags"]]
    people_with_donations = [p for p in people_profiles if p["donations"] and p["donations"]["total_pc"] > 0]
    people_revolving = [p for p in people_profiles if "revolving_door" in p["flags"]]
    people_integrity = [p for p in people_profiles if p["integrity_violations"]]

    lines.append("## Summary")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|--------|-------|")
    lines.append(f"| Organizations tracked | {len(org_profiles)} |")
    lines.append(f"| Organizations with lobbyist registrations | {len(orgs_with_lobbyists)} |")
    lines.append(f"| Organizations with Public Accounts payments | {len(orgs_with_payments)} |")
    lines.append(f"| Organizations with accountability flags | {len(orgs_flagged)} |")
    lines.append(f"| People tracked | {len(people_profiles)} |")
    lines.append(f"| People with PC donations | {len(people_with_donations)} |")
    lines.append(f"| Revolving door (govt → lobbyist) | {len(people_revolving)} |")
    lines.append(f"| Integrity violations | {len(people_integrity)} |")
    lines.append("")

    # ---- HIGHEST-RISK ORGANIZATIONS ----
    lines.append("## Organizations by Accountability Risk")
    lines.append("")
    lines.append("Organizations sorted by number of flags (connection strength, AG findings, lobbying intensity).")
    lines.append("")

    flagged_orgs = sorted(org_profiles, key=lambda o: (-len(o["flags"]), -o["lobbyist_count"]))

    for org in flagged_orgs:
        if not org["flags"] and org["lobbyist_count"] == 0 and not org["public_accounts"]:
            continue

        lines.append(f"### {org['name']}")
        lines.append("")

        # Contract summary
        if org["contracts"]:
            total_val = org["total_contract_value"]
            val_str = f"${total_val/1e9:.1f}B" if total_val >= 1e9 else f"${total_val/1e6:.0f}M" if total_val >= 1e6 else f"${total_val:,.0f}" if total_val > 0 else "undisclosed"
            lines.append(f"**Contracts:** {len(org['contracts'])} tracked, combined value {val_str}")
            ag_flagged = [c for c in org["contracts"] if c.get("ag_flagged")]
            if ag_flagged:
                lines.append(f"  - **AG flagged:** {', '.join(c['name'] for c in ag_flagged)}")
            sole_source = [c for c in org["contracts"] if "sole" in c.get("decision_type", "").lower()]
            if sole_source:
                lines.append(f"  - **Sole-source:** {', '.join(c['name'] for c in sole_source)}")
            lines.append("")

        # Public Accounts
        if org["public_accounts"]:
            pa = org["public_accounts"]
            total = pa["total_paid"]
            total_str = f"${total/1e6:.1f}M" if total >= 1e6 else f"${total:,.0f}"
            lines.append(f"**Public Accounts payments:** {total_str}")
            if pa["top_ministries"]:
                for m in pa["top_ministries"][:3]:
                    mt = m["total"]
                    mt_str = f"${mt/1e6:.1f}M" if mt >= 1e6 else f"${mt:,.0f}"
                    lines.append(f"  - {m['ministry']}: {mt_str}")
            lines.append("")

        # Lobbyist registrations
        if org["lobbyist_registrations"]:
            lines.append(f"**Lobbyist registrations:** {org['lobbyist_count']}")
            active = [r for r in org["lobbyist_registrations"] if r.get("status", "").lower() == "active"]
            inactive = [r for r in org["lobbyist_registrations"] if r.get("status", "").lower() != "active"]
            if active:
                firms = list(set(r["firm"] for r in active if r["firm"]))
                lobbyists = list(set(r["lobbyist_name"] for r in active if r["lobbyist_name"]))
                lines.append(f"  - **Active:** {', '.join(lobbyists[:5])}")
                if firms:
                    lines.append(f"  - **Firms:** {', '.join(firms[:5])}")
            lines.append("")

        # Relationships
        if org["relationships"]:
            lines.append(f"**Political connections:** {len(org['relationships'])}")
            for rel in org["relationships"][:5]:
                lines.append(f"  - {rel['from']} ({rel['type']}): {rel['evidence'][:100]}")
            lines.append("")

        # Flags
        if org["flags"]:
            lines.append(f"**Flags:** {', '.join(org['flags'])}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # ---- PEOPLE: THE REVOLVING DOOR ----
    lines.append("## People: The Revolving Door")
    lines.append("")
    lines.append("Tracked individuals sorted by accountability risk. Combines donation records,")
    lines.append("salary disclosure, and lobbyist registration data.")
    lines.append("")

    # Sort: integrity violations first, then revolving door, then by donation amount
    sorted_people = sorted(people_profiles, key=lambda p: (
        -int(p["integrity_violations"]),
        -int("revolving_door" in p["flags"]),
        -(p["donations"]["total_pc"] if p["donations"] else 0),
        -p["lobbyist_client_count"],
    ))

    for person in sorted_people:
        if not person["flags"] and not person["donations"] and not person["lobbyist_registrations"]:
            continue

        lines.append(f"### {person['name']}")
        if person["type"]:
            lines.append(f"*{person['type']}*" + (f" — {person['firm']}" if person['firm'] else ""))
        lines.append("")

        # Donations
        if person["donations"] and person["donations"]["total_pc"] > 0:
            d = person["donations"]
            lines.append(f"**PC donations:** ${d['total_pc']:,.0f} (all parties: ${d['total_all_parties']:,.0f})")
            if d["top_donations"]:
                for don in d["top_donations"][:3]:
                    lines.append(f"  - {don.get('year','?')}: ${don.get('amount',0):,.0f} to {don.get('recipient','?')}")
            lines.append("")

        # Sunshine List
        if person["sunshine"]:
            s = person["sunshine"]
            lines.append(f"**Sunshine List:** {s['total_matches']} records ({', '.join(s['years_found'][:5])}{'...' if len(s['years_found']) > 5 else ''})")
            if s["top_salary"]:
                ts = s["top_salary"]
                lines.append(f"  - Highest: {ts.get('salary','?')} at {ts.get('employer','?')} ({ts.get('year','?')})")
            if s["employers"]:
                lines.append(f"  - Employers: {', '.join(s['employers'][:3])}")
            lines.append("")

        # Lobbyist registrations
        if person["lobbyist_registrations"]:
            lines.append(f"**Lobbyist clients:** {person['lobbyist_client_count']}+")
            active = [r for r in person["lobbyist_registrations"] if r.get("status", "").lower() == "active"]
            if active:
                clients = list(set(r["client"] for r in active if r["client"]))[:5]
                lines.append(f"  - Active clients: {', '.join(clients)}")
            lines.append("")

        # Relationships
        if person["relationships"]:
            lines.append(f"**Documented connections:** {len(person['relationships'])}")
            for rel in person["relationships"][:5]:
                amt = ""
                if rel.get("amount"):
                    a = rel["amount"]
                    amt = f" (${a/1e6:.0f}M)" if a >= 1e6 else f" (${a:,.0f})"
                lines.append(f"  - → {rel['to']} ({rel['type']}{amt})")
            lines.append("")

        # Flags
        if person["flags"]:
            lines.append(f"**Flags:** {', '.join(person['flags'])}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # ---- DATA COVERAGE ----
    lines.append("## Data Coverage and Limitations")
    lines.append("")
    lines.append("| Source | Coverage | Limitation |")
    lines.append("|--------|----------|------------|")
    lines.append("| Elections Ontario | 429K records, 2014-present | Corporate donations banned Sept 2017; pre-2017 data includes corporate donors |")
    lines.append("| Public Accounts | 2023-24, 2024-25 | Only direct provincial payments; crown agency payments (Metrolinx, IO, OPG) not included |")
    lines.append("| Sunshine List | 1996-2020 (2M+ records) | 2021-2022 data not yet downloaded; $100K threshold not inflation-adjusted |")
    lines.append("| Lobbyist Registry | Active + inactive registrations | Results capped at 10 per search (first page); actual counts may be higher |")
    lines.append("")
    lines.append("### Unmatched organizations")
    lines.append("")
    lines.append("These tracked organizations had no Public Accounts payment matches. They are typically")
    lines.append("paid through crown agencies (Metrolinx, Infrastructure Ontario, OPG) rather than directly:")
    lines.append("")
    unmatched = [o for o in org_profiles if not o["public_accounts"] and o["contracts"]]
    for org in unmatched[:20]:
        contract_names = [c["name"] for c in org["contracts"][:3]]
        lines.append(f"- **{org['name']}** — contracts: {', '.join(contract_names)}")
    lines.append("")

    return "\n".join(lines)


# ============================================================================
# MAIN
# ============================================================================

def main():
    print("Building cross-reference report...")
    print("=" * 60)

    # Load all data
    sources = load_all_sources()

    # Build profiles
    print("\nBuilding organization profiles...")
    org_profiles = build_org_profiles(sources)
    print(f"  {len(org_profiles)} organizations profiled")

    print("Building people profiles...")
    people_profiles = build_people_profiles(sources)
    print(f"  {len(people_profiles)} people profiled")

    # Stats
    orgs_with_data = [o for o in org_profiles if o["lobbyist_count"] > 0 or o["public_accounts"] or o["flags"]]
    people_with_data = [p for p in people_profiles if p["donations"] or p["lobbyist_registrations"] or p["sunshine"]]
    print(f"\n  Organizations with cross-reference data: {len(orgs_with_data)}")
    print(f"  People with cross-reference data: {len(people_with_data)}")

    # Save JSON
    json_output = {
        "generated": datetime.now().isoformat(),
        "sources": {
            "elections_ontario": "raw-data/elections-ontario/cross_reference_results.json",
            "public_accounts": "raw-data/public-accounts/cross-reference-results.json",
            "sunshine_list": "raw-data/sunshine-list/cross-reference-results.json",
            "lobbyist_registry_orgs": "raw-data/lobbyist-registry/org_search_results.json",
            "lobbyist_registry_people": "raw-data/lobbyist-registry/people_search_results.json",
        },
        "summary": {
            "organizations_tracked": len(org_profiles),
            "organizations_with_lobbyists": len([o for o in org_profiles if o["lobbyist_count"] > 0]),
            "organizations_with_payments": len([o for o in org_profiles if o["public_accounts"]]),
            "people_tracked": len(people_profiles),
            "people_revolving_door": len([p for p in people_profiles if "revolving_door" in p["flags"]]),
            "people_integrity_violations": len([p for p in people_profiles if p["integrity_violations"]]),
        },
        "organization_profiles": org_profiles,
        "people_profiles": people_profiles,
    }

    json_path = RAW_DIR / "cross-reference-report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_output, f, indent=2, ensure_ascii=False)
    print(f"\nSaved JSON: {json_path}")

    # Generate and save markdown
    md = generate_markdown(org_profiles, people_profiles, sources)
    md_path = REPORT_DIR / "cross-reference-report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"Saved report: {md_path}")

    # Print top-level findings
    print("\n" + "=" * 60)
    print("KEY FINDINGS")
    print("=" * 60)

    # Top orgs by lobbying
    top_lobby = sorted(org_profiles, key=lambda o: -o["lobbyist_count"])[:10]
    print("\nTop organizations by lobbyist registrations:")
    for o in top_lobby:
        if o["lobbyist_count"] > 0:
            pa_str = ""
            if o["public_accounts"]:
                pa = o["public_accounts"]["total_paid"]
                pa_str = f", received ${pa/1e6:.1f}M" if pa >= 1e6 else f", received ${pa:,.0f}"
            print(f"  {o['name']}: {o['lobbyist_count']} registrations{pa_str}")

    # Top people by flags
    flagged_people = [p for p in people_profiles if p["flags"]]
    print(f"\nPeople with accountability flags: {len(flagged_people)}")
    for p in sorted(flagged_people, key=lambda p: -len(p["flags"]))[:10]:
        print(f"  {p['name']}: {', '.join(p['flags'])}")


if __name__ == "__main__":
    main()
