#!/usr/bin/env python3
"""
Ontario Budget Import & Analysis Tool

Manages budget data for the Ontario provincial spending visualization.
Supports importing new budget years, computing year-over-year changes,
generating accountability ledgers, and validating data integrity.

Usage:
    python3 scripts/import_budget.py template 2026-27
    python3 scripts/import_budget.py diff 2025-26 2026-27
    python3 scripts/import_budget.py ledger 2025-26
    python3 scripts/import_budget.py validate 2025-26

All paths are relative to the project root (viz/).
"""

import argparse
import copy
import json
import os
import sys
from datetime import date

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

# Project root: two levels up from this script (viz/scripts/ -> viz/)
PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))

# Old-format data lives in viz/data/
OLD_DATA_DIR = os.path.join(PROJECT_ROOT, "data")

# New-format data lives in viz/decisions/YYYY-YY/
DECISIONS_DIR = os.path.join(PROJECT_ROOT, "decisions")

# Derived output dir
DERIVED_DIR = os.path.join(PROJECT_ROOT, "derived")


def decisions_dir_for(year):
    return os.path.join(DECISIONS_DIR, year)


def budget_lines_path(year):
    return os.path.join(decisions_dir_for(year), "budget-lines.json")


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------

def load_json(path):
    """Load and return parsed JSON from path, or None if missing."""
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    """Write data as formatted JSON."""
    ensure_dir(os.path.dirname(path))
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"  Wrote: {os.path.relpath(path, PROJECT_ROOT)}")


def prior_year(year_str):
    """Given '2026-27', return '2025-26'."""
    parts = year_str.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        sys.exit(f"Error: Invalid fiscal year format '{year_str}'. Expected YYYY-YY (e.g. 2026-27).")
    start = int(parts[0])
    return f"{start - 1}-{int(parts[1]) - 1:02d}"


def load_budget_data(year):
    """
    Load revenue and expense data for a given fiscal year.

    Checks two locations:
      1. decisions/YYYY-YY/budget-lines.json  (new format, combined)
      2. data/revenue.json + data/expenses.json (old format, if year matches)

    Returns (revenue_dict, expenses_dict) or exits with error.
    """
    bl_path = budget_lines_path(year)
    bl = load_json(bl_path)
    if bl is not None:
        # New format produced by this script: revenue_sources / expense_sectors
        # Older hand-written format: revenue / expenses + total_revenue / total_expenses
        rev_sources = (
            bl.get("revenue_sources")
            or bl.get("revenue", [])
        )
        exp_sectors = (
            bl.get("expense_sectors")
            or bl.get("expenses", [])
        )
        rev_total = (
            bl.get("revenue_total")
            or bl.get("total_revenue")
        )
        exp_total = (
            bl.get("expense_total")
            or bl.get("total_expenses")
        )
        revenue = {
            "total": rev_total,
            "year": year,
            "sources": rev_sources if isinstance(rev_sources, list) else [],
        }
        expenses = {
            "total": exp_total,
            "year": year,
            "sectors": exp_sectors if isinstance(exp_sectors, list) else [],
        }
        return revenue, expenses

    # Fall back to old format
    rev_path = os.path.join(OLD_DATA_DIR, "revenue.json")
    exp_path = os.path.join(OLD_DATA_DIR, "expenses.json")
    rev = load_json(rev_path)
    exp = load_json(exp_path)

    if rev and rev.get("year") == year:
        return rev, exp
    if exp and exp.get("year") == year:
        return rev, exp

    sys.exit(
        f"Error: No budget data found for {year}.\n"
        f"  Looked in: {bl_path}\n"
        f"  Looked in: {rev_path} (year={rev.get('year') if rev else 'N/A'})\n"
        f"  Looked in: {exp_path} (year={exp.get('year') if exp else 'N/A'})"
    )


def load_all_entity_data(year):
    """
    Load contracts, companies, people, connections for a year.
    Checks decisions/YYYY-YY/ first, then falls back to data/.
    """
    dec_dir = decisions_dir_for(year)
    files = {
        "contracts": "contracts.json",
        "companies": "companies.json",
        "people": "people.json",
        "connections": "connections.json",
    }
    # Also check for alternate key names in old format
    # Old format: companies.json has {"companies": [...]}, etc.
    result = {}
    for key, filename in files.items():
        # Try decisions dir first
        new_path = os.path.join(dec_dir, filename)
        data = load_json(new_path)
        if data is not None:
            result[key] = data
            continue
        # Fall back to old data dir
        old_path = os.path.join(OLD_DATA_DIR, filename)
        data = load_json(old_path)
        if data is not None:
            result[key] = data
        else:
            result[key] = None
    return result


