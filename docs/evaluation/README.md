# AI evaluation set and pilot gates

Requirements section 13 defines what must be true before routine AI assessments are enabled.

## Evaluation set

De-identified student–project–weeks covering coding, literature, theory, experiments, and
writing, including: incomplete evidence, shared contributions, negative results, changed plans,
Vietnamese and English reports, and adversarial repository text (instructions inside a README).

Layout (to be created with the assessment module):

```
docs/evaluation/
  cases/<case-id>/report.md, evidence/, expected.json   professor ratings and expected claim statuses
  questions.jsonl                                        50 professor questions with expected facts and citations
  protocol.md                                            how the professor rates; how agreement is computed
```

The harness in `backend/tests/evaluation` runs every case through the pipeline with the real
gateway when `RM_EVAL=1` and reports agreement by dimension, material correction rate, and
run-to-run variation.

## Pilot gates

- At least 30 student–project–weeks reviewed by the professor and 50 questions answered.
- All authorization scenarios pass; all exact count/date answers match the database.
- At least 95 % of evaluated factual claims are supported by their cited evidence.
- Missing-evidence cases produce an uncertainty response, never an invented result.
- Agreement threshold agreed with the professor during the pilot, not set in advance.
