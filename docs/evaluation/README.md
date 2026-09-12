# AI evaluation set and pilot gates

Requirements section 13 defines what must be true before routine AI assessments are enabled.

## Evaluation set

De-identified student–project–weeks covering coding, literature, theory, experiments, and
writing, including: incomplete evidence, shared contributions, negative results, changed plans,
Vietnamese and English reports, and adversarial repository text (instructions inside a README).

Layout:

```
docs/evaluation/
  cases/<case-id>/report.md, evidence/, expected.json   ratings and expected claim statuses
  questions.jsonl                                        professor questions with expected facts
  protocol.md                                            how the professor rates; how agreement is computed
```

Ten seed cases exist, covering every category above. They are de-identified constructions, and
their ratings are the specification's anchors applied by the author of the set — **not the
professor's judgement**. The pilot gate is 30 student–project–weeks rated by the professor on real
work; until those exist, agreement numbers measure agreement with the anchors, which is a check on
the prompt rather than evidence that the rubric is calibrated.

`questions.jsonl` holds 20 of the 50 the gate asks for, chosen to cover every question kind the
assistant must handle: facts computed in SQL, narrative, longitudinal across a rubric change,
uncertainty, confidentiality, and one adversarial.

The harness in `backend/tests/evaluation` keeps two questions apart. Contract properties — the
index withheld when evidence is absent, no citation outside the snapshot, no instruction obeyed
from a README — are pass/fail and run on every CI pass against the deterministic gateway. Agreement
with the professor needs the real provider, runs under `RM_EVAL=1`, and is reported rather than
asserted. See [protocol.md](protocol.md) for why, and for what each measure means.

## Pilot gates

- At least 30 student–project–weeks reviewed by the professor and 50 questions answered.
- All authorization scenarios pass; all exact count/date answers match the database.
- At least 95 % of evaluated factual claims are supported by their cited evidence.
- Missing-evidence cases produce an uncertainty response, never an invented result.
- Agreement threshold agreed with the professor during the pilot, not set in advance.
