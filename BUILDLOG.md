# BUILDLOG — trading-engine

Source of truth for build state. Read at the start of every loop iteration; trust this over
remembered state. Specs live in `../personal-data-store/trading/` (engine design §12 wins on
conflict; execution design §7 has exit criteria).

## Current phase: M3/M4 — league go-live + nightly wiring, M3 exit demo, experiment framework

## Phase exits stamped

- **M0 — DONE 2026-07-18.** Criterion: `_meta.json` shows a clean nightly run over ~4k+ names,
  from cron, max-history backfill done. Evidence: cron run of 2026-07-17 22:30 UTC completed
  clean — `logs/cron.log` ends `=== done 2026-07-17T22:34:09Z ===`; `_meta.json`
  `last_run 2026-07-17T22:34:06Z`, mode incremental, liquid_count 4,118, prices_rows 19.8M,
  failed_this_run 3 (honest), screen 642 passing / 3,880 screened; sync commit `356c7af`
  authored 22:34:09 +0000 (inside the cron window, no human involvement). Backfill was
  stamped done 2026-07-16 (4,121 names, 19.8M rows).
- **M3 — DONE 2026-07-18.** Criterion: a discretionary paper trade goes end-to-end through the
  UI's risk gates. Evidence: on the REAL store DB, backend (:8000) + Next UI (:3000) running,
  submitted through the UI's own `/api` proxy (the exact route the ticket form posts to):
  (1) stopless DELL ticket → rejected, 5 gates fail honestly; (2) DELL 39sh @ entry 397 /
  stop 387 / target 417 → rejected by `playbook_named` (`experiment` setups capped at 0.25%
  risk $98 < $390) — a real rules.md cap enforced; (3) DELL 9sh ($90 risk) → **allowed:true,
  ticket 3, pending sim_order 42** in the `discretionary` book (auto-created), all 8 gates
  pass/ack, audit + journal rows verified via the API. No same-bar fill — order fills at
  Monday 2026-07-20's open in the nightly league step (correct per exec-design §2). Caveat:
  submission was via the UI's proxy route, not a hand-clicked browser; pages were previously
  verified SSR-rendering the same flow.
- **M4 — DONE 2026-07-18.** Criterion: first pre-registered experiment report published +
  intraday archive accumulating under the disk watchdog. Evidence: E1 SPY-Monday report
  committed at `data/reports/experiments/e1-spy-monday.md` (`9568cec`; pre-registered config,
  locked holdout, honest negative in-sample result); intraday archive at 2 consecutive real
  daily pulls (2026-07-17: 2.40M 1m + 4.67M 5m rows; 2026-07-18: +448,716 1m + +492,011 5m,
  1078/1078 tickers, 0 failures) behind the §12.7 queue guards incl. the disk watchdog
  (store 1.65 GiB vs 60/80 GB caps). Fundamentals/earnings miners built + scheduled
  (earnings nightly, fundamentals Fridays, `ac9fa72`); first real full runs in flight
  2026-07-18 (jobs 7+8).

## Environment truth (verified 2026-07-16, from this devbox)