# ---------------------------------------------------------------------------
# Mode 1: template
# ---------------------------------------------------------------------------

def cmd_template(args):
    """Generate a template budget-lines.json for a new fiscal year."""
    year = args.year
    prev = prior_year(year)

    print(f"Generating budget template for {year} based on {prev}...")

    revenue, expenses = load_budget_data(prev)

    # Build template revenue sources with amounts nulled out
    template_sources = []
    for src in revenue.get("sources", []):
        entry = copy.deepcopy(src)
        entry["amount"] = None
        template_sources.append(entry)

    # Build template expense sectors with amounts nulled out
    template_sectors = []
    for sector in expenses.get("sectors", []):
        entry = copy.deepcopy(sector)
        entry["amount"] = None
        if "subcategories" in entry:
            for sub in entry["subcategories"]:
                sub["amount"] = None
        template_sectors.append(entry)

    template = {
        "_comment": f"Budget lines for {year}. Fill in amounts from the budget document. "
                    f"Structure copied from {prev}. Set amounts to actual figures (in dollars, not thousands).",
        "fiscal_year": year,
        "based_on": prev,
        "source_url": None,
        "revenue_total": None,
        "revenue_sources": template_sources,
        "expense_total": None,
        "expense_sectors": template_sectors,
    }

    out_path = budget_lines_path(year)
    save_json(out_path, template)

    # Count items
    n_rev = len(template_sources)
    n_sec = len(template_sectors)
    n_sub = sum(len(s.get("subcategories", [])) for s in template_sectors)

    print(f"\nTemplate created with:")
    print(f"  {n_rev} revenue sources (amounts set to null)")
    print(f"  {n_sec} expense sectors, {n_sub} subcategories (amounts set to null)")
    print(f"\nNext steps:")
    print(f"  1. Open {os.path.relpath(out_path, PROJECT_ROOT)}")
    print(f"  2. Fill in revenue_total, expense_total, and all amounts")
    print(f"  3. Add/remove line items as needed for the new budget")
    print(f"  4. Run: python3 scripts/import_budget.py validate {year}")
    print(f"  5. Run: python3 scripts/import_budget.py diff {prev} {year}")


# ---------------------------------------------------------------------------
# Mode 2: diff
# ---------------------------------------------------------------------------

def compute_change(old_val, new_val):
    """Compute change and percentage. Handles None values."""
    if old_val is None or new_val is None:
        return {"old": old_val, "new": new_val, "change": None, "change_pct": None}
    change = new_val - old_val
    pct = round((change / old_val) * 100, 2) if old_val != 0 else None
    return {"old": old_val, "new": new_val, "change": change, "change_pct": pct}


