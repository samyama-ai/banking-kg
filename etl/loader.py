"""Build banking-kg (market layer + bank layer + bridge), load it into a Samyama engine, check it,
compute the bank's campaign audiences and optionally export a snapshot.

    python -m etl.loader --data ../data/banking-kg --url http://localhost:8081 --graph bankingkg
    python -m etl.loader ... --layers market                 # the public layer only (the v1 31,128-node graph)
    python -m etl.loader ... --export ../data/banking-kg/banking-kg.sgsnap

In order:
  1. build every requested layer in memory (etl.market, etl.bank, etl.bridge)
  2. refuse unless the bank data's validation_report_v1.json says ok
  3. create the tenant if missing; refuse if it already holds data
  4. apply schema/banking_kg.cypher (one uniqueness constraint per label)
  5. load nodes, then edges
  6. check every label and relationship-type count against what was built; exit non-zero on any difference
  7. bank layer: compute audiences UC1, UC3-UC7 with UC2 applied (etl.audiences), export CSVs
  8. export the snapshot if --export is given
Then: `python -m etl.embed` (vector search) and `python -m etl.verify` (independent audience check).
"""

import argparse
import json
import pathlib
import sys
import time

from etl import audiences, bank, bridge, market
from etl.helpers import Engine, Graph, create_edges, create_nodes, statements

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema" / "banking_kg.cypher"


def build(data: pathlib.Path, bank_data: pathlib.Path, layers, state="DC", year=2023):
    """The whole graph in memory, plus the bank layer's as-of date (None without it)."""
    g, as_of = Graph(), None
    if "market" in layers:
        g.merge(market.build(data, state, year))
    if "bank" in layers:
        rep = json.loads((bank_data / "validation_report_v1.json").read_text())
        if not rep["ok"]:
            sys.exit("bank data: validation_report_v1.json says the dataset failed its checks - refusing to load it")
        b, as_of = bank.build(bank_data)
        for rows in b.nodes.values():
            for p in rows.values():
                p["synthetic"] = True
        g.merge(b)
        if "market" in layers:
            g.merge(bridge.build(g, b))
    return g, as_of


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=pathlib.Path, default=ROOT.parent / "data" / "banking-kg")
    ap.add_argument("--bank-data", type=pathlib.Path, help="the bank's request tables (default: <data>/bank_v1)")
    ap.add_argument("--layers", default="market,bank", help="comma list of market, bank (default both, with the bridge)")
    ap.add_argument("--url", default="http://localhost:8081")
    ap.add_argument("--graph", default="bankingkg")
    ap.add_argument("--state", default="DC")
    ap.add_argument("--year", type=int, default=2023)
    ap.add_argument("--export", type=pathlib.Path, help="write the tenant snapshot here after loading")
    a = ap.parse_args(argv)
    layers = {x.strip() for x in a.layers.split(",")}
    bank_data = a.bank_data or a.data / "bank_v1"
    t0 = time.time()

    def log(msg):
        print(f"[{time.time() - t0:7.1f}s] {msg}", flush=True)

    g, as_of = build(a.data, bank_data, layers, a.state, a.year)
    want_n, want_e = g.counts()
    log(f"built {sum(want_n.values()):,} nodes / {sum(want_e.values()):,} edges ({', '.join(sorted(layers))})")

    db = Engine(a.url, a.graph)
    if a.graph not in db.tenants():
        db.create_tenant()
        log(f"created tenant {a.graph}")
    if db.q("MATCH (n) RETURN count(n)")[0][0]:
        sys.exit(f"tenant {a.graph} is not empty - refusing to load. Use a new --graph or delete the tenant first.")
    for s in statements(SCHEMA):
        db.q(s)
    log("schema applied")
    for label, rows in g.nodes.items():
        create_nodes(db, label, list(rows.values()))
        log(f"  {label:20} {len(rows):>7,}")
    for rel, es in g.edges.items():
        create_edges(db, rel, es)
        log(f"  {rel:20} {len(es):>7,}")

    got_n = {(r[0][0] if isinstance(r[0], list) else r[0]): r[1] for r in db.q("MATCH (n) RETURN labels(n), count(n)")}
    got_e = dict(db.q("MATCH ()-[r]->() RETURN type(r), count(r)"))
    bad = [f"{k}: built {v:,}, engine {got_n.get(k, 0):,}" for k, v in want_n.items() if got_n.get(k, 0) != v]
    bad += [f"{k}: built {v:,}, engine {got_e.get(k, 0):,}" for k, v in want_e.items() if got_e.get(k, 0) != v]
    if bad:
        sys.exit("count mismatch after load:\n  " + "\n  ".join(bad))
    log(f"verified in engine: {sum(got_n.values()):,} nodes / {sum(got_e.values()):,} edges, every label and type matches")

    if as_of:
        audiences.run(db, as_of, a.data / "audiences", log)
    if a.export:
        log(f"snapshot {a.export} ({db.export_snapshot(a.export):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