| Source / tool | Status | Evidence |
|---|---|---|
| Stooq | **BLOCKED** — returns JS anti-bot challenge page (HTTP 200 but HTML, not CSV) | `curl stooq.com/q/d/l/?s=spy.us&i=d` → `<!DOCTYPE html>… crypto.subtle.digest` PoW page |
| yfinance | **WORKS** — primary EOD source | SPY `period=max` → 8,421 rows (1993-01-29 → 2026-07-15); batch `yf.download` 4 tickers OK |
| Nasdaq Trader symbol directory | **WORKS over HTTPS** with browser User-Agent + `--retry 3`; plain curl truncates mid-file | full file = 13,055 lines ending `File Creation Time:` footer — always verify footer |
| FTP (ftp.nasdaqtrader.com) | **BLOCKED** (timeout) | curl ftp:// hung >120s |
| PyPI via uv | **WORKS** — no TLS interception problems | `uv pip install duckdb pandas yfinance …` clean |
| uv + Python 3.12 | Installed: uv 0.11.29 → `~/.local/bin`, CPython 3.12.13; system python is 3.7 (never use) | `.venv` created at repo root |
| gh CLI | **NOT AVAILABLE** — `/usr/local/bin/gh` is a corp tool (`galaxy_selector.py`), not GitHub CLI | repo is **local-only** for now; store's remote proves GitHub SSH (`ssh://git@ssh.github.com:443`) works, so a remote can be added once the owner creates the GitHub repo |
| Disk | Repo lives on `/data00` — **411 GB free** (root `/` has 99 GB free) | `df -h` 2026-07-16 |
| Box | 32 cores, 62 GB RAM confirmed | `nproc`, `free -g` |
| Node.js | Not installed, but nodejs.org tarball (HTTP 200) + registry.npmjs.org (HTTP 200) both reachable — install user-space at M3 | curl checks 2026-07-16 |

## Done

- 2026-07-16 · Environment truth pass (table above). Stooq contingency triggered → yfinance is primary.
- 2026-07-16 · Repo scaffolded at `/data00/home/jun.ong/trading-engine` (git init, local-only), `.venv` with Python 3.12 + deps.
- 2026-07-16 · **M0 code built & verified** (Opus subagent wrote, main loop verified end-to-end):
  `lib/db.py` (schema: prices/universe/universe_snapshot/screen_results/jobs),
  `universe.py` (13,053 parsed → 12,209 kept incl. 5,549 ETFs; append-only snapshot),
  `collect.py` (--bootstrap-floor / --backfill resumable / incremental calendar-gated),
  `run_daily.sh`. Smoke: 300-name floor pass → 98 liquid, 2 failed (honest); 20-name
  backfill → history to 1962; AAPL 2026-07-15 close 327.50 cross-checked vs independent pull.
- 2026-07-16 · Full-universe `--bootstrap-floor` **done**: active=12,209 · priced=12,105 · **liquid=4,118** · failed=106 (dead tickers, honest). 785k price rows.
- 2026-07-16 · Full `--backfill` (max history, 4,118 liquid names) **running** (nice 19, logs/backfill-2026-07-16.log; resumable — if interrupted just rerun `collect.py --backfill`).
- 2026-07-16 · **M1 code committed** (screen.py, sync.py, run_daily.sh wired). Proven on a 37-name real-bar fixture incl. independent math recheck (zero diff) + append-only/--rerun/new_today diff tests. Full-DB verification queued behind backfill. Post-backfill TODO: retry stragglers (`collect.py --backfill` again — resumable), then real screen run.

## Decisions

- 2026-07-16 · **yfinance is the primary EOD source** (Stooq blocked from this network — spec §3 contingency). `source` column = 'yfinance'.
- 2026-07-16 · **Universe list via HTTPS nasdaqtraded.txt** with browser UA + retries; completeness check = `File Creation Time:` footer present, else retry/keep last good file. FTP unusable.
- 2026-07-16 · **Repo local-only** (no GitHub CLI on box). M1's sync exit criterion needs a remote — flag to owner before M1 completes: create `ong6/trading-engine` on GitHub and we'll add the SSH remote.
- 2026-07-16 · Owner directive: **Fable plans, Opus subagents write code** (token efficiency). Verification still done by running end-to-end in the main loop.
- 2026-07-16 · Backfill is a **resumable job** in a minimal DuckDB `jobs` table from day one (§12.7: no ad-hoc pools; backfill of ~5k names must survive interruption).
- 2026-07-16 · **Cron at 22:30 UTC year-round** (box is UTC; = 6:30pm ET summer / 5:30pm ET winter, both post-close for yfinance; calendar gate handles holidays). **Install cron only after backfill completes** — DuckDB is single-writer, a cron collect during backfill would collide.
- 2026-07-16 · Universe kept at 12,209 (incl. 5,549 ETFs) — spec keeps ETFs explicitly; the liquidity floor is the real boundary (~4-6k expected liquid).
- 2026-07-16 · tmux not installed on box — loop continuity is via the agent scheduler instead; noted, not blocking.

