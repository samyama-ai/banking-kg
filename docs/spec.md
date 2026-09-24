# Lending Ledger Graph — Specification

**Draft 1 · 23 September 2026 · handed over for build**

Retail and corporate lending as one graph, built from four public regulatory
filings that nobody joins up.

---

## 0 · How to read this

This spec separates what is **settled** from what is **expected to change**. If
you are picking this up from someone else, that distinction is the most
important thing on the page.

**Settled — changing these breaks everything downstream**

- The ontology in §5, particularly what `Loan` and `Application` mean
- The four sources in §3 and the join keys in §4
- The standards decision in §5: MISMO primary, FIBO as the semantic layer
- The public/synthetic boundary in §10

**Proposed — change freely, no conversation needed**

- The entire question catalogue in §8
- Geographic scope and year
- Which questions appear in the video

**Yours to decide** — §11. The analysis is written up; the call is yours.

Every figure marked *measured* was read from a live source on 22–23 September
2026. §13 says how, so it can be re-run. **Do that before trusting any of it.**

---

## 1 · The question

> **Asked by a risk officer, an examiner, or a competitor**
>
> This lender reported $400M of mortgage originations to one regulator and $50M
> of real-estate loan growth to another. Where did the difference go — and which
> lenders in this market keep what they write?

It is answerable only by joining two independent regulatory filings by the same
institution, through an identity chain neither filing carries. Every figure in
the answer comes from a government source; nothing is modelled or inferred.

The same shape extends to the corporate book: SBA approvals per lender against
the movement in their reported commercial and industrial loans.

---

## 2 · Scope

**In**

- Retail lending — mortgage, refinance, home improvement, HELOC, open-end lines, at loan level
- Corporate lending — SBA 7(a) and 504, at loan level, with industry and franchise detail
- Lender identity — charter, legal entity, parent relationships
- Lender balance sheet — quarterly loan composition and loss allowance

**Out, and why**

- **Deposits, transactions, customer behaviour** — no public source carries them
  at loan-book grain, and inventing them would weaken the claim the graph makes
- **Loan performance over time** — HMDA records the decision, not what happened next
- **The whole commercial book** — SBA covers government-guaranteed lending only

This is a *lending book* graph, not a customer graph. It is deliberately distinct
from `bank-model-risk-kg`, which models model governance and regulatory lineage
rather than the loans themselves.

---

## 3 · Sources

| Layer | Grain | Source | Key | Verified |
|---|---|---|---|---|
| Retail mortgage | loan / application | HMDA, CFPB data-browser API | `lei` | 17,474 records, 99 columns, one state-year, no key required |
| Corporate lending | loan | SBA 7(a) & 504 FOIA | `BankFDICNumber` | back to FY1991, quarterly refresh |
| Lender identity | institution | FDIC BankFind + GLEIF | `CERT`, `LEI` | 595 VA institutions; a real LEI resolved to a named entity |
| Balance sheet | institution / quarter | FDIC financials (Call Report) | `CERT` | 25,158 VA rows to 1984; `LNRE` `LNCI` `LNCONOTH` `LNATRES` |

> **Operational note.** SBA's published download URLs are stale — the working
> links must be read off the dataset page rather than from documentation or
> search results. Any loader that hard-codes them will break on the next
> quarterly refresh.

---

## 4 · The join

```
HMDA loan ──lei──▶ GLEIF ──legal entity──▶ FDIC cert ◀──BankFDICNumber── SBA loan
                                               │
                                               └──▶ Call Report filings (quarterly)
```

**Verified.** A real LEI taken from the HMDA download resolved through GLEIF to
**CROSSCOUNTRY MORTGAGE, LLC** — jurisdiction US-DE, status ACTIVE. The chain
holds on live data, not on documentation.

One lender, both books, plus its own balance sheet. That path is the product.

---

## 5 · Ontology

We align to published standards rather than authoring a model from scratch. The
modelling has been done by the bodies whose job it is.

> **The finding this section rests on.** FIBO publishes
> `LOAN/RealEstateLoans/HomeMortgageDisclosureActCoveredMortgages.rdf` — a formal
> ontology for the exact dataset in §3. Its `HMDA-Disposition` class has eight
> subtypes. HMDA's `action_taken` column has eight codes. **All eight map
> one-to-one**, checked against 17,474 real records.

| Class | Worthless without | Aligned to |
|---|---|---|
| `Lender` | cert, name | FDIC / FIBO `FormalOrganization` |
| `LegalEntity` | lei | GLEIF / FIBO `LegalPerson` |
| `Loan` | amount, rate, term | FIBO `HMDA-CoveredLoanContract`, MISMO |
| `Application` | disposition | FIBO `HMDA-Disposition` |
| `Business` | naics | NAICS / FIBO |
| `Property` | tract, value | MISMO, FIBO `ConstructionType` |
| `Geography` | fips, tract | Census |
| `Filing` | period, schedule | Call Report / MDRM |
| `Position` | as-of date, amount | RC-C categories |

