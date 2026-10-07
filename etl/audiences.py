"""Campaign audiences for the bank layer's marketing use cases 1-7 (docs/use-cases.md),
computed by Cypher inside the graph.

UC2 ("one message per household") is not a separate list: it is applied to
every audience before export. Whole households are held out as the control
group (so a campaign's effect can be measured against them), and one member
per household is marked household_primary for mail.

Dates are 'YYYY-MM-DD' strings, so string comparison orders them.
"""

import csv
import hashlib
import json
import pathlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

from etl.helpers import Engine, create_edges, lit

CONTROL_SHARE = 0.10


@dataclass(frozen=True)
class UseCase:
    code: str
    name: str
    campaign: str
    graph_need: str          # from the proposal: Essential / Helpful
    request_columns: str     # the request columns the use case reads
    caveat: str
    cypher: str              # returns customer_id, household_id, then reason fields
    reason: Callable


def use_cases(as_of: str) -> list:
    d = date.fromisoformat(as_of)
    d60, d90, d180 = ((d - timedelta(days=n)).isoformat() for n in (60, 90, 180))
    return [
        UseCase("UC1", "Household member left", "Retention", "Essential",
                "customers.address_line1, postal_code, customer_status; account_owners; accounts.close_date, close_reason_code",
                "Household = same address. 60-day window.",
                "MATCH (gone:Customer)-[:MEMBER_OF]->(h:Household)<-[:MEMBER_OF]-(c:Customer) "
                "WHERE gone.id <> c.id AND c.status = 'ACTIVE' AND gone.status = 'CLOSED' "
                "MATCH (gone)-[o:OWNS]->(a:Account) "
                f"WHERE o.role_code = 'P' AND a.close_reason_code = 'CUSTOMER_REQUEST' AND a.close_date >= '{d60}' "
                "RETURN c.id, h.id, max(a.close_date)",
                lambda r: f"Household member closed their accounts on {r[2]}"),
        UseCase("UC3", "Estate transition", "Retention", "Essential",
                "customers.customer_status = DECEASED; account_owners.relationship_code (P, J, B)",
                "The request has no date of death; compliance should approve timing and tone.",
                "MATCH (dead:Customer)-[o1:OWNS]->(a:Account)<-[o2:OWNS]-(heir:Customer) "
                "WHERE dead.status = 'DECEASED' AND heir.status = 'ACTIVE' AND o1.role_code = 'P' AND o2.role_code IN ['B', 'J'] "
                "RETURN heir.id, heir.household_id, o2.role",
                lambda r: f"Named {str(r[2]).lower()} on an account of a customer who has passed away"),
        UseCase("UC4", "Next generation", "Retention", "Essential",
                "customers.birth_year, city; account_owners (J, B); customer_change_events (ADDRESS)",
                "Selecting by age needs compliance review.",
                "MATCH (old:Customer)-[o1:OWNS]->(a:Account)<-[o2:OWNS]-(young:Customer) "
                "WHERE old.age >= 65 AND young.age <= 40 AND old.age - young.age >= 25 "
                "AND o2.role_code IN ['J', 'B'] AND young.status = 'ACTIVE' "
                "RETURN young.id, young.household_id, coalesce(young.last_address_change_dt, ''), young.city",
                lambda r: "Shares an account with a much older customer" + (f"; moved on {r[2]} to {r[3]}" if r[2] else "")),
        UseCase("UC5", "Household digital adoption", "Engagement", "Essential",
                "digital_sessions (login_success, login_timestamp); customers address",
                "'Never logged in' = no successful session in the history window.",
                "MATCH (u:Customer)-[:MEMBER_OF]->(h:Household)<-[:MEMBER_OF]-(c:Customer) "
                "WHERE u.id <> c.id AND u.logins_90d >= 4 AND c.digital_user = false AND c.status = 'ACTIVE' "
                "RETURN c.id, h.id, max(u.logins_90d)",
                lambda r: f"Another household member logged in {r[2]} times in the last 90 days"),
        UseCase("UC6", "Customers like past responders (proxy)", "Growth", "Essential",
                "accounts.product_code, open_date; transactions (payroll descriptions)",
                "PROXY: the request has no campaign-response data, so 'responders' = customers who opened "
                "High-Yield Savings in the last 180 days. Similarity = same employer.",
                "MATCH (r:Customer)-[:OWNS]->(n:Account) "
                f"WHERE n.product_code = 'SAV-HY' AND n.open_date >= '{d180}' "
                "MATCH (r)-[:OWNS]->(:Account)-[:PAID_BY]->(e:Counterparty)<-[:PAID_BY]-(:Account)<-[:OWNS]-(c:Customer) "
                "WHERE c.id <> r.id AND c.status = 'ACTIVE' "
                "AND NOT EXISTS { MATCH (c)-[:OWNS]->(x:Account) WHERE x.product_code = 'SAV-HY' } "
                "RETURN c.id, c.household_id, e.name, count(DISTINCT r)",
                lambda r: f"Paid by {r[2]}, like {r[3]} recent High-Yield Savings opener(s)"),
        UseCase("UC7", "Money leaving to competitors", "Retention", "Helpful",
                "transactions.description, txn_type_code, direction, post_date",
                "Competitor names are parsed from description text: the request has no routing or ACH fields.",
                "MATCH (c:Customer)-[o:OWNS]->(a:Account)-[s:SENDS_TO]->(k:Counterparty) "
                f"WHERE o.role_code IN ['P', 'J'] AND c.status = 'ACTIVE' AND s.count >= 2 AND s.last_date >= '{d90}' "
                "RETURN c.id, c.household_id, k.name, sum(s.total)",
                lambda r: f"Sent ${float(r[3]):,.0f} to {r[2]} over the history window"),
    ]


