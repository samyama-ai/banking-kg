"""mcp_server.server: each registered tool delegates to mcp_server.tools (fastmcp is stubbed, so it need not be installed)."""

import importlib
import sys
import types

from tests.conftest import FakeEngine


def test_server_registers_every_tool(monkeypatch):
    registered = []

    class FastMCP:
        def __init__(self, name):
            self.name = name

        def tool(self):
            def register(fn):
                registered.append(fn.__name__)
                return fn

            return register

        def run(self):
            pass

    monkeypatch.setitem(sys.modules, "fastmcp", types.SimpleNamespace(FastMCP=FastMCP))
    sys.modules.pop("mcp_server.server", None)
    server = importlib.import_module("mcp_server.server")
    assert server.mcp.name == "banking-kg"
    assert registered == ["lender_book", "list_audiences", "audience_members", "customer_connections"]
    db = FakeEngine([("MATCH (a:Audience)", [["UC1", "n", "c", 1, 1, "d"]])])
    monkeypatch.setattr(server, "db", db)
    assert server.list_audiences()[0]["use_case"] == "UC1"
    assert server.audience_members("UC1") == [] and set(server.customer_connections("C1")) >= {"household"}
    assert set(server.lender_book("X")) >= {"lender"}
    sys.modules.pop("mcp_server.server", None)
