"""Campaign audiences for the bank layer's marketing use cases 1-7 (docs/use-cases.md),
computed by Cypher inside the graph.

UC2 ("one message per household") is not a separate list: it is applied to every audience before export.
Whole households are held out as the control group (so a campaign's effect can be measured against them),
and one member per household is marked household_primary for mail.

Every threshold is a named constant below; etl.verify imports the same names, so the independent
recalculation can never drift from the rules the graph applies. Dates are 'YYYY-MM-DD' strings, so string
comparison orders them (the engine has no date functions).
"""

import csv
import hashlib
import json
import pathlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from etl.helpers import Engine, create_edges, csv_safe, lit

# ---------------------------------------------------------------- rules (shared with etl.verify)
LEFT_WINDOW_DAYS = 60  # UC1: a household member closed their accounts this recently
RECENT_DAYS = 90  # UC5 login window (Customer.logins_90d), UC7 transfer recency
RESPONDER_WINDOW_DAYS = 180  # UC6: "responders" opened the product this recently
OLDER_AGE, YOUNGER_AGE, GENERATION_GAP = 65, 40, 25  # UC4
ACTIVE_LOGINS = 4  # UC5: logins in RECENT_DAYS that make a household member "active online"
MIN_TRANSFERS = 2  # UC7: transfers to one competitor that make a pattern, not a one-off
RESPONDER_PRODUCT = "SAV-HY"  # UC6: High-Yield Savings
PRIMARY = "P"  # account_owners.relationship_code
HEIR_ROLES = ("B", "J")  # UC3: beneficiary, joint
NEXT_GEN_ROLES = ("J", "B")  # UC4: joint, beneficiary
SENDER_ROLES = ("P", "J")  # UC7: primary, joint
ACTIVE, CLOSED, DECEASED = "ACTIVE", "CLOSED", "DECEASED"
CUSTOMER_REQUEST = "CUSTOMER_REQUEST"  # accounts.close_reason_code
# ---------------------------------------------------------------- UC2
CONTROL_SHARE = 0.10  # share of households held out of every campaign
PERCENT = 100
CAMPAIGN, CONTROL = "CAMPAIGN", "CONTROL"
EXPORT_FIELDS = ["customer_id", "household_id", "slice", "household_primary", "reason", "as_of"]


@dataclass(frozen=True)
class UseCase:
    """One campaign audience: what it is for, what it reads, and the Cypher that selects it."""

    code: str
    name: str
    campaign: str
    graph_need: str  # Essential / Helpful
    request_columns: str  # the request columns the use case reads
    caveat: str
    cypher: str  # returns customer_id, household_id, then reason fields
    reason: Callable  # Cypher row -> the plain-English reason stored on IN_AUDIENCE


def cypher_list(xs) -> str:
    """A Cypher list literal, e.g. ['B', 'J']."""
    return "[" + ", ".join(lit(x) for x in xs) + "]"


def days_before(as_of: str, n: int) -> str:
    """The 'YYYY-MM-DD' date n days before as_of."""
    return (date.fromisoformat(as_of) - timedelta(days=n)).isoformat()


