# Storage revision (r16-gen + r16-raw, now numbered revision 18) — deploy checklist

Branch `p24/r16` (on top of `p24/integrate-wave1`). Status: **DO NOT DEPLOY — blocked** (B1, B2; B3 fixed on the branch).
Rehearsed on a store copy only (see "Rehearsal result"). Nothing here was run against the live store.

## Blockers (must be fixed in a lane and re-reviewed before any deploy)

- **B1 Live catalog is not a supported migration pre-image.** Migration 0000 (`engine/migrations/0000_post_r15_baseline.py`)
  bootstraps only three exact catalogs (pre-v2 `3ea2d60e…`, v2 `62bf4255…`, r15 `dcd1a8ea…`), all generated from
  freshly initialised stores. The live store (snapshot 2026-10-21 08:34 and 2026-10-22 02:57, both catalog
  `865f64aa…`) differs from r15: extra tables `experiment_results`, `job_resolutions`, `sim_settlements`; missing
  `agent_paper_book_attribution`, `agent_paper_decision_receipts`, `agent_paper_order_attribution`; and 8 tables whose
  DDL differs (accumulated `ALTER … ADD COLUMN` order/constraints: actions_fetch_log, agent_evaluation_labels,
  agent_proposals, agent_shadow_attempts, daily_opportunity_execution_quality, daily_opportunity_runs,
  fundamentals_fetch_log, jobs). `bootstrap()` raises "database is not a supported pre-v2, v2, or r15 catalog".
- **B2 Lazily created tables are refused after migration.** `sim/settle.ensure_table` creates `sim_settlements` on
  first applied settlement; on a versioned store the guard raises `SchemaMigrationRequired` (reproduced by
  `tests/test_p22_round3.py::test_late_recovery_keeps_cash_delisting`, the only non-pin failure on `p24/r16`). Same
  class: `experiment_results`, `job_resolutions` and any other lazily created table. The baseline must include them
  (BOOTSTRAP_CALLS) and the live-shape pre-image must be supported (B1).
- **B3 (fixed on p24/r16) Backup fingerprint cost.** The Python per-row fingerprint took 3,980 s for one backup of the
  12 GB copy (13.5 GB RSS). It is now computed in DuckDB (`duckdb-row-sha256-v1`): backup 656-661 s, verify 163-168 s.
  Remaining: `COPY FROM DATABASE` peaks at ~24 GB RSS (pre-existing on main; it cannot run under a 4-6 GB cap because the
  copy is one uncommitted transaction). Recommended: copy the file bytes under the producer locks (as publication's
  no-WAL fast path does) and keep the logical-snapshot equality check.
- Integrator-owned, already known: registration/runtime re-pin (below), the off-host remote restore drill wiring
  (`write_remote_restore_plan` + `remote_restore_drill` need a generation-backed bundle committed to the private
  backup repo), orchestrator sign-off on pausing TradingView history (E4 evidence of no reader).

## Re-pin needed (do not run until B1 and B2 are fixed)

Pinned files changed by the storage revision: `engine/lib/db.py` (P15 + E1/sector/XS runtime), `engine/lib/snapshots.py`,
`tools/backup_database.py`, `tools/publish_snapshot.py`, `engine/queue_runner.py`, `engine/signals.py`,
`engine/tradingview_history_archive.py` (P15). 104 pin tests fail only for this (list in the integrate report).

## Pre-flight (all must hold)

1. `main` contains the merged branch; both timezone suites green after the single re-pin; `ruff check .` clean.
2. `.venv/bin/python -m engine.job_contract audit` → `status: ok`; `python -m tools.schedule_contract_check --static` clean.
3. Free space ≥ 70 GiB on the store filesystem (restore reserve) plus 2× store size for backup + first generation.
4. Window outside 13:00-21:00, 02:20-02:50, 07:30-07:50 UTC weekdays; no queue drain running.
5. A fresh verified off-host copy exists (trading-data backup current).

## Deploy (from the live checkout, after `git pull`; reuse the runbook helpers)

