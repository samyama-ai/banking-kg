"""Read-only MCP server for banking-kg.

    pip install -e '.[mcp]'
    BANKING_KG_URL=http://localhost:8081 BANKING_KG_GRAPH=bankingkg python -m mcp_server.server

Tools never write to the graph and never return contact details (the graph holds none). Every argument is
quoted with etl.helpers.lit; limits are cast to int.
"""

import os

from fastmcp import FastMCP

from etl.helpers import Engine, lit

db = Engine(os.environ.get("BANKING_KG_URL", "http://localhost:8081"), os.environ.get("BANKING_KG_GRAPH", "bankingkg"))
mcp = FastMCP("banking-kg")


@mcp.tool()
def lender_book(name: str) -> dict:
    """One market lender's whole book: identity, Call Report filings, HMDA originations by product and buyer, SBA loans by industry."""
    n = lit(name)
    who = db.q(f"MATCH (l:Lender) WHERE l.name = {n} RETURN l.id, l.lender_type, l.cert, l.hq_city, l.hq_state, l.assets_k, l.synthetic")
    filings = db.q(f"MATCH (l:Lender)-[:FILED]->(f:Filing) WHERE l.name = {n} "
                   "RETURN f.period, f.assets_k, f.residential_re_loans_k, f.ci_loans_k ORDER BY f.period")
    loans = db.q(f"MATCH (l:Lender)<-[:ORIGINATED_BY]-(x:Loan)<-[:ORIGINATED_AS]-(:Application)-[:FOR_PRODUCT]->(p:LoanProduct) "
                 f"WHERE l.name = {n} RETURN p.name, count(x), sum(x.amount)")
    sold = db.q(f"MATCH (l:Lender)<-[:ORIGINATED_BY]-(x:Loan)-[:SOLD_TO]->(p:Purchaser) WHERE l.name = {n} RETURN p.name, count(x)")
    sba = db.q(f"MATCH (l:Lender)<-[:MADE_BY]-(s:SBALoan)<-[:BORROWED]-(:Business)-[:IN_INDUSTRY]->(i:Industry) "
               f"WHERE l.name = {n} RETURN i.name, count(s), sum(s.gross_approval)")
    return {"lender": who, "filings": filings, "originations_by_product": loans, "sold_to": sold, "sba_by_industry": sba}


@mcp.tool()
def list_audiences() -> list[dict]:
    """The bank's campaign audiences: use case, name, size and as-of date (synthetic data)."""
    rows = db.q("MATCH (a:Audience) RETURN a.use_case, a.name, a.campaign, a.customers, a.households, a.as_of ORDER BY a.use_case")
    return [dict(zip(["use_case", "name", "campaign", "customers", "households", "as_of"], r, strict=False)) for r in rows]


@mcp.tool()
def audience_members(use_case: str, slice: str = "CAMPAIGN", limit: int = 25) -> list[dict]:
    """Customers in one audience (e.g. use_case='UC3'), with the plain-English reason."""
    rows = db.q(f"MATCH (c:Customer)-[m:IN_AUDIENCE]->(a:Audience) WHERE a.use_case = {lit(use_case)} AND m.slice = {lit(slice)} "
                f"RETURN c.id, c.household_id, m.reason LIMIT {int(limit)}")
    return [dict(zip(["customer_id", "household_id", "reason"], r, strict=False)) for r in rows]


@mcp.tool()
def customer_connections(customer_id: str) -> dict:
    """Who and what a bank customer is connected to: household members, co-owners, competitors, employers, audiences."""
    cid = lit(customer_id)
    hh = db.q(f"MATCH (c:Customer)-[:MEMBER_OF]->(:Household)<-[:MEMBER_OF]-(m:Customer) WHERE c.id = {cid} RETURN m.id, m.status")
    co = db.q(f"MATCH (c:Customer)-[:OWNS]->(a:Account)<-[o:OWNS]-(m:Customer) WHERE c.id = {cid} AND m.id <> c.id "
              "RETURN m.id, o.role, a.id")
    cp = db.q(f"MATCH (c:Customer)-[:OWNS]->(:Account)-[r]->(k:Counterparty) WHERE c.id = {cid} RETURN type(r), k.name, k.kind")
    aud = db.q(f"MATCH (c:Customer)-[m:IN_AUDIENCE]->(a:Audience) WHERE c.id = {cid} RETURN a.use_case, m.slice, m.reason")
    return {"household": hh, "co_owners": co, "counterparties": cp, "audiences": aud}


if __name__ == "__main__":
    mcp.run()
