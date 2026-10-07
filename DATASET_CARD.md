---
license: other
license_name: proprietary-samyama
pretty_name: banking-kg
tags:
  - knowledge-graph
  - samyama
  - property-graph
  - finance
  - banking
  - hmda
  - synthetic-data
language:
  - en
size_categories:
  - 10K<n<100K
---

# Dataset card for `banking-kg`

**A bank and its market in one graph: 75,179 nodes · 241,222 relationships · 29 node types · 33
relationship types.** Washington DC's 2023 lending market from four public regulatory filings, and one
fictional bank's 5,000 customers, joined where they honestly can be.

> Private / confidential (see `LICENSE`). Built 2026-10-07 on Samyama engine 1.7.1.

## Composition

| Layer | Real or synthetic | Nodes | Relationships |
|---|---|--:|--:|
| Market — DC 2023 (HMDA, GLEIF, FDIC, SBA) | **real, public** | 31,128 | 83,640 |
| Bank — *Banking-KG Bank*, 5,000 customers, as of 2026-08-31 | **synthetic** | 44,044 | 152,795 |
| Campaign audiences (computed) | synthetic | 6 | 3,762 |
| Bridge — the bank as a market lender; its mortgages in HMDA's product taxonomy | synthetic bank node | 1 | 1,025 |
| **Total** | | **75,179** | **241,222** |

Every synthetic node carries `synthetic: true`; no real node does.

### Node types (29)

Card (20,698), Application (17,474), Account (11,525), Loan (8,616), Customer (5,000), Household (2,677),
CustomerLoan (1,807), Collateral (1,517), SBALoan (966), Filing (895), Business (858), Address (807),
CreditLine (707), Lender (539), LegalEntity (478), Industry (221), Tract (201), Franchise (44),
MerchantCategory (35), Product (32), Counterparty (29), BusinessUnit (17), DenialReason (9), Purchaser (9),
Audience (6), LoanProduct (6), DevelopmentCompany (4), County (1), MSA (1)

### Relationship types (33)

SPENDS_AT (81,269), HAS_CARD (20,698), FILED_WITH (17,474), FOR_PRODUCT (17,474), IN_TRACT (17,346),
OWNS (14,670), OF_PRODUCT (11,525), ORIGINATED_AS (8,616), ORIGINATED_BY (8,616), OWES (5,777),
SOLD_TO (5,114), MEMBER_OF (4,300), IN_AUDIENCE (3,762), DENIED_FOR (3,718), HOLDS_CARD (3,603),
PAID_BY (2,803), SENDS_TO (2,178), BORROWS (1,807), HAS_LOAN (1,807), SECURED_BY (1,517),
CLASSIFIED_AS (993), BORROWED (966), MADE_BY (966), FILED (895), IN_INDUSTRY (866), LOCATED_AT (844),
HAS_CREDIT_LINE (707), REGISTERED_AS (478), IN_COUNTY (201), RECEIVES_FROM (134), UNDER_FRANCHISE (65),
OFFERED_BY (32), IN_MSA (1)

Full schema: `docs/schema.md`; executable: `schema/banking_kg.cypher`; standards: `docs/standards.md`.

## Sources and licences

| Source | Publisher | Terms |
|---|---|---|
| HMDA Loan/Application Register 2023 (DC) | CFPB / FFIEC | U.S. government public data |
| FDIC BankFind institutions and financials | FDIC | U.S. government public data |
| SBA 7(a) & 504 FOIA (FY2020+, FY2010+) | SBA | U.S. government public data |
| LEI records | GLEIF | CC0 1.0 |
| Bank layer: 26-table customer data request | Samyama synthetic generator (seeds 42 and 7) | synthetic; no real person or institution |

## Intended use

Demonstrating what a graph adds to a bank's own data and its regulatory filings: provenance and
reconciliation across regulators, market concentration and fair-lending views, campaign audiences built from
connections between customers, and the bank's book beside its market. Building and testing queries,
vector search, natural-language query and graph algorithms on the Samyama engine.

## Out of scope / do not use for

- **Any claim about effect size from the bank layer** — its patterns were authored and planted, not learned.
- Attributing anything in the bank layer to a real institution: the bank and its competitors are fictional
  and are never matched to a real lender.
- Credit decisions or fair-lending conclusions about named lenders: HMDA shows decisions, not performance,
  and the public file omits credit scores.

## Quality checks

- The loader exits unless every per-label and per-type count read back from the engine equals what was built.
- Market: HMDA 17,474 records / 99 columns re-verified against the live endpoint (2026-10-06); triangle
  count 8,616 = loans (every loan closes application → loan → lender).
- Bank: the generator's validator passes (0 schema/key/code problems, 14 / 14 cross-table checks); every
  audience matches an independent plain-Python recalculation member-for-member; planted answer key
  recovered 40 / 40 heirs, 40 / 40 next-generation customers, 50 / 50 friend pairs kept apart.

## Known limitations

LEI → FDIC certificate is a legal-name match (unique matches only). Tract adjacency is not built. HMDA
purchaser is a category, not an institution. The bank's customers (VA, MD, NC) are not in the market's
geography (DC). UC6 is a proxy; UC7 reads competitor names from description text. FIBO alignment is checked
on `action_taken` only.

## Refresh cadence

Market: HMDA is annual; SBA FOIA quarterly; FDIC financials quarterly — `etl.fetch` re-reads all of them,
including SBA's links from the dataset page. Bank: static, seeded; regenerate only on a new request version.

## Citation

See `CITATION.cff`.
