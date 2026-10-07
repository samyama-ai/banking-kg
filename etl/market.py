"""Market layer: the public lending market for one state-year, built in memory from four public sources.

    from etl.market import build; g = build(data_dir)     # g.nodes[label][id] = props, g.edges[rel] = [...]

Sources, all read from files already downloaded into data_dir (see etl/fetch.py):
  hmda_<st>_<yr>.csv                    HMDA LAR, CFPB data-browser API          -> Application, Loan, Tract ...
  filers_<st>_<yr>.json, gleif_*.json   HMDA filers + GLEIF lei-records          -> Lender, LegalEntity
  fdic_active_institutions.json         FDIC BankFind institutions               -> Lender.cert (by legal name)
  fdic_financials_*.json                FDIC financials (Call Report figures)    -> Filing
  sba_7a_*.csv, sba_504_*.csv           SBA 7(a) / 504 FOIA                      -> SBALoan, Business, Industry ...

Spec §5 rule that must not drift: every HMDA row is an Application; only action_taken = 1 is also a Loan.
Privacy: SBA borrowers filed as INDIVIDUAL (sole proprietors) get a generic name and no street address.
"""

import csv
import hashlib
import json
import pathlib
import re

from etl import config
from etl import identity as I
from etl.helpers import Graph
from etl.reference import COUNTY_NAMES, MSA_NAMES

# HMDA code lists (FFIEC filing instructions; spec §6)
ACTION = {
    1: "Loan originated",
    2: "Approved, not accepted",
    3: "Denied",
    4: "Withdrawn by applicant",
    5: "File closed, incomplete",
    6: "Purchased loan",
    7: "Preapproval denied",
    8: "Preapproval approved, not accepted",
}
ORIGINATED = 1  # the one action_taken code that makes a Loan
LOAN_TYPE = {1: "Conventional", 2: "FHA", 3: "VA", 4: "USDA RHS/FSA"}
PURPOSE = {1: "Home purchase", 2: "Home improvement", 31: "Refinancing", 32: "Cash-out refinancing", 4: "Other purpose", 5: "Not applicable"}
LIEN = {1: "First lien", 2: "Subordinate lien"}
OCCUPANCY = {1: "Principal residence", 2: "Second residence", 3: "Investment property"}
PURCHASER = {
    1: "Fannie Mae",
    2: "Ginnie Mae",
    3: "Freddie Mac",
    4: "Farmer Mac",
    5: "Private securitizer",
    6: "Commercial bank, savings bank or savings association",
    71: "Credit union, mortgage company or finance company",
    72: "Life insurance company",
    8: "Affiliate institution",
    9: "Other type of purchaser",
}
DENIAL = {
    1: "Debt-to-income ratio",
    2: "Employment history",
    3: "Credit history",
    4: "Collateral",
    5: "Insufficient cash (down payment, closing costs)",
    6: "Unverifiable information",
    7: "Credit application incomplete",
    8: "Mortgage insurance denied",
    9: "Other",
}
DENIAL_COLUMNS = ("denial_reason-1", "denial_reason-2", "denial_reason-3", "denial_reason-4")
OPEN_END_YES = 1
MISSING = ("", "NA")  # HMDA's empty and not-applicable values
DTI_MISSING = ("NA", "Exempt")
AGE_MISSING = ("NA", "8888", "9999")  # 8888 / 9999: not applicable / no co-applicant
# SBA FOIA LoanStatus codes
SBA_STATUS = {
    "PIF": "Paid in full",
    "P I F": "Paid in full",
    "NOT FUNDED": "Not funded",
    "CHGOFF": "Charged off",
    "EXEMPT": "Active (status exempt from disclosure)",
    "COMMIT": "Committed, not disbursed",
    "CANCLD": "Cancelled",
}
SBA_INDIVIDUAL = "INDIVIDUAL"  # BusinessType of a sole proprietor
NAICS_SECTOR_DIGITS = 2
ZIP5 = 5
# FDIC report dates (MMDD) -> quarter
QUARTER = {"0331": "Q1", "0630": "Q2", "0930": "Q3", "1231": "Q4"}
# id formats
APP_ID, LOAN_ID = "APP-{:06d}", "LOAN-{:06d}"
SBA7A_ID, SBA504_ID = "SBA7A-{:05d}", "SBA504-{:05d}"
BUSINESS_HASH_CHARS = 10
MILLION, THOUSAND = 1_000_000, 1_000


