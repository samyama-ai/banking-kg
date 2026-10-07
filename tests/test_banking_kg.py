"""Offline tests for banking-kg: both layers, the bridge and the schema, on hand-built fixtures with known
answers. One live test runs when BANKING_KG_URL points at a loaded engine (e.g. http://localhost:8081)."""

import os
import pathlib
import re

import pytest

from etl import audiences, bridge
from etl import bank as bank_layer
from etl import identity as I
from etl import market as market_layer
from etl.helpers import Graph, lit, props, statements
from etl.verify import expected, graph_members
from tests import bank_fixture, market_fixture

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema" / "banking_kg.cypher"


@pytest.fixture(scope="module")
def market(tmp_path_factory):
    return market_layer.build(market_fixture.write_fixture(tmp_path_factory.mktemp("market")))


@pytest.fixture(scope="module")
def bank_dir(tmp_path_factory):
    return bank_fixture.write_fixture(tmp_path_factory.mktemp("bank"))


# ---------------------------------------------------------------- helpers and schema
def test_cypher_literals():
    assert lit("O'Neil") == "'O\\'Neil'"
    assert lit(True) == "true"
    assert props({"a": 1, "b": None, "c": ""}) == "{a: 1}"


def test_schema_has_one_constraint_per_label():
    s = statements(SCHEMA)
    assert len(s) == 29 and all(x.startswith("CREATE CONSTRAINT") for x in s)


def test_schema_documents_every_label_and_relationship_the_code_creates():
    schema = SCHEMA.read_text()
    code = "".join((ROOT / "etl" / f).read_text() for f in ("market.py", "bank.py", "bridge.py", "audiences.py"))
    labels = set(re.findall(r'g\.node\("([A-Za-z]+)"', code)) | {"Audience"}
    rels = set(re.findall(r'g\.edge\("([A-Z_]+)"', code)) | set(re.findall(r'create_edges\(db, "([A-Z_]+)"', code))
    rels |= {"SENDS_TO", "RECEIVES_FROM", "PAID_BY"}
    assert len(labels) == 29, sorted(labels)
    assert [x for x in labels if f"(:{x} " not in schema and f"(:{x})" not in schema] == []
    assert [r for r in rels if f":{r} " not in schema and f":{r}]" not in schema] == []


# ---------------------------------------------------------------- market layer
def test_identity_unique_name_match_and_tie_break():
    idx = I.fdic_index(market_fixture_rows())
    gleif = {"L1": {"legal_name": "ALPHA BANK NATIONAL ASSOCIATION"},
             "L2": {"legal_name": "TWIN SAVINGS BANK", "hq_region": "US-VA", "hq_city": "NORFOLK"},
             "L9": {"legal_name": "TWIN SAVINGS BANK"}}
    assert I.match("L1", "Alpha Bank, N.A.", gleif, idx)["CERT"] == "101"
    assert I.match("L2", "Twin Savings Bank", gleif, idx)["CERT"] == "202"     # HQ state breaks the tie
    assert I.match("L9", "Twin Savings Bank", gleif, idx) is None              # still ambiguous: no certificate
    assert I.norm("First Bank & Trust Co.") == "first bank and trust"


def market_fixture_rows():
    return [{"NAME": "Alpha Bank", "CERT": "101", "STALP": "VA", "CITY": "Richmond"},
            {"NAME": "Twin Savings Bank", "CERT": "201", "STALP": "OH", "CITY": "Akron"},
            {"NAME": "Twin Savings Bank", "CERT": "202", "STALP": "VA", "CITY": "Norfolk"}]


def test_every_row_is_an_application_and_only_originations_are_loans(market):
    assert len(market.nodes["Application"]) == 4
    assert sorted(market.nodes["Loan"]) == ["LOAN-000001", "LOAN-000003"]
    assert len(market.edges["ORIGINATED_AS"]) == len(market.edges["ORIGINATED_BY"]) == 2
    assert [e[1] for e in market.edges["SOLD_TO"]] == ["LOAN-000001"]        # LOAN-000003 kept on balance sheet
    assert sorted(e[3] for e in market.edges["DENIED_FOR"]) == ["DR-1", "DR-3"]


def test_lenders_certificates_and_filings(market):
    L = market.nodes["Lender"]
    assert L["L1"]["cert"] == 101 and L["L1"]["lender_type"] == "Bank" and L["L1"]["assets_k"] == 950000
    assert L["L2"]["cert"] == 202
    assert "cert" not in L["L3"] and L["L3"]["lender_type"] == "Non-bank lender"
    assert sorted(f[3] for f in market.edges["FILED"]) == ["FIL-101-20221231", "FIL-101-20231231"]
    assert market.nodes["Filing"]["FIL-101-20231231"]["period"] == "2023Q4"


def test_sba_lenders_businesses_and_privacy(market):
    assert len(market.nodes["SBALoan"]) == 4                                  # 3 DC 7(a) + 1 504; the MD row is out
    made_by = {e[1]: e[3] for e in market.edges["MADE_BY"]}
    assert made_by["SBA7A-00001"] == "L1"                                     # cert 101 reuses the HMDA lender
    assert made_by["SBA7A-00003"] == "SBA-MAIN-STREET-CAPITAL"
    assert made_by["SBA504-00001"] == "CDC-CAPITAL-CDC"
    biz = market.nodes["Business"]
    assert len(biz) == 2
    sole = [b for b in biz.values() if b["sole_proprietor"]]
    assert len(sole) == 1 and sole[0]["name"].startswith("Sole proprietor") and "Jane" not in str(sole[0])
    assert len(market.edges["LOCATED_AT"]) == 1                               # one business, three loans, one address edge
    assert len(market.edges["IN_INDUSTRY"]) == 2


