# P15 registration revision 21 — storage deploy checklist

Branch `r21/integrate` integrates `p24/storage-r18` (`f0282839`, based on `53a86579`) into
main `36d91bb1`, retaining the revision-20 GPT-6.1-Sol model amendment. Status: **awaiting integration acceptance**; not deployed. Rehearsed on store copies only (see "Rehearsal result"). Nothing here was run against the
live store.

**Deploy plan.** Trial 287 closes at its owner-precommitted 2026-11-03 06:30 UTC epoch. Hold until that epoch
has finished, then the orchestrator merges `r21/integrate` into `origin/main` and deploys in one sitting. Never
deploy in 22:15–23:59 or 02:00–04:00 UTC; also avoid the producer/provider windows below. The earlier pre-flight
switch of private `confirm_287.py` to `pin_latest_generation` is dropped: trial 287 closes on November 3 and has
no December epoch. Check any other remaining snapshot consumers before deployment.

**Rename.** The storage work formerly numbered revision 20 is revision 21 after main's model amendment.
`ops/storage-r20/` is now `ops/storage-r21/`; `P20_*`, `R20_*` and `p20_*` become `P21_*`, `R21_*` and `p21_*`.
Use a new `r21-deploy` state directory. Historical rehearsal entries keep their original commit references.

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
  (board 24 h, evidence 3.5 h) and possibly behind the primary.
- **Finding 3 (fixed): publication cadence and API writes.** Evidence writers: accounts-settle (07:45, 11:55 UTC),
  agent-data-capture (01:25), agent-shadow (01:30), daily opportunity (02:00), hourly and four-hour opportunity
  (New York market hours), P15 pre-open (09:05 New York), P15 scoring (02:30, publishes), P15 events (publishes at
  most every 2 h), P16 challengers (disabled), and API POSTs. The new `trading-engine-publish-on-change` timer
  (:12 and :42 UTC, minutes no other unit starts at) publishes only on weekdays during US market hours (09:30-16:00
  New York), at most once every three hours (it skips while the newest generation, from any publisher, is under 175
  minutes old), only when the primary changed, and not when every table whose storage changed is one no code the API
  imports names (`UNREAD_TABLES`); it skips at once when a publication, producer lock or writer is active. The
  nightly, P15 scoring and P15 pre-open publish after themselves; P15 events no longer do. Weekends carry only those
  job publications. Bound: in market hours evidence lags its last write by at most 3 hours plus one publication, inside
  the 3.5-hour evidence budget; settle's 07:45 and 11:55 UTC writes wait for the pre-open publication (up to about
  5.5 hours) and are served flagged `pending_publication` meanwhile. Its schedule-contract entry declares `writes:
  store/snapshots`. Publication now holds the producer locks and one read-only handle only while
  it copies the primary (49-131 s for the 12.7 GB copy in the rehearsal, against 10 minutes before), then builds the
  generation from the copy; API writes wait up to 180 s for that handle instead of failing (cost: a write arriving
  during a capture is delayed until it ends).
- **Finding 4 (fixed):** publication records the primary's storage identity before releasing its read-only handle.
- **Finding 6 (fixed): raw payloads stay main-readable.** Writers seal the legacy plain `<sha>.json` until
  `tools.convert_raw_payloads --apply` records the store flag `store/raw-payload-encoding.json`; a test runs main's
  reader over what the branch writes.
