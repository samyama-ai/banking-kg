# banking-kg

**A bank and its market in one graph.** Washington DC's 2023 lending market, built from four public
regulatory filings nobody joins up, and one bank's own customers — households, accounts, loans, where
their money goes — joined to it. **75,179 nodes · 241,222 relationships · 29 node types · 33 relationship
types**, on the [Samyama](https://git.samyama.ai/Samyama.ai) graph-vector engine.

> **Private / confidential** — Samyama.ai. See [`LICENSE`](LICENSE).
> The **market layer is real public data**. The **bank layer is synthetic**: *Banking-KG Bank* and its
> competitors are fictional, and every bank-layer node carries `synthetic: true`.

![banking-kg demo: reconciliation, concentration, fair lending, credit risk, retention, and the bank beside its market](demo/banking-kg.gif)

## Demo

A narrated terminal walkthrough of the questions a bank's risk, finance, compliance and marketing teams ask —
what is real, who keeps what they write (HMDA vs. Call Report), who dominates the core mortgage product, what
an examiner sees first in low-income tracts, where SBA loans fail, which customers are moving money to
competitors, and how the bank's own mortgages sit beside the market's:

```bash
pip install -e '.[demo]'                                         # rich, for the terminal output
BANKING_KG_GRAPH=bankingkg python -m demo.demo                   # run live against a loaded engine
asciinema rec --headless --window-size 110x34 -i 5 -c "python -m demo.demo" demo/banking-kg.cast   # re-record
agg --font-size 15 demo/banking-kg.cast demo/banking-kg.gif     # re-render the GIF
```

The 45-minute Samyama Insight walkthrough and its question set are in [`demo/README.md`](demo/README.md).

| Layer | Source | In the graph |
|---|---|---|
| **Market** · retail mortgage | HMDA LAR (CFPB data-browser API) | 17,474 `Application`, 8,616 `Loan` (only `action_taken = 1`), 201 `Tract`, buyers, denial reasons |
| **Market** · lender identity | GLEIF + FDIC BankFind | 538 `Lender`, 478 `LegalEntity`; LEI → FDIC certificate by legal name (179 banks) |
| **Market** · balance sheet | FDIC financials (Call Report figures) | 895 quarterly `Filing`, 2022Q4–2023Q4, $ thousands |
| **Market** · corporate lending | SBA 7(a) & 504 FOIA | 966 `SBALoan`, 858 `Business`, 807 `Address`, 221 `Industry`, 44 `Franchise` |
| **Bank** · customers (synthetic) | 26-table customer data request | 5,000 `Customer`, 2,677 `Household`, 11,525 `Account`, 1,807 `CustomerLoan`, 20,698 `Card`, 29 `Counterparty` |
| **Bank** · campaign audiences | computed in the graph | 6 `Audience` (use cases 1, 3–7; use case 2 applied to all) |
| **Bridge** | — | the bank as a market `Lender`; 993 of its mortgages and HELOCs classified in HMDA's product taxonomy |

Schema: [`docs/schema.md`](docs/schema.md) · Standards: [`docs/standards.md`](docs/standards.md) ·
Questions and use cases: [`docs/use-cases.md`](docs/use-cases.md) · Data: [`docs/data.md`](docs/data.md) ·
Querying: [`docs/QUERYING.md`](docs/QUERYING.md) · Spec: [`docs/spec.md`](docs/spec.md) ·
Demo: [`demo/README.md`](demo/README.md) · Benchmarks: [`benchmarks/results.md`](benchmarks/results.md) ·
Start here: [`GETTING_STARTED.md`](GETTING_STARTED.md)

## The questions it answers

**About the market (real):** *This lender reported $400M of mortgage originations to one regulator and $50M
of real-estate loan growth to another — where did the difference go, and which lenders in this market keep
what they write?* Answerable only by joining two regulatory filings through an identity chain neither
carries (HMDA LEI → GLEIF → FDIC certificate → Call Report, and → SBA).

**About the bank (synthetic):** *Which existing customers share a reason to be contacted?* — a household
member left, an estate is changing hands, the next generation is on the account, money is leaving to a
competitor. Computed from the connections between customers, not from each customer alone.

**Across the line:** *How does our book sit beside the market?* — our mortgages in the same product
taxonomy as every DC origination, our profile in the same vector space as every DC lender.

## Quick start

```bash
python3.12 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'
pytest                                                                  # 180 offline tests, no engine or data needed
ruff check . && ruff format --check .                                   # lint (incl. bandit security rules) and style

# engine: the local licensed 1.7.1 container (HTTP on :8081) — check the port first
lsof -nP -iTCP:8081 -sTCP:LISTEN

python -m etl.fetch  --data ../data/banking-kg --state DC --year 2023   # market sources, ~5 min, keyless
python -m etl.loader --url http://localhost:8081 --graph bankingkg      # both layers + audiences, ~5 min
python -m etl.embed  --url http://localhost:8081 --graph bankingkg      # vector search; needs Ollama + all-minilm
python -m etl.verify --data-dir ../data/banking-kg/bank_v1 --audiences ../data/banking-kg/audiences
python -m benchmarks.run --url http://localhost:8081 --graph bankingkg
```

**From the snapshot instead** (record: [`data/SNAPSHOT.md`](data/SNAPSHOT.md)):

```bash
curl -X POST localhost:8081/api/tenants -H 'Content-Type: application/json' -d '{"id":"bankingkg","name":"bankingkg"}'
curl -X POST localhost:8081/api/tenants/bankingkg/snapshot/import -F "file=@../data/banking-kg/banking-kg.sgsnap"
python -m etl.embed --url http://localhost:8081 --graph bankingkg       # embed config is not in the snapshot
```

## Configuration

Every setting lives in [`etl/config.py`](etl/config.py); nothing else hard-codes a URL, port, timeout, batch
size or quota. Command-line flags default to it, and these environment variables override it:

| Variable | Default | What it sets |
|---|---|---|
| `BANKING_KG_URL` | `http://localhost:8081` | engine HTTP API (http or https only) |
| `BANKING_KG_GRAPH` | `bankingkg` | tenant id |
| `BANKING_KG_DATA` | `../data/banking-kg` | data folder (outside the repo) |
| `BANKING_KG_STATE`, `BANKING_KG_YEAR` | `DC`, `2023` | market scope |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama as seen from this machine |
| `BANKING_KG_ENGINE_OLLAMA` | `http://host.docker.internal:11434` | Ollama as seen from the engine |
| `BANKING_KG_EMBED_MODEL` | `all-minilm` | embedding model |
| `BANKING_KG_LIVE` | unset | `1` runs the live test against a loaded engine |

Every command exits non-zero on failure (1: refused or a mismatch; 2: engine, Ollama or inputs unreachable)
with a one-line reason on stderr.

## Layout

| Folder | What |
|---|---|
| `schema/` | `banking_kg.cypher`: every node type and relationship, documented, plus one uniqueness constraint per label |
| `etl/` | `config.py` (every setting) · `fetch.py` (public sources) · `market.py` (market layer) · `identity.py` (LEI → FDIC cert) · `bank.py` (bank layer) · `bridge.py` · `loader.py` (load + check + audiences + snapshot) · `audiences.py` · `verify.py` (independent recalculation) · `embed.py` · `helpers.py` (graph, engine client, Cypher quoting) · `reference.py` |
| `tests/` | one test module per source module, on two hand-built miniatures where every answer is known, a fake engine and a local HTTP server; 99% line coverage; one live test |
| `benchmarks/` | query timings for every demo question and audience |
| `mcp_server/` | read-only MCP tools (`tools.py`, testable without an MCP runtime; `server.py` registers them): a lender's whole book, audiences, a customer's connections |
| `demo/` | the 45-minute walkthrough: segments, question set, vector and NLQ prompts |
| `docs/` | schema, standards, use cases, data, querying, spec, issues |
| `data/` | `SNAPSHOT.md` only — the data itself lives in `../data/banking-kg/`, never in the repo |

## What was verified

| Check | Result |
|---|---|
| HMDA DC 2023 | 17,474 records + header, 99 columns: matches the spec (re-run 2026-10-06) |
| GLEIF | all 478 DC filer LEIs resolved |
| LEI → FDIC certificate | by GLEIF legal name, unique matches only — the LEI → RSSD panel now returns Access Denied |
| Triangle count | 8,616 = exactly the number of loans: every loan closes application → loan → lender |
| Bank data | its own validator: 0 schema/key/code problems, 14 / 14 cross-table checks |
| Load | every per-label and per-type count read back from the engine equals what was built (the loader exits otherwise) |
| Audiences | each recomputed in plain Python from the CSVs, without the graph, and compared member-for-member (`etl.verify`) |

## Honest limits

- **The bank layer is synthetic.** Effect sizes are authored, not learned; never quote them as evidence.
- **The two layers meet only where they honestly can**: the bank as a lender, and its mortgages in HMDA's
  product taxonomy. Its customers live in VA, MD and NC; the market layer is DC only (spec D4).
- **HMDA is decisions, not performance**; **SBA is guaranteed lending only**; **Call Report figures are
  aggregates** — the reconciliation works *because* grains differ.
- HMDA purchaser is a category, so "is the buyer a lender here too?" (spec Q3) cannot be answered.
- Tract adjacency (spec Q10, Q20) is not built. FIBO alignment is checked on `action_taken` only.
- UC6 is a proxy and too broad as-is; UC7 reads competitor names from description text.
- Estate (UC3) and age-based (UC4) selection need compliance review before any real campaign.
