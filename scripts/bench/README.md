# Performance benchmarks

k6 scripts for the targets in architecture section 15:

| Script | Target |
| --- | --- |
| `overview.js` | Professor overview p95 < 2 s at 10 concurrent sessions |
| `report_submit.js` | Report submission p95 < 2 s |
| `assistant.js` | Assistant first token p95 < 10 s, completion < 30 s |

Seed the benchmark dataset first: `uv run python scripts/seed_benchmark.py` (50 students, 30 projects,
3 years, 100k chunks). Scripts land with the modules they exercise.
