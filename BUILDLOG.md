# BUILDLOG — trading-engine

Source of truth for build state. Read at the start of every loop iteration; trust this over
remembered state. Specs live in `../personal-data-store/trading/` (engine design §12 wins on
conflict; execution design §7 has exit criteria).

## Current phase: post-Done — §12.3 utilization build-out (walk-forward DONE 2026-08-04; sweeps open) + M1 remote pending

## Phase exits stamped

- **Mission Done gate (7 consecutive clean unattended nightlies) — DONE 2026-08-04.**
  Criterion: 7 consecutive clean unattended nightly runs, counting from Fri 2026-07-24
  (post-incident reset). Evidence: `logs/run-2026-07-{24,27,28,29,30,31}.log` +
  `logs/run-2026-08-03.log` — all 7 end `=== done … ===` with 0 FATAL/ERROR/Traceback;
  league.md advanced to 2026-08-03 (17 books); farm section `OK` each night; the two risk
  nights inside the streak both passed (07-28 six new books' first live signals; 07-31 first
  monthly-sleeve execution — dual_momentum vs real BIL hurdle +3.72%, sector_momentum,
  low_vol first signals — long night, done 2026-08-01T00:16:49Z, clean). E1's first
  unattended forward write confirmed on 08-03 (`+oos 2026-08-03`, 3/40 Mondays).
  **M1 remains the only open milestone** (needs owner-created GitHub remote).
  Stamped by the store-session agent (owner-directed review), not the build loop.

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
| gh CLI | **NOT AVAILABLE** — `/usr/local/bin/gh` is a corp tool (`<internal tool>`), not GitHub CLI | repo is **local-only** for now; store's remote proves GitHub SSH (`ssh://git@ssh.github.com:443`) works, so a remote can be added once the owner creates the GitHub repo |
| Disk | Repo lives on `/data00` — **411 GB free** (root `/` has 99 GB free) | `df -h` 2026-07-16 |
| Box | 32 cores, 62 GB RAM confirmed | `nproc`, `free -g` |
| Node.js | Not installed, but nodejs.org tarball (HTTP 200) + registry.npmjs.org (HTTP 200) both reachable — install user-space at M3 | curl checks 2026-07-16 |

## Done

- 2026-07-16 · Environment truth pass (table above). Stooq contingency triggered → yfinance is primary.
- 2026-07-16 · Repo scaffolded at `~/trading-engine` (git init, local-only), `.venv` with Python 3.12 + deps.
- 2026-07-16 · **M0 code built & verified** (Opus subagent wrote, main loop verified end-to-end):
  `lib/db.py` (schema: prices/universe/universe_snapshot/screen_results/jobs),
  `universe.py` (13,053 parsed → 12,209 kept incl. 5,549 ETFs; append-only snapshot),
  `collect.py` (--bootstrap-floor / --backfill resumable / incremental calendar-gated),
  `run_daily.sh`. Smoke: 300-name floor pass → 98 liquid, 2 failed (honest); 20-name
  backfill → history to 1962; AAPL 2026-07-15 close 327.50 cross-checked vs independent pull.
- 2026-07-16 · Full-universe `--bootstrap-floor` **done**: active=12,209 · priced=12,105 · **liquid=4,118** · failed=106 (dead tickers, honest). 785k price rows.
- 2026-07-16 · Full `--backfill` (max history, 4,118 liquid names) **running** (nice 19, logs/backfill-2026-07-16.log; resumable — if interrupted just rerun `collect.py --backfill`).
- 2026-07-16 · **M1 code committed** (screen.py, sync.py, run_daily.sh wired). Proven on a 37-name real-bar fixture incl. independent math recheck (zero diff) + append-only/--rerun/new_today diff tests. Full-DB verification queued behind backfill. Post-backfill TODO: retry stragglers (`collect.py --backfill` again — resumable), then real screen run.
- 2026-08-04 · **News analyst built & proven end-to-end** (phase-4 `claude -p` cron row of
  trading-engine-design §10; spec: store `trading/trading-engine/news-analyst-design.md`).
  Zero-tool, wrapper-assembled: `engine/news_analyst.sh` (flock `.news-analyst.lock`, own
  `logs/news-analyst.log`) slices `~/news-scraper/data/news.jsonl` since the watermark in
  `data/news_analyst_state.json`, assembles ONE prompt from `engine/news_analyst_prompt.md`
  (standing instructions / output contract) + headlines + the store's `watchlist.md` and
  `market-context.md` + league open positions (read-only DuckDB), calls the CLI, and writes
  `data/reports/news/<date>.md` + `latest.md` (sync.py commits them with the nightly artifacts).
  **First real run 2026-08-04 08:03Z**: 133 headlines → a brief whose every number traced back
  to a verbatim headline on spot-check (BMY/AstraZeneca $400bn merger-talk report — BMY is
  genuinely held in book 1; Iran/oil, yen-intervention, semi/CXMT items against market-context).
  A second immediate run correctly logged "0 new headlines — no claude call, no brief" and left
  the watermark untouched. Failure posture: **news is non-critical**, every path logs a
  breadcrumb and exits 0, and the watermark advances ONLY after a brief is on disk, so a failed
  run's headlines are re-covered by the next one.
  - **`--bare` does not work and was dropped** (design assumed it from `--help` presence).
    Verified: `--bare` reads "strictly ANTHROPIC_API_KEY or apiKeyHelper … OAuth and keychain
    are never read", so on this box's subscription login every `--bare` call returns
    `is_error` + "Not logged in · Please run /login" in ~70ms. The properties it was chosen for
    are reproduced explicitly: `--settings '{"permissions":{"deny":[…]}}'` (tools removed —
    verified the model reports no Bash tool available), `--strict-mcp-config`,
    `--permission-mode dontAsk`, `--max-turns 1`, wrapped in `timeout 900`.
  - `jq` is **not installed** on this box; JSON is parsed with the venv python (the wrapper
    prefers jq if it ever appears).
  - DuckDB is single-writer and the farm can hold the lock through a long drain, so the
    positions read retries ~30s then degrades to a dated `data/news_positions_cache.json`
    snapshot rather than failing the run.
  - Cron (appended, existing nightly untouched): `0 11 * * 1-5` news analyst; plus the design's
    open scraper-persistence item — `@reboot` **and** hourly `17 * * * *`
    `~/news-scraper/ensure_scraper.sh`, an idempotent relaunch guard (PID-alive + cmdline check
    against PID reuse, own flock; the launched scraper gets `9>&-` so it does not inherit and
    hold the guard's lock for its whole life — caught in a sandbox test).

## Decisions

- 2026-07-16 · **yfinance is the primary EOD source** (Stooq blocked from this network — spec §3 contingency). `source` column = 'yfinance'.
- 2026-07-16 · **Universe list via HTTPS nasdaqtraded.txt** with browser UA + retries; completeness check = `File Creation Time:` footer present, else retry/keep last good file. FTP unusable.
- 2026-07-16 · **Repo local-only** (no GitHub CLI on box). M1's sync exit criterion needs a remote — flag to owner before M1 completes: create `ong6/trading-engine` on GitHub and we'll add the SSH remote.
- 2026-07-16 · Owner directive: **Fable plans, Opus subagents write code** (token efficiency). Verification still done by running end-to-end in the main loop.
- 2026-07-16 · Backfill is a **resumable job** in a minimal DuckDB `jobs` table from day one (§12.7: no ad-hoc pools; backfill of ~5k names must survive interruption).
- 2026-07-16 · **Cron at 22:30 UTC year-round** (box is UTC; = 6:30pm ET summer / 5:30pm ET winter, both post-close for yfinance; calendar gate handles holidays). **Install cron only after backfill completes** — DuckDB is single-writer, a cron collect during backfill would collide.
- 2026-07-16 · Universe kept at 12,209 (incl. 5,549 ETFs) — spec keeps ETFs explicitly; the liquidity floor is the real boundary (~4-6k expected liquid).
- 2026-07-16 · tmux not installed on box — loop continuity is via the agent scheduler instead; noted, not blocking.

- 2026-07-29 · **D3 — `prices` is a CACHE of Yahoo's split-adjusted view, not a point-in-time table.** Controlled, audited, watermarked restatement is how that cache stays internally coherent, and it is the ONLY internally consistent policy short of re-architecting collection: our stored history is already Yahoo-back-adjusted as of each row's fetch date, and every incremental re-fetch arrives restated, so there is no raw series to preserve. The professional alternative (QuantConnect LEAN / Quantopian — keep truly-raw prices append-only, derive an adjusted VIEW from cumulative factors) was considered and rejected for that reason. **The append-only guardrail is unchanged and still applies in full to every `as_of`-stamped point-in-time table** (screen_results, fundamentals, universe_snapshot, earnings_calendar, intraday_prices, and the new corporate_actions). Restatement writes an `audit_log` row and a `split_adjustments` watermark row, so it is exactly-once and fully traceable.
- 2026-07-29 · **D3b — the split's price boundary and its fill boundary are different, on purpose.** Prices are restated at the `break_date` located in the stored series (the nightly 5-day re-fetch restates the tail, so a late-spotted split's break sits at the refetch edge, not at the ex-date — restating `date < ex_date` would double-adjust). Fills are compensated at the `ex_date`, because a fill before the ex-date was economically executed at pre-split prices whatever the storage boundary turned out to be.
- 2026-07-29 · **D4 — `--rerun` rebuild semantics: state is a pure function of (sim_fills, sim_dividends).** `rebuild_state` replays both, ordered by date with dividends BEFORE fills within a date — exactly the live phase-a0-then-phase-a order, so `apply_fill`'s cash-bounded buy clamp sees an identical cash trajectory and never re-clamps a stored fill. Fills before an APPLIED split's ex-date replay at qty×ratio / px÷ratio (notional invariant). Dividends replay at their RECORDED amount: the cash was received at the share count of the day and a later split does not retroactively change what was paid.
- 2026-07-29 · **D6 — the actions FETCH is warn-and-continue, the RECONCILE is FATAL.** The fetch is a network call and a night with no fresh actions data is not a night with wrong data: the reconciler still adjudicates everything already stored, and the >40%-move tripwire is independent of the fetch. The reconcile is deliberately un-`||`-guarded under `set -e` — if it cannot run we do not know whether the price scale the league is about to trade on is coherent, and trading on a broken scale is strictly worse than skipping a night. A `skipped_sanity` verdict is NOT a failure: it is the designed never-guess outcome and surfaces as a TODO breadcrumb plus an audit_log row.

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
- 2026-07-17 · **Node.js 24.18.0 LTS installed user-space** at `~/tools/node`
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

- 2026-07-18 · **Hardening session (4 Opus reviewers → 4 Opus fixers, all findings verified
  behaviorally before commit)**. Reviews confirmed clean: fill honesty (next-open, slippage
  sign, liquidity cap, cash conservation), DSR math matches Bailey–LdP 2014 to 1e-12, miners
  resume/torn-row-safe, no price fabrication anywhere. Fixed (commits `a091272`..`fb95d64`):
  - queue_runner: reclaim stale `running` jobs at drain start (killed drain left job 7
    unresumable); dedup pending (kind,params) enqueues; refuse unknown job types.
  - run_daily: universe refresh non-fatal (was: transient Nasdaq hiccup aborts whole nightly
    — biggest threat to Monday); PYTHONUNBUFFERED for live logs.
  - screen: MIN_BARS 253 (exactly-252-bar names were silently unpassable); skip-if-done
    regenerates missing report files. intraday: universe CTE bounded to 40 days (was
    full-table scan). All date.today() → UTC date. Atomic _meta.json writes.
  - server: qty<=0 rejected with 400 (negative qty bypassed EVERY gate → accidental short);
    unknown playbooks capped at 0.25% (was only literal 'experiment'; library empty until
    owner vets setups — every named setup capped for now); pending unfilled tickets now count
    toward the 4R heat cap; **earnings_window gate implemented** (latest as_of per ticker,
    fail inside [today,+7d], ack clears fail+unknown, degrades to unknown on no data);
    ticket inserts transactional. Backend restarted on the new code.
  - sim: league.step is one transaction (no half-done day, no double-fill on rerun);
    pending-order dedup in generate_all; sells clamp to held qty, buys clamp to cash
    (floor-to-0 → rejected insufficient_cash); qty!=0 in MTM; median $vol excludes fill day;
    rebuild_state replays in live order so --rerun stays exact.
  - earnings: NaT no longer mislabels is_estimate; datetime64/string dates coerced not
    dropped; universe unions trailing-14d as_of (partial snapshot only adds names).
  - experiment: holdout **pinned at first registration** (sidecar lock.json + DB recovery)
    — was silently sliding forward with new data under a "computed once" banner.
  - lxml installed (yfinance parse speed).

