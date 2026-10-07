// banking-kg — Query Console segment (18 questions). Read by demo_queries.py (GRAPH=bankingkg) and by
// benchmarks/run.py.
//
// Format: "// Q<n> · <question>", an options line "// walk=<n> expand=<yes|no>", then the Cypher;
// a blank line ends the block. Every question returns node AND relationship variables so the Auto
// view draws a graph.
//
// Three acts:
//   Q1-Q7    THE MARKET    real public data: Washington DC 2023 — HMDA, GLEIF, FDIC Call Reports, SBA
//   Q8-Q14   THE BANK      synthetic: Banking-KG Bank's 5,000 customers, as of 2026-08-31. The engine has no
//                          date() functions, so the 60/90-day windows are fixed dates (2026-07-02, 2026-06-02)
//   Q15-Q18  ACROSS        the bank inside its market: the bridge, and the closer
// Spec question numbers in brackets. Validated on engine 1.7.1 enterprise (:8081) on 2026-10-07.

// Q1 · Where did this number come from? One mortgage traced to its application, lender, legal entity, Call Report, tract and buyer [spec 1]
// walk=5 expand=yes
MATCH (a:Application)-[o:ORIGINATED_AS]->(n:Loan {id: 'LOAN-000124'})-[s:SOLD_TO]->(p:Purchaser)
MATCH (n)-[ob:ORIGINATED_BY]->(l:Lender)-[r:REGISTERED_AS]->(e:LegalEntity)
MATCH (a)-[it:IN_TRACT]->(t:Tract)-[ic:IN_COUNTY]->(c:County)
MATCH (l)-[fi:FILED]->(f:Filing) WHERE f.period IN ['2022Q4', '2023Q4']
RETURN a, o, n, s, p, ob, l, r, e, it, t, ic, c, fi, f

// Q2 · Two filings, two regulators: Truist's large DC mortgages sold to Fannie Mae and Freddie Mac, beside the two Call Reports that bracket 2023 [spec 2]
// walk=4 expand=yes
MATCH (l:Lender {name: 'Truist Bank'})-[fi:FILED]->(f:Filing) WHERE f.period IN ['2022Q4', '2023Q4']
MATCH (l)<-[ob:ORIGINATED_BY]-(n:Loan)-[s:SOLD_TO]->(p:Purchaser) WHERE p.name IN ['Fannie Mae', 'Freddie Mac'] AND n.amount >= 600000
RETURN l, fi, f, ob, n, s, p

// Q3 · Who keeps what they write? Citibank's DC loans never sold to anyone [spec 4]
// walk=4 expand=yes
MATCH (l:Lender {name: 'Citibank, National Association'})<-[ob:ORIGINATED_BY]-(n:Loan)
WHERE NOT (n)-[:SOLD_TO]->()
WITH l, ob, n LIMIT 40
RETURN l, ob, n

// Q4 · If this tract turns, who is exposed? The busiest tract in DC and every lender with a large loan there [spec 5]
// walk=4 expand=yes
MATCH (t:Tract {name: 'Tract 0032.00'})<-[it:IN_TRACT]-(a:Application)-[o:ORIGINATED_AS]->(n:Loan)-[ob:ORIGINATED_BY]->(l:Lender)
WHERE n.amount >= 850000
RETURN t, it, a, o, n, ob, l

// Q5 · What an examiner sees first: denied applications in the lowest-income tracts, and the reasons given [spec 13]
// walk=4 expand=yes
MATCH (t:Tract)<-[it:IN_TRACT]-(a:Application)-[d:DENIED_FOR]->(r:DenialReason)
WHERE t.income_pct_of_msa < 30 AND a.loan_amount >= 400000
RETURN t, it, a, d, r

// Q6 · One lender, both books: banks making DC mortgages and SBA-guaranteed business loans, with their 2023Q4 Call Report [spec §4]
// walk=4 expand=yes
MATCH (l:Lender)<-[mb:MADE_BY]-(s:SBALoan)
WHERE l.name IN ['Wells Fargo Bank, National Association', 'PNC Bank, National Association', 'Bank of America, National Association', 'JPMorgan Chase Bank, National Association']
MATCH (l)-[fi:FILED]->(f:Filing) WHERE f.period = '2023Q4'
RETURN l, mb, s, fi, f

// Q7 · Invisible row by row: addresses where several businesses each drew their own guaranteed loan [spec 21]
// walk=4 expand=yes
MATCH (ad:Address)<-[:LOCATED_AT]-(x:Business)
WITH ad, count(x) AS n WHERE n >= 4
MATCH (ad)<-[la:LOCATED_AT]-(b:Business)-[bo:BORROWED]->(s:SBALoan)-[mb:MADE_BY]->(l)
RETURN ad, la, b, bo, s, mb, l

// Q8 · Now our own bank. One family as Banking-KG Bank sees it: four people at one address, what they own, and whose products they are
// walk=4 expand=yes
MATCH (h:Household) WHERE h.size = 4 WITH h LIMIT 1
MATCH (c:Customer)-[m:MEMBER_OF]->(h)
MATCH (c)-[o:OWNS]->(a:Account)-[p:OF_PRODUCT]->(pr:Product)-[ob:OFFERED_BY]->(b:Lender)
RETURN h, m, c, o, a, p, pr, ob, b

// Q9 · Use case 1, a family starts to leave: the member who closed their accounts in the last 60 days, and the ones still with us
// walk=4 expand=yes
MATCH (gone:Customer)-[m1:MEMBER_OF]->(h:Household)<-[m2:MEMBER_OF]-(c:Customer)
WHERE gone.status = 'CLOSED' AND c.status = 'ACTIVE'
MATCH (gone)-[o:OWNS]->(a:Account)
WHERE o.role_code = 'P' AND a.close_reason_code = 'CUSTOMER_REQUEST' AND a.close_date >= '2026-07-02'
RETURN gone, m1, h, m2, c, o, a

// Q10 · Use case 3, estate transition: customers who have passed away, their accounts, and the living heirs named on them
// walk=4 expand=yes
MATCH (dead:Customer)-[o1:OWNS]->(a:Account)<-[o2:OWNS]-(heir:Customer)
WHERE dead.status = 'DECEASED' AND heir.status = 'ACTIVE' AND o1.role_code = 'P' AND o2.role_code IN ['B', 'J']
RETURN dead, o1, a, o2, heir

// Q11 · Use case 4, the next generation: much younger joint owners and beneficiaries on older customers' accounts
// walk=4 expand=yes
MATCH (old:Customer)-[o1:OWNS]->(a:Account)<-[o2:OWNS]-(young:Customer)
WHERE old.age >= 65 AND young.age <= 40 AND old.age - young.age >= 25 AND o2.role_code IN ['J', 'B'] AND young.status = 'ACTIVE'
RETURN old, o1, a, o2, young

// Q12 · Use case 7, money leaving: households sending regular transfers to one competitor in the last 90 days
// walk=4 expand=yes
MATCH (h:Household)<-[m:MEMBER_OF]-(c:Customer)-[o:OWNS]->(a:Account)-[s:SENDS_TO]->(k:Counterparty)
WHERE k.name = 'NORTHSTAR FED' AND s.count >= 2 AND s.last_date >= '2026-06-02' AND o.role_code = 'P'
WITH h, m, c, o, a, s, k LIMIT 40
RETURN h, m, c, o, a, s, k

// Q13 · Bring your mortgage home: active customers paying a mortgage at another lender, and the accounts they already have with us
// walk=4 expand=yes
MATCH (c:Customer)-[w:OWES]->(k:Counterparty)
WHERE w.account_type = 'MORTGAGE' AND c.status = 'ACTIVE'
WITH c, w, k LIMIT 30
MATCH (c)-[o:OWNS]->(a:Account)
RETURN c, w, k, o, a

// Q14 · Home equity behind our own first mortgage: borrowers whose HELOC sits in second place on the house
// walk=4 expand=yes
MATCH (cu:Customer)-[b1:BORROWS]->(h:CustomerLoan)-[s:SECURED_BY]->(co:Collateral)
WHERE s.lien_position = 2
MATCH (cu)-[b2:BORROWS]->(m:CustomerLoan) WHERE m.loan_type = 'MORTGAGE' AND m.status = 'ACTIVE'
WITH cu, b1, h, s, co, b2, m LIMIT 30
RETURN cu, b1, h, s, co, b2, m

// Q15 · Across the line: Banking-KG Bank as one more lender in the market — its 2023 mortgages, filed in HMDA's own product taxonomy
// walk=5 expand=yes
MATCH (b:Lender {id: 'BANKING-KG'})<-[ob:OFFERED_BY]-(pr:Product)<-[op:OF_PRODUCT]-(a:Account)-[hl:HAS_LOAN]->(c:CustomerLoan)-[ca:CLASSIFIED_AS]->(p:LoanProduct)
WHERE c.origination_date >= '2023-01-01' AND c.origination_date < '2024-01-01'
RETURN b, ob, pr, op, a, hl, c, ca, p

// Q16 · Same product, two worlds: our 2023 first-lien mortgages and the market's largest conventional first-lien originations meet at one LoanProduct
// walk=5 expand=yes
MATCH (c:CustomerLoan)-[ca:CLASSIFIED_AS]->(p:LoanProduct {name: 'Conventional:First Lien'})
WHERE c.origination_date >= '2023-01-01' AND c.origination_date < '2024-01-01'
WITH p, c, ca LIMIT 8
MATCH (p)<-[fp:FOR_PRODUCT]-(a:Application)-[oa:ORIGINATED_AS]->(n:Loan)-[ob:ORIGINATED_BY]->(l:Lender)
WHERE n.amount >= 6000000
RETURN c, ca, p, fp, a, oa, n, ob, l

// Q17 · Who we compete with for the same borrower: our customers' mortgages owed elsewhere, beside the banks that write the most conventional first liens in DC
// walk=4 expand=yes
MATCH (c:Customer)-[w:OWES]->(k:Counterparty) WHERE w.account_type = 'MORTGAGE' AND c.status = 'ACTIVE'
WITH c, w, k LIMIT 20
MATCH (c)-[b:BORROWS]->(m:CustomerLoan)-[ca:CLASSIFIED_AS]->(p:LoanProduct)
MATCH (p)<-[fp:FOR_PRODUCT]-(a:Application)-[oa:ORIGINATED_AS]->(n:Loan)-[ob:ORIGINATED_BY]->(l:Lender)
WHERE l.name IN ['Citibank, National Association', 'Wells Fargo Bank, National Association', 'Truist Bank'] AND n.amount >= 5000000
RETURN c, w, k, b, m, ca, p, fp, a, oa, n, ob, l

// Q18 · Show me this lender's entire book: M&T Bank — its Call Reports, legal entity, DC mortgages and buyers, SBA loans and their industries. The same picture Q15 drew for our own bank [spec 25]
// walk=6 expand=yes
MATCH (l:Lender {name: 'Manufacturers and Traders Trust Company'})-[fi:FILED]->(f:Filing)
MATCH (l)-[r:REGISTERED_AS]->(e:LegalEntity)
MATCH (l)<-[ob:ORIGINATED_BY]-(n:Loan) WHERE n.amount >= 500000
OPTIONAL MATCH (n)-[so:SOLD_TO]->(p:Purchaser)
MATCH (l)<-[mb:MADE_BY]-(s:SBALoan)<-[bo:BORROWED]-(b:Business)-[ii:IN_INDUSTRY]->(i:Industry) WHERE s.gross_approval >= 1000000
RETURN l, fi, f, r, e, ob, n, so, p, mb, s, bo, b, ii, i