def num(v, typ=float):
    """v as a number of type typ, or None when it is missing or not numeric ('NA', 'Exempt', '')."""
    try:
        return typ(float(v))
    except (TypeError, ValueError):
        return None


def code(v):
    """A HMDA code as an int, or None."""
    return num(v, int)


def money(v):
    """A short dollar label for a node name: $1.2M or $455K."""
    v = v or 0
    return f"${v / MILLION:.1f}M" if v >= MILLION else f"${v / THOUSAND:.0f}K"


def title(s):
    """Title-case words that are all capitals; leave mixed-case words alone."""
    return " ".join(w.capitalize() if w.isupper() else w for w in (s or "").split())


def slug(s):
    """Upper-case, runs of non-alphanumerics replaced by '-', for ids built from names."""
    return re.sub(r"[^A-Z0-9]+", "-", s.upper()).strip("-")


def present(v):
    """v, or None when HMDA marks it missing."""
    return None if v in MISSING else v


def source(data: pathlib.Path, pattern: str) -> pathlib.Path:
    """The one file in data matching pattern; FileNotFoundError naming the fetch step otherwise."""
    hit = next(iter(sorted(data.glob(pattern))), None)
    if hit is None:
        raise FileNotFoundError(f"{data}/{pattern} not found - run `python -m etl.fetch --data {data}` first")
    return hit


def read_json(path: pathlib.Path):
    """Decode a JSON source file; FileNotFoundError naming the fetch step when it is missing."""
    if not path.exists():
        raise FileNotFoundError(f"{path} not found - run `python -m etl.fetch --data {path.parent}` first")
    return json.loads(path.read_text())


def build(data: pathlib.Path, state=config.STATE, year=config.YEAR) -> Graph:
    """The market layer for one state-year, from the files etl.fetch wrote into data."""
    state = config.check_state(state)
    g = Graph()
    s = state.lower()
    filers = read_json(data / f"filers_{s}_{year}.json").get("institutions", [])
    gleif = read_json(data / f"gleif_{s}_{year}.json")
    idx = I.fdic_index(read_json(data / "fdic_active_institutions.json"))
    fin = read_json(source(data, "fdic_financials_*.json"))
    latest = {}
    for r in fin:
        if r["CERT"] not in latest or r["REPDTE"] > latest[r["CERT"]]["REPDTE"]:
            latest[r["CERT"]] = r
    cert_to_id = add_lenders(g, filers, gleif, idx, latest)
    add_hmda(g, source(data, f"hmda_{s}_{year}.csv"), year)
    add_sba(g, source(data, "sba_7a_*.csv"), source(data, "sba_504_*.csv"), state, cert_to_id, latest)
    add_filings(g, fin, cert_to_id)
    return g


