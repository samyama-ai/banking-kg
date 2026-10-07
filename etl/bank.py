"""Bank layer: one bank's own customers, built from the 26-table customer data request (synthetic).

    from etl.bank import build; g, as_of = build(data_dir / "bank_v1")

The bank is Banking-KG Bank, a fictional institution. Every row is synthetic: keys start `PATTERN-`,
`source_system` is `PATTERN_ONLY_GENERATOR`, emails are @example.com. Only request columns are read.
Contact fields (email, phone, street address) never enter the graph: audience exports carry customer_id
and are joined to contact details downstream, under the bank's own controls.

DERIVED parts carry derived: true and a `basis`:
  * Household     individuals sharing address_line1 + postal_code. A joint account between people at
                  different addresses is NOT a household.
  * Counterparty  competitor and employer names parsed from transaction descriptions (the request has no
                  ACH originator or routing fields), and lenders from credit_bureau_tradeline.lender_name.
  * SENDS_TO / RECEIVES_FROM / PAID_BY / SPENDS_AT  totals over the history window.

`CustomerLoan` is the bank's own loan record. It is NOT the market layer's `Loan`, which is a HMDA
origination; etl.bridge relates the two through the shared LoanProduct taxonomy.

A roll-up row that points at a customer the customers table does not contain is skipped and counted in
`graph.skipped[table]` rather than failing the build; the dataset's own validator
(validation_report_v1.json, checked by etl.loader) is the gate for referential integrity.
"""

import collections
import csv
import hashlib
import pathlib
import re
from datetime import date, timedelta

from etl.helpers import Graph
from etl.reference import MCC

COMPETITOR_RX = re.compile(r"^(?:EXT TRANSFER (?:TO|FROM)|WIRE TO) (.+?) X{4,}\d+$")
PAYROLL_RX = re.compile(r"^(.+?) PAYROLL PPD ID: (\d+)$")
COMPETITOR_TXN_CODES = ("205", "206", "111")  # external transfer out, external transfer in, outgoing wire
DEBIT = "DEBIT"
YES = "Y"
OWN_TRADELINE = "(THIS BANK)"  # a tradeline the bureau reports for the bank itself, not a competitor
CLOSED = "CLOSED"
INDIVIDUAL = "INDIVIDUAL"
LEDGER = "LEDGER"  # daily_balances.bal_type used for the latest balance
RECENT_LOGIN_DAYS = 90  # Customer.logins_90d window
DATE_CHARS = 10  # 'YYYY-MM-DD' prefix of a timestamp
BIRTH_YEAR_CHARS = 4
KEY_TAIL = 4  # last characters of a key shown in a node name, e.g. "Everyday Checking …5596"
HOUSEHOLD_HASH_CHARS = 12


def rows(root, entity):
    """Rows of one request table ('bronze.customers' -> root/bronze/customers.csv), '' read as None."""
    layer, name = entity.split(".", 1)
    path = root / layer / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - is {root} the bank's request tables (bank_v1)?")
    with path.open(newline="") as fh:
        for r in csv.DictReader(fh):
            yield {k: (v if v != "" else None) for k, v in r.items()}


def num(v):
    """v as a float, or None when it is missing."""
    return None if v is None else float(v)


def hh_id(addr, z):
    """Stable household id from address line 1 + postal code (sha1, not a security use)."""
    return "hh:" + hashlib.sha1(f"{addr}|{z}".encode(), usedforsecurity=False).hexdigest()[:HOUSEHOLD_HASH_CHARS]


def tail(key):
    """The last KEY_TAIL characters of a key, for a readable node name."""
    return key[-KEY_TAIL:]


def build(root: pathlib.Path):
    """(graph, as_of) for the bank layer read from root; as_of is the extract date of the customers table."""
    g = Graph()
    first = next(rows(root, "bronze.customers"), None)
    if first is None:
        raise ValueError(f"{root}/bronze/customers.csv has no rows")
    as_of = first["extract_dt"]
    add_products(g, root)
    add_customers(g, root, as_of)
    add_customer_rollups(g, root, as_of)
    add_accounts(g, root)
    add_transactions(g, root)
    add_loans(g, root)
    add_cards_and_lines(g, root)
    add_tradelines(g, root)
    return g, as_of


