# Data Accuracy Audit Plan

## Objective
Verify every data point in the 6 JSON files against sourced reports. This visualization will be used publicly — accuracy is non-negotiable.

## Audit Checklist

### 1. Revenue (revenue.json)
- [ ] Verify all dollar amounts against Ontario Budget 2025 Chapter 3
- [ ] Verify percentages add up to 100%
- [ ] Verify total matches $219.9B

### 2. Expenses (expenses.json)
- [ ] Verify sector totals against FAO / Budget docs
- [ ] Verify subcategory amounts against MOH Expenditure Estimates
- [ ] Verify sectors sum to $232.5B (or close, accounting for overlap)

### 3. Contracts (contracts.json)
- [ ] Every contract value has a source URL
- [ ] Values match what IO/Metrolinx/government actually announced
- [ ] Status fields are current
- [ ] Company IDs reference real entries in companies.json

### 4. Companies (companies.json)
- [ ] Every company exists and is correctly named
- [ ] total_gov_value is defensible from sources
- [ ] connection_strength ratings are justified
- [ ] lobbyist references point to real people.json entries
- [ ] donations_pc amounts are sourced

### 5. People (people.json)
- [ ] Every person's role is accurately described
- [ ] integrity_violations flag is correct (only 3: Massoudi, Fidani-Diker, Piccini)
- [ ] Client arrays match what's in connections.json
- [ ] No libellous or unsourced claims

### 6. Connections (connections.json)
- [ ] Every edge has evidence and source_url
- [ ] Types are appropriate (lobbies_for, donated, worked_for, etc.)
- [ ] Amounts are correct where specified
- [ ] No duplicate edges
- [ ] From/to IDs all exist in people.json or companies.json

## Output
- Fix any errors found
- Add source_url where missing
- Create SOURCES.md with all unique source URLs organized by topic
- Flag any claims that need additional verification

## Data Collection: Next Steps

The following enhancements would improve data completeness but are not blocking.
Listed in order of value added.

### 1. Lobbyist Registry: Pagination Support (Medium Value)

**What:** The scraper (`scripts/scrape_lobbyist_registry.py`) currently returns only the
first page of results (10 per search). Organizations like Aecon, EllisDon, Bruce Power,
IBM, and Therme Group all hit the 10-result cap and likely have more registrations.

**Value added:** Complete lobbyist counts for the 13 organizations currently capped at 10.
Would let us say "Aecon has 17 lobbyist registrations" instead of "10+". Changes the
precision of the lobbying intensity metric but unlikely to change the accountability
narrative — the first page already identifies the key firms and lobbyists.

**Effort:** The pagination detection is implemented (Telerik RadGrid `rgPageNext` button
parsing). The remaining issue is that ASP.NET requires all form fields to be replayed
on pagination postbacks. The `fetch_next_page()` method exists but needs the correct
POST payload — current attempts return HTTP 500 or the form page. Likely needs the full
set of visible form fields (radio buttons, text inputs) echoed back, not just hidden state.

**How to test:** `python3 scripts/scrape_lobbyist_registry.py --mode single --query "Aecon" --field client`
should return >10 results when pagination is working.

### 2. Lobbyist Registry: Government Target Searches (Low Value)

**What:** Run `--mode targets` to search the registry by government official title
(e.g., "Premier", "Minister of Finance", "Minister of Transportation").

**Value added:** Would show which organizations are lobbying specific ministers. However,
this produces noisy results — every lobbyist who lists "Office of the Premier" as a target
would appear, regardless of whether they're related to our tracked organizations. The
useful question ("which of our tracked orgs lobbied the Premier?") is already partially
answered by the organization search results, which show the lobbyists and their clients.

**Effort:** The `--mode targets` code is implemented. Ran once but "Premier" search failed
(likely because it's a keyword search, not a structured field). May need to use the
`txtSearchByKeyWord` field instead of `txtSearchByMinistry`.

### 3. Sunshine List: 2021-2024 Data (Low Value)

**What:** Current sunshine list coverage ends at 2020. Data for 2021-2024 exists on
`data.ontario.ca` but the package IDs/URLs weren't found during initial collection.

**Value added:** Would update salary figures for tracked people. Current data already
covers the critical period (pre-2018 government roles for revolving door analysis).
Post-2020 salary data matters mainly for people still in public sector roles.

### 4. Dashboard: Surface Cross-Reference Data (Medium-High Value)

**What:** The dashboard (`dashboard/`) currently loads `companies.json`, `people.json`,
`connections.json`, `contracts.json` — but these don't include the raw data we collected:
Public Accounts payment amounts, lobbyist registration counts/firms, Sunshine List
salaries, or Elections Ontario donation totals.

**Value added:** Would let users see at a glance: "Aecon has 10+ lobbyist registrations
via Sussex Strategy and McMillan Vantage, received $X in Public Accounts payments, and
key executives donated $Y to the PC Party." Currently this is only in the markdown
cross-reference report, not the interactive dashboard.

**What's needed:**
- Enrich `dashboard/data/companies.json` with `public_accounts_total`, `lobbyist_count`,
  `lobbyist_firms`, `donations_pc_total` fields from the cross-reference report JSON
- Enrich `dashboard/data/people.json` with `sunshine_salary`, `donation_total`,
  `lobbyist_client_count` fields
- Update `dashboard/derived/accountability-ledger.json` to include these new fields
- Update Ledger view columns and Network view tooltips to display the new data
- Rebuild `accountability-ledger.json` with enriched data
