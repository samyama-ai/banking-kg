"""The schema file, the demo question files, and one live check against a loaded engine.

The live test runs only when BANKING_KG_LIVE=1 (it reads the audiences the loader exported and the bank
tables under BANKING_KG_DATA / config.DATA_DIR)."""

import os
import re

import pytest

from etl import config
from etl.helpers import statements
from etl.verify import expected, graph_members
from tests.conftest import ROOT

SCHEMA = ROOT / "schema" / "banking_kg.cypher"
DEMO = ROOT / "demo"
LABELS, RELATIONSHIPS = 29, 33


def code_labels_and_relationships():
    code = "".join((ROOT / "etl" / f).read_text() for f in ("market.py", "bank.py", "bridge.py", "audiences.py"))
    labels = set(re.findall(r'g\.node\(\s*"([A-Za-z]+)"', code)) | {"Audience"}
    rels = set(re.findall(r'g\.edge\(\s*"([A-Z_]+)"', code)) | set(re.findall(r'create_edges\(\s*db,\s*"([A-Z_]+)"', code))
    return labels, rels | {"SENDS_TO", "RECEIVES_FROM", "PAID_BY"}  # chosen at run time in etl.bank


def test_schema_has_one_idempotent_constraint_per_label():
    s = statements(SCHEMA)
    assert len(s) == LABELS and all(x.startswith("CREATE CONSTRAINT") and "IF NOT EXISTS" in x for x in s)
    assert len({x.split()[2] for x in s}) == LABELS  # constraint names are unique


def test_schema_documents_every_label_and_relationship_the_code_creates():
    schema = SCHEMA.read_text()
    labels, rels = code_labels_and_relationships()
    assert len(labels) == LABELS, sorted(labels)
    assert len(rels) == RELATIONSHIPS, sorted(rels)
    assert [x for x in labels if f"(:{x} " not in schema and f"(:{x})" not in schema] == []
    assert [r for r in rels if f":{r} " not in schema and f":{r}]" not in schema] == []
    constrained = {re.search(r"FOR \(n:(\w+)\)", x).group(1) for x in statements(SCHEMA)}
    assert constrained == labels


def test_demo_questions_have_an_options_line_and_return_graph_variables():
    text = (DEMO / "queries.cypher").read_text()
    blocks = re.findall(r"// (Q\d+) · .*\n// (walk=\d+.*)\n((?:[^/\n].*\n)+)", text)
    assert [b[0] for b in blocks] == [f"Q{i}" for i in range(1, 19)]
    assert all(re.search(r"RETURN \w+(, \w+)+", b[2]) for b in blocks)


def test_demo_tables_have_header_separators():
    for name in ("vectors.md", "nlq.md", "algorithms.md"):
        lines = (DEMO / name).read_text().splitlines()
        heads = [i for i, line in enumerate(lines) if line.startswith("| #")]
        assert heads and all(lines[i + 1].startswith("|---") for i in heads), name


@pytest.mark.skipif(os.environ.get("BANKING_KG_LIVE") != "1", reason="set BANKING_KG_LIVE=1 after loading an engine")
def test_live_graph_audiences_match_independent_calculation():
    assert graph_members(config.DATA_DIR / config.AUDIENCE_DIR_NAME) == expected(config.DATA_DIR / config.BANK_DIR_NAME)
