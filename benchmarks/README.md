# Benchmarks

```bash
python -m benchmarks.run --url http://localhost:8081 --graph bankingkg
```

Times every question in [`../demo/queries.cypher`](../demo/queries.cypher) and every campaign-audience
query (use cases 1, 3–7) on the loaded graph, and writes [`results.md`](results.md): rows returned, min and
median time, plus the engine version, machine and graph size they were measured on.

These are single-machine numbers. They show the questions are interactive at this size; they are not a
performance claim. Rerun on the target host before quoting any figure.