**`Loan` vs `Application` — the distinction that must not drift.** HMDA records
*applications*, of which only `action_taken = 1` became loans. An `Application`
always exists; a `Loan` exists only where one was originated. Conflating them
inflates every total by roughly 2×.

> **Standards conflict — settled, do not reopen without discussion.** MISMO, FIBO
> and CREFC IRP overlap and do not agree. **MISMO is primary for loan structure**,
> because it is what the real data is shaped by. **FIBO is the semantic layer
> above it.** CREFC is named but out of scope for v1. A spec claiming conformance
> to all three will not survive review.

> **Known gap.** The FIBO mapping is spot-checked on disposition only. The other
> 58 coded fields are unvalidated — roughly a day's work, and worth doing before
> anyone builds on it.

---

## 6 · Taxonomy index

**~14 ontologies and formal models · 30+ taxonomies · 12 identifier systems.**
HMDA alone carries **59 coded fields** across its 99 columns.

| Family | Governs | Scale | v1 |
|---|---|---|---|
| **FIBO** | financial semantics, incl. an HMDA module | LOAN + 11 modules | yes |
| **MISMO** + ULDD, UCD, URLA, UAD, iLAD | mortgage lifecycle | 6 datasets | yes |
| **Call Report** XBRL + MDRM | lender-level reporting | FFIEC 031/041/051 | yes |
| **HMDA enumerations** | loan type, purpose, lien, denial reason | 59 fields | yes |
| **NAICS** | corporate industry | ~1,000 codes | yes |
| Census geography | tract → county → CBSA | hierarchical | yes |
| FDIC / NCUA class | charter and institution type | small | yes |
| CREFC IRP v8.4 | commercial real estate | Master Coding Matrix | named |
| FR Y-14Q H.1 | wholesale corporate loans | schedule | named |
| Basel asset classes, CECL staging | risk weighting, provisioning | — | named |
| Metro 2, FICO bands | consumer credit reporting | — | out |
| ISO 20022, BIAN, FpML, ACORD | payments, architecture, derivatives, insurance | — | out |

**Identifiers the graph joins on:** `LEI` · `ULI` · `FDIC CERT` · `FFIEC RSSD` ·
`NMLS ID` · `EIN` · `DUNS` · `FIGI` · `CUSIP/ISIN` · `MERS MIN` · agency loan
numbers · LEI Level-2 parent relationships

**Publishing layer**, if the graph is ever exposed as linked data: PROV-O
(lineage) · DCAT (catalogue) · SKOS (the taxonomies themselves) · ORG (entity
hierarchies).

---

## 7 · Size

| scope | records | nodes | edges |
|---|---:|---:|---:|
| **DC 2023 — measured** | 17,474 | **26,307** | **87,833** |
| One state, 5 years | 87,370 | ~132,000 | ~439,000 |
| Virginia 2023 | 262,110 | ~395,000 | ~1.3M |
| DC + VA + MD 2023 | 436,850 | ~658,000 | ~2.2M |
| **National 2023** | 11,500,000 | **~11.7M** | **~52.5M** |

National figures use CFPB's own published totals — 11.5M LAR records from 5,113
reporting institutions in 2023 — not extrapolation. 2022 was 14.3M records.

Plus SBA corporate at roughly 400,000 national loans FY2020–present, and FDIC
financials at 25,158 quarterly rows for Virginia alone.

**Recommended v1: one state-year.** At 26,307 nodes it is the same size as
`marketing-attribution-kg` (20,102 / 78,752), which loads in 40 s, answers 24
questions in 1.6 s, and exports to an 865 KB snapshot that imports in 0.21 s.
Every performance characteristic is therefore already known rather than a risk.
The schema does not change when scaling — adding states is more rows, not a
redesign.

> **Unverified.** Whether the engine holds 11.7M nodes and 52.5M edges has not
> been tested. Everything measured here was at 20K.
> `samyama-cloud/raw/architecture/billion-edge-cost-analysis.md` may answer it;
> read before committing to national scale.

---

## 8 · Question catalogue

*Proposed — expected to change. Each carries why it is hard, so a replacement
preserves what it demonstrates.*

**Status:** ◦ proposed · ◐ Cypher written · ● runs and visualises
**All 25 are currently ◦.**

### Provenance and reconciliation

