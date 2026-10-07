"""etl.helpers: identifiers, literals, the in-memory graph, batched loading and the engine client."""

import json
import urllib.error

import pytest

from etl import config, helpers
from etl.helpers import Engine, EngineError, Graph, create_edges, create_nodes, csv_safe, ident, lit, props, statements
from tests.conftest import FakeEngine, FakeResponse, http_error, json_body


# ---------------------------------------------------------------- identifiers and literals
@pytest.mark.parametrize("name", ["Lender", "SOLD_TO", "_x", "a1"])
def test_ident_accepts_plain_identifiers(name):
    assert ident(name) == name


@pytest.mark.parametrize("name", ["", "1abc", "a b", "a-b", "x) DETACH DELETE (n", "Lender`", None, 5])
def test_ident_rejects_anything_that_could_change_a_statement(name):
    with pytest.raises(ValueError):
        ident(name)


def test_lit_escapes_quotes_and_backslashes():
    assert lit("O'Neil") == "'O\\'Neil'"
    assert lit("a\\b") == "'a\\\\b'"
    assert lit("x' OR 1=1 //") == "'x\\' OR 1=1 //'"
    assert lit("café · …") == "'café · …'"


def test_lit_keeps_numbers_and_booleans_unquoted():
    assert lit(True) == "true" and lit(False) == "false"
    assert lit(3) == "3" and lit(2.5) == "2.5"


def test_props_drops_empty_values_and_checks_keys():
    assert props({"a": 1, "b": None, "c": ""}) == "{a: 1}"
    assert props({"name": "x"}) == "{name: 'x'}"
    with pytest.raises(ValueError):
        props({"bad key": 1})


@pytest.mark.parametrize(("value", "safe"), [("=SUM(A1)", "'=SUM(A1)"), ("+1", "'+1"), ("-2", "'-2"), ("@x", "'@x"), ("plain", "plain"), (7, 7)])
def test_csv_safe_neutralises_spreadsheet_formulas(value, safe):
    assert csv_safe(value) == safe


# ---------------------------------------------------------------- Graph
def test_graph_node_merges_properties_and_ignores_empty_values():
    g = Graph()
    assert g.node("L", "1", a=1, b=None, c="") == "1"
    g.node("L", "1", d=2)
    assert g.nodes["L"]["1"] == {"id": "1", "a": 1, "d": 2}


def test_graph_edge_skips_missing_ends_and_none_props():
    g = Graph()
    g.edge("R", "A", "1", "B", "2", w=1, x=None)
    g.edge("R", "A", "", "B", "2")
    g.edge("R", "A", "1", "B", None)
    assert g.edges["R"] == [("A", "1", "B", "2", {"w": 1})]


def test_graph_merge_and_counts():
    a, b = Graph(), Graph()
    a.node("L", "1", x=1)
    b.node("L", "1", y=2)
    b.node("M", "9")
    b.edge("R", "L", "1", "M", "9")
    b.skipped["t"] += 2
    a.merge(b)
    assert a.nodes["L"]["1"] == {"id": "1", "x": 1, "y": 2}
    assert a.counts() == ({"L": 1, "M": 1}, {"R": 1})
    assert a.skipped["t"] == 2


# ---------------------------------------------------------------- batched loading
def test_create_nodes_batches_and_groups_by_key_set():
    db = FakeEngine()
    rows = [{"id": str(i), "a": 1} for i in range(5)] + [{"id": "x", "b": None}]
    create_nodes(db, "Thing", rows, batch=2)
    assert len(db.queries) == 4  # 5 rows with {id, a} in batches of 2 -> 3, and 1 row with {id}
    assert all(q.startswith("CREATE (:Thing ") for q in db.queries)
    assert "b:" not in db.queries[-1]


def test_create_nodes_rejects_a_bad_label():
    with pytest.raises(ValueError):
        create_nodes(FakeEngine(), "Bad Label", [{"id": "1"}])


def test_create_edges_matches_by_id_and_writes_props_only_when_present():
    db = FakeEngine()
    create_edges(db, "SOLD_TO", [("Loan", "L1", "Purchaser", "P1", {}), ("Loan", "L2", "Purchaser", "P1", {"w": 1})], batch=1)
    assert db.queries[0] == "MATCH (a0:Loan), (b0:Purchaser) WHERE a0.id = 'L1' AND b0.id = 'P1' CREATE (a0)-[:SOLD_TO]->(b0)"
    assert db.queries[1].endswith("CREATE (a0)-[:SOLD_TO {w: 1}]->(b0)")


def test_create_edges_rejects_bad_identifiers():
    with pytest.raises(ValueError):
        create_edges(FakeEngine(), "SOLD TO", [("Loan", "1", "P", "2", {})])
    with pytest.raises(ValueError):
        create_edges(FakeEngine(), "R", [("Lo an", "1", "P", "2", {})])


