"""etl.embed: profiles, Ollama calls (faked), vector writes, the embed config and the command line."""

import json
import urllib.error

import pytest

from etl import config, embed
from etl.helpers import EngineError
from tests.conftest import FakeEngine, FakeResponse

PROFILE_ANSWERS = [
    ("RETURN l.id, l.name, l.lender_type", [["L1", "Alpha Bank", "Bank", "Richmond", "VA"], ["B", "Banking-KG Bank", "Bank", None, None]]),
    ("RETURN l.id, count(n)", [["L1", 4]]),
    ("SOLD_TO", [["L1", "Fannie Mae", 3]]),
    ("FOR_PRODUCT", [["L1", "Conventional:First Lien", 4]]),
    ("IN_INDUSTRY", [["L1", "Full-Service Restaurants", 2]]),
    ("HAS_LOAN", [["B", "MORTGAGE", 5], ["B", "AUTO", 2]]),
]


def test_profiles_describe_each_book():
    prof = embed.profiles(FakeEngine(PROFILE_ANSWERS), "DC", 2023)
    assert prof["L1"] == (
        "Alpha Bank, bank headquartered in Richmond, VA. 4 DC mortgages originated in 2023, mostly conventional, first lien. "
        "Keeps 25% of its loans on balance sheet, sells mainly to Fannie Mae. SBA business lending in full-service restaurants."
    )
    assert prof["B"] == "Banking-KG Bank, bank. Retail and commercial book of 5 mortgage, 2 auto loans."


def fake_ollama(monkeypatch, reply):
    """Patch open_url so Ollama answers with reply (bytes) or raises it (an exception)."""

    def opener(url, data=None, headers=None, timeout=None, **k):
        if isinstance(reply, Exception):
            raise reply
        return FakeResponse(reply)

    monkeypatch.setattr(embed, "open_url", opener)


def test_ollama_returns_one_vector_per_text(monkeypatch):
    fake_ollama(monkeypatch, json.dumps({"embeddings": [[0.1], [0.2]]}).encode())
    assert embed.ollama("http://o:1", "m", ["a", "b"]) == [[0.1], [0.2]]


@pytest.mark.parametrize("reply", [urllib.error.URLError("refused"), b"not json", json.dumps({"embeddings": [[0.1]]}).encode(), b"{}"])
def test_ollama_failures_are_embed_errors(monkeypatch, reply):
    fake_ollama(monkeypatch, reply)
    with pytest.raises(embed.EmbedError):
        embed.ollama("http://o:1", "m", ["a", "b"])


def test_write_batches_set_statements():
    db = FakeEngine()
    rows = [(f"id{i}", "t") for i in range(5)]
    embed.write(db, "Industry", rows, [[0.1234567]] * 5, batch=2)
    assert len(db.queries) == 3
    assert db.queries[0].startswith("MATCH (n0:Industry), (n1:Industry) WHERE n0.id = 'id0' AND n1.id = 'id1' SET n0.embedding = [0.123457]")
    with pytest.raises(ValueError):
        embed.write(db, "Bad Label", rows, [[0.1]] * 5)


def test_texts_writes_profiles_and_skips_empty_labels():
    db = FakeEngine([*PROFILE_ANSWERS, ("MATCH (n:Industry)", [["722511", "Full-Service Restaurants", "722511"]])])
    rows = embed.texts(db, "DC", 2023)
    assert set(rows) == {"Lender", "Industry"}
    assert rows["Industry"] == [("722511", "Full-Service Restaurants (NAICS 722511)")]
    assert sum("SET l.profile" in q for q in db.queries) == 2


def test_embed_config():
    cfg = embed.embed_config("http://host.docker.internal:11434", "all-minilm", 384, ["Lender", "Product"])
    assert cfg["vector_dimension"] == 384 and cfg["chunk_size"] == config.EMBED_CHUNK_SIZE
    assert cfg["embedding_policies"] == {"Lender": ["name"], "Product": ["name"]}
    with pytest.raises(ValueError):
        embed.embed_config("file:///x", "m", 1, [])


def test_run_indexes_embeds_and_rebuilds(monkeypatch):
    monkeypatch.setattr(embed, "ollama", lambda url, model, texts: [[0.0]] * len(texts))
    db = FakeEngine(PROFILE_ANSWERS)
    assert embed.run(db, "http://o:1", "http://o:1", "m", 384, "DC", 2023, log=lambda _: None) == 2
    assert db.posts[0][0] == "/api/tenants/t" and db.posts[0][2]["method"] == "PATCH"
    assert db.posts[-1][0] == "/api/tenants/t/vector-index/rebuild"  # the rebuild comes last
    assert any(q.startswith("CREATE VECTOR INDEX lender_embedding") for q in db.queries)


def test_main_exit_codes(monkeypatch, capsys):
    def fail(*a, **k):
        raise EngineError("engine not reachable")

    monkeypatch.setattr(embed, "run", fail)
    assert embed.main(["--url", "http://e:1"]) == embed.EXIT_UNREACHABLE
    assert "not reachable" in capsys.readouterr().err
    assert embed.main(["--url", "file:///x"]) == embed.EXIT_UNREACHABLE
    monkeypatch.setattr(embed, "run", lambda *a, **k: 0)
    assert embed.main(["--url", "http://e:1"]) == embed.EXIT_OK
