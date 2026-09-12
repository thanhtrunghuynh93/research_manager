# Week of 14–20 September — Convergence bound

## Planned work
Prove the O(1/√T) bound for the projected variant, or find the counterexample.

## Work performed
Proved the bound under bounded gradients and a decreasing step size. The step where the projection
is non-expansive needed the constraint set to be convex, which I had been assuming without saying
so; the statement now carries that hypothesis.

## Results and research learning
Theorem 3.1 holds as stated with convexity added. I also found that the constant is worse than the
unprojected case by a factor of 2, which the earlier draft claimed was identical — that claim was
wrong and is now corrected.

## Evidence
The proof note, four pages, with the corrected constant.

## Deviations and blockers
None.

## Next-week plan
Check whether the factor of 2 is tight with a small numerical experiment.
