# banking-kg — Graph Algorithms segment (5 steps)

Read by `demo_algorithms.py` (GRAPH=bankingkg): the first table. Source and target are node ids, resolved to
engine ids at run time. Relationships point from a customer to an account to a product to the bank, and from
a loan to its lender; the path algorithms follow that direction. Measured on tenant bankingkg2 (75,179 nodes)
on 2026-10-07; each runs in 1–5 s on the whole graph.

| # | Algorithm id | Card | Question | Params | Expected |
|---|---|---|---|---|---|
| 1 | pagerank | PageRank | What holds this graph together? | damping_factor=0.85, iterations=20 | **Banking-KG Bank** first (every account flows to it through its products), then the DC county, the conventional first-lien product (where both layers meet) and the MSA; then Statement Savings, Fannie Mae, Freddie Mac, Navy Federal and Truist |
| 2 | wcc | Weakly Connected Components | Is the bank part of its market, or a separate graph? | | 20 components: **one of 75,147 nodes holding both layers**, the 17 business units (the request gives no way to join them) and two lenders whose only DC activity touches nothing else |
| 3 | bfs | BFS Shortest Path | How does a customer reach the bank? | source=PATTERN-CUST-000002417, target=BANKING-KG | Elizabeth Jackson → Everyday Checking …5596 → Everyday Checking → Banking-KG Bank, 3 hops |
| 4 | bfs | BFS Shortest Path | How does a customer's mortgage reach the market? | source=PATTERN-CUST-000000007, target=Conventional:First Lien | Donald Lewis → 15 YR FIXED loan …0005 → Conventional:First Lien, 2 hops: the same node 6,297 DC originations point to |
| 5 | triangle_count | Triangle Count | Does every record close back on itself? | | 13,380 triangles: 8,616 from the market (application → loan → lender closes on application → lender for every loan) and 4,764 in the bank (customer → account → loan or card closes on the customer) |
