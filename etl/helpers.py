"""In-memory graph, engine client, Cypher literals and batched loading (standard library only).

Engine 1.7.1 rules this follows:
  * one label per node; multi-label MATCH is unreliable
  * property maps take literals only, so values are interpolated here with lit()
  * uniqueness constraints are declared, but the loader checks every count itself
  * load into an engine started with --data-path, never --ephemeral, or id-anchored edges are dropped
  * the vector index does not backfill: embed after loading, then rebuild (etl.embed)
"""

import collections
import json
import pathlib
import urllib.error
import urllib.request


class Graph:
    """nodes[label][id] = props (always with "id"); edges[rel] = [(from_label, from_id, to_label, to_id, props)]."""

    def __init__(self):
        self.nodes = collections.defaultdict(dict)
        self.edges = collections.defaultdict(list)

    def node(self, label, nid, **p):
        cur = self.nodes[label].setdefault(nid, {"id": nid})
        cur.update({k: v for k, v in p.items() if v is not None and v != ""})
        return nid

    def edge(self, rel, fl, fid, tl, tid, **p):
        if fid and tid:
            self.edges[rel].append((fl, fid, tl, tid, {k: v for k, v in p.items() if v is not None}))

    def merge(self, other: "Graph"):
        """Add another layer. A node present in both keeps both property sets (the other layer's win)."""
        for label, rows in other.nodes.items():
            for nid, p in rows.items():
                self.nodes[label].setdefault(nid, {}).update(p)
        for rel, es in other.edges.items():
            self.edges[rel].extend(es)
        return self

    def counts(self):
        return {k: len(v) for k, v in self.nodes.items()}, {k: len(v) for k, v in self.edges.items()}


class Engine:
    def __init__(self, url: str, graph: str):
        self.base, self.graph, self.calls = url.rstrip("/"), graph, 0

    def post(self, path, body, timeout=600, raw=False, method="POST"):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                return data if raw else json.loads(data or b"{}")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"{path}: {e.code} {e.read().decode()[:400]}") from None

    def q(self, cypher: str):
        self.calls += 1
        try:
            return self.post("/api/query", {"query": cypher, "graph": self.graph}).get("records", [])
        except RuntimeError as e:
            raise RuntimeError(f"{e}\n  in: {cypher[:300]}") from None

    def status(self):
        with urllib.request.urlopen(self.base + "/api/status", timeout=10) as r:
            return json.loads(r.read())

    def tenants(self):
        with urllib.request.urlopen(self.base + "/api/tenants", timeout=30) as r:
            return [t["id"] for t in json.loads(r.read())["tenants"]]

    def create_tenant(self, max_memory_gb=4, max_nodes=2_000_000):
        self.post("/api/tenants", {"id": self.graph, "name": self.graph,
                                   "quotas": {"max_connections": 100, "max_edges": 10_000_000,
                                              "max_memory_bytes": max_memory_gb << 30, "max_nodes": max_nodes,
                                              "max_query_time_ms": 120_000, "max_storage_bytes": 10 << 30}})

    def export_snapshot(self, dest: pathlib.Path) -> int:
        data = self.post(f"/api/tenants/{self.graph}/snapshot/export", {}, timeout=1800, raw=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return len(data)


def lit(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def props(d: dict) -> str:
    return "{" + ", ".join(f"{k}: {lit(v)}" for k, v in d.items() if v is not None and v != "") + "}"


def create_nodes(db: Engine, label: str, rows: list, batch=200):
    """Rows grouped by key set so no null property is written."""
    groups = collections.defaultdict(list)
    for r in rows:
        groups[tuple(sorted(k for k, v in r.items() if v is not None and v != ""))].append(r)
    for rs in groups.values():
        for i in range(0, len(rs), batch):
            db.q("CREATE " + ", ".join(f"(:{label} {props(r)})" for r in rs[i:i + batch]))


def create_edges(db: Engine, rel: str, edges: list, batch=100):
    """edges: (from_label, from_id, to_label, to_id, props). Index-anchored MATCH ... CREATE."""
    for i in range(0, len(edges), batch):
        chunk = edges[i:i + batch]
        m = ", ".join(f"(a{j}:{e[0]}), (b{j}:{e[2]})" for j, e in enumerate(chunk))
        w = " AND ".join(f"a{j}.id = {lit(e[1])} AND b{j}.id = {lit(e[3])}" for j, e in enumerate(chunk))
        c = ", ".join(f"(a{j})-[:{rel} {props(e[4])}]->(b{j})" if e[4] else f"(a{j})-[:{rel}]->(b{j})" for j, e in enumerate(chunk))
        db.q(f"MATCH {m} WHERE {w} CREATE {c}")


def statements(path: pathlib.Path) -> list:
    """Executable statements from a .cypher file: comments dropped, split on ';'."""
    text = "\n".join(line for line in path.read_text().splitlines() if not line.strip().startswith("//"))
    return [" ".join(s.split()) for s in text.split(";") if s.strip()]
