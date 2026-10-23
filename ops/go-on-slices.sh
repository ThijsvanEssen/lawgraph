#!/bin/sh
# Lets the slice loops held by hold-slices.sh go on (SIGCONT) where they stopped. Writes no data itself.
for name in renormalize-judgments.sh relink-judgments.sh relink-citations.sh; do
  for pid in $(pgrep -f "^sh (.*/)?$name\$"); do
    kill -CONT "$pid" && echo "$(date -u +%T) $name ($pid) goes on"
  done
done
