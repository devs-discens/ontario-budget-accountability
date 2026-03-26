# Data Schema

The data model is designed to be reusable across jurisdictions. The core concept: every significant public expenditure is a **decision** that can be linked to **entities** (people and organizations) through **relationships**.

## Directory structure

```
audits/{fiscal-year}/
  data/
    budget-lines.json       Revenue and expense line items
    contracts.json          Procurement decisions
    policy-actions.json     Legislative/policy decisions
    appointments.json       Board/agency appointments
    people.json             Individuals
    organizations.json      Companies, agencies, unions, associations
    relationships.json      Documented connections between entities
    accountability-ledger.json  Derived: flattened joined view
  research/
    *.md                    Human-readable reports
```

## Schema definitions

### budget-lines.json

```json
{
  "fiscal_year": "2025-26",
  "total_revenue": 219900000000,
  "total_expenses": 232500000000,
  "deficit": 14600000000,
  "source_url": "https://...",
  "revenue": [
    {
      "id": "string",
      "name": "string",
      "amount": 0,
      "prior_year": null,
      "change_pct": null,
      "source_url": "https://..."
    }
  ],
  "expenses": [
    {
      "id": "string",
      "name": "string",
      "amount": 0,
      "prior_year": null,
      "change_pct": null,
      "notes": "string",
      "source_url": "https://...",
      "subcategories": [
        {
          "id": "string",
          "name": "string",
          "amount": 0,
          "source": "string",
          "contracts": ["contract-id-ref"]
        }
      ]
    }
  ]
}
```

### contracts.json

```json
{
  "fiscal_year": "2025-26",
  "contracts": [
    {
      "id": "string (unique, kebab-case)",
      "name": "string",
      "value": 0,
      "sector": "string (matches expense sector id)",
      "decision_type": "competitive-bid | sole-source | sole-bid | progressive-p3 | ministerial-override | legislative | alliance | not-yet-awarded",
      "decision_maker": "string (IO, Metrolinx, Minister, Cabinet, etc.)",
      "date_awarded": "YYYY-MM | null",
      "status": "awarded | under-construction | complete | terminated | planning | early-construction | development-phase | announced",
      "companies": ["org-id-ref"],
      "ag_flagged": false,
      "ag_finding": "string | null",
      "source_url": "https://...",
      "notes": "string | null"
    }
  ]
}
```

### policy-actions.json

```json
{
  "fiscal_year": "2025-26",
  "actions": [
    {
      "id": "string",
      "name": "string",
      "type": "legislation | mzo | order-in-council | regulation | program-creation | policy-change",
      "date": "YYYY-MM",
      "description": "string",
      "beneficiaries": ["org-id-ref"],
      "estimated_value": 0,
      "decision_maker": "string",
      "ag_flagged": false,
      "source_url": "https://..."
    }
  ]
}
```

### appointments.json

```json
{
  "fiscal_year": "2025-26",
  "appointments": [
    {
      "id": "string",
      "person": "person-id-ref",
      "position": "string",
      "organization": "org-id-ref",
      "date": "YYYY-MM",
      "appointed_by": "person-id-ref",
      "compensation": 0,
      "source_url": "https://..."
    }
  ]
}
```

### people.json

```json
{
  "people": [
    {
      "id": "string (unique, kebab-case)",
      "name": "string",
      "type": "politician | insider | lobbyist-insider | lobbyist | executive",
      "firm": "string | null",
      "integrity_violations": false,
      "clients": ["org-id-ref"],
      "timeline": [
        { "date": "YYYY or YYYY-MM", "event": "string" }
      ]
    }
  ]
}
```

**Type definitions:**
- `politician` — elected official or minister
- `insider` — unelected government staff (chief of staff, advisor, appointee) who has NOT become a lobbyist
- `lobbyist-insider` — former government insider who is now a registered lobbyist or runs a lobbying firm
- `lobbyist` — registered lobbyist with no prior government role
- `executive` — private sector executive (CEO, founder, board member)

### organizations.json

```json
{
  "organizations": [
    {
      "id": "string (unique, kebab-case)",
      "name": "string",
      "org_type": "company | crown-agency | union | association | non-profit | consortium",
      "contracts": ["contract-id-ref"],
      "total_gov_value": 0,
      "donations_pc": 0,
      "connection_strength": "none | weak | moderate | strong | very_strong",
      "lobbyists": ["person-id-ref"],
      "notes": "string | null"
    }
  ]
}
```

**`total_gov_value` rules:**
- For a sole contractor: the full contract value
- For a consortium entity (e.g., "Connect 6ix"): the full consortium contract value
- For a member of a consortium: `null` (their share is not publicly disclosed)
- For an equity/finance provider: `null` (they invest capital, they don't receive the construction value)

### relationships.json

```json
{
  "relationships": [
    {
      "id": "string (rel-001, rel-002, ...)",
      "from": "person-or-org-id",
      "to": "person-or-org-id",
      "type": "lobbies_for | donated | worked_for | appointed_by | hired | associated_with | received_contract",
      "start_date": "YYYY or YYYY-MM | null",
      "end_date": "YYYY or YYYY-MM | null",
      "amount": 0,
      "evidence": "string (factual description)",
      "source_url": "https://..."
    }
  ]
}
```

**Relationship type definitions:**
- `lobbies_for` — person/firm is a registered lobbyist for the organization
- `donated` — person/organization made political donations (specify to whom in `to` field)
- `worked_for` — person worked for the entity (government or private sector)
- `appointed_by` — person was appointed to a position by the entity
- `hired` — organization hired the person (revolving door from government)
- `associated_with` — documented personal relationship relevant to accountability (e.g., attending events)
- `received_contract` — organization received a contract from the government

## ID conventions

- All IDs are lowercase kebab-case: `ontario-shipyards`, `kory-teneycke`, `mississauga-hospital`
- Person IDs use full name: `first-last` (e.g., `mark-lawson`)
- Organization IDs use the common short name (e.g., `aecon` not `aecon-group-inc`)
- Contract IDs describe the project: `ontario-line-south`, `sdf-ontario-shipyards`
- Relationship IDs are sequential: `rel-001`, `rel-002`, etc.

## Validation rules

Run `scripts/import_budget.py validate {year}` to check:
- All JSON files are syntactically valid
- Revenue sources sum to total revenue
- Expense sectors sum to total expenses
- Subcategories sum to their parent sector
- All company IDs in contracts exist in organizations.json
- All person IDs in relationships exist in people.json
- All from/to IDs in relationships exist in people.json or organizations.json
- No orphan entities (people/organizations with no relationships or contracts)
- All entries have source_url (warning, not error)