def add_products(g, root):
    """Product per product code; BusinessUnit per branch (isolated: the request cannot join it)."""
    for r in rows(root, "bronze.products"):
        g.node(
            "Product",
            f"prod:{r['product_code']}",
            code=r["product_code"],
            name=r["product_name"],
            product_type=r["product_type"],
            status=r["product_status_code"],
            description=r.get("description"),
        )
    for r in rows(root, "bronze.business_unit"):
        # the request says this joins to customers.branch, which it does not request: no edge can be made
        g.node(
            "BusinessUnit",
            f"bu:{r['source_business_unit_key']}",
            code=r["source_business_unit_key"],
            name=f"Branch {r['source_business_unit_key']} · {r['business_unit']}",
            business_unit=r["business_unit"],
            open_date=r["open_date"],
            close_date=r["close_date"],
            postal_code=r["postal_code"],
        )


def add_customers(g, root, as_of):
    """Customer per row (no contact fields), and Household per shared address of individuals."""
    households = {}
    year = date.fromisoformat(as_of).year
    for r in rows(root, "bronze.customers"):
        cid = r["source_customer_key"]
        birth = r["birth_year"]
        g.node(
            "Customer",
            cid,
            customer_type=r["customer_type"],
            status=r["customer_status"],
            birth_date=birth,
            age=(year - int(birth[:BIRTH_YEAR_CHARS])) if birth else None,
            annual_income=num(r["annual_income"]),
            business_unit=r["business_unit"],
            risk_ranking=r["risk_ranking"],
            retention=r["retention"],
            relationship_start_dt=r["relationship_start_dt"],
            last_contact_dt=r["last_contact_dt"],
            city=r["city"],
            state_code=r["state_code"],
            postal_code=r["postal_code"],
            name=r["customer_name"],
        )
        if r["customer_type"] == INDIVIDUAL and r["address_line1"]:
            households.setdefault((r["address_line1"], r["postal_code"]), []).append(cid)
    for (addr, z), members in households.items():
        hid = hh_id(addr, z)
        people = "1 person" if len(members) == 1 else f"{len(members)} people"
        g.node(
            "Household",
            hid,
            name=f"Household · {people} · {z}",
            size=len(members),
            postal_code=z,
            derived=True,
            basis="same address_line1 + postal_code",
        )
        for m in members:
            g.edge("MEMBER_OF", "Customer", m, "Household", hid, derived=True)
            g.nodes["Customer"][m]["household_id"] = hid


def customer(g, key, table):
    """The Customer node for key, or None (counted in g.skipped[table]) when the customers table lacks it."""
    c = g.nodes["Customer"].get(key)
    if c is None:
        g.skipped[table] += 1
    return c


def add_customer_rollups(g, root, as_of):
    """Per-customer roll-ups: last address change, deceased date, logins, latest credit score, receptiveness."""
    recent = (date.fromisoformat(as_of) - timedelta(days=RECENT_LOGIN_DAYS)).isoformat()
    for r in rows(root, "bronze.customer_change_events"):
        c = customer(g, r["source_customer_key"], "customer_change_events")
        if c is None:
            continue
        day = r["change_dt"][:DATE_CHARS]
        if r["data_ident"] == "ADDRESS" and day > c.get("last_address_change_dt", ""):
            c["last_address_change_dt"] = day
        if r["data_ident"] == "STATUS" and r["new_value"] == "DECEASED":
            c["deceased_reported_dt"] = day
    last_login, logins = {}, collections.Counter()
    for r in rows(root, "bronze.digital_sessions"):
        if r["login_success"] != YES:
            continue
        day, k = r["login_timestamp"][:DATE_CHARS], r["source_customer_key"]
        last_login[k] = max(last_login.get(k, day), day)
        if day > recent:
            logins[k] += 1
    for k, c in g.nodes["Customer"].items():
        c["logins_90d"] = logins.get(k, 0)
        c["digital_user"] = k in last_login
        if k in last_login:
            c["last_login"] = last_login[k]
    score = {}
    for r in rows(root, "bronze.credit_bureau"):
        k = r["source_customer_key"]
        if r["credit_score"] is not None and (k not in score or r["score_date"] > score[k][0]):
            score[k] = (r["score_date"], int(r["credit_score"]))
    for k, (dt, s) in score.items():
        if (c := customer(g, k, "credit_bureau")) is not None:
            c.update(credit_score=s, credit_score_date=dt)
    for r in rows(root, "bronze.crm_data"):
        if (c := customer(g, r["source_customer_key"], "crm_data")) is not None:
            c["receptiveness_score"] = num(r["receptiveness_score"])


