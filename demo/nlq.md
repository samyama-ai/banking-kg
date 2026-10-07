# banking-kg — Natural Language segment (10 questions)

Read by `demo_nlq.py` (GRAPH=bankingkg): the first table, one row per question. The page generates Cypher from
the question with the tenant's NLQ config, runs it, and shows both. Expected answers are from reference
queries on tenant bankingkg2 (75,179 nodes), 2026-10-07. Questions 1–4 are the market (real), 5–9 the bank
(synthetic), 10 crosses the line.

| # | Question | Expected answer |
|---|---|---|
| 1 | How many mortgage applications became loans? Show the count. | 8,616 (of 17,474 applications) |
| 2 | Which lenders originated the most loans? Show the lender name and the number of loans, most first. | First Savings Mortgage · 444; First Home Mortgage · 380; Rocket Mortgage · 335; Truist Bank · 300 … |
| 3 | What are the most common reasons applications were denied? Show the reason and the number of applications, most first. | Debt-to-income ratio · 1,101; Credit history · 719; Collateral · 635; Other · 464 … |
| 4 | How many lenders are there of each type? Show the lender type and the count. | Non-bank lender · 276; Bank · 180 (includes Banking-KG Bank); Credit union · 68; Bank (no active FDIC charter) · 15 |
| 5 | How many of our customers are in each status? Show the status and the count. | ACTIVE · 4,695; CLOSED · 238; DECEASED · 41; INACTIVE · 26 |
| 6 | Which of our products have the most accounts? Show the product and the number of accounts, most first. | Everyday Checking · 2,163; Statement Savings · 1,827; Interest Checking · 903; Money Market Account · 776 … |
| 7 | Which competitors receive the most money from our customers' accounts? Show the competitor and the total sent, largest first. | Meridian Natl · 6.83M; Swiftsave · 6.49M; Cardinal Cmnty · 6.39M; Harvest CU · 5.82M … |
| 8 | Which employers pay the most of our customers? Show the employer and the number of customers, most first. | Blue Ridge Manufacturing · 328; Keystone Construction · 313; Tidewater Logistics · 308; Federal Contracting Partners · 307 … |
| 9 | How large is each campaign audience? Show the audience name and the number of customers, largest first. | Customers like past responders (proxy) · 2,588; Money leaving to competitors · 546; Household digital adoption · 512; Next generation · 50; Estate transition · 40; Household member left · 26 |
| 10 | How many of our loans fall under each mortgage product the market reports? Show the product and the count. | Conventional:First Lien · 872; Conventional:Subordinate Lien · 121 |

## Tenant NLQ config (needed by this segment)

```text
PORT=8791 python3 video_tools/claude_chat_proxy.py      # keep running during the recording
PATCH /api/tenants/bankingkg  nlq_config = {enabled: true, provider: "OpenAI", model: "claude", api_key: "local",
                              api_base_url: "http://host.docker.internal:8791/v1", system_prompt: <below>}
```

System prompt:

