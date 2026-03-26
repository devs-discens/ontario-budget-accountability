#!/usr/bin/env python3
"""
Enrich Dashboard Data
=====================
Merges cross-reference data (Public Accounts, Elections Ontario, Sunshine List,
Lobbyist Registry) into the dashboard's JSON files so the interactive views
can display the full evidence chain.

Modifies:
  - dashboard/data/companies.json  (adds payment, lobbyist, donation fields)
  - dashboard/data/people.json     (adds donation, sunshine, lobbyist fields)
  - dashboard/data/connections.json (adds new lobbying edges from registry scrape)

Usage:
    python3 scripts/enrich_dashboard_data.py
"""

import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DASHBOARD_DATA = PROJECT_DIR / "dashboard" / "data"
RAW_DATA = PROJECT_DIR / "raw-data"

def load_json(path):
    if not path.exists():
        print(f"  SKIP: {path} not found")
        return None
    with open(path) as f:
        return json.load(f)


def enrich_companies():
    """Add public accounts, lobbyist, and election data to companies.json."""
    companies = load_json(DASHBOARD_DATA / "companies.json")
    if not companies:
        return

    # Load cross-reference sources
    payments = load_json(RAW_DATA / "public-accounts" / "cross-reference-results.json")
    lobbyist_orgs = load_json(RAW_DATA / "lobbyist-registry" / "org_search_results.json")
    elections = load_json(RAW_DATA / "elections-ontario" / "cross_reference_results.json")

    # Index payment data by org_id
    payment_index = {}
    if payments:
        for org in payments.get("matched_organizations", []):
            payment_index[org["org_id"]] = org

    # Index lobbyist data by org_id
    lobbyist_index = {}
    if lobbyist_orgs:
        for entry in lobbyist_orgs:
            lobbyist_index[entry.get("org_id", "")] = entry

    enriched = 0
    for company in companies["companies"]:
        cid = company["id"]
        evidence = {}

        # Public Accounts payments
        if cid in payment_index:
            pa = payment_index[cid]
            total = pa.get("total_paid_all_years_found", 0)
            yearly = pa.get("yearly_totals", {})
            # Top ministries
            ministry_totals = {}
            for year_data in pa.get("matches_by_year", {}).values():
                if isinstance(year_data, list):
                    for m in year_data:
                        ministry = m.get("ministry", "Unknown")
                        amt = m.get("amount", 0)
                        if isinstance(amt, (int, float)):
                            ministry_totals[ministry] = ministry_totals.get(ministry, 0) + amt
            top_ministries = sorted(ministry_totals.items(), key=lambda x: -x[1])[:3]

            company["public_accounts_total"] = total
            company["public_accounts_years"] = yearly
            company["public_accounts_ministries"] = [
                {"ministry": m, "total": t} for m, t in top_ministries
            ]
            evidence["public_accounts"] = True

        # Lobbyist registrations
        if cid in lobbyist_index:
            entry = lobbyist_index[cid]
            results = entry.get("results", [])
            company["lobbyist_count"] = entry.get("result_count", len(results))
            company["lobbyist_registrations"] = []
            for r in results:
                reg = {
                    "lobbyist": r.get("lobbyist_name", ""),
                    "firm": r.get("firm", ""),
                    "status": r.get("status", ""),
                    "registration_no": r.get("registration_no", ""),
                }
                company["lobbyist_registrations"].append(reg)
            # Extract unique active firms
            active_firms = list(set(
                r.get("firm", "") for r in results
                if r.get("status", "").lower() == "active" and r.get("firm")
            ))
            company["lobbyist_firms"] = active_firms
            evidence["lobbyist_registry"] = True

        # Count evidence sources
        sources = []
        if evidence.get("public_accounts"):
            sources.append("public_accounts")
        if evidence.get("lobbyist_registry"):
            sources.append("lobbyist_registry")
        if company.get("donations_pc"):
            sources.append("elections_ontario")
        if company.get("connection_strength") not in (None, "none"):
            sources.append("political_connections")
        company["evidence_sources"] = sources
        company["evidence_count"] = len(sources)

        if evidence:
            enriched += 1

    # Save
    with open(DASHBOARD_DATA / "companies.json", "w", encoding="utf-8") as f:
        json.dump(companies, f, indent=2, ensure_ascii=False)
    print(f"  Enriched {enriched} companies")
    return companies


