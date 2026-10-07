"""Time every demo question and every campaign-audience query on a loaded banking-kg graph.

    python -m benchmarks.run --url http://localhost:8081 --graph bankingkg

Reads the question set from demo/queries.cypher and the audiences from etl.audiences, runs each query
--runs times after one warm-up and writes benchmarks/results.md: rows returned, min and median wall time,
with the engine version, machine and graph size it was measured on. Wall time includes the HTTP round
trip. Single-machine numbers on this graph, not a performance claim.
"""

import argparse
import datetime as dt
import pathlib
import platform
import re
import statistics
import time

from etl.audiences import use_cases
from etl.helpers import Engine

ROOT = pathlib.Path(__file__).resolve().parent
QUESTIONS = ROOT.parent / "demo" / "queries.cypher"


def questions(path=QUESTIONS):
    """(label, cypher) for every '// Q<n> · <question>' block; a blank line ends a block."""
    out, cur, body = [], None, []
    for line in path.read_text().splitlines() + [""]:
        m = re.match(r"// (Q\d+) · (.*)", line)
        if m:
            cur, body = f"{m.group(1)} {m.group(2).split('[')[0].strip()}", []
        elif cur and line.strip() and not line.startswith("//"):
            body.append(line.strip())
        elif cur and not line.strip() and body:
            out.append((cur, " ".join(body)))
            cur, body = None, []
    return out


def timed(db, cypher, runs):
    n = len(db.q(cypher))
    times = []
    for _ in range(runs):
        t = time.perf_counter()
        db.q(cypher)
        times.append((time.perf_counter() - t) * 1000)
    return n, min(times), statistics.median(times)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8081")
    ap.add_argument("--graph", default="bankingkg")
    ap.add_argument("--runs", type=int, default=5)
    a = ap.parse_args(argv)
    db = Engine(a.url, a.graph)
    version = db.status().get("version")
    nodes = db.q("MATCH (n) RETURN count(n)")[0][0]
    edges = db.q("MATCH ()-[r]->() RETURN count(r)")[0][0]
    as_of = db.q("MATCH (a:Audience) RETURN a.as_of LIMIT 1")
    rows = [(label, *timed(db, cy, a.runs)) for label, cy in questions()]
    if as_of:
        rows += [(f"{uc.code} {uc.name}", *timed(db, uc.cypher, a.runs)) for uc in use_cases(as_of[0][0])]
    for label, n, _, md in rows:
        print(f"{label[:70]:70} {n:>6,} rows  median {md:7.1f} ms")
    lines = [
        "# Benchmark results — demo questions and campaign audiences", "",
        (f"Measured {dt.datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')} on {platform.platform()} ({platform.machine()}), "
         f"Samyama engine {version}, graph `{a.graph}`: {nodes:,} nodes / {edges:,} relationships. "
         f"{a.runs} runs after one warm-up; wall time including the HTTP round trip."), "",
        "| Query | Rows | Min (ms) | Median (ms) |", "|---|--:|--:|--:|",
    ]
    lines += [f"| {label} | {n:,} | {mn:.1f} | {md:.1f} |" for label, n, mn, md in rows]
    lines += ["", "Single machine. Not a performance claim; rerun on the target host before quoting any figure."]
    (ROOT / "results.md").write_text("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