def cmd_diff(args):
    """Compute year-over-year changes between two budget years."""
    from_year = args.from_year
    to_year = args.to_year

    print(f"Computing year-over-year changes: {from_year} -> {to_year}...")

    rev_old, exp_old = load_budget_data(from_year)
    rev_new, exp_new = load_budget_data(to_year)

    # --- Revenue changes ---
    old_rev_by_id = {s["id"]: s for s in rev_old.get("sources", [])}
    new_rev_by_id = {s["id"]: s for s in rev_new.get("sources", [])}

    all_rev_ids = list(dict.fromkeys(
        list(old_rev_by_id.keys()) + list(new_rev_by_id.keys())
    ))

    revenue_changes = []
    new_items = []
    removed_items = []

    for rid in all_rev_ids:
        old_src = old_rev_by_id.get(rid)
        new_src = new_rev_by_id.get(rid)

        if old_src and new_src:
            ch = compute_change(old_src.get("amount"), new_src.get("amount"))
            ch["id"] = rid
            ch["name"] = new_src.get("name", old_src.get("name"))
            revenue_changes.append(ch)
        elif new_src and not old_src:
            new_items.append({
                "id": rid,
                "name": new_src.get("name"),
                "type": "revenue",
                "amount": new_src.get("amount"),
            })
        elif old_src and not new_src:
            removed_items.append({
                "id": rid,
                "name": old_src.get("name"),
                "type": "revenue",
                "amount": old_src.get("amount"),
            })

    # --- Expense changes ---
    old_exp_by_id = {s["id"]: s for s in exp_old.get("sectors", [])}
    new_exp_by_id = {s["id"]: s for s in exp_new.get("sectors", [])}

    all_exp_ids = list(dict.fromkeys(
        list(old_exp_by_id.keys()) + list(new_exp_by_id.keys())
    ))

    expense_changes = []

    for eid in all_exp_ids:
        old_sec = old_exp_by_id.get(eid)
        new_sec = new_exp_by_id.get(eid)

        if old_sec and new_sec:
            ch = compute_change(old_sec.get("amount"), new_sec.get("amount"))
            ch["id"] = eid
            ch["name"] = new_sec.get("name", old_sec.get("name"))

            # Subcategory changes
            old_subs = {s["id"]: s for s in old_sec.get("subcategories", [])}
            new_subs = {s["id"]: s for s in new_sec.get("subcategories", [])}
            all_sub_ids = list(dict.fromkeys(
                list(old_subs.keys()) + list(new_subs.keys())
            ))

            sub_changes = []
            for sid in all_sub_ids:
                old_sub = old_subs.get(sid)
                new_sub = new_subs.get(sid)
                if old_sub and new_sub:
                    sc = compute_change(old_sub.get("amount"), new_sub.get("amount"))
                    sc["id"] = sid
                    sc["name"] = new_sub.get("name", old_sub.get("name"))
                    sub_changes.append(sc)
                elif new_sub and not old_sub:
                    new_items.append({
                        "id": sid,
                        "name": new_sub.get("name"),
                        "type": "expense_subcategory",
                        "parent_sector": eid,
                        "amount": new_sub.get("amount"),
                    })
                elif old_sub and not new_sub:
                    removed_items.append({
                        "id": sid,
                        "name": old_sub.get("name"),
                        "type": "expense_subcategory",
                        "parent_sector": eid,
                        "amount": old_sub.get("amount"),
                    })

            if sub_changes:
                ch["subcategory_changes"] = sub_changes
            expense_changes.append(ch)

        elif new_sec and not old_sec:
            new_items.append({
                "id": eid,
                "name": new_sec.get("name"),
                "type": "expense_sector",
                "amount": new_sec.get("amount"),
            })
        elif old_sec and not new_sec:
            removed_items.append({
                "id": eid,
                "name": old_sec.get("name"),
                "type": "expense_sector",
                "amount": old_sec.get("amount"),
            })

    # --- Totals ---
    total_revenue_change = compute_change(
        rev_old.get("total"), rev_new.get("total")
    )
    total_expense_change = compute_change(
        exp_old.get("total"), exp_new.get("total")
    )

    # Deficit = expenses - revenue (positive = deficit)
    old_deficit = None
    new_deficit = None
    if rev_old.get("total") is not None and exp_old.get("total") is not None:
        old_deficit = exp_old["total"] - rev_old["total"]
    if rev_new.get("total") is not None and exp_new.get("total") is not None:
        new_deficit = exp_new["total"] - rev_new["total"]
    deficit_change = compute_change(old_deficit, new_deficit)

    result = {
        "from_year": from_year,
        "to_year": to_year,
        "generated": date.today().isoformat(),
        "revenue_changes": revenue_changes,
        "expense_changes": expense_changes,
        "new_items": new_items,
        "removed_items": removed_items,
        "total_revenue_change": total_revenue_change,
        "total_expense_change": total_expense_change,
        "deficit_change": deficit_change,
    }

    out_path = os.path.join(DERIVED_DIR, "year-over-year.json")
    save_json(out_path, result)

    # Print summary
    print(f"\nYear-over-year summary ({from_year} -> {to_year}):")
    print(f"  Revenue: ${_fmt(total_revenue_change.get('old'))} -> ${_fmt(total_revenue_change.get('new'))}"
          f" ({_fmt_pct(total_revenue_change.get('change_pct'))})")
    print(f"  Expenses: ${_fmt(total_expense_change.get('old'))} -> ${_fmt(total_expense_change.get('new'))}"
          f" ({_fmt_pct(total_expense_change.get('change_pct'))})")
    print(f"  Deficit: ${_fmt(old_deficit)} -> ${_fmt(new_deficit)}"
          f" ({_fmt_pct(deficit_change.get('change_pct'))})")
    print(f"  Revenue line changes: {len(revenue_changes)}")
    print(f"  Expense sector changes: {len(expense_changes)}")
    if new_items:
        print(f"  New items: {len(new_items)}")
        for item in new_items:
            print(f"    + {item['name']} ({item['type']})")
    if removed_items:
        print(f"  Removed items: {len(removed_items)}")
        for item in removed_items:
            print(f"    - {item['name']} ({item['type']})")


