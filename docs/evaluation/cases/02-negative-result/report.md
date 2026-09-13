# Week of 14–20 September — Curriculum ordering

## Planned work
Test whether curriculum ordering of the training data improves convergence on the small split.

## Work performed
Implemented three orderings (length-ascending, difficulty-ascending by a proxy score, and random),
ran five seeds each, and compared validation loss at 2k, 5k and 10k steps.

## Results and research learning
Curriculum ordering does not help. At 10k steps the three orderings are within 0.004 validation
loss of each other, which is inside the seed-to-seed spread of 0.011. The difficulty proxy
correlates with sequence length at r = 0.82, so the two "different" curricula were nearly the same
experiment; that is the useful finding and it invalidates the design in the proposal. I am dropping
this line rather than tuning it further.

## Evidence
Run table with five seeds per condition; the correlation plot.

## Deviations and blockers
None. The hypothesis was tested and not supported.

## Next-week plan
Write the negative result into the methods notes and move to the data-mixing experiment.
