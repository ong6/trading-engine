# Storage revision (r16-gen + r16-raw, now numbered revision 20 after main took registration revisions 18 and 19) — deploy checklist

Branch `p24/r16` (on top of `p24/integrate-wave1`), blockers B1-B4 fixed on `p24/storage-r18` (main merged at
454cfc6a). Status: **ready for the single re-pin and orchestrator review**; not yet deployed. Rehearsed on store copies
only (see "Rehearsal result"). Nothing here was run against the live store.

**Deploy hold:** Hold until trial 287's 2026-11-03 epoch has run, or until the private consumer is switched to
generations; see pre-flight 6.

## Blockers

- **B1 (fixed on p24/storage-r18) Deployed catalog is a supported pre-image.** Migration 0000 accepts the deployed
  catalog `865f64aa…` exactly (alongside pre-v2, v2 and r15). Of its eight drifted tables, six are rebuilt into the
  baseline DDL (agent_evaluation_labels, agent_proposals, agent_shadow_attempts, daily_opportunity_execution_quality,
  daily_opportunity_runs, fundamentals_fetch_log): rows are copied by column name and proven equal (EXCEPT ALL both
  ways), and a table is refused if a stored column would be lost or change type. actions_fetch_log and jobs already
  match: the baseline now declares `jobs.timeout_s` and keeps `actions_fetch_log.attempted_at` nullable (16,435 deployed
  rows predate the stamp and are kept unstamped). Baseline catalog after migration: `7286ea9b…`.
- **B2 (fixed on p24/storage-r18) First-use tables are owned by the baseline.** BOOTSTRAP_CALLS now create the 52
  tables code creates on first use or in inactive stores (`sim_settlements`, `experiment_results` with its forward
  columns, `job_resolutions`, P16, broker and authority ledgers). `tests/test_baseline_table_coverage.py` fails if any
  `CREATE TABLE` in engine/, sim/, server/ or tools/ names a table the baseline does not create (separate databases
  listed).
- **B3 (fixed) Backup cost.** Fingerprints run in DuckDB (p24/r16). Backup create (pre-migration, unversioned store)
  now copies the file bytes under the producer locks, replays a pending WAL into the copy, and keeps the
  logical-snapshot equality check; publication's and the generation-backed backup's DuckDB connections are capped at
  4 GB / 4 threads and spill to disk. Publication cannot use a byte copy: the hot file must exclude the cold tables.
  Every rehearsal step now peaks at or under 7.5 GB RSS.
- **B4 (fixed on p24/storage-r18) Migration identity no longer freezes initializer files.** Migration 0000 carries
  the baseline DDL and the per-pre-image rebuild plan as data; its recorded hash covers that file alone. CI
  (`test_fresh_initializers_reproduce_the_newest_migration_catalog`) requires the fresh initializers to reproduce the
  newest migration's exact catalog and names any drifted object ("add a migration"); a regression test edits
  initializer files on a migrated store and proves writers, publication and backup still open.
- **Accepted by the orchestrator:** the canonical backup path (`readlink -f "$HOME"`, below); publication holding the
  producer locks about 10 minutes; the empty inactive-store tables (P16, broker, authority) in the market catalog.
- Integrator-owned, already known: registration/runtime re-pin (below), the off-host remote restore drill wiring
  (`write_remote_restore_plan` + `remote_restore_drill` need a generation-backed bundle committed to the private
  backup repo), orchestrator sign-off on pausing TradingView history (E4 evidence of no reader).

## Re-pin needed (once, at merge)

Pinned files changed by the storage revision: `engine/lib/db.py` (P15 + E1/sector/XS runtime), `engine/lib/snapshots.py`,
`tools/backup_database.py`, `tools/publish_snapshot.py`, `engine/queue_runner.py`, `engine/signals.py`,
`engine/tradingview_history_archive.py` (P15). 104 pin tests fail only for this (list in the integrate report).
`p24/storage-r18` touches `engine/lib/db.py`, `tools/backup_database.py` and `tools/publish_snapshot.py` again.

## Pre-flight (all must hold)