def test_business_ids_are_stable(tmp_path):
    a = market_layer.build(market_fixture.write_fixture(tmp_path / "a"))
    b = market_layer.build(market_fixture.write_fixture(tmp_path / "b"))
    assert sorted(a.nodes["Business"]) == sorted(b.nodes["Business"])


# ---------------------------------------------------------------- bank layer
def test_households_are_addresses_not_joint_accounts(bank_dir):
    g, as_of = bank_layer.build(bank_dir)
    assert as_of == bank_fixture.AS_OF
    C = g.nodes["Customer"]
    assert C["C1"]["household_id"] == C["C2"]["household_id"] == C["C6"]["household_id"]
    assert C["C3"]["household_id"] != C["C1"]["household_id"]                # joint owner elsewhere
    assert C["C7"]["household_id"] != C["C8"]["household_id"]                # friends sharing an account
    assert all(h["derived"] for h in g.nodes["Household"].values())


def test_derived_edges_are_marked(bank_dir):
    g, _ = bank_layer.build(bank_dir)
    for rel in ("SENDS_TO", "PAID_BY", "SPENDS_AT", "MEMBER_OF"):
        assert g.edges[rel] and all(e[4].get("derived") for e in g.edges[rel]), rel
    assert [c["name"] for c in g.nodes["Counterparty"].values() if c["kind"] == "COMPETITOR"] == ["NORTHSTAR FED"]


def test_no_contact_fields_in_the_graph(bank_dir):
    g, _ = bank_layer.build(bank_dir)
    for c in g.nodes["Customer"].values():
        assert "email" not in c and "phone" not in c and "address_line1" not in c


def test_description_parsers():
    assert bank_layer.COMPETITOR_RX.match("EXT TRANSFER TO NORTHSTAR FED XXXXXX1234").group(1) == "NORTHSTAR FED"
    assert bank_layer.COMPETITOR_RX.match("WIRE TO APEX DIGITAL XXXXXX9").group(1) == "APEX DIGITAL"
    assert bank_layer.COMPETITOR_RX.match("POS PURCHASE FRESHWAY MARKET") is None
    m = bank_layer.PAYROLL_RX.match("ACME CORP PAYROLL PPD ID: 111")
    assert m.group(1) == "ACME CORP" and m.group(2) == "111"


def test_independent_answers_match_the_fixture(bank_dir):
    assert expected(bank_dir) == bank_fixture.EXPECTED


def test_control_group_holds_out_whole_households():
    members = {f"c{i}": (f"h{i // 3}", "why") for i in range(300)}
    out = audiences.finalise("UCX", members, bank_fixture.AS_OF)
    by_hh = {}
    for r in out:
        by_hh.setdefault(r["household_id"], set()).add(r["slice"])
    assert all(len(s) == 1 for s in by_hh.values())                           # never split a household
    assert 0 < sum(r["slice"] == "CONTROL" for r in out) < len(out)
    assert sum(r["household_primary"] for r in out) == len(by_hh)              # one mail piece per household


# ---------------------------------------------------------------- bridge
def test_bridge_places_the_bank_in_the_market(market):
    b = Graph()
    b.node("Product", "prod:MTG-30F", name="30 YR FIXED")
    b.node("CustomerLoan", "M1", loan_type="MORTGAGE")
    b.node("CustomerLoan", "H1", loan_type="HELOC")
    b.node("CustomerLoan", "H2", loan_type="HELOC")
    b.node("CustomerLoan", "A1", loan_type="AUTO")
    b.edge("SECURED_BY", "CustomerLoan", "H2", "Collateral", "X", lien_position=1)
    br = bridge.build(market, b)
    assert br.nodes["Lender"][bridge.BANK_ID]["synthetic"] is True
    assert [e[1] for e in br.edges["OFFERED_BY"]] == ["prod:MTG-30F"]
    got = {e[1]: e[3] for e in br.edges["CLASSIFIED_AS"]}
    assert got == {"M1": bridge.FIRST_LIEN, "H1": bridge.SUBORDINATE, "H2": bridge.FIRST_LIEN}   # no auto loan


def test_bank_layer_never_names_a_market_lender(market, bank_dir):
    g, _ = bank_layer.build(bank_dir)
    names = {n["name"].lower() for n in market.nodes["Lender"].values()}
    assert not [c for c in g.nodes["Counterparty"].values() if c["name"].lower() in names]


# ---------------------------------------------------------------- live
@pytest.mark.skipif(not os.environ.get("BANKING_KG_URL"), reason="set BANKING_KG_URL to a loaded engine")
def test_live_graph_audiences_match_independent_calculation():
    data = pathlib.Path(os.environ.get("BANKING_KG_DATA", ROOT.parent / "data" / "banking-kg"))
    assert graph_members(data / "audiences") == expected(data / "bank_v1")
