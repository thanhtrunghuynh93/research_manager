#!/usr/bin/env bash
# Run the stack on the fakes: the deterministic gateway, the in-memory repository connector, and
# mailpit. No provider key, no GitHub App, no money spent, no mail leaving the machine.
#
#   scripts/run_mock.sh                 start
#   scripts/run_mock.sh --seed          start and load the demo dataset
#   scripts/run_mock.sh --down          stop
#
# Everything works: reports are submitted, assessments are produced, the review queue fills. What
# the fake cannot do is judge research — its ratings come from stated heuristics — so this is for
# exercising the workflow, not for calibrating the rubric.
#
# It is its own compose project, so nothing it seeds can end up in the real stack's database.
set -euo pipefail
exec "$(dirname "$0")/run.sh" --mode mock "$@"
