#!/bin/sh
# #453 at night, once after its deploy: the results of the Kiesraad for the Eerste Kamer (6 pages), the changes of
# /personele_mutaties (the term lists and every item once, paced: about 200 pages), then normalize
# eerstekamer-mutations, which writes lg_ek_terms and lg_ek_seats whole; ek-seats-counts.sql before and after; one
# lock for the steps (minutes). Stops at the first failure and says so through the alert.
. "$(dirname "$0")/_night.sh"
wait_night
sh "$D/ek-seats-steps.sh" || fail ek-seats-steps $?
