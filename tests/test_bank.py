"""etl.bank: the synthetic bank layer, on the hand-built bank miniature (tests/bank_fixture.py)."""

import csv

import pytest

from etl import bank
from tests import bank_fixture


def add_rows(root, table, rows):
    """Append rows to one fixture table, keeping its header."""
    path = root / "bronze" / f"{table}.csv"
    with path.open(newline="") as fh:
        cols = next(csv.reader(fh))
    with path.open("a", newline="") as fh:
        csv.DictWriter(fh, fieldnames=cols).writerows({c: r.get(c, "") for c in cols} for r in rows)


@pytest.fixture
def fresh(tmp_path):
    """A writable copy of the bank miniature, for tests that add rows."""
    return bank_fixture.write_fixture(tmp_path / "bank")


def test_households_are_addresses_not_joint_accounts(bank_dir):
    g, as_of = bank.build(bank_dir)
    assert as_of == bank_fixture.AS_OF
    cust = g.nodes["Customer"]
    assert cust["C1"]["household_id"] == cust["C2"]["household_id"] == cust["C6"]["household_id"]
    assert cust["C3"]["household_id"] != cust["C1"]["household_id"]  # joint owner elsewhere
    assert cust["C7"]["household_id"] != cust["C8"]["household_id"]  # friends sharing an account
    assert all(h["derived"] for h in g.nodes["Household"].values())
    assert g.nodes["Household"][cust["C1"]["household_id"]]["size"] == 3


def test_customer_rollups(bank_dir):
    cust = bank.build(bank_dir)[0].nodes["Customer"]
    assert cust["C1"]["age"] == 76 and cust["C1"]["logins_90d"] == 5 and cust["C1"]["digital_user"] is True
    assert cust["C6"]["digital_user"] is False and cust["C6"]["logins_90d"] == 0
    assert cust["C3"]["last_address_change_dt"] == "2026-07-15"


def test_derived_edges_are_marked(bank_dir):
    g, _ = bank.build(bank_dir)
    for rel in ("SENDS_TO", "PAID_BY", "SPENDS_AT", "MEMBER_OF"):
        assert g.edges[rel] and all(e[4].get("derived") for e in g.edges[rel]), rel
    assert [c["name"] for c in g.nodes["Counterparty"].values() if c["kind"] == "COMPETITOR"] == ["NORTHSTAR FED"]
    sends = g.edges["SENDS_TO"][0][4]
    assert sends["count"] == 2 and sends["total"] == 2400.0 and (sends["first_date"], sends["last_date"]) == ("2026-07-10", "2026-08-10")


def test_accounts_owners_and_products(bank_dir):
    g, _ = bank.build(bank_dir)
    assert g.nodes["Account"]["A5"]["name"] == "SAV-HY …A5"
    owns = {(e[1], e[3]): e[4] for e in g.edges["OWNS"]}
    assert owns[("C3", "A1")]["role_code"] == "J" and owns[("C1", "A1")]["primary"] is True
    assert len(g.edges["OF_PRODUCT"]) == len(g.nodes["Account"])


def test_no_contact_fields_in_the_graph(bank_dir):
    g, _ = bank.build(bank_dir)
    for c in g.nodes["Customer"].values():
        assert "email" not in c and "phone" not in c and "address_line1" not in c


def test_description_parsers():
    assert bank.COMPETITOR_RX.match("EXT TRANSFER TO NORTHSTAR FED XXXXXX1234").group(1) == "NORTHSTAR FED"
    assert bank.COMPETITOR_RX.match("WIRE TO APEX DIGITAL XXXXXX9").group(1) == "APEX DIGITAL"
    assert bank.COMPETITOR_RX.match("POS PURCHASE FRESHWAY MARKET") is None
    pay = bank.PAYROLL_RX.match("ACME CORP PAYROLL PPD ID: 111")
    assert pay.group(1) == "ACME CORP" and pay.group(2) == "111"


def test_small_helpers():
    assert bank.num(None) is None and bank.num("1.5") == 1.5
    assert bank.tail("PATTERN-ACCT-000005596") == "5596"
    assert bank.hh_id("1 Oak St", "23220") == bank.hh_id("1 Oak St", "23220") != bank.hh_id("1 Oak St", "23221")


def test_missing_table_and_empty_customers_are_clear_errors(tmp_path, fresh):
    with pytest.raises(FileNotFoundError, match="bank_v1"):
        bank.build(tmp_path)
    (fresh / "bronze" / "customers.csv").write_text("source_customer_key,extract_dt\n")
    with pytest.raises(ValueError, match="no rows"):
        bank.build(fresh)


def test_rows_naming_unknown_customers_are_skipped_and_counted(fresh):
    add_rows(fresh, "crm_data", [{"source_customer_key": "NOBODY", "receptiveness_score": "0.5"}])
    add_rows(
        fresh,
        "credit_bureau",
        [
            {"source_customer_key": "NOBODY", "score_date": "2026-01-01", "credit_score": "700"},
            {"source_customer_key": "C1", "score_date": "2026-02-01", "credit_score": ""},
        ],
    )
    g, _ = bank.build(fresh)
    assert g.skipped == {"crm_data": 1, "credit_bureau": 1}
    assert "credit_score" not in g.nodes["Customer"]["C1"]  # an empty score is ignored, not a crash


