# Observability

The MVP relies on structured JSON logs from every container (`docker compose logs`) and the
Prometheus endpoint at `/api/metrics` (queue depth, oldest queued job, model
errors, citation validation failures, access denials — added by each module as it lands).
`rm_citation_validation_failures_total` keeps its `surface` label with one value, `assessment`:
the chat assistant was withdrawn in migration 0029 (ADR 0023), so a panel or alert that queried
`surface="assistant"` goes flat after that deploy and can be deleted.

If a metrics stack is added later, put the Grafana dashboards under `dashboards/` and the log
shipper configuration (vector or promtail) in this folder. Never ship raw report text or prompts
to logs (requirements section 11, Observability).