def add_lenders(g, filers, gleif, idx, latest) -> dict:
    """Lender + LegalEntity per HMDA filer; returns {FDIC certificate: lender id} for the certificates matched."""
    cert_to_id = {}
    for f in filers:
        lei, gl = f["lei"], gleif.get(f["lei"], {})
        row = I.match(lei, f["name"], gleif, idx)
        cert = int(row["CERT"]) if row else None
        g.node(
            "Lender",
            lei,
            name=f["name"],
            lei=lei,
            cert=cert,
            lender_type=I.lender_type(f["name"], row),
            hq_city=title(gl.get("hq_city") or ""),
            hq_state=(gl.get("hq_region") or "").replace(I.US_REGION_PREFIX, ""),
            hmda_applications=f.get("count"),
            assets_k=latest.get(cert, {}).get("ASSET") if cert else None,
        )
        g.node(
            "LegalEntity",
            lei,
            name=gl.get("legal_name", f["name"]),
            lei=lei,
            jurisdiction=gl.get("jurisdiction"),
            status=gl.get("status"),
            legal_form=gl.get("legal_form"),
            category=gl.get("category"),
        )
        g.edge("REGISTERED_AS", "Lender", lei, "LegalEntity", lei)
        if cert:
            cert_to_id[cert] = lei
    return cert_to_id


def add_hmda(g, path: pathlib.Path, year: int):
    """Application for every HMDA row; Loan, buyer and denial reasons where they apply; tract -> county -> MSA."""
    geo_seen = set()
    with open(path, newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh), 1):
            aid, act = APP_ID.format(i), code(r["action_taken"])
            amount = num(r["loan_amount"])
            g.node(
                "Application",
                aid,
                name=f"{(ACTION.get(act) or '').split(',')[0]} {money(amount)}",
                action=ACTION.get(act),
                action_code=act,
                loan_amount=amount,
                loan_to_value=num(r["loan_to_value_ratio"]),
                interest_rate=num(r["interest_rate"]),
                rate_spread=num(r["rate_spread"]),
                income_k=num(r["income"]),
                debt_to_income=None if r["debt_to_income_ratio"] in DTI_MISSING else r["debt_to_income_ratio"],
                loan_type=LOAN_TYPE.get(code(r["loan_type"])),
                purpose=PURPOSE.get(code(r["loan_purpose"])),
                lien=LIEN.get(code(r["lien_status"])),
                occupancy=OCCUPANCY.get(code(r["occupancy_type"])),
                property_value=num(r["property_value"]),
                dwelling=r["derived_dwelling_category"],
                applicant_race=r["derived_race"],
                applicant_ethnicity=r["derived_ethnicity"],
                applicant_sex=r["derived_sex"],
                applicant_age=None if r["applicant_age"] in AGE_MISSING else r["applicant_age"],
                open_end=code(r["open-end_line_of_credit"]) == OPEN_END_YES,
                year=year,
            )
            g.edge("FILED_WITH", "Application", aid, "Lender", r["lei"])
            prod = r["derived_loan_product_type"]
            g.node("LoanProduct", prod, name=prod)
            g.edge("FOR_PRODUCT", "Application", aid, "LoanProduct", prod)
            add_geography(g, r, aid, geo_seen)
            for k in DENIAL_COLUMNS:
                d = code(r[k])
                if d in DENIAL:
                    g.node("DenialReason", f"DR-{d}", name=DENIAL[d], code=d)
                    g.edge("DENIED_FOR", "Application", aid, "DenialReason", f"DR-{d}")
            if act == ORIGINATED:  # only an origination is a Loan (spec §5)
                add_loan(g, r, aid, LOAN_ID.format(i), year)


def add_geography(g, r, aid, seen):
    """Application -> Tract -> County -> MSA; each tract and county is linked upward once."""
    tract, county = present(r["census_tract"]), present(r["county_code"])
    if not tract:
        return
    g.node(
        "Tract",
        tract,
        name=f"Tract {tract[-6:-2]}.{tract[-2:]}",
        fips=tract,
        population=num(r["tract_population"], int),
        minority_pct=num(r["tract_minority_population_percent"]),
        income_pct_of_msa=num(r["tract_to_msa_income_percentage"]),
        msa_median_family_income=num(r["ffiec_msa_md_median_family_income"], int),
        owner_occupied_units=num(r["tract_owner_occupied_units"], int),
    )
    g.edge("IN_TRACT", "Application", aid, "Tract", tract)
    if not county or (tract, county) in seen:
        return
    seen.add((tract, county))
    g.node("County", county, name=COUNTY_NAMES.get(county, county), fips=county)
    g.edge("IN_COUNTY", "Tract", tract, "County", county)
    msa = present(r["derived_msa-md"])
    if msa and ("county", county) not in seen:
        seen.add(("county", county))
        g.node("MSA", msa, name=MSA_NAMES.get(msa, msa), code=msa)
        g.edge("IN_MSA", "County", county, "MSA", msa)


