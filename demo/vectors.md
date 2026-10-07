# banking-kg — Vector Search segment (9 searches)

Read by `demo_vector_search.py` (GRAPH=bankingkg): the first table, one row per search. The question is
embedded server-side with the tenant's embed config (local Ollama `all-minilm`, 384-dim; no API key) and the
nearest nodes are returned by cosine similarity. Embeddings are written by `etl/embed.py` (930 nodes).

Market: **Lender** by its *book profile*, a sentence generated from the graph (type, headquarters, DC
mortgages, main product, share kept, main buyer, SBA industries — and for Banking-KG Bank, its own loan book);
Industry, Franchise, Purchaser, DenialReason, LoanProduct. Bank: Product, Counterparty (competitors,
employers, lenders), MerchantCategory, Audience. Results checked on tenant bankingkg2 on 2026-10-07.

| # | Question | Label | Top K | Show on graph | What the nearest neighbours show |
|---|---|---|---|---|---|
| 1 | bank headquartered in Richmond, Virginia with mortgage, auto, personal and home equity loans | Lender | 6 | yes | real Virginia banks first — Virginia Partners Bank, Virginia National Bank, The Freedom Bank of Virginia: the peers Banking-KG Bank would be compared with |
| 2 | community bank that keeps its loans and lends to small businesses | Lender | 5 | yes | Bridgewater Bank, Commonwealth Business Bank, United Community Bank, Open Bank, First Business Bank |
| 3 | online mortgage company that sells everything to Fannie Mae | Lender | 5 | no | Zillow Home Loans, loanDepot and other sellers |
| 4 | credit union for military families | Lender | 5 | no | Navy Federal Credit Union first |
| 5 | high yield savings account | Product | 5 | no | High-Yield Savings, Statement Savings, Money Market Account |
| 6 | online bank customers are moving money to | Counterparty | 5 | yes | Apex Digital, Swiftsave Online Bank — the fictional online competitors |
| 7 | hospital or health system employer | Counterparty | 5 | no | Commonwealth Health System first (a fictional employer) |
| 8 | customers moving their money to another bank | Audience | 3 | yes | "Money leaving to competitors" first |
| 9 | too much debt compared to income | DenialReason | 5 | yes | Debt-to-income ratio first |

Search 1 is the cross-layer moment: a description of the synthetic bank lands on real banks with the same
shape of business. Searching with Banking-KG Bank's stored profile itself returns it at 1.00, then Kearny
Bank, Virginia National Bank and NBKC Bank (0.70–0.71).
