# Storage revision (r16-gen + r16-raw, now numbered revision 20 after main took registration revisions 18 and 19) — deploy checklist

Branch `p24/storage-r18` (storage revision on top of main at 1fae615d). Status: **review findings fixed, awaiting
re-review**; not deployed. Rehearsed on store copies only (see "Rehearsal result"). Nothing here was run against the
live store.

**Deploy hold:** Hold until trial 287's 2026-11-03 epoch has run, or until the private consumer is switched to
generations; see pre-flight 6.

## What the revision changes, and the review findings it answers

- **Migration (B1, B2, B4).** Migration 0000 accepts the deployed catalog `865f64aa…` exactly (alongside pre-v2, v2
  and r15), rebuilds the six tables whose DDL drifted through runtime `ADD COLUMN` (rows copied by column name and
  proven equal; a lost column or type change refuses), creates every first-use table, and carries the baseline as
  data, so its identity is that file alone. Post-migration catalog `7286ea9b…`. `actions_fetch_log.attempted_at`
  stays nullable (16,435 deployed rows predate the stamp). Five deployed columns become NOT NULL; a NULL in any of
  them makes the migration refuse cleanly and roll back, so pre-flight 8 checks them first. A rebuild refuses a
  stored column whose type or collation differs from the baseline, and refuses to run outside the migration's
  transaction (it drops the original before the copy is proven). CI proves the fresh initializers reproduce the newest
  migration's catalog; `tests/test_baseline_table_coverage.py` fails on any `CREATE TABLE`, `ADD COLUMN` or
  `CREATE INDEX` the baseline lacks.
- **Finding 1 (fixed): producers read the primary.** Only the API's request path pins generations; the nightly's
  market date, queue children, forward reviews and P15 scoring read the primary as on main.
- **Findings 2-3 (fixed): reads never refuse for cadence.** Board and evidence reads serve the newest generation;
  only "no generation" refuses. Responses carry `x-generation-stale` and `x-pending-publication`; `/meta` and
  `/agent/evaluation/status` return the served generation's `as_of`, age, budget, `stale` and `pending_publication`;
  `/health` reports `degraded` (HTTP 200) when the board is stale. A generation is stale when it is past its budget
  (board 24 h, evidence 45 min) and possibly behind the primary.
- **Finding 3 (fixed): publication cadence and API writes.** Evidence writers: accounts-settle (07:45, 11:55 UTC),
  agent-data-capture (01:25), agent-shadow (01:30), daily opportunity (02:00), hourly and four-hour opportunity
  (New York market hours), P15 pre-open (09:05 New York), P15 scoring (02:30, publishes), P15 events (publishes at
  most every 2 h), P16 challengers (disabled), and API POSTs. The new `trading-engine-publish-on-change` timer
  (:12 and :42 UTC, minutes no other unit starts at) republishes only when the primary changed and skips at once when
  a publication, producer lock or writer is active. Bound: with no producer running, evidence lags its last write by
  at most 30 min plus one publication. Publication now holds the producer locks and one read-only handle only while
  it copies the primary (49-131 s for the 12.7 GB copy in the rehearsal, against 10 minutes before), then builds the
  generation from the copy; API writes wait up to 180 s for that handle instead of failing (cost: a write arriving
  during a capture is delayed until it ends).
- **Finding 4 (fixed):** publication records the primary's storage identity before releasing its read-only handle.
- **Finding 6 (fixed): raw payloads stay main-readable.** Writers seal the legacy plain `<sha>.json` until
  `tools.convert_raw_payloads --apply` records the store flag `store/raw-payload-encoding.json`; a test runs main's
  reader over what the branch writes.
- **Finding 7 (fixed):** backup and generation manifests record the DuckDB version; verify refuses a version change
  with "DuckDB version differs", not the tamper message. The fingerprint's memory-limit restore parses DuckDB's text.
- **Finding 8 (fixed):** backup create checks the source WAL's identity, refusing a WAL-only commit by a writer outside
  the locks.
