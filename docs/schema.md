# banking-kg — schema

Executable schema, with every property: [`../schema/banking_kg.cypher`](../schema/banking_kg.cypher).
Standards and code lists behind each field: [standards.md](standards.md).

## One graph, two layers, one bridge

| Layer | What it is | Real or synthetic | Built by |
|---|---|---|---|
| **Market** | Washington DC's 2023 lending market, from four public regulatory filings nobody joins up | **Real**, public, keyless | `etl/market.py` |
| **Bank** | One bank's own customers: households, accounts, loans, cards, where money goes, who pays them | **Synthetic**: a fictional bank, *Banking-KG Bank* | `etl/bank.py` |
| **Bridge** | The bank as a lender inside the market, and its mortgages in the market's product taxonomy | the bank node is synthetic | `etl/bridge.py` |

Every bank-layer node carries `synthetic: true`. Nothing in the market layer does. A query can always
tell which side of the line an answer came from:

```cypher
MATCH (n) RETURN coalesce(n.synthetic, false) AS synthetic, count(n)
```

## The picture

In words: on the market side, an `Application` is filed with a `Lender`; if originated it becomes a `Loan`,
which may be `SOLD_TO` a `Purchaser`. Applications sit in a `Tract`, which sits in a `County` and an `MSA`.
Lenders register as a `LegalEntity` and file quarterly `Filing`s; SBA loans link a `Business` to the lender
that made them. On the bank side, a `Customer` belongs to a `Household`, owns `Account`s of a `Product`,
borrows `CustomerLoan`s secured by `Collateral`, and sends money to or is paid by a `Counterparty`. The two
sides meet in two places: every bank `Product` is `OFFERED_BY` the bank's `Lender` node, and the bank's
mortgages are `CLASSIFIED_AS` the same `LoanProduct` that market applications are filed under.

```text
 MARKET (public)                                                        BANK (synthetic)

 (Purchaser)<-SOLD_TO-(Loan)-ORIGINATED_BY->(Lender)<-OFFERED_BY-(Product)<-OF_PRODUCT-(Account)<-OWNS-(Customer)-MEMBER_OF->(Household)*
                        ^                 / |   \                                 | |  \        |  \
               ORIGINATED_AS     FILED_WITH |    REGISTERED_AS            HAS_LOAN | |   SENDS_TO* | OWES        IN_AUDIENCE
                        |           /       |     \                               v |   PAID_BY*  v   \              v
 (DenialReason)<-DENIED_FOR-(Application)  FILED   (LegalEntity)        (CustomerLoan) | SPENDS_AT* (Counterparty)* (Audience)
                        |        \          v                             |   \     v
                  IN_TRACT    FOR_PRODUCT (Filing)          CLASSIFIED_AS |  SECURED_BY  (MerchantCategory)*
                        v            v                                    |       v
 (MSA)<-IN_MSA-(County)<-IN_COUNTY-(Tract)  (LoanProduct)<---------------+  (Collateral)   + Card, CreditLine,
                                                                                            BusinessUnit
 (Lender)<-MADE_BY-(SBALoan)<-BORROWED-(Business)-IN_INDUSTRY->(Industry)
 (DevelopmentCompany)<-MADE_BY-'   '-UNDER_FRANCHISE->(Franchise)   (Business)-LOCATED_AT->(Address)

 * marks a derived part: built from the source, not a source row (derived: true, with a `basis`)
```

## Market layer — 17 node types (real)

| Node | One per | Source | Key facts |
|---|---|---|---|
| **Lender** | HMDA filer, or SBA lender with no HMDA filing | HMDA filers, GLEIF, FDIC BankFind | `cert` (FDIC certificate) is matched by **legal name**, unique matches only (`etl/identity.py`). `lender_type`: Bank · Credit union · Non-bank lender · Bank (no active FDIC charter) |
| **LegalEntity** | LEI | GLEIF | jurisdiction, legal form, status |
| **Application** | HMDA row | HMDA LAR | **every** row; `action` is HMDA `action_taken` |
| **Loan** | origination | HMDA LAR | **only** `action_taken = 1`. An Application always exists; a Loan only where one was made. Conflating them inflates every total ~2× |
| **LoanProduct** | product | HMDA `derived_loan_product_type` | e.g. `Conventional:First Lien` |
| **Tract → County → MSA** | census geography | HMDA tract fields | tract income % of MSA, minority %, owner-occupied units |
| **DenialReason**, **Purchaser** | HMDA code | HMDA code lists | Purchaser is a *category* ("Fannie Mae", "Commercial bank…"), not an institution |
| **SBALoan** | SBA 7(a) / 504 loan | SBA FOIA | approval, guarantee, status incl. *Charged off* |
| **Business** | SBA borrower | SBA FOIA | sole proprietors: generic name, no street address |
| **Address**, **Industry** (NAICS), **Franchise**, **DevelopmentCompany** (504 CDC) | | SBA FOIA | |
| **Filing** | lender × quarter | FDIC financials (Call Report figures) | 2022Q4–2023Q4, **$ thousands** |

