// banking-kg — schema v2.0 (2026-10-07)
// One graph, two layers and a bridge. Plain-English version: docs/schema.md · standards: docs/standards.md.
//
//   MARKET layer  real, public: Washington DC 2023 — HMDA LAR (CFPB), GLEIF, FDIC BankFind + financials
//                 (Call Report figures, $ thousands), SBA 7(a) FY2020+ and 504 FY2010+ FOIA.   etl/market.py
//   BANK layer    synthetic: one fictional bank's customers (Banking-KG Bank), from its 26-table customer
//                 data request. Every node carries synthetic: true.                              etl/bank.py
//   BRIDGE        the bank as a market Lender, and its mortgages classified in HMDA's product taxonomy. etl/bridge.py
//
// Rules for every node and edge
//   id          unique per label. Market ids are source keys (LEI, FIPS, NAICS, FDIC cert) or stable
//               derived keys (APP-<row>, LOAN-<row>, FIL-<cert>-<date>); bank ids are request keys (PATTERN-*)
//   synthetic   true on every bank-layer node and on the bank's Lender node; absent on real public data
//   derived     true on anything built that is not a source row; `basis` says from what
//   dates       'YYYY-MM-DD' strings (SBA, bank layer) or 'YYYYMMDD' (FDIC report_date), so string order is date order
//   money       HMDA and SBA amounts in dollars; FDIC *_k fields in $ thousands; bank layer in dollars
//   PII         market: SBA sole proprietors keep no name or street. Bank: customer name kept for the demo;
//               email, phone and street address are NOT loaded
//
// Engine 1.7.1 limits followed: one label per node; literal property maps only; the loader checks counts
// itself because constraints may not enforce; load into an engine started with --data-path; create vector
// indexes after loading and rebuild them (they do not backfill).

// ======================================================================= MARKET layer (17 labels)
// (:Lender {id: LEI | FDIC-<cert> | NCUA-<n> | SBA-<NAME>, name, lei, cert, lender_type, hq_city, hq_state,
//           hmda_applications, assets_k, profile, synthetic})
//     HMDA filer, or an SBA lender with no HMDA filing. lender_type: Bank | Credit union | Non-bank lender |
//     Bank (no active FDIC charter). cert = FDIC certificate, matched by legal name (etl/identity.py)
// (:LegalEntity {id: LEI, name, lei, jurisdiction, status, legal_form, category})          GLEIF
// (:Application {id: APP-<row>, name, action, action_code, loan_amount, loan_to_value, interest_rate,
//                rate_spread, income_k, debt_to_income, loan_type, purpose, lien, occupancy, property_value,
//                dwelling, applicant_race, applicant_ethnicity, applicant_sex, applicant_age, open_end, year})
//     EVERY HMDA row. action = HMDA action_taken (8 codes = FIBO HMDA-Disposition, one to one)
// (:Loan {id: LOAN-<row>, name, amount, interest_rate, rate_spread, term_months, loan_to_value, loan_type,
//         purpose, total_loan_costs, year})
//     ONLY action_taken = 1 (originated). Never conflate with Application (spec §5)
// (:LoanProduct {id = name})          HMDA derived_loan_product_type, e.g. 'Conventional:First Lien'
// (:Tract {id: 11-digit FIPS, name, fips, population, minority_pct, income_pct_of_msa,
//          msa_median_family_income, owner_occupied_units})
// (:County {id: 5-digit FIPS, name, fips})         (:MSA {id: MSA/MD code, name, code})
// (:DenialReason {id: DR-<code>, name, code})      (:Purchaser {id: PUR-<code>, name, code})  HMDA code lists
// (:Business {id: BIZ-<sha1>, name, business_type, business_age, city, zip, sole_proprietor})   SBA borrower
// (:Address {id: ADDR-<street-zip>, name, street, zip, city})       not for sole proprietors
// (:Industry {id: NAICS code, name, naics, sector})
// (:Franchise {id: FR-<code>, name, code})
// (:SBALoan {id: SBA7A-<n> | SBA504-<n>, name, program, gross_approval, sba_guaranteed, approval_date,
//            fiscal_year, interest_rate, term_months, status, charge_off_amount, jobs_supported})
// (:DevelopmentCompany {id: CDC-<NAME>, name, city, state})      504 certified development company
// (:Filing {id: FIL-<cert>-<YYYYMMDD>, name, period, report_date, cert, assets_k, deposits_k, net_loans_k,
//           real_estate_loans_k, residential_re_loans_k, ci_loans_k, consumer_loans_k, loss_allowance_k,
//           net_chargeoffs_ytd_k})      FDIC financials = Call Report figures, quarterly 2022Q4..2023Q4

