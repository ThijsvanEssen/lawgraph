#!/bin/sh
# LAWGRAPH_ALERT_COMMAND of the server: the message (plain Dutch, scripts/_alert.sh) as a push through ntfy.
topic="$(cat /srv/lawgraph/ntfy-topic)"
curl -s -d "${1:-$LAWGRAPH_ALERT_MESSAGE}" "https://ntfy.sh/$topic" > /dev/null
