"""Build banking-kg (market layer + bank layer + bridge), load it into a Samyama engine, check it,
compute the bank's campaign audiences and optionally export a snapshot.

    python -m etl.loader --url http://localhost:8081 --graph bankingkg
    python -m etl.loader ... --layers market                 # the public layer only (31,128 nodes)
    python -m etl.loader ... --export ../data/banking-kg/banking-kg.sgsnap

Defaults (URL, tenant, data directory, state, year) come from etl/config.py and its environment variables.

In order:
  1. build every requested layer in memory (etl.market, etl.bank, etl.bridge)
  2. refuse unless the bank data's validation_report_v1.json says ok
  3. create the tenant if missing; refuse if it already holds data
  4. apply schema/banking_kg.cypher (one uniqueness constraint per label; idempotent)
  5. load nodes, then edges
  6. check every label and relationship-type count against what was built; fail on any difference
  7. bank layer: compute audiences UC1, UC3-UC7 with UC2 applied (etl.audiences), export CSVs
  8. export the snapshot if --export is given
Then: `python -m etl.embed` (vector search) and `python -m etl.verify` (independent audience check).

Exit code: 0 on success, 1 when the load is refused or a count differs, 2 when the engine or data cannot be reached.
"""

import argparse
import json
import pathlib
import sys
import time

from etl import audiences, bank, bridge, config, market
from etl.helpers import Engine, EngineError, Graph, create_edges, create_nodes, statements

SCHEMA = config.ROOT / "schema" / "banking_kg.cypher"
LAYERS = ("market", "bank")
VALIDATION_REPORT = "validation_report_v1.json"
EXIT_OK, EXIT_REFUSED, EXIT_UNREACHABLE = 0, 1, 2


class LoadRefusedError(RuntimeError):
    """The loader will not proceed: invalid input data, a non-empty tenant, or counts that do not match."""


def parse_layers(text: str) -> set:
    """{'market', 'bank'} from a comma list; ValueError naming anything unknown or an empty list."""
    layers = {x.strip() for x in text.split(",") if x.strip()}
    unknown = layers - set(LAYERS)
    if unknown or not layers:
        raise ValueError(f"--layers takes a comma list of {', '.join(LAYERS)}; got {text!r}")
    return layers


def check_bank_data(bank_data: pathlib.Path):
    """Refuse bank data whose own validator did not pass."""
    path = bank_data / VALIDATION_REPORT
    if not path.exists():
        raise LoadRefusedError(f"{path} not found - is {bank_data} the bank's request tables?")
    if not json.loads(path.read_text()).get("ok"):
        raise LoadRefusedError(f"{path} says the dataset failed its checks - refusing to load it")


def build(data: pathlib.Path, bank_data: pathlib.Path, layers, state=config.STATE, year=config.YEAR):
    """The whole graph in memory, plus the bank layer's as-of date (None without the bank layer)."""
    g, as_of = Graph(), None
    if "market" in layers:
        g.merge(market.build(data, state, year))
    if "bank" in layers:
        check_bank_data(bank_data)
        b, as_of = bank.build(bank_data)
        for rows in b.nodes.values():
            for p in rows.values():
                p["synthetic"] = True
        g.merge(b)
        if "market" in layers:
            g.merge(bridge.build(g, b))
    return g, as_of


def engine_counts(db: Engine):
    """({label: count}, {relationship type: count}) as the engine reports them."""
    nodes = {(r[0][0] if isinstance(r[0], list) else r[0]): r[1] for r in db.q("MATCH (n) RETURN labels(n), count(n)")}
    return nodes, dict(db.q("MATCH ()-[r]->() RETURN type(r), count(r)"))


def count_differences(want_n, want_e, got_n, got_e) -> list:
    """One line per label or relationship type whose engine count differs from what was built."""
    bad = [f"{k}: built {v:,}, engine {got_n.get(k, 0):,}" for k, v in want_n.items() if got_n.get(k, 0) != v]
    return bad + [f"{k}: built {v:,}, engine {got_e.get(k, 0):,}" for k, v in want_e.items() if got_e.get(k, 0) != v]


def load(db: Engine, g: Graph, log=print):
    """Create the tenant if needed, apply the schema, load g and check every count; LoadRefusedError on a problem."""
    if db.graph not in db.tenants():
        db.create_tenant()
        log(f"created tenant {db.graph}")
    if db.q("MATCH (n) RETURN count(n)")[0][0]:
        raise LoadRefusedError(f"tenant {db.graph} is not empty - use a new --graph or delete the tenant first")
    for s in statements(SCHEMA):
        db.q(s)
    log("schema applied")
    for label, rows in g.nodes.items():
        create_nodes(db, label, list(rows.values()))
        log(f"  {label:20} {len(rows):>7,}")
    for rel, es in g.edges.items():
        create_edges(db, rel, es)
        log(f"  {rel:20} {len(es):>7,}")
    want_n, want_e = g.counts()
    got_n, got_e = engine_counts(db)
    bad = count_differences(want_n, want_e, got_n, got_e)
    if bad:
        raise LoadRefusedError("count mismatch after load:\n  " + "\n  ".join(bad))
    log(f"verified in engine: {sum(got_n.values()):,} nodes / {sum(got_e.values()):,} edges, every label and type matches")


def main(argv=None):
    """CLI entry point; returns the process exit code."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=pathlib.Path, default=config.DATA_DIR)
    ap.add_argument("--bank-data", type=pathlib.Path, help=f"the bank's request tables (default: <data>/{config.BANK_DIR_NAME})")
    ap.add_argument("--layers", default=",".join(LAYERS), help="comma list of market, bank (default both, with the bridge)")
    ap.add_argument("--url", default=config.ENGINE_URL)
    ap.add_argument("--graph", default=config.GRAPH)
    ap.add_argument("--state", default=config.STATE)
    ap.add_argument("--year", type=int, default=config.YEAR)
    ap.add_argument("--export", type=pathlib.Path, help="write the tenant snapshot here after loading")
    a = ap.parse_args(argv)
    t0 = time.time()

    def log(msg):
        print(f"[{time.time() - t0:7.1f}s] {msg}", flush=True)

    try:
        layers = parse_layers(a.layers)
        db = Engine(a.url, a.graph)
        g, as_of = build(a.data, a.bank_data or a.data / config.BANK_DIR_NAME, layers, a.state, a.year)
        want_n, want_e = g.counts()
        log(f"built {sum(want_n.values()):,} nodes / {sum(want_e.values()):,} edges ({', '.join(sorted(layers))})")
        for table, n in sorted(g.skipped.items()):
            log(f"  skipped {n:,} {table} rows naming a customer the customers table does not have")
        load(db, g, log)
        if as_of:
            audiences.run(db, as_of, a.data / config.AUDIENCE_DIR_NAME, log)
        if a.export:
            log(f"snapshot {a.export} ({db.export_snapshot(a.export):,} bytes)")
    except (LoadRefusedError, ValueError, FileNotFoundError) as e:
        print(f"load refused: {e}", file=sys.stderr)
        return EXIT_REFUSED
    except EngineError as e:
        print(f"engine error: {e}", file=sys.stderr)
        return EXIT_UNREACHABLE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
