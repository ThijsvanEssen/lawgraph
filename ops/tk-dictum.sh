#!/bin/sh
# #390, once after the deploy of 0.79.32: the dictum of every motion whose text was read before.
. "$(dirname "$0")/_steps.sh"
counts dictum before tk-dictum-check.sql
step dictum1-semantic-tk-dictum semantic tk-dictum
counts dictum after tk-dictum-check.sql
echo "== all done $(date -u +%T)"
