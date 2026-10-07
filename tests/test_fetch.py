"""etl.fetch: every download is faked; the tests check parsing, batching, error translation and the files written."""

import json
import urllib.error

import pytest

from etl import config, fetch
from tests.conftest import FakeResponse

SBA_PAGE = (
    '<a href="https://data.sba.gov/sites/default/files/uploaded_resources/FOIA_7a_FY2020_Present_asof_260630.csv">7a</a>'
    '<a href="https://data.sba.gov/sites/default/files/uploaded_resources/FOIA_504_FY2010_Present_asof_260630.csv">504</a>'
)


def test_get_translates_network_errors(monkeypatch):
    def refuse(*a, **k):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(fetch, "open_url", refuse)
    with pytest.raises(fetch.FetchError, match="refused"):
        fetch.get("https://x.example/")


def test_get_refuses_non_http_urls_before_opening():
    with pytest.raises(fetch.FetchError, match="not an http"):
        fetch.get("file:///etc/passwd")


def test_get_sends_the_user_agent_and_returns_the_body(monkeypatch):
    seen = {}

    def ok(url, headers=None, timeout=None, **k):
        seen.update(url=url, headers=headers, timeout=timeout)
        return FakeResponse(b"body")

    monkeypatch.setattr(fetch, "open_url", ok)
    assert fetch.get("https://x.example/", {"Accept": "a"}) == b"body"
    assert seen["headers"] == {"User-Agent": config.USER_AGENT, "Accept": "a"} and seen["timeout"] == config.TIMEOUT_FETCH_S


def test_get_json_rejects_non_json(monkeypatch):
    monkeypatch.setattr(fetch, "get", lambda *a, **k: b"<html>")
    with pytest.raises(fetch.FetchError, match="not JSON"):
        fetch.get_json("https://x.example/")


def test_gleif_records_pages_and_parses(monkeypatch):
    monkeypatch.setattr(config, "GLEIF_PAUSE_S", 0)
    monkeypatch.setattr(config, "GLEIF_BATCH", 2)
    urls = []

    def answer(url, headers=None):
        urls.append(url)
        return {
            "data": [
                {
                    "attributes": {
                        "lei": "L1",
                        "registration": {"status": "ISSUED"},
                        "entity": {
                            "legalName": {"name": "ALPHA BANK"},
                            "headquartersAddress": {"city": "RICHMOND", "region": "US-VA"},
                            "legalForm": {"id": "XYZ"},
                            "status": "ACTIVE",
                            "jurisdiction": "US",
                            "category": "GENERAL",
                        },
                    }
                }
            ]
        }

    monkeypatch.setattr(fetch, "get_json", answer)
    out = fetch.gleif_records(["L1", "L2", "L3"])
    assert len(urls) == 2  # 3 LEIs in pages of 2
    assert out["L1"] == {
        "legal_name": "ALPHA BANK",
        "jurisdiction": "US",
        "status": "ACTIVE",
        "legal_form": "XYZ",
        "hq_city": "RICHMOND",
        "hq_region": "US-VA",
        "category": "GENERAL",
        "reg_status": "ISSUED",
    }


def test_sba_links_found_and_missing():
    links = fetch.sba_links(SBA_PAGE)
    assert set(links) == {"sba_7a_fy2020_present.csv", "sba_504_fy2010_present.csv"}
    assert links["sba_7a_fy2020_present.csv"].endswith("FOIA_7a_FY2020_Present_asof_260630.csv")
    with pytest.raises(fetch.FetchError, match="no longer links"):
        fetch.sba_links("<html>nothing here</html>")


def test_sba_certs_reads_one_state(tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("BorrState,BankFDICNumber\nDC,101\nDC,\nMD,999\nDC,abc\nDC,202\n")
    assert fetch.sba_certs(f, "DC") == {101, 202}


def test_financials_batches_certificates(monkeypatch):
    monkeypatch.setattr(config, "FDIC_CERT_BATCH", 2)
    urls = []
    monkeypatch.setattr(fetch, "get_json", lambda url: urls.append(url) or {"data": [{"data": {"CERT": 1}}]})
    assert fetch.financials({3, 1, 2}, 2023) == [{"CERT": 1}, {"CERT": 1}]
    assert len(urls) == 2 and "20221231" in urls[0] and "20231231" in urls[0]


def test_fetch_writes_every_source(monkeypatch, tmp_path):
    def body(url, headers=None, timeout=None):
        if "view/csv" in url:
            return b"lei,action_taken\nL1,1\nL1,3\n"
        if url == config.SBA_DATASET_PAGE:
            return SBA_PAGE.encode()
        if "FOIA_7a" in url:
            return b"BorrState,BankFDICNumber\nDC,101\n"
        return b"x"

    def as_json(url, headers=None):
        if "filers" in url:
            return {"institutions": [{"lei": "L1", "name": "Alpha Bank", "count": 2}]}
        if "institutions" in url:
            return {"data": [{"data": {"NAME": "Alpha Bank", "CERT": "101", "STALP": "VA", "CITY": "Richmond"}}]}
        return {"data": []}

    monkeypatch.setattr(fetch, "get", body)
    monkeypatch.setattr(fetch, "get_json", as_json)
    monkeypatch.setattr(config, "GLEIF_PAUSE_S", 0)
    lines = []
    fetch.fetch(tmp_path, "DC", 2023, lines.append)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == [
        "fdic_active_institutions.json",
        "fdic_financials_2022q4_2023q4.json",
        "filers_dc_2023.json",
        "gleif_dc_2023.json",
        "hmda_dc_2023.csv",
        "sba_504_fy2010_present.csv",
        "sba_7a_fy2020_present.csv",
    ]
    assert lines[0] == "HMDA DC 2023: 2 records"
    assert json.loads((tmp_path / "filers_dc_2023.json").read_text())["institutions"][0]["lei"] == "L1"


def test_main_reports_a_fetch_error(monkeypatch, tmp_path, capsys):
    def fail(*a, **k):
        raise fetch.FetchError("source moved")

    monkeypatch.setattr(fetch, "fetch", fail)
    assert fetch.main(["--data", str(tmp_path)]) == 1
    assert "source moved" in capsys.readouterr().err
    monkeypatch.setattr(fetch, "fetch", lambda *a, **k: None)
    assert fetch.main(["--data", str(tmp_path), "--state", "dc"]) == 0


def test_fetch_refuses_a_state_that_is_not_a_postal_code(tmp_path):
    with pytest.raises(ValueError, match="state code"):
        fetch.fetch(tmp_path, "../../etc", 2023)
    assert fetch.main(["--data", str(tmp_path), "--state", "../x"]) == 1