def add_loan(g, r, aid, lid, year):
    """The Loan an originated application became, its lender, and its buyer if it was sold."""
    g.node(
        "Loan",
        lid,
        name=f"Loan {money(num(r['loan_amount']))}",
        amount=num(r["loan_amount"]),
        interest_rate=num(r["interest_rate"]),
        rate_spread=num(r["rate_spread"]),
        term_months=num(r["loan_term"], int),
        loan_to_value=num(r["loan_to_value_ratio"]),
        loan_type=LOAN_TYPE.get(code(r["loan_type"])),
        purpose=PURPOSE.get(code(r["loan_purpose"])),
        total_loan_costs=num(r["total_loan_costs"]),
        year=year,
    )
    g.edge("ORIGINATED_AS", "Application", aid, "Loan", lid)
    g.edge("ORIGINATED_BY", "Loan", lid, "Lender", r["lei"])
    p = code(r["purchaser_type"])
    if p in PURCHASER:
        g.node("Purchaser", f"PUR-{p}", name=PURCHASER[p], code=p)
        g.edge("SOLD_TO", "Loan", lid, "Purchaser", f"PUR-{p}")


def business_id(r) -> str:
    """Stable id for an SBA borrower: sha1 of name + street + zip (not a security use)."""
    key = re.sub(r"[^A-Z0-9]+", " ", r["BorrName"].strip().upper() + "|" + r["BorrStreet"].strip().upper() + "|" + r["BorrZip"].strip()[:ZIP5])
    return "BIZ-" + hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest()[:BUSINESS_HASH_CHARS]