def finalise(code: str, members: dict, as_of: str) -> list:
    """UC2 on one audience: control group of whole households, and one
    household_primary per household. members: customer_id -> (household_id, reason)."""
    keys = sorted({h or f"solo:{c}" for c, (h, _) in members.items()})
    control = {k for k in keys if int(hashlib.sha1(f"{code}|{k}".encode()).hexdigest(), 16) % 100 < CONTROL_SHARE * 100}
    seen, out = set(), []
    for cid, (hid, why) in sorted(members.items()):
        k = hid or f"solo:{cid}"
        out.append({"customer_id": cid, "household_id": hid, "slice": "CONTROL" if k in control else "CAMPAIGN",
                    "household_primary": k not in seen, "reason": why, "as_of": as_of})
        seen.add(k)
    return out


def run(db: Engine, as_of: str, export_dir: pathlib.Path, log=print) -> list:
    export_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for uc in use_cases(as_of):
        members = {}
        for rec in db.q(uc.cypher):
            members.setdefault(rec[0], (rec[1], uc.reason(rec)))
        out = finalise(uc.code, members, as_of)
        aud = f"aud:{uc.code}:{as_of}"
        households = len({r["household_id"] or r["customer_id"] for r in out})
        db.q(f"CREATE (:Audience {{id: {lit(aud)}, use_case: {lit(uc.code)}, name: {lit(uc.name)}, campaign: {lit(uc.campaign)}, "
             f"as_of: {lit(as_of)}, customers: {len(out)}, households: {households}, synthetic: true}})")
        create_edges(db, "IN_AUDIENCE", [("Customer", r["customer_id"], "Audience", aud,
                                          {"slice": r["slice"], "reason": r["reason"], "household_primary": r["household_primary"]})
                                         for r in out])
        slug = uc.name.lower().replace("(", "").replace(")", "").replace(" ", "_")
        with (export_dir / f"{uc.code}_{slug}.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["customer_id", "household_id", "slice", "household_primary", "reason", "as_of"])
            w.writeheader()
            w.writerows(out)
        n_ctl = sum(r["slice"] == "CONTROL" for r in out)
        summary.append({"use_case": uc.code, "name": uc.name, "customers": len(out), "households": households,
                        "campaign": len(out) - n_ctl, "control": n_ctl})
        log(f"  {uc.code} {uc.name}: {len(out)} customers in {households} households ({n_ctl} held out)")
    (export_dir / "audience_summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary
