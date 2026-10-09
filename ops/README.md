# ops/

Scripts and read-only queries for the server, run through `.github/workflows/ops.yml` with the deploy key: no
personal SSH key, and every run is in the Actions log. Only what is merged here can be sent.

```sh
gh workflow run ops -f action=status                       # health, timers, runs, statements, disk, ops jobs
gh workflow run ops -f action=run -f name=<script>          # ops/<script>.sh, in the background on the server
gh workflow run ops -f action=log -f name=<script>          # the tail of /srv/lawgraph/ops/<script>.log
gh workflow run ops -f action=sql -f name=<query>           # ops/<query>.sql in a read-only session (600 s)
gh run view --log "$(gh run list -w ops -L 1 --json databaseId -q '.[0].databaseId')"   # the output
```

A `.sh` here runs on the server as the deploy user, from `/srv/lawgraph/app` with its venv. One that writes takes
the lock of the scheduled runs first, as `scripts/_run.sh` does, so it never runs beside a poll, the nightly or a
deploy, and never lets go of the lock halfway:

```sh
set -a && . /srv/lawgraph/scheduler.env && set +a
LOCK="${TMPDIR:-/tmp}/lawgraph-scheduled.lock"
until mkdir "$LOCK" 2>/dev/null; do sleep 30; done
trap 'rmdir "$LOCK"' EXIT
trap 'exit 130' INT TERM
```

A `.sql` here only reads: the session is `default_transaction_read_only`, so PostgreSQL refuses a write.
