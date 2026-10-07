"""A hand-built miniature of the public sources (one state-year, "DC" 2023) with known answers.

  Lenders  L1 "Alpha Bank, N.A." (LEI L1) -> GLEIF "ALPHA BANK NATIONAL ASSOCIATION" -> FDIC cert 101 (unique name)
           L2 "Twin Savings Bank" -> two FDIC charters of that name; GLEIF HQ US-VA picks cert 202
           L3 "Beta Mortgage LLC" -> no FDIC match: Non-bank lender
  HMDA     row 1  L1 originated, sold to Fannie Mae           -> Application + Loan + SOLD_TO
           row 2  L1 denied (DTI, credit history)              -> Application only, 2 DENIED_FOR
           row 3  L3 originated, kept                          -> Application + Loan, no SOLD_TO
           row 4  L2 withdrawn, a subordinate-lien product    -> Application only
  SBA 7(a) Acme Diner borrows twice from cert 101 at one address  -> 1 Business, 2 SBALoans, 1 LOCATED_AT
           a sole proprietor borrows from an SBA-only lender       -> no name, no Address
  SBA 504  Acme Diner again, through a development company
  FDIC     cert 101 files 2022Q4 and 2023Q4
"""

import csv
import json
import pathlib

HMDA_COLS = ["lei", "action_taken", "census_tract", "county_code", "derived_msa-md", "loan_amount", "loan_to_value_ratio",
             "interest_rate", "rate_spread", "income", "debt_to_income_ratio", "loan_type", "loan_purpose", "lien_status",
             "occupancy_type", "property_value", "derived_dwelling_category", "derived_race", "derived_ethnicity", "derived_sex",
             "applicant_age", "open-end_line_of_credit", "derived_loan_product_type", "tract_population",
             "tract_minority_population_percent", "tract_to_msa_income_percentage", "ffiec_msa_md_median_family_income",
             "tract_owner_occupied_units", "denial_reason-1", "denial_reason-2", "denial_reason-3", "denial_reason-4",
             "loan_term", "total_loan_costs", "purchaser_type"]
SBA_COLS = ["BorrName", "BorrStreet", "BorrCity", "BorrState", "BorrZip", "BusinessType", "BusinessAge", "NaicsCode",
            "NaicsDescription", "LoanStatus", "GrossApproval", "SBAGuaranteedApproval", "ApprovalDate", "ApprovalFY",
            "InitialInterestRate", "TermInMonths", "GrossChargeOffAmount", "JobsSupported", "FranchiseName", "FranchiseCode",
            "BankName", "BankFDICNumber", "BankNCUANumber", "CDC_Name", "CDC_City", "CDC_State"]


def hmda(lei, action, tract="11001000100", purchaser="0", denials=(), product="Conventional:First Lien"):
    r = {c: "NA" for c in HMDA_COLS}
    r.update({"lei": lei, "action_taken": str(action), "census_tract": tract, "county_code": "11001", "derived_msa-md": "47894",
              "loan_amount": "455000", "loan_type": "1", "loan_purpose": "1", "lien_status": "1", "occupancy_type": "1",
              "derived_loan_product_type": product, "derived_dwelling_category": "Single Family (1-4 Units):Site-Built",
              "derived_race": "White", "derived_ethnicity": "Not Hispanic or Latino", "derived_sex": "Joint",
              "applicant_age": "35-44", "open-end_line_of_credit": "2", "tract_population": "4000",
              "tract_minority_population_percent": "40.5", "tract_to_msa_income_percentage": "120",
              "ffiec_msa_md_median_family_income": "152100", "tract_owner_occupied_units": "900", "purchaser_type": purchaser,
              "loan_term": "360", "interest_rate": "6.5", "rate_spread": "0.4", "debt_to_income_ratio": "30%-<36%"})
    for i, d in enumerate(denials, 1):
        r[f"denial_reason-{i}"] = str(d)
    return r


def sba(name, street, cert="", status="PIF", btype="CORPORATION", franchise="", cdc="", bank="Alpha Bank"):
    return {"BorrName": name, "BorrStreet": street, "BorrCity": "WASHINGTON", "BorrState": "DC", "BorrZip": "20001",
            "BusinessType": btype, "BusinessAge": "Existing or more than 2 years old", "NaicsCode": "722511",
            "NaicsDescription": "Full-Service Restaurants", "LoanStatus": status, "GrossApproval": "250000",
            "SBAGuaranteedApproval": "187500", "ApprovalDate": "2021-03-04", "ApprovalFY": "2021", "InitialInterestRate": "6.0",
            "TermInMonths": "120", "GrossChargeOffAmount": "0", "JobsSupported": "8", "FranchiseName": franchise,
            "FranchiseCode": "", "BankName": bank, "BankFDICNumber": cert, "BankNCUANumber": "", "CDC_Name": cdc,
            "CDC_City": "WASHINGTON", "CDC_State": "DC"}


def _csv(path, rows, cols):
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def write_fixture(d: pathlib.Path) -> pathlib.Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "filers_dc_2023.json").write_text(json.dumps({"institutions": [
        {"lei": "L1", "name": "Alpha Bank, N.A.", "count": 2},
        {"lei": "L2", "name": "Twin Savings Bank", "count": 1},
        {"lei": "L3", "name": "Beta Mortgage LLC", "count": 1}]}))
    (d / "gleif_dc_2023.json").write_text(json.dumps({
        "L1": {"legal_name": "ALPHA BANK NATIONAL ASSOCIATION", "hq_city": "RICHMOND", "hq_region": "US-VA", "status": "ACTIVE"},
        "L2": {"legal_name": "TWIN SAVINGS BANK", "hq_city": "NORFOLK", "hq_region": "US-VA", "status": "ACTIVE"},
        "L3": {"legal_name": "BETA MORTGAGE LLC", "hq_city": "DOVER", "hq_region": "US-DE", "status": "ACTIVE"}}))
    (d / "fdic_active_institutions.json").write_text(json.dumps([
        {"NAME": "Alpha Bank", "CERT": "101", "STALP": "VA", "CITY": "Richmond"},
        {"NAME": "Twin Savings Bank", "CERT": "201", "STALP": "OH", "CITY": "Akron"},
        {"NAME": "Twin Savings Bank", "CERT": "202", "STALP": "VA", "CITY": "Norfolk"}]))
    (d / "fdic_financials_2022q4_2023q4.json").write_text(json.dumps([
        {"CERT": 101, "REPDTE": "20221231", "ASSET": 900000, "LNRERES": 300000},
        {"CERT": 101, "REPDTE": "20231231", "ASSET": 950000, "LNRERES": 310000}]))
    _csv(d / "hmda_dc_2023.csv", [hmda("L1", 1, purchaser="1"), hmda("L1", 3, denials=(1, 3)), hmda("L3", 1),
                                  hmda("L2", 4, tract="11001000200", product="Conventional:Subordinate Lien")], HMDA_COLS)
    _csv(d / "sba_7a_fy2020_present.csv", [sba("ACME DINER LLC", "1 MAIN ST", cert="101"),
                                           sba("ACME DINER LLC", "1 MAIN ST", cert="101", status="CHGOFF"),
                                           sba("JANE ROE", "9 SIDE ST", btype="INDIVIDUAL", bank="Main Street Capital"),
                                           sba("OTHER STATE CO", "5 ELM", cert="101") | {"BorrState": "MD"}], SBA_COLS)
    _csv(d / "sba_504_fy2010_present.csv", [sba("ACME DINER LLC", "1 MAIN ST", cdc="CAPITAL CDC")], SBA_COLS)
    return d
