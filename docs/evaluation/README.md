# AI evaluation set and pilot gates

Requirements section 13 defines what must be true before routine AI assessments are enabled.

## Evaluation set

De-identified student–project–weeks covering coding, literature, theory, experiments, and
writing, including: incomplete evidence, shared contributions, negative results, changed plans,
Vietnamese and English reports, and adversarial attachment text (instructions inside a README).
Evidence files named after commits or pull requests stand for the text a student attached; there
is no repository connector (ADR 0022).

Layout:

```
docs/evaluation/
  cases/<case-id>/report.md, evidence/, expected.json   ratings and expected claim statuses
  protocol.md                                            how the professor rates; how agreement is computed
```

Ten seed cases exist, covering every category above. They are de-identified constructions, and
their ratings are the specification's anchors applied by the author of the set — **not the
professor's judgement**. The pilot gate is 30 student–project–weeks rated by the professor on real
work; until those exist, agreement numbers measure agreement with the anchors, which is a check on
the prompt rather than evidence that the rubric is calibrated.

The professor-question set that sat beside these (`questions.jsonl`) evaluated the chat
assistant, and went with it in requirements 0.12 (ADR 0023). The overview's counts are checked by
ordinary tests against the database instead.

The harness in `backend/tests/evaluation` keeps two questions apart. Contract properties — the
index withheld when evidence is absent, no citation outside the snapshot, no instruction obeyed
from a README — are pass/fail and run on every CI pass against the deterministic gateway. Agreement
with the professor needs the real provider, runs under `RM_EVAL=1`, and is reported rather than
asserted. See [protocol.md](protocol.md) for why, and for what each measure means.

## Pilot gates

- At least 30 student–project–weeks reviewed by the professor.
- All authorization scenarios pass; all exact counts and dates on the overview match the database.
- At least 95 % of evaluated factual claims are supported by their cited evidence.
- Missing-evidence cases produce an uncertainty response, never an invented result.
- Agreement threshold agreed with the professor during the pilot, not set in advance.
