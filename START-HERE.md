# Start here

You are taking this over completely — the build **and** the open decisions. This
page gets you to the first commit. It should take about an hour.

## 1 · Read two things, not thirteen

[`docs/spec.md`](docs/spec.md) is long because it is a reference. On day one read
only:

- **§0** — what is settled, what you may change freely, what you now own
- **§1** — the question the whole graph exists to answer

Come back to the rest when an issue sends you there.

## 2 · Reproduce one measurement before you trust any of it

This matters more than reading. Every figure in the spec was read from a live
source, and §13 records how. Run at least the first one:

```bash
# HMDA — one state-year, no key, no registration
curl -sSL "https://ffiec.cfpb.gov/v2/data-browser-api/view/csv?years=2023&states=DC" -o dc.csv
wc -l dc.csv          # expect ~17,475 lines (17,474 records + header)
head -1 dc.csv | tr ',' '\n' | wc -l   # expect 99 columns
```

If that returns what §13 says it returns, the rest of the spec is probably sound.
If it does not, **stop and find out why before building anything** — the CFPB
could have changed the endpoint, and SBA's published URLs already went stale
once.

The other four commands are in §13. Running all of them costs ten minutes and
tells you whether you are inheriting something live or something rotted.

## 3 · The three facts that will save you a day each

**`Loan` and `Application` are different things.** HMDA records *applications*;
only `action_taken = 1` became a loan. Conflating them inflates every total by
roughly 2×. This is the definition most likely to drift — see §5.

**The vector index does not backfill.** Nodes written before the index exists are
invisible to it forever, and every query returns zero rows *with no error*. It
reads exactly like vector search being unsupported. Create the index, then load.

**`algo.pageRank` is the only algorithm that exists** on engine 1.1.0.
`algo.degree`, `algo.bfs`, `algo.list` all answer "Unknown algorithm", and
`/api/nlq` returns 404. Anything promising community detection or natural
language will fail at build time, not design time.

## 4 · What is actually decided

| | |
|---|---|
| **Settled** | the ontology, the four sources, the join keys, the standards choice, the public/synthetic boundary |
| **Yours to change freely** | all 25 questions, geographic scope, which questions reach the video |
| **Yours to decide** | D2 (positioning) and D4 (scope) in §11 — the analysis is written up, the call is yours |

D1 (audience) was decided on 23 Sep: **a bank**. The reasoning is recorded in §11
because Sandeep may ask, and a decision without its reason cannot be defended
six weeks later.

## 5 · Pick up the first issue

Issues are listed in [`docs/issues.md`](docs/issues.md) with a suggested order.
The first two are decisions, not code — worth settling before the loader exists,
because both change what gets loaded.

The largest body of work, and the main risk in this spec, is that **no question
has been run yet**. All 25 are proposed. Turning them into Cypher that runs and
visualises is where the time goes.

## 6 · What Sandeep will likely ask

Recorded here so you are not caught out, and because the answers are all in the
spec:

- **How many ontologies and taxonomies?** ~14 ontologies and formal models, 30+
  taxonomies, 12 identifier systems. §6 names each with what it governs. HMDA
  alone carries 59 coded fields.
- **How big is the graph?** One state-year is 26,307 nodes / 87,833 edges —
  measured. National is ~11.7M nodes / ~52.5M edges, from CFPB's own published
  totals. §7 has the scaling table.
- **Why a graph and not a database?** §1. The reconciliation question needs two
  regulatory filings joined through an identity chain neither filing carries.
- **Is the data real?** Yes, all four layers. §10 explains why no synthetic layer
  is needed for the core demo, and what would change if one were added.
