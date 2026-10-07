# Demo — 45-minute walkthrough

**A bank and its market in one graph.** The video opens on the real DC lending market, turns to one
bank's own customers (synthetic), and closes where the two meet. It is recorded in Samyama Insight with the
demo kit in `samyama-graph-demo-ops/demo/scripts`; copy the four question files below into a
`bankingkg/` question set there.

| File | Read by | What |
|---|---|---|
| [`queries.cypher`](queries.cypher) | `demo_queries.py`, `benchmarks/run.py` | 18 Query Console questions, three acts |
| [`vectors.md`](vectors.md) | `demo_vector_search.py` | 9 searches, with the expected nearest neighbours |
| [`nlq.md`](nlq.md) | `demo_nlq.py` | 10 natural-language questions + the tenant NLQ system prompt |
| [`algorithms.md`](algorithms.md) | `demo_algorithms.py` | 5 algorithm steps with measured results |

Every expected answer below was measured on engine 1.7.1 (tenant `bankingkg2`, 75,179 nodes) on 2026-10-07.

## The story in one line

> *Every bank reports its lending to two regulators and keeps its customers in a third system. None of
> them join up. Here they are in one graph — the market you report into, the customers you serve, and the
> line between them.*

## Running order (45:00)

| # | Segment | Time | What is on screen | Say |
|---|---|--:|---|---|
| 01 | **Intro** | 3:00 | Home page → Schema Explorer: 29 node types, 33 relationship types, 75,179 nodes | Two layers. The market is real public data; the bank is synthetic and every one of its nodes says so (`synthetic: true`) |
| 01b | **How to read the graph** | 1:30 | Schema slides: market labels, bank labels, the bridge | `Loan` is a HMDA origination; `Application` is every decision; `CustomerLoan` is our own book |
| 02a | **Act 1 · The market** (Q1–Q7) | 10:00 | Query Console, graph view | Provenance (Q1), two filings and two regulators (Q2), who keeps what they write (Q3), tract exposure (Q4), what an examiner sees first (Q5), one lender both books (Q6), the address cluster (Q7) |
| 02b | **Act 2 · Our bank** (Q8–Q14) | 10:00 | Query Console | A family (Q8), a family starts to leave (Q9), estates (Q10), the next generation (Q11), money leaving to a competitor (Q12), bring your mortgage home (Q13), HELOC behind our first mortgage (Q14) |
| 02c | **Act 3 · Across the line** (Q15–Q18) | 5:00 | Query Console | Our bank as a lender in the market (Q15), the same product in two worlds (Q16), who we compete with for the same borrower (Q17), a real lender's whole book (Q18) |
| 03 | **Vector Search** | 5:00 | 9 searches | Lenders whose book resembles ours; products, competitors, employers, audiences by meaning |
| 04 | **Natural Language** | 5:00 | 10 questions, Cypher generated and run | Market, bank and audience questions in plain English |
| 05 | **Graph Algorithms** | 4:00 | PageRank, WCC, BFS, Dijkstra, triangle count | The bridge makes two graphs one: one component of 75,147 nodes |
| 06 | **Close** | 1:30 | Recap slide | What is real, what is synthetic, what a real bank's data would change |

Act 1 is the strongest evidence (everything traces to a government filing), so it comes first — decision
D2: reconciliation first, then competitive intelligence. Act 2 is the bank's daily work. Act 3 is the reason
for a graph.

## Lines to keep honest on camera

- "The market layer is real; every figure traces to HMDA, GLEIF, the FDIC or the SBA."
- "Banking-KG Bank is fictional. Its customers were generated, and the patterns in them were planted so we
  can prove the graph finds them — 40 of 40 heirs, 40 of 40 next-generation customers."
- "The bank's competitors are fictional too. We never match them to a real lender."
- "HMDA shows decisions, not repayment. The Call Report is an aggregate. That difference in grain is what
  makes the reconciliation work."

## How to rebuild

```bash
# 1. engine + graph (this repo)
python -m etl.loader --url http://localhost:8081 --graph bankingkg      # or import ../data/banking-kg/banking-kg.sgsnap
python -m etl.embed  --url http://localhost:8081 --graph bankingkg      # vector search (Ollama all-minilm)
# 2. NLQ: set the tenant's nlq_config to the system prompt in nlq.md (LLM through the local chat proxy)
# 3. record (from samyama-graph-demo-ops/demo/scripts, question set bankingkg/)
export GRAPH=bankingkg ENGINE_URL=http://localhost:8081
for s in demo_intro demo_queries demo_vector_search demo_nlq demo_algorithms; do caffeinate -i -s python3 -u $s.py; done
```

Outputs (git-ignored, in `samyama-graph-demo-ops/demo/scripts/videos/exports/`): `bankingkg_45min.mp4`
with soft subtitles, a burned-in copy and the `.srt`.
