#!/bin/sh
topic="$(cat /srv/lawgraph/ntfy-topic)"
msg="$(printf '%s' "${1:-$LAWGRAPH_ALERT_MESSAGE}" | sed -E 's/ on [^ ]+//; s/ \(log: [^)]*\)//')"
curl -s -d "$msg" "https://ntfy.sh/$topic" > /dev/null
