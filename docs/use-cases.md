# Questions and use cases

Three groups, matching the three acts of the demo. Every query here runs on the loaded graph; the demo
versions (which return nodes and relationships for drawing) are in [`../demo/queries.cypher`](../demo/queries.cypher),
and their timings in [`../benchmarks/results.md`](../benchmarks/results.md).

## 1 · The market (real public data)

The full catalogue — 25 questions, each with why it is hard — is [spec §8](spec.md#8--question-catalogue).
Status after the 2026-10-07 build (● runs and visualises · ◦ not yet):

| Spec # | Question | Demo | St |
|---|---|---|---|
| 1 | Where did this number come from? | Q1 | ● |
| 2 | Reported originations vs Call Report growth — where did the rest go? | Q2 | ● |
| 3 | Who bought our loans, and are they lenders here too? | — | ◦ blocked: HMDA purchaser is a category |
| 4 | Which loans were never sold? | Q3 | ● |
| 5 | If this tract turns, which lenders are exposed? | Q4 | ● |
| 6 | Which single industry touches the most lenders? | [v1 market demo](../../samyama-graph-demo-ops/demo/scripts/bankingkg/queries.cypher) | ● |
| 12 | Which tracts are served by only one or two lenders? | [v1 market demo](../../samyama-graph-demo-ops/demo/scripts/bankingkg/queries.cypher) | ● |
| 11 | Who charges the widest spread? | [v1 market demo](../../samyama-graph-demo-ops/demo/scripts/bankingkg/queries.cypher) | ● |
| 13 | Denial reasons in the lowest-income tracts | Q5 | ● |
| 14, 16 | Most central lenders; purchasers behind the most originators (PageRank) | algorithms 1 | ● |
| 18 | Lenders whose book resembles this one | vectors 1–2 | ● |
| 21 | Addresses with several businesses each drawing a guaranteed loan | Q7 | ● |
| 22, 23, 24 | Loan stacking, franchise concentration, charge-offs | [v1 market demo](../../samyama-graph-demo-ops/demo/scripts/bankingkg/queries.cypher) | ● |
| 25 | This lender's entire book | Q18 | ● |
| 10, 20 | Adjacent tracts | — | ◦ needs a tract-adjacency edge |
| 7, 8, 9, 15, 17, 19 | Shared borrowers, retail-only counties, source-system cascade, central-but-small, cross-book centrality, like-us-but-higher-allowance | — | ◦ not yet written |

The reconciliation question as a table — retained originations beside the change in reported residential
real-estate loans:

```cypher
MATCH (l:Lender)<-[:ORIGINATED_BY]-(n:Loan) WHERE NOT (n)-[:SOLD_TO]->()
WITH l, count(n) AS kept, sum(n.amount) / 1000 AS kept_k
MATCH (l)-[:FILED]->(f0:Filing {period: '2022Q4'}), (l)-[:FILED]->(f1:Filing {period: '2023Q4'})
RETURN l.name AS lender, kept, kept_k, f1.residential_re_loans_k - f0.residential_re_loans_k AS growth_k
ORDER BY kept DESC LIMIT 10
```

## 2 · The bank (synthetic): campaign audiences

*Which existing customers share a reason to be contacted?* Each bank-layer audience comes from the
**connections between customers**, which scoring each customer on their own cannot see. The authoritative
Cypher is in [`../etl/audiences.py`](../etl/audiences.py).

**How every audience is produced**
1. The Cypher below runs inside the graph.
2. UC2 is applied: whole households are held out as the **control group** (10%, by a stable hash, so the
   same households stay held out), and one member per household is `household_primary` (one mail piece).
3. The list is written to the graph (`Audience` node + `IN_AUDIENCE` edges) and exported as
   `../data/banking-kg/audiences/UCn_*.csv`: `customer_id, household_id, slice, household_primary, reason, as_of`.
4. `python -m etl.verify` recomputes every audience in plain Python from the CSVs, without the graph, and
   must agree member-for-member.

### Results (5,000 synthetic customers, as of 2026-08-31; built 2026-10-07)

| Use case | Customers | Households | Campaign | Control (held out) | Independent check | Note |
|---|--:|--:|--:|--:|---|---|
| UC1 Household member left | 26 | 22 | 23 | 3 | matches |  |
| UC3 Estate transition | 40 | 40 | 36 | 4 | matches | 40 / 40 planted living heirs found |
| UC4 Next generation | 50 | 49 | 45 | 5 | matches | all 40 planted next-generation customers (≤ 40, active) found; 10 more qualify by the age rule |
| UC5 Household digital adoption | 512 | 463 | 447 | 65 | matches |  |
| UC6 Customers like past responders (proxy) | 2,588 | 1,628 | 2,360 | 228 | matches | **Too broad to use as-is** (about half the customers): only 14 employers, so 'same employer' is a weak signal |
| UC7 Money leaving to competitors | 546 | 466 | 478 | 68 | matches | Size inflated by the synthetic design (~35% of customers send money to a competitor) |

Friends sharing an account (50 planted pairs) are never merged into one household: 50 / 50.

### The use cases, one by one

#### UC1 — Household member left (Retention · graph need: Essential)
Active customers in a household where another member closed their accounts at their own request in
the last 60 days. *Request:* customers address + status, account_owners, accounts.close_date / close_reason_code.
```cypher
MATCH (gone:Customer)-[:MEMBER_OF]->(h:Household)<-[:MEMBER_OF]-(c:Customer)
WHERE gone.id <> c.id AND c.status = 'ACTIVE' AND gone.status = 'CLOSED'
MATCH (gone)-[o:OWNS]->(a:Account)
WHERE o.role_code = 'P' AND a.close_reason_code = 'CUSTOMER_REQUEST' AND a.close_date >= $as_of_minus_60d
RETURN c.id, h.id, max(a.close_date)
```

#### UC2 — One message per household (every campaign · Essential)
Applied to every audience, not a list of its own: household control groups and one mail piece per
household. **Cannot be done with the request:** "one member opted out, others did not" — the request has no do-not-contact flag.

#### UC3 — Estate transition (Retention · Essential)
Living customers named JOINT or BENEFICIARY on an account whose primary owner is DECEASED.
*Request:* customers.customer_status, account_owners.relationship_code. The request has no date of death.
**Compliance should approve timing and tone.**
```cypher
MATCH (dead:Customer)-[o1:OWNS]->(a:Account)<-[o2:OWNS]-(heir:Customer)
WHERE dead.status = 'DECEASED' AND heir.status = 'ACTIVE' AND o1.role_code = 'P' AND o2.role_code IN ['B', 'J']
RETURN heir.id, heir.household_id, o2.role
```

#### UC4 — Next generation (Retention · Essential)
Customers aged 40 or under who are JOINT or BENEFICIARY on an account shared with a customer aged 65+,
at least 25 years older; a recent address change is shown in the reason. *Request:* birth_year, city,
account_owners, customer_change_events. **Selecting by age needs compliance review.**
Overlaps with UC3 when the older customer has died — marketing should decide whether one person gets both messages.
```cypher
MATCH (old:Customer)-[o1:OWNS]->(a:Account)<-[o2:OWNS]-(young:Customer)
WHERE old.age >= 65 AND young.age <= 40 AND old.age - young.age >= 25
  AND o2.role_code IN ['J', 'B'] AND young.status = 'ACTIVE'
RETURN young.id, young.household_id, coalesce(young.last_address_change_dt, ''), young.city
```

#### UC5 — Household digital adoption (Engagement · Essential)
Active customers who have never logged in, living with someone who logged in at least 4 times in 90 days.
*Request:* digital_sessions.
```cypher
MATCH (u:Customer)-[:MEMBER_OF]->(h:Household)<-[:MEMBER_OF]-(c:Customer)
WHERE u.id <> c.id AND u.logins_90d >= 4 AND c.digital_user = false AND c.status = 'ACTIVE'
RETURN c.id, h.id, max(u.logins_90d)
```

#### UC6 — Customers like past responders (Growth · Essential) — **PROXY**
the request has **no campaign-response data**, so "responders" here are customers who opened High-Yield
Savings in the last 180 days, and "like" means paid by the same employer. Replace with real responses
when the bank returns campaign results.
```cypher
MATCH (r:Customer)-[:OWNS]->(n:Account) WHERE n.product_code = 'SAV-HY' AND n.open_date >= $as_of_minus_180d
MATCH (r)-[:OWNS]->(:Account)-[:PAID_BY]->(e:Counterparty)<-[:PAID_BY]-(:Account)<-[:OWNS]-(c:Customer)
WHERE c.id <> r.id AND c.status = 'ACTIVE'
  AND NOT EXISTS { MATCH (c)-[:OWNS]->(x:Account) WHERE x.product_code = 'SAV-HY' }
RETURN c.id, c.household_id, e.name, count(DISTINCT r)
```

#### UC7 — Money leaving to competitors (Retention · Helpful)
Active primary or joint owners of an account that sent money to the same competitor at least twice,
most recently within 90 days. **Competitor names come from description text** (the request has no the routing
and ACH fields) — a real bank's descriptions must be checked before this is trusted.
```cypher
MATCH (c:Customer)-[o:OWNS]->(a:Account)-[s:SENDS_TO]->(k:Counterparty)
WHERE o.role_code IN ['P', 'J'] AND c.status = 'ACTIVE' AND s.count >= 2 AND s.last_date >= $as_of_minus_90d
RETURN c.id, c.household_id, k.name, sum(s.total)
```

### Next use cases (8-15)
Not built yet. With the request: 8 wallet gap ✅ possible; 9 business owners ✅ (AUTHORISED_SIGNER); 10 bring your
loan home ✅ via `OWES` (tradelines); 11 relationship-manager change ❌ no RM table in the request; 12 service
clusters ⚠ disputes and crm_data only; 13 branch closure ❌ business_unit cannot be joined;
14 HELOC clean-up ⚠ no co-borrowers; 15 life events ❌ licensed data, not in the request.

## 3 · Across the line

Only two joins are honest (see [schema.md](schema.md#bridge--1-node-2-relationship-types)): the bank is a
`Lender`, and its mortgages are `CLASSIFIED_AS` a HMDA `LoanProduct`. They are enough to put the bank's own
book beside the market's:

**Our book in the market's taxonomy, beside the market** (demo Q15, Q16):

```cypher
// ours: 2023 originations by HMDA product
MATCH (c:CustomerLoan)-[:CLASSIFIED_AS]->(p:LoanProduct)
WHERE c.origination_date >= '2023-01-01' AND c.origination_date < '2024-01-01'
RETURN p.name AS product, count(c) AS loans, avg(c.current_interest_rate) AS avg_rate
// -> Conventional:First Lien 84 loans at 6.68%; Conventional:Subordinate Lien 5 at 7.06%

// the market: DC 2023 originations by the same products
MATCH (a:Application)-[:ORIGINATED_AS]->(n:Loan) MATCH (a)-[:FOR_PRODUCT]->(p:LoanProduct)
RETURN p.name AS product, count(n) AS loans, avg(n.interest_rate) AS avg_rate
// -> Conventional:First Lien 6,297 at 6.58%; Conventional:Subordinate Lien 1,485 at 8.22%; FHA 438; VA 396
```

**Who we compete with for the same borrower** (demo Q17): our customers' mortgages owed at other lenders
(credit-bureau tradelines, fictional names) beside the real banks that write the most conventional first
liens in DC (Citibank 260, Wells Fargo 222, Truist 221, JPMorgan Chase 188 …).

**Lenders whose book resembles ours** (vectors 1): Banking-KG Bank's generated profile, searched against
every DC lender's — Virginia National Bank, Kearny Bank, NBKC Bank and other regional banks come back.

**One graph, not two** (algorithms 2): weakly connected components find a single component of 75,147 nodes
spanning both layers.

**What would make the cross-layer story stronger** — and each is a decision, not a bug:
- extend the market layer to VA, MD and NC (spec D4), so customers' collateral can sit in real tracts;
- a government-program field (FHA / VA) in the request, so the bank's mortgages classify beyond *Conventional*;
- a real bank's own data, under its controls — at which point the synthetic layer is replaced, not joined.
