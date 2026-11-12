#!/bin/sh
# At night, once after the deploy of the release that reads the conclusions from the Rechtspraak index (#1162): the
# conclusions of the Parket bij de Hoge Raad that no listing named since 20 Sep 2026, about 400 to 600 (measured with
# phr-gap-counts.sql on 11 Nov). phr-backfill-steps.sh, one lock, minutes. Stops at the first failure and says so
# through the alert; run again, it goes on (the retrieve skips what is stored).
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/phr-backfill-steps.sh" || fail phr-backfill-steps $?
