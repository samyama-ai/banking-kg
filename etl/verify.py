"""Check the graph's audiences against an independent calculation.

    python -m etl.verify --data-dir ../data/banking-kg/bank_v1 --audiences ../data/banking-kg/audiences

Every use case is recomputed here in plain Python straight from the request CSVs, WITHOUT etl.bank or the
engine, and compared member-for-member with the CSV the graph exported. A difference means a Cypher bug,
an engine quirk or a build bug; it is never papered over.

What is shared and what is not: the *rules* (windows, ages, roles, thresholds) are imported from
etl.audiences, because they are the specification both sides must follow. The *implementation* — reading
the tables, parsing descriptions, forming households — is deliberately written again here, so a bug in
etl.bank cannot hide itself.

If the dataset has an answer key (_answer_key/planted_patterns.csv from the pattern planter), the estate
and next-generation audiences are also checked for recall of the planted heirs and children, and the
friends-sharing-an-account pattern is checked NOT to have been merged into a household.

Exit code: 0 when everything matches, 1 on any difference, 2 when the inputs cannot be read.
"""

import argparse
import collections
import csv
import pathlib
import re
import sys
from datetime import date

from etl import config
from etl.audiences import (
    ACTIVE,
    ACTIVE_LOGINS,
    CLOSED,
    CUSTOMER_REQUEST,
    DECEASED,
    GENERATION_GAP,
    HEIR_ROLES,
    LEFT_WINDOW_DAYS,
    MIN_TRANSFERS,
    NEXT_GEN_ROLES,
    OLDER_AGE,
    PRIMARY,
    RECENT_DAYS,
    RESPONDER_PRODUCT,
    RESPONDER_WINDOW_DAYS,
    SENDER_ROLES,
    YOUNGER_AGE,
    days_before,
)

# written independently of etl.bank on purpose (see the module docstring)
COMPETITOR = re.compile(r"^(?:EXT TRANSFER (?:TO|FROM)|WIRE TO) (.+?) X{4,}\d+$")
PAYROLL = re.compile(r"^(.+?) PAYROLL PPD ID: (\d+)$")
COMPETITOR_TXN_CODES = ("205", "206", "111")
DATE_CHARS, BIRTH_YEAR_CHARS = 10, 4
SAMPLE = 3  # ids shown per side when an audience differs
EXIT_OK, EXIT_DIFF, EXIT_INPUT = 0, 1, 2


def read(root, entity):
    """Stream the rows of one request table ('bronze.customers' -> root/bronze/customers.csv)."""
    layer, name = entity.split(".", 1)
    path = root / layer / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    with path.open(newline="") as fh:
        yield from csv.DictReader(fh)


def birth_year(r):
    """Birth year from customers.birth_year, or None."""
    return int(r["birth_year"][:BIRTH_YEAR_CHARS]) if r["birth_year"] else None


