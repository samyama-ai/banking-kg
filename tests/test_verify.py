"""etl.verify: the independent recalculation, the answer key and the command line."""

import csv

import pytest

from etl import verify
from tests import bank_fixture


def write_audiences(d, members: dict):
    """Audience CSVs as the loader writes them: {code: [customer ids]}."""
    d.mkdir(parents=True, exist_ok=True)
    for code, ids in members.items():
        with (d / f"{code}_x.csv").open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["customer_id"])
            w.writeheader()
            w.writerows({"customer_id": i} for i in ids)
    return d


def test_independent_answers_match_the_fixture(bank_dir):
    assert verify.expected(bank_dir) == bank_fixture.EXPECTED


def test_graph_members_reads_the_exported_csvs(tmp_path):
    d = write_audiences(tmp_path / "aud", {"UC1": ["C1", "C6"], "UC3": ["C5"]})
    assert verify.graph_members(d) == {"UC1": {"C1", "C6"}, "UC3": {"C5"}}
    with pytest.raises(FileNotFoundError, match=r"etl\.loader"):
        verify.graph_members(tmp_path / "missing")


def test_answer_key_is_optional_and_checked_when_present(bank_dir, tmp_path):
    assert verify.answer_key_checks(bank_dir, {}) == []
    root = bank_fixture.write_fixture(tmp_path / "bank")
    (root / "_answer_key").mkdir()
    (root / "_answer_key" / "planted_patterns.csv").write_text(
        "pattern,customer_key,related_customer_key,account_key,detail\nESTATE_BENEFICIARY,C4,C5,A4,x\nNEXT_GEN,C1,C3,A1,x\nFRIENDS_JOINT,C7,C8,A8,x\n"
    )
    checks = verify.answer_key_checks(root, {"UC3": {"C5"}, "UC4": {"C3"}})
    assert [(hit, total) for _, hit, total in checks] == [(1, 1), (1, 1), (1, 1)]


def test_compare_reports_differences():
    lines = []
    assert verify.compare({"UC1": {"a"}}, {"UC1": {"a"}}, [("k", 1, 1)], lines.append)
    assert not verify.compare({"UC1": {"a"}}, {"UC1": {"b"}}, [], lines.append)
    assert "DIFF UC1" in lines[-1] and "only-graph ['b']" in lines[-1]
    assert not verify.compare({}, {}, [("planted", 0, 2)], lines.append)


def test_main_exit_codes(bank_dir, tmp_path):
    good = write_audiences(tmp_path / "good", {k: sorted(v) for k, v in bank_fixture.EXPECTED.items()})
    assert verify.main(["--data-dir", str(bank_dir), "--audiences", str(good)]) == verify.EXIT_OK
    bad = write_audiences(tmp_path / "bad", {"UC1": ["C1"]})
    assert verify.main(["--data-dir", str(bank_dir), "--audiences", str(bad)]) == verify.EXIT_DIFF
    assert verify.main(["--data-dir", str(tmp_path / "none"), "--audiences", str(good)]) == verify.EXIT_INPUT
