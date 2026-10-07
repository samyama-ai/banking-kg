"""etl.audiences: the use-case Cypher, UC2 (control groups, one mail piece per household) and the export."""

import csv
import json

from etl import audiences as A
from tests.conftest import FakeEngine

AS_OF = "2026-08-31"


def test_small_helpers():
    assert A.cypher_list(("B", "J")) == "['B', 'J']"
    assert A.days_before(AS_OF, 60) == "2026-07-02"
    assert A.days_before("2026-03-01", 1) == "2026-02-28"


def test_six_use_cases_with_their_rules_in_the_cypher():
    ucs = A.use_cases(AS_OF)
    assert [u.code for u in ucs] == ["UC1", "UC3", "UC4", "UC5", "UC6", "UC7"]
    cy = {u.code: u.cypher for u in ucs}
    assert "a.close_date >= '2026-07-02'" in cy["UC1"]
    assert f"old.age >= {A.OLDER_AGE}" in cy["UC4"] and f"young.age <= {A.YOUNGER_AGE}" in cy["UC4"]
    assert f"u.logins_90d >= {A.ACTIVE_LOGINS}" in cy["UC5"]
    assert "n.open_date >= '2026-03-04'" in cy["UC6"] and f"'{A.RESPONDER_PRODUCT}'" in cy["UC6"]
    assert f"s.count >= {A.MIN_TRANSFERS}" in cy["UC7"] and "s.last_date >= '2026-06-02'" in cy["UC7"]
    assert all(u.cypher.startswith("MATCH") and "RETURN" in u.cypher for u in ucs)


def test_reasons_read_well():
    ucs = {u.code: u for u in A.use_cases(AS_OF)}
    assert ucs["UC1"].reason(["c", "h", "2026-08-01"]) == "Household member closed their accounts on 2026-08-01"
    assert ucs["UC3"].reason(["c", "h", "BENEFICIARY"]).startswith("Named beneficiary")
    assert ucs["UC4"].reason(["c", "h", "", "Richmond"]) == "Shares an account with a much older customer"
    assert ucs["UC4"].reason(["c", "h", "2026-07-15", "Arlington"]).endswith("moved on 2026-07-15 to Arlington")
    assert ucs["UC7"].reason(["c", "h", "NORTHSTAR FED", 2400.0]) == "Sent $2,400 to NORTHSTAR FED over the history window"


def test_held_out_is_stable_and_near_the_control_share():
    keys = [f"h{i}" for i in range(2000)]
    first = [A.held_out("UC1", k) for k in keys]
    assert first == [A.held_out("UC1", k) for k in keys]
    share = sum(first) / len(keys)
    assert abs(share - A.CONTROL_SHARE) < 0.03
    assert first != [A.held_out("UC3", k) for k in keys]  # each audience draws its own control group


def test_control_group_holds_out_whole_households():
    members = {f"c{i}": (f"h{i // 3}", "why") for i in range(300)}
    out = A.finalise("UCX", members, AS_OF)
    by_hh = {}
    for r in out:
        by_hh.setdefault(r["household_id"], set()).add(r["slice"])
    assert all(len(s) == 1 for s in by_hh.values())  # never split a household
    assert 0 < sum(r["slice"] == A.CONTROL for r in out) < len(out)
    assert sum(r["household_primary"] for r in out) == len(by_hh)  # one mail piece per household


def test_customers_without_a_household_are_their_own_household():
    out = A.finalise("UCX", {"c1": (None, "why"), "c2": (None, "why")}, AS_OF)
    assert all(r["household_primary"] for r in out)


def test_file_name_and_export_are_spreadsheet_safe(tmp_path):
    uc = A.use_cases(AS_OF)[4]
    assert A.file_name(uc) == "UC6_customers_like_past_responders_proxy.csv"
    A.export(
        tmp_path / "x.csv",
        [{"customer_id": "c1", "household_id": None, "slice": "CAMPAIGN", "household_primary": True, "reason": "=HYPERLINK(evil)", "as_of": AS_OF}],
    )
    row = next(csv.DictReader((tmp_path / "x.csv").open()))
    assert row["reason"] == "'=HYPERLINK(evil)"


def test_run_writes_audiences_edges_csvs_and_summary(tmp_path):
    db = FakeEngine([("max(a.close_date)", [["C1", "H1", "2026-08-01"], ["C6", "H1", "2026-08-01"]])])
    summary = A.run(db, AS_OF, tmp_path, log=lambda _: None)
    assert [s["use_case"] for s in summary] == ["UC1", "UC3", "UC4", "UC5", "UC6", "UC7"]
    assert summary[0]["customers"] == 2 and summary[0]["households"] == 1
    creates = [q for q in db.queries if q.startswith("CREATE (:Audience")]
    assert len(creates) == 6 and all("synthetic: true" in q for q in creates)
    assert sum("IN_AUDIENCE" in q for q in db.queries) == 1  # only UC1 has members
    assert len(list(tmp_path.glob("UC*.csv"))) == 6
    assert json.loads((tmp_path / "audience_summary.json").read_text()) == summary
