#!/bin/zsh
# What is left of the rebuild of 2026-09-20, on the code of this checkout.
# No `| tee`: a pipe takes the live progress block away; the log goes to LAWGRAPH_LOG_FILE.
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH=src
export LAWGRAPH_LOG_FILE="$HOME/lawgraph-rebuild.log"
lawgraph() { /Users/thijs/Development/lawgraph/.venv/bin/python -m lawgraph "$@"; }

lawgraph normalize tk            # the cases, now with the dossier they belong to
lawgraph normalize tk-dossiers   # links them
lawgraph expand-graph            # rounds since they began, then one full semantic all
lawgraph check
