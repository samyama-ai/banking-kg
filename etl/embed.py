"""Embed text for Vector Search with a local Ollama model (no API key), and write each lender's book profile.

    python -m etl.embed --url http://localhost:8081 --graph bankingkg

Sets the tenant's embed config (Ollama all-minilm, 384-dim, the same model the engine uses to embed the
search text), creates one vector index per label, writes n.embedding and rebuilds the indexes. Run it after
etl.loader: the vector index does not backfill, so the rebuild at the end is what makes the vectors visible.

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
"""

import argparse
import collections
import json
import time

from etl.helpers import Engine, lit

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


def ollama(url, model, texts):
    import urllib.request
    req = urllib.request.Request(url.rstrip("/") + "/api/embed", data=json.dumps({"model": model, "input": texts}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["embeddings"]


def profiles(db, market="DC", year=2023):
    base = {i: (n, t, c, s) for i, n, t, c, s in db.q("MATCH (l:Lender) RETURN l.id, l.name, l.lender_type, l.hq_city, l.hq_state")}
    loans = dict(db.q("MATCH (l:Lender)<-[:ORIGINATED_BY]-(n:Loan) RETURN l.id, count(n)"))
    sold = collections.defaultdict(collections.Counter)
    for i, p, c in db.q("MATCH (l:Lender)<-[:ORIGINATED_BY]-(:Loan)-[:SOLD_TO]->(p:Purchaser) RETURN l.id, p.name, count(*)"):
        sold[i][p] = c
    prod = collections.defaultdict(collections.Counter)
    for i, p, c in db.q("MATCH (l:Lender)<-[:FILED_WITH]-(a:Application)-[:FOR_PRODUCT]->(p:LoanProduct) RETURN l.id, p.name, count(*)"):
        prod[i][p] = c
    ind = collections.defaultdict(collections.Counter)
    for i, n, c in db.q("MATCH (l:Lender)<-[:MADE_BY]-(:SBALoan)<-[:BORROWED]-(:Business)-[:IN_INDUSTRY]->(x:Industry) RETURN l.id, x.name, count(*)"):
        ind[i][n] = c
    own = collections.defaultdict(collections.Counter)      # the bank layer's own book, for the synthetic lender
    for i, t, c in db.q("MATCH (l:Lender)<-[:OFFERED_BY]-(:Product)<-[:OF_PRODUCT]-(:Account)-[:HAS_LOAN]->(n:CustomerLoan) "
                        "RETURN l.id, n.loan_type, count(n)"):
        own[i][t] = c
    out = {}
    for i, (name, typ, city, st) in base.items():
        parts = [f"{name}, {(typ or 'lender').lower()}" + (f" headquartered in {city}, {st}" if city else "") + "."]
        n = loans.get(i, 0)
        if prod[i]:
            parts.append(f"{n} {market} mortgages originated in {year}, mostly {prod[i].most_common(1)[0][0].replace(':', ', ').lower()}.")
        if n:
            s = sum(sold[i].values())
            kept = round(100 * (n - s) / n)
            parts.append(f"Keeps {kept}% of its loans on balance sheet" +
                         (f", sells mainly to {sold[i].most_common(1)[0][0]}." if s else ", sells none."))
        if ind[i]:
            parts.append("SBA business lending in " + ", ".join(k.lower() for k, _ in ind[i].most_common(3)) + ".")
        if own[i]:
            parts.append("Retail and commercial book of " + ", ".join(f"{c} {t.lower()}" for t, c in own[i].most_common()) + " loans.")
        out[i] = " ".join(parts)
    return out


def write(db, label, rows, vecs):
    for j in range(0, len(rows), 16):
        part = list(zip(rows[j:j + 16], vecs[j:j + 16]))
        m = ", ".join(f"(n{k}:{label})" for k in range(len(part)))
        w = " AND ".join(f"n{k}.id = {lit(nid)}" for k, ((nid, _), _) in enumerate(part))
        s = ", ".join(f"n{k}.embedding = {json.dumps([round(x, 6) for x in v])}" for k, (_, v) in enumerate(part))
        db.q(f"MATCH {m} WHERE {w} SET {s}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8081")
    ap.add_argument("--graph", default="bankingkg")
    ap.add_argument("--ollama", default="http://localhost:11434", help="Ollama as seen from this machine")
    ap.add_argument("--engine-ollama", default="http://host.docker.internal:11434", help="Ollama as seen from the engine")
    ap.add_argument("--model", default="all-minilm")
    ap.add_argument("--dims", type=int, default=384)
    ap.add_argument("--market", default="DC")
    ap.add_argument("--year", type=int, default=2023)
    a = ap.parse_args(argv)
    db, t0 = Engine(a.url, a.graph), time.time()

    rows = {}
    prof = profiles(db, a.market, a.year)
    if prof:
        for i, text in prof.items():
            db.q(f"MATCH (l:Lender) WHERE l.id = {lit(i)} SET l.profile = {lit(text)}")
        rows["Lender"] = list(prof.items())
    for label, (cy, fmt) in TEXTS.items():
        rs = [(i, fmt(n, x)) for i, n, x in db.q(cy)]
        if rs:
            rows[label] = rs
    db.post(f"/api/tenants/{a.graph}", {"embed_config": {
        "provider": "Ollama", "embedding_model": a.model, "api_key": None, "api_base_url": a.engine_ollama,
        "chunk_size": 512, "chunk_overlap": 50, "vector_dimension": a.dims,
        "embedding_policies": {label: ["name"] for label in rows}, "embedding_property": "embedding"}}, method="PATCH")
    for label in rows:
        db.q(f"CREATE VECTOR INDEX {label.lower()}_embedding FOR (n:{label}) ON (n.embedding) "
             f"OPTIONS {{dimensions: {a.dims}, similarity: 'cosine'}}")
    for label, rs in rows.items():
        for k in range(0, len(rs), 64):
            chunk = rs[k:k + 64]
            write(db, label, chunk, ollama(a.ollama, a.model, [t for _, t in chunk]))
        print(f"  {label:16} {len(rs):>5} embedded ({time.time() - t0:.0f}s)", flush=True)
    rebuilt = db.post(f"/api/tenants/{a.graph}/vector-index/rebuild", {}, timeout=900)
    print(f"{sum(map(len, rows.values())):,} nodes embedded with {a.model} ({a.dims}-dim); rebuilt: {rebuilt}")


if __name__ == "__main__":
    main()
