"""The MCP tools as plain functions over an engine client, so they can be tested without an MCP runtime.

Every tool is read-only, never returns contact details (the graph holds none), quotes every argument with
etl.helpers.lit, and caps how many rows it returns.
"""

from etl.helpers import lit

DEFAULT_LIMIT = 25
MAX_LIMIT = 500  # largest page a tool returns, whatever the caller asks for
GROUPS = ("CAMPAIGN", "CONTROL")  # IN_AUDIENCE.slice values
AUDIENCE_FIELDS = ["use_case", "name", "campaign", "customers", "households", "as_of"]
MEMBER_FIELDS = ["customer_id", "household_id", "reason"]


def bounded(limit) -> int:
    """limit as an int between 1 and MAX_LIMIT; ValueError when it is not a number."""
    return max(1, min(int(limit), MAX_LIMIT))


def lender_book(db, name: str) -> dict:
    """One market lender's whole book: identity, Call Report filings, HMDA originations by product and buyer, SBA loans by industry."""
    n = lit(name)
    return {
        "lender": db.q(f"MATCH (l:Lender) WHERE l.name = {n} RETURN l.id, l.lender_type, l.cert, l.hq_city, l.hq_state, l.assets_k, l.synthetic"),
        "filings": db.q(
            f"MATCH (l:Lender)-[:FILED]->(f:Filing) WHERE l.name = {n} "
            "RETURN f.period, f.assets_k, f.residential_re_loans_k, f.ci_loans_k ORDER BY f.period"
        ),
        "originations_by_product": db.q(
            "MATCH (l:Lender)<-[:ORIGINATED_BY]-(x:Loan)<-[:ORIGINATED_AS]-(:Application)"
            f"-[:FOR_PRODUCT]->(p:LoanProduct) WHERE l.name = {n} RETURN p.name, count(x), sum(x.amount)"
        ),
        "sold_to": db.q(f"MATCH (l:Lender)<-[:ORIGINATED_BY]-(x:Loan)-[:SOLD_TO]->(p:Purchaser) WHERE l.name = {n} RETURN p.name, count(x)"),
        "sba_by_industry": db.q(
            f"MATCH (l:Lender)<-[:MADE_BY]-(s:SBALoan)<-[:BORROWED]-(:Business)-[:IN_INDUSTRY]->(i:Industry) "
            f"WHERE l.name = {n} RETURN i.name, count(s), sum(s.gross_approval)"
        ),
    }


def list_audiences(db) -> list[dict]:
    """The bank's campaign audiences: use case, name, size and as-of date (synthetic data)."""
    rows = db.q("MATCH (a:Audience) RETURN a.use_case, a.name, a.campaign, a.customers, a.households, a.as_of ORDER BY a.use_case")
    return [dict(zip(AUDIENCE_FIELDS, r, strict=False)) for r in rows]


def audience_members(db, use_case: str, group: str = "CAMPAIGN", limit: int = DEFAULT_LIMIT) -> list[dict]:
    """Customers in one audience (e.g. use_case='UC3') and group (CAMPAIGN or CONTROL), with the plain-English reason."""
    if group not in GROUPS:
        raise ValueError(f"group must be one of {', '.join(GROUPS)}")
    rows = db.q(
        f"MATCH (c:Customer)-[m:IN_AUDIENCE]->(a:Audience) WHERE a.use_case = {lit(use_case)} AND m.slice = {lit(group)} "
        f"RETURN c.id, c.household_id, m.reason LIMIT {bounded(limit)}"
    )
    return [dict(zip(MEMBER_FIELDS, r, strict=False)) for r in rows]


def customer_connections(db, customer_id: str, limit: int = DEFAULT_LIMIT) -> dict:
    """Who and what a bank customer is connected to: household members, co-owners, competitors, employers, audiences."""
    cid, n = lit(customer_id), bounded(limit)
    return {
        "household": db.q(
            f"MATCH (c:Customer)-[:MEMBER_OF]->(:Household)<-[:MEMBER_OF]-(m:Customer) WHERE c.id = {cid} RETURN m.id, m.status LIMIT {n}"
        ),
        "co_owners": db.q(
            f"MATCH (c:Customer)-[:OWNS]->(a:Account)<-[o:OWNS]-(m:Customer) WHERE c.id = {cid} AND m.id <> c.id RETURN m.id, o.role, a.id LIMIT {n}"
        ),
        "counterparties": db.q(
            f"MATCH (c:Customer)-[:OWNS]->(:Account)-[r]->(k:Counterparty) WHERE c.id = {cid} RETURN type(r), k.name, k.kind LIMIT {n}"
        ),
        "audiences": db.q(f"MATCH (c:Customer)-[m:IN_AUDIENCE]->(a:Audience) WHERE c.id = {cid} RETURN a.use_case, m.slice, m.reason"),
    }
