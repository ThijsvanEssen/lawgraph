#!/bin/sh
# B110 bron 1 at night, once after its deploy: the creators of the stored ministerial regulations, their papers again
# and the LED_BY edges (creators-steps.sh, one lock, at most some 25 minutes). Not needed for correctness: the nightly
# asks 5000 a source a night and gets there on its own. Stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/creators-steps.sh" || fail creators-steps $?
