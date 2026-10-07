# Benchmark results — demo questions and campaign audiences

Measured 2026-10-07 11:21 IST on macOS-15.7.9-x86_64-i386-64bit (x86_64), Samyama engine 1.7.1, graph `bankingkg2`: 75,179 nodes / 241,222 relationships. 3 runs after one warm-up; wall time including the HTTP round trip.

| Query | Rows | Min (ms) | Median (ms) |
|---|--:|--:|--:|
| Q1 Where did this number come from? One mortgage traced to its application, lender, legal entity, Call Report, tract and buyer | 2 | 18.6 | 21.5 |
| Q2 Two filings, two regulators: Truist's large DC mortgages sold to Fannie Mae and Freddie Mac, beside the two Call Reports that bracket 2023 | 66 | 52.7 | 53.8 |
| Q3 Who keeps what they write? Citibank's DC loans never sold to anyone | 40 | 26.5 | 31.2 |
| Q4 If this tract turns, who is exposed? The busiest tract in DC and every lender with a large loan there | 23 | 22.9 | 23.5 |
| Q5 What an examiner sees first: denied applications in the lowest-income tracts, and the reasons given | 44 | 29.8 | 33.2 |
| Q6 One lender, both books: banks making DC mortgages and SBA-guaranteed business loans, with their 2023Q4 Call Report | 67 | 37.9 | 38.2 |
| Q7 Invisible row by row: addresses where several businesses each drew their own guaranteed loan | 5 | 9.1 | 10.0 |
| Q8 Now our own bank. One family as Banking-KG Bank sees it: four people at one address, what they own, and whose products they are | 8 | 39.3 | 43.1 |
| Q9 Use case 1, a family starts to leave: the member who closed their accounts in the last 60 days, and the ones still with us | 55 | 44.7 | 45.6 |
| Q10 Use case 3, estate transition: customers who have passed away, their accounts, and the living heirs named on them | 48 | 36.3 | 39.6 |
| Q11 Use case 4, the next generation: much younger joint owners and beneficiaries on older customers' accounts | 54 | 52.3 | 54.3 |
| Q12 Use case 7, money leaving: households sending regular transfers to one competitor in the last 90 days | 40 | 70.4 | 70.8 |
| Q13 Bring your mortgage home: active customers paying a mortgage at another lender, and the accounts they already have with us | 130 | 106.0 | 109.4 |
| Q14 Home equity behind our own first mortgage: borrowers whose HELOC sits in second place on the house | 30 | 28.0 | 32.8 |
| Q15 Across the line: Banking-KG Bank as one more lender in the market — its 2023 mortgages, filed in HMDA's own product taxonomy | 89 | 123.8 | 124.9 |
| Q16 Same product, two worlds: our 2023 first-lien mortgages and the market's largest conventional first-lien originations meet at one LoanProduct | 352 | 408.8 | 418.1 |
| Q17 Who we compete with for the same borrower: our customers' mortgages owed elsewhere, beside the banks that write the most conventional first liens in DC | 56 | 376.7 | 387.0 |
| Q18 Show me this lender's entire book: M&T Bank — its Call Reports, legal entity, DC mortgages and buyers, SBA loans and their industries. The same picture Q15 drew for our own bank | 360 | 343.0 | 354.7 |
| UC1 Household member left | 26 | 8.7 | 9.4 |
| UC3 Estate transition | 48 | 8.7 | 9.2 |
| UC4 Next generation | 54 | 16.2 | 16.2 |
| UC5 Household digital adoption | 512 | 12.6 | 14.5 |
| UC6 Customers like past responders (proxy) | 3,600 | 407.8 | 422.2 |
| UC7 Money leaving to competitors | 642 | 63.4 | 66.2 |

Single machine. Not a performance claim; rerun on the target host before quoting any figure.
