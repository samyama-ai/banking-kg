"""Embed text for Vector Search with a local Ollama model (no API key), and write each lender's book profile.

    python -m etl.embed --url http://localhost:8081 --graph bankingkg

Sets the tenant's embed config (Ollama, the model and dimension in etl/config.py — the same model the engine
uses to embed the search text), creates one vector index per label, writes n.embedding and rebuilds the
indexes. Run it after etl.loader: the vector index does not backfill, so the rebuild at the end is what makes
the vectors visible. Re-running it is harmless (indexes are recreated, vectors overwritten).

Text embedded per node (what a banker would type):
  market layer  Lender            its book profile (below)
                Industry          "<NAICS title> (NAICS <code>)"
                Franchise, Purchaser, DenialReason, LoanProduct   a short phrase around the name
  bank layer    Product           "<name>, <checking account | savings account | certificate of deposit | loan or credit line>"
                Counterparty      "<name>, <competitor bank | employer | lender>"
                MerchantCategory  "<ISO 18245 description> (MCC <code>)"
                Audience          "<name>: <campaign> campaign audience"
Labels whose layer is not loaded are skipped.

Lender.profile is generated from the graph itself, so "lenders whose book resembles this one" (spec Q18)
is a similarity over what the lender actually does in this market:
  "<name>, <type> headquartered in <city, state>. <n> mortgages originated in <market> <year>, mostly <product>;
   keeps <k>% on balance sheet, sells mainly to <buyer>. SBA business lending in <industries>."

Exit code: 0 on success, 2 when the engine or Ollama cannot be reached.
"""

import argparse
import collections
import json
import sys
import time
import urllib.error

from etl import config
from etl.helpers import Engine, EngineError, ident, lit, open_url

KIND = {"DDA": "checking account", "SDA": "savings account", "CDA": "certificate of deposit", "LOAN": "loan or credit line"}
CP = {"COMPETITOR": "competitor bank", "EMPLOYER": "employer", "LENDER": "lender"}
TEXTS = {
    "Industry": ("MATCH (n:Industry) RETURN n.id, n.name, n.naics", lambda n, c: f"{n} (NAICS {c})"),
    "Franchise": ("MATCH (n:Franchise) RETURN n.id, n.name, ''", lambda n, _: f"{n} franchise"),
    "Purchaser": ("MATCH (n:Purchaser) RETURN n.id, n.name, ''", lambda n, _: f"{n}, a buyer of mortgage loans on the secondary market"),
    "DenialReason": ("MATCH (n:DenialReason) RETURN n.id, n.name, ''", lambda n, _: f"Mortgage application denied because of {n}"),
    "LoanProduct": ("MATCH (n:LoanProduct) RETURN n.id, n.name, ''", lambda n, _: f"{n} mortgage"),
    "Product": ("MATCH (n:Product) RETURN n.id, n.name, n.product_type", lambda n, t: f"{n}, {KIND.get(t, 'product')}"),
    "Counterparty": ("MATCH (n:Counterparty) RETURN n.id, n.name, n.kind", lambda n, k: f"{n}, {CP.get(k, str(k).lower())}"),
    "MerchantCategory": ("MATCH (n:MerchantCategory) RETURN n.id, n.name, n.mcc_code", lambda n, c: f"{n} (MCC {c})"),
    "Audience": ("MATCH (n:Audience) RETURN n.id, n.name, n.campaign", lambda n, c: f"{n}: {c} campaign audience"),
}
TOP_INDUSTRIES = 3  # industries named in a lender's profile
PERCENT = 100
EXIT_OK, EXIT_UNREACHABLE = 0, 2


class EmbedError(RuntimeError):
    """Ollama could not be reached or returned something unusable."""


