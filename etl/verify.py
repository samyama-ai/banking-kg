"""Check the graph's audiences against an independent calculation.

    python -m etl.verify --data-dir ../data/banking-kg/bank_v1 --audiences ../data/banking-kg/audiences

Every use case is recomputed here in plain Python straight from the request CSVs,
WITHOUT etl.bank or the engine, and compared member-for-member with the CSV
the graph exported. A difference means a Cypher bug, an engine quirk or a
build bug; it is never papered over.

If the dataset has an answer key (_answer_key/planted_patterns.csv from the
pattern planter), the estate and next-generation audiences are also checked
for recall of the planted heirs and children, and the friends-sharing-an-account
pattern is checked NOT to have been merged into a household.
"""

import argparse
import collections
import csv
import pathlib
import re
import sys
from datetime import date, timedelta

COMPETITOR = re.compile(r"^(?:EXT TRANSFER (?:TO|FROM)|WIRE TO) (.+?) X{4,}\d+$")
PAYROLL = re.compile(r"^(.+?) PAYROLL PPD ID: (\d+)$")


def read(root, entity):
    layer, name = entity.split(".", 1)
    with (root / layer / f"{name}.csv").open(newline="") as fh:
        return list(csv.DictReader(fh))


def expected(root: pathlib.Path) -> dict:
    cust = {r["source_customer_key"]: r for r in read(root, "bronze.customers")}
    as_of = next(iter(cust.values()))["extract_dt"]
    d = date.fromisoformat(as_of)
    d60, d90, d180 = ((d - timedelta(days=n)).isoformat() for n in (60, 90, 180))
    age = {k: d.year - int(r["birth_year"][:4]) if r["birth_year"] else None for k, r in cust.items()}
    hh = {}
    members = collections.defaultdict(set)
    for k, r in cust.items():
        if r["customer_type"] == "INDIVIDUAL" and r["address_line1"]:
            hh[k] = (r["address_line1"], r["postal_code"])
            members[hh[k]].add(k)
    acc = {r["source_account_key"]: r for r in read(root, "bronze.accounts")}
    own = read(root, "bronze.account_owners")
    by_acct = collections.defaultdict(list)
    by_cust = collections.defaultdict(list)
    for o in own:
        by_acct[o["source_account_key"]].append(o)
        by_cust[o["source_customer_key"]].append(o)
    active = {k for k, r in cust.items() if r["customer_status"] == "ACTIVE"}
    out = {}

    # UC1
    s = set()
    for k, r in cust.items():
        if r["customer_status"] != "CLOSED" or k not in hh:
            continue
        left = [acc[o["source_account_key"]] for o in by_cust[k] if o["relationship_code"] == "P"]
        if any(a["close_reason_code"] == "CUSTOMER_REQUEST" and (a["close_date"] or "") >= d60 for a in left):
            s |= {m for m in members[hh[k]] if m != k and m in active}
    out["UC1"] = s
    # UC3
    s = set()
    for a, os_ in by_acct.items():
        dead = [o for o in os_ if o["relationship_code"] == "P" and cust[o["source_customer_key"]]["customer_status"] == "DECEASED"]
        if dead:
            s |= {o["source_customer_key"] for o in os_ if o["relationship_code"] in ("B", "J") and o["source_customer_key"] in active}
    out["UC3"] = s
    # UC4
    s = set()
    for a, os_ in by_acct.items():
        olds = [o["source_customer_key"] for o in os_ if (age.get(o["source_customer_key"]) or 0) >= 65]
        for o in os_:
            y = o["source_customer_key"]
            if o["relationship_code"] in ("J", "B") and y in active and age.get(y) is not None and age[y] <= 40 and \
                    any(age[x] - age[y] >= 25 for x in olds if x != y):
                s.add(y)
    out["UC4"] = s
    # UC5
    logins90, ever = collections.Counter(), set()
    for r in read(root, "bronze.digital_sessions"):
        if r["login_success"] == "Y":
            ever.add(r["source_customer_key"])
            if r["login_timestamp"][:10] > d90:
                logins90[r["source_customer_key"]] += 1
    s = set()
    for ms in members.values():
        if any(logins90[m] >= 4 for m in ms):
            s |= {m for m in ms if m not in ever and m in active and any(logins90[u] >= 4 for u in ms if u != m)}
    out["UC5"] = s
    # UC6 and UC7 need transactions
    payer = collections.defaultdict(set)          # employer id -> customers paid via an account they own
    sent = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, ""]))  # acct -> competitor -> [count, last]
    for t in read(root, "bronze.transactions"):
        desc = t["description"]
        if t["txn_type_code"] in ("205", "206", "111") and (m := COMPETITOR.match(desc)) and t["direction"] == "DEBIT":
            v = sent[t["source_account_key"]][m.group(1)]
            v[0] += 1
            v[1] = max(v[1], t["post_date"])
        elif t["is_payroll"] == "Y" and (m := PAYROLL.match(desc)):
            for o in by_acct[t["source_account_key"]]:
                payer[m.group(2)].add(o["source_customer_key"])
    has_hy = {o["source_customer_key"] for o in own if acc[o["source_account_key"]]["product_code"] == "SAV-HY"}
    responders = {o["source_customer_key"] for o in own if acc[o["source_account_key"]]["product_code"] == "SAV-HY"
                  and acc[o["source_account_key"]]["open_date"] >= d180}
    s = set()
    for paid in payer.values():
        if paid & responders:
            s |= {c for c in paid if c in active and c not in has_hy and (paid & responders) - {c}}
    out["UC6"] = s
    s = set()
    for a, comps in sent.items():
        if any(n >= 2 and last >= d90 for n, last in comps.values()):
            s |= {o["source_customer_key"] for o in by_acct[a] if o["relationship_code"] in ("P", "J")
                  and o["source_customer_key"] in active}
    out["UC7"] = s
    return out