16 relationship types: `REGISTERED_AS FILED_WITH FOR_PRODUCT IN_TRACT IN_COUNTY IN_MSA DENIED_FOR ORIGINATED_AS
ORIGINATED_BY SOLD_TO LOCATED_AT IN_INDUSTRY BORROWED UNDER_FRANCHISE MADE_BY FILED`. A `Loan` with no
`SOLD_TO` was kept on the balance sheet.

### The join this layer exists for

In words: a HMDA application carries the lender's LEI; GLEIF turns the LEI into a legal name; the legal name
is matched to an FDIC certificate; the certificate links the lender to its Call Report filings and to the SBA
loans it made.

```text
HMDA Application ──lei──▶ Lender ──LEI──▶ GLEIF legal name ──name match──▶ FDIC cert ◀──BankFDICNumber── SBA loan
                                                                              │
                                                                              └──▶ Call Report Filing (quarterly)
```

No filing carries this chain. The usual LEI→RSSD route (HMDA panel, FFIEC NIC) is not reachable, so the
certificate comes from a normalised legal-name match: ties broken by HQ state then city, anything still
ambiguous gets **no** certificate — a wrong one is worse than none.

## Bank layer — 12 node types (synthetic)

| Node | One per | From the request table | Notes |
|---|---|---|---|
| **Customer** | customer | `customers` | + roll-ups: last address change, deceased date, logins in 90 days, latest credit score, receptiveness. **No email, phone or street address** |
| **Household** (derived) | address | derived | individuals sharing `address_line1` + `postal_code`. A joint account between people at different addresses is **not** a household |
| **Account** | account | `accounts` | + latest ledger balance |
| **Product** | product | `products` | 32 products: checking, savings, CDs, mortgages, HELOC, auto, cards, lines |
| **CustomerLoan** | loan | `loans` | the bank's own loan record — **not** a HMDA `Loan` |
| **Collateral** | collateral | `loan_collateral` | lien position on `SECURED_BY` |
| **CreditLine**, **Card** | | `credit_lines`, `debit_cards`, `credit_cards` | |
| **Counterparty** (derived) | name | derived | COMPETITOR and EMPLOYER parsed from transaction descriptions; LENDER from credit-bureau tradelines. **All fictional** |
| **MerchantCategory** | MCC | `transactions.mcc_code` | ISO 18245 descriptions |
| **BusinessUnit** | branch | `business_unit` | **isolated**: the request names a join column it does not request |
| **Audience** | use case × as-of date | `etl/audiences.py` | campaign lists, see [use-cases.md](use-cases.md) |

15 relationship types: `MEMBER_OF OWNS OF_PRODUCT SENDS_TO RECEIVES_FROM PAID_BY SPENDS_AT HAS_LOAN BORROWS
SECURED_BY HAS_CREDIT_LINE HAS_CARD HOLDS_CARD OWES IN_AUDIENCE`. Derived means built from the source, not a source row.

## Bridge — 1 node, 2 relationship types

| | Meaning |
|---|---|
| `(:Lender {id: 'BANKING-KG', name: 'Banking-KG Bank', synthetic: true})` | the bank as one more lender in the market |
| `(:Product)-[:OFFERED_BY]->(:Lender)` | every bank product belongs to that lender |
| `(:CustomerLoan)-[:CLASSIFIED_AS {basis}]->(:LoanProduct)` | first-lien mortgages and HELOCs, in HMDA's product taxonomy. The request has no FHA/VA field, so all are *Conventional*; the lien comes from `loan_collateral.lien_position` |

**Deliberately not joined.** The bank's competitors are fictional and are never matched to a real
lender (synthetic money must not be attributed to a real institution). Customers are not placed in census
tracts: the market layer is DC and the customers live in VA, MD and NC — extending the market layer to
those states (spec D4) is what would make that join honest.

## What the request cannot support (so the graph does not pretend to)

| Gap | Effect |
|---|---|
| No `loan_borrowers` table | `BORROWS` is the primary borrower only; co-borrowers and guarantors are invisible |
| No do-not-contact flag | "one household member opted out" cannot be shown; suppression stays with the email vendor |
| No ACH originator / routing number | competitors and employers come from description text |
| No campaign responses | use case 6 uses a proxy (recent product openers) |
| `business_unit` cannot be joined | no branch-level filtering of audiences |
| `debit_cards` has no customer key | debit cards link to the account, not the cardholder |
| HMDA has no loan performance | the market layer shows decisions, never repayment |
| HMDA purchaser is a category | "is the buyer a lender here too?" (spec Q3) cannot be answered |

## Counts (built 2026-10-07)

See [`../DATASET_CARD.md`](../DATASET_CARD.md) for the per-label table. Market 31,128 nodes / 83,640
relationships; bank 44,044 nodes / 152,795 relationships, plus 6 audiences / 3,762 memberships; bridge 1 node /
1,025 relationships. Total 75,179 nodes / 241,222 relationships.
