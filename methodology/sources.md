# Data Sources for Ontario Budget Accountability

## Official Government Sources

| Source | URL | What it contains |
|--------|-----|-----------------|
| Ontario Budget | budget.ontario.ca/2025/ | Revenue/expense totals, sector breakdowns, infrastructure plan |
| Budget Chapter 3 (Fiscal Tables) | budget.ontario.ca/2025/chapter-3.html | The actual numbers — revenue by source, expenses by sector, deficit projections |
| Ministry Expenditure Estimates | ontario.ca/page/expenditure-estimates-ministry-* | Detailed program-level spending by ministry |
| Public Accounts | ontario.ca/page/public-accounts-ontario-2024-25 | Actual spending (vs budget projections), transfer payments by recipient |
| Public Accounts Detailed Payments | ontario.ca/page/public-accounts-2024-25-detailed-schedules-payments | Every transfer payment to external recipients (hospitals, agencies, schools). Available as PDF and CSV. |
| Ontario Open Data | data.ontario.ca | Machine-readable datasets including operating grants to universities/colleges |

## Independent Officers

| Source | URL | What it contains |
|--------|-----|-----------------|
| Financial Accountability Office (FAO) | fao-on.org | Independent budget analysis, spending plan reviews by sector, capital plan reviews. More detailed and often more honest than government documents. |
| Auditor General | auditor.on.ca | Value-for-money audits, special reports (e.g., Ontario Place, COVID contracts, SDF) |
| Integrity Commissioner | oico.on.ca | Lobbying compliance findings, Members' Integrity Act investigations |

## Public Registries

| Source | URL | What it contains |
|--------|-----|-----------------|
| Ontario Lobbyist Registry | lobbyist.oico.on.ca | Registered lobbyists, their clients, and their government targets. Note: less searchable than the federal registry. |
| Elections Ontario Contributions | finances.elections.on.ca/en/contributions | Political donations by individual (corporate donations banned since 2017) |
| Ontario Sunshine List | ontario.ca/page/public-sector-salary-disclosure | Public sector employees earning $100K+ |
| Public Appointments Secretariat | pas.gov.on.ca | Government appointments to agencies, boards, commissions |
| Federal Lobbyist Registry | lobbycanada.gc.ca | More searchable than Ontario's. Many Ontario-active lobbyists are also federally registered. |

## Procurement Portals

| Source | URL | What it contains |
|--------|-----|-----------------|
| Infrastructure Ontario | infrastructureontario.ca | Major P3/AFP project procurements — contract awards, shortlists, project updates |
| Metrolinx | metrolinx.com | Transit project procurements, contract awards |
| Ontario Tenders Portal | ontario.bidsandtenders.ca | Current and past government tenders |
| MERX | merx.com | Public sector tenders and contract awards |
| IESO Contract Awards | ieso.ca/Corporate-IESO/Corporate-Procurement/Contract-Awards | Energy sector procurement |

## Investigative Journalism

| Outlet | Strength | Notable Ontario investigations |
|--------|----------|-------------------------------|
| The Trillium | thetrillium.ca | Skills Development Fund, Ontario Shipyards/Teneycke, Tony Miele/developers, Therme lobbying |
| The Narwhal | thenarwhal.ca | Greenbelt scandal, Highway 413 developers, VW PowerCo, environmental impacts |
| National Observer | nationalobserver.com | Highway 413 developer land ownership, MZO-donor connections, Greenbelt investigations |
| Globe and Mail | theglobeandmail.com | Mike Harris/Chartwell, Ford's influencers (Teneycke/Froggatt), SDF lobbyists |
| CBC News | cbc.ca | Ontario Proud donors, Dean French patronage, SAMS/IBM, Billy Bishop, Greenbelt |
| Toronto Star | thestar.com | LTC deaths by ownership type, healthcare spending |
| Global News | globalnews.ca | SDF circular economy, Metrolinx control, Greenbelt lobbying |
| CP24/CTV | cp24.com | SDF $100M lobbyist connections, Piccini wedding/Leafs game |
| Canadaland | canadaland.com | Media and political accountability |
| PressProgress | pressprogress.ca | Jenni Byrne lobbying, PC candidate Sienna shares, OSAP changes |
| HuffPost Canada | huffpost.com (archive) | LTC lobbyist donations during COVID |