- 2026-07-18 (pm) · **Miners bootstrap drain died silently ~11:20 UTC — diagnosed, resumed,
  completed.** The background drain (jobs 7+8) was killed mid-earnings (no traceback; SIGHUP
  from the launching SSH session dropping — no tmux on box), leaving job 8 stale-`running` +
  a leftover WAL. Fundamentals (job 7) had already finished: **4,118/4,118 tickers**, 0 failed
  (3,568 pulled this run + 550 prior, ETF equity fields NULL-honest). Restarted with `nohup`:
  the hardening pass's stale-job reclaim worked as designed (job 8 → pending, resumed at
  1,046 already-done). **Earnings complete 15:34 UTC: 2,768 tickers, 0 failures**, dates
  2026-04-22→2026-10-16, AAPL 07-30 / MSFT 07-29 match the earlier independent confirms;
  `_meta.json` fundamentals+earnings blocks merged. Lesson applied: long background jobs get
  `nohup` (or the agent-tracked background shell), never a bare `&` from an SSH session.
- 2026-07-18 (pm) · **Pre-Monday checks from the Next list all pass**: `screen.py
  --skip-if-done` and `sim.league --init --skip-if-done` both no-op exit 0 on the real DB
  (first post-transaction-rewrite exercise); API degrades honestly under the drain's writer
  lock (`/health` 200, `/league` 503 "database busy"); **earnings gate verified on real data
  both ways** via POST /tickets — AIR (earnings Tue 07-21, confirmed) → `earnings_window:
  fail` + rejected; DELL (earnings 09-03) → `earnings_window: pass "no earnings within 7d"`
  (rejected on a deliberate no-stop so no order side-effect; tickets 5+6 journaled).
- 2026-07-18 (pm) · **Monday-readiness review (independent Opus pass over the unattended-run
  seams) → 1 central defect + 3 risks, all fixed & verified (`32a3550`)**. Findings: nightly
  stages opened DuckDB RW with **no lock retry** (`lib/db.py`) while un-`||`-guarded under
  `set -e` — one in-flight UI request at 22:30 (servers are left running) or a prior night's
  still-draining farm would hard-abort the whole nightly (server→engine direction was
  protected via 503, engine→server was not); no cross-night overlap guard; no drain runtime
  bound; sync failure aborted the nightly (though league results were already DB-safe —
  reviewer confirmed fill flow SOLID: Monday's step fills all pending incl. weekend gap, no
  double-fill/skip of order 42, and found zero price-fabrication paths). Fixes: bounded
  lock-retry in `db.connect()` (TRADING_ENGINE_LOCK_WAIT_S, default 60s; **proven live
  against the real locked store during the drain** — honest retry lines then re-raise, and
  the retry→succeed path proven on a copy); `flock -n .nightly.lock` overlap guard in
  run_daily.sh (proven: second invocation aborts exit 1 before any stage); wall-clock drain
  budget in queue_runner (TRADING_ENGINE_DRAIN_BUDGET_S, default 4h — stops starting jobs,
  never kills in-flight; proven with budget=0 on a throwaway DB, job stays pending); sync
  now best-effort WARN in run_daily.sh + refuses to commit mid-rebase/merge; failure
  breadcrumb names the failing stage (via logs/.last_stage — tee block is a subshell).

- 2026-07-24 · **INCIDENT: all four unattended nightlies 07-20→07-23 failed at the league
  stage — diagnosed, fixed, fully replayed (`6febad5`, `71543f3`, data sync `24f85a9`).**
  Root cause: the `discretionary` book (auto-created by the M3 server with
  `strategy='discretionary'`) had no REGISTRY entry, so `generate_all` hit
  `KeyError: 'discretionary'` on Monday's first live step. Because the day-step is one
  transaction, each night's fills rolled back entirely (league frozen at 07-17, 42 orders
  stuck pending), and because league failed under `set -e`, **sync and the farm never ran
  all week** — 4 days of screens/eod sat uncommitted, intraday/earnings mining stalled at
  07-17/07-18. Never caught pre-Monday because every earlier league exercise predated the
  discretionary book or ran on copies without it.
  Fixes, both proven behaviorally on DB copies before touching the real store:
  (1) no-op `Discretionary` strategy registered — generates nothing (orders come only from
  UI tickets), fills/MTM already cover the book; (2) found an **uncommitted** ORDER BY/LIMIT
  rewrite of `portfolio.position_open_since` in the tree (unlogged — likely a dropped prior
  session) and verified its claim both ways: with the old filtered MIN/MAX, the 07-21 step
  dies on a DuckDB 1.5.4 internal assertion ("index 0 within vector of size 0" — aggregate
  over rows appended in the same transaction); with the rewrite all steps pass. Committed.
  Recovery: replayed 07-20/21/22/23 in order on the real DB — Mon 42 fills incl.
  discretionary DELL order 42 @ 400.69 (9sh), Tue +10 orders, Wed 10 fills, Thu 10 fills;
  sim_equity now 11 books × 4 new days; league.md/csv regenerated (books honestly red:
  top5 −9.8%, top10 −6.2%, SPY bench −1.3%, discretionary +0.9%). `sync.py` committed the
  156 stranded data files. Farm recovery: intraday + earnings enqueued (jobs 9, 10) and
  drained same day — 1m/7d window still covered the whole gap, nothing lost.
  Lesson: **a strategy-registry lookup is part of the unattended seam** — the Monday-readiness
  review checked locks/overlap/sync but never ran a step with the discretionary book present.
  Copies used for go-live proofs must include every runtime-created row, not just the
  registered configs.

- 2026-07-24 (pm) · **Correction: the morning's farm-recovery drain did NOT complete.** The
  intraday job (9) finished (1081/1081, `_meta.json` block written, uncommitted by design),
  but the drain was killed silently ~11:07 UTC mid-earnings — job 10 left stale-`running`,
  leftover WAL, no queue_runner process, no traceback in `farm-recovery-2026-07-24.log`
  (same SIGHUP pattern as 07-18; the launching session dropped and `nohup` was not used,
  against the 07-18 lesson). 15:02 UTC: drain restarted as a harness-tracked background job
  (`queue_runner.py --run >> logs/farm-recovery-2026-07-24.log`); stale-job reclaim picked
  job 10 back up (earnings resumed, 25/1456 observed pulling). **Complete ~16:05 UTC:
  1,456 pulled, 0 failed (1,318 with dates + 138 honest no-date), 2,781 rows for
  as_of=2026-07-24 (dates 2026-04-30→2026-10-23), job 10 `done`, WAL checkpointed,
  store 1.84 GiB.** Earnings gate is current again ahead of tonight's nightly.
- 2026-07-24 (pm) · **Independent read-only audit of the incident fixes (Explore subagent)
  — both commits verified correct, no new crash defects.** `6febad5`: fills/MTM confirmed
  strategy-independent (only `generate_all` consumes the registry), no-op class emits zero
  orders on daily cadence. `71543f3`: ORDER BY/LIMIT rewrite semantically identical to the
  filtered MIN/MAX incl. NULL handling; sweep confirmed it was the only in-transaction
  aggregate-over-appended-rows query. run_daily.sh seam re-checked (flock, non-fatal
  universe/sync, farm pinned exit 0, lock-retry) — clean. Two watch items filed in Next:
  first-ever monthly-sleeve execution 07-31, and the unguarded `json.loads(config)` at
  league.py:148.

- 2026-07-28 · **League expanded 10 → 16 books: six research-grounded strategies added, plus
  a real calendar-arithmetic bug found and fixed along the way.** Research first (two web
  passes, full cited report in the store at `research/paper-league-strategy-sleeves.md`):
  trend-following on stocks (Wilcox & Crittenden; Concretum 2024 replication), stop-loss
  momentum (Han-Zhou-Zhu; Barroso & Santa-Clara; Daniel & Moskowitz), sector rotation
  (Quantpedia/Faber), low-vol anomaly, 52-week-high momentum (George & Hwang 2004), and
  EAR-based PEAD (Brandt et al. — needs no analyst data). New books, all long-only,
  point-in-time, pre-registered expectation + kill criterion in `configs.py`:
  `turtle_breakout` (daily; 55d-high entries on template passers, 0.75%-risk ATR sizing,
  chandelier 3×ATR trail, ≤10 positions, SPY-200d entry gate), `momo_stopped` (daily; the
  controlled A/B vs template_top10_banded — identical weekly selection, verified
  byte-identical order lists, plus a daily 15%-below-weekly-reference stop), `sector_momentum`
  (monthly; top-3 SPDR sectors by mean 3/6/12-mo return, negative-12-mo slots to cash),
  `low_vol` (monthly; 30 lowest-252d-vol ≥$5B names, 5-per-sector cap, keep-to-rank-60
  buffer), `high_52wk` (monthly; close÷252d-high ≥ 0.85, top 25, hold-to-0.75 buffer),
  `pead_ear` (daily; earnings reaction ≥ +5% vs SPY on 2× volume → 4% slots, ≤10
  concurrent, 45-session or −8% exit). New shared helpers `atr_wilder` /
  `highest_close_between` in base.py.
  **Bug fix: `calendar.trading_days_between` counted price ROWS, not sessions**
  (`COUNT(*)` over all tickers → "1 day" read as ~4,117). Every mr_overlay "10-day" time
  stop to date actually fired after ONE session (the live book's record so far is honestly
  a 1-day-hold variant — its forward record only matches its spec from tonight), and
  fills.py's 3-day `no_bar` grace rejected on the first retry. Fixed to
  `COUNT(DISTINCT date)`; all three callers audited (mr_overlay, pead_ear, fills.py) —
  session-count semantics correct for each. Proof: two full shakedowns on throwaway copies
  (window 06-22→07-27, 25 sessions, month + 6 week signals, 16 screens backfilled, exit 0,
  0 tracebacks, live store never opened). Post-fix: mr_overlay 85→43 fills with real 1–9
  session holds bounded by the 10-session stop (equity 37,009→38,092 over the window);
  pead_ear exits only via its −8% stop (3 cases verified against avg_cost) with 7 names
  held open; the five books that don't call `trading_days_between` byte-identical across
  runs — the fix touched only what it should. Implementation by an Opus subagent
  (spec + review + both verification passes by the orchestrating session).
  Tonight's nightly `--init` creates the six books (created=07-28); their first signals:
  daily books tonight, monthly books Fri 07-31.

