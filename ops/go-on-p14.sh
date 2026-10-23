#!/bin/sh
# Lets after-0806.sh (P14) go on (SIGCONT) without the slice loops. Held, it stopped reading the output of the step
# it runs ($(...) in its step helper): the pipe filled and the step blocked on its own log. Writes no data itself.
for pid in $(pgrep -f "^sh (.*/)?after-0806.sh\$"); do
  kill -CONT "$pid" && echo "$(date -u +%T) after-0806.sh ($pid) goes on"
done
