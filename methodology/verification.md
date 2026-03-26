# Verification Guide

Every claim in this project must be verifiable. This guide defines how to verify facts and rate the strength of political connections.

## Source hierarchy

When multiple sources exist, prefer in this order:

1. **Official government records** — Budget documents, Expenditure Estimates, Public Accounts, Ontario Gazette, Hansard
2. **Independent officers** — Auditor General reports, Integrity Commissioner findings, FAO analyses
3. **Public registries** — Ontario Lobbyist Registry, Elections Ontario contributions database, Ontario Sunshine List, federal Registry of Lobbyists
4. **Court records and legal filings** — statements of claim, Integrity Commissioner decisions
5. **Investigative journalism** — Globe and Mail, Toronto Star, CBC, The Trillium, The Narwhal, National Observer (verify the primary source cited in the article where possible)
6. **Industry and trade publications** — ConstructConnect, ReNew Canada, World Nuclear News
7. **Company announcements** — press releases, investor presentations, annual reports

**Not acceptable as sole sources:** Wikipedia, social media posts, partisan press releases (NDP/Liberal/PC party websites), anonymous claims, opinion columns. These can be used to find primary sources but should not be the source_url.

## Verifying financial data

| Claim type | How to verify | Primary source |
|-----------|---------------|----------------|
| Budget line item | Check against budget tables | budget.ontario.ca Chapter 3 |
| Ministry spending | Check Expenditure Estimates | ontario.ca/page/expenditure-estimates-ministry-* |
| Contract value | Check IO/Metrolinx announcement | infrastructureontario.ca or metrolinx.com |
| Political donation | Search Elections Ontario | finances.elections.on.ca/en/contributions |
| Lobbying relationship | Search Ontario Lobbyist Registry | lobbyist.oico.on.ca |
| AG finding | Read the AG report directly | auditor.on.ca |

## Rating connection strength

Every organization in `organizations.json` has a `connection_strength` field. Use this rubric:

### `very_strong`
**All three** of the following are documented:
- Financial link (donations to PC Party or Ontario Proud)
- Lobbyist who is a former government insider
- Direct contract/policy benefit from the Ford government

**Plus** at least one of:
- Auditor General criticism of the process
- Integrity Commissioner finding
- Active investigation (RCMP, OPP)
- Minister personally involved in directing the benefit

**Examples:** Ontario Shipyards ($35K donations + Teneycke lobbyist + $22M SDF grants + $215M shipbuilding program). TACC/De Gasperis ($294K donations + 3 lobbyists + Greenbelt removal + $8B value increase + RCMP investigation).

### `strong`
**Two** of the following are documented:
- Financial link (donations)
- Lobbyist or personal connection to government insider
- Direct contract/policy benefit

**Examples:** Scale Hospitality (Massoudi as lobbyist + $10K donations + $11M SDF despite late/low-scoring application). Nieuport Aviation (Mark Lawson as lobbyist + Billy Bishop special economic zone).

### `moderate`
**One strong indicator** or **multiple weak indicators**:
- A registered lobbyist (not necessarily an insider)
- Donations without a corresponding contract benefit
- A contract benefit without documented political connections but with questions about process

**Examples:** Aecon (Coronation Medal for founder + $2M SDF + involved in many government contracts but these were won through competitive IO/Metrolinx procurement).

### `weak`
**Minor or indirect indicators:**
- An industry association that endorsed the government
- A company that benefited from a broad policy (not targeted to them)
- A historical connection that predates the current government

### `none`
No documented political connections. Won contracts through competitive procurement with no evidence of insider involvement.

**Important:** Most companies should be rated `none`. The majority of Ontario's $232.5B budget goes to legitimate recipients through proper processes. The accountability focus is on the exceptions.

## Integrity violations flag

The `integrity_violations` field in `people.json` should be `true` **only** when the Ontario Integrity Commissioner has issued a formal finding of non-compliance.

**True:** The Commissioner found the person violated the Members' Integrity Act or the Lobbyists Registration Act.

**False:** Everything else, including:
- Investigation launched but no findings yet
- Media allegations without Commissioner finding
- Opposition party accusations
- Auditor General criticism (AG criticizes programs/processes, not individuals under the Integrity Act)

Setting this flag incorrectly is a defamation risk.

## Common verification pitfalls

1. **Confusing provincial and federal donations.** Ontario banned corporate donations in 2017. Pre-2017 corporate donations are historical. Post-2017 donations are personal only (max $1,675/year). Federal donations are a separate system.

2. **Confusing Ontario PC Party donations with Ontario Proud donations.** Ontario Proud is a third-party advertiser, not the PC Party. Donations to Ontario Proud are not "PC donations."

3. **Confusing municipal and provincial donations.** Rob Ford mayoral campaign donations are not Ontario PC Party donations.

4. **Attributing full contract value to consortium members.** When 5 companies share a $6B contract, no single company "received $6B." Use `null` for individual company values where the split is not disclosed.

5. **Confusing total project cost with government expenditure.** A $13.9B hospital P3 contract includes private financing — the government doesn't write a $13.9B cheque. The distinction matters.

6. **Stating investigation = finding.** An active investigation means questions are being asked. It does not mean wrongdoing has been found.
