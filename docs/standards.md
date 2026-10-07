# Standards, taxonomies and identifiers

banking-kg aligns to published standards rather than authoring a model from scratch. This page says which
standard governs which node or field, and how far the alignment has actually been checked. The wider
landscape (~14 ontologies, 30+ taxonomies, 12 identifier systems) is in [spec §6](spec.md#6--taxonomy-index).

## Settled decisions (spec §0, §5 — change only with discussion)

- **MISMO is primary for loan structure**, because it is what the real data is shaped by. **FIBO is the
  semantic layer above it.** CREFC IRP is named but out of scope. A claim of conformance to all three
  would not survive review: they overlap and disagree.
- **`Loan` ≠ `Application`.** HMDA records applications; only `action_taken = 1` became a loan.
- **The public / synthetic boundary** (spec §10). The market layer is strictly public. The bank layer is
  synthetic at the institution level too: a fictional bank, fictional competitors, `synthetic: true` on
  every node, and never joined to a real lender by name.

## Ontologies and formal models

| Standard | Governs in banking-kg | Alignment | Checked |
|---|---|---|---|
| **FIBO** `LOAN/RealEstateLoans/HomeMortgageDisclosureActCoveredMortgages` | `Application.action` ↔ `HMDA-Disposition` (8 subtypes); `Loan` ↔ `HMDA-CoveredLoanContract`; `Lender` ↔ `FormalOrganization`; `LegalEntity` ↔ `LegalPerson` | class-level | **8 of 8** dispositions map one-to-one on 17,474 real rows. The other 58 coded fields: **not yet** (issue 4) |
| **MISMO** (+ ULDD, URLA) | `Loan` / `CustomerLoan` structure: amount, rate, term, lien, LTV, occupancy, purpose | field names and code values follow HMDA's MISMO-derived enumerations | spot-checked |
| **Call Report / MDRM** (FFIEC 031/041/051) | `Filing` fields: `ASSET`, `DEP`, `LNLSNET`, `LNRE`, `LNRERES`, `LNCI`, `LNCON`, `LNATRES`, `NTLNLS` (FDIC's names for Call Report items) | one field per item, $ thousands | values read from FDIC's API |
| **Census geography** | `Tract` (11-digit FIPS) → `County` (5-digit) → `MSA` (MSA/MD code) | hierarchy as published | from HMDA's own tract fields |

## Code lists (taxonomies)

| Code list | Used for | Where |
|---|---|---|
| HMDA `action_taken` (8) | `Application.action` | `etl/market.py` `ACTION` |
| HMDA `loan_type`, `loan_purpose`, `lien_status`, `occupancy_type` | `Application` / `Loan` | `LOAN_TYPE`, `PURPOSE`, `LIEN`, `OCCUPANCY` |
| HMDA `purchaser_type` (10) | `Purchaser` | `PURCHASER` |
| HMDA `denial_reason-1..4` (9) | `DenialReason` | `DENIAL` |
| HMDA `derived_loan_product_type` (6) | `LoanProduct` — **also the bridge taxonomy** for the bank's mortgages | |
| **NAICS 2017/2022** | `Industry` (6-digit), `sector` (2-digit) | SBA `NaicsCode` |
| SBA loan status | `SBALoan.status` | `SBA_STATUS` |
| FDIC / NCUA institution class | `Lender.lender_type` | `etl/identity.py` |
| **ISO 18245** merchant category codes | `MerchantCategory` | `etl/reference.py` |
| Bank request code lists (relationship code P/J/B/…, account type, product type, close reason) | bank layer | as delivered |

## Identifiers

| Identifier | Standard | Node | Role |
|---|---|---|---|
| **LEI** | ISO 17442, GLEIF | `Lender.lei`, `LegalEntity.id` | joins HMDA to GLEIF |
| **FDIC certificate** | FDIC | `Lender.cert`, `Filing.cert` | joins GLEIF name → Call Report → SBA `BankFDICNumber` |
| NCUA charter | NCUA | `Lender` id `NCUA-<n>` | SBA credit-union lenders |
| **Census FIPS** | ANSI/INCITS 31 | `Tract`, `County` | geography |
| NAICS code | NAICS | `Industry.id` | industry |
| MCC | ISO 18245 | `MerchantCategory.mcc_code` | spend category |
| Bank keys | the request (`source_*_key`) | bank layer `id` | `PATTERN-*` in the synthetic data |

Not used yet, named for the next scope: ULI (HMDA loan id, not in the public file), FFIEC RSSD (route
blocked, see README), NMLS ID, EIN, DUNS, MERS MIN.

## Conventions every node follows

| Convention | Rule |
|---|---|
| ids | unique per label; source keys where one exists, otherwise a stable derived key (`APP-<row>`, `BIZ-<sha1>`) |
| `synthetic` | `true` on every bank-layer node and the bank's `Lender`; absent on public data |
| `derived` + `basis` | on anything built that is not a source row (households, counterparties, flow totals) |
| dates | ISO 8601 `YYYY-MM-DD` strings; FDIC `report_date` is `YYYYMMDD` |
| money | dollars, except FDIC `*_k` fields in **$ thousands** and HMDA `income_k` in thousands |
| PII | no email, phone or street address for bank customers; SBA sole proprietors keep no name or street |
| protected attributes | HMDA's derived race / ethnicity / sex / age are public fields and kept on `Application`; the bank request carries none and none is derived |

## Publishing layer (if the graph is ever exposed as linked data)

PROV-O for lineage, DCAT for the catalogue, SKOS for the code lists, ORG for entity hierarchies — named in
spec §6, not implemented.