def test_loans_collateral_and_tradelines(fresh):
    add_rows(
        fresh,
        "loans",
        [
            {
                "source_loan_key": "LN1",
                "source_account_key": "A3",
                "source_customer_key": "C3",
                "loan_type": "HELOC",
                "status": "ACTIVE",
                "principal_balance": "1000",
                "product name": "HELOC",
            }
        ],
    )
    add_rows(
        fresh,
        "loan_collateral",
        [
            {"source_collateral_key": "CO1", "source_loan_key": "LN1", "collateral_type": "REAL_ESTATE", "lien_position": "2"},
            {"source_collateral_key": "CO2", "source_loan_key": "LN1", "collateral_type": "REAL_ESTATE", "lien_position": ""},
        ],
    )
    add_rows(
        fresh,
        "credit_bureau_tradeline",
        [
            {"source_customer_key": "C3", "lender_name": "MERIDIAN NATIONAL BANK", "status": "OPEN", "account_type": "MORTGAGE", "balance": "9"},
            {"source_customer_key": "C3", "lender_name": "BANKING-KG (THIS BANK)", "status": "OPEN", "account_type": "AUTO"},
            {"source_customer_key": "C3", "lender_name": "OLD LENDER", "status": "CLOSED", "account_type": "AUTO"},
        ],
    )
    g, _ = bank.build(fresh)
    assert g.nodes["CustomerLoan"]["LN1"]["name"] == "HELOC loan …LN1"
    assert [e[4].get("lien_position") for e in g.edges["SECURED_BY"]] == [2, None]
    assert [e[3] for e in g.edges["OWES"]] == ["cp:lender:meridian_national_bank"]  # own and closed tradelines skipped
    assert ("C3", "LN1") in {(e[1], e[3]) for e in g.edges["BORROWS"]}


def test_bank_layer_never_names_a_market_lender(market, bank_dir):
    g, _ = bank.build(bank_dir)
    names = {n["name"].lower() for n in market.nodes["Lender"].values()}
    assert not [c for c in g.nodes["Counterparty"].values() if c["name"].lower() in names]


def test_cards_lines_balances_branches_and_status_events(fresh):
    add_rows(fresh, "credit_lines", [{"source_credit_line_key": "CL1", "source_account_key": "A1", "credit_limit": "5000", "current_balance": "10"}])
    add_rows(fresh, "debit_cards", [{"source_card_key": "DC1", "source_account_key": "A3", "card_status": "ACTIVE", "card_tier": "STD"}])
    add_rows(
        fresh,
        "credit_cards",
        [
            {
                "source_card_key": "CC1",
                "source_account_key": "A6",
                "source_customer_key": "C5",
                "card_status": "ACTIVE",
                "card_tier": "GOLD",
                "credit_limit": "9000",
                "current_balance": "1",
            }
        ],
    )
    add_rows(
        fresh,
        "daily_balances",
        [
            {"source_account_key": "A1", "bal_type": "LEDGER", "balance_date": "2026-08-30", "amt": "10.5"},
            {"source_account_key": "A1", "bal_type": "LEDGER", "balance_date": "2026-08-31", "amt": "12.0"},
            {"source_account_key": "A1", "bal_type": "AVAILABLE", "balance_date": "2026-08-31", "amt": "99"},
            {"source_account_key": "GONE", "bal_type": "LEDGER", "balance_date": "2026-08-31", "amt": "1"},
        ],
    )
    add_rows(
        fresh, "business_unit", [{"source_business_unit_key": "BR001", "business_unit": "RETAIL", "open_date": "1998-04-01", "postal_code": "23220"}]
    )
    add_rows(
        fresh,
        "customer_change_events",
        [
            {"source_customer_key": "C4", "change_dt": "2026-05-01 09:00:00+00:00", "data_ident": "STATUS", "new_value": "DECEASED"},
            {"source_customer_key": "NOBODY", "change_dt": "2026-05-01", "data_ident": "ADDRESS"},
        ],
    )
    add_rows(
        fresh,
        "digital_sessions",
        [{"source_session_key": "S9", "source_customer_key": "C6", "login_success": "N", "login_timestamp": "2026-08-30 09:00:00+00:00"}],
    )
    g, _ = bank.build(fresh)
    assert g.nodes["CreditLine"]["CL1"]["credit_limit"] == 5000.0 and ("A1", "CL1") in {(e[1], e[3]) for e in g.edges["HAS_CREDIT_LINE"]}
    assert g.nodes["Card"]["DC1"]["card_kind"] == "DEBIT" and g.nodes["Card"]["CC1"]["card_kind"] == "CREDIT"
    assert [(e[1], e[3]) for e in g.edges["HOLDS_CARD"]] == [("C5", "CC1")]  # debit cards carry no cardholder
    assert g.nodes["Account"]["A1"]["balance_latest"] == 12.0 and "GONE" not in g.nodes["Account"]
    assert g.nodes["BusinessUnit"]["bu:BR001"]["name"] == "Branch BR001 · RETAIL"
    assert g.nodes["Customer"]["C4"]["deceased_reported_dt"] == "2026-05-01"
    assert g.nodes["Customer"]["C6"]["digital_user"] is False  # a failed login is not a login
    assert g.skipped["customer_change_events"] == 1