- 2026-07-29 · **Corporate actions (splits + dividends) built, proven on throwaway copies and
  merged to `master` ahead of tonight's cron** (branch `corporate-actions`, commits `9128516`
  schema → `cd92941` collector+reconciler → `ca1af0a` dividend crediting → `d86cfdf`
  total-return signals → `f08b799` nightly wiring → `400fa67` shakedown → `85b22a2` log cap
  → `b7ee0ab` this entry, merged no-ff as `45462cf`). Closes two silent-corruption holes
  found by the 07-29 audit.
  **(1) Splits.** `collect.py` fetches `auto_adjust=False`, but Yahoo restates raw OHLC at
  fetch time while incremental collection only re-fetches `period="5d"` with INSERT OR
  REPLACE. So the first split in any stored name leaves a PERMANENT scale break ~5 sessions
  back: every lookback crossing it (SMA200, RS ranks, 55d breakout, ATR, 252d vol, 52wk high,
  3/6/12-mo returns) silently corrupts, and because `sim_positions.qty`/`avg_cost` were never
  adjusted, held books took a fake ~(1−1/ratio) crash that fires false stops.
  **(2) Dividends did not exist anywhere** — books never received distribution cash, so every
  long book undercounted total return. Worst case was `dual_momentum`'s absolute hurdle
  "12-mo return vs BIL": BIL's price is flat by construction and its whole return is coupon,
  so on a price basis the hurdle had degenerated from "beat the ~4% T-bill" to "beat 0" —
  i.e. the defensive half of GEM was inert. Its first live monthly signal is **Fri 07-31**,
  which is why this landed today.
  New `engine/actions.py` (three modes, one §12.7 job kind `actions`): `backfill` = full
  split/dividend history for every ticker in `prices`, resumable off `actions_fetch_log`;
  `incremental` = held ∪ pending ∪ core ETFs (SPY/EFA/BIL + 11 XL*) ∪ screen-top-50, seconds
  per night; `reconcile` = adjudicate and restate. New tables `corporate_actions`,
  `split_adjustments` (the watermark), `actions_fetch_log`, `sim_dividends`. Nightly order is
  now collect → universe → screen → **actions incremental → split reconcile** → league →
  sync → farm. `base.total_return` is now a real total return and the old price-only function
  it displaced was renamed `price_return`; `dual_momentum`, `sector_momentum` and league's
  vs-SPY column moved over, and `screen.py` was deliberately left alone (52wk ratio, vol, RS,
  ATR, breakouts are conventionally price-based).
  **The reconciler never guesses.** A split is applied only when the STORED series actually
  shows the break, and the break is *located* by scanning one-session close ratios around the
  ex-date rather than assumed to sit at the ex-date — because the nightly 5-day re-fetch
  restates the tail too, so a split spotted 2–3 sessions late has its break at the EDGE OF
  THE REFETCH WINDOW and restating `date < ex_date` would double-adjust the bars between.
  Readings matching neither hypothesis (break present / already restated) are recorded
  `skipped_sanity` with an audit_log row and a nightly TODO breadcrumb, and left for a human;
  ratios inside [0.694, 1.44] are ambiguous by construction and skipped rather than guessed.
  An INDEPENDENT tripwire, not gated on the actions fetch at all, WARNs on any held/pending
  name with a >40% one-session move and no corporate_actions row within ±7d.
  **Evidence — all five proofs green, live store never opened read-write by any test.**
  * *Synthetic split (3-arm A/B/C on identical copies).*
    `python -m sim.corp_actions_shakedown --db-prefix <scratch>/ca --data-dir <scratch>/data
    --setup-from store/market.duckdb`. A = one extra synthetic session, all bars carried flat.
    B = same but ATEX's new bar arrives at the post-2:1 scale with nothing reconciling it
    (the bug). C = same plus the corporate_actions row and the reconciler.
    B vs A: `mr_overlay 39,003.22 → 37,100.91 (−1,902.31)`, `template_top5 32,327.10 →
    28,967.69 (−3,359.41)` — the fake crash, reproduced. C vs A: **every one of the 17 books
    diff 0.00, order sets identical** (`RESULT: IDENTICAL`). Reconcile log:
    `RESTATED ATEX split 2:1 ex=2026-07-29 break=2026-07-29 rows=2887 (obs 2.0000)`;
    `OK qty x2, avg_cost /2 on 6 position(s)`; audit_log `split_restated {...
    "rows_restated": 2887}`; second pass `candidates=0`, state byte-identical (idempotent).
  * *The subtle one, caught and fixed:* `--rerun` rebuilds positions by replaying `sim_fills`,
    and every stored ATEX fill executed at the PRE-split scale — so a naive `rebuild_state`
    silently un-does the reconciler and the fake crash returns on the next re-run of a date.
    `rebuild_state` now scales pre-ex-date fills by the applied ratio (notional and therefore
    the cash trajectory unchanged, so `apply_fill`'s cash clamp never re-clamps). Proven both
    ways: with the fix `template_top5 ATEX qty=147.068236 avg_cost=52.078000` survives a
    `--rerun`; **negative control** (monkeypatch `_split_factors` to `{}`) fires the assertion
    and reverts it to `73.534118 / 104.156`.
  * *Dividend.* Arm D, differenced against the control arm because the step day also fills 20
    carried-over orders. A synthetic $1.00/sh on ATEX: **cash AND equity moved by exactly the
    entitlement for all 17 books (6 paid, 11 at 0.00)** — e.g. `template_top5 73.534118 sh ×
    $1.00 = $73.534118` credited and stored in `sim_dividends`; `--rerun` reproduces identical
    state and ledger; `rebuild_state` replays fills+dividends to the same cash and positions.
  * *Real-data nightly-equivalent.* The run_daily stage sequence (screen → actions incremental
    → reconcile → league, real 2026-07-28 bars, `--rerun` so nothing `--skip-if-done`-no-ops;
    universe/collect skipped as pure-network stages with no `--db` flag) on a copy: **exit 0,
    0 tracebacks, league.md renders all 17 books.** Real Yahoo pull of 77 names; reconcile
    adjudicated **36 real historical splits → 32 `noop_restated`, 3 `skipped_ambiguous`,
    1 `skipped_sanity`, rows_restated=0.**
  * *BIL sanity (real fetch, SPY/EFA/BIL).* 12-mo (252-session) as of 2026-07-28:
    **BIL price −0.09% vs total +3.72%** (12 distributions, $3.489/sh; research reference was
    −0.1% / +3.8% with the 3-mo T-bill at 3.91% — same ballpark). SPY **+16.29% → +17.47%**
    (+1.18%, the ~1.2%/yr yield). EFA **+14.48% → +18.19%**. The GEM hurdle is real again —
    and note this is not merely a magnitude correction: on price return SPY (+16.29%) beat
    EFA (+14.48%), but on total return **EFA (+18.19%) beats SPY (+17.47%)**, because EFA's
    ~3.7% yield is triple SPY's. The fix therefore FLIPS which asset dual_momentum selects on
    Friday 07-31. Post-merge verification of the same numbers on the live store confirms it.
  * *Regression.* No repo pytest suite exists (checked). `sim/backtest_shakedown.py --start 25`
    on sim-cleared copies, run on `master` and on the branch: both exit 0, 0 tracebacks, and
    the final 16-book equity/fill/open table is **byte-identical** (`diff` empty) — the copy
    has no corporate_actions rows so `total_return` degrades to `price_return` exactly as
    designed. Note: the shakedown fails on a *raw* copy of the live store on master too
    (pending 07-28 orders vs a 06-23 window trip the look-ahead assert) — pre-existing, not a
    regression; it needs sim state cleared, which is its documented usage.
  **First-run safety, the thing that could have destroyed the store.** A watermark-only design
  would treat every historical split as unreconciled on first run and divide prices repeatedly.
  Because adjudication is driven by what the stored series actually shows, real history reads
  as already-restated and is marked no-op: BIL's genuine 1:2 reverse split (2017-11-30) and
  EFA's 3:1 (2005-06-09) both came back `noop_restated`, **rows_restated=0**, with BIL's closes
  flat at ~91.48 across the ex-date. Also verified the D3 dividend share-basis question on
  those two names: dps/price per payment stays the same order of magnitude on both sides of a
  later split (BIL 0.0022–0.4431% pre vs 0.0033–0.4615% post; EFA 0.07–1.91% pre vs
  0.21–2.55% post), confirming yfinance back-adjusts dividends for later splits to the same
  scale our restated prices use.
  Reconcile costs **17.4 ms/candidate** (36 candidates in 0.63s), so the one-time pass over
  the full backfill's split history extrapolates to ~3 min for 10k splits — safe in front of
  the league even though that stage is fatal.
  **KNOWN LIMITATIONS (documented, deliberately not built now):**
  (i) *Delisting / merger cash-outs.* A position in a name that stops printing freezes at its
  last close after the 3-day `no_bar` window; real practice credits the deal price. Needs a
  manual/assisted path — not attempted, because inventing a cash-out price is exactly the
  fabrication the mission forbids.
  (ii) *Idle cash earns 0%.* Broker-realistic and deliberate; the BIL opportunity cost is
  visible via the benchmarks now that BIL's total return is honest.
  (iii) *`intraday_prices` is not restated* by the reconciler — it is a raw append-only
  archive, not a signal source, and no strategy reads it.
  (iv) *Dividends are credited as unreinvested cash* (documented v1 approximation in
  `total_return`'s docstring); this matches how the books actually behave, since sim dividend
  cash is only redeployed at the next rebalance.
  **Post-merge live-store dry run (03:25–03:30 UTC, ~19 h before cron).** Because the reconcile
  stage is FATAL and sits in front of the league, both nightly commands were run by hand
  against the real store exactly as `run_daily.sh` will run them, rather than discovering a
  surprise at 22:30. `actions.py --mode incremental`: 77 names, 0 failed, 41 s.
  `actions.py --mode reconcile`: exit 0 in 1.3 s, 36 candidates → 32 `noop_restated`,
  3 `skipped_ambiguous` (PRK 1.05:1 ×2, XLF 1.231:1 — all sub-threshold ratios), 1
  `skipped_sanity` (ARWR 0.0153846:1 ex-2004, observed 1.6 — Yahoo's row disagrees with our
  bars, correctly left alone), **rows_restated = 0**; tripwire silent. Verified afterwards
  read-only: live `prices` untouched (`SUM(rows_restated) = 0`), `sim_positions` unchanged
  (42 rows, ATEX still 41.6396 / 38.3144 / 73.5341), 36 splits + 1,839 dividends stored,
  SPY/EFA/BIL/XL* all with full dividend history. A second reconcile exits 0 with 0
  candidates, so tonight's stage is a fast no-op over this set and only adjudicates whatever
  is new.
  (v) *A split adjudicated `noop_restated` does not adjust sim positions* — correct today
  because the nightly reconcile decides every split within a session of its ex-date, well
  inside the 5-day refetch window, but it is the assumption that would break if the nightly
  stopped running for a week across a split in a held name.
- 2026-07-29 · **E1 forward (out-of-sample) runner built — the experiment's second half, and
  the first out-of-sample Mondays are on the record.** §12.3 froze E1 (buy SPY Monday open,
  sell that Monday's close) on 07-16 and `9568cec` published the BACKTEST half on 07-18
  (in-sample + a locked holdout, computed once). The half that actually decides E1's fate —
  the forward window that "starts with the league", running to 40 Mondays and then a kill
  test — did not exist. It does now: `farm/experiment_runner.py`, one append-only row per
  settled out-of-sample Monday, plus `data/reports/experiments/e1-spy-monday-forward.md`
  regenerated every night. Branch `e1-experiment`, five commits, merged to master.
  **Decisions.**
  (D-E1a) *The forward phase is registered in its OWN frozen file*
  (`farm/experiments/e1-spy-monday.forward.json`), not as an `oos_start` key added to the
  pre-registered YAML. That YAML already has result rows, so its hash is frozen and editing
  it would — correctly — trip `experiment.py`'s immutability check. Forward rows therefore
  carry the **YAML's** hash as their `params_hash`, so `check_immutable` still sees exactly
  one hash under the id; the forward file's own hash rides in `meta_json`. The runner
  recomputes the parent hash and refuses to write if it has drifted (proven: a one-character
  edit to the YAML's `gross_annual` produced `FROZEN CONFIG CHANGED … Refusing to write`).
  (D-E1b) *Two things §12.3 leaves open were registered in advance, before the evidence
  existed.* The **cost model** is the paper league's own fill model — `sim/fills.py`
  `slippage_bps_for(median_dollar_vol('SPY', monday))` = `max(half_spread_bps, 5) + 5` =
  **10.0 bp/side, 20 bp round-trip** (SPY's 60-bar median dollar volume is ~$36bn, far above
  the $50M top tier), which is **6.7× stricter** than the 3bp the backtest registered; a
  forward test must be at least as honest as the league beside it. The **kill test reads the
  NET series** — the conservative reading of "≈+10%/yr gross vs ~1.2–1.5%/yr costs". Gross
  and 3bp-net are published alongside so either reading stays available to a reader. Both
  choices are in the frozen file, so neither can be picked after seeing the data.
  (D-E1c) *Storage extends `experiment_results` rather than adding a table.* That table was
  shaped for per-PARTITION statistics, so three additive columns carry what a single dated
  trade needs (`trade_date`, `gross_ret`, `net_ret`); backtest rows read NULL there, which is
  also how the two series are separated in SQL (`trade_date IS NULL` = backtest stats). A
  forward row is `partition = 'oos:<date>'`, so the existing primary key does the idempotence
  work too. The stat columns that mean nothing for one observation (`std_ret`, `t_stat`, the
  CAGR/Sharpe family) are left NULL rather than filled with a figure that would read like a
  result.
  (D-E1d) *Settled-bar guard.* A Monday is recorded only after **21:15 UTC that day** — past
  the 16:00 ET close under both DST regimes, and well before the 22:30 UTC nightly. The table
  is append-only, so recording a mid-session close would be permanently wrong. Proven by
  running with a faked `now` of Monday 18:00 UTC: the Monday is skipped, and picked up at
  21:20 UTC.
  (D-E1e) *Nightly position: between league and sync, inline, non-fatal.* AFTER league so the
  row lands with the night's other forward evidence; **BEFORE sync** so the regenerated report
  is committed the same night — the farm section runs post-sync and would miss the commit by
  a day. Inline rather than queued because the job is one SPY row in milliseconds and §12.7's
  queue is for heavy work; the dispatch entry `experiment_forward` is registered anyway so a
  missed night can be replayed through the normal job path (proven end-to-end through
  `queue_runner --run`). `|| WARN` under `set -e`: experiment reporting must never block
  trading data, and the runner is idempotent so a failed night is simply picked up by the next.
  **Bug found and fixed on the way (this one would have bitten).** `experiment.py`'s
  `append_results` did a bare `INSERT INTO experiment_results SELECT …` — **positional**, so
  it requires row width to equal table width and breaks the moment the table gains a column.
  Adding the three forward columns does exactly that. Caught on a throwaway copy by clearing
  the table and re-running a first registration against the widened schema; fixed by naming
  the columns. The first compatibility test had *passed* only because `check_immutable`
  short-circuits the append when the config already has results — a green test that proved
  nothing, which is why the cleared-table run was worth doing.
  **Evidence (all copy-first; live store touched only by the runner's production write path).**
  * *Hand check.* SPY 2026-07-20 open **747.0599975585938** close **742.0900268554688** →
    gross **−0.66527062%**; net at 10bp/side **−0.86374161%**. SPY 2026-07-27 open
    **744.9099731445312** close **739.0900268554688** → gross **−0.78129526%**, net
    **−0.97953443%**. Recomputed independently from the stored bars, matched the stored
    `gross_ret`/`net_ret` to <1e-15.
  * *Idempotence.* Three consecutive runs on a copy: 13 backtest rows + 2 forward rows, and
    still 15 after runs 2 and 3. On the LIVE store a second run appended nothing (15 rows).
  * *Nightly-equivalent tail.* league → experiment → sync on a copy, mirroring `run_daily.sh`'s
    structure under `set -euo pipefail`: **exit 0**. A deliberately broken `--id` in the same
    sequence printed the WARN and the sequence still exited 0 (non-fatality proven, not
    asserted). `sync.py --dry-run` staged
    `data/reports/experiments/e1-spy-monday-forward.md` — it stages `data/` wholesale, so
    **sync needed no change**, as the spec asked to verify.
  * *Live store.* First real run appended 2 rows; afterwards the 13 pre-existing backtest rows
    were verified **byte-identical**, still one distinct `config_hash`, and prices /
    sim_positions / jobs untouched (job 18, the actions backfill, still pending for tonight).
  **The result so far is negative, and published that way.** Both out-of-sample Mondays lost:
  cum gross **−1.44%**, cum net **−1.83%**, 0/2 winners. The report leads with
  "**NO RESULT YET — 2 of 40**", prints "38 Mondays to go", and states that the kill test
  runs once, at n=40. It also shows what the criterion *would* say today while saying plainly
  that it is not being applied — the point being that no peek can change the frozen plan.
  For context (report-only, never in the statistics), the 2 years of Mondays before the
  out-of-sample start ran gross +0.1655%/Monday (t 2.30) but **−0.0347%/Monday net at the
  league's 20bp** (t −0.48) — i.e. the pre-registered decayed edge was already inside the
  spread before the forward window opened.
  **M4 stamp.** M4 was stamped DONE 2026-07-18 on the backtest report; its exit criterion
  ("first pre-registered experiment report published") is now satisfied in the sense that
  actually matters — a **forward, out-of-sample** record exists and is accumulating, not just
  a backtest. M4's other criterion (intraday archive accumulating under the disk watchdog)
  has kept running since: the archive is enqueued nightly and store/ is ~2.05 GiB against the
  60/80 GB caps.
  **KNOWN LIMITATIONS (deliberate).**
  (i) *No holiday-Monday substitution.* A market-holiday Monday produces no row at all —
  never a synthetic flat trade — so 40 Mondays is ~10 calendar months, not 40 weeks.
  (ii) *The forward series is unadjusted for corporate actions* in the sense that it reads
  `prices` as stored; SPY's dividends do not enter an intraday open→close return, and the
  reconciler keeps the scale coherent, so this is correct today but would need thought for a
  name that splits mid-window.
  (iii) *One experiment only.* The runner is E1-shaped (`weekday_open` → `same_day_close`);
  a second forward experiment with different mechanics needs the rule dispatch generalized,
  which is not worth building before there is a second experiment.

- 2026-07-29 (pm) · **"Should the bot react intraday?" — measured instead of assumed.**
  Owner asked whether after-hours-only trading is missing opportunity. New read-only tool
  `farm/execution_drag.py` computes, from the bot's own fills, the signed cost of filling at
  next-open vs the signal-day close → `data/reports/execution-drag.md`. First result over
  all 124 fills: overnight delay costs **+7.7 bp/fill mean, t = 0.63 — indistinguishable
  from zero**, and it decomposes with opposite signs by strategy: momentum books pay
  +23–30 bp (t ≈ 0.7–0.8, not significant), mean-reversion books **gain** −21 bp (the delay
  buys the dip cheaper). Verified against an independent hand computation (same numbers).
  Decision rule pre-committed in the report: MOC-style close-execution A/B variants are
  considered only for a book whose drag is adverse with t > 2 at n ≥ 100 own fills; MR
  books excluded (favorable sign is structural). Intraday *selection* stays rejected on the
  2026-07-29 cadence research (short-horizon reversal + turnover; store note
  `research/selection-cadence-vs-volatility.md`); live-broker reactivity remains M5,
  deferred, personal hardware only. Not wired into the nightly on purpose (streak at 3/7,
  monthly debut Friday) — run manually or from the weekly review.

- 2026-07-29 (pm) · **Historical-backtest farm built — the league books replayed over 6mo/1y/
  3y/5y/15y windows, on scratch copies, by their own live code** (design §12.3; Next #13(b)
  first workload). New package `farm/backtest/`: `hist_screen.py` (vectorized point-in-time
  screen), `replay.py` (per-(book, window) scratch build + real league day-step loop),
  `stats.py`, `report.py`, `grid.py`, `proofs.py`; `engine/queue_runner.py` gains the
  `backtest` job kind. **`engine/run_daily.sh`, `sim/league.py`, `sim/fills.py` and every
  strategy file are untouched** — the replay drives them, it does not fork them.
  **The two design calls that make this honest.**
  (D-BF1) *Vectorize the SCREEN, never the STRATEGY.* The expensive part of a 15-year
  replay is recomputing `screen_results` for 3,775 sessions; the part that would quietly
  invalidate the whole exercise is reimplementing what a book does. So `hist_screen.py`
  recomputes the screen set-based in DuckDB — window frames over each ticker's own bar
  sequence, which IS the live screener's positional semantics (`closes[-50:]` ==
  `AVG(close) OVER (… ROWS 49 PRECEDING)`) — and everything downstream is the production
  code path: `league.init_portfolios`, `league.step`, `fills.attempt_fill`,
  `portfolio.credit_dividends`, the real strategy classes. A replay is 5 s of screen and N
  day-steps, not a second engine.
  (D-BF2) *Slim scratch, live store read-only.* Each job exports parquet from the live
  connection (SELECT / COPY TO only — never a write), loads it into
  `scratch/<book>__<window>/replay.duckdb` (prices trimmed to the window + 460 sessions of
  warmup, actions, universe, fundamentals), replays, writes one result JSON and deletes the
  scratch. 460 sessions covers every lookback any book reads (the screen's 400-bar pull, the
  252-session total returns, `high_52wk`'s 430-day window, `low_vol`'s 428-day vol window,
  the 200-session SPY regime, the 60-bar median-$vol the fill model prices slippage from).
  Only `passes_template = TRUE` screen rows are stored: every `sim/strategies/*` read goes
  through `passing_ranked` / `rank_position`, both of which filter to passing rows, so the
  non-passing ~11M rows of a 15-year window are dead weight.
  **Five proofs, all green** (`farm/backtest/proofs.py --all`).
  * *Screen equivalence.* Against a FRESH `engine/screen.py --rerun` on the same copy:
    **2026-07-15 / 07-21 / 07-28 → 0 membership differences and 0 column differences**
    (3,873 / 3,876 / 3,882 names; close, rs_rank, template_score, passes_template, dist_50d,
    dist_200d, off_52w_low, off_52w_high, base_tight, vol_dryup all exact). Against the rows
    STORED on the day, 07-28 also matches exactly (0 diffs), while 07-15 and 07-21 differ —
    and every one of those differences is attributable: 6 and 4 names have since left
    `universe` (AVNS, CCRN, NOWL, NSA, SBIL, TMHC), and 4 / 56 closes were restated by the
    corporate-actions reconciler. That is survivorship and restatement caught in the act,
    two weeks out, which is the best argument for disclosure #1 in the reports.
  * *Replay fidelity.* `sim/backtest_shakedown.py` over 2026-06-22→07-16 on one scratch copy
    vs the new driver over the same span off the same screens on another:
    **`template_top10_banded` and `mr_overlay` are row-identical in sim_orders (40 / 39),
    sim_fills (39 / 39), sim_equity (18 / 18), sim_positions (19 / 22) and sim_dividends.**
    Both drive the same league code, so equality was the only acceptable result.
  * *Stats sanity.* `spy_benchmark` 1y recomputed by an independent implementation that
    imports nothing from `farm/backtest`: equity_end **47,259.6738684082**, total
    **+21.17865094%**, CAGR **+21.19459576%**, vol **12.45908803%**, Sharpe **1.6106349048**,
    Sharpe-ex-BIL **1.3071286955**, maxDD **−8.77592838%** — every one matching to **0.00e+00**.
    BIL excess lowers Sharpe as it must (1.6106 → 1.3071). (The book bought 62 SPY at
    625.024424 = the 2025-07-17 open + 10 bp, after `apply_fill`'s integer cash clamp.)
  * *Queue end-to-end.* `queue_runner --enqueue backtest --params
    {"config_id":"ew_benchmark","window":"6mo"} --priority 140` then `--run` on a full copy:
    job 19 pending → running → **done in 22.9 s**, result JSON + `data/reports/backtests/`
    regenerated.
  * *Nightly-equivalent tail.* league → experiment → sync --dry-run → queue drain on a copy
    under `set -euo pipefail`: **exit 0**, and `sync.py --dry-run` staged
    `data/reports/backtests/**` unprompted (it stages `data/` wholesale, so **sync needed no
    change**). Nothing this feature added runs in the nightly.
  **What the numbers say so far (6mo window, PRE-BACKFILL — regenerate after job 18).**
  Ranked by total return: sector_momentum +14.85%, spy_benchmark +10.45%, mr_overlay_gated
  +9.34%, mr_overlay +6.59%, dual_momentum +5.43%, low_vol +5.32%, ew_benchmark +4.70%,
  dual_momentum_gated +1.55%, high_52wk −0.41%, template_top5 −3.32%, momo_stopped −6.05%,
  template_top10_banded −8.22%, turtle_breakout −10.29%, template_top10_banded_gated
  −14.31%, template_top5_gated −17.14%. **The whole RS-template family loses to the
  equal-weight benchmark on the same universe and runs at 82–87% annualized vol with 34–38%
  drawdowns** — the books really do hold the microcap/biotech tape the live league holds
  today (the replay's 2026-07 selection overlaps the live book's actual positions), so this
  is the book, not an artifact. Nothing here is out-of-sample; see the report's disclosures.
  **KNOWN COMPROMISES (all disclosed at the top of every report).** (i) Survivor universe —
  the screen's eligible set is **1,237 names in July 2011 against 3,873 today**, and all
  1,237 are names that were still listed in 2026; that is why **vs EW on the same universe**
  is the primary comparison and absolute CAGR is context only. (ii) `low_vol`'s $5B cap
  filter uses TODAY'S fundamentals snapshot restamped to the window start (no historical
  caps exist) — static-cap look-ahead; without it the book is silently inert. (iii)
  `pead_ear` is excluded outright (no historical earnings dates) and `discretionary` is a
  human book — both said plainly rather than faked. (iv) `new_today` is defined against the
  previous session in the replay window rather than the previous stored `run_date`; no
  strategy reads that column.
  **MEASURED RUNTIME + the enqueued grid.** Per-job 6mo (124 sessions, one book, nice 19,
  8 threads): ETF books 7.5 s · template family 13–20 s · turtle 23 s · momo_stopped 32 s ·
  ew_benchmark 38 s · mr_overlay 85 s. Anchored on real long runs, the day-step cost is
  **linear in sessions** — mr_overlay 3y = 405.7 s over 753 sessions (250/500/750 at
  135/269/389 s → 0.52 s/session flat), turtle_breakout 3y = 130.7 s (0.152 s/session) — and
  the vectorized screen is nearly free: **753 sessions screened in 9 s** (396,728 passing
  rows). **15y (3,775 sessions) estimate: mr_overlay ~30–34 min (the worst book),
  mr_overlay_gated ~24 min, momo_stopped ~12 min, ew_benchmark ~11 min, turtle ~8–11 min,
  the template family ~5–6 min, low_vol/high_52wk ~5–6 min, the ETF books ~2 min. The whole
  15y tier ~2 h; the ENTIRE 78-job grid ~3.5 h sequential.** No single job comes near the
  spec's 6 h flag, so the nightly's flock overlap guard is not at risk (the drain budget
  stops STARTING jobs at 4 h but never kills one in flight).
  **Grid enqueued on the live store: jobs 19–96** (78 jobs = 15 books × {6mo,1y,3y,5y,15y}
  + `max` for the three ETF-only books), priorities staggered so short windows land first —
  **140** 6mo (19–33) · **145** 1y (34–48) · **150** 3y (49–63) · **155** 5y (64–78) ·
  **160** 15y (79–93) · **165** max (94–96). The corporate-actions backfill (**job 18,
  priority 130**) was verified still pending at enqueue time and drains FIRST; the runner's
  own `ORDER BY priority ASC, created_at ASC` was checked empirically on a copy (a 15y job
  enqueued *before* a 6mo job still sorts behind it). `grid.py --enqueue` refuses to run at
  all if a pending `actions` job would not outrank the grid. Tonight's 4 h drain minus job
  18's ~1.5–2 h leaves ~2 h, so expect the 6mo/1y/3y tiers to land tonight and the rest over
  the following nights — jobs are independent, so a partial grid is a partial report, not a
  broken one. Reports regenerate after every job; because the farm drains AFTER sync in
  `run_daily.sh`, each night's backtest reports are committed by the FOLLOWING night's sync.

- 2026-07-29 (eve) · **Full backtest grid COMPLETE same-day — the box was drained manually
  instead of waiting nights.** Two manual `queue_runner --run` drains (harness-tracked,
  nohup, `logs/manual-drain-2026-07-29.log`): job 18 actions backfill (409,684 rows /
  8,582 tickers — dividend coverage now full) + all 78 backtest jobs (19–96), zero
  failures; second drain finished ~14:30 UTC, ~8 h before cron. Every window in
  `data/reports/backtests/README.md` is now populated with full-dividend totals.
  Headlines (survivor-universe caveat applies to every absolute number; vs-EW is the
  honest read): **no stock-picking book beats its own EW-same-universe benchmark on any
  window ≥ 3y**; SPY's 15y Sharpe 0.86 beats every book except **low_vol at 0.95** (11.4%
  CAGR at 12.1% vol — the one book doing its job across cycles); **template_top5 15y max
  DD −83%** even with the survivor tailwind (its live kill criterion will do its work);
  **mr_overlay standalone ≈ 0% total over 15y** (Sharpe 0.06 — "overlay only, never
  standalone" confirmed; note ~90% idle cash at sim's 0% — a BIL-parked variant would
  read ~+1–2pp/yr higher, still nowhere); **the regime gate loses money in the 3y/5y
  risk-on windows but pays over 15y** (template_top5_gated +808% vs ungated +272%; DD
  −74% vs −83%) — drawdown insurance, priced exactly as the July lesson said;
  momo_stopped's daily stop adds modestly over 15y (+673% vs +621% banded, similar
  Sharpe). Findings mirrored to the store: `research/league-strategy-backtests.md` +
  two lessons.md lines.

- 2026-07-31 · **`macro_composite` book + `engine/signals.py` collector built and proven on
  branch `macro-composite` — NOT merged (deliberate: tonight is the first monthly-signal
  nightly, mid-streak; merge only after it verifies clean).** The league's first non-price
  book. Research first (three web passes + a live endpoint probe from this box, full cited
  report in the store at `research/market-regime-signals.md`): short interest is the strongest
  peer-reviewed aggregate predictor (Rapach JFE 2016); margin debt is coincident-to-lagging
  once its 3-week lag counts; Fama–French 2019 kills yield-curve-inversion timing (the
  re-steepen is the signal); "net liquidity" rejected as spurious; FINRA ATS dark-pool data
  rejected for timing (2–4wk lag) — DIX is the honest daily dark-pool read; breadth computed
  internally from our own prices has the best evidence-to-lag ratio (Zweig thrust). Built by
  an Opus subagent to a frozen spec, verified by it, branch commits `057001b`..`d6e0341`:
  append-only point-in-time `macro_signals` (series, obs_date, value, fetch_as_of; D-MS1
  first-observed-wins), 10-source collector (curl_cffi chrome impersonation — this network
  TLS-fingerprint-kills plain curl on FRED; warn-and-continue per source; LAG_DAYS registry;
  internal breadth set-based), queue job kind `signals` + nightly enqueue at priority 105,
  and the weekly book: four frozen blocks (breadth / credit / vol structure / macro) → SPY
  tier {0,25,50,75,100}%, fear-extremes add-back, margin+short-interest cap, 0.20 hysteresis.
  Thresholds pre-registered 2026-07-31 in configs.py before any evidence.
  **Proofs (all on copies; live store never RW):** 66,563-row backfill across 20 series
  (AAII→1987, VIX→1990, margin→1997); 3 independent-refetch spot checks exact (VIX vs
  yfinance, DIX re-download incl. 2020-03-23, ICSA vs fresh FRED); second backfill inserts 0;
  point-in-time gate proven both directions (fetch_as_of tomorrow → invisible today); 28-session
  shakedown exit 0 with sane tier moves (0.25→0.75, then hysteresis holds) and the other 16
  books **byte-identical to a master run on the same copy** (md5-matched dumps); queue
  end-to-end done; nightly tail exit 0 including a broken-network run (9 sources degraded,
  breadth still computed, zero wrong rows). D-MS2: `--pit-lag` backfill mode stamps
  fetch_as_of = obs_date + LAG_DAYS as a labelled reconstruction so historical replays can see
  the series; default backfill stamps today (honest, invisible to the past).
  **Open items:** (i) put/call 2019-10→2022-12 gap is our request-budget choice, not CBOE's —
  `PC_ERA2_BACKFILL_START` to 2019-10-07 closes it (~830 requests); (ii) the pre-registered
  short-interest cap is firing on a **denominator artifact** (settlement 07-15 Σadv fell 30%,
  short base flat → dtc 2.08→2.96 = fake +43%) — live read today would be composite +3 →
  1.00 capped to 0.50; threshold stays frozen, the honest fix if the forward record indicts
  it is SI/float, not a tuned sigma; (iii) AAII sits behind Imperva and intermittently serves
  a block page at HTTP 200 — magic-byte guard WARNs honestly, file self-heals (full history
  each pull); (iv) hy_oas keyless-capped to 3y (ICE) — free FRED API key is the fix, flagged
  to owner; HYG/LQD internal substitute covers; (v) breadth is survivor-biased (today's
  universe_snapshot) — same disclosure as the backtest farm.
  **Incident avoided:** the build agent left the working tree checked out on the branch;
  caught ~hours before cron and switched back to master. Lesson for every future delegated
  build: **cron runs the working tree — an implementation agent's last act must be
  `git checkout master`**, and the orchestrator must verify it.

- 2026-08-04 · **Weekly walk-forward re-validation built and proven — Next item 13(a),
  the top-priority designed-but-unbuilt §12.3 workload, is DONE.** New package
  `farm/walkforward/` (`protocol.py` / `runner.py` / `report.py` / `grid.py`), queue job
  kind `walkforward` registered in `engine/queue_runner.py`, and a Sunday driver
  `engine/run_weekly_walkforward.sh`. Commits `a0e8a68` (package + queue) → `5d8016b`
  (driver + docs) → this entry. **`engine/run_daily.sh`, `sim/league.py`, `sim/fills.py`
  and every strategy file are untouched** — the walk-forward drives them, exactly as the
  backtest farm does. This is the workload execution design §6 names ("Sunday cron:
  /watchlist-scan + /trading-review + **the farm's walk-forward re-validation**").
  **The protocol, registered before any evidence (D-WF1–D-WF5 written out in
  `protocol.py`; D-WF6 in `runner.py`).**
  (D-WF1) *Rolling-origin, train 24 months → validate 12 months, step = validate length,
  6 folds, anchored on the latest session.* Step = validate length is what makes the six
  validate windows DISJOINT — six independent out-of-sample measurements, no session
  counted twice. 12 months of validate is the shortest window that gives a MONTHLY-cadence
  book (dual_momentum, sector_momentum, low_vol, high_52wk, ew_benchmark) twelve real
  decisions; anything shorter judges half the league on 2–3 rebalances. 6 folds ≈ six years
  of validate coverage — COVID crash and recovery, the 2022 bear, the 2023-25 bull — at a
  measured cost that fits inside one §12.7 drain budget. All four numbers are job params,
  so a deeper run is an override, not a redesign.
  (D-WF2) *Each fold is an INDEPENDENT replay starting fresh at the $39,000 reference
  notional.* The cheaper alternative — one long continuous replay sliced into folds — lets a
  book that halved its equity in fold 1 trade fold 6 at half size, where integer-share
  rounding and the fill model's liquidity guard behave differently. A re-validation must
  measure the RULE at its designed size, not the archaeology of an account opened in 2018.
  The cost of that call is that fold returns do not compound into a multi-year number; that
  number is the backtest farm's job and the reports say so.
  (D-WF3) *The anchor is the LATEST session in the store, not league inception.* A weekly
  re-validation feeding a weekly review has to include the most recent data. The newest
  validate window therefore overlaps the live forward record by however many sessions have
  passed since 2026-07-17 (17 sessions today, against a 252-session window). That overlap is
  a *shadow* of the live book, not extra out-of-sample evidence, and every such fold is
  flagged `◈` in the reports rather than quietly counted.
  (D-WF4) *The replayed config is the row in the LIVE `portfolios` table, not
  `sim/strategies/configs.py`.* `portfolios.config` is the JSON frozen at the book's creation
  and is what `league.generate_all` actually reads; re-validating anything else would
  re-validate a rule the league is not trading. The book list comes from the same query
  (`WHERE active`), so a book the league stops running stops being re-validated.
  (D-WF5) *Nothing is fitted anywhere in this workload.* The train window is a MEASUREMENT
  baseline (what the rule did on the sessions immediately before), not a search — §12.3's
  farm exists "to kill bad ideas cheaply, not to find a lucky parameter". Parameter grids
  stay in item 13(b).
  (D-WF6) *One job per BOOK, not per fold.* The fold windows overlap by construction, so a
  per-fold job would rebuild the same ~8.5M-row price scratch and re-run the same screen six
  times. One job builds one scratch, screens once over the whole span, then replays each
  fold inside it — 6× less I/O for identical numbers.
  **The verdict flag is mechanical and is NOT a kill.** Against `ew_benchmark` on the same
  folds: **PASS** = beats EW in ≥ 50% of validate windows AND mean validate excess ≥ 0;
  **WATCH** = one of those fails; **REVIEW** = both fail *and* the latest window also trails
  EW. REVIEW puts the book on the Sunday agenda against its own pre-registered prose kill
  criterion, which is printed on its page and is what actually decides. Benchmarks are
  labelled `reference` and not judged.
  **Evidence — every proof ran on a COPY of the store. The live store was opened read-write
  exactly once by this session, by the production enqueue** (`grid.py --enqueue` writing 15
  `jobs` rows); verified read-only afterwards that `prices` (19,866,576 rows), `portfolios`
  (17) and `sim_equity` (161 rows, max date 2026-08-03) are unchanged. The copy was taken
  after job 106's signals backfill checkpointed and released the writer lock (no `.wal` left
  beside the file), so it is a clean snapshot, not a torn one.
  * *Hand check against an independent reconstruction.* `spy_benchmark`, one fold
    (train 2026-02-03→2026-05-01, validate 2026-05-01→2026-08-03), scratch kept. Equity
    rebuilt from scratch out of `sim_fills` + `sim_dividends` + `prices` by a script that
    imports nothing from `farm/`: equity@split `40758.775135742195` and equity@end
    `42938.51681152345` **matched the stored `sim_equity` to 0.000000000000**; validate
    total return, annualized vol, Sharpe and max drawdown all matched the result JSON to
    **0.0 / 0.00e+00**. The train/validate split abuts and does not double-count: **train 62
    rows + validate 64 rows − 1 shared split row = 125 = total `sim_equity` rows.** Economic
    sanity: the book returned **+5.3479%** against SPY price-only **+5.1370%** and SPY with
    dividends **+5.4012%** — i.e. it captured the dividend and gave back a sliver to the idle
    cash left by `apply_fill`'s integer-share clamp (56 shares, ~$300 idle), which is exactly
    what a $39k SPY holder should look like.
  * *Queue end-to-end, every book.* `farm/walkforward/grid.py --enqueue` on the copy →
    **jobs 107–121, all 15 eligible books**, drained by the real `queue_runner.py --run`
    (nice 19, ionice idle, load/RAM guard, 8 GB declared per job): **15/15 `done`, 0
    failures, 0 tracebacks** (`logs/wf-shakedown-2026-08-04.log`). Reduced protocol
    (3mo/3mo, 2 folds, 187 sessions) so every book's code path ran cheaply — per job
    12.3 s (dual_momentum) to 117.0 s (mr_overlay_gated), whole grid ~9.5 min. The
    partially-drained report is honest: books that finished before `ew_benchmark` showed
    verdict `no-benchmark` rather than a fabricated comparison, and resolved once it landed.
  * *Full-protocol runs (the real 24/12/6 shape, 2018-08-03 → 2026-08-03, 2,009 sessions).*
    Through the queue on the copy (jobs 122–124, all `done`, 0 tracebacks).
    `spy_benchmark` **172.8 s**, `template_top5` **335.8 s**, `mr_overlay` **2,981.5 s**
    (~50 min — the league's most expensive book by 9×, at 462–516 s per fold).
    Scratch build **11 s** for **8,546,946 price rows**
    (2016-10-05 onward — 460 sessions of warmup ahead of the span); the vectorized screen
    **2,009 sessions → 796,463 passing rows in 14 s**. Sanity on the numbers, not just the
    plumbing: `spy_benchmark`'s six validate windows read **+34.62% / −4.57% / +9.59% /
    +19.66% / +17.57% / +22.49%**, with the −4.57% window (2021-08→2022-08) carrying a
    **−22.27%** max drawdown — that is the 2022 bear market showing up where it belongs, on
    a book that only ever buys SPY once.
  * *Projected cost of the whole weekly grid.* Anchoring the backtest farm's measured
    per-session cost table on these three (0.0356 s/session `spy_benchmark`, 0.0684
    `template_top5`, 0.6515 `mr_overlay`, over 4,536 fold-sessions per book), the 15-book
    grid is **≈ 2.7–3 h sequential**, with `mr_overlay` (~50 min) and `mr_overlay_gated`
    (~37 min projected) as the only long poles. That fits inside one §12.7 drain budget
    (4 h, and the budget only stops STARTING jobs), and no single job comes near the spec's
    6 h flag. Each scratch store is **586 MB** and is deleted when its job finishes.
  * *First real finding, and it is the one the median column exists for.* `template_top5`'s
    six validate windows are **+389.99% / −18.02% / +8.38% / −40.26% / −52.86% / +44.29%** —
    mean **+55.25%**, **median −4.82%**, win rate 50%, worst validate drawdown **−68.98%**.
    The entire mean is one fold (2020-08→2021-08, the meme tape on a survivor universe). A
    book judged on its average walk-forward window would look like a triumph; the same book
    judged on its median window is a coin flip with a 69% drawdown. Both numbers are in the
    report, which is the point. For contrast on the same six windows, `mr_overlay` reads
    **+29.61% / −4.35% / −9.95% / −3.36% / +11.06% / +9.36%** (mean +5.40%, win rate 50%,
    worst validate drawdown −17.30%) — a book whose 15-year standalone total was ≈ 0% in the
    backtest farm looks materially better over the last six years, which is exactly the kind
    of regime-dependence a rolling walk-forward exists to surface. None of this is the real
    grid's output; it is three books measured to prove the machinery. The live grid
    (jobs 107–121) writes the numbers that count.
  **Cadence: a separate Sunday cron, deliberately NOT a stage in the nightly.**
  `engine/run_daily.sh` is a weekday-only cron (`30 22 * * 1-5`), so the `date -u +%u`
  cadence gate the Friday fundamentals stage uses would be **dead code** for a Sunday
  workload — the spec's gating pattern does not support this cleanly, so the workload got its
  own driver instead. `engine/run_weekly_walkforward.sh` (flock guard, enqueue → drain →
  sync) is committed and executable but **NOT installed in cron by the build loop**. Intended
  entry, documented in the script header and here (owner action):
  ```
  0 6 * * 0 ~/trading-engine/engine/run_weekly_walkforward.sh \
      >> ~/trading-engine/logs/walkforward-cron.log 2>&1
  ```
  Sunday 06:00 UTC is clear of everything (nightly 22:30 Mon-Fri, news analyst 11:00 Mon-Fri)
  and the measured grid lands long before Monday's nightly. Until that line exists the script
  is run by hand; it re-anchors to the latest session, so an off-day run is simply a
  re-validation as of that day.
  **Grid enqueued on the live store: jobs 107–121** (15 books), priorities **170/172/174/176**
  staggered by measured cost (ETF sleeves first, `mr_overlay` last) — strictly BELOW the
  nightly archive/miner jobs (100–130) and the historical-backtest grid (140–165), so a
  walk-forward can never delay a nightly stage. Job 106 (the signals backfill) had already
  drained, so nothing was forced to run concurrently; **the grid will drain with tonight's
  nightly farm section** (post-sync, 4 h budget) and each night's reports are committed by
  the FOLLOWING night's sync, same as the backtest farm.
  **KNOWN LIMITATIONS (documented, deliberately not built now).**
  (i) *`macro_composite` is excluded* — its inputs are point-in-time by `fetch_as_of` and the
  production backfill honestly stamps `fetch_as_of = today`, so a historical replay sees an
  empty signal table and the book is inert rather than wrong. It needs the labelled
  `--pit-lag` reconstruction backfill (D-MS2) before it can be walk-forwarded. `pead_ear`
  (no historical earnings dates) and `discretionary` (human book) are excluded for the same
  reasons the backtest farm excludes them.
  (ii) *Same survivor-universe and static-cap caveats as the backtest farm*, disclosed at the
  top of every walk-forward report — which is why **vs EW on the same universe, fold by
  fold** is the headline comparison and absolute return is context.
  (iii) *Out-of-sample in the DATA, not in the RULE.* These books were written by someone who
  has lived through this market. The league's live forward record is still the only true
  out-of-sample evidence; this report answers the narrower question of whether a rule is
  behaving now the way it behaved on the sessions immediately before.
  (iv) *No cross-fold significance test.* Six validate windows is enough for a win rate and a
  median, not for a t-stat worth printing. Bootstrap robustness is item 13(b) and stays
  there.

- 2026-08-04 (pm) · **Five agentic self-improving books built, proven and live** (spec: store
  `trading/trading-engine/agentic-strategies-design.md`). Branch `agentic-strategies`, four
  commits `993cbc0` (configs + `sleeve_alloc`) → `0fceee9` (the entry gate) → `b79bf4c`
  (charters + validator + autopsy + both harnesses) → `5f42c19` (nightly report stage),
  merged no-ff as `a097fdf`. **Working tree left on `master`.**
  **The shape.** Five books whose CORE IS CODE and whose agent may only make bounded,
  pre-registered adjustments, each measured against a frozen twin and nothing else:

  | Book | Algo | Agent role | Twin |
  |---|---|---|---|
  | `news_gated_momo` | `momo_stopped` | daily veto/downscale on adverse news | `momo_stopped` (live) |
  | `adaptive_mr` | `mr_overlay` | weekly tune of 5 params | **new** `adaptive_mr_frozen` |
  | `agentic_alloc` | **new** `sleeve_alloc` | weekly sleeve weights | **new** `agentic_alloc_frozen` |
  | `stop_tuner_turtle` | `turtle_breakout` | weekly stop geometry | `turtle_breakout` (live) |
  | `earnings_context_pead` | `pead_ear` | daily reaction-class veto/downscale | `pead_ear` (live) |

  **Decisions.**
  (D-AG1) *The twin for books 1/4/5 is the PRE-EXISTING live book, not a fresh clone.* It runs
  the identical algorithm and already has a forward record; a second clone would burn a book
  slot to answer a question the existing one answers. The cost is a 7-session inception gap
  (twins 07-28, AI books 08-03), so **every spread is computed on the COMMON WINDOW** — both
  curves rebased to 1.00 on the first session both have equity. Books 2 and 3 get purpose-built
  twins instead: `mr_overlay`'s record carries the pre-fix `trading_days_between` calendar-bug
  artefact, and the sleeve allocator has no ancestor at all.
  (D-AG2) *The gate is a FILE the strategy reads, not a model call inside the nightly.* A
  `claude -p` call inside `generate_orders` would put an LLM, a network dependency and a quota
  on the critical path of the FATAL league stage. A file written 50 minutes earlier by an
  independent fail-soft session cannot break the nightly at all: **no gate file means pure
  algo**, and that is the behaviour on every failure path.
  (D-AG3) *Bounds live in the charter and are parsed FROM it.* One source of truth, so the
  numbers a human reviews in `agents/<book>/charter.md` are literally the numbers
  `agents/validator.py` enforces. There is no second bounds file to drift.
  (D-AG4) *Tuner proposals are ALL-OR-NOTHING; gater proposals are two-severity.* Partially
  applying a tuner proposal would apply a change stripped of the reasoning that justified it,
  and the rationale stored beside it would then describe something that never happened. For a
  gate, discarding nine sound vetoes because a tenth row was malformed is worse than the
  malformed row — so file-level violations (wrong book, too many decisions, veto share above
  the cap) reject the whole gate, row-level ones drop that row and are logged.
  (D-AG5) *Registered cross-checks the bounds alone cannot catch.* `weight × max_concurrent
  ≤ 1.00` (0.15 and 8 are each in-bounds but their product is 120% of equity — `apply_fill`
  would clamp it to cash and the book would silently run at a different concurrency than its
  config claims) and `trail_mult ≥ stop_mult` (a trail tighter than the initial stop trails a
  position out before it was ever at initial risk). Anything checkable in code is checked in
  code, never left to the model's judgement.
  (D-AG6) *The cash sleeve holds BIL, not idle cash.* Idle cash earns 0% in this engine by
  design; a cash sleeve that earns nothing would make "be defensive" a structural loser and
  would understate what a real cash allocation does. BIL is already priced and already
  dividend-credited — the same proxy `dual_momentum` uses.
  (D-AG7) *The agentic report is NIGHTLY, inline, between the E1 stage and sync.* The
  AI-minus-twin spread is the only number that decides these books' fate at 2027-02-01, and a
  number the owner sees every morning is a number nobody can quietly re-baseline later. Pure
  render, read-only, seconds — so it does not belong in the §12.7 queue — and `|| WARN` so
  reporting can never block trading data.
  (D-AG8) *The tuner's evidence diet includes same-STRATEGY peer books, labelled.* An AI book
  and its purpose-built twin are both born on day one, so for their first weeks NEITHER has a
  closed trade and the tuner has literally nothing to read. The ancestor running the identical
  module has weeks of trades. Peer records are presented as evidence about the ALGORITHM, never
  about this book's spread — and the first real session honoured exactly that distinction.
  **Evidence — every proof ran on a COPY. The live store was opened read-write exactly once,
  by the production `--init`.**
  * *Twin safety, the strict version.* `git archive master` into a scratch tree, two
    byte-identical copies of the store (`md5sum` equal), `python -m sim.league --rerun
    --date 2026-08-03` under each code tree. **All six sim tables byte-identical across all 17
    pre-existing books** (`sim_orders` 329, `sim_fills` 325, `sim_equity` 161, `sim_positions`
    236, `portfolios` 17, `sim_dividends` 0) and `league.md`/`league.csv` identical by `diff`.
    This matters more than usual tonight: the 15 pending walk-forward jobs (107–121) import
    strategy code from the working tree.
  * *`--init` on a copy* created the 7 new books **plus `macro_composite`** — the latter was
    already queued for tonight's `--init` by the 2026-08-04 merge and is not something this
    build introduced. One league step ran clean, 25 books, exit 0.
  * *The sleeve allocator, hand-checked.* Replayed the real week-signal session 2026-07-31 on
    a rewound copy: **BIL 25.00% ($9,750) · XLE/XLK 8.33% each · XLV 16.67%** (8.33% as a trend
    pick *plus* 8.33% as a defensive holding — the accumulation path) **· XLU/XLP 8.33% each ·
    total deployed 75.00%**, because SPY's RSI(2) was not below 30 so the MR sleeve correctly
    sat in cash. AI book and frozen twin identical at equal weights, as they must be at
    inception. Filled 6/6 on 08-03.
  * *Three REAL `claude -p` tuner sessions, and all three declined to change anything —
    correctly.* `stop_tuner_turtle` and `adaptive_mr` against the live store's data both
    returned no-change citing zero closed trades. The second `adaptive_mr` session, after the
    peer-autopsy widening (D-AG8), reasoned properly from the peer record: *"time-stop hit rate
    0.00%, hold median 2.0 sessions vs a 10-session stop — the time stop is simply not binding,
    which argues for leaving it alone, not moving it."*
    **Then the one worth writing down.** To exercise the apply path, a synthetic autopsy
    fixture was built on a copy (14 manufactured round trips, every one held exactly 10
    sessions, 100% time-stop rate — a screaming "loosen the time stop" signal). The session
    **detected the fixture and refused it**: *"the tickers are alphabetically consecutive,
    every one of the 14 was held exactly 10 sessions, and the time-stop rate reads 100.00%,
    while the same algorithm running live in mr_overlay has a median hold of 2.0 sessions and a
    0.00% time-stop rate … I will not tune off that block"* — and wrote a lesson saying so.
    The prompt's "never invent a number / unavailable is absent evidence, not neutral" rules
    are doing real work. It also means **the apply path could not be proven from a model
    output**, so it was proven from a hand-written proposal instead, labelled as such.
  * *Validator, both directions, against a copy.* In-bounds `time_stop 10 → 12` → **APPLIED
    v1 → v2**, `portfolios.config` params now carry `agent_version: 2` and
    `agent_version_since: 2026-08-04`. Out-of-bounds `rsi_max → 30` (registered [5,15]) →
    **REJECTED**, config untouched, still v2. Both rows in `changes.jsonl`. Unit-level: 21
    bounds cases exercised — step cap, change count, integer typing, unlisted parameter, wrong
    book, both cross-checks, and every simplex constraint (per-sleeve cap, sum, turnover,
    missing keys).
  * *A REAL `claude -p` gater session against today's ACTUAL news brief.* `news_gated_momo`
    had 0 candidates so the wrapper skipped the call entirely (no quota spent).
    `earnings_context_pead` saw 8 candidates and classified all eight `unclear` with **zero
    vetoes** — *"none appears in today's 133-headline brief (the only direct name hit is BMY,
    which is not a candidate)"* — which is charter D-A5a working exactly as registered:
    `unclear` defaults to TAKE, because vetoing the unexplained would quietly turn a PEAD
    sleeve into a large-cap PEAD sleeve as a function of news coverage.
  * *The gate MECHANISM, proven separately with a hand-written gate file* (veto SNAP,
    downscale TWST ×0.5) through a full league step on two copies: **exactly one book's orders
    changed.** SNAP's 309.52-share buy gone, TWST 15.4364 → 7.7182 (exactly ×0.5), six
    candidates untouched; the frozen twin `pead_ear` and all 24 other books byte-identical, and
    `sim_equity` and `sim_fills` identical across every book.
  * *Live store integrity after `--init`.* `prices` 19,866,576 · `sim_equity` 161 ·
    `sim_fills` 325 · `sim_orders` 329 · `sim_positions` 236 — **all unchanged**; `portfolios`
    17 → 25, the only table that moved. The 15 pending walk-forward jobs (107–121) untouched,
    no `.wal` left. The new books have 0 equity rows and 0 orders until tonight's nightly.
  **Scraper feeds widened 4 → 11** (`~/news-scraper/stock_news_scraper.py`; that directory is
  deliberately NOT a git repo, so the change is documented in a new `~/news-scraper/NOTES.md`
  rather than committed). The four original feeds are kept unchanged; added five Yahoo
  headline feeds covering the owner's watchlist and two macro/business feeds (MarketWatch
  MarketPulse, Federal Reserve press releases). Every added feed was verified to return real
  items from this box BEFORE being added, not merely to return HTTP 200. Yahoo's multi-symbol
  form works and genuinely mixes symbols, but caps at ~20 items per feed — hence five small
  thematic groups rather than one 13-symbol feed where the newsiest name would crowd the rest
  out. Restarted (`kill $(cat scraper.pid)` + `ensure_scraper.sh`; the hourly watchdog will not
  do it for you, since from its point of view a live scraper is a healthy one):
  **`START pid=525401 feeds=11`, first cycle `new_items=145`, all 7 new feeds represented**
  (fed_press 20 · mw_marketpulse 30 · wl_data 18 · wl_exchanges 20 · wl_megacap 17 ·
  wl_security 20 · wl_semis 20; the original four contributed 0 because their items were
  already deduped — correct).
  **Cron appended** (`crontab -l` + append + reload; the 11 pre-existing lines verified
  byte-identical afterwards):
  ```
  40 21 * * 1-5 …/agents/run_gaters.sh >> …/logs/agentic-gater-cron.log 2>&1
  30 10 * * 0   …/agents/run_tuners.sh  >> …/logs/agentic-tuner-cron.log 2>&1
  ```
  **KNOWN LIMITATIONS (documented, deliberately not built now).**
  (i) *The apply path has never been exercised by a model-authored change* — all three real
  sessions correctly declined, which is the right behaviour at 13 sessions of league history
  but leaves that path proven only by hand. First genuine test is a Sunday tuner cycle with
  real closed trades behind it.
  (ii) *A veto's counterfactual is only observable through the twin.* The hit-rate report scores
  a veto only when the twin actually bought the name; a veto on a name the twin never took is
  reported as unscored rather than assumed correct. Downscales are excluded from the hit rate
  entirely — they change size, not selection.
  (iii) *The candidate preview the gater sees is the LAST STORED session's*, because at 21:40
  UTC today's bars are not collected yet. Vetoes are by ticker, so a decision on a name that
  does not end up proposed is simply inert — but the agent is choosing from an indication, not
  a promise, and the prompt says so.
  (iv) *`macro_composite` and `pead_ear` are excluded from walk-forward*, so two of the five
  books' tuner sessions will read "walkforward unavailable" for a while yet.
  (v) *Books were created with `created = 2026-08-03`* (the store's MAX(date) at `--init`
  time), a day before the charters' registration date. Immaterial to the 26-week clock, which
  runs to a fixed 2027-02-01, and the spreads key off `sim_equity`, not `created`.

## Next

1. ~~Verify the miners bootstrap~~ **DONE 2026-07-18 pm** (see above — fundamentals 4,118,
   earnings 2,768, gate live on real data, skip-if-done smoke tests pass).
2. ~~Monday 2026-07-20 first full unattended nightly~~ **FAILED — see 2026-07-24 incident
   above; fixed and replayed same week.** Verify Saturday that Friday 07-24's 22:30 UTC cron
   ran clean end-to-end (collect → screen → league → sync → farm incl. Friday fundamentals):
   fills present, league.md advanced to 07-24, farm section says OK, no TODO breadcrumb.
3. **Mission "Done" gate**: 7 consecutive clean unattended nightly runs — **counter reset,
   now counting from Friday 2026-07-24** if clean. Watch `logs/cron.log` daily; any failure
   resets the count.
4. **M1 exit** still needs the GitHub remote (owner action: create `ong6/trading-engine`, then
   `git remote add origin ssh://git@ssh.github.com:443/ong6/trading-engine.git`; sync.py
   pushes automatically once a remote exists; then prove a pull on another machine).
5. **Watch Fri 2026-07-31's nightly log closely** — first-ever production execution of the
   monthly sleeves (dual_momentum ×2, ew_benchmark: 0 orders since inception; `generate_all`
   cadence-gates before `get_strategy`, so their `generate_orders` has never run live).
   2026-07-24 independent read-only audit (post-incident): both fix commits verified correct
   (no-op strategy sound — fills/MTM don't touch the strategy object; ORDER BY/LIMIT rewrite
   semantically identical to the MIN/MAX it replaced, and the only vulnerable in-txn query),
   no new crash defect found; monthly paths read sound (empty-history and zero-price guarded)
   but are the one genuinely unexercised seam, landing inside the 7-clean-run streak.
   **2026-07-28 update: 07-31 is now a bigger night** — the three new monthly books
   (sector_momentum, low_vol, high_52wk) also fire their first live signals then, alongside
   the weekly rebalances. All were month-signal-exercised in the 06-30 shakedown step
   (low_vol legitimately inert until a fundamentals snapshot with as_of ≤ month-end exists —
   07-31 will have 07-18+ snapshots, so it goes live for real).
8. **Watch tonight's (2026-07-28) nightly** — first unattended run with the six new books:
   `--init` creates them, then turtle_breakout / momo_stopped / pead_ear generate their
   first live daily signals. New code inside the 7-clean-run streak (counter: 2/7 as of
   Mon 07-27) — shakedown-proven on copies, but per the 07-24 lesson the live store's
   runtime-created rows are the seam to watch. Also confirm mr_overlay's behavior change
   post calendar-fix (holds now reach up to 10 sessions; its pre-fix record was effectively
   1-day holds — noted in its forward interpretation).
9. **Corporate-actions backfill is enqueued as job 18** (`actions`, priority 130, params
   `{"mode": "backfill"}`) — the farm drains it at the tail of tonight's 2026-07-29 nightly,
   after intraday and earnings. ~12,105 distinct tickers in `prices` at ~0.5 s/name ≈ **1.5–2 h**
   (same throughput class as earnings), inside the 4 h drain budget and resumable off
   `actions_fetch_log` if it is interrupted — per the 07-18/07-24 lesson, if it has to be
   restarted by hand use `nohup` or a harness-tracked background shell, never a bare `&`.
   **Watch for on Thursday 07-30:** (a) the backfill lands thousands of historical splits, so
   *Thursday's* reconcile is the big one-time adjudication pass — expect a burst of
   `skipped_ambiguous`/`skipped_sanity` TODO lines (capped at 20 in the log, all of them in
   `audit_log WHERE actor='actions.reconcile'`) and expect `rows_restated=0`, since real
   history reads as already-restated; a NON-zero rows_restated on a name we hold deserves an
   immediate look. (b) That pass is measured at 17.4 ms/candidate (~3 min for 10k splits) but
   it now sits in front of the league on a FATAL stage — if it ever grows past a few minutes,
   move it behind the league or make it incremental by ex_date.
10. **Fri 2026-07-31 is now the payoff night for this work** — `dual_momentum`'s first-ever
   live monthly signal runs against a REAL BIL hurdle (+3.72% total vs −0.09% price) instead
   of the degenerate "> 0" one, and `sector_momentum`'s first signal ranks the SPDR sleeves on
   total return. Confirm in the log that the actions stage ran before the league and that
   BIL/SPY/EFA/XL* all have current dividend rows; sanity-check that whichever sleeve GEM
   picks is consistent with the printed 12-mo total returns.
11. `engine/collect.py` still fetches `auto_adjust=False` + `period="5d"` INSERT OR REPLACE.
   That is now *handled* (the reconciler is the compensating control) rather than fixed at
   source. If collection is ever re-architected, the cleaner design is a periodic full
   re-fetch per name, which would make restatement unnecessary — worth revisiting, not urgent.
6. Latent fragility (audit finding, not currently triggerable): a portfolio row with
   NULL/non-JSON `config` crashes the league stage — `generate_all` does
   `json.loads(cfg_json)` unguarded (league.py:148). Both insert sites always write JSON
   today; guard it (skip + WARN) next time league.py is touched.
7. Nice-to-haves surfaced this session (not blocking): `lxml` for historical earnings
   surprises; post-farm second sync if a same-night intraday `_meta` commit is wanted;
   ~~walk-forward re-validation job type for active league strategies (weekly, §12.3)~~
   **DONE 2026-08-04** (`farm/walkforward/`); weekly-review integration (exec-design §6
   Sunday loop) — the walk-forward half now exists and is the input that loop was waiting
   for; still to wire: `/watchlist-scan` + `/trading-review` alongside it, plus
   `farm/execution_drag.py` (item 14).
12. **E1 forward record: check the first unattended write on Monday 2026-08-03's nightly.** The
   two rows on the board now were written by hand-run production commands; 08-03 is the first
   time the `experiment` stage fires from cron. Confirm in `logs/run-2026-08-03.log` that the
   stage sits between league and sync, that it prints `+oos 2026-08-03`, and that the sync
   commit that night includes `data/reports/experiments/e1-spy-monday-forward.md`. A
   non-Monday nightly should print "no new settled Mondays" and nothing else. **The kill
   evaluation is at n=40 — roughly 2027-05, ~10 calendar months out given holiday Mondays —
   and until then the correct action on any interim number is none.**
13. **Compute-utilization gap (owner audit 2026-07-29): the box is the mission's most
   underused asset.** 32 cores / 62 GiB, load-avg ~0.16, nightly busy ~26 min/weekday —
   §12.3's compute goal ("work the box fully") is not met. The remaining designed-but-unbuilt
   §12.3 workloads, in priority order: (a) weekly walk-forward re-validation of every active
   league rule (feeds the Sunday review loop, exec-design §6) — **DONE 2026-08-04**
   (`farm/walkforward/`, job kind `walkforward`, 15-book grid enqueued; see the entry above.
   Open follow-ups: install the Sunday cron line, and revisit once `macro_composite` has a
   `--pit-lag` signal reconstruction to walk-forward against); (b) weekend
   deep sweeps (parameter grids, bootstrap robustness, regime splits, cost-sensitivity)
   through the job queue at ≤24 nice-19 workers — **PARTLY DONE 2026-07-29**: the queue-driven
   farm workload now exists (`farm/backtest/`, job kind `backtest`, 78-job grid enqueued at
   priorities 140–165) and its first workload — replaying every league book over 6mo/1y/3y/5y/
   15y windows — is built and proven; **parameter grids, bootstrap robustness, regime splits
   and cost-sensitivity are still open**, as is walk-forward re-validation; (c) generalize the
   E1 forward runner's rule dispatch so the next pre-registered experiment doesn't need new
   plumbing — **STILL OPEN**. All run behind §12.7 caps; none block the mission's Done gate.
15. **DONE 2026-08-04 (merge + backfill enqueued/draining; watch tonight's nightly for the
   signals stage + league `--init` creating the book).** Original item:
   **Merge `macro-composite` after Fri 07-31's nightly verifies clean** (streak intact,
   monthly sleeves fired correctly): `git merge --no-ff macro-composite`, then run the one-time
   signals backfill on the live store through the queue (`queue_runner.py --enqueue signals
   --params '{"mode":"backfill"}'` + drain, ~15–20 min network time), then league `--init` on
   the next nightly creates the book — first live weekly signal the following Monday. Watch
   the first nightly with the signals job for per-source WARNs (AAII/Imperva expected
   occasionally). Owner decision pending: free FRED API key for full hy_oas history.
