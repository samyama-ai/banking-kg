# Data

**Data never enters this repo.** Everything lives in the workspace's unversioned data folder,
`../data/banking-kg/` (`.gitignore` also blocks `*.csv` and `*.sgsnap`). The folder holds the market source
files written by `etl.fetch`, the bank's request tables under `bank_v1/`, and the audiences and snapshot the
loader writes:

```text
../data/banking-kg/
  hmda_dc_2023.csv  filers_dc_2023.json  gleif_dc_2023.json      market layer, written by etl.fetch
  fdic_active_institutions.json  fdic_financials_2022q4_2023q4.json
  sba_7a_fy2020_present.csv  sba_504_fy2010_present.csv
  bank_v1/                                                         bank layer: the 26 request tables
    bronze/<table>.csv  validation_report_v1.json  _answer_key/planted_patterns.csv
  audiences/UC*.csv  audience_summary.json                         written by etl.loader
  banking-kg.sgsnap                                                written by etl.loader --export
```

## Market layer — real, public, keyless

| Source | Endpoint | What it gives |
|---|---|---|
| HMDA LAR | `ffiec.cfpb.gov/v2/data-browser-api/view/csv?years=2023&states=DC` | 17,474 applications, 99 columns |
| HMDA filers | `…/view/filers?years=2023&states=DC` | 478 LEIs with names |
| GLEIF | `api.gleif.org/api/v1/lei-records` | legal name, HQ, legal form, status |
| FDIC BankFind | `banks.data.fdic.gov/api/institutions` | active institutions, for the name match |
| FDIC financials | `banks.data.fdic.gov/api/financials` | Call Report figures, 2022Q4–2023Q4 |
| SBA 7(a) & 504 FOIA | links read off `data.sba.gov/dataset/7a-504-foia` on every run | DC loans; the published URLs go stale |

```bash
python -m etl.fetch --data ../data/banking-kg --state DC --year 2023     # ~5 min, ~250 MB
```

Re-run the five commands in [spec §13](spec.md#13--verification-log) before trusting any figure. Last
re-run 2026-10-06: all matched (see the README).

## Bank layer — synthetic

**All of it is synthetic.** The bank (*Banking-KG Bank*) and its competitors are fictional. Every key starts
`PATTERN-`, every `source_system` is `PATTERN_ONLY_GENERATOR`, emails are `@example.com` and phones use the
fictional 555-01xx range. Use it to build and demonstrate queries, **never as evidence of how large an
effect is**: the shapes were written by hand, not learned.

The tables follow a 26-table customer data request (344 columns): customers, accounts, account owners,
products, transactions, daily balances, loans, collateral, credit lines, cards, credit bureau and
tradelines, digital sessions, CRM, change events, business units and more. Size: **5,000 customers,
3,757,369 rows, 532 MB**. Its own validator passes (`validation_report_v1.json`: 0 schema, key or code
problems; 14 of 14 cross-table checks — balances roll forward exactly from posted transactions, owner
counts, rates, fees, HELOC balances, no protected attribute). `etl.loader` refuses to load it otherwise.

It was generated from a fixed seed (customers seed 42, marketing patterns seed 7) with Samyama's
core-banking synthetic generator; `bank_v1` is a link to that output in the workspace data folder.

### Planted patterns (answer key)

`bank_v1/_answer_key/planted_patterns.csv` is not bank data: it lists which customers were given each
pattern, so the use cases can be checked.

| Pattern | Count | Checked by |
|---|--:|---|
| ESTATE_BENEFICIARY, ESTATE_JOINT | 20 + 20 | UC3 must find all living heirs |
| NEXT_GEN (about two-thirds then move to a city) | 60 | UC4 must find every planted customer ≤ 40 and active |
| FRIENDS_JOINT (different surname and address) | 50 | must **not** become one household |
| BUSINESS_PARTNER | 30 | reserved for a later use case |

### Defects found in the request — reported, not silently fixed

1. `loans.extract_dt` and `loans.source_system` are each listed twice (346 rows → 344 distinct columns).
2. `loans` has both `orig_credit_score` and `original_credit_score`.
3. `loans."product name"` contains a space (read exactly as requested).
4. `business_unit` "joins to `customers.branch`", which the request does not ask for.
5. `transfers.frequency` allows only MONTHLY, WEEKLY, ONE_TIME — bi-weekly transfers exist.
6. `loans.rate_type` allows only FIXED, ARM — HELOCs are VARIABLE.
7. Debit and credit cards use different status vocabularies (`HOT_LOST_STOLEN` vs `HOT/LOST`).
8. Code tables are promised with the data but the request has no entity for them
   (shipped as `_supplementary_reference_codes.csv`).

## Privacy

| Layer | Rule |
|---|---|
| Market | public data. SBA borrowers filed as INDIVIDUAL keep no name or street address, although the FOIA file carries them |
| Bank | synthetic, and still treated as if real: email, phone and street address are never loaded; audience exports carry `customer_id` only |
| Both | protected attributes: HMDA's public derived fields stay on `Application`; nothing is derived for bank customers. Estate (UC3) and age-based (UC4) selection need compliance review before any real campaign |