def add_accounts(g, root):
    """Account per row (named after its product), OWNS per owner row, and each account's latest ledger balance."""
    for r in rows(root, "bronze.accounts"):
        aid = r["source_account_key"]
        product = g.nodes["Product"].get(f"prod:{r['product_code']}", {})
        g.node(
            "Account",
            aid,
            name=f"{product.get('name', r['account_type'])} …{tail(aid)}",
            account_type=r["account_type"],
            product_code=r["product_code"],
            status=r["account_status"],
            open_date=r["open_date"],
            close_date=r["close_date"],
            close_reason_code=r["close_reason_code"],
            rate=num(r["rate"]),
            naics=r["naics"],
            business_unit=r["business_unit"],
            last_activity_date=r["last_activity_date"],
        )
        g.edge("OF_PRODUCT", "Account", aid, "Product", f"prod:{r['product_code']}")
    for r in rows(root, "bronze.account_owners"):
        g.edge(
            "OWNS",
            "Customer",
            r["source_customer_key"],
            "Account",
            r["source_account_key"],
            role_code=r["relationship_code"],
            role=r["relationship_description"],
            primary=r["primary_owner_flag"] == YES,
            share=num(r["ownership_share"]),
        )
    bal = {}
    for r in rows(root, "bronze.daily_balances"):
        if r["bal_type"] == LEDGER:
            k = r["source_account_key"]
            if k not in bal or r["balance_date"] > bal[k][0]:
                bal[k] = (r["balance_date"], float(r["amt"]))
    for k, (dt, v) in bal.items():
        if k in g.nodes["Account"]:
            g.nodes["Account"][k].update(balance_latest=v, balance_date=dt)


def add_transactions(g, root):
    """Roll transactions up into SENDS_TO / RECEIVES_FROM (competitors), PAID_BY (employers) and SPENDS_AT (MCC)."""
    flows, spend = {}, {}
    for r in rows(root, "bronze.transactions"):
        acct, desc, day, amt = r["source_account_key"], r["description"] or "", r["post_date"], float(r["amount"] or 0)
        m = COMPETITOR_RX.match(desc) if r["txn_type_code"] in COMPETITOR_TXN_CODES else None
        if m:
            cp = "cp:comp:" + m.group(1).lower().replace(" ", "_")
            g.node("Counterparty", cp, name=m.group(1), kind="COMPETITOR", derived=True, basis="transaction description")
            rel = "SENDS_TO" if r["direction"] == DEBIT else "RECEIVES_FROM"
        elif r["is_payroll"] == YES and (m := PAYROLL_RX.match(desc)):
            cp = f"cp:emp:{m.group(2)}"
            g.node("Counterparty", cp, name=m.group(1), kind="EMPLOYER", derived=True, basis="payroll transaction description")
            rel = "PAID_BY"
        else:
            if r["mcc_code"] and r["direction"] == DEBIT:
                s = spend.setdefault((acct, r["mcc_code"]), [0, 0.0])
                s[0] += 1
                s[1] += amt
            continue
        f = flows.setdefault((rel, acct, cp), [0, 0.0, None, None])
        f[0] += 1
        f[1] += amt
        f[2] = min(f[2] or day, day)
        f[3] = max(f[3] or day, day)
    for (rel, acct, cp), (n, total, first, last) in flows.items():
        g.edge(rel, "Account", acct, "Counterparty", cp, count=n, total=round(total, 2), first_date=first, last_date=last, derived=True)
    for (acct, mcc), (n, total) in spend.items():
        g.node("MerchantCategory", f"mcc:{mcc}", mcc_code=mcc, name=MCC.get(mcc, f"MCC {mcc}"), description=MCC.get(mcc))
        g.edge("SPENDS_AT", "Account", acct, "MerchantCategory", f"mcc:{mcc}", count=n, total=round(total, 2), derived=True)