14. **Fold `farm/execution_drag.py` into the weekly review loop** (exec-design §6) once the
   7-clean-run streak completes — a one-line stage or a review-skill step; until then run it
   manually. Revisit the MOC close-execution question only when its pre-committed decision
   rule (adverse drag, t > 2, n ≥ 100 per book) actually triggers. Intraday stop-check A/B
   variants: deferred until momo_stopped's close-checked stop has a judgeable record — the
   coarser A/B answers first whether stops help at all.

16. **Agentic books — the three dates that matter.** (a) **First live gater session tonight,
   2026-08-04 21:40 UTC** — the first time `agents/run_gaters.sh` fires from cron, ~50 minutes
   ahead of the nightly. Confirm in `logs/agentic-gater.log` that both books are found in the
   store, that a gate file is written (or an honest "0 candidates / no claude call" line), and
   that the 22:30 league stage prints a `[gate]` line for `news_gated_momo` and
   `earnings_context_pead` — "no gate file — fail-open" is a perfectly good outcome and is what
   the twins' code path must keep looking like. Also confirm the new `agentic-report` stage runs
   between `experiment` and `sync` and that `data/reports/agentic/` lands in the night's sync
   commit. (b) **First Sunday tuner cycle, 2026-08-09 10:30 UTC** — the first cycle behind a
   real walk-forward grid (jobs 107–121 drain tonight), so it is also the first time the tuner
   prompt has out-of-sample evidence in it rather than "unavailable". Watch for whether any
   book proposes an actual change: three real sessions so far have all declined, correctly, and
   **the apply path has still never been exercised by a model-authored proposal.** (c) **26-week
   evaluation, 2027-02-01** — AI vs frozen twin, net of costs, on the common window. Until then
   the correct action on any interim spread is none; the number is published nightly for honesty,
   not for steering. A book that trails loses its AGENT LOOP, never its algorithm.

