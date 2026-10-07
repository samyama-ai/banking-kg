"""A hand-built miniature of the bank's request tables in which every use case has a known answer.

As of 2026-08-31.
  C1 Alice (b.1950, ACTIVE)  -- lives at 1 Oak St with C2 and C6; logs in often
  C2 Bob   (b.1952, CLOSED)  -- same household; closed his checking 2026-08-01 at his request   -> UC1 {C1, C6}
  C3 Dan   (b.1995, ACTIVE)  -- joint owner on Alice's savings, lives elsewhere, moved 2026-07-15 -> UC4 {C3}
                              -- sends money to NORTHSTAR FED twice in 90 days                   -> UC7 {C3}
  C4 Eve   (b.1940, DECEASED)-- primary on an account where C5 is BENEFICIARY                   -> UC3 {C5}, and UC4
  C5 Fay   (b.1990, ACTIVE)  -- opened High-Yield Savings 2026-07-01; paid by ACME
  C6 Gus   (b.1985, ACTIVE)  -- in Alice's household, never logged in                           -> UC5 {C6}
                              -- paid by ACME like Fay, has no High-Yield Savings                -> UC6 {C6}
  C7 Hal / C8 Ivy -- friends sharing a savings account at different addresses: NOT one household
"""

import csv
import pathlib

AS_OF = "2026-08-31"


def _w(root, entity, rows, cols):
    layer, name = entity.split(".", 1)
    p = root / layer / f"{name}.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def cust(k, name, born, status, addr, z, city="Richmond", ctype="INDIVIDUAL"):
    return {"source_customer_key": k, "customer_name": name, "birth_year": f"{born}-06-01", "customer_status": status,
            "customer_type": ctype, "address_line1": addr, "postal_code": z, "city": city, "state_code": "VA",
            "extract_dt": AS_OF, "relationship_start_dt": "2010-01-01", "business_unit": "RETAIL", "risk_ranking": "1", "retention": "R0"}


def acct(k, owner, product, opened="2015-01-01", closed="", reason="", atype="DDA"):
    return {"source_account_key": k, "source_customer_key": owner, "product_code": product, "account_type": atype,
            "account_status": "CLOSED" if closed else "ACTIVE", "open_date": opened, "close_date": closed,
            "close_reason_code": reason, "rate": "0.010000", "business_unit": "RETAIL", "last_activity_date": AS_OF}


def own(a, c, code):
    desc = {"P": "PRIMARY", "J": "JOINT", "B": "BENEFICIARY"}[code]
    return {"source_account_key": a, "source_customer_key": c, "relationship_code": code, "relationship_description": desc,
            "primary_owner_flag": "Y" if code == "P" else "N", "ownership_share": "1.0000" if code == "P" else ""}


def txn(a, day, code, amount, desc, direction="DEBIT", payroll="N", mcc=""):
    return {"source_account_key": a, "post_date": day, "txn_type_code": code, "amount": amount, "description": desc,
            "direction": direction, "is_payroll": payroll, "mcc_code": mcc}


