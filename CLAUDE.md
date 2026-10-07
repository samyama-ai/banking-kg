# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**banking-kg**: one Samyama graph in two layers joined by a bridge.
- **Market layer** (`etl/market.py`): real, public data for Washington DC 2023, from HMDA, GLEIF, FDIC
  (BankFind and Call Report financials) and SBA 7(a)/504.
- **Bank layer** (`etl/bank.py`): synthetic customers of a fictional bank, *Banking-KG Bank*, built from a
  26-table customer data request.
- **Bridge** (`etl/bridge.py`): places the bank in the market.

The built graph has 75,179 nodes and 241,222 relationships. Read `README.md`, `docs/schema.md` and spec
§0 (`docs/spec.md`) first.

The repo is private (`LICENSE`). **Never write a client's or prospect's name into it.** The bank is
always "Banking-KG Bank", and the bank layer's source is "the customer data request". This rule also covers
the paths, modules and folder names the bank data came from.

The project uses Python ≥ 3.12 and only the standard library; pytest, pytest-cov, ruff and fastmcp are optional extras.

## Commands

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest                                    # offline, hand-built fixtures; no engine or data
.venv/bin/python -m pytest tests/test_bridge.py::test_loan_product          # one test (one module per source module)
.venv/bin/python -m pytest --cov=etl --cov=benchmarks --cov=mcp_server     # coverage (kept at ~99%)
.venv/bin/ruff check . && .venv/bin/ruff format --check .  # strict rules incl. bandit (S) and docstrings (D1)
BANKING_KG_LIVE=1 .venv/bin/python -m pytest                # + live check against ../data/banking-kg/audiences

