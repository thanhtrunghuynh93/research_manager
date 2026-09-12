# Week of 14–20 September — Evaluation pipeline

## Planned work
Build the evaluation pipeline with Student B and land it on main.

## Work performed
Wrote the metric implementations and the aggregation layer. Student B wrote the runner and the
config schema. We pair-reviewed and B merged the pull request on Friday.

## Results and research learning
The pipeline runs end to end. The per-query breakdown revealed that 4 % of queries have no relevant
document at all in our judgments, which silently depressed every metric we had reported before.

## Evidence
PR #212, co-authored commit `3d9f001`, and the per-query breakdown.

## Deviations and blockers
None.

## Next-week plan
Re-run the September numbers with the empty-judgment queries excluded and report the difference.