1. `main` contains the merged branch; both timezone suites green after the single re-pin; `ruff check .` clean.
2. `.venv/bin/python -m engine.job_contract audit` → `status: ok`; `python -m tools.schedule_contract_check --static` clean.
3. Free space ≥ 70 GiB on the store filesystem (restore reserve) plus 2× store size for backup + first generation.
4. Window outside 13:00-21:00, 02:20-02:50, 07:30-07:50 UTC weekdays; no queue drain running. Allow about 45 minutes
   with producers quiesced: backup create ~9 min, verify ~3 min, migration ~6 min, first publication ~10-11 min of
   held producer locks (later publications reuse unchanged cold parts), plus the verify steps.
5. A fresh verified off-host copy exists (trading-data backup current).
6. Private consumers of `store/snapshots/market-latest.duckdb` that check the schema-1 manifest must be switched to
   `pin_latest_generation` before deploy; they fail closed on a generation layout.

## Deploy (from the live checkout, after `git pull`; reuse the runbook helpers)

```bash
cd ~/trading-engine
export P22_ROOT="$PWD" P22_STATE="$HOME/.local/state/r20-deploy"; mkdir -m 700 -p "$P22_STATE"
# capture unit/cron/process state exactly as docs/settlement-runbook.md "P22 deployment" step 1, then:
source "$P22_STATE/functions.bash"       # helpers saved by that step
git rev-parse HEAD > "$P22_STATE/predeploy.sha"
p22_clean_source; p22_quiesce; p22_lock
R20_BACKUP="$(readlink -f "$HOME")/r20-backups/pre-migration-$(date -u +%Y%m%dT%H%M%SZ)"  # verify refuses a symlinked parent
.venv/bin/python -m tools.backup_database create "$R20_BACKUP" --source store/market.duckdb
.venv/bin/python -m tools.backup_database verify "$R20_BACKUP" | tee "$P22_STATE/backup-verify.json"
MSHA=$(.venv/bin/python -c 'import json,sys;print(json.load(open(sys.argv[1]))["manifest_sha256"])' "$P22_STATE/backup-verify.json")
PRE=$(.venv/bin/python -m engine.schema_migrations plan | .venv/bin/python -c 'import json,sys;print(json.load(sys.stdin)["expected_pre_catalog_sha256"])')
.venv/bin/python -m engine.schema_migrations apply "$R20_BACKUP" --backup-manifest-sha256 "$MSHA" \
  --source-commit "$(git rev-parse HEAD)" --pre-catalog-sha256 "$PRE"
.venv/bin/python -m tools.publish_snapshot            # first generation: API readers serve ONLY generations
.venv/bin/python -m tools.install_automation --apply  # stops/disables the paused TradingView timer
p22_unlock
p22_readers_ready
p22_release_producers
```

## Verify (stop at the first failure and roll back)

1. `python -m engine.schema_migrations plan` → `status: current`, schema id 1.
2. `python - <<<'from engine.lib.snapshots import pin_latest_generation as p; print(p().info.generation_id)'` succeeds;
   `curl -sI localhost:8000/health` shows `x-data-source: snapshot` and `x-generation-id`.
