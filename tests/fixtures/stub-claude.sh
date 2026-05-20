#!/usr/bin/env bash
#
# Stub Claude Code binary for tests. Reads three env vars:
#   STUB_TRANSCRIPT_PATH  — absolute path to a JSONL fixture; its contents are emitted to stdout.
#   STUB_EXIT_CODE        — integer exit code (default 0).
#   STUB_STDERR           — optional stderr message; written line-by-line before exit.
#
# Used by tests/integration/* to simulate a real Claude Code subprocess without burning tokens.
# Per spec 004-agents/research.md §1: the runner reads stdout line-by-line; this script honors
# that by simply `cat`-ing the fixture file (which is JSONL: one event per line).
#

set -uo pipefail

TRANSCRIPT="${STUB_TRANSCRIPT_PATH:-/dev/null}"
EXIT_CODE="${STUB_EXIT_CODE:-0}"

if [[ -n "${STUB_STDERR:-}" ]]; then
  printf '%s\n' "${STUB_STDERR}" >&2
fi

if [[ -r "${TRANSCRIPT}" ]]; then
  cat "${TRANSCRIPT}"
fi

exit "${EXIT_CODE}"
