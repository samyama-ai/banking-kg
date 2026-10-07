"""etl.loader: layer selection, the bank-data gate, the load-and-check, and the command line."""

import json

import pytest

from etl import bridge, loader
from etl.helpers import EngineError, Graph
from tests.conftest import FakeEngine


def test_parse_layers():
    assert loader.parse_layers("market,bank") == {"market", "bank"}
    assert loader.parse_layers(" bank ") == {"bank"}
    for bad in ("", "market,banks", "all", ","):
        with pytest.raises(ValueError, match="--layers"):
            loader.parse_layers(bad)


def test_check_bank_data(tmp_path):
    with pytest.raises(loader.LoadRefusedError, match="not found"):
        loader.check_bank_data(tmp_path)
    (tmp_path / loader.VALIDATION_REPORT).write_text(json.dumps({"ok": False}))
    with pytest.raises(loader.LoadRefusedError, match="failed its checks"):
        loader.check_bank_data(tmp_path)
    (tmp_path / loader.VALIDATION_REPORT).write_text(json.dumps({"ok": True}))
    loader.check_bank_data(tmp_path)


def test_build_market_only_has_no_bank_and_no_bridge(market_dir, bank_dir):
    g, as_of = loader.build(market_dir, bank_dir, {"market"})
    assert as_of is None and "Customer" not in g.nodes and bridge.BANK_ID not in g.nodes["Lender"]


def test_build_both_layers_tags_bank_nodes_and_adds_the_bridge(market_dir, bank_dir):
    g, as_of = loader.build(market_dir, bank_dir, {"market", "bank"})
    assert as_of == "2026-08-31"
    assert all(p.get("synthetic") for p in g.nodes["Customer"].values())
    assert not any(p.get("synthetic") for p in g.nodes["Application"].values())
    assert g.nodes["Lender"][bridge.BANK_ID]["synthetic"] is True
    assert len(g.edges["OFFERED_BY"]) == len(g.nodes["Product"])


def test_build_bank_only_skips_the_bridge(market_dir, bank_dir):
    g, _ = loader.build(market_dir, bank_dir, {"bank"})
    assert "Lender" not in g.nodes and "OFFERED_BY" not in g.edges


def test_engine_counts_and_differences():
    db = FakeEngine([("labels(n)", [[["Lender"], 2], ["Loan", 3]]), ("type(r)", [["SOLD_TO", 1]])])
    got_n, got_e = loader.engine_counts(db)
    assert got_n == {"Lender": 2, "Loan": 3} and got_e == {"SOLD_TO": 1}
    assert loader.count_differences({"Lender": 2, "Loan": 4}, {"SOLD_TO": 1, "X": 1}, got_n, got_e) == [
        "Loan: built 4, engine 3",
        "X: built 1, engine 0",
    ]


def small_graph():
    g = Graph()
    g.node("Lender", "L1")
    g.node("Loan", "N1")
    g.edge("ORIGINATED_BY", "Loan", "N1", "Lender", "L1")
    return g


def counting_engine(nodes=0, lender=1, loan=1, rel=1, tenants=()):
    return FakeEngine(
        [("RETURN count(n)", [[nodes]]), ("labels(n)", [[["Lender"], lender], [["Loan"], loan]]), ("type(r)", [["ORIGINATED_BY", rel]])],
        tenants=tenants,
    )


def test_load_creates_the_tenant_applies_the_schema_and_checks_counts():
    db, lines = counting_engine(), []
    loader.load(db, small_graph(), lines.append)
    assert db.tenant_ids == ["t"] and "created tenant t" in lines
    assert sum(q.startswith("CREATE CONSTRAINT") for q in db.queries) == 29
    assert any("verified in engine" in line for line in lines)


def test_load_refuses_a_non_empty_tenant():
    with pytest.raises(loader.LoadRefusedError, match="not empty"):
        loader.load(counting_engine(nodes=5, tenants=["t"]), small_graph(), lambda _: None)


def test_load_refuses_when_a_count_differs():
    with pytest.raises(loader.LoadRefusedError, match="Loan: built 1, engine 0"):
        loader.load(counting_engine(loan=0, tenants=["t"]), small_graph(), lambda _: None)


def test_main_exit_codes(monkeypatch, market_dir, bank_dir, tmp_path, capsys):
    monkeypatch.setattr(loader, "Engine", lambda url, graph: FakeEngine([("RETURN count(n)", [[7]])], tenants=[graph]))
    assert loader.main(["--data", str(market_dir), "--bank-data", str(bank_dir), "--layers", "market"]) == loader.EXIT_REFUSED
    assert "not empty" in capsys.readouterr().err
    assert loader.main(["--layers", "everything"]) == loader.EXIT_REFUSED

    def unreachable(self):
        raise EngineError("engine not reachable")

    monkeypatch.setattr(loader, "build", lambda *a: (small_graph(), None))
    monkeypatch.setattr(loader, "Engine", lambda url, graph: type("E", (FakeEngine,), {"tenants": unreachable})())
    assert loader.main(["--layers", "market"]) == loader.EXIT_UNREACHABLE


def test_main_success_runs_audiences_and_exports(monkeypatch, tmp_path):
    db = counting_engine()
    monkeypatch.setattr(loader, "Engine", lambda url, graph: db)
    monkeypatch.setattr(loader, "build", lambda *a: (small_graph(), "2026-08-31"))
    ran = []
    monkeypatch.setattr(loader.audiences, "run", lambda d, as_of, out, log: ran.append((as_of, out)))
    snap = tmp_path / "s.sgsnap"
    assert loader.main(["--data", str(tmp_path), "--export", str(snap)]) == loader.EXIT_OK
    assert ran == [("2026-08-31", tmp_path / "audiences")] and snap.read_bytes() == b"snap"
