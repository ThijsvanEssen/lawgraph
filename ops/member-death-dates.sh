#!/bin/sh
# Once after the deploy that maps the day a person died (Persoon.Overlijdensdatum, death_date), at night: normalize
# tk-dossiers --persons (every stored Persoon record again into its member, some 4,600, merged into what other steps
# wrote); member-death-dates-counts.sql before and after; under the lock. Stops at a failure and says so through the
# alert. After it, a changed Persoon record brings its death_date with the weekly run.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/member-death-dates-steps.sh" || fail member-death-dates-steps $?
