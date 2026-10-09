#!/bin/sh
# Every week: link everything again, then fetch what the graph refers to and lacks.
# The full `semantic all` comes first: a text loaded long ago can name a law loaded this
# week, and what it names and is missing is what `expand-graph` then fetches.
. "$(dirname "$0")/_run.sh"

# The members, factions, their seats and vacant seats, which the daily run skips
# (`--skip-members`): a new seat or vacancy shows within a week. A short step.
step retrieve tk-dossiers --since 1d --skip-decisions --skip-documents
step normalize tk-dossiers --since 1d
step semantic all
step expand-graph
step check
finish
