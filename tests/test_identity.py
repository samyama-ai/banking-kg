"""etl.identity: name normalisation and the LEI -> FDIC certificate match."""

import pytest

from etl import identity as I

FDIC = [
    {"NAME": "Alpha Bank", "CERT": "101", "STALP": "VA", "CITY": "Richmond"},
    {"NAME": "Twin Savings Bank", "CERT": "201", "STALP": "OH", "CITY": "Akron"},
    {"NAME": "Twin Savings Bank", "CERT": "202", "STALP": "VA", "CITY": "Norfolk"},
    {"NAME": "Twin Savings Bank", "CERT": "203", "STALP": "VA", "CITY": "Roanoke"},
]


@pytest.mark.parametrize(
    ("name", "normal"),
    [
        ("First Bank & Trust Co.", "first bank and trust"),
        ("Alpha Bank, N.A.", "alpha bank"),
        ("ALPHA BANK NATIONAL ASSOCIATION", "alpha bank"),
        ("The   Beta   Company, Inc.", "beta"),
        ("", ""),
        (None, ""),
    ],
)
def test_norm(name, normal):
    assert I.norm(name) == normal


def test_fdic_index_groups_by_normalised_name():
    idx = I.fdic_index(FDIC)
    assert [r["CERT"] for r in idx["twin savings bank"]] == ["201", "202", "203"]
    assert idx["alpha bank"][0]["CERT"] == "101"


def test_match_prefers_gleif_legal_name_then_filer_name():
    idx = I.fdic_index(FDIC)
    assert I.match("L1", "something else", {"L1": {"legal_name": "ALPHA BANK NATIONAL ASSOCIATION"}}, idx)["CERT"] == "101"
    assert I.match("L1", "Alpha Bank, N.A.", {}, idx)["CERT"] == "101"


def test_match_breaks_ties_by_state_then_city():
    idx = I.fdic_index(FDIC)
    gleif = {"L2": {"legal_name": "TWIN SAVINGS BANK", "hq_region": "US-VA", "hq_city": "NORFOLK"}}
    assert I.match("L2", "Twin Savings Bank", gleif, idx)["CERT"] == "202"


def test_match_returns_none_when_still_ambiguous_or_unknown():
    idx = I.fdic_index(FDIC)
    assert I.match("L9", "Twin Savings Bank", {"L9": {"legal_name": "TWIN SAVINGS BANK", "hq_region": "US-VA"}}, idx) is None
    assert I.match("L8", "Nobody Mortgage LLC", {}, idx) is None
    assert I.match("L7", None, {}, idx) is None


@pytest.mark.parametrize(
    ("name", "row", "kind"),
    [
        ("Alpha Bank", {"CERT": "1"}, I.BANK),
        ("Navy Federal Credit Union", None, I.CREDIT_UNION),
        ("Old Bank of Somewhere", None, I.BANK_NO_CHARTER),
        ("Rocket Mortgage, LLC", None, I.NON_BANK),
        (None, None, I.NON_BANK),
    ],
)
def test_lender_type(name, row, kind):
    assert I.lender_type(name, row) == kind