## 2026-08-18 · Agentic layer retired; NAAIM collector unregistered

- **The AI layer had been silently dead for 13 days.** Every `claude -p` session failed from
  **2026-08-05** through 2026-08-17 — the news analyst (10 consecutive weekdays), both daily
  gaters, and all three weekly tuners. Root cause was an **expired subscription OAuth token**,
  not a code fault: re-authenticating on 2026-08-18 and replaying the exact cron invocation
  (`--permission-mode dontAsk --strict-mcp-config --settings <deny-list> --max-turns 1
  --output-format json`) returned `is_error:false` on the first try. The fail-soft contract
  held perfectly — no gate file meant pure algo, every night, and nothing traded on stale or
  guessed input. **The defect was not the failure, it was the silence.** A 13-day outage
  surfaced only as `TODO:` lines in a log nobody tails; `data/_meta.json` never knew.

- **Decision: remove the agentic crons rather than repair them** (operator call, 2026-08-18).
  The token spend is not wanted. Removed from crontab: `news_analyst.sh` (11:00 weekdays),
  `run_gaters.sh` (21:40 weekdays), `run_tuners.sh` (Sunday 10:30). The nightly, the weekly
  walk-forward, and the RSS scraper watchdog are untouched. The scripts and charters stay on
  disk, unreferenced — re-enabling is a crontab edit, not a rebuild.

