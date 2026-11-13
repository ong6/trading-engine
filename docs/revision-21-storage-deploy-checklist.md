# P15 registration revision 21 — storage deploy checklist

Branch `r21/integrate` integrates `p24/storage-r18` (`f0282839`, based on `53a86579`) into
main `36d91bb1`, retaining the revision-20 GPT-6.1-Sol model amendment. The 2026-11-11 unblock
also merges main through `72bc5e78` and the P15-lock (`6b3b69e0`), ETF-verifier/TradingView-mapping
(`9379457b`) and basis-release (`3dffadf1`) fixes. Status: **awaiting integration acceptance**;
not deployed. Main through `e02fbabf` (merged at `4b395d91`) adds minute-capture recovery, terminal rejection evidence and no-bars split repair selection.
The November 12 amendment adds archive capacity and bounded nightly split retry. Trial 375
compatibility is rehearsed; live-287 signal/settle compatibility is audited. Deployment still
requires the disk reserve and the quiescent window rules below. The owner collection decision
on November 13 keeps every revision-20 collection path enabled in revision 21.
All database writes in this lane were to disposable sandboxes.

**Deploy plan.** Trial 287 confirmation is **CLOSED**. The owner's October 30 pre-commitment
(private README) closes it on any November 3 result other than PASS; that epoch was PENDING.
The orchestrator disabled `confirm-287.timer` on 2026-11-12 at about 12:10 UTC. Preserve its
frozen runner, registration and PENDING ledger; it never runs again and needs no amendment.
The separately registered live-287 paper signal and settlement remain compatible (pre-flight 6).
The orchestrator merges `r21/integrate` into `origin/main` and deploys in one sitting. Never
deploy in 22:15–23:59 or 02:00–04:00 UTC; also avoid the producer/provider windows below.

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
  timers start only at release, including TradingView when its collection flag is enabled; the live schedule-contract check runs before
  release and again after it.
- **Known guard bypasses (accepted residual risk).** DDL assembled at run time from values the coverage scan cannot
  resolve, DuckDB relation-API persistence (refused at run time by the guard instead), and statements against the
  separate pit/research databases; publication and backup re-verify the exact catalog, so a bypass fails closed there.
- **Still open:** the off-host remote restore drill (needs a generation-backed bundle committed to the private backup
  repo); incremental capture (copy only changed table data) as a follow-up to cut publication I/O; the deploy disk reserve
  (pre-flight 3), to be measured again in the window.

## Revision-21 pins

The final integration pins are recorded below after all source changes. Registration revision 21 keeps the
revision-20 model amendment, efforts and prior GPT-5.6 identities intact. Its reason discloses the accepted liquid
backfill, terminal-label, observer-writer and pre-open deadline fixes, the enforced 70 GiB minimum reserve,
and the schema-1 compatibility, scoring lock deadline, ETF verification, proven provider mappings and
evidence-based basis release integrated on 2026-11-11 (including the unreported-split residual risk).
The November 12 notes disclose the 120 GiB total archive cap and 90 GiB live-store soft warning
(the former 60:80 proportion), plus the store-volume reserve of 70 GiB + 2× primary including WAL.
These are operational capacity settings, not registered statistical values. Nightly retries at most
three recorded `skipped_no_bars` splits after accepted post-ex bars arrive, through the repair tool's
complete source-history proof; mismatches/unavailable evidence retain the skip and quarantine.
Round two rotates groups of at most three by a UTC weekday index matching the Monday–Friday
nightly. A fixed eligible set gets every turn within ceil(count/3) scheduled nights while eligible.
The automatic horizon is ex-date through 60 calendar days after it; older skips remain for manual
repair and appear only as an age-out count in the run summary. No retry ledger or migration is added.
`source_commit` is the last commit touching a registered file; `code_identity.files` covers the complete imported
closure; `registration_sha256` uses `canonical_sha256` over the document with that key removed. E1 v8, sector v12
and XS v23 retain every frozen value and migrate only their deployed digests. Any later pinned-source edit requires
all affected hashes, source commit and the registration self-hash to be recomputed before acceptance.

