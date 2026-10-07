"""In-memory graph, engine client, Cypher literals and batched loading (standard library only).

Engine 1.7.1 rules this follows:
  * one label per node; multi-label MATCH is unreliable
  * property maps take literals only (no parameters), so values are interpolated with lit() and every
    label, relationship type and property key is checked by ident() before it reaches a statement
  * uniqueness constraints are declared, but the loader checks every count itself
  * load into an engine started with --data-path, never --ephemeral, or id-anchored edges are dropped
  * the vector index does not backfill: embed after loading, then rebuild (etl.embed)
"""

import collections
import json
import pathlib
import re
import urllib.error
import urllib.request

from etl import config

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")  # characters a spreadsheet treats as the start of a formula


class EngineError(RuntimeError):
    """The engine could not be reached, or it rejected a request."""


def open_url(url, data=None, headers=None, method=None, timeout=config.TIMEOUT_QUERY_S):
    """The only place banking-kg opens a URL: refuses anything but http(s), then returns the open response.

    Callers handle urllib.error.HTTPError / URLError, which they translate into their own error type."""
    req = urllib.request.Request(config.check_url(url), data=data, headers=headers or {}, method=method)  # noqa: S310 - checked
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - scheme checked by config.check_url


def ident(name: str) -> str:
    """Return name if it is safe to use unquoted as a label, relationship type or property key."""
    if not isinstance(name, str) or not IDENT.match(name):
        raise ValueError(f"not a valid Cypher identifier: {name!r}")
    return name


def csv_safe(value):
    """A CSV cell that a spreadsheet will not run as a formula (prefixes a quote when needed)."""
    if isinstance(value, str) and value.startswith(FORMULA_START):
        return "'" + value
    return value


class Graph:
    """nodes[label][id] = props (always with "id"); edges[rel] = [(from_label, from_id, to_label, to_id, props)].

    skipped counts source rows a builder dropped, by table, so the loader can report them."""

    def __init__(self):
        self.nodes = collections.defaultdict(dict)
        self.edges = collections.defaultdict(list)
        self.skipped = collections.Counter()

    def node(self, label, nid, **p):
        """Create the node, or add properties to it. None and "" values are never stored. Returns the id."""
        cur = self.nodes[label].setdefault(nid, {"id": nid})
        cur.update({k: v for k, v in p.items() if v is not None and v != ""})
        return nid

    def edge(self, rel, fl, fid, tl, tid, **p):
        """Add a relationship; skipped when either end id is empty. None values are not stored."""
        if fid and tid:
            self.edges[rel].append((fl, fid, tl, tid, {k: v for k, v in p.items() if v is not None}))

    def merge(self, other: "Graph"):
        """Add another layer. A node present in both keeps both property sets (the other layer's win)."""
        for label, rows in other.nodes.items():
            for nid, p in rows.items():
                self.nodes[label].setdefault(nid, {}).update(p)
        for rel, es in other.edges.items():
            self.edges[rel].extend(es)
        self.skipped.update(other.skipped)
        return self

    def counts(self):
        """({label: node count}, {relationship type: edge count})."""
        return {k: len(v) for k, v in self.nodes.items()}, {k: len(v) for k, v in self.edges.items()}