- **Finding 7 (fixed):** backup and generation manifests record the DuckDB version; verify refuses a version change
  with "DuckDB version differs", not the tamper message. A bundle written before versions were recorded refuses
  ("records no DuckDB version") unless `verify` or `remote-restore-drill` gets `--allow-unrecorded-duckdb-version`;
  pass it only after confirming the bundle was written under the DuckDB this verifier runs (`duckdb.__version__`;
  on 2026-10-23 the live virtualenv and this revision's lock both run DuckDB 1.5.5). The fingerprint's memory-limit restore parses
  DuckDB's text.
- **Finding 8 (fixed):** backup create checks the source WAL's identity, refusing a WAL-only commit by a writer outside
  the locks.
- **Finding 5 (fixed): this checklist.** Deploy and rollback are scripts (`ops/storage-r21/`) run from fresh shells
  under `set -euo pipefail`, every result checked; state persists in `$P21_STATE/state.env`; backup, migration and
  publication take the producer locks themselves (never inside a held lock); the live checkout stays on branch
  `main` and neither script copies or reverts anything under `data/`; units are staged without starting timers and
  timers start only at release, never the paused TradingView timer; the live schedule-contract check runs before
  release and again after it.
- **Known guard bypasses (accepted residual risk).** DDL assembled at run time from values the coverage scan cannot
  resolve, DuckDB relation-API persistence (refused at run time by the guard instead), and statements against the
  separate pit/research databases; publication and backup re-verify the exact catalog, so a bypass fails closed there.
- **Still open:** the off-host remote restore drill (needs a generation-backed bundle committed to the private backup
  repo); orchestrator sign-off on pausing TradingView history; incremental capture (copy only changed
  table data instead of the whole 12.8 GB primary) as a follow-up to cut publication I/O.

## Revision-21 pins

The final integration pins are recorded below after all source changes. Registration revision 21 keeps the
revision-20 model amendment, efforts and prior GPT-5.6 identities intact. Its reason discloses the accepted liquid
backfill, terminal-label, observer-writer and pre-open deadline fixes and the enforced 70 GiB minimum reserve.
`source_commit` is the last commit touching a registered file; `code_identity.files` covers the complete imported
closure; `registration_sha256` uses `canonical_sha256` over the document with that key removed. E1 v8, sector v12
and XS v23 retain every frozen value and migrate only their deployed digests. Any later pinned-source edit requires
all affected hashes, source commit and the registration self-hash to be recomputed before acceptance.

Final pins: 169 source files; `source_commit` `7e84006905e60ec7d3bce482ec35f190795e08c0`;
`registration_sha256` `0c42af77d52d2e8cffa0853e82cd28804d9cc64edb087d7f8432ff80b0356097`.

| Contract | Version | New digest | Accepted deployed predecessor (unchanged by the revision-20 model amendment) |
|---|---|---|---|
| E1 | 8 | `f8f31db9ffdf0d6b793706912d5655d31cb71ca915a71b3000e569697cf75465` | `2c8ec5b06a93edbca6104569c1bb5c66514cd6476f209169ca1f6041cd470538` |
| Sector | 12 | `de4e60ec4700130ac1bcac59bc17fca639e98595aa649e851f3340395b5c5d72` | `bad2576494c4c1357d8045018d98da3d1575ed096844b66423f094ee104dd7ea` |
| XS | 23 | `3f7fec7a8c9bb22a3fa857c2ea04ce4e62593f8aa6fcf85c363cf3d97bc4f48d` | `d00ee8124b254daed00e01846fe909f9e29606b8247a49c3e6bdfa46dd50d8c6` |

## Pre-flight (all must hold)

1. `main` contains the merged branch at registration revision 21; both timezone suites green; `ruff check .` clean.
2. `.venv/bin/python -m engine.job_contract audit` → `status: ok`; `python -m tools.schedule_contract_check --static` clean.
3. Free space ≥ 70 GiB (stricter than the host's 70 GB rule) on the store filesystem (restore reserve) plus 3× store size: the backup, the first generation,
   and publication's transient copy of the primary.
4. Window outside 22:15–23:59 and 02:00–04:00 UTC every day, and outside
   13:00–21:00 and 07:30–07:50 UTC weekdays; no queue drain running. Allow about 45 minutes
   with producers quiesced (backup create plus verify, migration, first publication; see the rehearsal timings).
5. A fresh verified off-host copy exists (trading-data backup current).
6. Trial 287 has closed at its November 3 epoch; no `confirm_287.py` consumer switch is required. Confirm any
   other active schema-1 consumer supports generations before deploy.
7. Inside the window, after quiescence, the deploy script runs `engine.schema_migrations plan` read-only on the live
   primary and stops unless the pre-image is `865f64aa…`.
8. In the same window it counts NULLs, read-only, in the five deployed columns the baseline makes NOT NULL
   (`agent_evaluation_labels.round_trip_cost_bps`, `net_return`, `net_excess_return`;
   `daily_opportunity_execution_quality.post_fill_position_qty`, `post_fill_cash`) and stops before the backup if any
   exists: migration 0000 would refuse such a row and roll back (the reviewer reproduced the refusal). On the
   2026-10-22 copies every one of these is non-NULL.

## Deploy

The orchestrator merges the approved branch into `origin/main` (a merge commit, `--no-ff`) and starts the deploy in
the same sitting, outside 22:15–23:59 and 02:00–04:00 UTC; `P21_APPROVED_SHA` is that merge commit. The live checkout stays on branch
`main`. Anything that moves the live checkout onto `origin/main` before quiescence would put revision-21 code on the
unmigrated store: the nightly's pull (22:30 UTC weekdays) and a `te-autopush` rebase. The deploy's first step pauses
both (the crontab and `te-autopush.timer`; it refuses while a nightly runs). If revision-21 code reaches the
unmigrated store anyway, every producer's writable open refuses with `SchemaMigrationRequired` ("unmigrated
operational store … nothing was written") before writing.

```bash
set -euo pipefail
: "${P21_APPROVED_SHA:?set the full approved merge SHA on origin/main}"
export P21_ROOT="$HOME/trading-engine" P21_STATE="$HOME/.local/state/r21-deploy" P21_APPROVED_SHA
cd "$P21_ROOT"
.venv/bin/python -c 'from datetime import datetime, timezone; n=datetime.now(timezone.utc); m=n.hour*60+n.minute; assert n >= datetime(2026,11,3,6,30,tzinfo=timezone.utc), "epoch not reached"; assert not (m>=1335 or 120<=m<240), "excluded deploy window"; assert not (n.weekday()<5 and (780<=m<1260 or 450<=m<470)), "producer/provider window"'
export OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 MKL_NUM_THREADS=4
export TRADING_ENGINE_DUCKDB_THREADS=4 TRADING_ENGINE_DUCKDB_MEMORY=4GB
export TRADING_ENGINE_MIN_FREE_GIB=70
# Refuse before deploy unless backup, generation and transient copy retain the reserve.
.venv/bin/python -c 'from engine.lib import store_limits; from pathlib import Path; p=Path("store/market.duckdb"); print(store_limits.require_free_space(p.parent,purpose="revision-21 deploy",need_bytes=3*store_limits.file_bytes(p)))'
git -C "$P21_ROOT" fetch --quiet origin
git -C "$P21_ROOT" show "$P21_APPROVED_SHA:ops/storage-r21/deploy.sh" > "$HOME/r21-deploy.sh"
nice -n 10 bash "$HOME/r21-deploy.sh"
```

`ops/storage-r21/deploy.sh`, in order (any failure stops it with producers quiesced):

1. Pauses the nightly and `te-autopush` (captured first, so release restores them; a refusal before step 2 resumes
   them at once). Then refuses unless `HEAD` is branch `main` with its upstream, no rebase, merge or revert is in progress, the index is
   clean, `P21_APPROVED_SHA` is a merge commit on `origin/main`, and every commit after it on `origin/main` is an
   ordinary commit that changes only `data/`. This runs before anything stops. It records the pre-deploy commit
   and copies `rollback.sh`, `common.bash` and `host.bash` from the merge into `$P21_STATE`.
2. Captures units, crontab and processes, then quiesces producers, readers and `te-autopush` (waiting for a running
   autopush's lock) and records the primary's file identity.
3. Runs the normal data commit: `engine.sync` commits pending producer output under `data/` and pushes it (a
   rejected push rebases onto `origin/main` once); `te-autopush` pushes any local commit sync left behind. The
   tracked tree must then be clean and `origin/main` must hold every local commit.
4. `git pull --ff-only`, then refuses unless `HEAD` contains the merge and only `data/` commits follow it (checked
   again just before the pull too, because `main` may move in between). Refusals here happen before the store is
   touched. `uv sync`; the registration must be revision 21.
5. Pre-flights 7 and 8 (read-only); backup create and verify under `$HOME/r21-backups`. The bundle is recorded in
   `state.env` (`R21_BACKUP`, `R21_MANIFEST`) only after it verifies.
6. Migrates (`--source-commit` is the deployed `HEAD`) and asserts `current`; runs the E1, sector and XS
   `--migrate-runtime-contract` migrations (each accepts only the deployed revision-19 digest and refuses an INVALID
   published report) and one ordinary refresh; then asserts that E1's checkpoint and the sector and XS reports carry
   the re-pinned digests and that neither report is INVALID.
7. Publishes the first generation; stages units with `install_automation --stage` (nothing starts); explicitly restarts the API and UI after the source change (even when their unit files match)
   and checks the generation headers, the evidence route (`pending_publication: false`), `/meta`'s
   `e1_forward`, `forward_review` and `xs_forward_review` (none INVALID), the invariants and retention.
8. Runs `schedule_contract_check --live` and refuses any violation except the ones quiescence explains (`not-active`
   timers, `missing-cron`).
9. Releases producers with the full `install_automation --apply` (installs and enables
   `trading-engine-publish-on-change.timer`), restarts the host timers that ran before (never the
   paused TradingView timer), and runs the live schedule-contract check again. A failure from here on says producers
   may be running.

## Verify after release (stop at the first failure and roll back)

Run from the deployed checkout; each command must exit zero. Restart trading-engine-api and trading-engine-ui after the code changes, then verify /health and
/agent/model/status. Stage starts no service; the deploy's reader phase explicitly restarts both before checking
them. The installer will also restart them when their source changed once the separate v2-restart lane lands. This prevents the stale-source failure observed after
October 22, when the API ran old code for eight days.

```bash
set -euo pipefail
cd "$P21_ROOT"
.venv/bin/python -m engine.schema_migrations plan > "$P21_STATE/post-schema.json"
.venv/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["status"] == "current" and d["database_schema_id"] == 1, d' "$P21_STATE/post-schema.json"
.venv/bin/python -m tools.registration_identity --base "$P21_APPROVED_SHA^1"
.venv/bin/python -m tools.schedule_contract_check --static
systemctl --user is-enabled --quiet trading-engine-publish-on-change.timer
systemctl --user restart trading-engine-api.service trading-engine-ui.service
systemctl --user is-active --quiet trading-engine-publish-on-change.timer trading-engine-api.service trading-engine-ui.service
systemctl --user show trading-engine-api.service -p MainPID -p ExecMainStartTimestamp
curl --silent --fail --dump-header "$P21_STATE/post-health.headers" --output "$P21_STATE/post-health.json" http://127.0.0.1:8000/health
grep -qi '^x-data-source: snapshot' "$P21_STATE/post-health.headers"
grep -qi '^x-generation-id: market-' "$P21_STATE/post-health.headers"
grep -qi '^x-generation-stale: false' "$P21_STATE/post-health.headers"
curl --silent --fail http://127.0.0.1:8000/agent/model/status > "$P21_STATE/post-model-status.json"
.venv/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); assert "GPT-6.1-Sol:max" in json.dumps(d), d' "$P21_STATE/post-model-status.json"
curl --silent --fail http://127.0.0.1:8000/agent/evaluation/status > "$P21_STATE/post-evaluation.json"
.venv/bin/python -c 'import json,sys; g=json.load(open(sys.argv[1]))["generation"]; assert g["pending_publication"] is False, g' "$P21_STATE/post-evaluation.json"
curl --silent --fail http://127.0.0.1:8000/meta > "$P21_STATE/post-meta.json"
.venv/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); assert all(d[k]["status"] != "INVALID" for k in ("e1_forward","forward_review","xs_forward_review"))' "$P21_STATE/post-meta.json"
.venv/bin/python -m tools.check_invariants --snapshot latest
.venv/bin/python -m tools.schedule_contract_check --live
.venv/bin/python -m tools.publish_snapshot --retention-dry-run
```

During US market hours, repeat the evidence check within 3.5 hours of a write; inspect
`journalctl --user -u trading-engine-publish-on-change.service --since today` for a successful publication or a
valid unchanged/age skip. The first nightly must advance books and all three forward records without
`SchemaMigrationRequired`; P15 scoring and pre-open must complete, with no held unit enabled or active in the ops
digest. After the first generation-backed backup reaches the private backup repo, run its off-host restore drill
with the exact remote and commit below; the tool verifies the pinned bundle manifest from that commit and checks
its own reserve. Use a disposable scratch directory on a volume with enough reserve and record the receipt.

```bash
: "${P21_BACKUP_REMOTE:?set the private backup repository remote}"
: "${P21_BACKUP_COMMIT:?set the exact backup commit}"
: "${P21_RESTORE_SCRATCH:?set a disposable restore scratch parent}"
nice -n 10 .venv/bin/python -m tools.backup_database remote-restore-drill \
  "$P21_BACKUP_REMOTE" "$P21_BACKUP_COMMIT" "$P21_STATE/remote-restore.json" \
  --scratch-parent "$P21_RESTORE_SCRATCH"
```

## Rollback

```bash
P21_STATE="$HOME/.local/state/r21-deploy" bash "$HOME/.local/state/r21-deploy/rollback.sh"
```

The deploy copies `rollback.sh`, `common.bash` and `host.bash` into `$P21_STATE`, so the rollback runs from a fresh
shell whatever is checked out. It never leaves `HEAD` detached and never copies or reverts anything under `data/`:

1. Quiesces. With a recorded backup it refuses unless the bundle verifies with the recorded manifest hash, then keeps
   the incident primary and quarantines the generations. Without one (the deploy stopped at or before the backup,
   including a failed backup create) it refuses unless the phase is at or before `code-switched` and the primary's
   file identity is unchanged since quiesce: the store was never written, so it is left alone.
2. Removes the publish-on-change units.
3. Runs the normal data commit, `git pull --ff-only`, and, when `HEAD` carries the approved merge, commits
   `git revert -m 1 <merge>` on `main` (refusing if a non-`data/` commit follows the merge), pushes it to
   `origin/main` and pulls. `main` must then equal `origin/main` and match the merge's first parent outside `data/`,
   so the nightly pull keeps the previous code. `uv sync`.
4. With a verified backup: restores the primary byte for byte; restores E1's checkpoint and the sector and XS forward
   reports (and their pages) to the deployed commit's versions, the commit the backup was taken at before the
   contract migrations, through a data commit; runs one normal forward refresh under the previous code and refuses
   to release unless E1, sector and XS are all valid (committed by a second data commit); then publishes a snapshot
   in the previous code's format.
5. Starts the readers and releases producers with the previous code's installer.

A rerun after a stop part-way keeps the first incident copy, reverts once (the revert commit is recorded in
`$P21_STATE/rollback.env`) and restores the primary only once.

**Re-deploy after a rollback.** The rollback's revert commit stays on `main`, so merging the branch again would bring
in only commits made after the first merge: the revert must be reverted first. Revert it on a redeploy branch, merge
any fixes there, and merge that branch with `--no-ff`, so the deploy again gets a merge commit (it refuses anything
else, and a later rollback reverts it with `-m 1`):

```bash
git fetch origin
git checkout -B r21-redeploy origin/main
source "$P21_STATE/rollback.env"          # P21_REVERT_SHA, the rollback's revert commit
git revert --no-edit "$P21_REVERT_SHA"    # restores the revision-21 code on the redeploy branch
if test -n "${P21_FIXED_BRANCH:-}"; then git merge --no-edit "$P21_FIXED_BRANCH"; fi
git checkout main && git pull --ff-only
git merge --no-ff -m "Merge r21-redeploy: storage revision 21 again" r21-redeploy
git push origin main                      # P21_APPROVED_SHA=$(git rev-parse HEAD); deploy at once
```

A rollback after release **loses every write to the primary made since the backup** (it stays in
`$P21_STATE/incident/market.duckdb` for manual recovery). Raw payloads written since release stay readable by the
previous code, because they are in the legacy plain encoding until the conversion flag is set. `data/` keeps what
producers wrote: report files written since release are committed by the data commit and stay as they are (the next
nightly under the previous code rewrites them), and every data commit stays in history. The `store/pit/*.duckdb`
databases (free sources, options, minute bars, SEC bulk) are separate stores that are not restored: they keep rows
written since release, and their schemas did not change in this revision.

**Forward records after a rollback past the contract migrations.** Since the contract migrations, E1's checkpoint and
the sector and XS reports carry the revision-21 digests, which the previous code refuses. The rollback restores
exactly these records (step 4) from the deployed commit: the restored primary predates every post-deploy
observation, so records and store agree again, and the forward refresh proves it before producers run.

Raw zstd conversion (`tools/convert_raw_payloads.py --apply`) is a separate, later one-off: run only after the
restore drill passes, with the producer lock held and TradingView jobs drained. It records the store flag that switches
writers to zstd, after which a code rollback can no longer read new raw payloads; its rollback is the off-host raw
archive.

## Revision-21 acceptance checks

At the integrated source, both full suites passed with 6,525 tests, zero failures and zero skips:
UTC 259.22 s; Asia/Singapore 267.05 s. Run the release checks from `r21/integrate`:

```bash
set -euo pipefail
TZ=UTC REGISTRATION_BASE_REF=origin/main nice -n 10 .venv/bin/python -m pytest -q -W error -n 8 -p no:cacheprovider
TZ=Asia/Singapore REGISTRATION_BASE_REF=origin/main nice -n 10 .venv/bin/python -m pytest -q -W error -n 8 -p no:cacheprovider
.venv/bin/python -m tools.registration_identity --base origin/main
.venv/bin/python -m tools.deploy_gate --check . --base origin/main
.venv/bin/python -m tools.schedule_contract_check --static
git diff --exit-code origin/main -- sim/execution.py sim/nyse.py engine/verify_prices.py
```

Registration identity passes for its one registration that pins code. The static schedule check passes with the
existing disclosed P15-scoring restart-loop exception. The final diff leaves both trial-375 simulator files and
`engine/verify_prices.py` byte-identical to main; the model client also remains identical to the revision-20 client.

## Publication I/O (measured 2026-10-23)

One republication of the 12.8 GB store (a later generation, 60 of 67 cold parts reused), with the whole process tree
accounted from `/proc/<pid>/io`: 955 s, 31.3 GB read, 120.6 GB of pages dirtied, of which 64.1 GB never reached the
disk (the scratch capture copy and DuckDB spill, deleted first), so **56.4 GB written**; the capture copy alone is
12.8 GB of that. A first generation (every cold part new) dirtied 74-76 GB. The capture window, in which producers and
API writers wait, took 89 s and 154 s (the copy is bound by the disk: a plain `cp` of the same file took 137 s at the
same hour); API writes wait up to 180 s.

Expected volume, from the writers' schedules and the publishers' own runs:

| Publication policy | Per weekday | Written per weekday | Per week |
|---|---|---|---|
| publish-on-change every :12/:42 slot after a change, events every 2 h (before round 2) | 25 | about 1.4 TB | about 7.3 TB |
| at most hourly (first round-2 pass) | 16 | about 0.9 TB | about 4.7 TB |
| nightly, P15 scoring and P15 pre-open after themselves; otherwise at most every 3 h in market hours (this revision) | 5 (scoring, pre-open, about 16:42 and 19:42 UTC, nightly) | about 0.28 TB written, 0.16 TB read | 26 publications, about 1.5 TB (Saturday: scoring only; Sunday: none) |

Follow-up (open, not built): incremental capture, copying only changed table data instead of the whole 12.8 GB file,
would cut the capture copy and most of each publication's writes.

## Revision-21 rehearsal method

Use one disposable checkout with the exact integration code and the published snapshot's matching metadata cohort.
The Friday-postflight log is required even though it is untracked; validate all prospective and operational cohort
files before the expensive backup. Resolve the checkout, data directory and bundle paths to their canonical paths:
the verifier refuses symlinked directory components. Recovery database files must be owner-only (`chmod 600`).

Before creating any store copy, generation or backup bundle, measure free space on the store volume and refuse
unless free space minus the full expected size remains at least 75 GB (the code's 70 GiB reserve is stricter).
Keep at most two store-sized files, and delete each full copy as soon as its step is verified. Open the original
published snapshot read-only and pin its immutable bytes for the entire drill. Delete the full backup after the
create/verify step; recreate its mandatory recovery bytes from that same pinned pre-image only for migration,
verify them through the migration tool, and delete them immediately after migration. Verify original-table row
counts and logical hashes, migrate and refresh the three frozen runtime records, then publish from the working
copy. Delete the verified generation and working store before restoring the original pre-image for the rollback
check. Validate the restored bytes, catalog and frozen records under the previous main code, then delete the copy.
Run at niceness 10, with at most four DuckDB threads and at most 8 GB memory; this rehearsal uses 4 GB.

## Rehearsal result (2026-10-23, mirrored-live sandboxes)

Each sandbox mirrors the live checkout: branch `main` tracking a bare origin (a local repository) at the live main,
the live checkout's uncommitted `data/` outputs (`data/_meta.json` modified, `data/reports/producer-detail/`
untracked), the lane's virtualenv, and a copy of a live published snapshot (SHA-256 equal to its manifest) as the
primary. An "orchestrator" clone pushes `main` + `p24/storage-r18` as a `--no-ff` merge; deploy and rollback are the
merge's own scripts, run from fresh shells (`env -i`); host steps (units, crontab) are stand-ins that only log, and
the readers are a real API process for the sandbox store. Times are UTC, outside 22:15-23:59 and the provider windows,
except where noted.

| Scenario (head) | Result |
|---|---|
| fast-forward refusal (ceea1800) | `origin/main` carries a code commit after the merge: the deploy refuses at its first step ("changes files outside data/"); nothing stopped, `HEAD` and the primary's identity unchanged |
| failed backup create, rollback (ceea1800) | `main` moved by a data commit; the deploy commits and pushes the uncommitted outputs (`engine.sync`: push rejected, rebased, pushed), fast-forwards, passes the pre-flights; backup create fails (unwritable parent); `state.env` has no `R21_BACKUP`, phase `code-switched`. The rollback proves the primary unchanged since quiesce, commits `Revert "Merge …"` on `main`, pushes and pulls: `HEAD` = `origin/main`, code = the merge's first parent, registration 19, every data commit and output kept, store untouched; a rerun is a no-op ("already reverted") |
| deploy, rollback after release (ceea1800, 23:14 copy) | deploy 35 min (backup create 521 s + verify 172 s, migration 347 s, contract migrations 1 s each, first generation 755 s, first evidence read 4.4 min); only `data/` after the merge; E1 `676aa2ae`, sector `7b3ed5a3`, XS `0727df99`; `/meta` shows all three ACCUMULATING. Publish-on-change right after the republication skips ("captured from the primary's current bytes"), and after an API write skips ("13 minutes old; at most once an hour"). The rollback after release keeps the incident copy, commits the outputs written since release, reverts on `main`, restores the primary byte for byte (SHA-256 equal to the pre-deploy copy) and serves the previous code's API (11 min) |
| same, measured (ceea1800, 23:14 copy) | the republication I/O above; the rollback after release again byte-identical (10 min) |
| deploy, one real nightly, rollback after release (head cd0892a8, 02:54 copy after the host's P15 scoring, `main` at the live dcc194b4) | deploy 33 min (backup 559 + 189 s, migration 380 s, first generation 789 s); every active book at 2026-10-22; `engine/run_daily.sh` (sandbox HOME, drain budget -1) 39 min, every stage exit 0: collect 292 s, actions 1,118 s, market date 2026-10-22, screen, league, sector and XS ACCUMULATING under `7b3ed5a3`/`0727df99`, E1 checkpoint `676aa2ae` with 13 observations, sync pushed its screen commit to the sandbox origin, snapshot 786 s. The rollback after release kept that commit, reverted on `main` and restored the primary byte for byte (8 min) |
| deploy, rollback after release with the forward-record restore (b939c275, after the round-2 decisions; 02:54 copy, `main` at dcc194b4) | deploy from 07:50 UTC: its first step paused the nightly and `te-autopush` (stubbed), then as above; E1, sector and XS ACCUMULATING under the re-pinned digests. The rollback after release restored the primary byte for byte, restored E1's checkpoint and the sector and XS reports to the deployed commit's versions (data commit `storage_r21_rollback_records`), and the previous code's refresh was valid: sector ACCUMULATING `bad25764`, XS ACCUMULATING `d00ee812`, E1 checkpoint `2c8ec5b0` with 13 observations and `--report-only` clean (refresh committed); `main` = `origin/main`, code = the merge's first parent; previous code's API 200 (9 min) |

Two runs did not reach the nightly, by design: on the post-nightly 23:14 copy the nightly stops at market-date
("active portfolio checkpoints disagree: 2026-10-21, 2026-10-22") because the P15 books advance only at the host's
02:30 P15 scoring (the same check, unchanged from main, refuses on the copy itself); and backup create refuses
("screen-metadata-behind", "evidence-invalid") when the checkout's committed reports are newer or older than the
store, until the checkout matches the store's evening. In the first scenario-3 run the sandbox nightly started at
02:15, its collect ended at 02:19 and its actions stage ran 02:19-02:26 inside the 02:20-02:50 window before it was
paused until 02:50.

The off-host `remote_restore_drill` was not run (needs a generation-backed bundle committed to the private backup repo).