| # | Question | Why it is hard | Shows | St |
|---|---|---|---|---|
| 1 | Where did this number come from? | Five hops nobody wrote down | traversal | ◦ |
| 2 | We reported $400M originated and $50M growth — where did the rest go? | Two filings, two regulators, no shared key | traversal | ◦ |
| 3 | Who bought our loans, and are they lenders here too? | The buyer re-enters the graph as an originator | path | ◦ |
| 4 | Which loans have no traceable purchaser at all? | Absence, not presence | traversal | ◦ |

### Concentration and blast radius

| # | Question | Why it is hard | Shows | St |
|---|---|---|---|---|
| 5 | If this tract turns, which lenders are exposed and by how much? | Fan-out with dollar weighting | traversal | ◦ |
| 6 | Which single industry touches the most lenders? | NAICS → loans → lender, aggregated | traversal | ◦ |
| 7 | Which lenders share the most borrowers with this one? | Two lenders meeting at a borrower set | pattern | ◦ |
| 8 | Which counties have retail lending but no corporate lending? | An edge type that is absent | traversal | ◦ |
| 9 | If this source system failed, which figures lose provenance? | Depth-unbounded cascade | traversal | ◦ |

### Fair lending and disparity

*Framed for a bank audience as what an examiner would see before they arrive.*

| # | Question | Why it is hard | Shows | St |
|---|---|---|---|---|
| 10 | Which lenders deny at different rates in *adjacent* tracts? | **Needs a derived adjacency edge** | traversal | ◦ |
| 11 | Same income and LTV — who charges the widest spread? | Parallel paths, same endpoints | aggregation | ◦ |
| 12 | Which tracts are served by only one lender? | Degree-1 detection | traversal | ◦ |
| 13 | Do denial reasons cluster by geography or by applicant? | Two clusterings compared | aggregation | ◦ |

### Graph algorithms

| # | Question | Why it is hard | Shows | St |
|---|---|---|---|---|
| 14 | Which lenders are most central in this market? | Centrality over a shared-tract network | PageRank | ◦ |
| 15 | Which are central *despite* small balance sheets? | Rank against assets — the mismatch is the finding | PageRank | ◦ |
| 16 | Which purchasers sit behind the most originators? | Secondary-market hubs | PageRank | ◦ |
| 17 | Which lender is central in corporate but invisible in retail? | Cross-book centrality | PageRank | ◦ |

### Vector search

| # | Question | Why it is hard | Shows | St |
|---|---|---|---|---|
| 18 | Find lenders whose book resembles this one | Similarity over a composition vector | vector | ◦ |
| 19 | Which looks like us but carries a higher loss allowance? | Near neighbours, divergent outcome | vector | ◦ |
| 20 | Tracts with a similar profile but different outcomes | **Needs adjacency** | vector | ◦ |

### Corporate and pattern detection

| # | Question | Why it is hard | Shows | St |
|---|---|---|---|---|
| 21 | Which addresses carry several businesses drawing separate guaranteed loans? | Invisible row by row | pattern | ◦ |
| 22 | Which borrowers took loans from several lenders in one year? | Loan stacking; borrower is not a key | pattern | ◦ |
| 23 | Which franchise brands concentrate in a single lender? | Brand → lender concentration | aggregation | ◦ |
| 24 | Which lenders charge off out of line with peers in the same industry? | Peer group defined by the graph | aggregation | ◦ |

### Closer

| # | Question | Why it is hard | Shows | St |
|---|---|---|---|---|
| 25 | Show me this lender's entire book | Every node type and edge type in one frame | all | ◦ |

> **Two dependencies.** Questions 10 and 20 need a **tract-adjacency edge** no
> source provides — derivable from census shapefiles, but real work. Questions
> 18–20 need the **vector index created before loading**; built afterwards it
> returns zero rows silently, with no error.

---

## 9 · Capability matrix

| Capability | Carried by | Runs on 1.1.0 |
|---|---|---|
| Traversal · pattern matching | Q1–9, 21–22 | yes |
| Aggregation | Q11, 13, 23–24 | yes |
| PageRank | Q14–17 | yes |
| Vector search | Q18–20 | yes, with caveat |
| Community detection | — | **no — WCC absent** |
| Natural-language query | — | **no — `/api/nlq` 404** |

> **Engine constraints — measured, not assumed.** `/api/nlq` returns **404**;
> genuinely absent. `algo.pageRank` is the **only** algorithm that exists —
> `algo.degree`, `algo.bfs`, `algo.list` all answer "Unknown algorithm", so
> community detection must run client-side or be dropped. Vector search works,
> but **the index does not backfill**: nodes written before it exists are
> invisible to it forever.

---

## 10 · Public and synthetic

