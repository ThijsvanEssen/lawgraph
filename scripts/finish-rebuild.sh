#!/bin/zsh
# Repair the BWB listing of 2026-09-20 (3,938 regulations were never retrieved) and finish
# the rebuild, on the code of this checkout.
# No `| tee`: a pipe takes the live progress block away; the log goes to LAWGRAPH_LOG_FILE.
cd "$(dirname "$0")/.." || exit 1
export PYTHONPATH=src
export LAWGRAPH_LOG_FILE="$HOME/lawgraph-rebuild.log"
lawgraph() { /Users/thijs/Development/lawgraph/.venv/bin/python -m lawgraph "$@"; }

lawgraph retrieve bwb --mode full   # a listing that checks itself; stored toestanden are skipped
lawgraph normalize bwb              # the new regulations, and the annexes of all of them
lawgraph expand-graph               # rounds of the three phases, then one full semantic all
lawgraph check