def expected(root: pathlib.Path) -> dict:
    """{use case code: set of customer ids} recomputed from the CSVs alone."""
    cust = {r["source_customer_key"]: r for r in read(root, "bronze.customers")}
    if not cust:
        raise ValueError(f"{root}/bronze/customers.csv has no rows")
    as_of = next(iter(cust.values()))["extract_dt"]
    year = date.fromisoformat(as_of).year
    left, recent, responder_since = (days_before(as_of, n) for n in (LEFT_WINDOW_DAYS, RECENT_DAYS, RESPONDER_WINDOW_DAYS))
    age = {k: (year - by) if (by := birth_year(r)) is not None else None for k, r in cust.items()}
    hh, members = {}, collections.defaultdict(set)
    for k, r in cust.items():
        if r["customer_type"] == "INDIVIDUAL" and r["address_line1"]:
            hh[k] = (r["address_line1"], r["postal_code"])
            members[hh[k]].add(k)
    acc = {r["source_account_key"]: r for r in read(root, "bronze.accounts")}
    own = list(read(root, "bronze.account_owners"))
    by_acct, by_cust = collections.defaultdict(list), collections.defaultdict(list)
    for o in own:
        by_acct[o["source_account_key"]].append(o)
        by_cust[o["source_customer_key"]].append(o)
    active = {k for k, r in cust.items() if r["customer_status"] == ACTIVE}
    out = {}

    # UC1: active members of a household where another member closed their primary accounts recently
    s = set()
    for k, r in cust.items():
        if r["customer_status"] != CLOSED or k not in hh:
            continue
        left_accounts = [acc[o["source_account_key"]] for o in by_cust[k] if o["relationship_code"] == PRIMARY]
        if any(a["close_reason_code"] == CUSTOMER_REQUEST and (a["close_date"] or "") >= left for a in left_accounts):
            s |= {m for m in members[hh[k]] if m != k and m in active}
    out["UC1"] = s
    # UC3: living joint owners / beneficiaries on a deceased primary owner's account
    s = set()
    for os_ in by_acct.values():
        if any(o["relationship_code"] == PRIMARY and cust[o["source_customer_key"]]["customer_status"] == DECEASED for o in os_):
            s |= {o["source_customer_key"] for o in os_ if o["relationship_code"] in HEIR_ROLES and o["source_customer_key"] in active}
    out["UC3"] = s
    # UC4: much younger joint owners / beneficiaries on an older customer's account
    s = set()
    for os_ in by_acct.values():
        olds = [o["source_customer_key"] for o in os_ if (age.get(o["source_customer_key"]) or 0) >= OLDER_AGE]
        for o in os_:
            y = o["source_customer_key"]
            if (
                o["relationship_code"] in NEXT_GEN_ROLES
                and y in active
                and age.get(y) is not None
                and age[y] <= YOUNGER_AGE
                and any(age[x] - age[y] >= GENERATION_GAP for x in olds if x != y)
            ):
                s.add(y)
    out["UC4"] = s
    # UC5: never logged in, living with someone active online
    logins, ever = collections.Counter(), set()
    for r in read(root, "bronze.digital_sessions"):
        if r["login_success"] == "Y":
            ever.add(r["source_customer_key"])
            if r["login_timestamp"][:DATE_CHARS] > recent:
                logins[r["source_customer_key"]] += 1
    s = set()
    for ms in members.values():
        s |= {m for m in ms if m not in ever and m in active and any(logins[u] >= ACTIVE_LOGINS for u in ms if u != m)}
    out["UC5"] = s
    # UC6 and UC7 need one pass over transactions
    payer = collections.defaultdict(set)  # employer id -> customers paid into an account they own
    sent = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, ""]))  # acct -> competitor -> [count, last]
    for t in read(root, "bronze.transactions"):
        desc = t["description"]
        if t["txn_type_code"] in COMPETITOR_TXN_CODES and (m := COMPETITOR.match(desc)) and t["direction"] == "DEBIT":
            v = sent[t["source_account_key"]][m.group(1)]
            v[0] += 1
            v[1] = max(v[1], t["post_date"])
        elif t["is_payroll"] == "Y" and (m := PAYROLL.match(desc)):
            for o in by_acct[t["source_account_key"]]:
                payer[m.group(2)].add(o["source_customer_key"])
    has_product = {o["source_customer_key"] for o in own if acc[o["source_account_key"]]["product_code"] == RESPONDER_PRODUCT}
    responders = {
        o["source_customer_key"]
        for o in own
        if acc[o["source_account_key"]]["product_code"] == RESPONDER_PRODUCT and acc[o["source_account_key"]]["open_date"] >= responder_since
    }
    s = set()
    for paid in payer.values():
        if paid & responders:
            s |= {c for c in paid if c in active and c not in has_product and (paid & responders) - {c}}
    out["UC6"] = s
    s = set()
    for a, comps in sent.items():
        if any(n >= MIN_TRANSFERS and last >= recent for n, last in comps.values()):
            s |= {o["source_customer_key"] for o in by_acct[a] if o["relationship_code"] in SENDER_ROLES and o["source_customer_key"] in active}
    out["UC7"] = s
    return out