def use_cases(as_of: str) -> list:
    """The six audiences (UC1, UC3-UC7) with their windows fixed relative to as_of."""
    left, recent, responders = (days_before(as_of, n) for n in (LEFT_WINDOW_DAYS, RECENT_DAYS, RESPONDER_WINDOW_DAYS))
    return [
        UseCase(
            "UC1",
            "Household member left",
            "Retention",
            "Essential",
            "customers.address_line1, postal_code, customer_status; account_owners; accounts.close_date, close_reason_code",
            f"Household = same address. {LEFT_WINDOW_DAYS}-day window.",
            "MATCH (gone:Customer)-[:MEMBER_OF]->(h:Household)<-[:MEMBER_OF]-(c:Customer) "
            f"WHERE gone.id <> c.id AND c.status = {lit(ACTIVE)} AND gone.status = {lit(CLOSED)} "
            "MATCH (gone)-[o:OWNS]->(a:Account) "
            f"WHERE o.role_code = {lit(PRIMARY)} AND a.close_reason_code = {lit(CUSTOMER_REQUEST)} AND a.close_date >= {lit(left)} "
            "RETURN c.id, h.id, max(a.close_date)",
            lambda r: f"Household member closed their accounts on {r[2]}",
        ),
        UseCase(
            "UC3",
            "Estate transition",
            "Retention",
            "Essential",
            "customers.customer_status = DECEASED; account_owners.relationship_code (P, J, B)",
            "The request has no date of death; compliance should approve timing and tone.",
            "MATCH (dead:Customer)-[o1:OWNS]->(a:Account)<-[o2:OWNS]-(heir:Customer) "
            f"WHERE dead.status = {lit(DECEASED)} AND heir.status = {lit(ACTIVE)} AND o1.role_code = {lit(PRIMARY)} "
            f"AND o2.role_code IN {cypher_list(HEIR_ROLES)} "
            "RETURN heir.id, heir.household_id, o2.role",
            lambda r: f"Named {str(r[2]).lower()} on an account of a customer who has passed away",
        ),
        UseCase(
            "UC4",
            "Next generation",
            "Retention",
            "Essential",
            "customers.birth_year, city; account_owners (J, B); customer_change_events (ADDRESS)",
            "Selecting by age needs compliance review.",
            "MATCH (old:Customer)-[o1:OWNS]->(a:Account)<-[o2:OWNS]-(young:Customer) "
            f"WHERE old.age >= {OLDER_AGE} AND young.age <= {YOUNGER_AGE} AND old.age - young.age >= {GENERATION_GAP} "
            f"AND o2.role_code IN {cypher_list(NEXT_GEN_ROLES)} AND young.status = {lit(ACTIVE)} "
            "RETURN young.id, young.household_id, coalesce(young.last_address_change_dt, ''), young.city",
            lambda r: "Shares an account with a much older customer" + (f"; moved on {r[2]} to {r[3]}" if r[2] else ""),
        ),
        UseCase(
            "UC5",
            "Household digital adoption",
            "Engagement",
            "Essential",
            "digital_sessions (login_success, login_timestamp); customers address",
            "'Never logged in' = no successful session in the history window.",
            "MATCH (u:Customer)-[:MEMBER_OF]->(h:Household)<-[:MEMBER_OF]-(c:Customer) "
            f"WHERE u.id <> c.id AND u.logins_90d >= {ACTIVE_LOGINS} AND c.digital_user = false AND c.status = {lit(ACTIVE)} "
            "RETURN c.id, h.id, max(u.logins_90d)",
            lambda r: f"Another household member logged in {r[2]} times in the last {RECENT_DAYS} days",
        ),
        UseCase(
            "UC6",
            "Customers like past responders (proxy)",
            "Growth",
            "Essential",
            "accounts.product_code, open_date; transactions (payroll descriptions)",
            "PROXY: the request has no campaign-response data, so 'responders' = customers who opened "
            f"High-Yield Savings in the last {RESPONDER_WINDOW_DAYS} days. Similarity = same employer.",
            "MATCH (r:Customer)-[:OWNS]->(n:Account) "
            f"WHERE n.product_code = {lit(RESPONDER_PRODUCT)} AND n.open_date >= {lit(responders)} "
            "MATCH (r)-[:OWNS]->(:Account)-[:PAID_BY]->(e:Counterparty)<-[:PAID_BY]-(:Account)<-[:OWNS]-(c:Customer) "
            f"WHERE c.id <> r.id AND c.status = {lit(ACTIVE)} "
            f"AND NOT EXISTS {{ MATCH (c)-[:OWNS]->(x:Account) WHERE x.product_code = {lit(RESPONDER_PRODUCT)} }} "
            "RETURN c.id, c.household_id, e.name, count(DISTINCT r)",
            lambda r: f"Paid by {r[2]}, like {r[3]} recent High-Yield Savings opener(s)",
        ),
        UseCase(
            "UC7",
            "Money leaving to competitors",
            "Retention",
            "Helpful",
            "transactions.description, txn_type_code, direction, post_date",
            "Competitor names are parsed from description text: the request has no routing or ACH fields.",
            "MATCH (c:Customer)-[o:OWNS]->(a:Account)-[s:SENDS_TO]->(k:Counterparty) "
            f"WHERE o.role_code IN {cypher_list(SENDER_ROLES)} AND c.status = {lit(ACTIVE)} AND s.count >= {MIN_TRANSFERS} "
            f"AND s.last_date >= {lit(recent)} "
            "RETURN c.id, c.household_id, k.name, sum(s.total)",
            lambda r: f"Sent ${float(r[3]):,.0f} to {r[2]} over the history window",
        ),
    ]