def ollama(url, model, texts):
    """Embedding vectors for texts from Ollama's /api/embed, one per text, in order."""
    try:
        with open_url(
            url.rstrip("/") + "/api/embed",
            data=json.dumps({"model": model, "input": texts}).encode(),
            headers={"Content-Type": "application/json"},
            timeout=config.TIMEOUT_OLLAMA_S,
        ) as r:
            vecs = json.loads(r.read()).get("embeddings")
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
        raise EmbedError(f"Ollama at {url}: {e}. Is it running, and has `ollama pull {model}` been run?") from None
    if not isinstance(vecs, list) or len(vecs) != len(texts):
        raise EmbedError(f"Ollama at {url} returned {len(vecs or [])} vectors for {len(texts)} texts")
    return vecs


def profiles(db, market=config.STATE, year=config.YEAR):
    """{lender id: one-sentence book profile} for every Lender, built from the loaded graph."""
    base = {i: (n, t, c, s) for i, n, t, c, s in db.q("MATCH (l:Lender) RETURN l.id, l.name, l.lender_type, l.hq_city, l.hq_state")}
    loans = dict(db.q("MATCH (l:Lender)<-[:ORIGINATED_BY]-(n:Loan) RETURN l.id, count(n)"))
    sold = collections.defaultdict(collections.Counter)
    for i, p, c in db.q("MATCH (l:Lender)<-[:ORIGINATED_BY]-(:Loan)-[:SOLD_TO]->(p:Purchaser) RETURN l.id, p.name, count(*)"):
        sold[i][p] = c
    prod = collections.defaultdict(collections.Counter)
    for i, p, c in db.q("MATCH (l:Lender)<-[:FILED_WITH]-(a:Application)-[:FOR_PRODUCT]->(p:LoanProduct) RETURN l.id, p.name, count(*)"):
        prod[i][p] = c
    ind = collections.defaultdict(collections.Counter)
    for i, n, c in db.q(
        "MATCH (l:Lender)<-[:MADE_BY]-(:SBALoan)<-[:BORROWED]-(:Business)-[:IN_INDUSTRY]->(x:Industry) RETURN l.id, x.name, count(*)"
    ):
        ind[i][n] = c
    own = collections.defaultdict(collections.Counter)  # the bank layer's own book, for the synthetic lender
    for i, t, c in db.q(
        "MATCH (l:Lender)<-[:OFFERED_BY]-(:Product)<-[:OF_PRODUCT]-(:Account)-[:HAS_LOAN]->(n:CustomerLoan) RETURN l.id, n.loan_type, count(n)"
    ):
        own[i][t] = c
    out = {}
    for i, (name, typ, city, st) in base.items():
        parts = [f"{name}, {(typ or 'lender').lower()}" + (f" headquartered in {city}, {st}" if city else "") + "."]
        n = loans.get(i, 0)
        if prod[i]:
            parts.append(f"{n} {market} mortgages originated in {year}, mostly {prod[i].most_common(1)[0][0].replace(':', ', ').lower()}.")
        if n:
            s = sum(sold[i].values())
            kept = round(PERCENT * (n - s) / n)
            parts.append(
                f"Keeps {kept}% of its loans on balance sheet" + (f", sells mainly to {sold[i].most_common(1)[0][0]}." if s else ", sells none.")
            )
        if ind[i]:
            parts.append("SBA business lending in " + ", ".join(k.lower() for k, _ in ind[i].most_common(TOP_INDUSTRIES)) + ".")
        if own[i]:
            parts.append("Retail and commercial book of " + ", ".join(f"{c} {t.lower()}" for t, c in own[i].most_common()) + " loans.")
        out[i] = " ".join(parts)
    return out


def write(db, label, rows, vecs, batch=config.EMBED_SET_BATCH):
    """SET n.embedding for (id, text) rows of one label, batch nodes per statement."""
    label = ident(label)
    for j in range(0, len(rows), batch):
        part = list(zip(rows[j : j + batch], vecs[j : j + batch], strict=True))
        m = ", ".join(f"(n{k}:{label})" for k in range(len(part)))
        w = " AND ".join(f"n{k}.id = {lit(nid)}" for k, ((nid, _), _) in enumerate(part))
        s = ", ".join(f"n{k}.embedding = {json.dumps([round(x, 6) for x in v])}" for k, (_, v) in enumerate(part))
        db.q(f"MATCH {m} WHERE {w} SET {s}")


def texts(db, market, year):
    """{label: [(id, text)]} for every label that has nodes; also writes Lender.profile."""
    rows = {}
    prof = profiles(db, market, year)
    if prof:
        for i, text in prof.items():
            db.q(f"MATCH (l:Lender) WHERE l.id = {lit(i)} SET l.profile = {lit(text)}")
        rows["Lender"] = list(prof.items())
    for label, (cy, fmt) in TEXTS.items():
        rs = [(i, fmt(n, x)) for i, n, x in db.q(cy)]
        if rs:
            rows[label] = rs
    return rows


def embed_config(engine_ollama, model, dims, labels):
    """The tenant embed_config: Ollama as the engine sees it, the name property embedded per label."""
    return {
        "provider": "Ollama",
        "embedding_model": model,
        "api_key": None,
        "api_base_url": config.check_url(engine_ollama),
        "chunk_size": config.EMBED_CHUNK_SIZE,
        "chunk_overlap": config.EMBED_CHUNK_OVERLAP,
        "vector_dimension": dims,
        "embedding_policies": {label: ["name"] for label in labels},
        "embedding_property": "embedding",
    }


def run(db, ollama_url, engine_ollama, model, dims, market, year, log=print):
    """Profiles, embed config, indexes, vectors, rebuild. Returns the number of nodes embedded."""
    t0 = time.time()
    rows = texts(db, market, year)
    db.post(f"/api/tenants/{db.graph}", {"embed_config": embed_config(engine_ollama, model, dims, rows)}, method="PATCH")
    for label in rows:
        db.q(
            f"CREATE VECTOR INDEX {ident(label).lower()}_embedding FOR (n:{label}) ON (n.embedding) "
            f"OPTIONS {{dimensions: {int(dims)}, similarity: 'cosine'}}"
        )
    for label, rs in rows.items():
        for k in range(0, len(rs), config.EMBED_BATCH):
            chunk = rs[k : k + config.EMBED_BATCH]
            write(db, label, chunk, ollama(ollama_url, model, [t for _, t in chunk]))
        log(f"  {label:16} {len(rs):>5} embedded ({time.time() - t0:.0f}s)")
    rebuilt = db.post(f"/api/tenants/{db.graph}/vector-index/rebuild", {}, timeout=config.TIMEOUT_REBUILD_S)
    total = sum(map(len, rows.values()))
    log(f"{total:,} nodes embedded with {model} ({dims}-dim); rebuilt: {rebuilt}")
    return total


def main(argv=None):
    """CLI entry point; returns the process exit code."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=config.ENGINE_URL)
    ap.add_argument("--graph", default=config.GRAPH)
    ap.add_argument("--ollama", default=config.OLLAMA_URL, help="Ollama as seen from this machine")
    ap.add_argument("--engine-ollama", default=config.ENGINE_OLLAMA_URL, help="Ollama as seen from the engine")
    ap.add_argument("--model", default=config.EMBED_MODEL)
    ap.add_argument("--dims", type=int, default=config.EMBED_DIMS)
    ap.add_argument("--market", default=config.STATE)
    ap.add_argument("--year", type=int, default=config.YEAR)
    a = ap.parse_args(argv)
    try:
        run(Engine(a.url, a.graph), a.ollama, a.engine_ollama, a.model, a.dims, a.market, a.year, lambda m: print(m, flush=True))
    except (EngineError, EmbedError, ValueError) as e:
        print(f"embed failed: {e}", file=sys.stderr)
        return EXIT_UNREACHABLE
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
