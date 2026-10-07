"""Download the four public sources for one state-year into a data directory (outside the repo).

    python -m etl.fetch --data ../data/banking-kg --state DC --year 2023

Writes, all public and keyless (source URLs and limits: etl/config.py):
  hmda_<st>_<yr>.csv               CFPB HMDA data-browser API (LAR, 99 columns)
  filers_<st>_<yr>.json            CFPB HMDA filers for that state-year (LEI, name, count)
  gleif_<st>_<yr>.json             GLEIF lei-records for every filer
  fdic_active_institutions.json    FDIC BankFind, all active institutions (name match to LEI)
  sba_7a_*.csv, sba_504_*.csv      SBA 7(a) FY2020+ and 504 FY2010+ FOIA, links read off the dataset page
  fdic_financials_*.json           FDIC financials for every matched or SBA certificate, <yr-1>Q4 .. <yr>Q4

Spec §3: SBA's documented URLs go stale, so the links are read from the SBA dataset page on every run
rather than hard-coded.
"""

import argparse
import csv
import json
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse

from etl import config
from etl import identity as I
from etl.helpers import open_url


class FetchError(RuntimeError):
    """A source could not be downloaded, or no longer looks the way this module expects."""


def get(url, headers=None, timeout=config.TIMEOUT_FETCH_S) -> bytes:
    """GET an http(s) URL and return the body."""
    try:
        with open_url(url, headers={"User-Agent": config.USER_AGENT, **(headers or {})}, timeout=timeout) as r:
            return r.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError) as e:
        raise FetchError(f"{url}: {e}") from None


def get_json(url, headers=None, timeout=config.TIMEOUT_FETCH_S):
    """GET a URL and decode its JSON body."""
    body = get(url, headers, timeout)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise FetchError(f"{url}: reply is not JSON: {body[: config.ERROR_SNIPPET]!r}") from None


def gleif_records(leis):
    """{lei: summary} for every LEI GLEIF knows, queried in pages of config.GLEIF_BATCH."""
    out = {}
    for i in range(0, len(leis), config.GLEIF_BATCH):
        q = urllib.parse.urlencode({"filter[lei]": ",".join(leis[i : i + config.GLEIF_BATCH]), "page[size]": str(config.GLEIF_BATCH)})
        for rec in get_json(f"{config.GLEIF_URL}?{q}", {"Accept": "application/vnd.api+json"}).get("data", []):
            at, e = rec["attributes"], rec["attributes"]["entity"]
            hq = e.get("headquartersAddress") or {}
            out[at["lei"]] = {
                "legal_name": e["legalName"]["name"],
                "jurisdiction": e.get("jurisdiction"),
                "status": e.get("status"),
                "legal_form": (e.get("legalForm") or {}).get("id"),
                "hq_city": hq.get("city"),
                "hq_region": hq.get("region"),
                "category": e.get("category"),
                "reg_status": (at.get("registration") or {}).get("status"),
            }
        time.sleep(config.GLEIF_PAUSE_S)
    return out


def sba_links(page: str) -> dict:
    """{output file name: download URL} for each file in config.SBA_FILES, read off the dataset page."""
    links = sorted(set(re.findall(config.SBA_LINK_RX, page)))
    out = {}
    for pattern, name in config.SBA_FILES:
        hit = next((u for u in links if pattern in u), None)
        if hit is None:
            raise FetchError(f"SBA dataset page no longer links a {pattern} file - check {config.SBA_DATASET_PAGE}")
        out[name] = hit
    return out


def sba_certs(path: pathlib.Path, state: str) -> set:
    """FDIC certificates of the lenders behind a state's SBA 7(a) loans."""
    with open(path, encoding="latin-1", newline="") as fh:
        return {int(r["BankFDICNumber"]) for r in csv.DictReader(fh) if r["BorrState"] == state and r["BankFDICNumber"].strip().isdigit()}


def financials(certs, year):
    """FDIC financial rows (Call Report figures) for the certificates, from <year-1>Q4 to <year>Q4."""
    rows, cl = [], sorted(certs)
    for i in range(0, len(cl), config.FDIC_CERT_BATCH):
        flt = f"CERT:({' OR '.join(map(str, cl[i : i + config.FDIC_CERT_BATCH]))}) AND REPDTE:[{year - 1}1231 TO {year}1231]"
        q = urllib.parse.urlencode({"filters": flt, "fields": config.FDIC_FINANCIAL_FIELDS, "limit": str(config.FDIC_LIMIT), "format": "json"})
        rows += [x["data"] for x in get_json(f"{config.FDIC_FINANCIALS_URL}?{q}").get("data", [])]
    return rows


def fetch(d: pathlib.Path, st: str, yr: int, log=print):
    """Download every source for one state-year into d."""
    st = config.check_state(st)
    d.mkdir(parents=True, exist_ok=True)
    s = st.lower()
    hmda = get(config.HMDA_CSV_URL.format(year=yr, state=st))
    (d / f"hmda_{s}_{yr}.csv").write_bytes(hmda)
    log(f"HMDA {st} {yr}: {hmda.count(b'\n') - 1:,} records")
    filers = get_json(config.HMDA_FILERS_URL.format(year=yr, state=st))
    (d / f"filers_{s}_{yr}.json").write_text(json.dumps(filers))
    leis = [f["lei"] for f in filers.get("institutions", [])]

    gleif = gleif_records(leis)
    (d / f"gleif_{s}_{yr}.json").write_text(json.dumps(gleif))
    log(f"GLEIF: {len(gleif)} of {len(leis)} LEIs resolved")

    fdic = [x["data"] for x in get_json(config.FDIC_INSTITUTIONS_URL.format(limit=config.FDIC_LIMIT)).get("data", [])]
    (d / "fdic_active_institutions.json").write_text(json.dumps(fdic))
    log(f"FDIC active institutions: {len(fdic):,}")

    for name, url in sba_links(get(config.SBA_DATASET_PAGE).decode("utf-8", "replace")).items():
        (d / name).write_bytes(get(url, timeout=config.TIMEOUT_SBA_DOWNLOAD_S))
        log(f"SBA {name} <- {url}")

    idx = I.fdic_index(fdic)
    certs = {int(r["CERT"]) for f in filers.get("institutions", []) if (r := I.match(f["lei"], f["name"], gleif, idx))}
    certs |= sba_certs(d / config.SBA_FILES[0][1], st)
    rows = financials(certs, yr)
    (d / f"fdic_financials_{yr - 1}q4_{yr}q4.json").write_text(json.dumps(rows))
    log(f"FDIC financials: {len(rows):,} quarterly filings for {len(certs)} certificates")


def main(argv=None):
    """CLI entry point; returns the process exit code."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=pathlib.Path, default=config.DATA_DIR)
    ap.add_argument("--state", default=config.STATE)
    ap.add_argument("--year", type=int, default=config.YEAR)
    a = ap.parse_args(argv)
    try:
        fetch(a.data, a.state, a.year)
    except (FetchError, ValueError) as e:
        print(f"fetch failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