def _fmt(val):
    """Format a dollar value for display."""
    if val is None:
        return "N/A"
    billions = val / 1_000_000_000
    return f"{billions:,.1f}B"


def _fmt_pct(val):
    """Format a percentage change for display."""
    if val is None:
        return "N/A"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.2f}%"


# ---------------------------------------------------------------------------
# Mode 3: ledger
# ---------------------------------------------------------------------------

def cmd_ledger(args):
    """Generate an accountability ledger joining all data for a fiscal year."""
    year = args.year

    print(f"Generating accountability ledger for {year}...")

    _, expenses = load_budget_data(year)
    entity_data = load_all_entity_data(year)

    contracts_data = entity_data.get("contracts")
    companies_data = entity_data.get("companies")
    people_data = entity_data.get("people")
    connections_data = entity_data.get("connections")

    # Build lookup indexes
    contracts_list = []
    if contracts_data:
        contracts_list = contracts_data.get("contracts", contracts_data if isinstance(contracts_data, list) else [])

    contracts_by_id = {c["id"]: c for c in contracts_list}

    companies_list = []
    if companies_data:
        companies_list = companies_data.get("companies", companies_data if isinstance(companies_data, list) else [])
    companies_by_id = {c["id"]: c for c in companies_list}

    people_list = []
    if people_data:
        people_list = people_data.get("people", people_data if isinstance(people_data, list) else [])
    people_by_id = {p["id"]: p for p in people_list}

    connections_list = []
    if connections_data:
        connections_list = connections_data.get("connections", connections_data if isinstance(connections_data, list) else [])

    # Build connection indexes: company_id -> list of connections
    # Also: person -> companies they lobby for
    company_connections = {}  # company_id -> [connection, ...]
    person_to_companies = {}  # person_id -> [company_id, ...]

    for conn in connections_list:
        from_id = conn.get("from")
        to_id = conn.get("to")
        conn_type = conn.get("type")

        # If a person lobbies_for a company
        if conn_type == "lobbies_for":
            person_to_companies.setdefault(from_id, []).append(to_id)
            company_connections.setdefault(to_id, []).append(conn)

        # If a company donated
        if conn_type == "donated":
            company_connections.setdefault(from_id, []).append(conn)

        # If person worked_for someone (political connections)
        if conn_type == "worked_for":
            company_connections.setdefault(from_id, []).append(conn)

    # For each company, find connected people (lobbyists + insiders)
    company_people = {}  # company_id -> [person_id, ...]
    company_lobbyists = {}  # company_id -> [person_id, ...]

    for person in people_list:
        pid = person["id"]
        ptype = person.get("type", "")
        clients = person.get("clients", [])
        for client_id in clients:
            company_people.setdefault(client_id, []).append(pid)
            if "lobbyist" in ptype:
                company_lobbyists.setdefault(client_id, []).append(pid)

    # Also check company records for lobbyist fields
    for comp in companies_list:
        cid = comp["id"]
        for lob_id in comp.get("lobbyists", []):
            if lob_id not in company_lobbyists.get(cid, []):
                company_lobbyists.setdefault(cid, []).append(lob_id)
            if lob_id not in company_people.get(cid, []):
                company_people.setdefault(cid, []).append(lob_id)

    # Determine which contracts are referenced from expense subcategories
    contract_to_sector = {}
    for sector in expenses.get("sectors", []):
        sector_name = sector.get("name", sector.get("id"))
        for sub in sector.get("subcategories", []):
            for cid in sub.get("contracts", []):
                contract_to_sector[cid] = sector_name

    # Build ledger rows from contracts
    rows = []
    summary = {
        "total_decisions": 0,
        "total_value": 0,
        "flagged_by_ag": 0,
        "sole_source": 0,
        "insider_connected": 0,
        "total_through_insider_lobbyists": 0,
    }

    for contract in contracts_list:
        cid = contract["id"]
        company_ids = contract.get("companies", [])

        # Determine sector from expense mapping, or from contract itself
        sector = contract_to_sector.get(cid, contract.get("sector", "unknown"))

        # Determine decision type
        decision_type = "competitive"  # default
        _name = contract.get("name") or ""
        _notes = contract.get("notes") or ""
        _src_url = contract.get("source_url") or ""
        name_lower = (_name + " " + _notes).lower()
        if "sole-source" in name_lower or "sole source" in name_lower:
            decision_type = "sole-source"
        elif "sole-bid" in name_lower or "single bid" in name_lower:
            decision_type = "sole-bid"

        status = contract.get("status", "unknown")

        # Determine decision maker
        decision_maker = "Ontario Government"
        if any(kw in name_lower for kw in ["infrastructure ontario", "io "]):
            decision_maker = "Infrastructure Ontario"
        elif "metrolinx" in name_lower:
            decision_maker = "Metrolinx"
        elif "opg" in name_lower or "nuclear" in name_lower or "darlington" in name_lower or "pickering" in name_lower:
            decision_maker = "OPG / Ontario Energy"
        elif "hydro one" in name_lower:
            decision_maker = "Hydro One"
        # Infer from sector
        if sector == "transit-transportation" or "transit" in sector.lower():
            if decision_maker == "Ontario Government":
                decision_maker = "Infrastructure Ontario / Metrolinx"
        if "hospital" in name_lower:
            if decision_maker == "Ontario Government":
                decision_maker = "Infrastructure Ontario"
        if "sdf" in cid or "skills development" in name_lower:
            decision_maker = "Ministry of Labour"

        # Gather recipient info
        recipient_names = []
        for comp_id in company_ids:
            comp = companies_by_id.get(comp_id)
            if comp:
                recipient_names.append(comp.get("name", comp_id))
            else:
                recipient_names.append(comp_id)
        recipient = " + ".join(recipient_names) if recipient_names else "Unknown"

        # Connection analysis
        connected_people_set = set()
        connected_lobbyists_set = set()
        for comp_id in company_ids:
            for pid in company_people.get(comp_id, []):
                connected_people_set.add(pid)
            for pid in company_lobbyists.get(comp_id, []):
                connected_lobbyists_set.add(pid)

        # Connection strength from companies
        strengths = []
        for comp_id in company_ids:
            comp = companies_by_id.get(comp_id)
            if comp:
                strengths.append(comp.get("connection_strength", "none"))

        # Strongest connection wins
        strength_order = {"very_strong": 4, "strong": 3, "moderate": 2, "weak": 1, "none": 0}
        connection_strength = "none"
        for s in strengths:
            if strength_order.get(s, 0) > strength_order.get(connection_strength, 0):
                connection_strength = s

        # Flags
        flags = []
        all_text_lower = (_notes + " " + _src_url).lower()
        if ("auditor" in all_text_lower or "ag " in all_text_lower
                or "ag found" in all_text_lower or "auditor general" in all_text_lower
                or "auditor-general" in all_text_lower):
            flags.append("ag_flagged")
        if decision_type in ("sole-source", "sole-bid"):
            flags.append("sole_source")
        if "fraud" in all_text_lower or "opp investigating" in all_text_lower:
            flags.append("fraud_investigation")
        if "terminated" in status:
            flags.append("terminated")
        if contract.get("needs_verification"):
            flags.append("needs_verification")
        if connected_lobbyists_set:
            flags.append("insider_lobbyist")
        if connection_strength in ("strong", "moderate"):
            flags.append("insider_connected")

        # AG finding
        ag_finding = None
        if "ag_flagged" in flags:
            ag_finding = _notes if _notes else None

        value = contract.get("value")

        row = {
            "id": cid,
            "name": contract.get("name"),
            "amount": value,
            "sector": sector,
            "status": status,
            "decision_type": decision_type,
            "decision_maker": decision_maker,
            "recipient": recipient,
            "recipient_ids": company_ids,
            "connection_strength": connection_strength,
            "connected_people": sorted(connected_people_set),
            "connected_lobbyists": sorted(connected_lobbyists_set),
            "flags": flags,
            "ag_finding": ag_finding,
            "source_url": contract.get("source_url", ""),
        }
        rows.append(row)

        # Update summary
        summary["total_decisions"] += 1
        if value:
            summary["total_value"] += value
        if "ag_flagged" in flags:
            summary["flagged_by_ag"] += 1
        if "sole_source" in flags:
            summary["sole_source"] += 1
        if connection_strength in ("strong", "moderate"):
            summary["insider_connected"] += 1
        if connected_lobbyists_set and value:
            summary["total_through_insider_lobbyists"] += value

    ledger = {
        "fiscal_year": year,
        "generated": date.today().isoformat(),
        "summary": summary,
        "rows": rows,
    }

    out_path = os.path.join(DERIVED_DIR, "accountability-ledger.json")
    save_json(out_path, ledger)

    print(f"\nAccountability ledger summary for {year}:")
    print(f"  Total decisions: {summary['total_decisions']}")
    print(f"  Total value: ${_fmt(summary['total_value'])}")
    print(f"  Flagged by AG: {summary['flagged_by_ag']}")
    print(f"  Sole-source/sole-bid: {summary['sole_source']}")
    print(f"  Insider-connected (strong/moderate): {summary['insider_connected']}")
    print(f"  Total $ through insider lobbyists: ${_fmt(summary['total_through_insider_lobbyists'])}")

    # Warn about missing source_urls
    missing_urls = [r for r in rows if not r.get("source_url")]
    if missing_urls:
        print(f"\n  WARNING: {len(missing_urls)} contracts missing source_url:")
        for r in missing_urls:
            print(f"    - {r['id']}: {r['name']}")