def graph_members(aud_dir: pathlib.Path) -> dict:
    """{use case code: set of customer ids} from the CSVs the loader exported."""
    if not aud_dir.is_dir():
        raise FileNotFoundError(f"{aud_dir} not found - run etl.loader with the bank layer first")
    got = {}
    for p in sorted(aud_dir.glob("UC*.csv")):
        with p.open(newline="") as fh:
            got[p.name.split("_")[0]] = {r["customer_id"] for r in csv.DictReader(fh)}
    return got


def answer_key_checks(root: pathlib.Path, got: dict) -> list:
    """[(check, found, planted)] against _answer_key/planted_patterns.csv; [] when the dataset has no key."""
    key = root / "_answer_key" / "planted_patterns.csv"
    if not key.exists():
        return []
    cust = {r["source_customer_key"]: r for r in read(root, "bronze.customers")}
    with key.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    year = date.fromisoformat(next(iter(cust.values()))["extract_dt"]).year
    heirs = {
        k
        for r in rows
        if r["pattern"].startswith("ESTATE")
        for k in (r["customer_key"], r["related_customer_key"])
        if cust[k]["customer_status"] == ACTIVE
    }
    young = set()
    for r in rows:
        if r["pattern"] == "NEXT_GEN":
            a, b = r["customer_key"], r["related_customer_key"]
            y = a if birth_year(cust[a]) > birth_year(cust[b]) else b
            if cust[y]["customer_status"] == ACTIVE and year - birth_year(cust[y]) <= YOUNGER_AGE:
                young.add(y)
    friends = [(r["customer_key"], r["related_customer_key"]) for r in rows if r["pattern"] == "FRIENDS_JOINT"]
    same = sum(1 for a, b in friends if (cust[a]["address_line1"], cust[a]["postal_code"]) == (cust[b]["address_line1"], cust[b]["postal_code"]))
    return [
        ("UC3 finds the planted living heirs", len(heirs & got.get("UC3", set())), len(heirs)),
        (f"UC4 finds the planted next-generation customers (<={YOUNGER_AGE}, active)", len(young & got.get("UC4", set())), len(young)),
        ("friends sharing an account are NOT merged into one household", len(friends) - same, len(friends)),
    ]


def compare(exp: dict, got: dict, checks: list, log=print) -> bool:
    """Print one line per audience and per answer-key check; True when everything agrees."""
    ok = True
    for uc in sorted(exp):
        e, g = exp[uc], got.get(uc, set())
        match = e == g
        ok &= match
        log(
            f"{'OK  ' if match else 'DIFF'} {uc}: graph {len(g)}, independent {len(e)}"
            + ("" if match else f"  only-graph {sorted(g - e)[:SAMPLE]} only-independent {sorted(e - g)[:SAMPLE]}")
        )
    for name, hit, total in checks:
        good = hit == total
        ok &= good
        log(f"{'OK  ' if good else 'MISS'} {name}: {hit}/{total}")
    return ok


def main(argv=None):
    """CLI entry point; returns the process exit code."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=pathlib.Path, default=config.DATA_DIR / config.BANK_DIR_NAME)
    ap.add_argument("--audiences", type=pathlib.Path, default=config.DATA_DIR / config.AUDIENCE_DIR_NAME)
    a = ap.parse_args(argv)
    try:
        exp, got = expected(a.data_dir), graph_members(a.audiences)
        checks = answer_key_checks(a.data_dir, got)
    except (FileNotFoundError, ValueError, KeyError) as e:
        print(f"verify: cannot read inputs: {e}", file=sys.stderr)
        return EXIT_INPUT
    return EXIT_OK if compare(exp, got, checks) else EXIT_DIFF


if __name__ == "__main__":
    sys.exit(main())