python -m etl.fetch  --data ../data/banking-kg --state DC --year 2023            # market sources, ~5 min
python -m etl.loader --url http://localhost:8081 --graph <tenant> [--layers market|bank|market,bank] [--export PATH]
python -m etl.embed  --url http://localhost:8081 --graph <tenant>               # Ollama all-minilm on :11434
python -m etl.verify --data-dir ../data/banking-kg/bank_v1 --audiences ../data/banking-kg/audiences
python -m benchmarks.run --url http://localhost:8081 --graph <tenant>            # rewrites benchmarks/results.md
```

**Configuration.** Every URL, port, timeout, batch size, quota and source endpoint is in `etl/config.py`;
CLI flags default to it and environment variables (`BANKING_KG_URL`, `BANKING_KG_GRAPH`, `BANKING_KG_DATA`,
`OLLAMA_URL`, …; table in README) override it. Don't add literals elsewhere — add a named constant. All HTTP
goes through `helpers.open_url`, which refuses non-http(s) schemes; Cypher identifiers go through
`helpers.ident`, values through `helpers.lit`. Every CLI `main()` returns 0 / 1 (refused or mismatch) /
2 (unreachable) and prints a one-line reason to stderr.

To check a change without an engine, build the graph in memory:
`from etl.loader import build; g, as_of = build(Path('../data/banking-kg'), Path('../data/banking-kg/bank_v1'), {'market','bank'})`,
then compare `g.counts()`.

**Engine.** `:8081` is the local Docker container `sg-bankmodelrisk` (`samyama:1.7.1-internal-licensed`). It
holds these tenants:

| Tenant | What it holds |
|---|---|
| `bankingkg` | the market-only v1 graph, which the first video recorded |
| `bankingkg2` | the full two-layer graph |
| `bankmodelrisk` | another project |

The loader refuses a non-empty tenant, so load into a new tenant id. **Do not delete tenants you did not
create.** If `:8080` is used, it may be the remote engine through the SSH tunnel.

## Data

Data lives in `../data/banking-kg/`, never in the repo. `.gitignore` blocks `*.csv`, `*.sgsnap` and
`data/*` except `data/SNAPSHOT.md`.

- `bank_v1` is a symlink to the synthetic request tables.
- `audiences/` and `banking-kg.sgsnap` are written by the loader.
- `etl.loader` refuses the bank data unless `bank_v1/validation_report_v1.json` says `ok`.

## Architecture

`loader.build()` builds the full graph in memory before anything is sent:

1. `market.build()`, then `bank.build()`, with every bank node tagged `synthetic: true`.
2. `bridge.build()`.
3. All layers are merged into one `helpers.Graph`, where `nodes[label][id] = props` and
   `edges[rel] = [(from_label, from_id, to_label, to_id, props)]`.

It then loads the graph:

1. Apply `schema/banking_kg.cypher`, one constraint per label.
2. Load nodes in batches, grouped by key set so no null property is written.
3. Load edges with `MATCH … WHERE a.id = … CREATE`.
4. Read every per-label and per-type count back and exit non-zero on any difference.
5. Run `audiences.run()`.

Cypher values are inlined with `helpers.lit()` because the engine does not take parameters.

### Rules that must not drift

- **`Application` vs `Loan` vs `CustomerLoan`.**
  - Every HMDA row is an `Application`.
  - Only `action_taken = 1` also becomes a `Loan`.
  - `CustomerLoan` is the bank's own record. It meets HMDA only through
    `(:CustomerLoan)-[:CLASSIFIED_AS]->(:LoanProduct)`.
- **Join layers only where it is honest.** The bridge makes exactly two joins: the bank as a `Lender`
  (`id 'BANKING-KG'`), and mortgage/HELOC products. Bank `Counterparty` names are fictional: never match
  them to a real `Lender`. A test enforces this.
- **Identity** (`etl/identity.py`): LEI → GLEIF legal name → FDIC cert, by normalized-name match.
  - Only unique matches are accepted. Ties are broken by HQ state, then city.
  - If it is still ambiguous, no cert is assigned.
- **Privacy.**
  - SBA sole proprietors get no name or street.
  - Bank customers never get email, phone or street address.
- **Stable ids.** `Business` ids are a sha1 of name, street and zip, not `hash()`. Address and industry edges
  are deduplicated per (business, target) pair.
- **Vector indexes do not backfill.** `etl/embed.py` creates the indexes, writes the vectors, then calls
  `vector-index/rebuild`. Keep the rebuild last.
- **Document new labels and relationships.** A test fails if a label or relationship created in
  `market.py`, `bank.py`, `bridge.py` or `audiences.py` is missing from `schema/banking_kg.cypher`.

### Audiences

Bank use cases UC1 and UC3–UC7 live in `etl/audiences.py`.
- UC2 is applied to every audience: whole households are held out as the control group, and one
  `household_primary` is kept per household.
- `etl/verify.py` recomputes every audience from the CSVs without the graph, and must match member for member.
- The planted answer key is in `bank_v1/_answer_key/`.

## Demo and docs

`demo/` holds the 45-minute running order (`README.md`) and the question files the recorder in
`../samyama-graph-demo-ops/demo/scripts` reads:
- `queries.cypher`: 18 questions in three acts. Each block is `// Q<n> · …`, then `// walk=…`, then the
  Cypher, ending at a blank line. Return node and relationship variables.
- `vectors.md`, `nlq.md` (includes the tenant's NLQ system prompt) and `algorithms.md`.

`benchmarks/run.py` parses `queries.cypher`.

Docs:
- `docs/standards.md`: which standard governs which field. MISMO is primary and FIBO is the semantic layer;
  both are settled.
- `docs/use-cases.md`: per-question status.
- `docs/issues.md`: the status table.

## Things that are easy to get wrong

- **Units.**
  - HMDA and SBA amounts are in dollars.
  - FDIC `*_k` fields are in **$ thousands**.
  - Dates are ISO strings; FDIC `report_date` is `YYYYMMDD`, and `period` looks like `2023Q4`.
- **The engine has no `date()` function.** The demo's 60- and 90-day windows are fixed dates relative to the
  bank's as-of date, 2026-08-31.
- **Avoid Cartesian `MATCH` chains in demo questions.** A combined "whole picture" query produced 7,200 rows
  and took 9 s. Use `WITH … LIMIT` or split the question.
- **Conventions** (`docs/issues.md`): one issue → one branch → one PR, named `<type>/<ISSUE-ID>/<kebab-desc>`,
  with PRs of about 400 insertions at most.