- **Consequence: the five AI books and two frozen twins are retired** (`active = FALSE`, seven
  `portfolio_retired` rows in `audit_log`, actor `operator.retire_agentic`). With no agent
  driving them, `news_gated_momo`, `earnings_context_pead`, `adaptive_mr`, `agentic_alloc` and
  `stop_tuner_turtle` are byte-identical to their controls, and `adaptive_mr_frozen` /
  `agentic_alloc_frozen` have nothing left to control for. The league goes 25 → 18 books.
  **These books were RETIRED, not KILLED.** The pre-registered 26-week criterion (2027-02-01,
  AI vs twin net of costs) never accrued valid evidence: the AI acted on exactly one session
  (2026-08-04) out of ~15 since inception, which is why the pairs sat at identical returns
  (+3.66%/+3.66% and +0.96%/+0.96%) in the 08-17 standings. Reporting that spread as an AI
  result would have been the dishonest outcome. `sim_equity` history is preserved; the books
  simply stop stepping, stop generating orders, and drop out of `league.md`.

- **NAAIM unregistered from `SOURCES`.** It never stored a single row — `macro_signals` holds
  **0 rows** for `naaim_exposure` — and **no strategy reads the series** (`macro_composite`'s
  four blocks are breadth / credit / VIX term / macro). NAAIM replaced the `.xlsx` download
  with a Symfony widget, so the href scrape could not match and raised a WARN on every nightly.
  Retiring it costs nothing and takes the nightly to zero signal warnings. The replacement
  source is recorded in `src_naaim()`'s docstring for whoever wants it back —
  `https://index.naaim.org/embeddable/table`, ~131 weekly rows — with the caveat that
  **that widget's own freshest row was 2026-05-13**, i.e. NAAIM is ~3 months stale at source.
  Give the series a reader before giving it a collector.