class Engine:
    """A Samyama engine's HTTP API, bound to one tenant (graph)."""

    def __init__(self, url: str, graph: str):
        self.base, self.graph, self.calls = config.check_url(url).rstrip("/"), graph, 0

    def _read(self, path, timeout, **kw) -> bytes:
        """Open base + path and return the body; EngineError on any HTTP or network failure."""
        url = self.base + path
        try:
            with open_url(url, timeout=timeout, **kw) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            raise EngineError(f"{url}: HTTP {e.code} {e.read().decode(errors='replace')[: config.ERROR_SNIPPET]}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise EngineError(f"{url}: engine not reachable ({e}). Is it running, and is the URL right?") from None

    def post(self, path, body, timeout=config.TIMEOUT_QUERY_S, raw=False, method="POST"):
        """Send JSON to path; return the decoded JSON reply, or the raw bytes when raw=True."""
        data = self._read(path, timeout, data=json.dumps(body).encode(), method=method, headers={"Content-Type": "application/json"})
        if raw:
            return data
        try:
            return json.loads(data or b"{}")
        except json.JSONDecodeError:
            raise EngineError(f"{path}: reply is not JSON: {data[: config.ERROR_SNIPPET]!r}") from None

    def get(self, path, timeout=config.TIMEOUT_TENANTS_S):
        """GET path and return the decoded JSON reply."""
        data = self._read(path, timeout)
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            raise EngineError(f"{path}: reply is not JSON: {data[: config.ERROR_SNIPPET]!r}") from None

    def q(self, cypher: str):
        """Run one Cypher statement on this tenant; return its rows."""
        self.calls += 1
        try:
            return self.post("/api/query", {"query": cypher, "graph": self.graph}).get("records", [])
        except EngineError as e:
            raise EngineError(f"{e}\n  in: {cypher[: config.CYPHER_SNIPPET]}") from None

    def status(self):
        """The engine's /api/status (version, storage counts)."""
        return self.get("/api/status", timeout=config.TIMEOUT_STATUS_S)

    def tenants(self):
        """Ids of every tenant on the engine."""
        return [t["id"] for t in self.get("/api/tenants").get("tenants", [])]

    def create_tenant(self, quotas=None):
        """Create this tenant with the quotas in config.TENANT_QUOTAS (or the ones given)."""
        self.post("/api/tenants", {"id": self.graph, "name": self.graph, "quotas": quotas or config.TENANT_QUOTAS})

    def export_snapshot(self, dest: pathlib.Path) -> int:
        """Write the tenant's .sgsnap to dest; return its size in bytes."""
        data = self.post(f"/api/tenants/{self.graph}/snapshot/export", {}, timeout=config.TIMEOUT_SNAPSHOT_S, raw=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return len(data)


def lit(v) -> str:
    """A Cypher literal for v: booleans and numbers as-is, everything else as an escaped single-quoted string."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("\\", "\\\\").replace("'", "\\'") + "'"


def props(d: dict) -> str:
    """A Cypher property map of d's non-empty values, e.g. {id: 'x', n: 1}."""
    return "{" + ", ".join(f"{ident(k)}: {lit(v)}" for k, v in d.items() if v is not None and v != "") + "}"


def create_nodes(db: Engine, label: str, rows: list, batch=config.NODE_BATCH):
    """CREATE the rows as nodes of one label, in batches. Rows are grouped by key set so no null property is written."""
    label = ident(label)
    groups = collections.defaultdict(list)
    for r in rows:
        groups[tuple(sorted(k for k, v in r.items() if v is not None and v != ""))].append(r)
    for rs in groups.values():
        for i in range(0, len(rs), batch):
            db.q("CREATE " + ", ".join(f"(:{label} {props(r)})" for r in rs[i : i + batch]))


def create_edges(db: Engine, rel: str, edges: list, batch=config.EDGE_BATCH):
    """CREATE relationships of one type. edges: (from_label, from_id, to_label, to_id, props); ends matched by id."""
    rel = ident(rel)
    for i in range(0, len(edges), batch):
        chunk = edges[i : i + batch]
        m = ", ".join(f"(a{j}:{ident(e[0])}), (b{j}:{ident(e[2])})" for j, e in enumerate(chunk))
        w = " AND ".join(f"a{j}.id = {lit(e[1])} AND b{j}.id = {lit(e[3])}" for j, e in enumerate(chunk))
        c = ", ".join(f"(a{j})-[:{rel} {props(e[4])}]->(b{j})" if e[4] else f"(a{j})-[:{rel}]->(b{j})" for j, e in enumerate(chunk))
        db.q(f"MATCH {m} WHERE {w} CREATE {c}")


def statements(path: pathlib.Path) -> list:
    """Executable statements from a .cypher file: // comment lines dropped, split on ';'.

    The split is textual, so a statement must not contain ';' inside a string literal (the schema has none)."""
    text = "\n".join(line for line in path.read_text().splitlines() if not line.strip().startswith("//"))
    return [" ".join(s.split()) for s in text.split(";") if s.strip()]