- **Finding 5 (fixed): this checklist.** Deploy and rollback are scripts (`ops/storage-r20/`) run from fresh shells
  under `set -euo pipefail`, every result checked; state persists in `$P20_STATE/state.env`; backup, migration and
  publication take the producer locks themselves (never inside a held lock); `predeploy.sha` is recorded before the
  checkout moves; units are staged without starting timers and timers start only at release, never the paused
  TradingView timer; the release runs the live schedule-contract check (the ops digest's held-active check).
- **Known guard bypasses (accepted residual risk).** DDL assembled at run time from values the coverage scan cannot
  resolve, DuckDB relation-API persistence (refused at run time by the guard instead), and statements against the
  separate pit/research databases; publication and backup re-verify the exact catalog, so a bypass fails closed there.
- **Still open:** the off-host remote restore drill (needs a generation-backed bundle committed to the private backup
  repo); orchestrator sign-off on pausing TradingView history.

## Re-pin (done on the branch: registration revision 20)

`server/p15-registration.json` is revision 20 over the storage revision and the reliability-ops limits
(`engine/lib/store_limits.py` joins the registered closure). E1 v8, sector v12 and XS v23 keep their versions; each
runner's `--migrate-runtime-contract` accepts only the deployed revision-19 digest (E1 `2c8ec5b0…`, sector
`bad25764…`, XS `d00ee812…`), and the deploy script runs the three migrations after the schema migration. A later
change to a registered file needs another revision.

## Pre-flight (all must hold)

1. `main` contains the merged branch at registration revision 20; both timezone suites green; `ruff check .` clean.
2. `.venv/bin/python -m engine.job_contract audit` → `status: ok`; `python -m tools.schedule_contract_check --static` clean.
3. Free space ≥ 70 GiB on the store filesystem (restore reserve) plus 3× store size: the backup, the first generation,
   and publication's transient copy of the primary.
4. Window outside 13:00-21:00, 02:20-02:50, 07:30-07:50 UTC weekdays; no queue drain running. Allow about 45 minutes
   with producers quiesced (backup create plus verify, migration, first publication; see the rehearsal timings).
5. A fresh verified off-host copy exists (trading-data backup current).
6. Private consumers of `store/snapshots/market-latest.duckdb` that check the schema-1 manifest must be switched to
   `pin_latest_generation` before deploy; they fail closed on a generation layout.
7. Inside the window, after quiescence, the deploy script runs `engine.schema_migrations plan` read-only on the live
   primary and stops unless the pre-image is `865f64aa…`.
8. In the same window it counts NULLs, read-only, in the five deployed columns the baseline makes NOT NULL
   (`agent_evaluation_labels.round_trip_cost_bps`, `net_return`, `net_excess_return`;
   `daily_opportunity_execution_quality.post_fill_position_qty`, `post_fill_cash`) and stops before the backup if any
   exists: migration 0000 would refuse such a row and roll back (the reviewer reproduced the refusal). On the
   2026-10-22 copies every one of these is non-NULL.

## Deploy

```bash
set -euo pipefail
export P20_ROOT="$HOME/trading-engine" P20_STATE="$HOME/.local/state/r20-deploy" P20_APPROVED_SHA=<full sha>
git -C "$P20_ROOT" fetch --quiet origin
git -C "$P20_ROOT" show "$P20_APPROVED_SHA:ops/storage-r20/deploy.sh" > "$HOME/r20-deploy.sh"
bash "$HOME/r20-deploy.sh"
```

`ops/storage-r20/deploy.sh` records the pre-deploy commit before the checkout moves, then: captures units, crontab and
processes; quiesces producers and readers (`ops/storage-r20/host.bash`); keeps generated `data/` and `logs/` changes
aside, checks out the approved commit (registration revision 20) and puts them back; asserts the pre-image read-only; creates and verifies the pre-migration backup under a canonical path (`$HOME/r20-backups`);
migrates and asserts `current`; runs the E1, sector and XS `--migrate-runtime-contract` migrations (each accepts
only the deployed revision-19 digest) and one ordinary refresh that must not be INVALID; publishes the first generation; stages units with `install_automation --stage`
(nothing starts); starts the readers and checks the generation headers, the evidence route
(`pending_publication: false`), the invariants and retention; then releases producers with the full
`install_automation --apply` and restarts the host timers that ran before, never the paused TradingView timer, and
runs the live schedule-contract check. Every value the rollback needs is in `$P20_STATE/state.env`.

## Verify after release (stop at the first failure and roll back)

1. `python -m engine.schema_migrations plan` → `status: current`, schema id 1.
2. `curl -sI localhost:8000/health` shows `x-data-source: snapshot`, `x-generation-id`, `x-generation-stale: false`.
3. Within 45 minutes of any write, `/agent/evaluation/status` reports `generation.pending_publication: false` (the
   publish-on-change timer ran) and never 503.
4. `python -m tools.check_invariants --snapshot latest` exits 0 (shadow).
5. First nightly after deploy: books advance, E1, sector and XS records are written, no `SchemaMigrationRequired`;
   P15 scoring and pre-open green; ops digest shows no `held-active` or `held-enabled`.
