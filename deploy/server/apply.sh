#!/bin/sh
# The server config of deploy/server/ against what is live on the server (run there, from the copy the ops
# workflow sends over):
#   apply.sh check   read only: the diff of every file against the live one, systemd-analyze verify of the
#                    units, and caddy validate plus caddy adapt of the live Caddyfile with the concordans.nl
#                    block from here, against the live one (the same JSON: nothing changes for the site)
#   apply.sh apply   check, and only when every check passed: the changed files installed, daemon-reload,
#                    the changed timers restarted, a new timer enabled, and caddy reloaded when its block changed
# Stops at the first error. Files on the server that are not here (a drop-in by hand) are named, not touched.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
UNITS=/etc/systemd/system
CADDYFILE=/etc/caddy/Caddyfile
SNIPPET=/etc/caddy/concordans.caddy
ALERT=/srv/lawgraph/bin/alert.sh
TMP=$(mktemp -d)
trap 'rm -r "$TMP"' EXIT
mode=${1:-check}
changed_units=""
changed_caddy=0
changed_alert=0
failed=0

note() { echo "== $*"; }
bad() { echo "!! $*"; failed=1; }

# the live Caddyfile with its concordans.nl block replaced by an import of the given file
caddyfile_with() {
  awk -v snippet="$1" '
    /^concordans\.nl \{/ { print "import " snippet; skip = 1; next }
    skip && /^\}/ { skip = 0; next }
    !skip { print }
  ' "$CADDYFILE"
}

check_units() {
  for f in "$HERE"/systemd/*; do
    name=$(basename "$f")
    if [ ! -e "$UNITS/$name" ]; then
      note "new: $name"; changed_units="$changed_units $name"
    elif ! diff -u "$UNITS/$name" "$f"; then
      changed_units="$changed_units $name"
    fi
  done
  for f in "$UNITS"/lawgraph-*; do
    [ -e "$HERE/systemd/$(basename "$f")" ] || note "on the server only (left alone): $(basename "$f")"
  done
  # verify the units as they would be: templates under an instance name
  mkdir -p "$TMP/units"
  cp "$HERE"/systemd/* "$TMP/units/"
  verify=""
  for f in "$TMP"/units/*; do
    case "$f" in
      *@.service) ;;
      *) verify="$verify $f" ;;
    esac
  done
  for inst in lawgraph-poll@echr lawgraph-poll-tk@2h; do
    tmpl=$(echo "$inst" | sed 's/@.*/@.service/')
    cp "$TMP/units/$tmpl" "$TMP/units/$inst.service"
    verify="$verify $TMP/units/$inst.service"
  done
  # shellcheck disable=SC2086
  if out=$(SYSTEMD_UNIT_PATH="$TMP/units:" systemd-analyze verify $verify 2>&1); then
    note "systemd-analyze verify: ok"
  else
    echo "$out"; bad "systemd-analyze verify failed"
  fi
}

check_caddy() {
  live_block="$TMP/live-block.caddy"
  if [ -e "$SNIPPET" ]; then
    cp "$SNIPPET" "$live_block"
  else
    awk '/^concordans\.nl \{/ { on = 1 } on { print } on && /^\}/ { exit }' "$CADDYFILE" > "$live_block"
  fi
  diff -u "$live_block" "$HERE/caddy/concordans.caddy" || changed_caddy=1
  caddyfile_with "$HERE/caddy/concordans.caddy" > "$TMP/Caddyfile.new"
  if out=$(caddy validate --adapter caddyfile --config "$TMP/Caddyfile.new" 2>&1); then
    note "caddy validate: ok"
  else
    echo "$out" | tail -5; bad "caddy validate failed"
  fi
  # the JSON names the file each block came from; the name of the file is not the config
  caddy adapt --adapter caddyfile --config "$CADDYFILE" 2>/dev/null \
    | sed -e "s#\"$CADDYFILE\"#\"<file>\"#g" -e "s#\"$SNIPPET\"#\"<file>\"#g" > "$TMP/live.json"
  caddy adapt --adapter caddyfile --config "$TMP/Caddyfile.new" 2>/dev/null \
    | sed -e "s#\"$CADDYFILE\"#\"<file>\"#g" -e "s#\"$HERE/caddy/concordans.caddy\"#\"<file>\"#g" > "$TMP/new.json"
  if cmp -s "$TMP/live.json" "$TMP/new.json"; then
    note "caddy adapt: the same JSON as the live Caddyfile"
  else
    note "caddy adapt: the JSON differs from the live Caddyfile"
    [ "$changed_caddy" -eq 1 ] || bad "the JSON differs while the block is the same"
  fi
  grep -q "^import $SNIPPET\$" "$CADDYFILE" || note "the live Caddyfile has the block inline, not 'import $SNIPPET'"
}

check_alert() {
  diff -u "$ALERT" "$HERE/bin/alert.sh" || changed_alert=1
}

check_units
check_caddy
check_alert
[ -n "$changed_units" ] || [ "$changed_caddy" -eq 1 ] || [ "$changed_alert" -eq 1 ] || note "no changes: the server is as here"
[ "$failed" -eq 0 ] || { echo "!! a check failed; nothing applied"; exit 1; }
[ "$mode" = apply ] || { note "check done${changed_units:+, units to change:$changed_units}"; exit 0; }

# apply: only what changed, and the Caddyfile only when it imports the block (the first split is by hand)
if [ "$changed_caddy" -eq 1 ] && ! grep -q "^import $SNIPPET\$" "$CADDYFILE"; then
  echo "!! the live Caddyfile does not import $SNIPPET yet; split it by hand first (docs: deploy/server/README.md)"
  exit 1
fi
set -e
for name in $changed_units; do
  sudo -n install -m 644 "$HERE/systemd/$name" "$UNITS/$name"
  note "installed $name"
done
if [ -n "$changed_units" ]; then
  sudo -n systemctl daemon-reload
  for name in $changed_units; do
    case "$name" in
      *.timer)
        if systemctl is-enabled --quiet "$name" 2>/dev/null; then
          sudo -n systemctl restart "$name"; note "restarted $name"
        else
          sudo -n systemctl enable --now "$name"; note "enabled $name"
        fi
        ;;
    esac
  done
fi
if [ "$changed_alert" -eq 1 ]; then
  install -m 755 "$HERE/bin/alert.sh" "$ALERT"
  note "installed alert.sh"
fi
if [ "$changed_caddy" -eq 1 ]; then
  sudo -n cp "$SNIPPET" "$SNIPPET.bak-$(date -u +%Y%m%d%H%M%S)"
  sudo -n install -m 644 "$HERE/caddy/concordans.caddy" "$SNIPPET"
  if ! sudo -n systemctl reload caddy; then
    echo "!! caddy reload failed; the old block is in $SNIPPET.bak-*"
    exit 1
  fi
  note "caddy reloaded"
fi
note "applied"
