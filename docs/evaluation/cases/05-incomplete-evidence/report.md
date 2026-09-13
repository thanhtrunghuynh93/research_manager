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
The work is on a private branch that the connector could not read this week; the sync failed with
an authorization error on Thursday.

## Deviations and blockers
The repository connection needs reauthorising.

## Next-week plan
Reauthorise the connection and report the duplicate rate per source.
