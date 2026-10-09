# deploy/server/

The config of the production server as it is live, so it changes through a pull request and a review, not by hand:

- `systemd/`: the API (`lawgraph-api.service`) and the scheduled runs: the nightly (`daily.sh`), the weekly
  (`weekly.sh`) and the polls (`poll.sh`), each a service and a timer, in `/etc/systemd/system/`.
- `caddy/concordans.caddy`: the site blocks of `concordans.nl` (files of the build as they are, every other path
  the page from the API's `/render`, the static shell when the API is slow or down) and `www.concordans.nl` (a 301
  to the apex). The server's `/etc/caddy/Caddyfile` serves other sites too, which are not ours to keep here; it
  reads this file with `import /etc/caddy/concordans.caddy`.
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

`config-apply` changes the Caddy block only while the live Caddyfile imports `/etc/caddy/concordans.caddy` (it
does since 9 Oct 2026); it refuses otherwise.