- **`stooq` is permanently blocked, and the flag was never a probe.** `collect.py:311` writes
  the literal string `"blocked"`; it has never reflected a live check. Verified 2026-08-18:
  stooq now answers with a JavaScript proof-of-work browser challenge, so it is unusable
  without a headless browser. Price collection is therefore **single-sourced on yfinance** —
  not a data-loss issue today, but the redundancy the design assumed does not exist.


## 2026-08-18b · Two drawdown probes on the EW basket; bounded parallelism in the queue

- **What the live league can and cannot say.** Asked to "adjust strategies since we have been
  running on live markets for a while", the first honest step was to measure how much evidence
  actually exists. It is 22 sessions for the oldest book and **15 for the current leader**
  (`momo_stopped`, 37 fills). Testing every active book's daily excess return vs `spy_benchmark`:
  **not one book reaches |t| = 2.** The leader sits at t = +1.06, `mr_overlay` at t = +0.04.
  Nothing here is distinguishable from luck, so **no existing book was tuned, re-weighted or
  killed on live P&L** — doing so would be fitting to three weeks of noise and is exactly what
  the pre-registration rules exist to prevent. Existing books keep their frozen parameters.

- **What the walk-forward CAN say**, over six folds and eight years: `ew_benchmark` posts
  +30.55% mean validate return and **no active book beats it in more than 50% of folds**. The
  momentum family is the only one with positive mean excess (top5 +32.85%, top10 +11.50%,
  momo_stopped +4.79%) and it buys that with −48% to −69% worst-fold drawdowns. Every other
  family is strongly negative vs EW (mr −25.09%, turtle −25.37%, low_vol −19.95%, dual momentum
  −16.92%). **The screen is the edge; most rules layered on top subtract from it.** EW's one
  real weakness is a −36.48% worst-fold drawdown, so that is what the new books attack.

