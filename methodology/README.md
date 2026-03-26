# Methodology: How to Audit a Provincial Budget

This document describes the process used to build the Ontario Budget Accountability audit. It is designed to be replicable for any Canadian province or territory.

## Overview

A budget accountability audit answers four questions about every significant public expenditure:

1. **How much?** — The dollar amount
2. **Who decided?** — Which minister, which process (competitive bid vs sole-source vs override)
3. **Who benefits?** — The company, individual, or organization receiving the money
4. **What's the connection?** — Lobbyist, donor, former staffer, board appointment, or none

## Step-by-step process

### Phase 1: Budget Research

1. **Obtain the budget document.** In Ontario: budget.ontario.ca. Look for Chapter 3 (fiscal tables) for revenue and expense breakdowns by sector.

2. **Obtain the FAO analysis.** The Financial Accountability Office publishes independent budget notes, spending plan reviews by ministry, and capital plan reviews. These are more detailed and more honest than the budget document itself.

3. **Obtain Expenditure Estimates.** Each ministry publishes detailed estimates. The Ministry of Health estimates, for example, break down the $91.1B health sector into specific programs (hospital operations, OHIP billings, drug programs, etc.).

4. **Record every line item** into `budget-lines.json` with amounts and source URLs. Include prior-year amounts where available for year-over-year comparison.

### Phase 2: Contract Research

5. **Identify named contracts.** Search Infrastructure Ontario, Metrolinx, and ministry procurement portals for specific contract awards. Record: value, companies, decision type, date awarded.

6. **Classify decision types:**
   - `competitive-bid` — open competition, multiple bidders
   - `sole-source` — no competition, single vendor selected
   - `sole-bid` — competition held but only one bid received
   - `progressive-p3` — competitive selection then collaborative development phase
   - `ministerial-override` — minister's office overrode bureaucratic process
   - `legislative` — spending authorized by legislation (subsidies, tax credits)
   - `not-yet-awarded` — announced but procurement incomplete

7. **Check Auditor General reports** for each contract/program. Flag anything the AG has criticized.

### Phase 3: Political Connections

8. **Identify the people.** For each company receiving public money:
   - Who are the executives/owners?
   - Do they have registered lobbyists? (Check Ontario Lobbyist Registry)
   - Have they or their executives donated to any political party? (Check Elections Ontario)
   - Are any former government staff now working for or lobbying for the company?
   - Has the company received government board appointments?

9. **Document each relationship** with: who, to whom, type (lobbies_for, donated, worked_for, appointed_by, hired), start date, evidence, source URL.

10. **Rate connection strength** per the [verification guide](verification.md).

### Phase 4: Policy Actions

11. **Identify legislation and policy decisions** that create spending or benefit specific parties. Record: what it does, who benefits, who decided, source URL.

12. **Cross-reference** policy beneficiaries with political connection data. The most significant findings come from this cross-referencing — e.g., a lobbyist who worked for the Premier now lobbying for a company that benefits from legislation the Premier passed.

### Phase 5: Verification

13. **Audit every data point** against its source URL. See [verification guide](verification.md).

14. **Run the validation script** to check structural integrity.

15. **Have a second person review** the connection strength ratings and flag descriptions.

### Phase 6: Publication

16. **Write the narrative reports** — human-readable summaries of the findings.
17. **Publish the structured data** — JSON files with source URLs on every claim.
18. **Publish the dashboard** — optional visualization layer.

## Time estimates

| Phase | First audit | Subsequent years |
|-------|-------------|-----------------|
| Budget research | 4-6 hours | 2-3 hours (template exists) |
| Contract research | 8-12 hours | 4-6 hours (prior year as baseline) |
| Political connections | 8-12 hours | 2-4 hours (incremental) |
| Policy actions | 2-4 hours | 1-2 hours |
| Verification | 4-6 hours | 2-3 hours |
| Writing | 4-6 hours | 2-3 hours |
| **Total** | **30-46 hours** | **13-21 hours** |

An LLM assistant (Claude Code, etc.) significantly accelerates the research phases — the initial Ontario audit was completed in approximately 8 hours with LLM assistance for research, structuring, and verification. However, human judgment is required for connection strength ratings, editorial decisions, and final verification.

## Adapting for other provinces

The [schema](schema.md) is jurisdiction-agnostic. To audit another province:

1. Fork this repository
2. Replace Ontario-specific data sources with equivalent provincial sources
3. Follow the same methodology
4. Use the same JSON schema — this enables cross-provincial comparison

Key differences by province:
- **Lobbyist registries** vary in accessibility and format
- **FOI/ATIP** processes differ in cost and response time
- **Political donation** transparency varies
- Some provinces have **independent budget officers** (like Ontario's FAO); others don't
