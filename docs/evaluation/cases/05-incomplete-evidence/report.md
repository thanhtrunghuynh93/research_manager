# Week of 14–20 September — Data pipeline

## Planned work
Finish the deduplication stage and report the duplicate rate on the full corpus.

## Work performed
Finished the deduplication stage and ran it on the full corpus. The duplicate rate is 11.4 %.
Also fixed the memory blow-up on the 4-million-document shard.

## Results and research learning
Deduplication removes 11.4 % of documents. The near-duplicate threshold of 0.85 Jaccard is the one
that matched manual inspection best.

## Evidence
The work is on the lab cluster, which I could not reach from Thursday because my access had
expired, so I could not export the logs or the branch to attach them.

## Deviations and blockers
My cluster access needs renewing.

## Next-week plan
Renew the cluster access, attach the run logs, and report the duplicate rate per source.
