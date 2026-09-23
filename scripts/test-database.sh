#!/bin/sh
# A small database with real data in which every part of the model occurs, for trying the API
# and the front end: scripts/test-database.sh [database] (default lawgraph_small). It is built
# next to the database of .env, in about twenty minutes and a few hundred MB; drop it (and its
# payloads under LAWGRAPH_PAYLOAD_STORE) to build it again. Run it in a terminal: every step
# shows its progress there.
#
# It is chosen around a few chains, so that every relation has edges:
#   Grondwet with its history, and dossiers 35786 and 35785 with their memoranda: amendments,
#     versions, the dossier a law was legislated in, a memorandum that explains what it changed
#   Wet openbare manifestaties and bill 37014 (pending): changes a bill proposes, the sections
#     of its memorandum, votes, commitments
#   Uitvoeringswet AVG (dossier 34851): the EU act it implements
#   Besluit proceskosten bestuursrecht: an instrument based on an article of the Awb
#   Awb, Wetboek van Strafrecht, Burgerlijk Wetboek Boek 7: what recent case law cites
# and a little of every other source: two weeks of the Tweede Kamer, of the three highest
# courts and of the Staatscourant, ECHR judgments against the Netherlands, papers of the
# Eerste Kamer and treaties.
set -u
cd "$(dirname "$0")/.." || exit 1
export ARANGO_DB_NAME="${1:-lawgraph_small}"
L=.venv/bin/lawgraph

GRONDWET=BWBR0001840 AWB=BWBR0005537 SR=BWBR0001854 BW7=BWBR0005290
WOM=BWBR0004318 UAVG=BWBR0040940 PROCESKOSTEN=BWBR0006160
DOSSIERS="35786 35785 37014 34851 32450"

failed=0
step() { "$L" "$@" || { failed=1; echo "test-database: lawgraph $* failed" >&2; }; }

set --
for id in $GRONDWET $AWB $SR $BW7 $WOM $UAVG $PROCESKOSTEN; do set -- "$@" --bwb-id "$id"; done
step retrieve bwb "$@"
step retrieve bwb-history $GRONDWET $WOM $UAVG $PROCESKOSTEN
step retrieve tk --since 14d
step retrieve tk-dossiers --since 14d
for number in $DOSSIERS; do step retrieve tk-dossiers --dossier-number "$number"; done
step retrieve rechtspraak --since 14d
step retrieve staatscourant --since 14d
step retrieve echr --respondent NLD --max-records 25
step retrieve eerstekamer --since 60d --max-records 200
step retrieve verdragenbank --max-records 25
step normalize all
step semantic all
# What the loaded records name: memoranda, publications, EU acts, cited judgments (the
# judgments are named by the edges that semantic wrote).
step retrieve tk-content
step retrieve staatsblad --mode from-graph
step retrieve eurlex --mode gaps
step retrieve rechtspraak --mode gaps
step normalize all
step semantic all
step check --skip-edges
exit $failed
