#!/bin/zsh
# The rest of the rebuild of 2026-09-20, on the code of this checkout (PR #3).
# No `| tee`: a pipe takes the live progress block away; the log goes to LAWGRAPH_LOG_FILE.
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH=src
export LAWGRAPH_LOG_FILE="$HOME/lawgraph-rebuild.log"
lawgraph() { /Users/thijs/Development/lawgraph/.venv/bin/python -m lawgraph "$@"; }

lawgraph normalize all     # also puts `basis` and `celex_refs` on every BWB regulation
lawgraph semantic all
lawgraph expand-graph      # rounds since they began, then one full semantic all
lawgraph check
