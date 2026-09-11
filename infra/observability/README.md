# Observability

The MVP relies on structured JSON logs from every container (`docker compose logs`) and the
Prometheus endpoint at `/api/metrics` (queue depth, oldest queued job, sync staleness, model
errors, citation validation failures, access denials — added by each module as it lands).

If a metrics stack is added later, put the Grafana dashboards under `dashboards/` and the log
shipper configuration (vector or promtail) in this folder. Never ship raw report text or prompts
to logs (requirements section 11, Observability).