// ----------------------------------------------------------------------- MARKET relationships (16)
// (:Lender)-[:REGISTERED_AS]->(:LegalEntity)
// (:Application)-[:FILED_WITH]->(:Lender)
// (:Application)-[:FOR_PRODUCT]->(:LoanProduct)
// (:Application)-[:IN_TRACT]->(:Tract)-[:IN_COUNTY]->(:County)-[:IN_MSA]->(:MSA)
// (:Application)-[:DENIED_FOR]->(:DenialReason)                up to 4 per application
// (:Application)-[:ORIGINATED_AS]->(:Loan)-[:ORIGINATED_BY]->(:Lender)
// (:Loan)-[:SOLD_TO]->(:Purchaser)                             absent = kept on balance sheet
// (:Business)-[:LOCATED_AT]->(:Address)
// (:Business)-[:IN_INDUSTRY]->(:Industry)
// (:Business)-[:BORROWED]->(:SBALoan)
// (:SBALoan)-[:UNDER_FRANCHISE]->(:Franchise)
// (:SBALoan)-[:MADE_BY]->(:Lender)                             7(a)
// (:SBALoan)-[:MADE_BY]->(:DevelopmentCompany)                 504
// (:Lender)-[:FILED]->(:Filing)

// ======================================================================= BANK layer (12 labels, synthetic)
// (:Customer {id, customer_type, status, birth_date, age, annual_income, business_unit, risk_ranking,
//             retention, relationship_start_dt, last_contact_dt, city, state_code, postal_code, name,
//             household_id, last_address_change_dt, deceased_reported_dt, logins_90d, digital_user,
//             last_login, credit_score, credit_score_date, receptiveness_score, synthetic})
//     from customers (+ customer_change_events, digital_sessions, credit_bureau, crm_data roll-ups)
// (:Household {id, name, size, postal_code, derived: true, basis})
//     DERIVED: individuals sharing address_line1 + postal_code
// (:Account {id, name, account_type, product_code, status, open_date, close_date, close_reason_code, rate,
//            naics, business_unit, last_activity_date, balance_latest, balance_date})
// (:Product {id: prod:<code>, code, name, product_type, status, description})
// (:BusinessUnit {id, code, name, business_unit, open_date, close_date, postal_code})
//     NO edges: the request says it joins to customers.branch, which it does not request
// (:Counterparty {id, name, kind, derived: true, basis})
//     kind COMPETITOR / EMPLOYER: parsed from transaction descriptions; LENDER: credit_bureau_tradeline.lender_name.
//     All names are fictional and are never matched to a market Lender
// (:MerchantCategory {id: mcc:<code>, mcc_code, name, description})     ISO 18245
// (:CustomerLoan {id, name, loan_type, product_code, status, principal_balance, original_loan_amount,
//                 term_months, current_interest_rate, rate_type, origination_date, maturity_date,
//                 next_rate_change_date, product_name, delinquent_days, original_credit_score})
//     the bank's own loan record — NOT a HMDA Loan
// (:Collateral {id, name, collateral_type, property_postal_code, property_state, property_type, collateral_value})
// (:CreditLine {id, name, credit_limit, current_balance})
// (:Card {id, name, card_kind, card_status, card_tier, credit_limit, current_balance})
// (:Audience {id: aud:<UC>:<as_of>, use_case, name, campaign, as_of, customers, households})   etl/audiences.py

