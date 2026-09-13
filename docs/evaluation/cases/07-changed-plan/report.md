# Week of 14–20 September — Ablation, abandoned

## Planned work
Run the three-way ablation agreed last week (frozen baseline: ablation A, B, C, weight 1 each).

## Work performed
Started ablation A and found that the checkpoint the ablations branch from was trained with a
different tokenizer than the one in the config. Every number from the last three weeks that used
that checkpoint is not comparable. I stopped the ablations, traced the mismatch to a config
override added on 2 September, and re-trained the reference checkpoint.

## Results and research learning
The comparison base was invalid. Ablations A, B and C were not run. Re-training the reference is
the prerequisite for all three, so the plan is deferred rather than dropped.

## Evidence
The config diff and the re-training log.

## Deviations and blockers
The frozen plan is not met: zero of the three ablations ran. I judged that running them on an
invalid base would have produced three weeks of unusable numbers.

## Next-week plan
Run ablations A, B and C on the re-trained reference.
