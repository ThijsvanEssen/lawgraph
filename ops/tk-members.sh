#!/bin/sh
# #410 at night: the members block of the TK in full (Persoon, Fractie, FractieZetelPersoon and
# FractieZetelVacature) plus an hour of dossiers, then normalize tk-dossiers since then, which writes the
# vacancies of the factions; faction-vacancies-counts.sql before and after; one lock for the two steps (minutes).
# Stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/tk-members-steps.sh" || fail tk-members-steps $?