def test_statements_drops_comments_and_splits(tmp_path):
    f = tmp_path / "s.cypher"
    f.write_text("// header\nCREATE CONSTRAINT a\n  FOR (n:A);\n// note\nCREATE CONSTRAINT b FOR (n:B);\n\n")
    assert statements(f) == ["CREATE CONSTRAINT a FOR (n:A)", "CREATE CONSTRAINT b FOR (n:B)"]


# ---------------------------------------------------------------- engine client
@pytest.fixture
def opened(monkeypatch):
    """Patch helpers.open_url; returns the list of calls and lets a test set the next reply or error."""
    calls, state = [], {"reply": json_body({}), "error": None}

    def fake_open(url, data=None, headers=None, method=None, timeout=None):
        calls.append({"url": url, "data": data, "headers": headers, "method": method, "timeout": timeout})
        if state["error"]:
            raise state["error"]
        return state["reply"]

    monkeypatch.setattr(helpers, "open_url", fake_open)
    return calls, state


def test_engine_rejects_a_non_http_url():
    with pytest.raises(ValueError):
        Engine("file:///tmp/x", "g")


def test_engine_query_posts_json_and_returns_records(opened):
    calls, state = opened
    state["reply"] = json_body({"records": [[1]]})
    db = Engine("http://e:1/", "g")
    assert db.q("RETURN 1") == [[1]]
    assert calls[0]["url"] == "http://e:1/api/query" and calls[0]["method"] == "POST"
    assert json.loads(calls[0]["data"]) == {"query": "RETURN 1", "graph": "g"}
    assert db.calls == 1


def test_engine_http_error_names_the_url_and_the_statement(opened):
    _, state = opened
    state["error"] = http_error("http://e:1/api/query", 400, b"syntax error near X")
    with pytest.raises(EngineError, match="HTTP 400 syntax error near X") as e:
        Engine("http://e:1", "g").q("MATCH (n) RETURN n")
    assert "in: MATCH (n) RETURN n" in str(e.value)


def test_engine_unreachable_is_an_engine_error(opened):
    _, state = opened
    state["error"] = urllib.error.URLError("connection refused")
    with pytest.raises(EngineError, match="not reachable"):
        Engine("http://e:1", "g").tenants()


def test_engine_non_json_reply_is_an_engine_error(opened):
    _, state = opened
    state["reply"] = FakeResponse(b"<html>proxy error</html>")
    with pytest.raises(EngineError, match="not JSON"):
        Engine("http://e:1", "g").post("/api/x", {})
    state["reply"] = FakeResponse(b"<html>")
    with pytest.raises(EngineError, match="not JSON"):
        Engine("http://e:1", "g").status()


def test_engine_tenants_status_create_and_export(opened, tmp_path):
    calls, state = opened
    db = Engine("http://e:1", "g")
    state["reply"] = json_body({"tenants": [{"id": "a"}, {"id": "g"}]})
    assert db.tenants() == ["a", "g"]
    state["reply"] = json_body({"version": "1.7.1"})
    assert db.status()["version"] == "1.7.1"
    assert calls[-1]["timeout"] == config.TIMEOUT_STATUS_S
    state["reply"] = json_body({})
    db.create_tenant()
    assert json.loads(calls[-1]["data"]) == {"id": "g", "name": "g", "quotas": config.TENANT_QUOTAS}
    state["reply"] = FakeResponse(b"\x1f\x8bsnapshot")
    assert db.export_snapshot(tmp_path / "out" / "s.sgsnap") == 10
    assert (tmp_path / "out" / "s.sgsnap").read_bytes() == b"\x1f\x8bsnapshot"
    assert calls[-1]["timeout"] == config.TIMEOUT_SNAPSHOT_S


def test_open_url_refuses_non_http_before_opening():
    with pytest.raises(ValueError):
        helpers.open_url("file:///etc/passwd")


@pytest.fixture
def local_engine():
    """A real HTTP server on 127.0.0.1 that answers like the engine, for end-to-end client tests."""
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self._reply(200, {"tenants": [{"id": "g"}]} if self.path == "/api/tenants" else {"version": "test"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if "BAD" in body.get("query", ""):
                self._reply(400, {"error": "syntax"})
            else:
                self._reply(200, {"records": [[body["graph"], body["query"]]]})

        def _reply(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_engine_end_to_end_over_real_http(local_engine):
    db = Engine(local_engine, "g")
    assert db.tenants() == ["g"]
    assert db.status() == {"version": "test"}
    assert db.q("RETURN 1") == [["g", "RETURN 1"]]
    with pytest.raises(EngineError, match="HTTP 400"):
        db.q("BAD")
