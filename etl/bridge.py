"""Bridge: places the bank layer's fictional bank inside the public market layer.

What is joined, and only this, because nothing else can be joined honestly:
  * Banking-KG Bank becomes one more `Lender` (synthetic: true), so "the bank" and "the market" are the
    same kind of node and market questions can be asked of it.
  * every bank `Product` -[:OFFERED_BY]-> that Lender.
  * every first-lien mortgage and HELOC `CustomerLoan` -[:CLASSIFIED_AS]-> the HMDA `LoanProduct` it would be
    reported under, so the bank's own book can be set beside the market's product mix.

What is deliberately NOT joined:
  * the bank's competitors (Counterparty) are fictional names; they are never matched to real lenders,
    because synthetic money flows must not be attributed to a real institution (spec §10).
  * customers are not placed in census tracts: the market layer is one state-year (DC 2023) and the bank's
    customers live in VA, MD and NC. Extending the market layer to those states (spec D4) is what makes a
    geographic join possible.
"""

from etl.helpers import Graph

BANK_ID = "BANKING-KG"
BANK = {"name": "Banking-KG Bank", "lender_type": "Bank", "hq_city": "Richmond", "hq_state": "VA", "synthetic": True}

# The request has no government-program field (FHA / VA / USDA), so the bank's mortgages are reported as
# conventional; lien position comes from loan_collateral.lien_position, else from the product.
FIRST_LIEN = "Conventional:First Lien"
SUBORDINATE = "Conventional:Subordinate Lien"
FIRST_POSITION = 1
MORTGAGE, HELOC = "MORTGAGE", "HELOC"  # bank loans.loan_type values that HMDA would report


def loan_product(loan: dict, lien: int | None) -> str | None:
    """The HMDA LoanProduct a bank loan would be reported under, or None for loans HMDA does not cover.

    A mortgage is first lien unless its collateral says otherwise; a HELOC is subordinate unless its
    collateral says it holds first position."""
    if loan.get("loan_type") == MORTGAGE:
        return SUBORDINATE if lien and lien > FIRST_POSITION else FIRST_LIEN
    if loan.get("loan_type") == HELOC:
        return SUBORDINATE if lien is None or lien > FIRST_POSITION else FIRST_LIEN
    return None


def build(market: Graph, bank: Graph) -> Graph:
    """The bridge as its own small graph: the bank's Lender node, OFFERED_BY and CLASSIFIED_AS edges.

    market supplies the LoanProduct nodes that exist; a classification is made only to one of them."""
    g = Graph()
    g.node("Lender", BANK_ID, **BANK)
    for pid in bank.nodes["Product"]:
        g.edge("OFFERED_BY", "Product", pid, "Lender", BANK_ID)
    lien = {e[1]: e[4].get("lien_position") for e in bank.edges["SECURED_BY"]}
    have = market.nodes.get("LoanProduct", {})
    for lid, loan in bank.nodes["CustomerLoan"].items():
        p = loan_product(loan, lien.get(lid))
        if p and p in have:
            g.edge(
                "CLASSIFIED_AS",
                "CustomerLoan",
                lid,
                "LoanProduct",
                p,
                basis="loan_type + lien_position; no FHA/VA field in the request, so conventional",
            )
    return g
