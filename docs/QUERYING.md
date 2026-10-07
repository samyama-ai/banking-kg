# Querying banking-kg

Four ways in, all against a loaded tenant (`bankingkg` below, engine HTTP on :8081).

## 1 · HTTP API

```bash
q() { curl -s localhost:8081/api/query -H 'Content-Type: application/json' \
        -d "$(python3 -c 'import json,sys; print(json.dumps({"graph":"bankingkg","query":sys.argv[1]}))' "$1")"; }

q "MATCH (n) RETURN labels(n), count(n)"
q "MATCH (l:Lender {name: 'Citibank, National Association'})<-[:ORIGINATED_BY]-(n:Loan) WHERE NOT (n)-[:SOLD_TO]->() RETURN count(n)"
```

The response carries `columns`, `records` (rows) and, when the query returns nodes or relationships,
`nodes` and `edges` for drawing. `GET /api/status` gives the engine version; `GET /api/tenants` the tenants.

## 2 · Samyama Insight (the visual console)

Point Insight at the engine and pick the `bankingkg` tenant. Query Console, Schema Explorer, Vector Search,
Natural Language and Graph Algorithms all work on it; the 45-minute demo ([../demo/README.md](../demo/README.md))
is recorded there. Return node and relationship variables (`RETURN a, r, b`) and the Auto view draws a graph.

## 3 · Vector search and natural language

`python -m etl.embed` embeds lender book profiles, industries, products, competitors, merchant categories
and audiences, and sets the tenant's embed config. Searches and their expected answers:
[../demo/vectors.md](../demo/vectors.md).

Natural-language questions go to `/api/nlq` once the tenant has an `nlq_config` (an LLM provider and a
system prompt). The prompt — the schema in plain English plus the rules that bite — is
[../demo/nlq.md](../demo/nlq.md).

## 4 · MCP (read-only tools for an AI assistant)

```bash
pip install -e '.[mcp]'
BANKING_KG_URL=http://localhost:8081 BANKING_KG_GRAPH=bankingkg python -m mcp_server.server
```

Tools: `lender_book(name)`, `list_audiences()`, `audience_members(use_case, slice, limit)`,
`customer_connections(customer_id)`. None writes; none returns contact details.

## Rules that bite when writing Cypher here

- **One label per node.** `MATCH (n:Lender:Bank)` is unreliable on 1.7.1; filter on `lender_type`.
- **Literals only in property maps** — the engine does not take parameters; `etl.helpers.lit` quotes.
- **`Loan` ≠ `Application` ≠ `CustomerLoan`.** Count originations with `Loan`, decisions with
  `Application`, the bank's own book with `CustomerLoan`.
- **Kept vs sold** is the *absence* of `SOLD_TO`: `WHERE NOT (n)-[:SOLD_TO]->()`.
- **$ thousands** on every `Filing` field; dollars on `Loan.amount` and `SBALoan.gross_approval`.
- **Dates are strings** (`'2026-08-31'`), so `>=` orders them; FDIC `report_date` is `'20231231'` and
  `period` is `'2023Q4'`.
- **Synthetic or real?** `coalesce(n.synthetic, false)` tells you which layer an answer came from.
- **Return graph variables** (`RETURN l, r, n`) for a picture; aggregates for a table.
