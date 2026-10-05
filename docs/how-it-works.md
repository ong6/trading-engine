# Operations runbook

Use this guide when a scheduled run, API, UI, or evidence projection misbehaves. The system
design and component map live in [`architecture-reference.md`](architecture-reference.md);
[`system-blueprint.md`](system-blueprint.md) explains the target architecture. The repository is
paper-only: there is no broker connection, credential, or real-money authority on this host.

## First response

Inspect before changing anything:

```bash
date -u
git status --short
tail -50 logs/cron.log
tail -50 logs/verify-cron.log
tail -50 logs/sweeps-cron.log
tail -50 logs/liquid-cron.log
tail -50 logs/walkforward-cron.log
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/meta
curl -fsS http://127.0.0.1:8000/research/readiness
curl -fsS http://127.0.0.1:8000/agent/evaluation/status
systemctl --user list-timers 'trading-engine-*'
```

Read `GET /meta` before interpreting a log in isolation. It reconciles schedule, log, lock,
database, report, queue, source-control, and evidence state. A missing or malformed
`data/_meta.json` is reported separately and does not hide live projections. `GET /health`
returns 503 with `busy` for lock contention and `unreadable` for a missing or invalid store.

Do not repair a paper record by editing or deleting evidence. Reproduce a producer defect, fix
the producer, and let the normal recovery path reconstruct only derivable outputs. Rule 1 is:
never invent a price or bar. Point-in-time rows are append-only, and orders fill next-open, never
same-bar.

## Scheduled work

There are five deterministic production cron schedules, and one evidence-only Saturday
postflight. The production schedules are:

| Driver | UTC schedule | Log | Expected completion grace |
|---|---|---|---|
| `run_daily.sh` | weekdays at 22:30 | `logs/cron.log` | 6 hours |
| `run_weekly_verify.sh` | Saturday at 02:00 | `logs/verify-cron.log` | 4 hours |
| `run_weekend_sweeps.sh` | Saturday at 06:00 | `logs/sweeps-cron.log` | 24 hours |
| `run_weekly_liquid.sh` | Sunday at 02:00 | `logs/liquid-cron.log` | 4 hours |
| `run_weekly_walkforward.sh` | Sunday at 06:00 | `logs/walkforward-cron.log` | 18 hours |

The exact five required user-crontab entries above are managed by
`tools.install_automation`. The auxiliary crontab entry remains outside the five
production-driver count: it runs `tools.verify_friday_postflight --publish` at 05:15 UTC each
Saturday. `scheduler` in `GET /meta` verifies the 5+1 shape, daemon state, UTC host timezone,
executable sources, and safe writable logs.

Each driver has an advisory lock. A start without a terminal marker is `running` only while the
lock is held; otherwise it is `interrupted`. A held lock past the driver's grace is
`stale-running`. Old or absent starts become `overdue` after the next slot and grace. These are
read-only diagnoses: they do not restart a process or alter a queue.

Every driver stage writes start, end, duration, and exit status to its normal log and appends the
same record to `logs/stage-timings.jsonl`. Timing publication is fail-soft. Summarize the latest
20 runs per driver, or one named driver, with:

```bash
.venv/bin/python -m tools.stage_timings --runs 20
.venv/bin/python -m tools.stage_timings --runs 20 --driver run_daily
```

## Nightly and queue checks

The nightly is the only weekday orchestrator. Its fatal path collects EOD data, resolves the
`breadth-qualified` operational date, screens, advances the paper league, writes reports, and
queues supporting work. The operational date requires at least 90% coverage and at least 1,000
names with real bars. A partial later batch cannot advance it. The `GET /screen/latest`
projection is independently capped; `GET /screen/{run_date}` remains an explicit archival lookup.

Inspect recent queue state without taking a write lease:

```bash
.venv/bin/python - <<'PY'
from engine.lib import db

with db.connect(read_only=True) as con:
    print(con.execute(
        "SELECT id, kind, state, created_at, updated_at "
        "FROM jobs ORDER BY id DESC LIMIT 20"
    ).fetchall())
PY
```

One DuckDB writer is allowed at a time. Heavy work belongs in the queue. Up to eight isolated
read-only workers may run jobs explicitly marked `parallel_safe`; a budget expiry stops starting
new work and never kills an in-flight job. Do not launch a second nightly or queue drain around a
held producer lock.

The queue uses a priority-ordered rolling pool: when a worker finishes, the next eligible job starts
without waiting for the rest of the old batch, but no lower-priority job launches before an earlier
one. A walk-forward drain builds one immutable read-only input store for the run; each worker keeps
only its private writable overlay. Workers convert termination into normal cleanup, and the next
drain removes only orphan scratch directories whose active lock is not held.

## Revision 9 throughput and read-path checks

The October 2 infrastructure revision changed scheduling and contention, not scoring or evidence
semantics. These are the expected paths when investigating runtime:

- `verify-prices` uses four workers, but a single global limiter still spaces all request starts by
  0.4 seconds. It releases its database connection after materializing the input and runs its
  network phase alongside the farm drain.
