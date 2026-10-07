"""etl.config: URL checking and environment overrides."""

import importlib

import pytest

from etl import config


@pytest.mark.parametrize("url", ["http://localhost:8081", "https://api.gleif.org/api/v1/lei-records", "http://10.0.0.5:8080/x?y=1"])
def test_check_url_accepts_http_and_https(url):
    assert config.check_url(url) == url


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.com/x", "localhost:8081", "http://", "", "javascript:alert(1)"])
def test_check_url_rejects_other_schemes_and_hostless_urls(url):
    with pytest.raises(ValueError, match="not an http"):
        config.check_url(url)


def test_environment_overrides_deployment_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("BANKING_KG_URL", "http://engine.example:9000")
    monkeypatch.setenv("BANKING_KG_GRAPH", "othergraph")
    monkeypatch.setenv("BANKING_KG_DATA", str(tmp_path))
    monkeypatch.setenv("BANKING_KG_YEAR", "2022")
    try:
        reloaded = importlib.reload(config)
        assert reloaded.ENGINE_URL == "http://engine.example:9000"
        assert reloaded.GRAPH == "othergraph"
        assert tmp_path == reloaded.DATA_DIR
        assert reloaded.YEAR == 2022
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_defaults_are_consistent():
    assert config.ENGINE_URL.startswith("http")
    assert config.TENANT_QUOTAS["max_memory_bytes"] == 4 * config.GIB
    assert config.EDGE_BATCH <= config.NODE_BATCH
    assert {name for _, name in config.SBA_FILES} == {"sba_7a_fy2020_present.csv", "sba_504_fy2010_present.csv"}


@pytest.mark.parametrize(("state", "out"), [("DC", "DC"), ("va", "VA"), (" md ", "MD")])
def test_check_state_accepts_postal_codes(state, out):
    assert config.check_state(state) == out


@pytest.mark.parametrize("state", ["", "D", "DCA", "../x", "D1", None])
def test_check_state_rejects_anything_else(state):
    with pytest.raises(ValueError, match="state code"):
        config.check_state(state)