## Academic/Research Sources

| Source | What it contains |
|--------|-----------------|
| CMAJ (Canadian Medical Association Journal) | Peer-reviewed study on for-profit vs non-profit LTC death rates during COVID |
| ICES (Institute for Clinical Evaluative Sciences) | Ontario physician payment data by specialty |
| CIHI (Canadian Institute for Health Information) | Comparative health spending data across provinces |

## Data Collection (automated scripts)

The `scripts/` directory contains tools that download and cross-reference data from the public registries above. All scripts use Python standard library only (no pip dependencies).

| Script | Source | Records | Output |
|--------|--------|---------|--------|
| `cross_reference_donations.py` | Elections Ontario bulk API | 429,434 contribution records (2014-present) | `raw-data/elections-ontario/cross_reference_results.json` |
| `cross_reference_payments.py` | Ontario Public Accounts CSVs | 30,306 payment records (2023-25) | `raw-data/public-accounts/cross-reference-results.json` |
| `cross_reference_sunshine.py` | Sunshine List CSVs + GitHub archive | 2,049,386 salary records (1996-2020) | `raw-data/sunshine-list/cross-reference-results.json` |
| `scrape_lobbyist_registry.py` | OICO Lobbyist Registry (ASP.NET) | 246 org + 144 people registrations | `raw-data/lobbyist-registry/org_search_results.json` |
| `build_crossref_report.py` | Joins all 4 sources above | 129 orgs + 42 people profiled | `audits/2025-26/research/cross-reference-report.md` |
| `enrich_dashboard_data.py` | Merges crossref into dashboard | Enriches companies.json, people.json, connections.json | `dashboard/data/*.json` |

### Data provenance

- **Elections Ontario:** Bulk download via `GET https://finances.elections.on.ca/api/bulk-data/download?downloadToken=CS-en-AllYears`. Returns ZIP with CSV of all contribution records. Corporate donations banned Sept 2017; pre-2017 records include corporate donors.
- **Public Accounts:** CSV from `data.ontario.ca/dataset/public-accounts-detailed-schedule-of-payments`. Covers direct provincial payments only — crown agency payments (Metrolinx, IO, OPG) are not included.
- **Sunshine List:** CSVs from `data.ontario.ca` (2018-2020) + GitHub `pbeens/Sunshine-List-CSV` (1996-2020). $100K disclosure threshold, not inflation-adjusted.
- **Lobbyist Registry:** Scraped from `lobbyist.oico.on.ca` ASP.NET Web Forms application. Polite scraping (2.5s between requests). Results capped at 10 per search (first page). Session cookies required.

## How to use these sources

**For a new budget year:**
1. Start with the Budget document (Chapter 3 for numbers)
2. Cross-reference with FAO budget note (for what the government isn't saying)
3. Check Expenditure Estimates for program-level detail
4. Wait for AG annual report (usually December) for accountability findings

**For a new contract:**
1. Check IO or Metrolinx for the official award announcement
2. Check trade publications (ConstructConnect, ReNew Canada) for consortium details
3. Check the Lobbyist Registry for any registered lobbyists for the winning company
4. Check Elections Ontario for executive donations

**For a new political connection:**
1. Start with the Lobbyist Registry (Ontario and federal)
2. Cross-reference with Elections Ontario contributions
3. Search investigative journalism (The Trillium and National Observer are strongest on Ontario connections)
4. Check the Public Appointments Secretariat for board appointments
5. Verify against primary sources before adding to the dataset