- 2026-07-16 · **Backfill 100% done**: 4,121 liquid names (incl. HAL via bounded start-date workaround for a yfinance period=max glitch), 19.8M rows, 1.2 GB store/. 3 retry passes; remaining failures = 0.
- 2026-07-16 · **First full-DB screen**: 3,879 screened (239 short-history skipped honestly) → 629 passing, regime risk-on, 2.8s runtime. Output shape/values sane (leveraged AMD ETFs + hot small caps at RS 99; DELL 98 tight base). 111 eod/ files.
- 2026-07-16 · **Incremental collect proven on real DB**: 4,113/4,118 with data, 5 failed, 3.3 min.
- 2026-07-16 · **Cron installed**: `30 22 * * 1-5 run_daily.sh >> logs/cron.log` (weekdays; calendar gate handles holidays). Tonight's 22:30 UTC run = M0 exit-criterion candidate.

- 2026-07-16 · **M2 code committed** (sim/: fills, portfolio, league, 10 strategies + configs). Shakedown on DB copy: 15 sessions, 267 fills, fill model verified vs exec-design §2 (3 hand-checks by builder + 1 independent random recheck; 0 same-bar fills; liquidity guard rejects oversize). Not wired into run_daily.sh yet. Live league tables get created in the real DB by `league.py --init` at go-live; shakedown artifacts were NOT committed.
- 2026-07-16 · M2 open items: regime-gate entry-block never exercised in a live risk-off window yet (unit-tested only); partial fills not modeled (oversize = reject, documented).

- 2026-07-17 · **Cron run of 2026-07-16 22:30 UTC FAILED** — `run_daily.sh: Permission denied`.
  Root cause: script was committed mode 100644 (no exec bit); earlier manual proofs ran it via
  `bash run_daily.sh`, masking it. Fix: `chmod +x` (git mode → 100755). **Recovery run executed
  via cron's exact invocation** (`/bin/sh -c '…/run_daily.sh >> logs/cron.log 2>&1'`), exit 0:
  incremental collect 4,115/4,118 (3 failed, honest) in ~4 min; screen 2026-07-16 → 651 passing /
  3,880 screened, regime risk-on; sync committed (`27302b3`). `_meta.json` updated. Missed
  2026-07-16 bars fully recovered. **M0 exit NOT stamped** — criterion requires the run to come
  *from cron*; tonight's 22:30 UTC run is the new candidate.
- 2026-07-17 · Found **uncommitted M3 work** in tree, not previously logged: `server/` (FastAPI
  backend — localhost-only dashboard + gated discretionary tickets that become pending sim_orders;
  never fills or steps the league), `sim/schema.py` M3 tables (disc_tickets / audit_log /
  review_markers), fastapi+uvicorn in requirements. Left **uncommitted** — unverified, and
  commit-after-proof is the rule. Verify end-to-end in a later iteration (after M0/M1), then commit.
- 2026-07-17 · **M3 backend verified end-to-end on a DB copy and committed** (`97b3d48`). Uvicorn
  against a copy via `TRADING_ENGINE_DB`; exercised: /health /meta /screen/latest /candidates/DELL
  /league /positions /orders /journal; gate rejections (no stop · R:R 1.0 · oversize qty 9999 vs
  1%-max 39 · earnings unacked) each rejected with the right gate + honest detail; accept path
  (DELL 30sh, entry 392 / stop 382 / target 412, R:R 2.0) → ticket `submitted` + **pending**
  sim_orders row + audit row, no fill (fills stay with the nightly step); cancel flow + double-cancel
  + missing-ticket errors correct; **write-lock test: POST → HTTP 503** with clear message while a
  RW connection held the DB, clean recovery after release; /review-done writes the circuit-breaker
  marker. Sizing/R:R/4R-budget rechecked by hand (equity $39,000 → 1R $390, max 39sh, 4R $1,560).
  All 8 gates match the exec-design §4 / rules.md table. Gates are **long-only** by design in v1
  (shorts rejected; sells = closes).
