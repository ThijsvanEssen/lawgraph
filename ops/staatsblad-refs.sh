#!/bin/sh
# Once after the deploy of E16, at night: the Staatsblad publication of every stored BWB toestand into its meta
# (staatsblad-refs.py, ~46k payloads read, minutes), then retrieve staatsblad, which reads it there; with
# staatsblad-refs-counts.sql before and after. Until it ran, retrieve staatsblad finds no publication to fetch.
# Stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/staatsblad-refs-steps.sh" || fail staatsblad-refs-steps $?