// ----------------------------------------------------------------------- BANK relationships (15)
// (:Customer)-[:MEMBER_OF {derived: true}]->(:Household)
// (:Customer)-[:OWNS {role_code, role, primary, share}]->(:Account)
// (:Account)-[:OF_PRODUCT]->(:Product)
// (:Account)-[:SENDS_TO {count, total, first_date, last_date, derived: true}]->(:Counterparty)       competitor, out
// (:Account)-[:RECEIVES_FROM {count, total, first_date, last_date, derived: true}]->(:Counterparty)  competitor, in
// (:Account)-[:PAID_BY {count, total, first_date, last_date, derived: true}]->(:Counterparty)        employer payroll
// (:Account)-[:SPENDS_AT {count, total, derived: true}]->(:MerchantCategory)
// (:Account)-[:HAS_LOAN]->(:CustomerLoan)
// (:Customer)-[:BORROWS {basis}]->(:CustomerLoan)              primary borrower only: no co-borrowers in the request
// (:CustomerLoan)-[:SECURED_BY {lien_position}]->(:Collateral)
// (:Account)-[:HAS_CREDIT_LINE]->(:CreditLine)
// (:Account)-[:HAS_CARD]->(:Card)
// (:Customer)-[:HOLDS_CARD]->(:Card)                           credit cards only
// (:Customer)-[:OWES {account_type, balance, monthly_payment, opened_date}]->(:Counterparty)  open external tradelines
// (:Customer)-[:IN_AUDIENCE {slice, reason, household_primary}]->(:Audience)
//     slice CAMPAIGN or CONTROL (whole households held out); household_primary = one mail piece per household

// ======================================================================= BRIDGE (1 node, 2 relationships)
// (:Lender {id: 'BANKING-KG', name: 'Banking-KG Bank', synthetic: true})     the bank, inside the market
// (:Product)-[:OFFERED_BY]->(:Lender)
// (:CustomerLoan)-[:CLASSIFIED_AS {basis}]->(:LoanProduct)     first-lien mortgages and HELOCs only

// ======================================================================= constraints (29 labels)
CREATE CONSTRAINT lender_id IF NOT EXISTS FOR (n:Lender) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT legalentity_id IF NOT EXISTS FOR (n:LegalEntity) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT application_id IF NOT EXISTS FOR (n:Application) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT loan_id IF NOT EXISTS FOR (n:Loan) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT loanproduct_id IF NOT EXISTS FOR (n:LoanProduct) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT tract_id IF NOT EXISTS FOR (n:Tract) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT county_id IF NOT EXISTS FOR (n:County) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT msa_id IF NOT EXISTS FOR (n:MSA) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT denialreason_id IF NOT EXISTS FOR (n:DenialReason) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT purchaser_id IF NOT EXISTS FOR (n:Purchaser) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT business_id IF NOT EXISTS FOR (n:Business) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT address_id IF NOT EXISTS FOR (n:Address) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT industry_id IF NOT EXISTS FOR (n:Industry) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT franchise_id IF NOT EXISTS FOR (n:Franchise) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT sbaloan_id IF NOT EXISTS FOR (n:SBALoan) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT developmentcompany_id IF NOT EXISTS FOR (n:DevelopmentCompany) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT filing_id IF NOT EXISTS FOR (n:Filing) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT customer_id IF NOT EXISTS FOR (n:Customer) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT household_id IF NOT EXISTS FOR (n:Household) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT account_id IF NOT EXISTS FOR (n:Account) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT product_id IF NOT EXISTS FOR (n:Product) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT businessunit_id IF NOT EXISTS FOR (n:BusinessUnit) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT counterparty_id IF NOT EXISTS FOR (n:Counterparty) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT merchantcategory_id IF NOT EXISTS FOR (n:MerchantCategory) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT customerloan_id IF NOT EXISTS FOR (n:CustomerLoan) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT collateral_id IF NOT EXISTS FOR (n:Collateral) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT creditline_id IF NOT EXISTS FOR (n:CreditLine) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT card_id IF NOT EXISTS FOR (n:Card) REQUIRE n.id IS UNIQUE;
CREATE CONSTRAINT audience_id IF NOT EXISTS FOR (n:Audience) REQUIRE n.id IS UNIQUE;