# ---------------------------------------------------------------------------
# Mode 4: validate
# ---------------------------------------------------------------------------

def cmd_validate(args):
    """Validate data integrity for a given fiscal year."""
    year = args.year
    errors = []
    warnings = []

    print(f"Validating data integrity for {year}...\n")

    # --- 1. Load and validate JSON files ---
    revenue = None
    expenses = None

    try:
        revenue, expenses = load_budget_data(year)
    except SystemExit as e:
        errors.append(f"Cannot load budget data: {e}")

    entity_data = load_all_entity_data(year)
    contracts_data = entity_data.get("contracts")
    companies_data = entity_data.get("companies")
    people_data = entity_data.get("people")
    connections_data = entity_data.get("connections")

    # Also try loading raw JSON to check validity
    json_files_to_check = []
    bl_path = budget_lines_path(year)
    if os.path.exists(bl_path):
        json_files_to_check.append(bl_path)
    for fname in ["revenue.json", "expenses.json", "contracts.json", "companies.json", "people.json", "connections.json"]:
        fpath = os.path.join(OLD_DATA_DIR, fname)
        if os.path.exists(fpath):
            json_files_to_check.append(fpath)

    for fpath in json_files_to_check:
        try:
            with open(fpath, "r") as f:
                json.load(f)
            _ok(f"Valid JSON: {os.path.relpath(fpath, PROJECT_ROOT)}")
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in {os.path.relpath(fpath, PROJECT_ROOT)}: {e}")

    # --- 2. Revenue sources sum to total ---
    if revenue:
        sources = revenue.get("sources", [])
        source_sum = sum(s.get("amount", 0) or 0 for s in sources)
        total = revenue.get("total")
        if total is not None:
            diff = abs(source_sum - total)
            if diff == 0:
                _ok(f"Revenue sources sum exactly to total (${_fmt(total)})")
            elif diff <= total * 0.02:
                # Within 2% tolerance (rounding items exist)
                _ok(f"Revenue sources sum to ${_fmt(source_sum)} vs total ${_fmt(total)} "
                    f"(diff: ${_fmt(diff)}, within rounding tolerance)")
            else:
                errors.append(
                    f"Revenue sources sum (${_fmt(source_sum)}) does not match "
                    f"total (${_fmt(total)}). Difference: ${_fmt(diff)}"
                )
        else:
            warnings.append("Revenue total is null")

        null_amounts = [s["id"] for s in sources if s.get("amount") is None]
        if null_amounts:
            warnings.append(f"Revenue sources with null amounts: {', '.join(null_amounts)}")

    # --- 3. Expense sectors sum to total ---
    if expenses:
        sectors = expenses.get("sectors", [])
        sector_sum = sum(s.get("amount", 0) or 0 for s in sectors)
        total = expenses.get("total")
        if total is not None:
            diff = abs(sector_sum - total)
            if diff == 0:
                _ok(f"Expense sectors sum exactly to total (${_fmt(total)})")
            elif diff <= total * 0.02:
                _ok(f"Expense sectors sum to ${_fmt(sector_sum)} vs total ${_fmt(total)} "
                    f"(diff: ${_fmt(diff)}, within rounding tolerance)")
            else:
                errors.append(
                    f"Expense sectors sum (${_fmt(sector_sum)}) does not match "
                    f"total (${_fmt(total)}). Difference: ${_fmt(diff)}"
                )
        else:
            warnings.append("Expense total is null")

        # Check subcategory sums
        for sector in sectors:
            subs = sector.get("subcategories", [])
            if subs:
                sub_sum = sum(s.get("amount", 0) or 0 for s in subs)
                sec_amt = sector.get("amount", 0) or 0
                if sec_amt > 0:
                    diff = abs(sub_sum - sec_amt)
                    if diff <= sec_amt * 0.05:
                        _ok(f"  {sector['name']}: subcategories sum to ${_fmt(sub_sum)} "
                            f"vs sector ${_fmt(sec_amt)}")
                    else:
                        warnings.append(
                            f"  {sector['name']}: subcategories sum (${_fmt(sub_sum)}) "
                            f"differs from sector total (${_fmt(sec_amt)}) by ${_fmt(diff)}"
                        )

        null_sectors = [s["id"] for s in sectors if s.get("amount") is None]
        if null_sectors:
            warnings.append(f"Expense sectors with null amounts: {', '.join(null_sectors)}")

    # --- 4. Contract company references ---
    if contracts_data and companies_data:
        contracts_list = contracts_data.get("contracts", [])
        companies_list = companies_data.get("companies", [])
        company_ids = {c["id"] for c in companies_list}

        missing_companies = set()
        for contract in contracts_list:
            for comp_id in contract.get("companies", []):
                if comp_id not in company_ids:
                    missing_companies.add(comp_id)

        if missing_companies:
            errors.append(
                f"Company IDs in contracts not found in companies.json: "
                f"{', '.join(sorted(missing_companies))}"
            )
        else:
            _ok(f"All company IDs in contracts exist in companies.json "
                f"({len(company_ids)} companies, {len(contracts_list)} contracts)")

    # --- 5. Person IDs in relationships ---
    if connections_data and people_data and companies_data:
        connections_list = connections_data.get("connections", [])
        people_list = people_data.get("people", [])
        companies_list = companies_data.get("companies", [])

        person_ids = {p["id"] for p in people_list}
        company_ids = {c["id"] for c in companies_list}
        all_entity_ids = person_ids | company_ids
        # Also add 'doug-ford' and other known entities that might be targets
        # (they should be in people.json)

        missing_from = set()
        missing_to = set()
        for conn in connections_list:
            from_id = conn.get("from")
            to_id = conn.get("to")
            if from_id not in all_entity_ids:
                missing_from.add(from_id)
            if to_id not in all_entity_ids:
                missing_to.add(to_id)

        if missing_from:
            errors.append(
                f"Connection 'from' IDs not found in people or companies: "
                f"{', '.join(sorted(missing_from))}"
            )
        if missing_to:
            errors.append(
                f"Connection 'to' IDs not found in people or companies: "
                f"{', '.join(sorted(missing_to))}"
            )
        if not missing_from and not missing_to:
            _ok(f"All from/to IDs in connections exist ({len(connections_list)} connections)")

    # --- 6. Orphan nodes ---
    if contracts_data and companies_data and connections_data:
        contracts_list = contracts_data.get("contracts", [])
        companies_list = companies_data.get("companies", [])
        connections_list = connections_data.get("connections", [])

        # Companies referenced in contracts or connections
        referenced_companies = set()
        for contract in contracts_list:
            for comp_id in contract.get("companies", []):
                referenced_companies.add(comp_id)
        for conn in connections_list:
            referenced_companies.add(conn.get("from"))
            referenced_companies.add(conn.get("to"))

        orphan_companies = []
        for comp in companies_list:
            if comp["id"] not in referenced_companies:
                orphan_companies.append(comp["id"])

        if orphan_companies:
            warnings.append(
                f"Orphan companies (no contracts or connections): "
                f"{', '.join(sorted(orphan_companies))}"
            )
        else:
            _ok(f"No orphan companies found")

    if people_data and connections_data and companies_data:
        people_list = people_data.get("people", [])
        connections_list = connections_data.get("connections", [])
        companies_list = companies_data.get("companies", [])

        # People referenced in connections or as lobbyists in companies
        referenced_people = set()
        for conn in connections_list:
            referenced_people.add(conn.get("from"))
            referenced_people.add(conn.get("to"))
        for comp in companies_list:
            for lob_id in comp.get("lobbyists", []):
                referenced_people.add(lob_id)

        orphan_people = []
        for person in people_list:
            if person["id"] not in referenced_people:
                orphan_people.append(person["id"])

        if orphan_people:
            warnings.append(
                f"Orphan people (no connections or lobbyist refs): "
                f"{', '.join(sorted(orphan_people))}"
            )
        else:
            _ok(f"No orphan people found")

    # --- 7. Missing source_url ---
    if contracts_data:
        contracts_list = contracts_data.get("contracts", [])
        no_url = [c["id"] for c in contracts_list if not c.get("source_url")]
        if no_url:
            warnings.append(f"{len(no_url)} contracts missing source_url: {', '.join(no_url)}")
        else:
            _ok(f"All contracts have source_url")

    # --- 8. Contract IDs referenced in expenses exist in contracts.json ---
    if expenses and contracts_data:
        contracts_list = contracts_data.get("contracts", [])
        contract_ids = {c["id"] for c in contracts_list}

        missing_contract_refs = set()
        for sector in expenses.get("sectors", []):
            for sub in sector.get("subcategories", []):
                for ref_id in sub.get("contracts", []):
                    if ref_id not in contract_ids:
                        missing_contract_refs.add(ref_id)

        if missing_contract_refs:
            errors.append(
                f"Contract IDs in expenses not found in contracts.json: "
                f"{', '.join(sorted(missing_contract_refs))}"
            )
        else:
            _ok("All contract references in expenses exist in contracts.json")

    # --- Summary ---
    print()
    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  [ERROR] {e}")
    if warnings:
        print(f"\nWARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  [WARN]  {w}")
    if not errors and not warnings:
        print("All checks passed with no errors or warnings.")
    elif not errors:
        print(f"\nValidation passed with {len(warnings)} warning(s) and 0 errors.")
    else:
        print(f"\nValidation FAILED: {len(errors)} error(s), {len(warnings)} warning(s).")
        sys.exit(1)