def write_fixture(root: pathlib.Path) -> pathlib.Path:
    customers = [cust("C1", "Alice Oak", 1950, "ACTIVE", "1 Oak St", "23220"),
                 cust("C2", "Bob Oak", 1952, "CLOSED", "1 Oak St", "23220"),
                 cust("C3", "Dan Elm", 1995, "ACTIVE", "9 Elm St", "22201", city="Arlington"),
                 cust("C4", "Eve Pine", 1940, "DECEASED", "5 Pine Rd", "23111"),
                 cust("C5", "Fay Ash", 1990, "ACTIVE", "7 Ash Ln", "23113"),
                 cust("C6", "Gus Oak", 1985, "ACTIVE", "1 Oak St", "23220"),
                 cust("C7", "Hal Birch", 1970, "ACTIVE", "3 Birch Ct", "23060"),
                 cust("C8", "Ivy Cedar", 1971, "ACTIVE", "8 Cedar Dr", "23225")]
    accounts = [acct("A1", "C1", "SAV-STD", atype="SAV"), acct("A2", "C2", "CHK-BASIC", closed="2026-08-01", reason="CUSTOMER_REQUEST"),
                acct("A3", "C3", "CHK-BASIC"), acct("A4", "C4", "CD-12", atype="CD"),
                acct("A5", "C5", "SAV-HY", opened="2026-07-01", atype="SAV"), acct("A6", "C5", "CHK-BASIC"),
                acct("A7", "C6", "CHK-BASIC"), acct("A8", "C7", "SAV-STD", atype="SAV")]
    owners = [own("A1", "C1", "P"), own("A1", "C3", "J"), own("A2", "C2", "P"), own("A3", "C3", "P"), own("A4", "C4", "P"),
              own("A4", "C5", "B"), own("A5", "C5", "P"), own("A6", "C5", "P"), own("A7", "C6", "P"), own("A8", "C7", "P"),
              own("A8", "C8", "J")]
    txns = [txn("A3", "2026-07-10", "205", "1500.00", "EXT TRANSFER TO NORTHSTAR FED XXXXXX1234"),
            txn("A3", "2026-08-10", "205", "900.00", "EXT TRANSFER TO NORTHSTAR FED XXXXXX5678"),
            txn("A6", "2026-08-14", "101", "2100.00", "ACME CORP PAYROLL PPD ID: 111", "CREDIT", "Y"),
            txn("A7", "2026-08-14", "101", "1900.00", "ACME CORP PAYROLL PPD ID: 111", "CREDIT", "Y"),
            txn("A7", "2026-08-20", "201", "42.10", "POS PURCHASE FRESHWAY MARKET", mcc="5411")]
    sessions = [{"source_session_key": f"S{i}", "source_customer_key": "C1", "source_account_key": "A1", "login_success": "Y",
                 "login_timestamp": f"2026-08-{10 + i:02d} 09:00:00+00:00"} for i in range(5)]
    _w(root, "bronze.customers", customers, list(customers[0]) + ["annual_income", "last_contact_dt"])
    _w(root, "bronze.accounts", accounts, list(accounts[0]) + ["naics"])
    _w(root, "bronze.account_owners", owners, list(owners[0]))
    _w(root, "bronze.transactions", txns, list(txns[0]))
    _w(root, "bronze.digital_sessions", sessions, list(sessions[0]))
    _w(root, "bronze.customer_change_events",
       [{"source_customer_key": "C3", "change_dt": "2026-07-15 10:00:00+00:00", "data_ident": "ADDRESS", "new_value": "9 Elm St"}],
       ["source_customer_key", "change_dt", "data_ident", "new_value"])
    _w(root, "bronze.products", [{"product_code": p, "product_name": p, "product_type": "DDA", "product_status_code": "A"}
                                 for p in ("SAV-STD", "CHK-BASIC", "CD-12", "SAV-HY")],
       ["product_code", "product_name", "product_type", "product_status_code"])
    empty = {"bronze.business_unit": ["source_business_unit_key", "business_unit", "open_date", "close_date", "postal_code"],
             "bronze.credit_bureau": ["source_customer_key", "score_date", "credit_score"],
             "bronze.crm_data": ["source_customer_key", "receptiveness_score"],
             "bronze.daily_balances": ["source_account_key", "bal_type", "balance_date", "amt"],
             "bronze.loans": ["source_loan_key", "source_account_key", "source_customer_key", "loan_type", "status", "principal_balance",
                              "current_interest_rate", "rate_type", "origination_date", "maturity_date", "next_rate_change_date", "product name"],
             "bronze.loan_collateral": ["source_collateral_key", "source_loan_key", "collateral_type", "property_postal_code",
                                        "property_type", "collateral_value", "lien_position"],
             "bronze.credit_lines": ["source_credit_line_key", "source_account_key", "credit_limit", "current_balance"],
             "bronze.debit_cards": ["source_card_key", "source_account_key", "card_status", "card_tier"],
             "bronze.credit_cards": ["source_card_key", "source_account_key", "source_customer_key", "card_status", "card_tier",
                                     "credit_limit", "current_balance"],
             "bronze.credit_bureau_tradeline": ["source_customer_key", "lender_name", "status", "account_type", "balance",
                                                "monthly_payment", "opened_date"]}
    for e, cols in empty.items():
        _w(root, e, [], cols)
    return root


# C5 is in UC4 as well as UC3: a much younger beneficiary on an older customer's account is
# "next generation" by the proposal's definition, even when that customer has died.
EXPECTED = {"UC1": {"C1", "C6"}, "UC3": {"C5"}, "UC4": {"C3", "C5"}, "UC5": {"C6"}, "UC6": {"C6"}, "UC7": {"C3"}}
