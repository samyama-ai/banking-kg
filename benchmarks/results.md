# Benchmark results — demo questions and campaign audiences

Measured 2026-10-07 10:34 on macOS-15.7.9-x86_64-i386-64bit (x86_64), Samyama engine 1.7.1, graph `bankingkg2`: 75,179 nodes / 241,222 relationships. 3 runs after one warm-up; wall time including the HTTP round trip.

| Query | Rows | Min (ms) | Median (ms) |
|---|--:|--:|--:|
| Q1 Where did this number come from? One mortgage traced to its application, lender, legal entity, Call Report, tract and buyer | 2 | 12.1 | 12.7 |
| Q2 Two filings, two regulators: Truist's large DC mortgages sold to Fannie Mae and Freddie Mac, beside the two Call Reports that bracket 2023 | 66 | 34.4 | 35.4 |
| Q3 Who keeps what they write? Citibank's DC loans never sold to anyone | 40 | 17.9 | 19.3 |
| Q4 If this tract turns, who is exposed? The busiest tract in DC and every lender with a large loan there | 23 | 15.7 | 16.6 |
| Q5 What an examiner sees first: denied applications in the lowest-income tracts, and the reasons given | 44 | 18.5 | 18.8 |
| Q6 One lender, both books: banks making DC mortgages and SBA-guaranteed business loans, with their 2023Q4 Call Report | 67 | 25.6 | 26.1 |
| Q7 Invisible row by row: addresses where several businesses each drew their own guaranteed loan | 5 | 6.6 | 6.9 |
| Q8 Now our own bank. One family as Banking-KG Bank sees it: four people at one address, what they own, and whose products they are | 8 | 28.2 | 31.7 |
| Q9 Use case 1, a family starts to leave: the member who closed their accounts in the last 60 days, and the ones still with us | 55 | 30.5 | 30.8 |
| Q10 Use case 3, estate transition: customers who have passed away, their accounts, and the living heirs named on them | 48 | 25.2 | 27.2 |
| Q11 Use case 4, the next generation: much younger joint owners and beneficiaries on older customers' accounts | 54 | 39.7 | 44.0 |
| Q12 Use case 7, money leaving: households sending regular transfers to one competitor in the last 90 days | 40 | 51.5 | 52.5 |
| Q13 Bring your mortgage home: active customers paying a mortgage at another lender, and the accounts they already have with us | 130 | 77.8 | 83.0 |
| Q14 Home equity behind our own first mortgage: borrowers whose HELOC sits in second place on the house | 30 | 23.7 | 23.7 |
| Q15 Across the line: Banking-KG Bank as one more lender in the market — its 2023 mortgages, filed in HMDA's own product taxonomy | 89 | 86.9 | 88.5 |
| Q16 Same product, two worlds: our 2023 first-lien mortgages and the market's largest conventional first-lien originations meet at one LoanProduct | 352 | 238.8 | 294.4 |
| Q17 Who we compete with for the same borrower: our customers' mortgages owed elsewhere, beside the banks that write the most conventional first liens in DC | 56 | 245.7 | 256.0 |
| Q18 Show me this lender's entire book: M&T Bank — its Call Reports, legal entity, DC mortgages and buyers, SBA loans and their industries. The same picture Q15 drew for our own bank | 360 | 200.4 | 202.7 |
| UC1 Household member left | 26 | 6.6 | 6.9 |
| UC3 Estate transition | 48 | 6.4 | 6.5 |
| UC4 Next generation | 54 | 13.0 | 13.2 |
| UC5 Household digital adoption | 512 | 10.9 | 11.2 |
| UC6 Customers like past responders (proxy) | 3,600 | 410.7 | 444.2 |
| UC7 Money leaving to competitors | 642 | 43.2 | 45.1 |

Single machine. Not a performance claim; rerun on the target host before quoting any figure.