The round-two integrated re-pin follows the existing two-commit sequence: freeze runtime
literals and disclosure (`41da99c1`), then hash that committed closure into P15 (`c9f3d4a2`). No later registered
source edit is included. Final pins: 175 source files;
`source_commit` `41da99c1169bf124894dcd433942a046076713d5`;
`registration_sha256` `028159ed70b4bd94982f805cd703ed9445638138a1e2eb8a0deebb7540538d17`.
The full P15 import closure includes the repair helper and five invariant support modules;
sector and XS pin the repair helper reached by reconciliation. Their digests change for the fair
retry selection; E1's freshly recomputed digest is unchanged. Frozen versions and accepted deployed
predecessors remain unchanged.

| Contract | Version | New digest | Accepted deployed predecessor (unchanged by the revision-20 model amendment) |
|---|---|---|---|
| E1 | 8 | `a024cca811e9e185a04ab5306601b1cdb16c261172a33e86aa5a1ad80166fe9d` | `2c8ec5b06a93edbca6104569c1bb5c66514cd6476f209169ca1f6041cd470538` |
| Sector | 12 | `5e3f72322a8c74b84cd0f468a180bb31d93ddbee80149fa5fe733d92d12fae0c` | `bad2576494c4c1357d8045018d98da3d1575ed096844b66423f094ee104dd7ea` |
| XS | 23 | `c894547e95293624a174a341b6a64e6e6801577c402a359de7532c9044d4017c` | `d00ee8124b254daed00e01846fe909f9e29606b8247a49c3e6bdfa46dd50d8c6` |

## Pre-flight (all must hold)

