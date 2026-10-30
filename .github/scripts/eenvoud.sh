#!/bin/sh
# The simplicity budget: eenvoud.py measures and compares with eenvoud-budget.json (a ratchet).
# Usage: eenvoud.sh [--write | --raised REF]
exec python3 "$(dirname "$0")/eenvoud.py" "$@"