def enrich_people():
    """Add donation, sunshine, and lobbyist data to people.json."""
    people = load_json(DASHBOARD_DATA / "people.json")
    if not people:
        return

    elections = load_json(RAW_DATA / "elections-ontario" / "cross_reference_results.json")
    sunshine = load_json(RAW_DATA / "sunshine-list" / "cross-reference-results.json")
    lobbyist_people = load_json(RAW_DATA / "lobbyist-registry" / "people_search_results.json")

    # Index elections by various name forms
    election_results = elections.get("results", {}) if elections else {}

    # Index sunshine by person ID
    sunshine_matches = sunshine.get("matches", {}) if sunshine else {}

    # Index lobbyist people by person ID
    lobbyist_index = {}
    if lobbyist_people:
        for entry in lobbyist_people:
            lobbyist_index[entry.get("person_id", "")] = entry

    enriched = 0
    for person in people["people"]:
        pid = person["id"]
        name = person.get("name", "")
        last_name = name.split()[-1] if name else ""
        evidence = {}

        # Elections Ontario — match by last name
        matched_key = None
        for key in election_results:
            if key.lower() == last_name.lower():
                matched_key = key
                break
            if key.lower().replace("-", " ") == last_name.lower().replace("-", " "):
                matched_key = key
                break

        if matched_key:
            e = election_results[matched_key]
            person["donations_pc_total"] = e.get("total_pc", 0)
            person["donations_all_total"] = e.get("total_all_parties", 0)
            top_donations = e.get("by_party", {}).get("PCP", {}).get("top_donations", [])[:5]
            person["top_donations"] = [
                {"year": d.get("year"), "amount": d.get("amount", 0), "recipient": d.get("recipient", "")}
                for d in top_donations
            ]
            evidence["elections_ontario"] = True

        # Sunshine List
        if pid in sunshine_matches:
            s = sunshine_matches[pid]
            records = s.get("sunshine_records", [])
            person["sunshine_years"] = s.get("years_found", [])
            person["sunshine_total_records"] = s.get("total_matches", 0)
            # Find highest salary
            best = None
            best_val = 0
            for r in records:
                try:
                    val = float(r.get("salary", "0").replace("$", "").replace(",", ""))
                    if val > best_val:
                        best_val = val
                        best = r
                except (ValueError, AttributeError):
                    pass
            if best:
                person["sunshine_top_salary"] = best.get("salary", "")
                person["sunshine_top_employer"] = best.get("employer", "")
                person["sunshine_top_title"] = best.get("title", "")
                person["sunshine_top_year"] = best.get("year", "")
            # Unique employers
            person["sunshine_employers"] = list(set(
                r.get("employer", "") for r in records if r.get("employer")
            ))[:5]
            evidence["sunshine_list"] = True

        # Lobbyist registrations (as lobbyist)
        if pid in lobbyist_index:
            entry = lobbyist_index[pid]
            results = entry.get("results", [])
            person["lobbyist_client_count"] = entry.get("result_count", len(results))
            person["lobbyist_clients"] = []
            for r in results:
                person["lobbyist_clients"].append({
                    "client": r.get("client", ""),
                    "firm": r.get("firm", ""),
                    "status": r.get("status", ""),
                })
            evidence["lobbyist_registry"] = True

        # Evidence count
        sources = []
        if evidence.get("elections_ontario"):
            sources.append("elections_ontario")
        if evidence.get("sunshine_list"):
            sources.append("sunshine_list")
        if evidence.get("lobbyist_registry"):
            sources.append("lobbyist_registry")
        if person.get("integrity_violations"):
            sources.append("integrity_commissioner")
        person["evidence_sources"] = sources
        person["evidence_count"] = len(sources)

        if evidence:
            enriched += 1

    with open(DASHBOARD_DATA / "people.json", "w", encoding="utf-8") as f:
        json.dump(people, f, indent=2, ensure_ascii=False)
    print(f"  Enriched {enriched} people")
    return people


def enrich_connections():
    """Add new lobbying edges from registry scrape that aren't already in connections.json."""
    connections = load_json(DASHBOARD_DATA / "connections.json")
    if not connections:
        return

    lobbyist_orgs = load_json(RAW_DATA / "lobbyist-registry" / "org_search_results.json")
    if not lobbyist_orgs:
        return

    # Load dashboard people to map lobbyist names to IDs
    people = load_json(DASHBOARD_DATA / "people.json")
    people_by_name = {}
    if people:
        for p in people["people"]:
            people_by_name[p["name"].lower()] = p["id"]

    edges = connections.get("connections", connections.get("edges", []))

    # Index existing edges to avoid duplicates
    existing = set()
    for e in edges:
        existing.add((e["from"], e["to"], e["type"]))

    added = 0
    for org_entry in lobbyist_orgs:
        org_id = org_entry.get("org_id", "")
        for result in org_entry.get("results", []):
            lobbyist_name = result.get("lobbyist_name", "").strip()
            if not lobbyist_name or not org_id:
                continue

            # Try to match lobbyist to a tracked person
            person_id = people_by_name.get(lobbyist_name.lower())
            if not person_id:
                continue  # Only add edges for tracked people

            edge_key = (person_id, org_id, "lobbies_for")
            if edge_key in existing:
                continue

            reg_no = result.get("registration_no", "")
            firm = result.get("firm", "")
            status = result.get("status", "")

            edges.append({
                "from": person_id,
                "to": org_id,
                "type": "lobbies_for",
                "amount": None,
                "evidence": f"Ontario Lobbyist Registry: {lobbyist_name} ({firm}) registered as lobbyist for {org_entry.get('query', org_id)}. Status: {status}. Reg# {reg_no}",
                "source_url": "https://lobbyist.oico.on.ca/Pages/Public/PublicSearch/",
                "data_source": "lobbyist_registry_scrape",
            })
            existing.add(edge_key)
            added += 1

    # Store back
    if "connections" in connections:
        connections["connections"] = edges
    else:
        connections["edges"] = edges

    with open(DASHBOARD_DATA / "connections.json", "w", encoding="utf-8") as f:
        json.dump(connections, f, indent=2, ensure_ascii=False)
    print(f"  Added {added} new lobbying edges from registry scrape")
    return connections


def main():
    print("Enriching dashboard data files...")
    print("=" * 50)

    print("\n1. Companies (Public Accounts + Lobbyist Registry):")
    enrich_companies()

    print("\n2. People (Elections + Sunshine + Lobbyist Registry):")
    enrich_people()

    print("\n3. Connections (new lobbying edges from registry):")
    enrich_connections()

    print("\n" + "=" * 50)
    print("Done. Dashboard data files enriched.")
    print("Run 'python3 -m http.server 8765' from dashboard/ to see changes.")


if __name__ == "__main__":
    main()