- 2026-07-17 · M3 open items: **Next.js UI not built** (M3 exit needs the trade through the *UI's*
  gates — install Node user-space first); `/candidates` returns bars + latest close but no
  server-side sizing prefill — UI computes it (needs equity; expose via /league or add a
  sizing-suggest endpoint when building the ticket page).
- 2026-07-17 · **Node.js 24.18.0 LTS installed user-space** at `/data00/home/jun.ong/tools/node`
  (npm 11.16.0; not on default PATH — scripts export it). npm registry reachable.
- 2026-07-17 · **M3 UI built & committed** (`5e7e2fa`; Opus subagent wrote, verified end-to-end twice —
  builder pass + independent main-loop pass, both on DB copies). Next 16 App Router in `ui/`,
  Next+React only, inline-SVG charts, system fonts (offline-clean), `/api/*` → `127.0.0.1:8000`
  rewrite proxy. Pages: dashboard / league / candidates/[ticker] (ticket form, client-side 1%-risk
  prefill from discretionary `/league` equity, full 8-gate checklist rendered on accept AND reject) /
  positions (+cancel) / journal (+review-done). Evidence: all pages SSR 200 with MOCK banner + real
  screen data; via the UI's own proxy: DELL ticket submit → `allowed:true` + 8 gates → pending order
  → cancel OK; `npm run build` clean. `ui/node_modules` gitignored.
- 2026-07-17 · **Backend defect found during UI build** (not fixed yet): on a DB where sim tables
  don't exist (fresh store — league never initialized), `GET /league` and `GET /journal` return
  **HTTP 500** (they read sim tables unguarded; `/orders` guards with `_table_exists`). UI shows an
  honest "Could not load data" state so nothing crashes, but the backend should guard → next
  iteration: add `_table_exists` guards (empty-state JSON) to `/league`, `/league/{id}/equity`,
  `/journal`, then re-verify. Matters for the real store DB, which has no sim tables until league
  go-live.

- 2026-07-17 · **Fresh-DB 500s fixed & verified** (`4bcdfc5`; Sonnet subagent wrote, verified by it +
  an independent main-loop pass on schema-less copies of the real DB). `/league`,
  `/league/{id}/equity`, `/positions`, `/journal` guarded with `_table_exists`; also caught that
  `/orders` guarded `disc_tickets` but not `sim_orders` itself. All five now 200 with honest empty
  shapes pre-league-init; regression confirmed (ticket POST → journal/orders non-empty). GETs stay
  read-only — no schema creation.

- 2026-07-17 · **M4 foundation built & first real intraday pull done** (`e99c992`; Opus subagent
  wrote + verified on a copy, main loop ran the real pull). `queue_runner.py` (§12.7: sequential
  drain of the jobs table behind nice19/ionice/load/RAM/disk guards; dispatch-table seam for farm
  job types), `intraday.py` (1m/7d + 5m/60d, top-500 dollar-volume ∪ screen passers ∪ SPY/QQQ/IWM,
  append-only anti-join), `lib/resources.py` (guards + merge-don't-clobber _meta writer). Real run:
  **1088/1088 tickers, 2.40M 1m + 4.67M 5m rows, 0 failures, store 1.31GiB**, `intraday` block in
  _meta.json, job 5 `done` in queue. Idempotence + independent cross-check (ABT, diff 0.0) proven
  on the copy. yfinance quirks logged: 5m first pulls can be partial (append-only converges);
  occasional spurious "delisted" on 5m for valid names (counted as gaps, retried once).
- 2026-07-17 · Decision: intraday universe = top-500 by 20d median dollar volume ∪ latest screen
  passers ∪ {SPY,QQQ,IWM} (resolves to ~1.1k names). Store watchlist names come via screen passers;
  no store coupling. NOT in run_daily.sh yet — wiring after tonight's M0 stamp (cron must stay
  byte-identical).