1. `main` contains the merged branch at registration revision 21; both timezone suites green; `ruff check .` clean.
2. `.venv/bin/python -m engine.job_contract audit` → `status: ok`; `python -m tools.schedule_contract_check --static` clean.
3. Free space ≥ 70 GiB (stricter than the host's 70 GB rule) on the store filesystem (restore reserve) plus 3× primary size (`market.duckdb` including WAL): the backup, the first generation,
   and publication's transient copy of the primary.
   On 2026-11-11 the primary and published pre-image are each 18,979,762,176 bytes (17.6763 GiB).
   Required free: 132,101,214,208 bytes (123.0288 GiB). The measurement after sandbox cleanup
   has 84,327,514,112 bytes (78.5361 GiB) free: **short by 47,773,700,096 bytes (44.4927 GiB)**.
   That dated measurement failed; background backup compression is reclaiming space on November 12.
   The final November 12 measurement below does not replace the window gate. Re-run `df -B1` and the deploy's
   `require_free_space(..., need_bytes=3*file_bytes(primary))` immediately before the window;
   the figures move with other jobs and the store. Compatibility adds no store-sized file.
4. Window outside 22:15–23:59 and 02:00–04:00 UTC every day, and outside
   13:00–21:00 and 07:30–07:50 UTC weekdays; no queue drain running. Allow about 45 minutes
   with producers quiesced (backup create plus verify, migration, first publication; see the rehearsal timings).
   Account for private readers too: live-287 settle/report Tue–Sat 07:40 and 11:50 UTC,
   signal weekdays 09:25 New York; T4 Sunday 07:05 signal and Tuesday 06:30 settle;
   backup starts daily 04:30 and 10:30; weekend queue work starts 06:00. Refresh actual timers,
   cron and queue state before choosing the window. The scripts do not pause every private reader.

   **Owner collection decision (2026-11-13).** Revision 21 pauses no collection relative
   to deployed revision 20. TradingView daily history, Massive options and the five macro
   series retain their collection flags enabled; each switch remains available for a later
   explicit pause. TradingView is quiesced during deploy and resumes at release. The existing
   revision-20 Massive options timer hold for provider responses is unchanged.

5. A fresh verified off-host copy exists (trading-data backup current).
6. The unmodified trial-375 reader accepts the generation hot file in a reduced-copy rehearsal
   (2026-11-11, below). Publication now includes `schema_version: 1`, `snapshot`, the hot file's
   `sha256`, and `as_of` inside the authenticated schema-2 manifest. Its resolved file and sibling
   manifest stay in the snapshots directory, and the hot file contains `prices`; no extra copy.
   The generation validator still checks its self-hash, exact field set, catalog and every file;
   compatibility must be either absent on an older schema-2 manifest or a complete, matching pair.
   The frozen reader's lines 169–179 check path, name, schema, hash **length** and session-close ≤
   publication ≤ observation. It does not compute the file hash; the rehearsal and r21 pin do.
   **Confirmation closure:** its known schema-2 and frozen-verifier refusals are historical diagnostics,
   no longer a deploy blocker. Confirmation is closed under the owner's pre-result commitment;
   the orchestrator disabled its timer at about 12:10 UTC today. In the window verify
   `systemctl --user is-enabled confirm-287.timer` reports `disabled` and
   `systemctl --user is-active confirm-287.timer` reports `inactive` (each returns nonzero for
   that expected state); it must not be queued to run. Do not amend or run the frozen confirmation.
   **Live-287 compatibility:** the November 12 r21-gates audit imported signal/settle and replayed
   322 cached responses: 315 successful parses, seven errors, no price differences. Its paths never
   call confirmation's source-pin or snapshot-layout gates. Explicit empty history now reports
   `fetch_or_parse_error:SourceNoData:…` instead of `fetch_or_parse_error:SourceError:…`; both are
   missing-price observations caught by `SourceError`, with no substitute fill or new ETF fallback.
   Repeat the consumer scan and read-only live imports below before quiescence. After first publication,
   before release, repeat the frozen-reader and generation verification command below.
7. Inside the window, after quiescence, the deploy script runs `engine.schema_migrations plan` read-only on the live
   primary and stops unless the pre-image is `865f64aa…`.
   The orchestrator already applied the November 12 live split repair (six iShares ETFs,
   28,958 bars) after the earlier audit; re-take the migration pre-image in this window rather
   than reuse the earlier receipt. This lane made no live-store write.
8. In the same window it counts NULLs, read-only, in the five deployed columns the baseline makes NOT NULL
   (`agent_evaluation_labels.round_trip_cost_bps`, `net_return`, `net_excess_return`;
   `daily_opportunity_execution_quality.post_fill_position_qty`, `post_fill_cash`) and stops before the backup if any
   exists: migration 0000 would refuse such a row and roll back (the reviewer reproduced the refusal). On the
   2026-10-22 copies every one of these is non-NULL.

### Pre-flight 6 consumer inventory (November 11 scan, November 12 audit and closure)

The scan covered `~/trading-alpha/live`, `~/trading-data` (including archived files), the user
systemd units (following links), `crontab -l`, and `~/news-scraper`. The confirmation runner was
also followed from its installed unit. No private file or unit was edited or executed as a job.

| Consumer | Generation compatibility and remaining action |
|---|---|
| `live/t4_forward.py`, `t4-forward-signal.service` (Sunday 07:05 UTC), `t4-forward-settle.service` (Tuesday 06:30 UTC) | Accepted the hot file and schema-1 compatibility fields with the unchanged imported reader. The two frozen simulator files still match main and their private receipt. Retention keeps latest plus one predecessor; this short reader resolves once and opens read-only. |
| `research/confirm_287.py`, `confirm-287.service`/timer | **CLOSED**, November 3 PENDING triggered the October 30 owner commitment; timer disabled by the orchestrator November 12 ~12:10 UTC. Preserve frozen bytes and the ledger; no future epoch or amendment. Verify inactive/disabled in the window. |
| `trading-data/alpha-work/live-287/prepare_measurement.py:54` | Historical one-shot measurement preparation; resolves latest and reads `universe`, which remains hot. Its query succeeded on the generation (12,892 rows); no manifest-version check. The archived script contains literal `~` paths, so standalone path expansion/setup is still required; it was not run. |
| `trading-data/backup.py`, `trading-data-backup.service` | Delegates create/verify to the installed engine backup tool; no direct schema-1 snapshot reader. r21 has generation-aware backup verification; the existing locked-primary fallback remains a primary copy. No live backup or off-host restore was run here; its disk reserve remains required. |
| `live/gap_fade_live.py` signal/settle/report, `live/trade_intents.py`, `trading-data/evidence_archive.py` | Compatible in the November 12 import/cache audit. Gap-fade uses confirmation's Nasdaq helpers, never the monthly gates. One missing-price exception-name diagnostic changes to `SourceNoData`; prices and refusal semantics match. Intent schemas are separate from market manifests. Verify imports in the window and observe the first normal signal/settle/report after release. |
| User units, crontab, news scraper | The units route to the three consumers above; crontab's engine jobs and scraper have no additional direct latest/manifest reader. Engine readers use r21's tested generation API. The scraper has no market snapshot reference. Archived documentation mentions are not scheduled consumers. |

Run this **after the first generation publication and before release**, from the deployed
checkout. It imports only the frozen snapshot interfaces, disables bytecode writes, keeps an
r21 pin throughout, verifies the exact file the frozen reader resolves, and reads the latest
session. It makes no private-state write and does not invoke signal, settle, report or a relay.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B - <<'PY'
import hashlib, importlib.util, sys
from datetime import datetime, timezone
from pathlib import Path
import duckdb
from engine.lib.snapshots import pin_latest_generation
spec = importlib.util.spec_from_file_location("r21_frozen_reader", Path.home()/"trading-alpha/live/t4_forward.py")
reader = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reader
spec.loader.exec_module(reader)
with pin_latest_generation(Path("store/market.duckdb")) as info:
    with duckdb.connect(str(info.path), read_only=True, config={"threads":"1"}) as con:
        latest = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    frozen = reader.Snapshot(observed=datetime.now(timezone.utc), required_session=latest,
                             directory=info.path.parent)
    with frozen.path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    assert frozen.path == info.path and digest == frozen.metadata["sha256"] == info.sha256
    with frozen.connection() as con:
        rows = con.execute("SELECT COUNT(*) FROM prices WHERE date=?", [latest]).fetchone()[0]
    assert rows > 0 and info.manifest_schema_version == 2
    print("trial 375 accepted; hot hash and generation files verified; latest session", latest, "rows", rows)
PY
```

Read-only live-287 import check from the deployed checkout before release (no signal,
settlement, report, export or provider call):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B - <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home()/"trading-alpha/live"))
import gap_fade_live, massive_287, trade_intents
from engine.verify_prices import SourceError, SourceNoData
assert issubclass(SourceNoData, SourceError)
print("live-287 signal/settle imports accepted; SourceNoData remains a SourceError")
PY
```

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
   `trading-engine-publish-on-change.timer` and the enabled TradingView history timer), restarts
   the host timers that ran before subject to the collection flag, and runs the live schedule-contract check again. A failure from here on says producers
   may be running.

