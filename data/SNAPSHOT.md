# Snapshot record

The binary is a release asset, not source (issue 13). It lives at `../data/banking-kg/banking-kg.sgsnap`.
This file records what it is.

| | |
|---|---|
| File | `banking-kg.sgsnap` |
| Scope | Market: Washington DC, HMDA 2023; SBA 7(a) FY2020+ and 504 FY2010+; Call Reports 2022Q4–2023Q4 (real). Bank: Banking-KG Bank, 5,000 customers as of 2026-08-31 (synthetic) |
| Size | 7,259,889 bytes (gzip; 53,858,084 uncompressed) |
| sha256 | `e70f56e210f236eba660fab2e4b63615aa814f8ef96cbcb1319537fbb11b72fb` |
| Contents | 75,179 nodes / 241,222 relationships (29 node types, 33 relationship types), 6 campaign audiences, Lender book profiles, 384-dim embeddings on 930 nodes across 10 labels |
| Exported | 2026-10-07, engine `samyama:1.7.1-internal-licensed`, tenant `bankingkg2` |
| Checked | imported into an empty tenant in 1.9 s: 75,179 nodes / 241,222 relationships, embeddings present |

Import:

```bash
curl -X POST localhost:8081/api/tenants -H 'Content-Type: application/json' -d '{"id":"bankingkg","name":"bankingkg"}'
curl -X POST localhost:8081/api/tenants/bankingkg/snapshot/import -F "file=@../data/banking-kg/banking-kg.sgsnap"
```

Vector Search and NLQ also need the tenant's `embed_config` and `nlq_config`, which are not part of the
snapshot: run `python -m etl.embed` to set the embed config (it re-embeds; harmless), and see
[`../demo/nlq.md`](../demo/nlq.md) for the NLQ config.

## Previous snapshot

`banking-kg-dc-2023.sgsnap` (market layer only, 31,128 nodes / 83,840 relationships including 200 duplicate
`LOCATED_AT` / `IN_INDUSTRY` edges since removed; sha256 `a2103528…bc25e`, exported 2026-10-06, tenant
`bankingkg`). Superseded by the file above.