- **Two books pre-registered 2026-08-18**, both changing exactly ONE thing versus `ew_benchmark`
  so any spread is attributable to the rule under test:
  * `ew_voltarget` — same basket, weights proportional to 1/sigma over 60 daily log returns,
    single name capped at 3x equal weight; names with <40 bars or zero measured vol are
    EXCLUDED rather than guessed.
  * `ew_trend_gated` — same basket, held only while SPY > 200d SMA, otherwise **rotated fully
    into BIL**. Deliberately the STRONGER form of the house gate: the existing `*_gated` books
    only block new entries, which bought `template_top10_banded` just ~4pp of drawdown relief
    (−47.81% ungated vs −43.69% gated).
  Both carry a pre-registered expectation with an honest negative prior and a kill criterion,
  and both are judged against `ew_benchmark`, never against SPY.

- **First walk-forward evidence (ONE fold, 2025-08-15 → 2026-08-17 — preliminary, not a verdict;
  this window also overlaps the live league):**

  | book | validate | max DD | Sharpe |
  |---|---|---|---|
  | ew_benchmark | +36.70% | −36.48% | · |
  | ew_voltarget | +35.38% | **−31.72%** | 0.85 |
  | ew_trend_gated | +13.69% | −36.36% | 0.51 |

  `ew_voltarget` gave up 1.3pp of return for 4.8pp of drawdown — directionally the hypothesis,
  modest. `ew_trend_gated` gave up **23pp of return for 0.1pp of drawdown**, i.e. the honest
  negative prior written into its own charter is looking correct on the first window. Neither
  is judged until its pre-registered criterion has a full risk-off fold to bite on.

- **A bug the first walk-forward caught, and why it was silent.** `ew_voltarget`'s first replay
  returned "0 fills, +0.00%" — not an error, a book that did nothing. Cause: `NEEDS_SCREEN` in
  `farm/backtest/replay.py` is an explicit allow-list, and a strategy missing from it gets a
  scratch store with no screen results, so `latest_screen_date()` returns None and the book
  posts zero orders **silently**. Both new books added there, plus `ew_trend_gated: [SPY, BIL]`
  in `REQUIRED` so BIL's 2007-05 listing clamps the window floor instead of producing
  un-funded risk-off stretches. Re-run after the fix: 2,641 and 2,337 fills. **Prove by running.**

- **Bounded parallelism for `parallel_safe` job kinds.** The box is 32 cores and the queue drained
  at load 0.1-0.8 — one job at a time, by design ("sequential => one job"). `walkforward` and
  `backtest` are now flagged `parallel_safe` because they read the live store READ-ONLY and write
  only their own scratch plus JSON/markdown; every store-writing kind (intraday, signals,
  earnings, fundamentals, actions) stays strictly sequential and is never batched. `--jobs N`
  (default **1**, so nothing changes unless asked; hard cap 8) runs a batch as subprocesses, each
  with its own read-only connection — the parent releases the write lock for the batch and
  reopens it to record outcomes, since DuckDB permits many readers OR one writer, never both.
  Children never touch the `jobs` table, so a killed child is reclaimed by the existing orphan
  sweep. Batch width is additionally clamped by the SAME `ENGINE_RAM_BUDGET_MB` the sequential
  path uses.

- **Measured, and less than projected.** A 4-job batch ran in **114s against ~260s sequential —
  ~2.3x, not the ~5x first sketched.** Two reasons, both worth recording. (a) The original idea
  of parallelising *folds* is impossible: all folds of a book share ONE scratch DuckDB and wipe
  it between folds, so the only safe axis is ACROSS books. (b) A batch's wall-clock is its
  SLOWEST member — in that batch one fold took 90.6s while the other three took 22-29s. On the
  real weekly grid (20 books x 6 folds, ~3-4h sequential) the jobs are far more uniform, so the
  gain should be closer to the batch width; that is a projection, not a measurement.

- **Earnings fetch deliberately NOT parallelised.** It looked like the biggest win (~35 of the
  nightly's 72 min) until the reason showed up: `PER_NAME_SLEEP = 0.4` x 2,965 names = **1,186s
  of intentional politeness pause**, not inefficiency. Since `stooq` is permanently blocked,
  **yfinance is the sole price source for the entire engine**, and the nightly already finishes
  at 23:42 with ~10h of headroom before the next open. Trading ~25 min of idle-time wall clock
  for a rate-limit ban on the only data feed is a bad trade. Left alone, on purpose.


## Blockers

- **GitHub remote still needed (owner action).** The box has working SSH auth to GitHub as
  `ong6` (`~/.ssh/id_ed25519_github`, `ssh.github.com:443` available if port 22 throttles),
  but no GitHub CLI and no API token — `/usr/local/bin/gh` is an unrelated internal tool.
  Create an EMPTY PRIVATE repo, then `git remote add origin` + push; `store/` and `logs/`
  are already gitignored so the 2.9 GiB DuckDB stays local. Until then every commit and the
  entire BUILDLOG exist on exactly one disk.