def add_loans(g, root):
    """CustomerLoan per loan (primary borrower only), and the Collateral securing it with its lien position."""
    for r in rows(root, "bronze.loans"):
        lid = r["source_loan_key"]
        g.node(
            "CustomerLoan",
            lid,
            name=f"{r['product name'] or r['loan_type']} loan …{tail(lid)}",
            loan_type=r["loan_type"],
            product_code=r.get("product_code"),
            status=r["status"],
            principal_balance=num(r["principal_balance"]),
            original_loan_amount=num(r.get("original_loan_amount")),
            term_months=num(r.get("term_months")),
            current_interest_rate=num(r["current_interest_rate"]),
            rate_type=r["rate_type"],
            origination_date=r["origination_date"],
            maturity_date=r["maturity_date"],
            next_rate_change_date=r["next_rate_change_date"],
            product_name=r["product name"],
            delinquent_days=num(r.get("delinquent_days")),
            original_credit_score=num(r.get("original_credit_score")),
        )
        g.edge("HAS_LOAN", "Account", r["source_account_key"], "CustomerLoan", lid)
        g.edge(
            "BORROWS", "Customer", r["source_customer_key"], "CustomerLoan", lid, basis="loans.source_customer_key (no co-borrowers in the request)"
        )
    for r in rows(root, "bronze.loan_collateral"):
        cid = r["source_collateral_key"]
        g.node(
            "Collateral",
            cid,
            name=f"{r['property_type'] or r['collateral_type']} collateral …{tail(cid)}",
            collateral_type=r["collateral_type"],
            property_postal_code=r["property_postal_code"],
            property_state=r.get("property_state_code"),
            property_type=r["property_type"],
            collateral_value=num(r["collateral_value"]),
        )
        g.edge(
            "SECURED_BY",
            "CustomerLoan",
            r["source_loan_key"],
            "Collateral",
            cid,
            lien_position=int(r["lien_position"]) if r["lien_position"] else None,
        )


def add_cards_and_lines(g, root):
    """CreditLine and Card nodes. Debit cards link to their account only: the request carries no cardholder."""
    for r in rows(root, "bronze.credit_lines"):
        k = r["source_credit_line_key"]
        g.node("CreditLine", k, name=f"Credit line …{tail(k)}", credit_limit=num(r["credit_limit"]), current_balance=num(r["current_balance"]))
        g.edge("HAS_CREDIT_LINE", "Account", r["source_account_key"], "CreditLine", k)
    for r in rows(root, "bronze.debit_cards"):
        k = r["source_card_key"]
        g.node("Card", k, name=f"DEBIT card …{tail(k)}", card_kind="DEBIT", card_status=r["card_status"], card_tier=r["card_tier"])
        g.edge("HAS_CARD", "Account", r["source_account_key"], "Card", k)
    for r in rows(root, "bronze.credit_cards"):
        k = r["source_card_key"]
        g.node(
            "Card",
            k,
            name=f"CREDIT card …{tail(k)}",
            card_kind="CREDIT",
            card_status=r["card_status"],
            card_tier=r["card_tier"],
            credit_limit=num(r["credit_limit"]),
            current_balance=num(r["current_balance"]),
        )
        g.edge("HAS_CARD", "Account", r["source_account_key"], "Card", k)
        g.edge("HOLDS_CARD", "Customer", r["source_customer_key"], "Card", k)


def add_tradelines(g, root):
    """OWES from a customer to each other lender holding an open tradeline (the bank's own tradelines skipped)."""
    for r in rows(root, "bronze.credit_bureau_tradeline"):
        name = r["lender_name"] or ""
        if not name or name.endswith(OWN_TRADELINE) or r["status"] == CLOSED:
            continue
        cp = "cp:lender:" + name.lower().replace(" ", "_")
        g.node("Counterparty", cp, name=name, kind="LENDER", derived=True, basis="credit_bureau_tradeline.lender_name")
        g.edge(
            "OWES",
            "Customer",
            r["source_customer_key"],
            "Counterparty",
            cp,
            account_type=r["account_type"],
            balance=num(r["balance"]),
            monthly_payment=num(r["monthly_payment"]),
            opened_date=r["opened_date"],
        )
