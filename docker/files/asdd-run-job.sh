#!/usr/bin/env bash
# asdd-run-job — process one job-note file, write a result file.
#
# Invoked inside a project container running in autonomous mode (spec 008
# FR-009 / US5). Reads the job-note file at $1 and writes a result at
# /asdd_home/results/<basename>.result.md.
#
# Production path: pipe the job-note body to `claude --print` so the LLM
# answers it; capture stdout to the result file.
#
# Test/CI path: when $ASDD_JOB_STUB_OUTPUT is set, that string is written
# to the result file verbatim instead of invoking claude. Lets the spec
# 008 integration tests assert the dispatch primitive end-to-end without
# requiring a live ANTHROPIC_API_KEY.

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "usage: asdd-run-job <job-note-path>" >&2
    exit 64
fi

JOB_PATH="$1"
if [ ! -f "$JOB_PATH" ]; then
    echo "asdd-run-job: job file not found: $JOB_PATH" >&2
    exit 66
fi

JOB_NAME="$(basename "$JOB_PATH")"
JOB_BASE="${JOB_NAME%.md}"
RESULTS_DIR="/asdd_home/results"
RESULT_FILE="${RESULTS_DIR}/${JOB_BASE}.result.md"

mkdir -p "$RESULTS_DIR"

if [ -n "${ASDD_JOB_STUB_OUTPUT:-}" ]; then
    # Test/CI mode — deterministic output, no LLM call.
    printf '%s\n' "$ASDD_JOB_STUB_OUTPUT" > "$RESULT_FILE"
else
    # Production mode — pipe job-note body to claude --print.
    claude --print < "$JOB_PATH" > "$RESULT_FILE"
fi

echo "asdd-run-job: wrote $RESULT_FILE"
