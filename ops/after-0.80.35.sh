#!/bin/sh
# B131 at night, once after the deploy of 0.80.35: the members by the name they go by and the seats without "-"
# (after-0.80.35-steps.sh, one lock, a few minutes). Goes live together with the explorer of B136 (`/ambten/…`
# without "-"). Stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/after-0.80.35-steps.sh" || fail after-0.80.35-steps $?
