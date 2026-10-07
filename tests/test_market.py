"""etl.market: the public layer, on the hand-built market miniature (tests/market_fixture.py)."""

import pytest

from etl import market as m
from tests import market_fixture


# ---------------------------------------------------------------- small helpers
@pytest.mark.parametrize(("v", "out"), [("455000", 455000.0), ("6.5", 6.5), ("NA", None), ("Exempt", None), ("", None), (None, None)])
def test_num(v, out):
    assert m.num(v) == out


def test_code_is_an_int_or_none():
    assert m.code("31") == 31 and m.code("1.0") == 1 and m.code("NA") is None


@pytest.mark.parametrize(("v", "label"), [(455000, "$455K"), (1_250_000, "$1.2M"), (None, "$0K"), (0, "$0K")])
def test_money(v, label):
    assert m.money(v) == label


def test_title_slug_present():
    assert m.title("ACME DINER llc") == "Acme Diner llc"
    assert m.title(None) == ""
    assert m.slug(" Main Street, Capital! ") == "MAIN-STREET-CAPITAL"
    assert m.present("NA") is None and m.present("") is None and m.present("11001") == "11001"


def test_business_id_is_stable_and_ignores_punctuation():
    a = {"BorrName": "ACME DINER LLC", "BorrStreet": "1 MAIN ST", "BorrZip": "20001-1234"}
    b = {"BorrName": "Acme Diner, LLC", "BorrStreet": "1 Main St.", "BorrZip": "20001"}
    assert m.business_id(a) == m.business_id(b)
    assert m.business_id(a).startswith("BIZ-") and len(m.business_id(a)) == len("BIZ-") + m.BUSINESS_HASH_CHARS


def test_missing_source_files_name_the_fetch_step(tmp_path):
    with pytest.raises(FileNotFoundError, match=r"etl\.fetch"):
        m.source(tmp_path, "hmda_*.csv")
    with pytest.raises(FileNotFoundError, match=r"etl\.fetch"):
        m.read_json(tmp_path / "filers_dc_2023.json")
    with pytest.raises(FileNotFoundError):
        m.build(tmp_path)


# ---------------------------------------------------------------- the layer
def test_every_row_is_an_application_and_only_originations_are_loans(market):
    assert len(market.nodes["Application"]) == 4
    assert sorted(market.nodes["Loan"]) == ["LOAN-000001", "LOAN-000003"]
    assert len(market.edges["ORIGINATED_AS"]) == len(market.edges["ORIGINATED_BY"]) == 2
    assert [e[1] for e in market.edges["SOLD_TO"]] == ["LOAN-000001"]  # LOAN-000003 kept on balance sheet
    assert sorted(e[3] for e in market.edges["DENIED_FOR"]) == ["DR-1", "DR-3"]


def test_application_fields_decode_hmda_codes(market):
    a = market.nodes["Application"]["APP-000001"]
    assert a["action"] == "Loan originated" and a["loan_type"] == "Conventional" and a["purpose"] == "Home purchase"
    assert a["lien"] == "First lien" and a["occupancy"] == "Principal residence" and a["open_end"] is False
    assert a["debt_to_income"] == "30%-<36%" and a["applicant_age"] == "35-44"
    assert "income_k" not in a  # 'NA' is not stored
    assert market.nodes["Application"]["APP-000002"]["action"] == "Denied"


def test_geography_tract_county_msa(market):
    assert set(market.nodes["Tract"]) == {"11001000100", "11001000200"}
    assert market.nodes["Tract"]["11001000100"]["name"] == "Tract 0001.00"
    assert market.nodes["County"]["11001"]["name"] == "District of Columbia"
    assert market.nodes["MSA"]["47894"]["name"].startswith("Washington-Arlington")
    assert len(market.edges["IN_COUNTY"]) == 2 and len(market.edges["IN_MSA"]) == 1


def test_lenders_certificates_and_filings(market):
    lenders = market.nodes["Lender"]
    assert lenders["L1"]["cert"] == 101 and lenders["L1"]["lender_type"] == "Bank" and lenders["L1"]["assets_k"] == 950000
    assert lenders["L1"]["hq_state"] == "VA" and lenders["L1"]["hq_city"] == "Richmond"
    assert lenders["L2"]["cert"] == 202
    assert "cert" not in lenders["L3"] and lenders["L3"]["lender_type"] == "Non-bank lender"
    assert sorted(f[3] for f in market.edges["FILED"]) == ["FIL-101-20221231", "FIL-101-20231231"]
    assert market.nodes["Filing"]["FIL-101-20231231"]["period"] == "2023Q4"
    assert len(market.edges["REGISTERED_AS"]) == len(market.nodes["LegalEntity"]) == 3


def test_sba_lenders_businesses_and_privacy(market):
    assert len(market.nodes["SBALoan"]) == 4  # 3 DC 7(a) + 1 504; the MD row is out
    made_by = {e[1]: e[3] for e in market.edges["MADE_BY"]}
    assert made_by["SBA7A-00001"] == "L1"  # cert 101 reuses the HMDA lender
    assert made_by["SBA7A-00003"] == "SBA-MAIN-STREET-CAPITAL"
    assert made_by["SBA504-00001"] == "CDC-CAPITAL-CDC"
    assert market.nodes["SBALoan"]["SBA7A-00002"]["status"] == "Charged off"
    biz = market.nodes["Business"]
    assert len(biz) == 2
    sole = [b for b in biz.values() if b["sole_proprietor"]]
    assert len(sole) == 1 and sole[0]["name"].startswith("Sole proprietor") and "Jane" not in str(sole[0]) and "SIDE" not in str(sole[0])
    assert len(market.edges["LOCATED_AT"]) == 1  # one business, three loans, one address edge
    assert len(market.edges["IN_INDUSTRY"]) == 2


def test_business_ids_are_stable_across_builds(tmp_path):
    a = m.build(market_fixture.write_fixture(tmp_path / "a"))
    b = m.build(market_fixture.write_fixture(tmp_path / "b"))
    assert sorted(a.nodes["Business"]) == sorted(b.nodes["Business"])
