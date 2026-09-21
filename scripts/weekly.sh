#!/bin/sh
# Every week: link everything again, then fetch what the graph refers to and lacks.
# The full `semantic all` comes first: a text loaded long ago can name a law loaded this
# week, and what it names and is missing is what `expand-graph` then fetches.
. "$(dirname "$0")/_run.sh"

step semantic all
step expand-graph
step check
finish