def held_out(code: str, household_key: str) -> bool:
    """Whether a household is in the control group of one audience: a stable hash, so reruns agree."""
    h = int(hashlib.sha1(f"{code}|{household_key}".encode(), usedforsecurity=False).hexdigest(), 16)
    return h % PERCENT < CONTROL_SHARE * PERCENT


def finalise(code: str, members: dict, as_of: str) -> list:
    """UC2 on one audience: control group of whole households, and one
    household_primary per household. members: customer_id -> (household_id, reason)."""
    seen, out = set(), []
    for cid, (hid, why) in sorted(members.items()):
        k = hid or f"solo:{cid}"
        out.append(
            {
                "customer_id": cid,
                "household_id": hid,
                "slice": CONTROL if held_out(code, k) else CAMPAIGN,
                "household_primary": k not in seen,
                "reason": why,
                "as_of": as_of,
            }
        )
        seen.add(k)
    return out


def file_name(uc: UseCase) -> str:
    """The export file for an audience, e.g. UC6_customers_like_past_responders_proxy.csv."""
    return f"{uc.code}_" + uc.name.lower().replace("(", "").replace(")", "").replace(" ", "_") + ".csv"


def export(path: pathlib.Path, rows: list):
    """Write one audience CSV; text cells are made safe to open in a spreadsheet."""
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=EXPORT_FIELDS)
        w.writeheader()
        w.writerows({k: csv_safe(v) for k, v in r.items()} for r in rows)


def run(db: Engine, as_of: str, export_dir: pathlib.Path, log=print) -> list:
    """Compute every audience in the graph, write Audience + IN_AUDIENCE, export CSVs and a summary."""
    export_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for uc in use_cases(as_of):
        members = {}
        for rec in db.q(uc.cypher):
            members.setdefault(rec[0], (rec[1], uc.reason(rec)))
        out = finalise(uc.code, members, as_of)
        aud = f"aud:{uc.code}:{as_of}"
        households = len({r["household_id"] or r["customer_id"] for r in out})
        db.q(
            f"CREATE (:Audience {{id: {lit(aud)}, use_case: {lit(uc.code)}, name: {lit(uc.name)}, campaign: {lit(uc.campaign)}, "
            f"as_of: {lit(as_of)}, customers: {len(out)}, households: {households}, synthetic: true}})"
        )
        create_edges(
            db,
            "IN_AUDIENCE",
            [
                (
                    "Customer",
                    r["customer_id"],
                    "Audience",
                    aud,
                    {"slice": r["slice"], "reason": r["reason"], "household_primary": r["household_primary"]},
                )
                for r in out
            ],
        )
        export(export_dir / file_name(uc), out)
        n_ctl = sum(r["slice"] == CONTROL for r in out)
        summary.append(
            {"use_case": uc.code, "name": uc.name, "customers": len(out), "households": households, "campaign": len(out) - n_ctl, "control": n_ctl}
        )
        log(f"  {uc.code} {uc.name}: {len(out)} customers in {households} households ({n_ctl} held out)")
    (export_dir / "audience_summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary
