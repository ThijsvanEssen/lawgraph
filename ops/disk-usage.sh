#!/bin/sh
# Read only: what fills the root disk (/), and how fast. Writes nothing; what the deploy user cannot read is skipped.
echo "== $(date -u '+%F %T') UTC"
df -h / /srv/lawgraph
echo "== largest directories on / (same file system, readable by this user)"
du -xh --max-depth=2 / 2>/dev/null | sort -rh | head -25
echo "== journal"
journalctl --disk-usage 2>/dev/null
echo "== docker"
docker system df 2>/dev/null
docker info --format 'data-root {{.DockerRootDir}}, log driver {{.LoggingDriver}}' 2>/dev/null
for c in $(docker ps --format '{{.Names}}'); do
  echo "-- $c log: $(docker inspect --format '{{.LogPath}}' "$c" 2>/dev/null) $(docker inspect --format '{{json .HostConfig.LogConfig}}' "$c" 2>/dev/null)"
done
echo "== /var/log, /tmp, home"
du -xsh /var/log /var/cache /tmp "$HOME" "$HOME/.cache" "$HOME/.local" 2>/dev/null
echo "== files over 200 MB on /"
find / -xdev -type f -size +200M -printf '%s %p\n' 2>/dev/null | sort -rn | head -15 | awk '{printf "%.0f MB %s\n", $1/1048576, $2}'
echo "== written in the last hour on / (top 15 by size)"
find / -xdev -type f -mmin -60 -printf '%s %p\n' 2>/dev/null | sort -rn | head -15 | awk '{printf "%.1f MB %s\n", $1/1048576, $2}'