6. Run `remote_restore_drill` against the private backup repo commit of the first generation-backed bundle.

## Rollback

```bash
P20_STATE="$HOME/.local/state/r20-deploy" bash "$HOME/.local/state/r20-deploy/rollback.sh"
```

The deploy copies `ops/storage-r20/rollback.sh` into `$P20_STATE`, so it runs from a fresh shell whatever is checked
out. It quiesces, refuses unless the recorded pre-migration backup verifies with the recorded manifest hash, keeps the
incident primary and quarantines the generations, removes the publish-on-change units, checks out the pre-deploy
commit detached (so the nightly cannot pull the reverted revision back), restores the primary byte for byte, publishes
a snapshot in the previous code's format, starts the readers and releases producers with the previous code's
installer.

A rollback after release **loses every write to the primary made since the backup** (it stays in
`$P20_STATE/incident/market.duckdb` for manual recovery). Raw payloads written since release stay readable by the
previous code, because they are in the legacy plain encoding until the conversion flag is set. `data/` follows the
checkout: tracked report files return to the pre-deploy commit's versions (the versions written since release are kept
in `$P20_STATE/incident/data-artifacts`), and commits the nightly pushed since release stay in history. The `store/pit/*.duckdb` databases (free sources, options, minute bars, SEC bulk) are separate
stores that are not restored: they keep rows written since release, and their schemas did not change in this revision.

Raw zstd conversion (`tools/convert_raw_payloads.py --apply`) is a separate, later one-off: run only after the
restore drill passes, with the producer lock held and TradingView jobs drained. It records the store flag that switches
writers to zstd, after which a code rollback can no longer read new raw payloads; its rollback is the off-host raw
archive.

## Rehearsal result (2026-10-22/23, real store copies)

Copies of the 18:07 published snapshot (12.7 GB, SHA-256 = manifest, catalog `865f64aa…`), each the
`store/market.duckdb` of a sandbox clone with no remote. Deploy and rollback are the committed scripts, run from fresh
shells (`env -i`); host steps (units, crontab) are stand-ins that only log, and the readers are a real API process for
the sandbox store. Wall clock (peak RSS).

Final run at the re-pinned head 5fd9cd59 (registration revision 20, series-B DuckDB limits), from the deployed
revision-19 code e7cd03a1 with the live checkout's generated `data/` files (deployed contract digests):

| Step | Result |
|---|---|
| pre-flight plan / NOT NULL count, read-only | 1 s / 1 s; pre-image `865f64aa…`, all five columns 0 NULL |
| backup create + verify | 527 s (5.1 GB) + 168 s |
| migration apply | 341 s (5.0 GB); catalog `7286ea9b…`, plan after `current` |
| runtime-contract migrations | E1, sector, XS each 1 s, from the deployed digests to `7c5a169d…`, `a39c219d…`, `718d6417…`; the ordinary refresh after them is ACCUMULATING, not INVALID |
| first generation | 670 s (5.1 GB); producer locks and capture handle held 16 s |
| readers, first evidence read (no projection yet) | 4.6 min once, then the projection is cached on disk |
| evidence read, warm / after an API restart / after a write | 200 in 33 s each (`projection_current: true`; `pending_publication` true after the write); the 33-47 s is `agent_evaluation.status`, which takes 47 s on the single-file store as well |
| republish with one API write per second | 827 s (5.9 GB); capture 17 s; 60 cold parts reused; 539 of 539 writes 200, slowest 18 s |
| one real nightly (`engine/run_daily.sh`, sandbox HOME, no remote, drain budget -1) | 31 min: collect 302 s, actions 491 s, market date 2026-10-22, league 63 s, 33 books' equity advanced 2026-10-21 → 2026-10-22; sector and XS records ACCUMULATING under the re-pinned contracts; E1 report valid (13 Mondays, no Monday on a Thursday); snapshot 843 s; invariants pass |
| evidence after the nightly's new inputs | 200 in 46 s with the previous projection (`projection_current: false`); the background warmer made it current 286 s later; no request waited for the cold projection |

Earlier runs at 4a778427 and aa048662 (before the re-pin and series B): the rollback script from a fresh shell
restored the primary byte for byte (SHA-256 equals the copied snapshot), kept the post-release row in the incident
copy and served the previous code's API (11 min); a +40 h clock served the board stale-flagged (`/health` 200
`degraded`) and never 503; a walkforward child ran from the published generation (59 s); publish-on-change cleared
`pending_publication` and skipped an unchanged primary in 6 s.

The off-host `remote_restore_drill` was not run (needs a generation-backed bundle committed to the private backup repo).