def _ok(msg):
    print(f"  [OK]    {msg}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Ontario Budget Import & Analysis Tool",
        epilog=(
            "Examples:\n"
            "  python3 scripts/import_budget.py template 2026-27\n"
            "  python3 scripts/import_budget.py diff 2025-26 2026-27\n"
            "  python3 scripts/import_budget.py ledger 2025-26\n"
            "  python3 scripts/import_budget.py validate 2025-26\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # template
    p_template = subparsers.add_parser(
        "template",
        help="Generate a budget-lines.json template for a new fiscal year, "
             "pre-populated with the prior year's structure (amounts set to null).",
    )
    p_template.add_argument(
        "year",
        help="Fiscal year to generate template for (e.g. 2026-27)",
    )

    # diff
    p_diff = subparsers.add_parser(
        "diff",
        help="Compute year-over-year changes between two budget years. "
             "Produces derived/year-over-year.json.",
    )
    p_diff.add_argument("from_year", help="Earlier fiscal year (e.g. 2025-26)")
    p_diff.add_argument("to_year", help="Later fiscal year (e.g. 2026-27)")

    # ledger
    p_ledger = subparsers.add_parser(
        "ledger",
        help="Generate an accountability ledger joining contracts, companies, "
             "people, and connections into a flat table. Produces derived/accountability-ledger.json.",
    )
    p_ledger.add_argument("year", help="Fiscal year (e.g. 2025-26)")

    # validate
    p_validate = subparsers.add_parser(
        "validate",
        help="Validate data integrity: JSON validity, sums, ID references, "
             "orphan nodes, missing source URLs.",
    )
    p_validate.add_argument("year", help="Fiscal year to validate (e.g. 2025-26)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    print(f"Ontario Budget Tool - {args.command}")
    print("=" * 50)

    if args.command == "template":
        cmd_template(args)
    elif args.command == "diff":
        cmd_diff(args)
    elif args.command == "ledger":
        cmd_ledger(args)
    elif args.command == "validate":
        cmd_validate(args)


if __name__ == "__main__":
    main()