def graph_members(aud_dir: pathlib.Path) -> dict:
    got = {}
    for p in sorted(aud_dir.glob("UC*.csv")):
        with p.open() as fh:
            got[p.name.split("_")[0]] = {r["customer_id"] for r in csv.DictReader(fh)}
    return got


def answer_key_checks(root: pathlib.Path, got: dict) -> list:
    key = root / "_answer_key" / "planted_patterns.csv"
    if not key.exists():
        return []
    cust = {r["source_customer_key"]: r for r in read(root, "bronze.customers")}
    rows = list(csv.DictReader(key.open()))
    res = []
    heirs = set()
    for r in rows:
        if r["pattern"].startswith("ESTATE"):
            for k in (r["customer_key"], r["related_customer_key"]):
                if cust[k]["customer_status"] == "ACTIVE":
                    heirs.add(k)
    res.append(("UC3 finds the planted living heirs", len(heirs & got.get("UC3", set())), len(heirs)))
    young = set()
    as_of = date.fromisoformat(next(iter(cust.values()))["extract_dt"])
    for r in rows:
        if r["pattern"] == "NEXT_GEN":
            a, b = r["customer_key"], r["related_customer_key"]
            ya, yb = int(cust[a]["birth_year"][:4]), int(cust[b]["birth_year"][:4])
            y = a if ya > yb else b
            if cust[y]["customer_status"] == "ACTIVE" and as_of.year - int(cust[y]["birth_year"][:4]) <= 40:
                young.add(y)
    res.append(("UC4 finds the planted next-generation customers (<=40, active)", len(young & got.get("UC4", set())), len(young)))
    friends = [(r["customer_key"], r["related_customer_key"]) for r in rows if r["pattern"] == "FRIENDS_JOINT"]
    same = sum(1 for a, b in friends if (cust[a]["address_line1"], cust[a]["postal_code"]) == (cust[b]["address_line1"], cust[b]["postal_code"]))
    res.append(("friends sharing an account are NOT merged into one household", len(friends) - same, len(friends)))
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=pathlib.Path, required=True)
    ap.add_argument("--audiences", type=pathlib.Path, required=True)
    a = ap.parse_args(argv)
    exp, got = expected(a.data_dir), graph_members(a.audiences)
    ok = True
    for uc in sorted(exp):
        e, g = exp[uc], got.get(uc, set())
        match = e == g
        ok &= match
        print(f"{'OK  ' if match else 'DIFF'} {uc}: graph {len(g)}, independent {len(e)}"
              + ("" if match else f"  only-graph {sorted(g - e)[:3]} only-independent {sorted(e - g)[:3]}"))
    for name, hit, total in answer_key_checks(a.data_dir, got):
        good = hit == total
        ok &= good
        print(f"{'OK  ' if good else 'MISS'} {name}: {hit}/{total}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