**The core demo needs no synthetic data.** Four real layers and a reconciliation
question carry the whole argument, and every figure traces to a government
filing. That is a stronger position than a generated dataset, because a reader
can check us.

Synthetic becomes an optional fifth layer only for borrower-level behaviour no
public source carries. If added, the disclosure is the one
`marketing-attribution-kg` already makes: the data is generated, the findings are
planted, and what is demonstrated is that the structure finds them without being
told where to look.

> **Carried from Qorro's research.** Generated data is not automatically
> anonymous. Regulators test singling-out, linkability and inference; fidelity
> and re-identification risk rise together. Equally, a dataset can be identifiably
> *one bank* from its regional concentration and product mix even with every
> customer anonymised. Any synthetic layer must therefore be synthetic at the
> institution level too — a further argument for keeping the real layer strictly
> public.

---

## 11 · Decisions

### Decided

**D1 — Audience: a bank.** *Decided 23 Sep 2026.*

The demo is built in a banking context and will be shown to people we meet in
the sector. Later iterations adapt the same graph as those connections appear,
so the 45-minute video is a reusable asset rather than a one-off pitch.

*Consequences:* the catalogue leans lender-side — what a bank can see about
itself and its market, not what a borrower experiences. Regulatory vocabulary is
assumed rather than explained: HMDA, Call Report, LTV and charge-off need no
gloss.

### Open — now yours

**D2 — How much audit flavour is useful to a bank?**

Reconciliation (Q2) is the strongest thing the data supports, and it positions
the graph as an examiner's tool. A bank audience generally finds competitive
intelligence more compelling — Q15 and Q17 land better than Q10 and Q13. D1
narrows this from "audit or growth" to "how much audit," but the call is still
open. Whichever way it goes, the catalogue's emphasis follows.

**D4 — Geographic scope for v1.**

One state-year is 26,307 nodes with every performance characteristic already
known. Three states reaches ~2.2M edges, which is past what a spreadsheet holds
and therefore makes the "why a graph" argument rather than asserting it.
National is 11.7M nodes and untested on this engine.

---

## 12 · Limitations

- **HMDA is decisions, not performance** — approved, denied or withdrawn, never repaid
- **SBA is guaranteed lending only**, not the whole commercial book
- **Call Report figures are aggregates** — the reconciliation works *because*
  grains differ, but a reader must be told, or the comparison looks naive
- **FIBO alignment is spot-checked** on one field of 59
- **One engine build** — every capability claim measured on
  `samyama-graph:1.1.0`. Two builds reporting the same version have answered the
  same query differently elsewhere in this ecosystem
- **No question has been run yet.** All 25 are proposed. The gap between proposed
  and verified is the main risk in this spec

---

## 13 · Verification log

Read from live sources on 22–23 September 2026. **Re-run these before building.**

| What | Result |
|---|---|
| HMDA data-browser API, DC 2023 | 17,474 records · 99 columns · 6.7 MB · no key |
| Coded fields in that sample | 59 of 99 |
| `action_taken` codes present | 8 of 8, mapping 1:1 to FIBO's 8 `HMDA-Disposition` classes |
| GLEIF lookup of a real LEI from that pull | resolved to a named, active US-DE entity |
| FDIC BankFind, Virginia | 595 institutions |
| FDIC financials, Virginia | 25,158 quarterly rows, back to 1984 |
| SBA 7(a) FY2020–present | header read; documented URLs stale, recovered from dataset page |
| FIBO HMDA module | downloaded from `edmcouncil/fibo`, classes enumerated |
| National totals | CFPB published figures, not extrapolated |

```bash
# 1 — HMDA
curl -sSL "https://ffiec.cfpb.gov/v2/data-browser-api/view/csv?years=2023&states=DC" -o dc.csv

# 2 — FDIC institutions
curl -sSL "https://banks.data.fdic.gov/api/institutions?filters=STALP:VA&fields=NAME,CERT,ASSET&limit=2&format=json"

# 3 — FDIC financials (Call Report figures)
curl -sSL "https://banks.data.fdic.gov/api/financials?filters=STALP:VA&fields=CERT,REPDTE,ASSET,LNRE,LNCI&limit=2&format=json"

# 4 — GLEIF, using any lei from dc.csv
curl -sSL -H "Accept: application/vnd.api+json" "https://api.gleif.org/api/v1/lei-records/<LEI>"

# 5 — FIBO's HMDA ontology module
curl -sSL "https://raw.githubusercontent.com/edmcouncil/fibo/master/LOAN/RealEstateLoans/HomeMortgageDisclosureActCoveredMortgages.rdf"
```

SBA's links are not listed here deliberately — they go stale. Read them off
<https://data.sba.gov/dataset/7a-504-foia> each time.
