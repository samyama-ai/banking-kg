"""mcp_server.tools: read-only, quoted, bounded."""

import pytest

from mcp_server import tools
from tests.conftest import FakeEngine


@pytest.mark.parametrize(("limit", "out"), [(25, 25), (0, 1), (-5, 1), (10_000, tools.MAX_LIMIT), ("7", 7)])
def test_bounded(limit, out):
    assert tools.bounded(limit) == out


def test_bounded_rejects_non_numbers():
    with pytest.raises(ValueError):
        tools.bounded("ten")


def test_list_audiences_maps_columns():
    db = FakeEngine([("MATCH (a:Audience)", [["UC1", "Household member left", "Retention", 26, 22, "2026-08-31"]])])
    assert tools.list_audiences(db) == [
        {"use_case": "UC1", "name": "Household member left", "campaign": "Retention", "customers": 26, "households": 22, "as_of": "2026-08-31"}
    ]


def test_audience_members_quotes_validates_and_caps():
    db = FakeEngine([("IN_AUDIENCE", [["C1", "H1", "why"]])])
    assert tools.audience_members(db, "UC1' OR 1=1 //", "CONTROL", 9_999) == [{"customer_id": "C1", "household_id": "H1", "reason": "why"}]
    q = db.queries[0]
    assert "a.use_case = 'UC1\\' OR 1=1 //'" in q and "m.slice = 'CONTROL'" in q and q.endswith(f"LIMIT {tools.MAX_LIMIT}")
    with pytest.raises(ValueError, match="group"):
        tools.audience_members(db, "UC1", "EVERYONE")


def test_customer_connections_and_lender_book_are_read_only():
    db = FakeEngine()
    out = tools.customer_connections(db, "C1")
    assert set(out) == {"household", "co_owners", "counterparties", "audiences"}
    book = tools.lender_book(db, "Truist Bank")
    assert set(book) == {"lender", "filings", "originations_by_product", "sold_to", "sba_by_industry"}
    writes = ("CREATE", "MERGE", "SET ", "DELETE", "REMOVE")
    assert not [q for q in db.queries if any(w in q for w in writes)]
    assert all("'C1'" in q for q in db.queries[:4]) and all("'Truist Bank'" in q for q in db.queries[4:])
