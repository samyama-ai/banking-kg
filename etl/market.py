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

from etl import identity as I
from etl.helpers import Graph

ACTION = {1: "Loan originated", 2: "Approved, not accepted", 3: "Denied", 4: "Withdrawn by applicant",
          5: "File closed, incomplete", 6: "Purchased loan", 7: "Preapproval denied", 8: "Preapproval approved, not accepted"}
LOAN_TYPE = {1: "Conventional", 2: "FHA", 3: "VA", 4: "USDA RHS/FSA"}
PURPOSE = {1: "Home purchase", 2: "Home improvement", 31: "Refinancing", 32: "Cash-out refinancing", 4: "Other purpose", 5: "Not applicable"}
LIEN = {1: "First lien", 2: "Subordinate lien"}
OCCUPANCY = {1: "Principal residence", 2: "Second residence", 3: "Investment property"}
PURCHASER = {1: "Fannie Mae", 2: "Ginnie Mae", 3: "Freddie Mac", 4: "Farmer Mac", 5: "Private securitizer",
             6: "Commercial bank, savings bank or savings association", 71: "Credit union, mortgage company or finance company",
             72: "Life insurance company", 8: "Affiliate institution", 9: "Other type of purchaser"}
DENIAL = {1: "Debt-to-income ratio", 2: "Employment history", 3: "Credit history", 4: "Collateral",
          5: "Insufficient cash (down payment, closing costs)", 6: "Unverifiable information", 7: "Credit application incomplete",
          8: "Mortgage insurance denied", 9: "Other"}
SBA_STATUS = {"PIF": "Paid in full", "P I F": "Paid in full", "NOT FUNDED": "Not funded", "CHGOFF": "Charged off", "EXEMPT": "Active (status exempt from disclosure)",
              "COMMIT": "Committed, not disbursed", "CANCLD": "Cancelled"}
QUARTER = {"0331": "Q1", "0630": "Q2", "0930": "Q3", "1231": "Q4"}


def num(v, typ=float):
    try:
        x = typ(float(v))
        return x
    except (TypeError, ValueError):
        return None


def code(v):
    return num(v, int)


def money(v):
    v = v or 0
    return f"${v / 1e6:.1f}M" if v >= 1e6 else f"${v / 1e3:.0f}K"


def title(s):
    return " ".join(w.capitalize() if w.isupper() else w for w in s.split())


