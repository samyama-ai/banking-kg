"""benchmarks.run: question parsing, timing, the report and the command line."""

from benchmarks import run
from etl.helpers import EngineError
from tests.conftest import FakeEngine


def test_questions_parses_blocks(tmp_path):
    f = tmp_path / "q.cypher"
    f.write_text("// header\n\n// Q1 · First question [spec 1]\n// walk=2\nMATCH (n)\nRETURN n\n\n// Q2 · Second\nRETURN 2\n")
    assert run.questions(f) == [("Q1 First question", "MATCH (n) RETURN n"), ("Q2 Second", "RETURN 2")]


def test_the_demo_question_set_has_eighteen_questions():
    qs = run.questions()
    assert [label.split()[0] for label, _ in qs] == [f"Q{i}" for i in range(1, 19)]
    assert all("RETURN" in cy for _, cy in qs)


def test_timed_and_report():
    n, mn, md = run.timed(FakeEngine([("RETURN", [[1], [2]])]), "RETURN 1", 3)
    assert n == 2 and 0 <= mn <= md
    text = run.report([("Q1 x", 2, 1.0, 1.5)], "1.7.1", "g", 10, 20, 3)
    assert "| Q1 x | 2 | 1.0 | 1.5 |" in text and "Samyama engine 1.7.1, graph `g`: 10 nodes / 20 relationships" in text


def test_main_writes_results(monkeypatch, tmp_path):
    db = FakeEngine([("count(n)", [[10]]), ("count(r)", [[20]]), ("a.as_of", [["2026-08-31"]])])
    db.status = lambda: {"version": "1.7.1"}
    monkeypatch.setattr(run, "Engine", lambda url, graph: db)
    monkeypatch.setattr(run, "RESULTS", tmp_path / "results.md")
    assert run.main(["--runs", "1"]) == run.EXIT_OK
    text = (tmp_path / "results.md").read_text()
    assert "| Q18 " in text and "| UC7 Money leaving to competitors |" in text


def test_main_reports_an_unreachable_engine(monkeypatch, capsys):
    def down(url, graph):
        raise EngineError("engine not reachable")

    monkeypatch.setattr(run, "Engine", down)
    assert run.main([]) == run.EXIT_UNREACHABLE
    assert "not reachable" in capsys.readouterr().err