- 2026-07-18 · **M4 backtest-farm framework built + E1 published** (`9568cec`; Opus subagent wrote +
  verified, real SPY data). `farm/experiment.py` (pre-registered YAML configs, SHA-256 config-hash
  immutability — mutated config under same id is refused, verified; RO price reads, brief RW append
  with lock-retry + `farm/pending-results/` fallback; in-sample vs locked-12-month-holdout split,
  holdout computed exactly once; append-only `experiment_results` table + report to
  `data/reports/experiments/<id>.md`), `farm/stats.py` (t-stat, annualized + Deflated Sharpe per
  Bailey–López de Prado 2014, CAGR, max DD).
- 2026-07-18 · **E1 SPY-Monday result: honest NEGATIVE (in-sample).** 1,583 Mondays 1993→2026-07-13.
  In-sample (1,534): gross +0.88%/yr vs registered +10% prior (0.09×), net −0.55%/yr @3bp r/t,
  t −0.28, deflated Sharpe 0.070; at the sim model's conservative 20bp r/t, −8.23%/yr. Monday
  effect decayed (strong 1990–94, negative 2000s–2010s, positive 2020–24 t=2.03). Holdout
  (49 Mondays, computed once, labeled separately): net +6.77%/yr, t 1.66. Forward kill criterion
  stands as registered (40 OOS Mondays, mean ≤ 0 or t < 0.5). 3 hand-checked trades matched
  independent SQL exactly; partitions disjoint (1,534 + 49 = 1,583, overlap 0).
- 2026-07-18 · **M4 miners built** (`456f184`; Opus subagent wrote + verified on a store copy):
  `engine/fundamentals.py` (weekly, full liquid universe incl. ETFs with NULL-honest equity fields,
  append-only point-in-time `fundamentals` keyed (ticker, as_of), ~70–80 min full pass at 0.4s/name
  polite rate) and `engine/earnings.py` (daily, universe = fundamentals-covered equities ∪ latest
  screen passers, fallback liquid non-ETF; `Ticker.calendar` next-date(s) with `is_estimate`;
  append-only `earnings_calendar` keyed (ticker, earnings_date, as_of), ~50–70 min/day). Proof:
  30-name real pulls, 3 fundamentals spot-checks matched an independent second pull (incl. JPM's
  honest NULL EV/EBITDA), AAPL 07-30 / MSFT 07-29 earnings confirmed independently, same-day
  re-runs insert 0. Schema helpers in `lib/db.py::init_mining_schema`.
- 2026-07-18 · **All three new job types registered in the queue dispatch** (`0e72889`, main loop):
  `fundamentals` (archive, 2000 MB) · `earnings` (archive, 1000 MB) · `experiment` (non-archive,
  2000 MB) beside `intraday`; all four loaders verified to resolve. Enqueue:
  `queue_runner.py --enqueue fundamentals` (weekly) / `--enqueue earnings` (daily) /
  `--enqueue experiment --params '{"id":"..."}'`.
- 2026-07-18 · M4 open items: `lxml` not installed → `get_earnings_dates` (historical earnings +
  surprises for event studies) unavailable; `.calendar` next-date path is sufficient for the risk
  gate. No historical regime data in `screen_results` (starts 2026-07-15) — E1 computed regime from
  SPY vs 200d SMA (no look-ahead), revisit as forward history accumulates. Earnings/fundamentals
  not yet scheduled (needs enqueue lines in the nightly/weekly driver — pending after league wiring
  lands).