- Nightly earnings pulls only names with an unknown next date, an event inside 21 NYSE sessions, or
  a successful pull more than seven calendar days old. Monday UTC is the full eligible-universe
  pass.
- A caught-up TradingView archive symbol waits for two to four completed sessions and requests them
  in one range. The per-request pause, request rate, 550-day historical chunk, and per-run chunk cap
  are unchanged.
- Intraday capture retains the exact response receipt, reuses an existing revision when the
  normalized payload is unchanged, and inserts genuinely new or changed facts in one batch.
- `GET /agent/evaluation/status` caches the expensive profitability validation and projection by
  registration plus audited-table generations. Intraday readiness caches coverage by row count and
  latest timestamp. A database change invalidates either result.
- Hourly and four-hour observers open one connection for the full run, pass it through quote and
  cross-check retention, and wait at most 60 seconds for the writer before reporting unavailable.

Profitability scoring finishes, re-renders the league, and only then runs evidence reporting. An
evidence-validation failure returns exit 75. The scoring service's
`RestartPreventExitStatus=75` records that failure without restarting the unit; any other nonzero
report failure remains a normal service failure.

## Read-only database snapshots

Completed producers publish an immutable consistent copy under `store/snapshots/` as
`market-<UTC stamp>.duckdb`. `market-latest.duckdb` is an atomically replaced relative symlink;
the matching JSON manifest records source data commit, publication time, file SHA-256, size, and
table row counts. Without a sibling `.wal`, publication records the source invariants through a
read-only attachment, file-copies and fsyncs while holding the producer locks, releases those
locks, then verifies the copy against the recorded invariants before publication. A present WAL
uses DuckDB's consistent `COPY FROM DATABASE` path instead. The newest two generations are
retained, and a snapshot error never changes the producer's result.

Profitability evidence loop (P15) event runs pass `--min-age-minutes 120`, so a valid latest snapshot newer than two hours is
logged as skipped with exit 0. Nightly, P15 scoring, and TradingView history remain unthrottled;
pre-open does not publish a snapshot.

When the primary database is writer-locked, read-only API requests may use the latest valid
snapshot. Snapshot responses carry `X-Data-Source: snapshot` and `X-Snapshot-As-Of`; corrupt or
unreadable primary databases do not trigger fallback. Evidence validation, including
`GET /agent/evaluation/status`, may use a snapshot only when its `as_of` is later than the live
database's last write. If no qualifying snapshot exists, the endpoint keeps its normal 503
behaviour. Research processes may open `store/snapshots/market-latest.duckdb` read-only.

For a one-off data inspection, resolve `market-latest.duckdb` once and open that immutable
path with `read_only=True`; never take a second writer or copy the changing live database.
A snapshot proves its own publication time, so compare its manifest with current API freshness
before interpreting counts. A successful driver and a current evidence cohort are separate:
`walkforward_evidence.status=stale-source` means the result's executable source hash differs from
the current tree. The final sync can pull a newer source after a successful weekly calculation.
Inspect result `git_sha` and `source_sha256`, then the source diff; retain the original evidence
and let the next admitted revalidation create a current cohort. Do not relabel old results.

The XS forward projection accepts the monitor's two output forms: waiting reports carry an
explicit `signal_boundary_frozen` flag; accumulating and verdict reports carry the frozen signal
boundary itself. The API still reconciles the entire report against the database. An early
`REVIEW-KILL` is valid before statistical maturity and remains visible as a paper review request.

If the nightly failed:

1. Identify the newest exact start and terminal marker in `logs/cron.log`.
2. Check `.nightly.lock`, `GET /meta`, and recent `jobs`; distinguish a current writer from a
   stale log.
3. Reproduce the failed command against a copy when the operation can mutate the store.
4. Fix only the demonstrated defect. Do not rewrite a frozen strategy, registration, or evidence
   prefix.
5. Run touched tests and the full suite, publish the metrics snapshot, and let the normal driver
   recover on its next admitted run.

## Evidence and portfolio checks

Current operational evidence is exposed by `GET /meta`, `GET /research/readiness`, and
`GET /agent/evaluation/status`. Generated Markdown is a report, not authority by itself:

- `data/reports/league.md` is the last completed nightly standings snapshot.
- `data/reports/forward/sector_momentum.md`,
  `data/reports/forward/xs_momentum_12_1.md`, and
  `data/reports/experiments/e1-spy-monday-forward.md` are the three frozen forward records.
- `data/reports/agent-eval/p15.md` is the P15 evaluation report; it does not activate or promote
  a policy.
- the weekly challenger-lab (P16) operator digest summarizes status but does not grant execution
  authority.

Discretionary ticket admission applies 11 ordered controls:
`data_quarantine`, `stop_present`, `entry_anchored`, `notional_cap`, `sizing_1pct`,
`playbook_named`, `rr_at_least_2`, `max_open_risk_4r`, `earnings_window`, `regime_gate`, and
`circuit_breaker`. Never bypass a rejected gate through a direct database edit.

## Challenger lab (P16) state before activation

P16 is built but inert. Its current parts are:

- evaluation v2: factor-neutral IC, always-valid sequential evaluation, deflated-Sharpe trial
  accounting, isolated P16 status, and the accepted census spanning agent paper decisions through
  the challenger lab (P5–P16);
- the challenger lab and timer, with no execution authority;
- the filing reader, which remains gated while any inventoried SEC caller bypasses the host-wide
  dispatcher; the frozen P15 scheduled caller currently keeps that gate closed;
- time-locked text and post-cutoff replay labs, whose real-data runs still require their named
  inputs and gates;
- deterministic portfolio construction, recovery, and diagnostics with books inactive;
- fill capture/calibration measurement, while `baseline_v1` remains the active simulator basis;
- the weekly operator digest and the Stage 2 personal-host design.

No P16 component is activated by installing automation, running a report, or loading the census.
Registration, rehearsals, and activation belong to the later registration and activation sequence
(W9b).

## Agent timers and logs

List installed timers and inspect service output with:

```bash
systemctl --user list-timers 'trading-engine-*'
journalctl --user -u trading-engine-daily-opportunity.service -n 50 --no-pager
journalctl --user -u trading-engine-agent-shadow.service -n 50 --no-pager
journalctl --user -u trading-engine-p15-scoring.service \
  -u trading-engine-p15-preopen.service \
  -u trading-engine-p15-events.service -n 50 --no-pager
```

The daily opportunity agent (P8) has local-simulator authority through its locked tool. The
multi-cadence agent tools (P9) intraday observers,
the agent-only shadow, P15 event decisions, and every P16 producer are shadow or data-only unless
their registration explicitly says otherwise. Disable a future timer run with
`systemctl --user disable --now trading-engine-<name>.timer`; disabling never deletes or retries a
recorded decision.

## API and UI

The API and UI bind to loopback. From another machine, forward both ports over SSH:

```bash
ssh -L 3000:127.0.0.1:3000 -L 8000:127.0.0.1:8000 <user>@<host>
```

Open `http://localhost:3000`. Port 3000 is enough for the UI; forward 8000 for direct API calls.
Audit installed automation without changing it:

```bash
.venv/bin/python -m tools.install_automation
systemctl --user status trading-engine-api.service trading-engine-ui.service --no-pager
```

Exit 0 means installed units and the managed cron block match their versioned sources. A
`changes-required` result is a dry-run plan, not permission to mutate. Apply only during an
admitted deployment step with `.venv/bin/python -m tools.install_automation --apply`.

If a page returns 503, check `/health`, `/meta`, and the current DuckDB writer before restarting a
service. Restarting cannot repair an unreadable store and can obscure the producer that owns a
legitimate lock.

## Recovery bundle

Create a bundle only at an explicit path outside the checkout:

```bash
.venv/bin/python -m tools.backup_database create /absolute/backup/path
.venv/bin/python -m tools.backup_database verify /absolute/backup/path
```

Keep the failed store separately. Restore only through the standard verified recovery command;
never copy selected DuckDB tables, regenerate point-in-time observations, or overwrite the public
`data/` outputs by hand.

While holding the normal producer locks, `backup_database create` uses the latest valid snapshot
when that snapshot is newer than the live database's last write. Otherwise it takes its own
consistent copy of the live database. Verification and restore semantics are unchanged.

## P15 activation record and recovery boundary

P15 activated on 2026-09-29. Registration revision 10 is live as of 2026-10-03 and binds
infrastructure changes without changing scoring, books, gates, labels, registered values, or
written evidence. The six source units and three timers are installed and enabled. The original
activation steps remain in the plan record; they are not a procedure to activate a second cohort.

For current operations, treat any change to a registered value as a new version and cohort. Before
an admitted schema or recovery operation, confirm the worktree and producer locks, create and
verify an external recovery bundle, and preserve the existing evidence. A normal deployment may
verify the installed units against source, but it must not replay missed pre-open or event windows.

Rollback disables the three timers first, reverts the activation commit, verifies the recovery
bundle, preserves the current store separately, restores through the standard recovery procedure,
and reapplies the installer. Never delete or rewrite P15 evidence to make a check pass.

## Session close

Run the tests touched by the change, then the full suite and:

```bash
.venv/bin/python -m tools.metrics_snapshot --check-budget
git status --short
```

Commit only source and documentation owned by the session. Pipeline `data/` outputs are never
stashed, reverted, or included in a build commit. Leave no source or documentation change
uncommitted.

<!-- sources: BUILDLOG.md, engine/bitemporal_facts.py, engine/earnings.py, engine/run_daily.sh, engine/lib/driver.sh, engine/queue_runner.py, engine/tradingview_history_archive.py, engine/verify_prices.py, farm/walkforward/runner.py, server/agent_evaluation_reporting.py, server/hourly_opportunity_observer.py, server/intraday_readiness.py, server/main.py, server/run_p15_scoring.sh, server/trading-engine-p15-events.timer, server/trading-engine-p15-preopen.timer, server/trading-engine-p15-scoring.service, server/trading-engine-p15-scoring.timer, server/p15-registration.json, server/p16-registration.json, tools/backup_database.py, tools/publish_snapshot.py, tools/stage_timings.py -->
