"""The metric series this system publishes (architecture §12, §15).

The list is the one the requirements name: ingestion failures, stale connections, queue latency,
assessment versions, model errors, citation validation failures, and access denials. Each is here
because its absence is invisible — a worker that stopped polling, a credential that expired three
weeks ago, and a model that refuses every call all look like a quiet week from the outside.

One rule governs what may become a label: never anything that identifies a person or carries
research text. A metric is scraped into a system with different access rules from this one, so a
student id in a label would be a disclosure through the monitoring stack. Workspace-level counts
and job names only.

Only the definitions live here, because `app.core` may not import the modules that would fill
them. `app/observability.py` does the reading (docs/repo_layout.md §3.3).
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge

# ---------------------------------------------------------------- counters (incremented in place)

MODEL_CALLS = Counter(
    "rm_model_calls_total",
    "Provider calls by prompt and outcome.",
    labelnames=("prompt_id", "status"),
)
CITATION_FAILURES = Counter(
    "rm_citation_validation_failures_total",
    "Citations dropped because they were not in the snapshot or the retrieved set.",
    labelnames=("surface",),
)
ACCESS_DENIALS = Counter(
    "rm_access_denials_total",
    "Requests refused by the authorization layer, by status.",
    labelnames=("status",),
)

# ---------------------------------------------------------------- gauges (refreshed on a schedule)

QUEUE_DEPTH = Gauge("rm_queue_depth", "Jobs waiting to run.", labelnames=("status",))
QUEUE_OLDEST_SECONDS = Gauge(
    "rm_queue_oldest_seconds", "Age of the oldest job still waiting, in seconds."
)
JOB_FAILURES = Gauge(
    "rm_job_failures", "Jobs in a failed state, by task name.", labelnames=("task",)
)
SYNC_STALENESS_SECONDS = Gauge(
    "rm_sync_staleness_seconds", "Time since the most recent successful repository sync."
)
REPOSITORIES = Gauge(
    "rm_repositories", "Connected repositories, by connection state.", labelnames=("state",)
)
ANALYSIS_RUNS = Gauge("rm_analysis_runs", "Assessment runs by state.", labelnames=("state",))
ASSESSMENT_VERSIONS = Gauge("rm_assessment_versions", "Assessment versions written.")
REVIEW_QUEUE = Gauge("rm_review_queue", "Draft assessments awaiting the professor.")
EMAIL_DELIVERIES = Gauge("rm_email_deliveries", "Email deliveries by state.", labelnames=("state",))