- 2026-07-18 · **Nightly fully wired & league LIVE on the real DB** (`8ae3937`, `2ad119c`,
  `7fe40e7`; Opus subagent wrote + verified on copies, then live). Order: collect →
  `screen --skip-if-done` → `sim.league --init --skip-if-done` (writes league.md/csv) → sync →
  farm subshell (enqueue + drain, pinned exit 0 so farm failures log WARN but never fail the
  nightly). League go-live: **10 portfolios, session 2026-07-17, 41 pending orders, 0 fills**
  (first fills Monday — no same-bar). Fill model re-verified on a 2-day historical copy run:
  6 fills reconcile exactly across 3 slippage tiers (15bp/10bp/20bp by mdv), 0 same-bar.
  Full `run_daily.sh` proven exit 0 via cron's exact `/bin/sh -c` form; real intraday pull
  1078/1078, 0 failures.
- 2026-07-18 · **Defect found + fixed by wiring** (`2ad119c`): `screen.py` exit-1'd on an
  already-screened date — every weekend/holiday weekday cron would have failed the nightly.
  Now `--skip-if-done` no-ops at exit 0 (matches collect.py); real failures still exit 1.
- 2026-07-18 · Decisions: league runs `--init` every nightly (idempotent, self-healing);
  monthly sleeves (dual_momentum×2, ew_benchmark) correctly generated 0 orders at a
  non-month-end go-live; farm `_meta.json` intraday accounting lands in the NEXT run's sync
  commit by design (add a post-farm sync later if a same-night commit is wanted).
- 2026-07-18 · **Miners scheduled in the nightly** (`ac9fa72`): earnings enqueued daily
  (prio 110), fundamentals Fridays (prio 120), after intraday (prio 100; queue drains
  ascending). Bootstrap first real runs enqueued fundamentals-before-earnings (jobs 7+8) so
  the earnings universe can use fundamentals coverage; drain running in background
  (`logs/miners-bootstrap-2026-07-18.log`). Until it lands, the earnings gate honestly
  reports "no earnings data — check manually" (observed in the M3 demo, ack flow works).
- 2026-07-18 · Interactive loop left RUNNING for the owner: FastAPI :8000 + Next dev :3000
  (loopback; `logs/server.log`, `logs/ui.log`). Note: while a queue job holds the DuckDB
  writer lock, UI reads/POSTs degrade honestly (503 / "Could not load data") — single-writer
  by design.

## Next

1. **Verify the miners bootstrap** (background drain, `logs/miners-bootstrap-2026-07-18.log`):
   `fundamentals` rows ≈ liquid universe, `earnings_calendar` populated, `_meta.json` blocks
   merged; then confirm the earnings gate reads real data on a fresh ticket check.
2. **Monday 2026-07-20 22:30 UTC cron = first full unattended nightly with everything wired**:
   collect → screen → league step (fills the 41 auto orders + discretionary DELL order 42 at
   Monday's open, conservative slippage) → sync → intraday + earnings mining. Verify Tuesday:
   fills present, league.md shows real equity moves, no WARN in the farm section.
3. **Mission "Done" gate**: 7 consecutive clean unattended nightly runs (counting from Monday
   2026-07-20 if clean). Watch `logs/cron.log` daily; any failure resets the count.
4. **M1 exit** still needs the GitHub remote (owner action: create `ong6/trading-engine`, then
   `git remote add origin ssh://git@ssh.github.com:443/ong6/trading-engine.git`; sync.py
   pushes automatically once a remote exists; then prove a pull on another machine).
5. Nice-to-haves surfaced this session (not blocking): `lxml` for historical earnings
   surprises; post-farm second sync if a same-night intraday `_meta` commit is wanted;
   walk-forward re-validation job type for active league strategies (weekly, §12.3);
   weekly-review integration (exec-design §6 Sunday loop) once a week of league history exists.

## Blockers

- None hard. Soft: GitHub remote needed before M1 exit (owner action — create the repo).
