#!/bin/sh
# Is HEAD only a version bump of BASE? Usage: version-bump.sh BASE
#
# Exits 0 when HEAD differs from BASE in exactly two lines: `__version__` in
# src/lawgraph/__init__.py and the `version` of docs/openapi.json, both from the same old
# version to the same higher one. Exits 1 on any other difference.
set -u
base=$1
lines=$(git diff --no-color --unified=0 "$base" HEAD -- . | grep -E '^[-+]' | grep -vE '^(---|\+\+\+) ')
old=$(printf '%s\n' "$lines" | sed -n 's/^-__version__ = "\([0-9.]*\)"$/\1/p')
new=$(printf '%s\n' "$lines" | sed -n 's/^+__version__ = "\([0-9.]*\)"$/\1/p')
expected=$(printf -- '-    "version": "%s",\n+    "version": "%s",\n-__version__ = "%s"\n+__version__ = "%s"' \
  "$old" "$new" "$old" "$new")
files=$(git diff --name-only "$base" HEAD | tr '\n' ' ')
if [ -n "$old" ] && [ -n "$new" ] && [ "$old" != "$new" ] \
  && [ "$files" = "docs/openapi.json src/lawgraph/__init__.py " ] \
  && [ "$lines" = "$expected" ] \
  && [ "$(printf '%s\n%s\n' "$old" "$new" | sort -V | tail -1)" = "$new" ]; then
  echo "$base to HEAD: version $old to $new, nothing else"
  exit 0
fi
echo "$base to HEAD: more than a version bump"
exit 1
