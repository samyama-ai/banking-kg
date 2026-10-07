"""Read-only MCP server for banking-kg: registers the tools in mcp_server/tools.py.

    pip install -e '.[mcp]'
    BANKING_KG_URL=http://localhost:8081 BANKING_KG_GRAPH=bankingkg python -m mcp_server.server

The engine URL and tenant come from etl/config.py (BANKING_KG_URL, BANKING_KG_GRAPH).
"""

from fastmcp import FastMCP

from etl import config
from etl.helpers import Engine
from mcp_server import tools

SERVER_NAME = "banking-kg"

db = Engine(config.ENGINE_URL, config.GRAPH)
mcp = FastMCP(SERVER_NAME)


@mcp.tool()
def lender_book(name: str) -> dict:
    """One market lender's whole book: identity, Call Report filings, HMDA originations by product and buyer, SBA loans by industry."""
    return tools.lender_book(db, name)


@mcp.tool()
def list_audiences() -> list[dict]:
    """The bank's campaign audiences: use case, name, size and as-of date (synthetic data)."""
    return tools.list_audiences(db)


@mcp.tool()
def audience_members(use_case: str, group: str = "CAMPAIGN", limit: int = tools.DEFAULT_LIMIT) -> list[dict]:
    """Customers in one audience (e.g. use_case='UC3') and group (CAMPAIGN or CONTROL), with the plain-English reason."""
    return tools.audience_members(db, use_case, group, limit)


@mcp.tool()
def customer_connections(customer_id: str, limit: int = tools.DEFAULT_LIMIT) -> dict:
    """Who and what a bank customer is connected to: household members, co-owners, competitors, employers, audiences."""
    return tools.customer_connections(db, customer_id, limit)


if __name__ == "__main__":
    mcp.run()
