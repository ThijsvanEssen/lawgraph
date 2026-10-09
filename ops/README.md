# ops/

Scripts and read-only queries for the server, run through `.github/workflows/ops.yml` with the deploy key: no
personal SSH key, and every run is in the Actions log. The workflow runs only on `develop` or `main` (on any other
ref its first step fails), so only what is merged here can be sent.

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

A writing script can source `_steps.sh` for that preamble: it waits until no scheduled run is busy, takes the lock,
and gives `counts <block> <before|after> <file.sql>` (a read-only query from here, printed and kept) and
`step <label> <lawgraph args...>` (one command, its log kept; the script stops at the first failure). Outputs go to
`/srv/lawgraph/ops/out/<script>/`. A run sends the whole of `ops/`, so a script can run its siblings
(`chain-rest.sh` runs `tk-dictum.sh`, `post-0.79.29.sh` and `post-0.79.30.sh`, each with its own lock). A chain that should run at night waits for its window itself (`revises-backfill.sh`: `NOT_BEFORE`, `NOT_AFTER`).

A night backfill sources `_night.sh`: `wait_night` waits for 03:00–07:00 Europe/Amsterdam (`NOT_BEFORE`,
`NOT_AFTER`), after the nightly, and `fail` sends the alert and stops. Its steps are a script of their own that
sources `_steps.sh`, so each takes the lock and lets it go: `staatsblad-notes.sh` (#413), `tk-members.sh` (#410)
and `bwb-definitions.sh` (#414, slices of 5,000 regulations, each under the lock on its own, going on from
`out/bwb-definitions.after`).

A `.sql` here only reads: the session is `default_transaction_read_only`, so PostgreSQL refuses a write.