## Verify after release (stop at the first failure and roll back)

Run from the deployed checkout; each command must exit zero. The deploy's reader phase (step 7) restarts
trading-engine-api and trading-engine-ui explicitly, and step 9's `install_automation --apply` restarts and
health-checks them again because their source changed in the deployed range (`changes.restarted_services` in its
output; each entry must show `status: ok`). Do not restart them again here: wait for readiness instead. This prevents the stale-source failure observed after
October 22, when the API ran old code for eight days.

```bash
set -euo pipefail
cd "$P21_ROOT"
.venv/bin/python -m engine.schema_migrations plan > "$P21_STATE/post-schema.json"
.venv/bin/python -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d["status"] == "current" and d["database_schema_id"] == 1, d' "$P21_STATE/post-schema.json"
.venv/bin/python -m tools.registration_identity --base "$P21_APPROVED_SHA^1"
.venv/bin/python -m tools.schedule_contract_check --static
systemctl --user is-enabled --quiet trading-engine-publish-on-change.timer
for _ in $(seq 90); do curl --silent --fail --output /dev/null http://127.0.0.1:8000/health && break; sleep 1; done
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

After release, drain pending archive jobs **1006/1007/1009/1014** (TradingView history,
intraday, earnings and fundamentals) through the normal parent queue in an available producer
window. Recheck the store cap and 70 GiB + 2× primary/WAL reserve; preserve failed attempts.
The normal budget can require several windows. A `PARTIAL:` result means work remains pending;
repeat in the next permitted window. Job **1006** must dispatch as `tradingview_history` under
the enabled flag, through the parent queue's resource, capacity and producer admission checks.
Retain its normal completion or partial/failure receipt alongside the other three jobs. Never
bypass parent admission with the child `--run-one`.

```bash
.venv/bin/python -m engine.queue_runner --run --kinds earnings,fundamentals,intraday,tradingview_history --jobs 1 --report-partial
.venv/bin/python -m engine.queue_runner --status
.venv/bin/python -m tools.verify_friday_postflight --dry-run  # after the first normal Friday nightly
```

Verify all four job dispositions through the queue, and query `SELECT MAX(as_of) FROM earnings_calendar`
on the primary in a normal read-only window: it must advance beyond October 30 and meet Friday
postflight's freshness rule. Retain queue and postflight receipts; the first normal Friday
postflight after release must have no stale-earnings failure. This lane runs no live queue or postflight.

After release, refetch wider real provider history for INTC and IOVA, including at least twenty
unchanged stored sessions before the held break and the break itself. Check the completed action
fetch and the release receipt under the integrated basis rule; the short five-day nightly fetch
cannot establish that history. Review the October 30 orders that already expired by `no_bar`
against their original intents and deadlines; record the disposition without replaying an expired
order or fabricating a historical fill. These operator steps were not run in this lane.

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

Round two, on the fair-retry re-pin `c9f3d4a2`, passed **6,728 tests** per full suite,
zero failures/errors/skips: UTC **317.32 s**, Asia/Singapore **313.58 s**, with warnings
as errors and eight workers. The affected tier, Ruff, job audit, static schedule and
registration identity also pass. Focused action/repair tests pass 54 cases; all 18
focused P15/E1/sector/XS identity cases pass. Only docs/metrics follow this tested source.

At the 2026-11-12 capacity/retry source, both full suites passed **6,717 tests**, zero
failures/errors/skips: UTC **316.97 s**, Asia/Singapore **306.79 s**, warnings as errors,
eight workers per suite. The affected tier, Ruff, job audit (22 jobs, no differences),
static schedule check and registration identity pass; all 18 focused P15/runtime checks pass.
Only documentation and metrics follow the rehearsed/fully tested source `195689ab`.

Current deploy pre-flights (2026-11-12; refresh live state in the window):

| Pre-flight | Today's state |
|---|---|
| 1 — main contains r21; suites/lint green | Prepared branch green; merge into main remains for the orchestrator. This lane did not push or merge main. |
| 2 — job/static schedule contracts | PASS. Live `/meta`'s dated 12:08:59 schedule receipt still flags `confirm-287.timer` as not enabled; refresh the host's closed-confirmation inventory/receipt in the window. |
| 3 — 70 GiB + 3× primary including WAL | PASS at 12:52:44 UTC: 132,133,576,704 bytes free (123.0590 GiB), required 132,101,214,208 (123.0288 GiB). The exact guard passes; remeasure before deployment. |
| 4 — permitted, quiescent window | Pending orchestrator verification. The November 13 window is 05:45–07:30 UTC, conditional on actual producer/private-reader/queue absence; the next window is Saturday. Keep the exclusion and 45-minute rules above. |
| 5 — fresh verified off-host backup | November 12 audit cites the 05:40:43 restore-and-push receipt; this lane did not independently retrieve or restore off-host bytes. Verify freshness in the window. |
| 6 — consumers | New reduced-generation T4 rehearsal PASS; live-287 audit supports compatibility; confirmation timer directly reads disabled/inactive. Repeat window imports, consumer scan and first-generation reader proof before release. |
| 7 — migration pre-image | Earlier catalog audit passed; today's six-ETF live repair is already applied. A fresh post-quiescence pre-image receipt is mandatory. |
| 8 — five NOT NULL columns | Earlier November 12 read-only counts were all zero. Recheck in the same window before backup/migration. |

At the 2026-11-11 integrated source, both full suites passed with **6,700 tests**, zero failures
and zero skips: UTC **270.42 s**; Asia/Singapore **272.77 s**, with warnings treated as errors
and eight workers per suite. The affected-test tier, `ruff check .`, job-contract audit
(`status: ok`, 22 jobs, no differences), static schedule check and registration identity all
pass. The static check retains the disclosed P15-scoring restart-loop exception below.
The earlier 2026-10-30 source passed 6,525 tests (UTC 259.22 s; Asia/Singapore 267.05 s).
Run the release checks from `r21/integrate`:

```bash
set -euo pipefail
TZ=UTC REGISTRATION_BASE_REF=origin/main nice -n 10 .venv/bin/python -m pytest -q -W error -n 8 -p no:cacheprovider
TZ=Asia/Singapore REGISTRATION_BASE_REF=origin/main nice -n 10 .venv/bin/python -m pytest -q -W error -n 8 -p no:cacheprovider
.venv/bin/python -m tools.registration_identity --base origin/main
.venv/bin/python -m tools.deploy_gate --check . --base origin/main
.venv/bin/python -m tools.schedule_contract_check --static
git diff --exit-code origin/main -- sim/execution.py sim/nyse.py
```

Registration identity passes for its one registration that pins code. The static schedule check passes with the
existing disclosed P15-scoring restart-loop exception. The final diff leaves both trial-375 simulator files and
the model client byte-identical to main. `engine/verify_prices.py` now includes the admitted ETF
fallback and is registered in revision 21; confirmation 287 stays closed with its frozen
verifier pin preserved. No frozen trial-375 simulator source moved.

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
counts and logical hashes, using identical explicit column order for rebuilt tables (`SELECT *` changes its hash
when baseline column order is restored), migrate and refresh the three frozen runtime records, then publish from the working
copy. Delete the verified generation and working store before restoring the original pre-image for the rollback
check. Validate the restored bytes, catalog and frozen records under the previous main code, then delete the copy.
Run at niceness 10, with at most four DuckDB threads and at most 8 GB memory; this rehearsal uses 4 GB.

## Round-two fair-retry reduced rehearsal (2026-11-12)

Re-ran the same reduced harness against `c9f3d4a2`, after the weekday rotation and 60-day
horizon re-pin. The original immutable pre-image and real reduced rows are the same as the
capacity rehearsal below. Migration ids 0 and 1 pass with catalog `7286ea9b…`.
Publication `market-20261112T124829071883Z.duckdb` carries schema-2 and schema-1 compatibility;
hot bytes 9,187,328; two cold parts totaling 2,810,571 bytes. The unchanged T4 reader accepts
60 November 11 rows, 59 complete feature histories and 60 outcome rows. The exact opened
hot-file and every generation file verify; stale/future publications refuse as before.
Minimum sampled /data00 free is 131,979,583,488 bytes (122.9156 GiB), across 376 samples.
All reserve guards pass. The sandbox and its databases, generation and cohort were removed.
This reduced reader/publication proof does not replace the whole-store deploy-window gates.

## Revision-21 capacity/retry reduced rehearsal (2026-11-12)

Re-ran the cited reduced-copy harness against `195689ab` (the complete new source and P15 pin).
Only its output/sandbox directory changed to the capacity lane. The immutable published pre-image
was `market-20261112T100325108641Z.duckdb`, 18,979,762,176 bytes, hashed against its manifest.
The new generation's catalog is current (`7286ea9b…`, migrations 0 and 1). The reduced store
has 22,736 real prices, 12,897 universe rows, 1,000 facts and 1,000 receipts; no recent intraday rows.
Seventeen matching current cohort files were copied verbatim. No source bar or evidence was invented.

Publication `market-20261112T122209531952Z.duckdb` carries schema-2 generation and schema-1
compatibility fields; hot bytes 9,187,328, two cold parts totaling 2,810,571 bytes. The unchanged T4
reader accepted 60 latest-session rows for November 11, 59 complete 253-session feature histories
and 60 outcome rows. The exact opened hot-file hash and every generation file verified; stale
and future cases still refused. Confirmation's preserved refusal diagnostics were exercised only
as read functions; its closed epoch runner was not invoked. Minimum sampled /data00 free space
was 116,909,240,320 bytes (108.8802 GiB), across 566 samples. Every copy/publication reserve
check passed. The disposable checkout, store, generation and parts were deleted after verification.

This is a reduced publication/reader rehearsal. It does not certify the whole live store's backup,
migration, forward-record refresh or rollback; those remain deploy-window gates.

## Historical revision-21 unblock rehearsal results (2026-11-11)

A full copy could not retain 70 GiB free: the published pre-image alone is 17.6763 GiB, against
about 8.4 GiB above the reserve. This was a **reduced-copy publication and reader rehearsal**,
not another full-store backup/migration/rollback or a full signal run. No SEC/model request,
relay, private-state write, live-store write, service action or deployment was performed.

The disposable checkout was a shared clone of the exact re-pinned integration source. The
original `market-20261111T030856677108Z.duckdb` was resolved once, opened read-only and its
18,979,762,176 bytes hashed against its schema-1 publication manifest. The sandbox bootstrapped
the current empty schema through migrations 0 and 1, then copied real prices for the reader's
59-name universe from 2025-05-09 through 2026-11-10, the real universe table, and bounded real
recent cold-table slices. Other tables remained empty. Seventeen current publication cohort
files, including the Friday-postflight artifact, were copied verbatim; they do not make this
reduced store a full evidence/forward-record replay. No evidence row was invented.

Rehearsal commands (the session's retained `rehearse.py` harness performs the steps above):

```bash
df -B1 /data00
git clone --quiet --shared --branch r21/integrate . "$P21_REHEARSAL_OUT/sandbox"
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
TRADING_ENGINE_DUCKDB_THREADS=4 TRADING_ENGINE_DUCKDB_MEMORY=4GB \
nice -n 10 .venv/bin/python "$P21_REHEARSAL_OUT/rehearse.py"
```

The harness runs `df -B1` and the unmodified reserve guard before each copy/publication, caps
extraction spill at 256 MiB, bounds the extraction/publication working set, samples free space,
and calls the unmodified imported `Snapshot`, `features`, `outcomes` and r21 pin interfaces.

| Output | Result |
|---|---|
| `SCHEMA` | `status: applied`, ids `[0, 1]`, current baseline catalog |
| `REDUCED_COPY` | 31,469,568 bytes; 22,732 prices, 12,892 universe rows, 1,000 facts, 1,000 receipts; no recent intraday rows available |
| `PUBLICATION` | `market-20261111T055102316287Z.duckdb`; `manifest_schema_version: 2`, `schema_version: 1`; hot 9,187,328 bytes; two cold parts, 2,971,218 bytes |
| `T4_ACCEPTED` | `hash_verified: true`, `freshness_verified: true`; latest session `2026-11-10`, 59 rows; 59 complete 253-session feature histories and 59 outcome rows |
| `T4_REFUSAL` | Both stale and future publications still refuse: `stale snapshot or publication from the future` |
| `GENERATION_ACCEPTED` | All referenced files byte-verified; two cold parts; schema-2 pin retained |
| Historical `CONFIRM_287_REFUSES` (confirmation now closed) | `the published engine snapshot is a manifest-schema-2 generation; this runner reads only the single-file schema-1 snapshot. Move it to engine.lib.snapshots.pin_latest_generation before the epoch runs` |
| Historical `CONFIRM_287_DEPENDENCY_REFUSES` (no amendment allowed) | `the frozen Nasdaq client changed: engine/verify_prices.py hashes` the integrated ETF client; `a new pin needs a disclosed pre-epoch dependency amendment` |
| `RESOURCES` | Minimum sampled free space 84,028,370,944 bytes (78.2575 GiB), 462 samples; all copy guards passed |
| Cleanup | Sandbox checkout, database, generations, cold parts and copied cohort removed; only text/code receipts retained |

## Revision-21 rehearsal results (2026-10-30)

Published pre-image: `market-20261030T133829129357Z.duckdb`, 16,529,502,208 bytes, matched its published
manifest. All work ran on disposable copies at niceness 10, four DuckDB threads and 4 GB memory.

| Step | Result |
|---|---|
| Backup create / explicit verify | 1,049.69 s / 278.97 s; both `ok`; full backup deleted immediately after verify |
| Migration | 538.53 s including mandatory recovery verification; schema id 1; recovery copy deleted immediately |
| Catalog before / after | `865f64aad4529c6f2cde3d0fb72d7b70dd968b85f49905681db1aef825d59a65` → `7286ea9b55c05d1bb16af2f2faeeb6aa69b1d5f711e1219efb2d5c27709a2e5d` |
| Original rows | 107/107 original table row counts and logical contents equal; three reordered tables compared in the same explicit column order; full comparison 260.25 s |
| Frozen contracts | E1, sector and XS migration plus normal refresh 2.95 s; all valid under revision-21 digests, unchanged versions |
| Publication | 1,068.73 s; capture/writer-lock window 136.11 s; verified 52,556,137 cold rows; hot database 4,296,552,448 bytes and cold parts 2,001,894,492 bytes |
| Rollback | 583.86 s including 234.33 s copy and full backup verification; byte-identical pre-image; original catalog; previous-main E1, sector and XS valid under deployed digests; restored copy deleted |
| Resources | Peak RSS 5,273,744 KiB; peak owned files 48,974,019,955 bytes; at most two store-sized files; minimum sampled free space 83,029,819,392 bytes |

The temporary generation and working store were deleted as soon as publication returned its verified manifest.
Current free space after deleting every disposable database and generation: 126,165,762,048 bytes.

Harness corrections were isolated to disposable-copy setup: supply the required Friday-postflight metadata, use
canonical paths and owner-only recovery files, compare rebuilt rows by explicit column order, and inspect the
library publication manifest rather than the CLI's `status` field. No source change or weakened gate was needed.
The create/verify, migration/equality/publication and rollback receipts use the same immutable published pre-image.

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
