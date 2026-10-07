"""Download the four public sources for one state-year into a data directory (outside the repo).

    python -m etl.fetch --data ../data/banking-kg --state DC --year 2023

Writes, all public and keyless:
  hmda_<st>_<yr>.csv               CFPB HMDA data-browser API (LAR, 99 columns)
  filers_<st>_<yr>.json            CFPB HMDA filers for that state-year (LEI, name, count)
  gleif_<st>_<yr>.json             GLEIF lei-records for every filer
  fdic_active_institutions.json    FDIC BankFind, all active institutions (name match to LEI)
  sba_7a_*.csv, sba_504_*.csv      SBA 7(a) FY2020+ and 504 FY2010+ FOIA, links read off the dataset page
  fdic_financials_*.json           FDIC financials for every matched or SBA certificate, <yr-1>Q4 .. <yr>Q4

Spec §3: SBA's documented URLs go stale, so the links are read from https://data.sba.gov/dataset/7a-504-foia
on every run rather than hard-coded.
"""
import argparse
import csv
import json
import pathlib
import re
import time
import urllib.parse
import urllib.request

from etl import identity as I

UA = {"User-Agent": "Mozilla/5.0 (banking-kg fetch)"}


def get(url, headers=None, timeout=300):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=pathlib.Path, required=True)
    ap.add_argument("--state", default="DC")
    ap.add_argument("--year", type=int, default=2023)
    a = ap.parse_args()
    d, st, yr = a.data, a.state.upper(), a.year
    d.mkdir(parents=True, exist_ok=True)
    s = st.lower()

    hmda = get(f"https://ffiec.cfpb.gov/v2/data-browser-api/view/csv?years={yr}&states={st}")
    (d / f"hmda_{s}_{yr}.csv").write_bytes(hmda)
    print(f"HMDA {st} {yr}: {hmda.count(b'\n') - 1:,} records")
    filers = json.loads(get(f"https://ffiec.cfpb.gov/v2/data-browser-api/view/filers?years={yr}&states={st}"))
    (d / f"filers_{s}_{yr}.json").write_text(json.dumps(filers))
    leis = [f["lei"] for f in filers["institutions"]]

    gleif = {}
    for i in range(0, len(leis), 100):
        q = urllib.parse.urlencode({"filter[lei]": ",".join(leis[i:i + 100]), "page[size]": "100"})
        for rec in json.loads(get("https://api.gleif.org/api/v1/lei-records?" + q, {"Accept": "application/vnd.api+json"}))["data"]:
            at, e = rec["attributes"], rec["attributes"]["entity"]
            hq = e.get("headquartersAddress") or {}
            gleif[at["lei"]] = {"legal_name": e["legalName"]["name"], "jurisdiction": e.get("jurisdiction"), "status": e.get("status"),
                                "legal_form": (e.get("legalForm") or {}).get("id"), "hq_city": hq.get("city"),
                                "hq_region": hq.get("region"), "category": e.get("category"), "reg_status": at["registration"]["status"]}
        time.sleep(0.5)
    (d / f"gleif_{s}_{yr}.json").write_text(json.dumps(gleif))
    print(f"GLEIF: {len(gleif)} of {len(leis)} LEIs resolved")

    fdic = [x["data"] for x in json.loads(get("https://banks.data.fdic.gov/api/institutions?filters=ACTIVE:1"
                                               "&fields=NAME,CERT,FED_RSSD,ASSET,CITY,STALP,BKCLASS&limit=10000&format=json"))["data"]]
    (d / "fdic_active_institutions.json").write_text(json.dumps(fdic))
    print(f"FDIC active institutions: {len(fdic):,}")

    page = get("https://data.sba.gov/dataset/7a-504-foia").decode("utf-8", "replace")
    links = sorted(set(re.findall(r'https://data\.sba\.gov/sites/default/files/uploaded_resources/FOIA_[^"]+\.csv', page)))
    for pat, out in ((r"FOIA_7a_FY2020_Present", "sba_7a_fy2020_present.csv"), (r"FOIA_504_FY2010_Present", "sba_504_fy2010_present.csv")):
        url = next(u for u in links if pat in u)
        (d / out).write_bytes(get(url, timeout=1800))
        print(f"SBA {out} <- {url}")

    idx = I.fdic_index(fdic)
    certs = {int(r["CERT"]) for f in filers["institutions"] if (r := I.match(f["lei"], f["name"], gleif, idx))}
    with open(d / "sba_7a_fy2020_present.csv", encoding="latin-1", newline="") as fh:
        certs |= {int(r["BankFDICNumber"]) for r in csv.DictReader(fh) if r["BorrState"] == st and r["BankFDICNumber"].strip().isdigit()}
    fields = "CERT,REPDTE,NAME,ASSET,DEP,LNLSNET,LNRE,LNRERES,LNCI,LNCON,LNATRES,NTLNLS"
    rows, cl = [], sorted(certs)
    for i in range(0, len(cl), 40):
        flt = f"CERT:({' OR '.join(map(str, cl[i:i + 40]))}) AND REPDTE:[{yr - 1}1231 TO {yr}1231]"
        u = "https://banks.data.fdic.gov/api/financials?" + urllib.parse.urlencode({"filters": flt, "fields": fields, "limit": "10000", "format": "json"})
        rows += [x["data"] for x in json.loads(get(u))["data"]]
    (d / f"fdic_financials_{yr - 1}q4_{yr}q4.json").write_text(json.dumps(rows))
    print(f"FDIC financials: {len(rows):,} quarterly filings for {len(certs)} certificates")


if __name__ == "__main__":
    main()