> You translate a banker's question into one openCypher query for a graph with two layers. The MARKET layer is real public data for Washington DC in 2023 (HMDA mortgage applications, GLEIF, FDIC Call Reports, SBA loans). The BANK layer is our own bank, Banking-KG Bank: its customers, households, accounts and loans (synthetic data). "Our", "we" and "us" mean the bank layer. Return only the Cypher, no explanation, no code fences.
> MARKET node labels (each node has exactly one label) and properties:
> Lender(id, name, lei, cert, lender_type 'Bank'|'Credit union'|'Non-bank lender'|'Bank (no active FDIC charter)', hq_city, hq_state, hmda_applications, assets_k, profile)  our bank is the Lender with id 'BANKING-KG'
> LegalEntity(id, name, lei, jurisdiction, status, legal_form, category)
> Application(id, action 'Loan originated'|'Denied'|'Withdrawn by applicant'|'Purchased loan'|'File closed, incomplete'|'Approved, not accepted'|'Preapproval approved, not accepted'|'Preapproval denied', loan_amount, loan_to_value, interest_rate, rate_spread, income_k, debt_to_income, loan_type 'Conventional'|'FHA'|'VA'|'USDA RHS/FSA', purpose, lien, occupancy, property_value, applicant_race, applicant_ethnicity, applicant_sex, applicant_age)
> Loan(id, amount, interest_rate, rate_spread, term_months, loan_to_value, loan_type, purpose, total_loan_costs)  only originated applications are loans; a market Loan is never one of our loans
> Purchaser(id, name), DenialReason(id, name), LoanProduct(id, name e.g. 'Conventional:First Lien')
> Tract(id, name, fips, population, minority_pct, income_pct_of_msa), County(id, name), MSA(id, name)
> Filing(id, name, period e.g. '2023Q4', cert, assets_k, deposits_k, net_loans_k, real_estate_loans_k, residential_re_loans_k, ci_loans_k, consumer_loans_k, loss_allowance_k, net_chargeoffs_ytd_k)  $ thousands
> Business(id, name, business_type, city, zip, sole_proprietor), Address(id, street, zip), Industry(id, name, naics), Franchise(id, name), DevelopmentCompany(id, name)
> SBALoan(id, program '7(a)'|'504', gross_approval, sba_guaranteed, approval_date, fiscal_year, interest_rate, term_months, status 'Paid in full'|'Charged off'|'Active (status exempt from disclosure)'|'Cancelled'|'Committed, not disbursed'|'Not funded', charge_off_amount, jobs_supported)
> BANK node labels and properties:
> Customer(id, name, customer_type 'INDIVIDUAL'|'BUSINESS', status 'ACTIVE'|'CLOSED'|'DECEASED'|'INACTIVE', age, annual_income, city, state_code, household_id, logins_90d, digital_user, credit_score)
> Household(id, size, postal_code), Account(id, name, account_type, product_code, status, open_date, close_date, close_reason_code, balance_latest)
> Product(id, code, name, product_type), CustomerLoan(id, loan_type 'MORTGAGE'|'AUTO'|'PERSONAL'|'HELOC'|'COMMERCIAL'|'STUDENT', status, principal_balance, original_loan_amount, current_interest_rate, origination_date)
> Collateral(id, collateral_type, property_type, collateral_value), CreditLine(id, credit_limit, current_balance), Card(id, card_kind 'DEBIT'|'CREDIT', card_status)
> Counterparty(id, name, kind 'COMPETITOR'|'EMPLOYER'|'LENDER'), MerchantCategory(id, name, mcc_code), Audience(id, use_case, name, campaign, customers, households)
> Relationships:
> (Application)-[:FILED_WITH]->(Lender), (Application)-[:ORIGINATED_AS]->(Loan), (Loan)-[:ORIGINATED_BY]->(Lender), (Loan)-[:SOLD_TO]->(Purchaser)
> (Application)-[:DENIED_FOR]->(DenialReason), (Application)-[:FOR_PRODUCT]->(LoanProduct), (Application)-[:IN_TRACT]->(Tract), (Tract)-[:IN_COUNTY]->(County), (County)-[:IN_MSA]->(MSA)
> (Lender)-[:REGISTERED_AS]->(LegalEntity), (Lender)-[:FILED]->(Filing)
> (Business)-[:BORROWED]->(SBALoan), (SBALoan)-[:MADE_BY]->(Lender), (SBALoan)-[:MADE_BY]->(DevelopmentCompany), (Business)-[:LOCATED_AT]->(Address), (Business)-[:IN_INDUSTRY]->(Industry), (SBALoan)-[:UNDER_FRANCHISE]->(Franchise)
> (Customer)-[:MEMBER_OF]->(Household), (Customer)-[:OWNS {role_code 'P'|'J'|'B'|'A'}]->(Account), (Account)-[:OF_PRODUCT]->(Product), (Product)-[:OFFERED_BY]->(Lender)
> (Account)-[:SENDS_TO {count, total, last_date}]->(Counterparty), (Account)-[:RECEIVES_FROM]->(Counterparty), (Account)-[:PAID_BY]->(Counterparty), (Account)-[:SPENDS_AT {count, total}]->(MerchantCategory)
> (Account)-[:HAS_LOAN]->(CustomerLoan), (Customer)-[:BORROWS]->(CustomerLoan), (CustomerLoan)-[:SECURED_BY {lien_position}]->(Collateral), (CustomerLoan)-[:CLASSIFIED_AS]->(LoanProduct)
> (Account)-[:HAS_CARD]->(Card), (Customer)-[:HOLDS_CARD]->(Card), (Account)-[:HAS_CREDIT_LINE]->(CreditLine), (Customer)-[:OWES {account_type, balance}]->(Counterparty), (Customer)-[:IN_AUDIENCE {slice}]->(Audience)
> Rules: use exact property values as listed. Give every returned column a readable alias. Order by the count or total descending when the question says "most" or "largest". Count applications with count(DISTINCT a) when following DENIED_FOR. Count customers with count(DISTINCT c).