```bash
cd ~/trading-engine
export P22_ROOT="$PWD" P22_STATE="$HOME/.local/state/r18-deploy"; mkdir -m 700 -p "$P22_STATE"
# capture unit/cron/process state exactly as docs/settlement-runbook.md "P22 deployment" step 1, then:
source "$P22_STATE/functions.bash"       # helpers saved by that step
git rev-parse HEAD > "$P22_STATE/predeploy.sha"
p22_clean_source; p22_quiesce; p22_lock
R18_BACKUP="$HOME/r18-backups/pre-migration-$(date -u +%Y%m%dT%H%M%SZ)"
.venv/bin/python -m tools.backup_database create "$R18_BACKUP" --source store/market.duckdb
.venv/bin/python -m tools.backup_database verify "$R18_BACKUP" | tee "$P22_STATE/backup-verify.json"
MSHA=$(.venv/bin/python -c 'import json,sys;print(json.load(open(sys.argv[1]))["manifest_sha256"])' "$P22_STATE/backup-verify.json")
PRE=$(.venv/bin/python -m engine.schema_migrations plan | .venv/bin/python -c 'import json,sys;print(json.load(sys.stdin)["expected_pre_catalog_sha256"])')
.venv/bin/python -m engine.schema_migrations apply "$R18_BACKUP" --backup-manifest-sha256 "$MSHA" \
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
.venv/bin/python -m tools.backup_database verify "$R18_BACKUP"
mkdir -m 700 "$P22_STATE/incident"; cp -a store/market.duckdb* "$P22_STATE/incident/"
mv store/snapshots "$P22_STATE/incident/quarantined-generations"   # readers on the old code use full snapshots
git checkout --detach "$(cat "$P22_STATE/predeploy.sha")"
cp "$R18_BACKUP/market.duckdb" store/market.duckdb.restore
cmp "$R18_BACKUP/market.duckdb" store/market.duckdb.restore
rm -f store/market.duckdb.wal; mv store/market.duckdb.restore store/market.duckdb
.venv/bin/python -m tools.install_automation --apply      # restores the pre-deploy unit set (TradingView enabled)
.venv/bin/python -m tools.publish_snapshot                # old-format full snapshot for the old readers
p22_unlock; p22_readers_ready; p22_release_producers
```

Raw zstd conversion (`tools/convert_raw_payloads.py --apply`) is a separate, later one-off: run only after the
restore drill passes, with the producer lock held and TradingView jobs drained; its rollback is the off-host raw archive.

## Rehearsal result (store copy, 2026-10-22, p24/r16 @ 2de9c24e; log: the integrate lane report)

Copy: newest published snapshot 2026-10-22 02:57 (SHA-256 = manifest; `store/backups/` is empty). Wall clock (peak RSS):

| Step | Real copy (deploy path) | Synthetic reconciled copy |
|---|---|---|
| reconcile (baseline catalog + live rows) | n/a | 212 s (16 GB); `actions_fetch_log` rows violate baseline NOT NULL (left empty); 3 live-only tables dropped |
| migration plan | 1 s | 1 s after apply: `current` |
| backup create | 661 s (23.8 GB) | 656 s (23.5 GB) |
| backup verify | 168 s (5.2 GB) | — |
| migration apply | **refused** after 324 s: "not a supported pre-v2, v2, or r15 catalog"; copy unchanged | applied, 324 s (5.3 GB) |
| first generation publish | refused (unmigrated) | 365 s (24 GB); hot 3.0 GB + shared parts, 7.2 GB for two generations |
| republish (frontier reuse) | — | 268 s (24 GB) |
| readers | refused: no generation | pin 5 s; board read ok (prices 21.27M, intraday 41.78M rows); evidence read ok right after publish |
| invariants on generation | — | 6 s, runs (shadow regressions only) |
| generation-backed backup + verify | — | 491 s (10.7 GB) + 163 s |
| restore drill | 10 s copy, byte-identical, logical snapshot equal (154 s) | 9 s copy, byte-identical, logical snapshot equal |

The off-host `remote_restore_drill` was not run (needs a generation-backed bundle committed to the private backup repo).
