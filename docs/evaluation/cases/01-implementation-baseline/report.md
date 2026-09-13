# Week of 14–20 September — Retrieval baselines

## Planned work
Reproduce the BM25 and dense-retrieval baselines on the internal corpus and record nDCG@10.

## Work performed
Implemented the corpus loader (`data/loader.py`), wired the BM25 baseline through the shared
evaluation harness, and ran both baselines on the 12k-document split. Fixed an off-by-one in the
relevance-judgment parser that had been inflating nDCG by roughly two points.

## Results and research learning
BM25 reaches nDCG@10 = 0.412; the dense baseline reaches 0.438. The gap is smaller than the
published 6-point difference, and the ablation suggests our corpus has shorter documents than the
one in the paper, which favours lexical matching. This is a property of the corpus, not a bug.

## Evidence
Commits `a1f3c9e` and `77b2d04`; the evaluation run log.

## Deviations and blockers
None.

## Next-week plan
Run the hybrid fusion baseline and report nDCG@10 with a 95 % bootstrap interval.