3. `/agent/evaluation/status` returns 200 right after publication (evidence reads need a generation newer than the
   primary's last write and ≤5 min old: every writer that should be visible to evidence reads must publish).
4. `python -m tools.check_invariants --snapshot latest` exits 0 (shadow).
5. `python -m tools.publish_snapshot --retention-dry-run` lists latest plus one previous.
6. First nightly after deploy: league account phase has no `SchemaMigrationRequired`; P15 scoring/pre-open green;
   ops digest shows no `held-enabled` for the TradingView timer.
7. Run `remote_restore_drill` against the private backup repo commit of the first generation-backed bundle.

## Rollback (any failure above; producers stay quiesced and locks held)

```bash
source "$P22_STATE/functions.bash"; p22_quiesce; p22_lock
.venv/bin/python -m tools.backup_database verify "$R20_BACKUP"
mkdir -m 700 "$P22_STATE/incident"; cp -a store/market.duckdb* "$P22_STATE/incident/"
mv store/snapshots "$P22_STATE/incident/quarantined-generations"   # readers on the old code use full snapshots
git checkout --detach "$(cat "$P22_STATE/predeploy.sha")"
cp "$R20_BACKUP/market.duckdb" store/market.duckdb.restore
cmp "$R20_BACKUP/market.duckdb" store/market.duckdb.restore
rm -f store/market.duckdb.wal; mv store/market.duckdb.restore store/market.duckdb
.venv/bin/python -m tools.install_automation --apply      # restores the pre-deploy unit set (TradingView enabled)
.venv/bin/python -m tools.publish_snapshot                # old-format full snapshot for the old readers
p22_unlock; p22_readers_ready; p22_release_producers
```

Raw zstd conversion (`tools/convert_raw_payloads.py --apply`) is a separate, later one-off: run only after the
restore drill passes, with the producer lock held and TradingView jobs drained; its rollback is the off-host raw archive.

## Rehearsal result (real store copy, 2026-10-22, p24/storage-r18 @ 2a0d90bd, capped restore @ 8dfeff3d)

Copy: newest published snapshot 2026-10-22 13:37 (12.5 GB, SHA-256 = manifest, catalog `865f64aa…`;
`store/backups/` is empty), run as `store/market.duckdb` of a worktree at the lane commit. Wall clock (peak RSS);
the previous column is the p24/r16 rehearsal (real copy where it ran, else its synthetic reconciled copy, marked *).

| Step | p24/r16 (before) | p24/storage-r18 (deploy path, real copy) |
|---|---|---|
| migration plan | 1 s | 1 s; pre-catalog `865f64aa…`, migrations 0 and 1 pending |
| backup create | 661 s (23.8 GB) | 506 s (5.0 GB); bundle file byte-identical to the source |
| backup verify | 168 s (5.2 GB) | 170 s (5.1 GB) |
| migration apply | **refused** after 324 s | applied, 327 s (5.1 GB); catalog `7286ea9b…`, schema 1; plan after: `current` |
| first generation publish | 365 s (24 GB)* | 622 s (7.5 GB), writer locks held 612 s; hot 3.0 GB + 1.66 GB cold parts (127), equality check 285 s |
| readers pin | 5 s* | 5 s pin + board read (prices 21,268,855, intraday 41,779,545); evidence read ok (`sim_settlements` 18 rows) |
| invariants on generation | 6 s, two missing-table errors* | 11 s (1.4 GB), all ten pass (shadow) |
| generation-backed backup + verify | 491 s (10.7 GB) + 163 s* | 502 s (10.7 GB) uncapped; capped: 912 s (5.1 GB) + 167 s, logical snapshot identical |
| restore drill | 10 s copy + 154 s check | pre-migration bundle 14 s + 155 s; generation bundles 11-19 s + 153-156 s; all byte-identical, logical snapshots equal |

Rerun after B4 (migration 0000 frozen as data; p24/storage-r18 @ 5b899cf5) on a fresh copy of the 15:52 published
snapshot (12.3 GB, SHA-256 = manifest, catalog `865f64aa…`); backup code unchanged since the table above:

| Step | Wall clock (peak RSS) |
|---|---|
| migration plan | 1 s; pre-catalog `865f64aa…` |
| backup create + verify (needed by apply) | 687 s (5.1 GB) + 185 s (5.0 GB); bundle byte-identical to the source |
| migration apply | applied, 354 s (5.2 GB); catalog `7286ea9b…`, schema 1; plan after: `current` |
| first generation publish | 632 s (7.5 GB) |
| readers pin | 5 s; board (prices 21,268,855, intraday 41,779,545) and evidence reads ok |
| invariants on generation | 11 s (1.4 GB), all ten pass (shadow) |

Publication now holds the producer locks about 10 minutes (was 6) because its DuckDB connections are capped at 4 GB.
The verify step needs the bundle path without a symlinked parent (hence `readlink -f "$HOME"` above). The off-host
`remote_restore_drill` was not run (needs a generation-backed bundle committed to the private backup repo).
