# Start here

You are taking this over completely — the build **and** the open decisions. This page gets you from a
fresh clone to a loaded graph and your first question in about an hour.

## 0 · Prerequisites

| | |
|---|---|
| Python | **3.12+** (the ETL uses only the standard library) |
| Engine | a licensed Samyama engine **1.7.1**. Locally that is the Docker container on HTTP **:8081**. Check the port before writing to it: `lsof -nP -iTCP:8081 -sTCP:LISTEN`, then `curl -s localhost:8081/api/status` |
| Ollama | only for vector search: `ollama pull all-minilm` |
| Data | `../data/banking-kg/` in the workspace — never in the repo. `bank_v1/` must hold the bank's 26 request tables (see [docs/data.md](docs/data.md)) |

```bash
python3.12 -m venv .venv && source .venv/bin/activate && pip install -e '.[dev]'
pytest                    # 16 offline tests on hand-built miniatures; no engine, no data needed
```

## 1 · Read three things, not thirteen

- [`README.md`](README.md) — what the graph is, what was verified, honest limits
- [`docs/schema.md`](docs/schema.md) — the two layers and the bridge, on one page
- [`docs/spec.md`](docs/spec.md) **§0 and §1 only** — what is settled, and the question the market layer exists to answer

Come back to the rest of the spec when an issue sends you there.

## 2 · Reproduce one measurement before you trust any of it

This matters more than reading. Every market figure was read from a live source, and spec §13 records how:

```bash
curl -sSL "https://ffiec.cfpb.gov/v2/data-browser-api/view/csv?years=2023&states=DC" -o dc.csv
wc -l dc.csv                              # expect 17,475 lines (17,474 records + header)
head -1 dc.csv | tr ',' '\n' | wc -l      # expect 99 columns
```

If that differs, **stop and find out why before building anything** — the CFPB could have moved the
endpoint, and SBA's published URLs already went stale once.

## 3 · Build and load

```bash
python -m etl.fetch  --data ../data/banking-kg --state DC --year 2023   # ~5 min, keyless
python -m etl.loader --url http://localhost:8081 --graph bankingkg      # ~5 min: both layers, checked, + audiences
python -m etl.embed  --url http://localhost:8081 --graph bankingkg      # vector search
python -m etl.verify --data-dir ../data/banking-kg/bank_v1 --audiences ../data/banking-kg/audiences
```

The loader refuses a non-empty tenant, and exits non-zero unless every per-label and per-type count read
back out of the engine equals what was built. `--layers market` loads the public layer alone.

## 4 · Ask your first question

```bash
curl -s localhost:8081/api/query -H 'Content-Type: application/json' -d '{"graph":"bankingkg",
  "query":"MATCH (n) RETURN coalesce(n.synthetic, false) AS synthetic, count(n)"}'
```

More in [`docs/QUERYING.md`](docs/QUERYING.md); the demo's 15 questions are in
[`demo/queries.cypher`](demo/queries.cypher).

## 5 · The facts that will save you a day each

**`Loan` and `Application` are different things.** HMDA records *applications*; only `action_taken = 1`
became a loan. Conflating them inflates every total by roughly 2×.

**`Loan` and `CustomerLoan` are different things too.** `Loan` is a public HMDA origination in DC;
`CustomerLoan` is the synthetic bank's own loan record. They meet only through `LoanProduct`.

**Never cross the synthetic line by name.** The bank's competitors are fictional. Do not match them to
real lenders, and do not quote a bank-layer number as evidence of anything: the shapes were authored.

**The vector index does not backfill.** Nodes written before an index exists are invisible to it, and
every query returns zero rows *with no error*. `etl.embed` creates the indexes after loading and rebuilds
them; keep that order.

**Check the engine version, not the docs.** The spec was written against 1.1.0 (PageRank only, no
`/api/nlq`). The graph is built and measured on **1.7.1**, which has NLQ, BFS, WCC and triangle count.
`/api/status` is the truth.

**Money units differ.** HMDA and SBA in dollars; FDIC `*_k` fields in **$ thousands**.

## 6 · What is decided

| | |
|---|---|
| **Settled** | the ontology, the four public sources, the join keys, MISMO primary / FIBO semantic, the public/synthetic boundary |
| **Decided** | D1 audience: a bank. D2: reconciliation first, then competitive intelligence. D4: DC 2023. D5: a synthetic bank layer, kept separate and labelled (spec §11) |
| **Yours to change freely** | the questions, the scope, which questions reach the video |

## 7 · Pick up the next issue

[`docs/issues.md`](docs/issues.md) lists what is done and what is next, in order. Conventions: **one issue
→ one branch → one PR**, branch named `<type>/<ISSUE-ID>/<kebab-desc>`, PRs capped at ~400 insertions.

## 8 · What you will likely be asked

- **Is the data real?** The market layer is, all four sources. The bank layer is synthetic, by design and
  labelled on every node — a real bank's customers cannot be public.
- **How big is it?** 75,179 nodes / 241,222 relationships. National HMDA would be ~11.7M nodes / ~52.5M
  edges (spec §7), untested on this engine.
- **Why a graph and not a database?** The market question needs two regulatory filings joined through an
  identity chain neither carries; the bank's use cases need the connections *between* customers.
- **How many standards?** ~14 ontologies, 30+ taxonomies, 12 identifier systems; [docs/standards.md](docs/standards.md)
  says which governs what.
