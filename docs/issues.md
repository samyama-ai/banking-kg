# Issues to raise

Suggested order. The first two are decisions, not code — settle them before the
loader exists, because both change what gets loaded.

House convention: **one issue → one branch → one PR**, branch named
`<type>/<ISSUE-ID>/<kebab-desc>`, PRs capped at ~400 insertions.

## Status — 2026-10-07

| # | Issue | Status |
|---|---|---|
| 1 | D2 positioning | **done** — reconciliation first, then competitive intelligence (spec §11) |
| 2 | D4 scope | **done** — DC 2023 (spec §11) |
| 3 | Re-run the verification log | **done** 2026-10-06 — all matched; LEI→RSSD panel now Access Denied (README) |
| 4 | FIBO mapping, remaining 58 fields | open |
| 5 | Schema and loader | **done** — `schema/banking_kg.cypher`, `etl/loader.py`; counts read back from the engine |
| 6 | Vector index | **done** — `etl/embed.py` creates the indexes, writes vectors, then rebuilds (the rebuild is what makes earlier writes visible) |
| 7 | Tract adjacency | open — blocks spec Q10, Q20 |
| 8–11 | The 25 questions | **16 of 25 ●**; Q3 blocked; Q7, Q8, Q9, Q15, Q17, Q19 to write (`docs/use-cases.md`) |
| 12 | 45-minute demo | **ready to record** — `demo/README.md` (running order), question files in `demo/` |
| 13 | Snapshot release | **done** — `data/SNAPSHOT.md` |
| 14 | National scale test | open, gated on D4 |
| 15 | Synthetic bank layer (D5) | **done** — `etl/bank.py`, `etl/bridge.py`, audiences UC1, UC3–UC7, independent verify |
| 16 | Extend the market layer to VA, MD, NC | new — lets the bank's customers and collateral sit in real tracts |
| 17 | Government-program field for the bank's mortgages | new — so `CLASSIFIED_AS` can reach FHA / VA products, not only *Conventional* |
| 18 | Run the MCP server end to end | new — written, needs `pip install -e '.[mcp]'` and one client session |
| 19 | NLQ config on the tenant | new — set `nlq_config` from `demo/nlq.md` and check the 10 answers before recording |

The original issue text follows, unchanged, for the reasoning behind each.

---

## Decisions — do these first

### 1 · Decide how much audit flavour suits a bank audience (D2)

`decision` · blocks the catalogue's emphasis

Reconciliation is the strongest thing the data supports and positions the graph
as an examiner's tool; competitive intelligence lands better with a bank. See
spec §11. Outcome: a one-line decision recorded in §11 with its reasoning, and
the catalogue reordered to match.

### 2 · Decide geographic scope for v1 (D4)

`decision` · blocks the loader

One state-year is 26,307 nodes with known performance. Three states reaches
~2.2M edges and makes the "why a graph" case by itself. National is 11.7M nodes,
untested on this engine. See spec §7.

---

## Foundation — before any question is written

### 3 · Re-run the verification log

`chore` · half a day

Run all five commands in spec §13 and record what came back. SBA's URLs already
went stale once; the CFPB endpoint could move. If anything differs from what §13
states, fix the spec before building on it.

### 4 · Validate the FIBO mapping across the remaining 58 coded fields

`research` · ~1 day

§5 is spot-checked on `action_taken` only — eight codes, eight classes, 1:1.
The other 58 HMDA coded fields are unvalidated. Produce a mapping table and
record which fields FIBO does *not* cover, because those are the ones we model
ourselves.

### 5 · Schema and loader for the four sources

`feat` · the main build

Nodes and edges per spec §5. Watch the `Loan` vs `Application` distinction — only
`action_taken = 1` becomes a `Loan`. Refuse to load a graph whose per-label
counts do not sum to the total, and read every count back out of the engine
rather than trusting what the loader believes it wrote.

### 6 · Create the vector index before loading

`feat` · blocks Q18–20

The index **does not backfill**. Nodes written before it exists are invisible to
it forever and every query returns zero rows *with no error*, which reads exactly
like vector search being unsupported. The index creation must run before the
loader, not after.

### 7 · Build the tract-adjacency edge

`feat` · blocks Q10, Q20

No source provides it. Derivable from census shapefiles. If this turns out to be
more than a day, drop Q10 and Q20 rather than delaying the catalogue — they are
two of twenty-five.

---

## The catalogue — the main risk

### 8–11 · Write and verify the 25 questions

`feat` · split across four issues, roughly six questions each, to stay under the
PR cap

All 25 are currently **proposed**. Each needs Cypher that runs, returns what the
question claims, and visualises legibly. Record the status per question in §8
(◦ proposed → ◐ written → ● runs and visualises).

Suggested split, so each PR demonstrates one capability:

- **8** — Q1–4 and Q25, provenance and the closer
- **9** — Q5–9 and Q21–22, traversal and pattern detection
- **10** — Q10–13 and Q23–24, aggregation
- **11** — Q14–20, PageRank and vector

Two engine facts that will cost a day each if forgotten: `algo.pageRank` is the
**only** algorithm that exists, and `CALL … YIELD … RETURN` accepts no trailing
`LIMIT` or `ORDER BY` — sort client-side.

---

## Deliverable

### 12 · Record the 45-minute demo

`demo` · after the catalogue runs

Twelve to fifteen questions shown in depth; the catalogue carries the rest. At
roughly 1:45 per question, 25 does not fit — `marketing-attribution-kg` ships 24
questions and demos a subset, which is the pattern to follow.

### 13 · Snapshot release

`chore` · after the loader

Export a `.sgsnap` so the graph can be shown without a load. `etl/snapshot.py` in
`marketing-attribution-demo` is the template — it carries the measured
`/api/status` caveat and the multipart import detail. Commit the record with size
and sha256; the binary itself is a release asset, not source.

---

## Only if scope goes national

### 14 · Test the engine at 11.7M nodes / 52.5M edges

`research` · gate on D4

Everything measured so far was at 20K.
`samyama-cloud/raw/architecture/billion-edge-cost-analysis.md` may already answer
this. If the engine cannot hold it, the honest scope is a few states and the spec
should say so.
