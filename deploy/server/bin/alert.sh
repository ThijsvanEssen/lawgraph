#!/bin/sh
# LAWGRAPH_ALERT_COMMAND of the server: the message (docs/operations.md, "Alerts") as a push through ntfy.
topic="$(cat /srv/lawgraph/ntfy-topic)"
curl -s -d "${1:-$LAWGRAPH_ALERT_MESSAGE}" "https://ntfy.sh/$topic" > /dev/null
