"""etl.bridge: the bank inside the market."""

import pytest

from etl import bridge
from etl.helpers import Graph


@pytest.mark.parametrize(
    ("loan_type", "lien", "product"),
    [
        ("MORTGAGE", None, bridge.FIRST_LIEN),
        ("MORTGAGE", 1, bridge.FIRST_LIEN),
        ("MORTGAGE", 2, bridge.SUBORDINATE),
        ("HELOC", None, bridge.SUBORDINATE),
        ("HELOC", 2, bridge.SUBORDINATE),
        ("HELOC", 1, bridge.FIRST_LIEN),
        ("AUTO", None, None),
        ("PERSONAL", 1, None),
        (None, None, None),
    ],
)
def test_loan_product(loan_type, lien, product):
    assert bridge.loan_product({"loan_type": loan_type}, lien) == product


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
    assert got == {"M1": bridge.FIRST_LIEN, "H1": bridge.SUBORDINATE, "H2": bridge.FIRST_LIEN}  # no auto loan
    assert all(e[4]["basis"] for e in br.edges["CLASSIFIED_AS"])


def test_bridge_classifies_only_to_products_the_market_has():
    market, b = Graph(), Graph()
    market.node("LoanProduct", bridge.FIRST_LIEN)
    b.node("CustomerLoan", "H1", loan_type="HELOC")  # would be subordinate, which this market lacks
    b.node("CustomerLoan", "M1", loan_type="MORTGAGE")
    assert [e[1] for e in bridge.build(market, b).edges["CLASSIFIED_AS"]] == ["M1"]