def add_sba(g, path_7a, path_504, state, cert_to_id, latest):
    """SBA 7(a) and 504 loans for one state: Business, Address, Industry, Franchise, lender or CDC."""
    linked = set()  # (business, address|industry): a business that took several loans is linked once per target

    def lender(name, cert, ncua):
        if cert and cert in cert_to_id:
            return cert_to_id[cert]
        nid = f"FDIC-{cert}" if cert else (f"NCUA-{ncua}" if ncua else "SBA-" + slug(name))
        if nid not in g.nodes["Lender"]:
            g.node(
                "Lender",
                nid,
                name=title(name),
                cert=cert,
                lender_type=I.BANK if cert else (I.CREDIT_UNION if ncua else I.NON_BANK),
                assets_k=latest.get(cert, {}).get("ASSET") if cert else None,
            )
            if cert:
                cert_to_id[cert] = nid
        return nid

    def business(r):
        indiv = r["BusinessType"].strip().upper() == SBA_INDIVIDUAL
        naics = r["NaicsCode"].strip()
        desc = title(r["NaicsDescription"].strip()) or None
        street, zipc = r["BorrStreet"].strip().upper(), r["BorrZip"].strip()[:ZIP5]
        bid = business_id(r)
        g.node(
            "Business",
            bid,
            name=f"Sole proprietor · {desc or 'business'}" if indiv else title(r["BorrName"].strip()),
            business_type=title(r["BusinessType"].strip()) or None,
            business_age=r["BusinessAge"].strip() or None,
            city=title(r["BorrCity"].strip()),
            zip=zipc,
            sole_proprietor=indiv,
        )
        if not indiv and street:
            aid = "ADDR-" + slug(f"{street} {zipc}")
            g.node("Address", aid, name=title(street), street=title(street), zip=zipc, city=title(r["BorrCity"].strip()))
            if (bid, aid) not in linked:
                linked.add((bid, aid))
                g.edge("LOCATED_AT", "Business", bid, "Address", aid)
        if naics:
            g.node("Industry", naics, name=desc or naics, naics=naics, sector=naics[:NAICS_SECTOR_DIGITS])
            if (bid, naics) not in linked:
                linked.add((bid, naics))
                g.edge("IN_INDUSTRY", "Business", bid, "Industry", naics)
        return bid

    def loan(r, sid, program, bid):
        status = r["LoanStatus"].strip()
        g.node(
            "SBALoan",
            sid,
            name=f"SBA {program} {money(num(r['GrossApproval']))}",
            program=program,
            gross_approval=num(r["GrossApproval"]),
            sba_guaranteed=num(r.get("SBAGuaranteedApproval")),
            approval_date=r["ApprovalDate"].strip() or None,
            fiscal_year=num(r["ApprovalFY"], int),
            interest_rate=num(r.get("InitialInterestRate")),
            term_months=num(r["TermInMonths"], int),
            status=SBA_STATUS.get(status, status or None),
            charge_off_amount=num(r["GrossChargeOffAmount"]) or None,
            jobs_supported=num(r["JobsSupported"], int),
        )
        g.edge("BORROWED", "Business", bid, "SBALoan", sid)
        fr = r["FranchiseName"].strip()
        if fr:
            fid = "FR-" + (r["FranchiseCode"].strip() or slug(fr))
            g.node("Franchise", fid, name=title(fr), code=r["FranchiseCode"].strip() or None)
            g.edge("UNDER_FRANCHISE", "SBALoan", sid, "Franchise", fid)

    with open(path_7a, encoding="latin-1", newline="") as fh:
        for i, r in enumerate((r for r in csv.DictReader(fh) if r["BorrState"] == state), 1):
            sid = SBA7A_ID.format(i)
            loan(r, sid, "7(a)", business(r))
            cert = num(r["BankFDICNumber"], int) or None
            ncua = num(r["BankNCUANumber"], int) or None
            g.edge("MADE_BY", "SBALoan", sid, "Lender", lender(r["BankName"].strip(), cert, ncua))
    with open(path_504, encoding="latin-1", newline="") as fh:
        for i, r in enumerate((r for r in csv.DictReader(fh) if r["BorrState"] == state), 1):
            sid = SBA504_ID.format(i)
            loan(r, sid, "504", business(r))
            cdc = r["CDC_Name"].strip()
            if cdc:
                cid = "CDC-" + slug(cdc)
                g.node("DevelopmentCompany", cid, name=title(cdc), city=title(r["CDC_City"].strip()), state=r["CDC_State"].strip())
                g.edge("MADE_BY", "SBALoan", sid, "DevelopmentCompany", cid)


def add_filings(g, fin, cert_to_id):
    """A quarterly Filing (Call Report figures, $ thousands) for every lender with a certificate."""
    for r in fin:
        lid = cert_to_id.get(r["CERT"])
        if not lid:
            continue
        d = r["REPDTE"]
        period = f"{d[:4]}{QUARTER.get(d[4:], d[4:])}"
        fid = f"FIL-{r['CERT']}-{d}"
        g.node(
            "Filing",
            fid,
            name=f"{period} Call Report",
            period=period,
            report_date=d,
            cert=r["CERT"],
            assets_k=r.get("ASSET"),
            deposits_k=r.get("DEP"),
            net_loans_k=r.get("LNLSNET"),
            real_estate_loans_k=r.get("LNRE"),
            residential_re_loans_k=r.get("LNRERES"),
            ci_loans_k=r.get("LNCI"),
            consumer_loans_k=r.get("LNCON"),
            loss_allowance_k=r.get("LNATRES"),
            net_chargeoffs_ytd_k=r.get("NTLNLS"),
        )
        g.edge("FILED", "Lender", lid, "Filing", fid)
