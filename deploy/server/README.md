# deploy/server/

The config of the production server as it is live, so it changes through a pull request and a review, not by hand:

- `systemd/`: the API (`lawgraph-api.service`) and the scheduled runs: the nightly (`daily.sh`), the weekly
  (`weekly.sh`) and the polls (`poll.sh`), each a service and a timer, in `/etc/systemd/system/`.
- `caddy/concordans.caddy`: the site block of `concordans.nl`. The server's `/etc/caddy/Caddyfile` serves other
  sites too, which are not ours to keep here; it holds this block, inline for now, later as
  `import /etc/caddy/concordans.caddy`.
- `bin/alert.sh`: `LAWGRAPH_ALERT_COMMAND`, a push through ntfy; the topic is in `/srv/lawgraph/ntfy-topic`, not
  here.
- `scheduler.env.example`: the names in `/srv/lawgraph/scheduler.env`.

`apply.sh` compares and applies, on the server, from the copy the ops workflow sends:

```sh
gh workflow run ops --ref main -f action=config-check   # read only: diff, systemd-analyze verify, caddy validate
gh workflow run ops --ref main -f action=config-apply   # the same, then only what changed, installed and reloaded
```

`check` shows the diff of every file against the live one, verifies the units, and validates the live
Caddyfile with this block in it. It also adapts that Caddyfile to JSON and compares it with the live one, so a
block that is the same gives the same config. `apply` runs the checks first and stops at any failure, so nothing
changes then. After the checks it installs the changed units and runs `daemon-reload`. It restarts a changed timer
and enables a new one. It installs `alert.sh`. It installs the Caddy block and reloads Caddy, keeping a backup of
the block before. A file on the server that is not here, such as a drop-in made by hand, is named and left alone.

The Caddy block is applied only once the live Caddyfile imports `/etc/caddy/concordans.caddy`. That split is done
once by hand: replace the inline block with the import, check that `caddy adapt` gives the same JSON, and reload.
Until then `config-apply` refuses a change to the block.