def build(data: pathlib.Path, state="DC", year=2023) -> Graph:
    g = Graph()
    filers = json.loads((data / f"filers_{state.lower()}_{year}.json").read_text())["institutions"]
    gleif = json.loads((data / f"gleif_{state.lower()}_{year}.json").read_text())
    idx = I.fdic_index(json.loads((data / "fdic_active_institutions.json").read_text()))
    fin = json.loads(next(data.glob("fdic_financials_*.json")).read_text())
    latest = {}
    for r in fin:
        if r["CERT"] not in latest or r["REPDTE"] > latest[r["CERT"]]["REPDTE"]:
            latest[r["CERT"]] = r

    # -- lenders and legal entities -------------------------------------------------------------
    cert_to_id = {}
    for f in filers:
        lei, gl = f["lei"], gleif.get(f["lei"], {})
        row = I.match(lei, f["name"], gleif, idx)
        cert = int(row["CERT"]) if row else None
        g.node("Lender", lei, name=f["name"], lei=lei, cert=cert, lender_type=I.lender_type(f["name"], row),
               hq_city=title(gl.get("hq_city") or ""), hq_state=(gl.get("hq_region") or "").replace("US-", ""),
               hmda_applications=f["count"], assets_k=latest.get(cert, {}).get("ASSET") if cert else None)
        g.node("LegalEntity", lei, name=gl.get("legal_name", f["name"]), lei=lei, jurisdiction=gl.get("jurisdiction"),
               status=gl.get("status"), legal_form=gl.get("legal_form"), category=gl.get("category"))
        g.edge("REGISTERED_AS", "Lender", lei, "LegalEntity", lei)
        if cert:
            cert_to_id[cert] = lei

    def sba_lender(name, cert, ncua):
        if cert and cert in cert_to_id:
            return cert_to_id[cert]
        nid = f"FDIC-{cert}" if cert else (f"NCUA-{ncua}" if ncua else "SBA-" + re.sub(r"[^A-Z0-9]+", "-", name.upper()).strip("-"))
        if nid not in g.nodes["Lender"]:
            g.node("Lender", nid, name=title(name), cert=cert,
                   lender_type="Bank" if cert else ("Credit union" if ncua else "Non-bank lender"),
                   assets_k=latest.get(cert, {}).get("ASSET") if cert else None)
            if cert:
                cert_to_id[cert] = nid
        return nid

    # -- HMDA applications, loans, geography ------------------------------------------------------
    msa_seen = set()
    with open(next(data.glob(f"hmda_{state.lower()}_{year}.csv")), newline="") as fh:
        for i, r in enumerate(csv.DictReader(fh), 1):
            aid, act = f"APP-{i:06d}", code(r["action_taken"])
            tract = r["census_tract"] if r["census_tract"] not in ("", "NA") else None
            county = r["county_code"] if r["county_code"] not in ("", "NA") else None
            g.node("Application", aid, name=f"{(ACTION.get(act) or '').split(',')[0]} {money(num(r['loan_amount']))}", action=ACTION.get(act), action_code=act, loan_amount=num(r["loan_amount"]),
                   loan_to_value=num(r["loan_to_value_ratio"]), interest_rate=num(r["interest_rate"]),
                   rate_spread=num(r["rate_spread"]), income_k=num(r["income"]), debt_to_income=r["debt_to_income_ratio"] if r["debt_to_income_ratio"] not in ("NA", "Exempt") else None,
                   loan_type=LOAN_TYPE.get(code(r["loan_type"])), purpose=PURPOSE.get(code(r["loan_purpose"])),
                   lien=LIEN.get(code(r["lien_status"])), occupancy=OCCUPANCY.get(code(r["occupancy_type"])),
                   property_value=num(r["property_value"]), dwelling=r["derived_dwelling_category"],
                   applicant_race=r["derived_race"], applicant_ethnicity=r["derived_ethnicity"], applicant_sex=r["derived_sex"],
                   applicant_age=r["applicant_age"] if r["applicant_age"] not in ("NA", "8888", "9999") else None,
                   open_end=code(r["open-end_line_of_credit"]) == 1, year=year)
            g.edge("FILED_WITH", "Application", aid, "Lender", r["lei"])
            prod = r["derived_loan_product_type"]
            g.node("LoanProduct", prod, name=prod)
            g.edge("FOR_PRODUCT", "Application", aid, "LoanProduct", prod)
            if tract:
                g.node("Tract", tract, name=f"Tract {tract[-6:-2]}.{tract[-2:]}", fips=tract,
                       population=num(r["tract_population"], int), minority_pct=num(r["tract_minority_population_percent"]),
                       income_pct_of_msa=num(r["tract_to_msa_income_percentage"]),
                       msa_median_family_income=num(r["ffiec_msa_md_median_family_income"], int),
                       owner_occupied_units=num(r["tract_owner_occupied_units"], int))
                g.edge("IN_TRACT", "Application", aid, "Tract", tract)
                if county and (tract, county) not in msa_seen:
                    msa_seen.add((tract, county))
                    g.node("County", county, name="District of Columbia" if county == "11001" else county, fips=county)
                    g.edge("IN_COUNTY", "Tract", tract, "County", county)
                    msa = r["derived_msa-md"]
                    if msa not in ("", "NA") and ("county", county) not in msa_seen:
                        msa_seen.add(("county", county))
                        g.node("MSA", msa, name="Washington-Arlington-Alexandria, DC-VA-MD-WV" if msa == "47894" else msa, code=msa)
                        g.edge("IN_MSA", "County", county, "MSA", msa)
            for k in ("denial_reason-1", "denial_reason-2", "denial_reason-3", "denial_reason-4"):
                d = code(r[k])
                if d in DENIAL:
                    g.node("DenialReason", f"DR-{d}", name=DENIAL[d], code=d)
                    g.edge("DENIED_FOR", "Application", aid, "DenialReason", f"DR-{d}")
            if act == 1:                       # only an origination is a Loan (spec §5)
                lid = f"LOAN-{i:06d}"
                g.node("Loan", lid, name=f"Loan {money(num(r['loan_amount']))}", amount=num(r["loan_amount"]), interest_rate=num(r["interest_rate"]),
                       rate_spread=num(r["rate_spread"]), term_months=num(r["loan_term"], int),
                       loan_to_value=num(r["loan_to_value_ratio"]), loan_type=LOAN_TYPE.get(code(r["loan_type"])),
                       purpose=PURPOSE.get(code(r["loan_purpose"])), total_loan_costs=num(r["total_loan_costs"]), year=year)
                g.edge("ORIGINATED_AS", "Application", aid, "Loan", lid)
                g.edge("ORIGINATED_BY", "Loan", lid, "Lender", r["lei"])
                p = code(r["purchaser_type"])
                if p in PURCHASER:
                    g.node("Purchaser", f"PUR-{p}", name=PURCHASER[p], code=p)
                    g.edge("SOLD_TO", "Loan", lid, "Purchaser", f"PUR-{p}")

    # -- SBA corporate lending ----------------------------------------------------------------------
    linked = set()   # (business, address|industry): a business that took several loans is linked once per target

    def business(r, prefix):
        indiv = r["BusinessType"].strip().upper() == "INDIVIDUAL"
        naics = r["NaicsCode"].strip()
        desc = title(r["NaicsDescription"].strip()) if r["NaicsDescription"].strip() else None
        street, zipc = r["BorrStreet"].strip().upper(), r["BorrZip"].strip()[:5]
        key = re.sub(r"[^A-Z0-9]+", " ", (r["BorrName"].strip().upper() + "|" + street + "|" + zipc))
        bid = "BIZ-" + hashlib.sha1(key.encode()).hexdigest()[:10]   # stable across runs
        g.node("Business", bid, name=f"Sole proprietor · {desc or 'business'}" if indiv else title(r["BorrName"].strip()),
               business_type=title(r["BusinessType"].strip()) or None, business_age=r["BusinessAge"].strip() or None,
               city=title(r["BorrCity"].strip()), zip=zipc, sole_proprietor=indiv)
        if not indiv and street:
            aid = "ADDR-" + re.sub(r"[^A-Z0-9]+", "-", f"{street} {zipc}").strip("-")
            g.node("Address", aid, name=title(street), street=title(street), zip=zipc, city=title(r["BorrCity"].strip()))
            if (bid, aid) not in linked:
                linked.add((bid, aid))
                g.edge("LOCATED_AT", "Business", bid, "Address", aid)
        if naics:
            g.node("Industry", naics, name=desc or naics, naics=naics, sector=naics[:2])
            if (bid, naics) not in linked:
                linked.add((bid, naics))
                g.edge("IN_INDUSTRY", "Business", bid, "Industry", naics)
        return bid

    def sba_loan(r, sid, program, bid):
        status = r["LoanStatus"].strip()
        g.node("SBALoan", sid, name=f"SBA {program} {money(num(r['GrossApproval']))}", program=program, gross_approval=num(r["GrossApproval"]),
               sba_guaranteed=num(r.get("SBAGuaranteedApproval")), approval_date=r["ApprovalDate"].strip() or None,
               fiscal_year=num(r["ApprovalFY"], int), interest_rate=num(r.get("InitialInterestRate")),
               term_months=num(r["TermInMonths"], int), status=SBA_STATUS.get(status, status or None),
               charge_off_amount=num(r["GrossChargeOffAmount"]) or None, jobs_supported=num(r["JobsSupported"], int))
        g.edge("BORROWED", "Business", bid, "SBALoan", sid)
        fr = r["FranchiseName"].strip()
        if fr:
            fid = "FR-" + (r["FranchiseCode"].strip() or re.sub(r"[^A-Z0-9]+", "-", fr.upper()))
            g.node("Franchise", fid, name=title(fr), code=r["FranchiseCode"].strip() or None)
            g.edge("UNDER_FRANCHISE", "SBALoan", sid, "Franchise", fid)

    with open(next(data.glob("sba_7a_*.csv")), encoding="latin-1", newline="") as fh:
        for i, r in enumerate((r for r in csv.DictReader(fh) if r["BorrState"] == state), 1):
            bid, sid = business(r, "7a"), f"SBA7A-{i:05d}"
            sba_loan(r, sid, "7(a)", bid)
            cert = num(r["BankFDICNumber"], int) or None
            ncua = num(r["BankNCUANumber"], int) or None
            g.edge("MADE_BY", "SBALoan", sid, "Lender", sba_lender(r["BankName"].strip(), cert, ncua))
    with open(next(data.glob("sba_504_*.csv")), encoding="latin-1", newline="") as fh:
        for i, r in enumerate((r for r in csv.DictReader(fh) if r["BorrState"] == state), 1):
            bid, sid = business(r, "504"), f"SBA504-{i:05d}"
            sba_loan(r, sid, "504", bid)
            cdc = r["CDC_Name"].strip()
            if cdc:
                cid = "CDC-" + re.sub(r"[^A-Z0-9]+", "-", cdc.upper()).strip("-")
                g.node("DevelopmentCompany", cid, name=title(cdc), city=title(r["CDC_City"].strip()), state=r["CDC_State"].strip())
                g.edge("MADE_BY", "SBALoan", sid, "DevelopmentCompany", cid)

    # -- Call Report filings for every lender that has a certificate ---------------------------------
    for r in fin:
        lid = cert_to_id.get(r["CERT"])
        if not lid:
            continue
        d = r["REPDTE"]
        period = f"{d[:4]}{QUARTER.get(d[4:], d[4:])}"
        fid = f"FIL-{r['CERT']}-{d}"
        g.node("Filing", fid, name=f"{period} Call Report", period=period, report_date=d, cert=r["CERT"],
               assets_k=r.get("ASSET"), deposits_k=r.get("DEP"), net_loans_k=r.get("LNLSNET"),
               real_estate_loans_k=r.get("LNRE"), residential_re_loans_k=r.get("LNRERES"), ci_loans_k=r.get("LNCI"),
               consumer_loans_k=r.get("LNCON"), loss_allowance_k=r.get("LNATRES"), net_chargeoffs_ytd_k=r.get("NTLNLS"))
        g.edge("FILED", "Lender", lid, "Filing", fid)
    return g
