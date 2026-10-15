#!/usr/bin/env bash
# Seeds the local opensearch with the sample docs.
# The golden set in evals/ expects exactly these docs and groups.
set -e

python -m scripts.local_ingest --groups all-staff \
  data/sample_docs/annual-leave-policy.md \
  data/sample_docs/expenses-policy.md

python -m scripts.local_ingest --groups platform-eng \
  data/sample_docs/platform-oncall-runbook.md

echo "done"
