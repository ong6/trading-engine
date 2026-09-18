# BUILDLOG — trading-engine

Source of truth for build state. Read at the start of every loop iteration; trust this over
remembered state. Specs live in `../personal-data-store/trading/` (engine design §12 wins on
conflict; execution design §7 has exit criteria).

## Current phase: post-Done — forward evidence accumulating; recurring sweep allowlist empty; M1 remote pending

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
| gh CLI | **NOT AVAILABLE** — `/usr/local/bin/gh` is an unrelated internal tool, not GitHub CLI | repo is **local-only** for now; store's remote proves GitHub SSH (`ssh://git@ssh.github.com:443`) works, so a remote can be added once the owner creates the GitHub repo |
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


## 2026-08-18c · 10-fold protocol; the sweep farm; and where AI is worth spending

- **Walk-forward grid 6 -> 10 folds** (`protocol.N_FOLDS`), reaching back to 2014-08.
  Pre-committed and directional -- more evidence, never less -- and decided BEFORE re-running
  anything, because the 6-fold result was fragile in a specific, measurable way: drop the single
  2018-2021 window and template_top5 goes +32.9% -> -17.5%, template_top10_banded +11.5% ->
  -11.9%, momo_stopped +4.8% -> -12.4%. A protocol a single window can flip is measuring the
  window. 10 folds costs 15% of the universe (2,827 -> 2,391 tickers with the required history)
  and is affordable only because the grid now runs parallel.

- **`farm/sweep/` — parameter sweeps over the EXISTING strategy classes.** The walk-forward
  judged each book at the one parameter set it happens to be registered with; whether a book is
  bad or merely badly parameterised is a question live trading cannot answer in useful time and
  pure compute can. Six grids, 51 candidates, no new strategy code and **no tokens**. A sweep
  never creates or modifies a league book: it writes to `data/reports/sweeps/<grid>/`, and a
  candidate becomes a book only when a human pre-registers it with an expectation and a kill
  criterion like everything else.

  Two design choices carry the honesty here. (a) **Ranked by MEDIAN excess vs ew_benchmark, not
  mean** — the mean is what the 2018-2021 fold hijacked. (b) **The trial count is printed in
  every report**, because the best of 51 draws looks good whether or not any skill is present;
  that count is exactly the input `farm/stats.py:deflated_sharpe` needs, and a sweep number
  quoted without it is not a result.

- **A seam, not a fork.** `run_book(..., book=...)` lets a candidate be walk-forwarded without
  existing in `portfolios`. Production passes nothing and still reads the live row, which is the
  entire point of the walk-forward: it re-validates the rule the league is actually trading.

- **Two bugs the smoke test caught, both silent-by-default.** A candidate built with
  `config_json=None` threw deep inside the replay (`portfolios.config` is TEXT that
  `league.generate_all` json.loads), and a candidate with a null `cadence` would have produced a
  book that simply never fires — a plausible-looking 0% row rather than an error. Cadence is now
  read from the strategy registry. Same failure mode as the `NEEDS_SCREEN` bug earlier today:
  **in this codebase the dangerous outcome is not a crash, it is a book that quietly does
  nothing and reports a number for it.**

- **Where AI is worth spending, and where it demonstrably is not.** The layer retired this
  morning made ~18 `claude -p` calls a week to make per-trade gating decisions, and its apply
  path was never once exercised by a model-authored proposal — every session correctly declined.
  That is the shape of the mistake: **frequent, low-stakes, mechanically-decidable calls are the
  worst possible use of an LLM**, and they are exactly what a trading loop generates most of.
  The right split follows from what is scarce. CPU is abundant here (32 cores, load 0.17) and
  tokens are not, so anything a grid can decide should be decided by a grid. That leaves AI one
  job worth paying for: proposing *structurally new* rules — the search step no sweep can perform
  because a sweep can only vary parameters of rules that already exist. Cadence should be monthly
  and batched (one call proposing many candidates), reading the sweep and walk-forward reports as
  input and emitting candidate specs as OUTPUT — never touching a live book, never in the
  nightly's path, and always landing in the same human pre-registration gate as everything else.


## 2026-08-20 · A book that never traded is not a 0.00% return; and the drain stops holding the writer

- **The defect: four sweep/walk-forward rows published a flat equity curve as a result.**
  `voltarget`'s three `vol_lookback=20` cells were ranked at **-17.21% median excess,
  0.00% worst drawdown** over 10 folds. That is not a return. Those books placed **zero
  fills in every fold** and their equity sat at the initial cash for twelve years.
  `sim/strategies/ew_voltarget.py` fetches `lookback + 1` closes, so with `vol_lookback=20`
  every name fails the `min_obs=40` test, `inv_vol` comes back empty and the book returns
  no orders — forever. The grid varied `vol_lookback` while holding `min_obs` at 40, making
  three of nine cells structurally impossible to satisfy.

- **It had already reached a published verdict.** `earnings_context_pead` in
  `data/reports/walkforward/README.md` (2026-08-17): 6 folds, all `status: ok`, **0 fills**,
  printed as `+0.00% mean validate / -30.55% vs EW / **REVIEW**`. Disclosure 6 of that same
  report promises "books that cannot be replayed are absent, not zero. Nothing is faked to
  fill a row." It was not true. Root cause behind that one: `protocol.EXCLUDED` is keyed by
  **config_id**, and `pead_ear` is excluded there ("no historical earnings dates") while its
  AI twin `earnings_context_pead`, running the identical strategy, was not — an exclusion
  list keyed by config cannot cover a strategy's twins by construction.

- **This is the FOURTH instance of one failure class**, after the `NEEDS_SCREEN` allow-list,
  the null `cadence`, and the null `config_json`. Stated once, as the house rule it now is:
  **in this codebase the dangerous outcome is never a crash — it is a book that quietly does
  nothing and reports a number for it.** So the guard goes at the measurement layer, where
  it catches the instances nobody has thought of yet, not only at each new call site:

  * `farm/walkforward/runner.py` — a fold with `n_fills == 0` returns `status: "inert"` and
    a reason, never `"ok"`. `summarize()` carries `n_folds_inert` and excludes those folds
    from every statistic; `run_book` prints the inert count.
  * `farm/walkforward/report.py` — a book with no `ok` fold drops out of the summary table
    into "Books NOT walk-forwarded", named with its reason. Disclosure 6 is now true.
  * `farm/sweep/sweep.py` — a candidate with nothing rankable gets an **Excluded** table
    saying why, instead of the silent `continue` that dropped it off the page. A cell whose
    excess is exactly 0.00 in every fold is tagged _identical to the benchmark; not a
    result_ — `concentration/cap-50` re-runs `ew_benchmark`'s own params and was sorting to
    the TOP of a table ranked by median excess.
  * Grids take an optional `feasible` predicate. `voltarget` declares
    `min_obs <= vol_lookback + 1` and expands to **6** cells, not 9 — an impossible cell must
    not inflate the trial count that every result is deflated against.
  * `sim/strategies/ew_voltarget.py` raises on `min_obs > lookback + 1` rather than posting
    no orders forever. The live book (`min_obs=40, vol_lookback=60`) is unaffected.

  **Proof (run, not inspected):** `ew_benchmark` with `cap=0` — a config that genuinely
  selects no names — walk-forwarded over 2 folds returns
  `fold statuses ['inert','inert'] · n_folds_ok 0 · n_folds_inert 2 · mean_validate_total None`.
  Before the change that book would have reported +0.00% twice. The historical-backtest farm
  was checked for the same leak and is clean: **0 of 78** stored runs have `n_fills == 0`.

- **Re-ranked, and the answer did not change.** `voltarget`'s best of 6 genuine cells is
  `max_weight_mult-1.5, vol_lookback-120` at **+0.02%** median excess, 50% beat rate,
  -35.70% worst DD vs EW's -37.53%. Inverse-vol weighting buys approximately nothing; the
  three phantom rows were the only thing that made the grid look like it had a shape.

- **`momo_stop` sweep completed (9 trials, 10 folds).** Every cell is NEGATIVE on median
  excess vs `ew_benchmark`; best is `n-20__stop_frac-0.9` at **-3.19%**, beating EW in 30% of
  folds. The cells with positive MEAN excess (`n-5`, +8% to +14%) carry **-63% to -65%**
  worst-fold drawdowns — the 2018-2021 skew again, which is exactly why the ranking is by
  median. **`momo_stopped` is not badly parameterised; the rule does not clear the screen.**
  Its live +8.08% lead is 15 sessions and |t| ~ 1.1.

- **Four grids, 30 genuine trials, and the best median excess anywhere is +0.02%.**

  | grid | trials | best cell | median excess | beats EW | worst DD |
  |---|---|---|---|---|---|
  | banding | 9 | `band_rank-15__n-5` | -3.05% | 50% | -61.32% |
  | concentration | 6 | `cap-10` (cap-50 = the benchmark itself) | -0.39% | 50% | -48.19% |
  | momo_stop | 9 | `n-20__stop_frac-0.9` | -3.19% | 30% | -42.76% |
  | voltarget | 6 | `max_weight_mult-1.5__vol_lookback-120` | +0.02% | 50% | -35.70% |

  The 2026-08-17 walk-forward said the screen is the edge and rules layered on it subtract.
  The sweeps now say the same thing about those rules' PARAMETER SPACES, which is the
  stronger claim and the one the walk-forward could not make. `meanrev` and `turtle_stops`
  are the two grids left (jobs 209/210, draining).

- **The drain held the DuckDB write lock for 7h40m and the UI was down for all of it.**
  The 08-19 nightly finished its own stages at 23:42 as usual, then drained two sweeps
  in-process until **06:51:49Z** — through the whole night and into the next session.
  DuckDB is single-writer, so `GET /league` answered `503 database busy` the entire time,
  and the box ran at load 2.9 on 32 cores. Two causes, both fixed:

  * `engine/run_daily.sh` drained with a bare `--run` (width 1). Only
    `run_weekly_walkforward.sh` ever passed `--jobs`. The nightly now passes **`--jobs 4`**,
    so `parallel_safe` kinds run as read-only children while the parent RELEASES the writer.
  * **The parallel pre-pass inverted the queue's own priorities** and could not simply be
    switched on: it drained EVERY `parallel_safe` job before the sequential loop, so a
    priority-900 sweep would have overtaken the nightly's own priority-100 intraday pull.
    `cmd_run` is now a single index loop that batches only jobs **already adjacent in
    priority order** — parallelism widens a run, it can never reorder one.

- **The proof found a real bug in the pre-existing parallel path.** First batched run of
  jobs 209/210: both children died — one on
  `Could not set lock on scratch/wf__ew_benchmark/replay.duckdb.wal`, the other on a
  `corporate_actions.parquet` the first had just `rmtree`'d. **Every sweep injects
  `ew_benchmark` as its benchmark**, and `run_book` derived the scratch dir from the
  config_id alone, so two concurrent sweeps always collide on `scratch/wf__ew_benchmark/`.
  The weekly walk-forward's `--jobs 4` never hit this because its jobs are all distinct
  books. `scratch_dir` is now `wf__<config_id>__p<pid>`: folds of one book still share one
  scratch store (the invariant that matters), processes never do.

  **Proof after the fix** — `signals` (priority 105) ran alone, in-process, FIRST; then
  `[queue] --- parallel batch [209, 210] (sweep, load 2.9, free RAM 49.1 GiB) ---`; two
  distinct scratch dirs `wf__ew_benchmark__p2694022` / `__p2694023`; both children alive and
  progressing; **`GET /league` = 200, 200, 200** during the batch, against 503 for the seven
  hours before it. Load 6.36 vs 2.9 sequential.

- **`sys.stdout.reconfigure(line_buffering=True)` in `cmd_run`.** Redirected to a log the
  parent is block-buffered while its children (own processes, own buffers) write straight
  through, so a tailed drain log showed a sweep running with no record of the batch line
  that started it. Same lesson as the agentic outage: the defect is the silence.

- **The batch reacquire needed a longer lock wait than the 60s default.** Releasing the
  writer for a batch creates a window the old always-held design did not have: a batch can
  end inside a nightly's ~4-minute `collect` stage, and `db.connect`'s 60s retry budget
  would lose that race, crash the drain and bounce every batched job back to `pending`.
  `db.connect(path, wait_s=...)` now takes an explicit floor (the env var still wins when
  larger) and `_run_parallel_batch` passes **900s**.

- **Requeued 209/210 by hand** (`state='pending'`, `progress='requeued: scratch-dir
  collision fixed 2026-08-20'`) after the collision failure — an infrastructure fault, not a
  job fault, so re-running is the honest action rather than leaving two `failed` rows.

### Next

1. **`protocol.EXCLUDED` is keyed by config_id and should be keyed by strategy** (or checked
   against both). The inert guard now catches the consequence, but a twin of an excluded
   strategy still burns a full replay to learn what the exclusion list already knew.
2. **Every sweep re-runs `ew_benchmark` from scratch** — 977s in the `banding` job, 1361s in
   `momo_stop`, for a result identical in both because the protocol and anchor match. Cache
   the benchmark result by (protocol hash, anchor, n_folds) and a sweep gets ~20 min cheaper.
3. **Retire or re-scope the four regime-gated twins.** `mr_overlay`/`_gated`,
   `template_top5`/`_gated`, `dual_momentum`/`_gated`, `template_top10_banded`/`_gated` are
   identical to the cent in `league.md` because the regime has been risk-on every session
   since inception. Four books, four rows in every report, zero information until the first
   risk-off stretch. Not a bug — but the gate they test is untested, and the board should say
   so rather than printing the pair twice.
4. **The two EW drawdown probes fire their first orders at the 08-31 month signal.** Both are
   monthly and were created 2026-08-18, so `+0.00%` on the board is correct, not inert.
   Confirm fills on the 09-01 nightly.


## 2026-08-20b · Error bars change the answer; and the one axis nothing had varied

Six parallel tracks. The confidence track reframed the other five, so it goes first.

- **26 of 30 swept candidates are `INDISTINGUISHABLE` from `ew_benchmark`. Zero are
  distinguishably better. All four that separate, separate DOWNWARD.** 90% percentile
  bootstrap on fold excesses, 10,000 resamples, seed `20260820` printed in every report.
  The top `banding` cell — the `-3.05%` row that had been sitting at the head of a ranked
  table — has a CI of **[-11.83%, +27.06%]**, and its entire `+15.05%` mean excess is ONE
  fold out of ten: `[-13.7, +27.1, +5.0, +66.5, +160.7, -11.8, -11.1, -11.7, -71.3, +10.8]`.
  **That table's ordering carried no information and had been read as though it did.**

- **How much this test can actually see, measured rather than asserted** (2,000 simulations
  per effect size on the pooled empirical fold-excess distribution, sd ~30pp): the
  probability of returning `distinguishable +` is **20% at a true +2pp median excess, 36% at
  +5pp, 66% at +10pp, 93% at +20pp**. **50% power sits near +7pp/yr and 90% near +18pp/yr.**
  So "zero distinguishably better" would still be the outcome roughly two thirds of the time
  if a genuine +5pp/yr edge were sitting in the grid. The per-grid README already says this
  in prose — "can reject a large effect and cannot confirm a small one" — and the number
  belongs beside the headline: **this pass rules out large edges; it cannot rule out useful
  ones.**

- Same instrument on the LIVE book set: **every WATCH book is `INDISTINGUISHABLE`**, and
  every book that separates from EW loses to it. `template_top5`'s `+32.85%` mean excess
  carries a CI of **[-33.86%, +127.67%]**. The pre-registered PASS/WATCH/REVIEW rule is
  unchanged byte-for-byte; the interval sits beside it as new information, not a
  redefinition.

- `farm/stats.py:deflated_sharpe` **had never been called from the sweep path** despite
  `sweep.py`'s own docstring saying the trial count exists to feed it. Wired in, with a new
  optional `var_sr` so the sweep passes the observed cross-trial variance rather than the
  estimator fallback. Top `banding` cell: raw SR +0.243, SR0 +0.289, **DSR 0.437** against a
  ~0.95 bar. The folds are the resampling unit and the reports say plainly that adjacent
  folds share 12 months of TRAIN window, so an i.i.d. bootstrap **understates** the
  uncertainty — the intervals are a FLOOR, which makes an INDISTINGUISHABLE verdict
  stronger than it looks and a distinguishable one weaker.

- **`N_FOLDS = 10` is not a compute budget. It is the honest maximum.** The obvious reply
  to wide intervals is "run more folds", and it was tested rather than assumed. Distinct
  tickers in `prices`, first week of June: **1996 → 937** against a World Bank count of
  **8,090** US listed domestic companies that year. The store's counts include ETFs while the
  World Bank series counts operating companies, so the audit recomputed it EX-ETF via
  `universe.etf`: June 1996 holds just **18** ETFs, so the clean figure is **919/8,090 =
  11.4%** — the headline survives the apples-to-apples fix. The middle rows did NOT and are
  corrected: 2003 is **23.8%** ex-ETF (claimed ~26%) and **2014 is 42%, not ~55%**. ADRs and
  multiple share classes in the store would push all three lower still, which strengthens
  the argument rather than weakening it. Those 937 are not a sample — they are
  precisely the names that survived thirty years. Confirmed by looking for names whose fate
  is not in dispute: **LEH, BSC, ENE, WCOM, CFC, MER, NT, CPQ, SIVB, FRC, TWX, YHOO, MON,
  CELG, ATVI are ABSENT ENTIRELY.** Not one 2008 casualty is in the store. **Any backtest
  spanning 2008 is one in which Lehman, Bear Stearns, Countrywide and Merrill cannot lose
  money.** Folds 11-30 would reach into the 12-26% region where the answer is guaranteed to
  look good. The survivorship disclosure printed in every report as a flat "~+7pp/yr" is
  wrong in shape: the bias grows monotonically as the window moves back.
  **Consequence: the evidence ceiling is structural, not computational.** 32 idle cores
  cannot resolve a +0.5% edge from ten overlapping folds of survivor-only data. That is why
  30 trials found nothing and why the 31st would not. Full argument in
  `docs/evidence-ceiling-2026-08-20.md`. **Stop expanding parameter search; spend on data
  quality and on the forward record instead.**

### The one axis nothing had ever varied

Every rule ever tried here changes WHICH names are held or HOW they are weighted against
each other, always at 100% gross exposure. A -36% worst-fold drawdown is a MARKET drawdown,
and per-name reweighting cannot fix one because the names fall together. That is why
`ew_voltarget` bought 1.8pp of drawdown for +0.02% median excess.

Three candidates, monthly, judged against `ew_benchmark`, charters with honest expectations
and kill criteria in `docs/charters/`. **None is a league book** — promotion remains a human
pre-registration. 2-fold proof against the live store (read-only), vs EW's -36.48%:

| candidate | worst validate DD | fold 1 / fold 2 (EW: +10.18% / +43.13%) |
|---|---|---|
| **`ew_gross_voltarget`** — gross exposure scaled to target portfolio vol, rest in BIL | **-18.22%** | +6.15% / +27.52% |
| `ew_sector_capped` — max names per sector | -35.11% | +9.47% / +41.90% |
| `ew_dd_throttle` — cut exposure below a peak drawdown | -36.46% | +7.41% / **+1.81%** |

**Drawdown halved — and an adversarial audit the same day showed that headline is
OVERSTATED, so it is corrected here rather than left standing.** The book ran at
`vol_ann` **17.31% / 17.70%** against the benchmark's **37.02% / 56.24%**, i.e. roughly 47%
and 31% of the benchmark's risk. It hit its 15% target, so the mechanism works — but **most
of the drawdown relief is mechanical de-risking, not evidence that the TIMING adds
anything.** Tested against the alternative hypothesis (a STATIC partial-exposure blend
matched to the same drawdown): static wins fold 1 (+7.3% vs +6.15%) and loses fold 2
(+14.4% vs +27.52%, where a 60/40 would have matched the return at double the drawdown).
**Dynamic sizing beat its static equivalent in exactly one fold out of two — unresolved.**

Risk-adjusted it does lead in both folds, which is the defensible version of the claim:

| fold | book | ret | vol_ann | ret/vol | ret/\|DD\| |
|---|---|---|---|---|---|
| 1 | ew_benchmark | +10.18% | 37.02% | 0.27 | 0.31 |
| 1 | ew_gross_voltarget | +6.15% | 17.31% | **0.36** | **0.34** |
| 2 | ew_benchmark | +43.13% | 56.24% | 0.77 | 1.18 |
| 2 | ew_gross_voltarget | +27.52% | 17.70% | **1.55** | **2.40** |

**The honest statement: de-risking halved the drawdown and improved risk-adjusted return in
both folds; whether the vol-TARGETING beats simply holding less equity is 1-for-1 and
unresolved at n=2.**

**The control was then built and RUN** (`ew_static_exposure`, same basket at constant gross,
rest in BIL, no signal and no state), which replaced the audit's log-scaling approximation
with a measurement:

| fold (bench vol) | book | ret | vol_ann | max DD | ret/vol |
|---|---|---|---|---|---|
| **1** (37.02%) | ew_gross_voltarget | +6.15% | 17.31% | −18.22% | 0.36 |
| | **static @ 0.5** | **+8.50%** | 18.41% | −17.42% | **0.46** |
| **2** (56.24%) | **ew_gross_voltarget** | **+27.52%** | 17.70% | −11.48% | **1.55** |
| | static @ 0.5 | +26.23% | 27.55% | −18.32% | 0.95 |

**Fold 1 is a LOSS for the book.** At matched risk the dumb control returned +8.50% against
its +6.15% — the timing subtracted 2.35pp. **Fold 2 is a clear win**: the same return as the
control at **64% of its volatility** and two thirds of its drawdown. The discriminator is the
fold's own volatility, which is mechanistically what vol targeting is for.

**Pre-registered BEFORE the 10-fold grid runs** (charter amendment): the timing benefit
should correlate positively with the fold's benchmark realized vol; test by regressing
(voltarget − vol-matched static) on `ew_benchmark`'s fold `vol_ann`, bootstrap CI on the same
protocol. **Two points are not evidence for a correlation — they are the reason to write the
hypothesis down before there are ten.** Honest negative case: at n=10 this will very probably
return INDISTINGUISHABLE, and that is the evidence ceiling rather than a verdict.
**The book's comparison rule is superseded: it is judged against the vol-matched static
control, never against `ew_benchmark`, and its kill criterion now requires beating that
control on risk-adjusted return in ≥50% of folds.** No look-ahead — the vol estimate reads closes `date <= as_of` and fills
are t+1 open (audited, CONFIRMED). Against `ew_trend_gated`'s binary version — 23pp of
return for 0.1pp of relief — the continuous form is still a different animal.
**Any 10-fold grid MUST carry a static-exposure control**, or it will re-measure de-risking
and call it timing.
`ew_dd_throttle` did what its own charter's negative prior predicted — whipsawed to +1.81%
with **no** drawdown relief. Pre-registered, then observed.

- **Sector data exists but is NOT point-in-time** (`fundamentals.sector`, five weekly
  snapshots from 2026-07-18). `ew_sector_capped` therefore carries a static-sector
  look-ahead, disclosed loudly in the class docstring, the grid comment and the charter,
  mirroring `low_vol`'s static-market-cap disclosure. **Live: 37 of the top 50 by RS on
  2026-08-19 are Healthcare** — `ew_benchmark` holds that basket equal-weighted, so the
  "diversified benchmark" is currently a ~74% healthcare bet. That is a live risk fact
  independent of any strategy decision.

### Data quality

- **A second EOD source exists and is verified.** `api.nasdaq.com/api/quote/{T}/historical`
  is free, key-free and genuinely independent (Yahoo's chart API is what yfinance already
  wraps, so it is not redundancy). It agrees with the store **to the cent** on OHLC for both
  an ETF and a small-cap. `assetclass` is required and not guessable — SPY with `assetclass=stocks` returns
  `Symbol not exists`; the `universe.etf` column supplies it. Built as a VERIFIER, not a
  failover: a one-day yfinance outage costs nothing on a resumable collector, but a silently
  wrong split costs money and nobody would notice.
- **The volume gap is a SETTLEMENT LAG, not a tape difference — an earlier reading in this
  entry was wrong and is corrected here.** The first full verifier run flagged 46 of 175
  names at up to 180bp; every one sat on the `as_of` session and on open/high/low only.
  Re-probing the worst 18 across their settled sessions gave a worst gap of **3.1bp**, and
  **close never disagreed on any session anywhere**. Volume has the same shape: settled
  sessions match **to the share** (NVDA 2026-08-18: 103,128,200 both sides), only the newest
  session differs. yfinance captures same-day O/H/L and volume before the tape settles and
  then restates. **Shipping rule: on a settled session all four fields count; on `as_of`
  only the CLOSE counts** — that is the number the league marks books against — while O/H/L
  and volume are measured but never flagged, published as `provisional_ohl_max_bp` so the
  exemption stays auditable. Without that rule this stage would flag a quarter of the
  universe nightly and be ignored inside a week.
- **First real run: 175 checked, 175 agreed, 0 disagreed, 2 not_checked.** Tolerance
  (pre-registered in-file): >10bp relative AND >=1c absolute; Nasdaq publishes <=4dp so
  worst-case rounding at the $3 liquidity floor is 1.7bp, ~6x headroom, while every defect
  class targeted is 1-3 orders larger (a missed 2:1 split is 5000bp). **Detector proved to
  FIRE**, not merely to stay quiet: a corrupted stored close agrees at 5bp and disagrees at
  12bp / 50bp / 10000bp. A verifier that has never fired is indistinguishable from one that
  cannot.

### The verifier's first find: three live positions marked at a price that will never move

- **The 2 `not_checked` names are `EA` and `TALK`, and BOTH are HELD.** Both are
  `active = FALSE` in `universe`, both return `symbol_not_found` from the second source, and
  **EA's last stored print is 2026-08-10** — ten days stale. `high_52wk` holds EA (7.43sh)
  and TALK (298.85sh); `low_vol` holds EA (6.19sh). Their equity contains a number that will
  never move again.
- **`portfolio.mark_to_market` had computed and returned the `carried` flag since it was
  written, and `sim/league.py` never read it.** Not the log, not `league.md`, not
  `_meta.json`. The same defect this codebase keeps producing: the honest computation
  happens and the result goes nowhere. `mtm_all` now returns `{"carried": {pf_id: [...]}}`,
  prints a WARN naming every book and ticker, and `step` appends `carried_marks=N` to its
  summary line. `verbose` is threaded so a walk-forward replay does not print it per session.
  **Proof:** a scratch book holding one live and one dead name returns
  `{'carried': {'bookA': ['DEAD']}}`, still values the position at the carried close
  (equity 1610.00 = 1000 cash + 10x51 + 5x20), and prints nothing under `verbose=False`.
- **A carried mark is deliberately NOT an error.** A halted name resumes; a genuinely
  delisted one needs a human decision about the position, not an exception. The engine has
  no delisting handler — `sim/fills.py` covers a missing bar on the FILL date, nothing
  covers a HELD name that stops printing. That is now visible rather than silent, which is
  the prerequisite for deciding what to do about it.
- **Survivorship cannot be back-filled for free.** Nasdaq publishes no dated historical
  symbol-directory archive; SEC EDGAR's `company_tickers.json` is itself current-issuer-only
  (verified by the absence of SIVB and FRC from it). **`universe_snapshot` is the only lever
  that compounds** — append-only, 26 dates and 320,233 rows since 2026-07-16, and it fixes
  the future rather than the past.
- **Leveraged/inverse ETFs: 812 of 12,459 names flagged**, 265 liquid, from `universe.name`
  alone (recall 94/94 on a hand list, 0 false positives on a 33-name control). **Every
  stored screen has passed 6-25 of them**, median 17, 42 distinct tickers — including
  **`SPYU`, a 4X ETN, 15 times**. Four live books hold `DLLL` (2x DELL) today. Behind
  `--universe-policy ex-leveraged`, **DEFAULT OFF**, with the policy stamped on every
  `screen_results` row so two policies can never be silently compared. **Not flipped**: it
  would redefine `ew_benchmark`, invalidate 65 stored folds, cost 4 legitimate names to the
  RS percentile shift, and still not fix TNXP. Equivalence proof: a scratch run under `all`
  reproduces the live 2026-08-19 screen exactly (534 passers, identical set).

### The fill model — and why the fix is the clamp, not the prices

The premise going in was that the cash-clamp warnings meant systematic under-investment.
**That premise was wrong**, and the audit says so with numbers: steady-state idle cash is
5.3-47.4 bp and the drag is **1-3 bp/yr**. 88% of the gap is correct behaviour (slippage
plus overnight gap on a fully-sized book).

The real finding is in the tail. **436 of 2,634 rejects (16.6%) are leveraged/inverse ETFs
carrying 90.8% of all stranded cash**; 50 rejects strand >10% of a book. Cause, traced:
`collect.py:88` fetches `auto_adjust=False`, which still SPLIT-adjusts OHLC, so a name with
heavy cumulative REVERSE splits has its old prices multiplied without limit. `DRIP` spans
$35.57 to **$83,000**; `TNXP` — not leveraged at all — reaches **$19.2 BILLION** in 2012;
32 tickers exceed $100,000.

**Volume is divided by the same factor the price is multiplied by**, so median dollar-volume
is preserved (TNXP: $76.3M in 2018 at 2 shares/day, $20.5M in 2025 at 842k shares/day).
**The liquidity filter is therefore SOUND and the prices are not wrong** — back-adjustment
preserves returns, which is what a backtest consumes. Exactly one rule keys on absolute
price per share, and it is the bug: `sim/portfolio.py:128` does
`affordable = math.floor(cash / px)`, so a $39,000 book facing a $31.7M adjusted price
computes `floor(0.0012) = 0`, rejects, and strands the allocation.

**Decisive detail: the live books already hold FRACTIONAL quantities** (`template_top10_banded`
holds `DLLL qty 102.384263`). Every sizing path in the engine is fractional; the exec design
§2 specifies fills, slippage and the 1%-of-dollar-volume guard and says NOTHING about lot
size; `BUILDLOG.md:284` records the `floor()` as a 2026-07-18 negative-cash safety fix.
**Whole-share trading is incidental, not designed.**

**Decision: fix the clamp (`affordable = cash / px` plus a dust floor on the reject branch).
Do not touch the universe for this and do not "correct" the prices.** It resolves 90.8% of
the stranded dollars as a side effect, fixes TNXP-class names that the leverage exclusion
would NOT have fixed, and costs no legitimate names. It invalidates all 65 fold JSONs, the
sweep grids and the live record since 2026-07-17, so it lands **version-stamped
(`fillmodel=v2`) with a scheduled regeneration, never silently.** At 1-3 bp/yr there is no
urgency. Full reasoning: `docs/synthesis-price-adjustment-and-fills-2026-08-20.md`.

### Also

- **The sweep farm is on cron** (`0 6 * * 6`, `engine/run_weekend_sweeps.sh`). Grids are
  read from `GRIDS` itself, so the three new candidate grids sweep from the next Saturday
  with no edit — 9 grids, 19 new cells. Priority 900, `--jobs 4`, 12 h budget.
- **Walk-forward exclusions are keyed by strategy as well as config_id.**
  `earnings_context_pead` — the book that started all of this — now appears under "Books NOT
  walk-forwarded" with an honest reason instead of a `+0.00% / REVIEW` row.
- The batched drain held through five hours of live sweeping with the API answering **200**
  throughout, against 503 for the seven hours before the fix.

### Next

0. **Resolve EA and TALK.** Two books hold three positions in names that stopped printing.
   Decide the corporate action (EA looks acquired) and settle them to cash rather than
   carrying a frozen mark; then decide whether a delisting handler belongs in `sim/`.
1. **`fillmodel=v2`** — the fractional clamp, version-stamped, with a full regeneration.
2. **Run `ew_benchmark` under both universe policies and publish the pair** rather than
   flipping a default. Decide `SPYU` (4X ETN) on its own merits either way.
3. **Price-sanity reporting**: 32 tickers over $100,000 adjusted are not a bug to fix but a
   fact to surface — a book holding one should say so.
4. **The three candidates need their 10-fold grids** (Saturday's cron will run them) and
   then a CI before any promotion conversation. `ew_gross_voltarget` is the only one worth
   the conversation on current evidence.
5. **Report the survivorship bias as time-varying**, with each fold carrying its universe
   size. The flat "~+7pp/yr" understates the early folds badly.


## 2026-08-20c · Working the box from measurement; and phantom bars

- **The farm was throttled by a guessed constant.** A `sweep`/`walkforward`/`backtest` job
  declared `mem_mb = 8000`. Measured (VmHWM + 1 s sampling): **peak 3,409 MB**, steady-state
  ~1.55 GB — so the declaration was **2.3x the true PEAK**, and it was the active brake,
  because `per_batch = ENGINE_RAM_BUDGET_MB // widest` = `48000 // 8000` = 6, then
  `min(--jobs 4, 6)` = **4**. The box ran four workers on ~6 GB and ~15 cores out of 62 GB
  and 32.

- **Throughput matrix, measured** — identical 1-fold `ew_benchmark` replays, unit
  deliberately shortened to 187 sessions so the matrix fit the load budget (relative
  throughput is the point, and the shortening is disclosed); baseline load ~5.5 including
  the live sweep worker:

  | config | wall (8 jobs) | jobs/hour | peak 1-min load |
  |---|---|---|---|
  | 2 workers x 8 threads | 140 s | 205 | 10.6 |
  | 4 x 4 | 81 s | 355 | 13.0 |
  | 8 x 2 | 57 s | 505 | 15.1 |
  | 8 x 4 | 55 s | **523** | 22.6 |
  | 16 x 2 | 86 s (16 jobs) | 670 | 28.4, free RAM to 21 G |

  **WIDTH is the lever; DuckDB threads beyond 2-4 buy nothing** (8x4 ~ 8x2). 16-wide still
  gains but hits the load ceiling and, at production job sizes, `16 x 3.4 GB = 54 GB` on a
  62 GB box — infeasible. Set from this: `mem_mb` 8000 -> **4500** (measured peak + 32%
  headroom), `--jobs` 4 -> **8** in all three drivers, `threads` 8 -> **4**. Effective width
  **4 -> 8**, ~1.5x farm throughput at ~65% of the load ceiling.

- **`LOAD_5MIN_MAX` stays 28.0**, deliberately. Width 8 sustains 20-24 including nightly
  stages, and the guard **exits the drain** rather than waiting — a trip parks a Sunday grid
  until Monday — so margin is worth more than the last increment of width. Raising it would
  only matter at width >= ~10, which RAM rules out anyway.

- **Batch starts are STAGGERED 4 s, added on review of the measurement rather than from it.**
  The peak is not spread over a job's life: it lands in the first ~15 s, in
  `build_scratch`'s parquet export. Launching a batch simultaneously therefore **aligns all
  eight peaks** — the worst case, not an unlucky one. 8 x 3.4 GB arriving at once leaves
  ~1.9 GB above `FREE_RAM_MIN_GB`, and tripping that floor parks the rest of the drain.
  Four seconds between launches decorrelates the peaks and costs nothing against jobs that
  run minutes to hours.

- **The real idle capacity is the CALENDAR, not the width.** The box sits near load 2 for
  roughly 150 h/week outside a ~72-minute weekday nightly and the two weekend windows. Per
  the evidence ceiling, **more parameter search is not the filler** — the return on it is
  measurably ~zero — so the slot goes to data quality:
  `engine/run_weekly_verify.sh`, **Saturday 02:00 UTC**, widening the nightly's ~40-name
  price cross-check to the whole liquid universe (~2 h at the measured 2.4 s/name). Four
  cron entries now cover the engine: nightly 22:30 Mon-Fri, full verify Sat 02:00, sweeps
  Sat 06:00, walk-forward Sun 06:00.

### Phantom bars — the store contains rows that were never market data

- Chasing EA's stale mark turned up something worse than staleness:

  | date | close | volume |
  |---|---|---|
  | 2026-08-03 | 209.910004 | 4,470,400 |
  | 2026-08-04 | 209.699997 | **48,713,698** |
  | 2026-08-05 | 209.699997 | **0** |
  | 2026-08-06 | 209.699997 | **0** |
  | 2026-08-07 | 209.699997 | **0** |
  | 2026-08-10 | 209.699997 | **0** |

  EA's last real session was **2026-08-04** — volume roughly 10x normal, the acquisition
  close — at $209.70, then **four bars at that identical price with zero volume**, then
  nothing. **yfinance keeps emitting a dead quote as a bar after a name stops trading, and
  those rows are indistinguishable from real ones to every consumer in the engine.**
  `mark_to_market` sees a bar and does not flag a carried price at all; the stale-mark
  detector added earlier the same day reported EA as **7 sessions stale when the truth was
  11**. A dead position looked fresher than it was.

- Detector re-keyed on `MAX(date) FILTER (WHERE volume > 0)`. **`volume = 0` alone is NOT
  proof of a phantom** — `JONEU`, a thin SPAC unit, has 13 legitimate zero-volume days — but
  for a HELD position "has not traded since" is the honest measure of staleness either way.
  Scale measured: 5 zero-volume bars on the worst recent session, 2 liquid tickers with >= 3
  in fourteen days. **Narrow, not systemic — and it landed on a held position.**

- **EA looks acquired at $209.70 on 2026-08-04. It was NOT settled.** The engine has no
  delisting handler, and inferring acquisition terms from a price and a volume spike would be
  inventing a fact. It is on the dashboard with the frozen value and its share of equity
  (`high_52wk` 7.96% across EA + TALK, `low_vol` 3.38%); the decision is the owner's.

- **Independent confirmation of the settlement-lag call**: a live verifier run over 30 volume
  comparisons returns **median absolute difference 0.0%** on settled sessions, with the only
  over-tolerance reading on the newest session. The exemption is doing exactly what it was
  designed to do.

### Next

1. **Resolve EA and TALK** (unchanged, and now quantified on the dashboard).
2. **`ew_gross_voltarget` is judged against the vol-matched `ew_static_exposure` cell**, never
   against `ew_benchmark`, with the pre-registered vol-correlation sub-hypothesis. Saturday's
   sweep runs both grids.
3. **The historical-backtest farm is 22 days stale and its 78 stored runs are `fillmodel=v1`.**
   Deliberately NOT put on a cron — it is in-sample by its own title and re-running it weekly
   buys compute, not confidence — but its README should say which fill model produced it.
4. **Benchmark-result caching** (~20 min per sweep): every grid re-runs `ew_benchmark` from
   scratch under an identical protocol and anchor.


## 2026-09-02 · Audit session: seven simulator bugs, three corrupted histories, first tests, two new books

Owner-directed session from the store (not the build loop). Five parallel review agents,
then fixes; everything below was proven by running (repro scripts, pytest, live before/after).

### Simulator (`sim/`, `server/`) — commit 3b0268f

1. **No dividend had ever been credited.** Phase a0 matched `ex_date = d`; yfinance publishes
   a dividend the session AFTER its ex-date (`actions_fetch_log`: WBS ex 08-10 appeared 08-11,
   JNJ ex 08-25 appeared 08-26). `sim_dividends` had 0 rows against 26 entitled events, while
   `vs SPY` was computed against SPY's TOTAL return. Now a 10-day catch-up window keyed
   exactly-once on (portfolio, ticker, ex_date), entitlement reconstructed as of ex_date−1
   from `sim_fills`. **Backfilled live 2026-09-02: 26 credits, $230.42** (`engine/backfill_dividends.py`).
2. **Monthly/weekly cadence silently skipped period ends** whenever the live latest bar was not
   a Friday / the last calendar day (`weekday()==4`, `(d+1).month`). ~29% of month-ends and
   every holiday week; Jul/Aug 2026 happened to end on weekdays so no live damage yet, but Oct
   2026 (ends Saturday) would have skipped every monthly book. New `sim/nyse.py` rule calendar,
   **0 disagreements against all 6,706 store sessions 2000-01-03..2026-09-01**, answers the
   question at the latest bar. Decision: hand-rolled rules over `pandas_market_calendars`
   because it is 120 auditable lines with no data dependency and it is now pinned by tests.
3. **`open = 0.0` bars filled buys for $0** and booked free shares (4 such rows in the store);
   `attempt_fill` and `apply_fill` refuse non-positive prices.
4. **A discretionary ticket submitted between `collect` and `league`** carried `signal_date = d`,
   tripped the look-ahead assert, and rolled back the entire day-step for every book.
   `fill_pending` now only considers `signal_date < d`. Also: a ticket submitted during the
   next US session (≥ 09:30 ET on a later calendar day) is stamped with THAT date, so the
   discretionary book can no longer fill at an open the owner already watched print.
5. **Risk gates trusted typed prices**: `entry_ref=1000, stop=999.99` on a $100 stock passed
   every gate with a 25x-the-book position. Gates now anchor to the latest close: stop must be
   below the live price, `entry_anchored` (±10%), `notional_cap` (≤ equity), and risk/share is
   measured from the worse of typed entry and latest close.
6. **`--rerun` deleted discretionary ticket orders** (dangling `disc_tickets.order_id`) and could
   double-count when a later date had already been stepped; both closed.
7. **Orders filled against zero-volume phantom bars**; volume 0/NULL is now "no bar" (pending →
   `no_bar` after 3 sessions, like a halt).

### Corporate actions (`engine/actions.py`) — commit 8f5b… (see git log)

- **The split adjudicator restated three real crashes as split breaks.** It accepted any
  one-session ratio within ln(1.2) of the split ratio anywhere in a 25-session window. BH
  2018-04-27 (+19.9% in store vs −20.1% at Yahoo, 9,612 rows ÷1.5), ORCL 1999-03-12 (genuine
  split already adjusted at ex 03-01; the "break" 8 sessions later was the earnings crash),
  NEM 1987-10-16 (the $33 special dividend), and HWKN 1989-04-25 (a zero-volume bad print at
  the ex-date). BH sits inside every walk-forward and backtest window since 2014.
  **Rule now:** tolerance ln(1.08); the break must sit within 5 sessions of the ex-date (or
  after a recent ex when a collection gap moved it); bars before the candidate must carry
  `fetched_at < ex_date`, otherwise Yahoo already adjusted them (`skipped_already_adjusted`).
  **Repaired live** (`engine/repair_restatements.py`, dry-run → store copy → live, with Yahoo
  cross-check): all four names now 0 rows >1% off Yahoo over their full histories; watermark
  `reverted_false_break`, `audit_log` rows appended. `split_adjustments`: applied 31, reverted 4.
- **`_restate` scaled every open position by the ratio**, including lots opened after the
  ex-date (which `rebuild_state` correctly leaves alone) — latent, no live position affected.
  It now restates prices, scales only pre-ex pending orders, and calls `rebuild_state` inside
  the same transaction (verified: rebuild reproduces the live ledger, 537 positions, 0 mismatches).
- **Open: JEM 2026-07-14 (1:12 reverse).** Yahoo's July-16 pull was half-adjusted; the reconciler
  ×12'd 58 rows of which 2 were right. Needs a full re-fetch of JEM, not the repair script. No
  positions, no bars after 07-15 — low impact, TODO.

### Engine (`engine/`) — see git log

- **Failure breadcrumbs were dead code** in every `run_*.sh` (`set -e` exited the pipeline before
  `PIPESTATUS` was read): 4 tracebacks in `cron.log`, 0 breadcrumbs. Fixed with a `set +e`
  wrap; breadcrumbs also reach the cron log. `run_weekend_sweeps.sh`'s `grep -v` under
  `pipefail` aborted an all-diagnostic listing before the "no grids" gate.
- **`universe.liquid` was written once, at bootstrap.** 336 names added since 07-16 could never
  qualify (inverse survivorship in the forward record). `collect.py --refresh-liquid` recomputes
  from the bootstrap rule (close ≥ $3, 63-bar median $vol ≥ $5M), admits + max-history backfills,
  demotes flag-only, never demotes a held name. **Dry run on a store copy: +122 / −141 today.**
  New driver `engine/run_weekly_liquid.sh` for **Sunday 02:00 UTC** — crontab line in its header,
  **not yet installed** (owner: add it).
- **Phantom bars passed the screen** (TALK, 2026-08-17, rs_rank 85, on a zero-volume bar).
  `REAL_BAR_SQL` (volume > 0 and not o=h=l=c) is shared by `screen.py`, `hist_screen.py` and the
  `_meta.json` stale list; the screen reports `skipped_phantom`.

### Tests — commit 2d4310c and later

`tests/` did not exist. Now **228 tests** (in-memory DuckDB, no store, no network): fill model,
portfolio math, calendar + NYSE rules, stats, risk gates, sizing, leverage classifier, resource
guards, strategy base, screen volume rule, liquid refresh, split adjudicator, the seven
regressions above, and the new strategies. `pyproject.toml` + `.github/workflows/ci.yml`.

### Evaluation and architecture — `docs/evaluation-2026-09-02.md`, `docs/architecture-review-2026-09-02.md`

Every book has a KEEP/WATCH/RETIRE verdict with the deciding fact; nine slots are RETIRE
(the four gated twins are equal to the cent on all 33 live sessions; `template_top5` breaches
its own 40% DD line in 5/10 folds; `turtle_breakout` WF DD −31% vs a 25% kill line; `mr_overlay`
9/9 sweep cells worse). **Not acted on — retirement is the owner's call**; the list is in the doc.
Architecture: `engine/` is not a package (40 `sys.path.insert` sites), the single-writer rule
is convention not structure, zero `logging`, 7 shell drivers share a 25-line preamble. The
9-step incremental refactor plan is in the review.

### New books — `docs/charters/`

- **`xs_momentum_12_1`** — the unscreened control (top-50 EW 12-1 momentum, monthly). Tests the
  claim that the Minervini screen adds anything over plain momentum. 3y design replay (v2 fills):
  +31.4% CAGR / −37% DD vs `ew_benchmark` +17.3% / −33% and `template_top10_banded` −0.3% / −48%.
  Survivor universe — upper bound.
- **`multi_asset_trend`** — 8 ETFs in fixed 12.5% slots, each held while its 12-mo total return
  beats BIL, remainder BIL, monthly. Replay Sharpe 1.45, DD −7.2%; no risk-off episode in window.
- **`xs_reversal_1m`** — designed, **withdrawn before registration**: replay correlation with EW
  0.71 against its own 0.70 kill line. Class + charter kept.
Both books are created by `league --init` at tonight's nightly; first signals last session of Sept.

### Public-readiness — see git log

LICENSE (MIT + paper-trading notice), CONTRIBUTING, SECURITY, CI, packaging; the two design
specs copied to `docs/design/` so no doc points at the private store; `data/eod/` and
`data/universe.csv` untracked (raw Yahoo-derived exports); box-specific paths and the work
identity scrubbed; **history rewritten** (`git filter-repo`: author identity → personal, the two
raw-data paths removed from every commit). Secret scan across full history: clean.

### Round 2 (same day, after the usage-limit reset)

- **`sim/settle.py`** — owner-supplied settlement of dead positions (cash / worthless / stock
  conversion), dry-run by default, cited `--source` required, refuses a name that has traded on
  or after the effective date. Own append-only ledger `sim_settlements`, replayed by
  `rebuild_state` between dividends and fills so `--rerun` reproduces it; equity history before
  the effective date is never restated. **Not applied to any name** — terms are the owner's to
  look up; `docs/settlement-runbook.md` has the exact commands for EA / TALK / WBS / FBRX.
- **Monthly-granularity walk-forward re-report** (`farm/walkforward/monthly.py`,
  `data/reports/walkforward/monthly-2026-09-02.md`). No per-fold monthly series existed on disk;
  `runner.py` now persists `validate_monthly_equity` per fold (additive) and the real table fills
  after Sunday's run. The proxy cut from the 15y backtests (v1 fills, 108 paired months, 13
  books) says: **no book is distinguishable from its control on the positive side** (best DSR
  0.18); `template_top5` and the two gated PASS books lose PASS because it rested on the mean
  while the median excess is ≤ 0; `mr_overlay*` and `turtle_breakout` are TRAILS with CIs wholly
  negative. The evaluation's critique of the evidence-ceiling doc stands.
- **JEM re-fetched 2026-09-03 02:20 UTC** (`engine/refetch_ticker.py`): 60 corrupt rows → 311
  clean rows 2025-06-09..2026-09-02 (Yahoo's own current view; JEM still trades — the store had
  simply stopped collecting it), watermark `superseded_by_refetch`, audit row appended.
- **Nightly 2026-09-02 on the new code: clean** (`=== done 23:15:03Z`), both new books created,
  `divs=2/$22.82` credited live through the catch-up path, `skipped_phantom=0` reported.
- (Both deferred items above were done in round 3.)
- Tests: **253 passed.**

### Round 3 (2026-09-03, 02:15–04:00 UTC)

- **Refactor steps 1–3 landed** (commit `ac20634`): `engine/` is a package, `python -m <pkg.module>`
  is the only invocation (script form dropped on purpose), `engine.lib.db.connect(path,
  read_only, wait_s)` is the single `duckdb.connect` in the packages (enforced by
  `tests/test_no_bare_connect.py`), `engine/lib/settings.py` owns paths and env overrides
  (`TRADING_ENGINE_DB` now honoured everywhere). Proof: 259 tests; `--help` on 37 entry points;
  league init + rerun, screen `--rerun` (516/68, identical to the nightly), queue status and the
  API's three read endpoints against a store copy. **Incident:** the proof sweep's
  `python -m engine.universe --help` ran the universe builder for real (no argparse then) and
  appended a 02:34 UTC `universe_snapshot` for 2026-09-03; removed (12,554 rows, `audit_log`
  row `universe_snapshot_removed`) so tonight's nightly writes the post-close one.
  `engine.universe` has argparse now.
- **Re-audit of the remaining `applied` restatements** (`docs/split-restatements-reaudit-2026-09-03.md`):
  18 of 29 were false, a second trigger of the same defect — for historical splits Yahoo's
  series is fully adjusted EXCEPT the zero-volume bars from the ex-date to the first traded
  post-split session, which sit on the old scale; the old adjudicator took the drop off that
  bogus bar as "the break" and divided every earlier, already-adjusted row. **All 18 reverted
  live** (ASTH, AYA, BRO, CHCO ×2, CTO, ERIC, GRC, INDB, IPAR, ODC, SKE, TECX, TJGC, TMP, TRST,
  UBSI with Yahoo cross-check → every one `0 rows >1% off Yahoo`; ISSC on internal evidence,
  no Yahoo history). AYA (held by three EW books) and ODC (closed July fills) had post-break
  fills only; books rebuilt from fills, positions unchanged. `split_adjustments` now:
  applied 11, reverted_false_break 22, superseded_by_refetch 2. The BUILDLOG's earlier
  "8 Yahoo-unadjusted names" was a misread; only WLFC (and OPAD) are genuinely served
  unadjusted and are left alone. SNEX 2026-07-14 and WLFC 2026-07-15 each have one bad bar
  that needs a single-bar refetch (`engine.refetch_ticker` replaces the whole history; fine
  for both — no positions).
- The new adjudicator would have applied **none** of the 29 (every bulk-loaded row has
  `fetched_at` ≥ ex_date → `skipped_already_adjusted`), which is the right answer: the
  bootstrap load is Yahoo's adjusted view and needs no restating.

### Round 4 (2026-09-03, 03:00–04:10 UTC) — refactor steps 5–7 and the queue's weak points

- **Step 6 — retired agentic layer archived** (`e484539`): `agents/`, `engine/news_analyst*`, the
  agentic/news reports and state files moved with structure to `archive/agentic-2026-08/` (README
  explains what, why, the 5+2 `active=FALSE` books still in `portfolios`, how to re-enable). The
  agent gate in `sim/strategies/base.py` is a no-op while the directory is absent. **Public-
  readiness flag:** the two archived news reports restate the owner's private theses — decide
  before going public.
- **Step 7 — structured logging** (`c333b93`): `engine.lib.log.get_logger(tag)`; 220 `print` →
  `log.*` in 35 modules with output **byte-identical** (league rerun, screen rerun, backtest
  shakedown, verify_prices diffed before/after on a store copy). `TRADING_ENGINE_LOG_LEVEL`,
  `TRADING_ENGINE_LOG_JSON=1`. Report/table output that is data stays `print`.
- **Step 5 + queue** (`bd87bda`): `engine/lib/driver.sh` is the one preamble (five drivers went
  226/111/88/63/64 → 169/89/64/46/48 lines; harness of 15 scenarios identical before/after);
  `queue_runner --enqueue-nightly` owns the nightly enqueue policy (tested, params byte-identical
  so existing rows dedup); `jobs.timeout_s` with kind defaults at 3× measured, enforced on parallel
  children (SIGTERM → `failed`/`timeout`); `supersedes=True` kinds (intraday) mark stale variants
  `superseded`. `run_daily.sh` lost the dead agentic-report block.
- **§A2 duplication closed** (`f6d843e`): `farm/stats/` package (`inference.py` returns-based,
  `equity.py` equity-curve) with ONE `max_drawdown(equity)` — the returns path compounds then
  delegates, equal to the old numbers to the last digit; old import paths still work.
  `engine/lib/util.py` takes `table_exists` (4 copies), `median` (2), `pct`/`num` (4 each),
  `utcnow`. Left in place because the copies differ in behaviour: `farm/autopsy._median`
  (drops None), `farm/experiment_runner._pct/_num` (— placeholder, dp=4, NaN rendered),
  `farm/backtest/replay._pct` (NaN rendered), the two `_num` string PARSERS in
  `verify_prices`/`signals`, `_select_universe` ×4 and `write_reports` ×3 (different jobs).
  isort pass (57 fixes); CI's ruff gate now includes `I`.
- Tests: **319 passed.** The architecture review's plan is complete.
- **Watch tonight's nightly** (first run under `driver.sh` + `--enqueue-nightly`): `logs/cron.log`
  should end `=== done` and the farm section should read `enqueue-nightly=0 run=0`.

### Decisions

- Hand-rolled NYSE calendar over `pandas_market_calendars` (auditable, no data dependency,
  validated against every stored session).
- `xs_reversal_1m` not registered: a book that fails its charter in the design replay is not a
  pre-registration.
- Retirements left to the owner; kill criteria are the owner's rules.
- `data/screens/` stays in git (it is the M1 deliverable); a data-branch split is deferred until
  `sync.py` is changed and dry-run.

### Next

0. **Owner: create the empty private GitHub repo `ong6/trading-engine`**; the push is one
   command away (`git remote add origin git@github.com:ong6/trading-engine.git && git push -u origin main`).
1. **Owner: install the `run_weekly_liquid.sh` crontab line** and decide the nine RETIRE slots.
2. Settle EA / TALK / WBS / FBRX (still `symbol_not_found` at the verifier; 12.1% of `high_52wk`
   frozen) — a delisting handler for `sim/`.
3. Refetch SNEX and WLFC (one bad bar each, no positions); decide OPAD/WLFC's unadjusted
   Yahoo series (leave, or refetch and let the new adjudicator skip).
4. Owner decision on the archived news reports before the repo goes public.
5. Structural single-writer enforcement is still convention + one factory; a write-lock
   assertion inside `connect(read_only=False)` (refuse when `.nightly.lock`/`.queue-drain.lock`
   is held by another pid) is the next step if a double-writer ever recurs.
5. Monthly-granularity re-reporting of walk-forward folds (block bootstrap on ~144 paired
   monthly excess returns instead of n=10 fold means).

## Blockers

- **GitHub remote still needed (owner action).** As of 2026-09-02 the repo `ong6/trading-engine`
  does not exist (`git ls-remote` → "Repository not found"). The box has working SSH auth to GitHub as
  `ong6` (`~/.ssh/id_ed25519_github`, `ssh.github.com:443` available if port 22 throttles),
  but no GitHub CLI and no API token — `/usr/local/bin/gh` is an unrelated internal tool.
  Create an EMPTY PRIVATE repo, then `git remote add origin` + push; `store/` and `logs/`
  are already gitignored so the 2.9 GiB DuckDB stays local. Until then every commit and the
  entire BUILDLOG exist on exactly one disk.

## 2026-09-06 — strategy evidence refresh and research-report hardening

- Re-ran the two 2026-09-02 books and their controls through the real 10-fold
  walk-forward on current code/data (anchor 2026-09-04, fill model v3).
  `xs_momentum_12_1` returned +32.45% mean validate versus EW +26.45%, but the
  +6.00pp annual-fold excess CI [-5.48%, +15.03%] and the 120-month block
  bootstrap both remain indistinguishable. It stays a control, not a promotion.
- `multi_asset_trend` returned +5.63% mean validate with -10.85% worst drawdown,
  versus SPY +15.24% / -32.41%. The drawdown objective worked, but the monthly
  paired test TRAILS SPY (-0.86%/month median, 90% CI [-1.18%, -0.51%], NW
  t=-3.21), and median validate Sharpe 0.51 was below dual momentum's 0.88. That
  directly breaches its pre-registered kill criterion. The empty paper book
  (0 positions/orders/fills) was set inactive; evidence remains on disk.
- Refreshed `sector_momentum`: +14.09% mean validate, -31.84% worst drawdown,
  mean excess -1.17pp vs SPY with CI [-6.48%, +4.85%]. It remains the strongest
  provisional non-reference incumbent, but WATCH / statistically indistinguishable.
- Fixed fold reporting to use registered controls (SPY for ETF allocation, EW
  for single-name books) and monthly reporting to classify multi-asset trend the
  same way. Added coherent-cohort filtering so a partially drained weekly grid
  cannot mix anchors/protocols in one comparison.
- Fixed a fill-allocation defect exposed by the refresh: simultaneous next-open
  buys were applied in order-ID/ticker order, so the first names consumed cash
  after gaps/slippage and later names were clipped or rejected. Fill model v3
  scales all executable buys for a portfolio pro rata before applying them; a
  regression test proves equal simultaneous intents get equal fills. Current v3
  reruns leave the headline conclusions unchanged (`xs_momentum_12_1` +32.45%
  mean validate vs EW +26.45%; sector +14.09%; multi-asset +5.63%).
- Hardened the historical farm: retired configs are explicit `active: false`;
  new-store initialization respects that flag; historical replay excludes by
  strategy (including PEAD twins and macro without historical PIT inputs); old
  retired artifacts are not rendered. Backtests now read the frozen live config
  and future result JSONs carry config/hash + git SHA provenance. The grid is now
  94 meaningful jobs rather than 138 mixed live/retired/invalid jobs.
- Review: `docs/review-2026-09-06.md`. Tests: 337 passed; CI ruff gate
  passed. No broker integration was added; the engine remains paper-only.

## 2026-09-06 — execution, capital and data hardening implementation

- Added fill model v4 with named execution profiles. `baseline_v1` reproduces
  v3's 10/15/20/30 bp-per-side behavior, `cost_2x_v1` is the required stress,
  and `participation_stress_v1` adds transparent square-root impact. Broker fee
  fields remain separate and zero until a real account schedule is verified.
- Persisted `initial_cash` and `execution_profile` per portfolio. Migration was
  tested twice on a full store copy and preserved 29 cash rows, 543 positions,
  975 fills and 697 equity rows exactly. Existing books become `$39,000` /
  `baseline_v1`; current cash is never reset.
- Added companion fill-cost and execution-attempt ledgers, full replay capital
  overrides, the six-notional × baseline/2x sensitivity runner, and isolated
  `data/reports/capital-sensitivity/` artifacts.
- Added data-quality classes and deterministic source-table fingerprints.
  Report cohorts require matching source, fill model, capital, execution
  profile, universe policy and data snapshot; cross-class relative comparisons
  are suppressed.
- Added explicit price quarantine with audited activate/resolve commands. It
  blocks buys but permits exits; verifier disagreement alone never activates it
  and never triggers an automatic repair.
- Verified in an isolated source copy while the pre-v4 sweeps remained active:
  the full Python suite and critical Ruff selectors passed, and a migrated-copy
  API smoke test returned all active books with persisted assumptions. The live
  tree is updated only after those sweeps exit to avoid mixed-code cohorts.
- Final audit tightened two edge cases: a cash-dust rejection now changes its
  execution-attempt outcome from filled to rejected, and the monthly/proxy
  report enforces the same source/fill/capital/profile/policy/data-snapshot and
  evidence-class boundaries as the primary reports. `macro_composite` is
  survivor-biased by its breadth input even though it ultimately holds SPY.

## 2026-09-07 — measured v4 capital/cost evidence

- Completed 48 full five-year replays: six starting balances × baseline/2x
  costs for `sector_momentum`, `dual_momentum`, `spy_benchmark`, and
  `xs_momentum_12_1`. Every cell uses fill model v4, source hash
  `0e1f682e34fa96e32363c09c00a96c7699ac8aa44364081327c82a0579ab2262`
  and repaired-data fingerprint
  `b1b031ac37c5b658034fd5b6234fdbe61facab5cba9cdd4afb1159c542fa3785`.
- SPY had zero capacity rejects through $10m. Sector and dual momentum had zero
  rejects through the sampled $1m point and rejected at $10m. The survivor-
  biased stock basket rejected at every sampled balance, starting with 4 at
  $10k and rising to 1,734 at $10m ($489.6m intended notional rejected).
- At the production $39k reference, doubled market friction changed CAGR by
  -0.01pp for SPY, -0.71pp for sector momentum, -0.37pp for dual momentum, and
  -1.85pp for the high-turnover stock basket. These are complete path replays;
  costs were not subtracted from a previously generated return series.
- Hardened `farm.capital_sensitivity` aggregates: exact-grid and provenance
  validation, full execution-profile stamps, sampled capacity bounds, separate
  market/total costs, and fail-closed summary rebuilds from existing cells.
  Targeted tests, the full Python suite, critical Ruff, shell syntax and diff
  hygiene passed. Repository-wide Ruff still exposes 54 unrelated pre-existing
  findings in archived/legacy files; none are in the changed capital files.

## 2026-09-07 — complete post-repair v4 walk-forward cohort

- Ran all 18 active, historically replayable books as queue jobs 356–373 under
  `trading-engine-hardening-walkforward-20260907.service`. The transient user
  service survived independently of the interactive connection, every job
  reached `done`, reports rendered, and the service exited with status 0.
- Machine-validated every result against the cohort contract: fill model `v4`,
  `$39,000`, `baseline_v1`, anchor `2026-09-04`, runtime source
  `f94c0c51b8bba9a94e4d874af008e48c1c437fd8535318e97a3e4b58addd6602`
  (95 files), repaired data fingerprint
  `b1b031ac37c5b658034fd5b6234fdbe61facab5cba9cdd4afb1159c542fa3785`,
  and an explicit evidence class. Seventeen books have ten terminal folds;
  `sector_momentum` explicitly drops the one fold whose validate start predates
  its required ETF history.
- Both fold and monthly loaders select all 18 new results as one coherent
  cohort. The renderer produced the index, all 18 active per-book pages, and
  fresh `monthly-2026-09-07.{md,json}` artifacts.
- Final candidate reading: sector momentum remains indistinguishable from SPY;
  dual momentum's fold mean trails SPY and its monthly median remains
  inconclusive; cross-sectional momentum remains indistinguishable from the
  survivor-biased EW control; both mean-reversion variants TRAIL EW monthly.
  No strategy is promoted and the system remains paper-only.
- Fixed a derived-report parser exposed by the new evidence-class column: the
  monthly comparison table had displayed blank fold verdicts. The parser now
  locates explicit verdict tokens across current and legacy schemas, including
  retained labels; regression coverage added and the monthly report rebuilt.

## 2026-09-07 — active-code and documentation cleanup

- Cleared all 46 Ruff findings in active Python and tests with behavior-preserving
  edits. `archive/` is now explicitly outside lint scope because it is immutable
  retired source retained for historical reproducibility; the five archived style
  findings are not active-runtime debt.
- Added `docs/README.md` as the current/historical documentation map and corrected
  the root and operating guides: 21 active paper portfolios, 18 historically
  replayable rules, 10-fold walk-forward, current queue column names, and installed
  weekday/Saturday/Sunday schedules. Dated audits remain unchanged snapshots.
- Added `docs/strategy-research-backlog.md`. No sweep candidate is promoted: none
  establishes positive excess over its proper control. The next primary evidence is
  the unchanged prospective `sector_momentum` paper record versus SPY; stock momentum
  remains a survivor-biased, capacity-constrained research control.
- Replaced the transient API process with an enabled user unit backed by
  `server/trading-engine-api.service`; user lingering is enabled. The API now survives
  disconnects and starts after reboot. Post-restart `/health` returned `ok=true` with a
  readable live DB.
- Verification: Ruff clean; `git diff --check` clean; all 396 Python tests pass;
  Python compilation, shell syntax, documentation links, the 18-book walk-forward
  dry-run, and the production Next.js build pass.
- Queue audit: no jobs are running. The sole failed row is historical job 315, a
  2026-09-05 `meanrev` sweep killed at its 14-hour timeout; later canonical evidence
  remains available, and no retry was started merely to erase truthful failure history.
- Reconciled operational health without rewriting that history. A failed Sunday driver is
  reported as `recovered` only after a later, tightly grouped cohort contains every currently
  replayable book exactly once and every job finishes cleanly. Queue health retains all-time
  state counts and failed rows, while separately classifying a closed-charter sweep failure
  as historical only when no equivalent sweep is pending or running. The UI's red alert now
  follows actionable failures; all non-sweep, malformed, open-charter, and actively retried
  failures remain actionable by default.

## 2026-09-07 — prospective sector-momentum monitor

- Added `engine.forward_review`, a read-only nightly monitor for the already-frozen
  `sector_momentum` paper book against `spy_benchmark`. It pins both exact config hashes,
  `$39,000` capital, `baseline_v1`, and the registered 12-month/10pp/no-drawdown-benefit
  kill criterion; any registration drift fails closed.
- The report cannot produce a decision before both one full calendar year and 200 shared
  equity sessions exist. It reports `ACCUMULATING`, `CONTINUE`, or `REVIEW-KILL`; it never
  changes a portfolio or authorizes live execution. The nightly stage is fail-soft and
  runs after league accounting but before sync.
- Current canonical artifact: `data/reports/forward/sector_momentum.{md,json}` is
  initially generated from the shared July paper path. A later audit below supersedes
  that boundary because those rows span older fill-model versions.
- `/meta` exposes only the safe forward-status projection and the UI header displays it;
  invalid artifacts and `REVIEW-KILL` are alerts. Verification expanded to 406 tests,
  all passing with warnings treated as errors; Ruff, shell syntax, API smoke, and the
  production UI build also pass.

## 2026-09-07 — recurring-search closure and final cleanup pass

- Closed an automation flaw that reran every completed sweep grid each Saturday against
  substantially the same history. `OPEN_RECURRING_GRIDS` is explicit and empty by default;
  the Saturday driver now cleanly no-ops until a newly chartered hypothesis is deliberately
  opened. Its parser ignores bracketed wrapper diagnostics, and tests cover both named-grid
  enqueue/drain behavior and the empty allowlist.
- Corrected current documentation for eight-way read-only replay concurrency, the normal
  4-hour versus Saturday 12-hour start budgets, and the live/source portfolio distinction.
  Removed stale hard-coded “17 portfolios” wording from active source and CLI help.
- Repaired five broken design-document links to private sibling-store notes without copying
  private research or device inventory into this repository. Added a regression test that
  resolves every local Markdown target across the repository.
- Kept model work outside the trading loop: cron and systemd remain deterministic. A future
  Codex scheduled review may inspect or propose, but cannot modify ledgers, open a search,
  promote a strategy, or authorize live capital.
- Verification: 425 tests collected and passed with warnings as errors; Ruff, Python
  compilation, shell syntax, diff hygiene, all local Markdown links, dependency integrity,
  the production UI build, systemd unit validation, API health, and the real empty-sweep
  no-op all pass. The API service is enabled/active and user lingering remains enabled.

## 2026-09-07 — forward evidence boundary correction

- Audited the live fills behind the prospective report. The July/August SPY and sector
  fills predate fill model v4 and have no v4 profile ledger rows, so the earlier 2026-07-28
  observation start was not execution-homogeneous. Reset the canonical comparison to the
  shared 2026-09-04 closing marks. Those marks are a zero-return baseline with inherited
  holdings; all earlier paper performance remains in the league but earns no forward-v4
  credit. Earliest maturity is now 2027-09-04 plus the 200-session minimum.
- The monitor now pins fill-model `v4`, the exact `baseline_v1` profile hash, candidate and
  control config hashes, capital, and a hash of the source files governing signal,
  execution, accounting, calendar, and quarantine behavior. Contract drift fails closed
  and requires a newly dated observation.
- Evaluation or registration failure now atomically replaces stale machine-readable status
  with `INVALID` while still returning nonzero to the fail-soft nightly. The API rejects
  unknown statuses or any report that violates `paper_only=true` / `automatic_action=none`.
- Baseline equity values are pinned, and every run verifies the previous report's equity
  hash against the current database prefix before extending it. A same-date rerun or other
  historical rewrite therefore invalidates the monitor instead of silently revising the
  prospective record.

## 2026-09-07 — pre-observation execution-contract correction

- Fixed cash-scaled buy handling when quantity-dependent repricing returns `rejected` or
  `pending`, and made profile-specific liquidity rejection text report the actual cap.
- Re-pinned the sector-momentum runtime contract at the unchanged 2026-09-04 baseline.
  This was permissible only because the live store still contained exactly one shared
  candidate/control row—the zero-return baseline—and no post-boundary market observation.
  The candidate/control configs, baseline equity, start date, fill model, and profile are
  unchanged; no accrued return was discarded or recomputed.
- Walk-forward results now stamp a versioned comparator declaration. Reporters no longer
  infer a fresh relative verdict for old artifacts, and candidate/control comparisons require
  matching source, fill, universe, capital, full execution profile, and data snapshot.
- Historical-backtest reporting selects one cohort across the entire multi-window index,
  identifies whether its source is current, and lists incompatible artifacts rather than
  silently assembling a cross-window patchwork.
- E1 remains on its frozen 20bp round-trip sensitivity, now explicitly pinned to the full
  `baseline_v1` profile hash. Existing append-only observations were not changed.
- Added `FIXED-ETF-REBAL-2026-09-07-v1`, a pre-run charter for one quarterly rebalancing-
  premium candidate against an identical buy-and-hold basket. No implementation, sweep,
  league activation, or historical result was created.

## 2026-09-07 — coherent cohort refresh and isolated fixed-ETF implementation

- Completed all 18 replayable walk-forward jobs as one source/data/protocol cohort under
  fill model v4, `$39,000`, `baseline_v1`, anchor 2026-09-04, and versioned proper controls.
  Reports and paired-month statistics were regenerated. No strategy established positive
  prospective excess: sector momentum remains -1.17pp mean fold excess versus SPY with an
  interval spanning zero; the positive-looking stock/template means remain too uncertain.
- Implemented the chartered SPY/IEF/GLD quarterly-rebalancing candidate and identical
  buy-and-hold control as exactly four isolated replays: candidate/control under baseline
  and doubled costs. The evaluator enforces source/data/protocol coherence, paired monthly
  bootstrap evidence, every-fold drawdown tolerance, and clean execution/accounting gates.
- A one-fold engineering shakedown traversed real next-open fills, dividends, and ledger
  rebuilds with no rejected, pending, capacity, missing-price, or accounting failures. Its
  latest-fold candidate return (+15.23%) trailed control (+16.42%); this is path validation,
  not charter evidence and not a promotion decision.
- Strengthened isolation after the shakedown: neither research class exists in the
  production strategy registry or `CONFIGS`. The dedicated experiment process installs
  both mappings only while its four frozen replays run and removes them in a `finally`
  block. Data-quality evidence is explicitly stamped on the isolated books.

## 2026-09-07 — precise forward runtime contract and pre-run verification

- Corrected the forward monitor's runtime boundary without weakening execution checks.
  The source hash continues to cover signals, fills, accounting, calendars, quarantine,
  and the live dispatcher; unrelated global strategy registrations no longer invalidate
  it. The monitor separately pins the exact registry mappings for `sector_momentum` and
  `spy_benchmark`, so either monitored remap still fails closed.
- Regression tests prove that mutating a true fill dependency changes the contract hash,
  unrelated research registration does not, and a monitored registry remap is rejected.
  The live report regenerated as `ACCUMULATING` at its unchanged zero-return 2026-09-04
  boundary. After restarting the managed API, `/meta` projects that same safe status.
- Verification before the full charter run: all 502 tests pass with warnings as errors;
  repository-wide Ruff, Python compilation, dependency integrity, and diff hygiene pass.
  The API remains enabled/active and `Linger=yes`; no broker, live capital, automatic
  promotion, or paper-book activation was added.

## 2026-09-07 — fixed-ETF charter result: REJECT-V1

- Ran all four frozen cells through a detached user service: buy-and-hold and quarterly
  rebalancing of SPY/IEF/GLD under `baseline_v1` and `cost_2x_v1`. The service exited 0 and
  all 40 folds completed under source hash
  `593f0ddc7b51bef8746640a03ca7f69b8a7558ed2b1730521e3b3f7f81b91d14`, data fingerprint
  `b1b031ac37c5b658034fd5b6234fdbe61facab5cba9cdd4afb1159c542fa3785`, fill model v4,
  `$39,000`, and the frozen 2026-09-04 anchor.
- Execution/accounting was clean across every cell: zero rejected or pending orders, zero
  capacity rejects, zero missing required assets/prices, and every ledger rebuild matched.
- The candidate produced +2.34% cumulative paired validation excess at baseline and +1.88%
  under doubled costs. Baseline mean monthly excess was only +0.0037%, with the predeclared
  90% stationary-bootstrap interval [-0.0517%, +0.0607%]. That interval includes zero, so
  the confidence gate failed and the deterministic verdict is `REJECT-V1`.
- The small historical point estimate is not a proven edge. The charter is closed without
  asset substitution, nearby-parameter tuning, a follow-up sweep, paper registration, or
  live-capital action. Canonical artifacts are in
  `data/reports/experiments/fixed-etf-rebalancing-v1/`.

## 2026-09-07 — prospective XS momentum evidence boundary

- Audited the available point-in-time stock-universe evidence: `universe_snapshot` has
  only 38 dates from 2026-07-16 through 2026-09-04. Historical
  `xs_momentum_12_1` results therefore remain survivor-biased and cannot establish a
  tradable edge. The next honest evidence is prospective time, not another historical
  replay or nearby parameter sweep.
- Added the read-only `engine.xs_forward_review` monitor and wired it fail-soft after the
  existing sector review in the weekday nightly. It freezes `xs_momentum_12_1` against
  `ew_benchmark` before the candidate's first 2026-09-30 monthly signal and waits for the
  shared post-fill close expected 2026-10-01. Legacy EW performance and the initial
  transition are excluded from measured return.
- The monitor pins both configs, `$39,000` capital, fill model v4, `baseline_v1`, the
  execution profile and runtime source hashes, exact signal inputs and derived ranks,
  pre-trade state, pending intents, initial order/fill transition, baseline ledger/state,
  and every published equity prefix. The signal-day report must be published before the
  next-open baseline can start, and the monitor fails closed on mutation. A valid
  invested-control no-op rebalance is represented explicitly rather than requiring an
  economically meaningless order; the candidate must execute its first signal.
- Signal/baseline ledger continuity hashes immutable fills and owner-entered settlements,
  while deliberately allowing late-arriving dividend credits. Boundary cash/equity records
  what was known then; a dividend discovered later remains an honest forward cash event.
- The frozen success gate requires 60 calendar months, at least 48 complete paired months,
  positive absolute and cumulative excess return, and a 90% stationary-bootstrap interval
  on mean monthly excess wholly above zero (10,000 draws, four-month mean block, seed
  20260907). Month accounting requires the scheduled final NYSE-session mark and fails
  closed on a missing completed month. A 55% candidate drawdown or later dirty execution
  requests human review. Every outcome remains paper-only with no automatic action.
- Added lifecycle coverage for waiting, the exact post-fill boundary, month-end inclusion,
  current-month exclusion, missing-month gaps, control no-op handling, candidate first
  trade, maturity, positive/inconclusive verdicts, drawdown/execution review, source/input/
  transition/equity continuity, and safe invalid artifacts. The current operating docs and
  dated charter addendum now expose both forward monitors and the evidence ceiling.
- Final verification: the live schema-v2 monitor wrote pre-signal `WAITING`; all 539 tests
  passed with warnings
  as errors; repository-wide Ruff, Python compilation, dependency integrity, shell syntax,
  local Markdown links, and diff hygiene passed. The API remains enabled/active, the live
  `/meta` projection remains sector `ACCUMULATING`, user lingering is enabled, and the
  weekday/Saturday/Sunday cron entries remain installed. No broker, credentials, live
  capital, model call in the deterministic loop, or automatic promotion was added.
- Added a separate fail-closed `xs_forward_review` projection to API `/meta` and a distinct
  dashboard-header badge. The existing `forward_review` field remains the sector monitor,
  preserving its API contract; operators can now see either monitor fail independently.
  The production UI build passed, the managed API was restarted, and live `/meta` reports
  sector `ACCUMULATING` and XS `WAITING`, both paper-only with no automatic action.

## 2026-09-07 — XS checkpoint accounting hardening

- Before the first XS signal, strengthened both prospective checkpoints. Signal-day
  portfolio cash must equal the dated equity row's cash, the dated equity must reconcile
  to cash plus marked nonzero positions, and the stored position count must equal the
  captured rows. The post-fill baseline applies the same cash, equity, and position-count
  invariants and now freezes the exact position rows alongside cash and equity.
- Later reviews preserve that immutable baseline snapshot while checking its dated equity
  row and the fill/settlement ledger. They deliberately do not compare the old snapshot to
  mutable current holdings after legitimate monthly rebalances.
- The candidate still has no 2026-09-30 signal or accrued forward result, so the runtime
  contract was safely re-pinned before observation to
  `5919378c7c825e4d3187de1f2242c0af825af6bc4f39878d7496ce01ff38df5c`.
  The regenerated report remains `WAITING`, paper-only, with no automatic action.
- Six regression tests cover inconsistent signal/baseline cash, equity, and position
  counts. All 545 tests pass with warnings as errors; repository-wide Ruff, Python
  compilation, dependency integrity, shell syntax, local Markdown links, and diff hygiene
  pass. No new strategy run was opened: the remaining nearby fixed-ETF ideas overlap
  already rejected trend, timing, throttle, or rebalancing families, so another run would
  add selection bias rather than credible evidence.

## 2026-09-07 — E1 forward-record lifecycle hardening

- Audited the nearer-term SPY Monday forward experiment. Its rows were appended in
  practice, but the shared table's primary key includes `run_at`, so the database did not
  itself enforce the documented one-row-per-Monday invariant. The runner now rejects
  duplicate or malformed dates and validates every stored row's parent-config hash,
  forward-config hash, partition, prices, gross/net arithmetic, registered-cost return,
  execution cost, and metadata before using it in statistics.
- Preserved all seven legitimate legacy rows without rewriting them. They predate explicit
  execution-profile fields but contain sufficient frozen prices and costs for exact
  validation. Future rows must also carry the pinned `baseline_v1` profile identity, and a
  runtime cost other than the frozen 20bp round trip fails before persistence.
- Added NYSE-calendar completeness: a missing SPY bar on a real eligible session is no
  longer silently treated as a holiday. The runner accepts at most the first 40 eligible
  settled Mondays, stops the sample exactly there, and changes the report from
  `NO RESULT YET` to the deterministic frozen `KILL`/`SURVIVE` verdict at maturity. Neither
  result performs an automatic action.
- Added a fail-closed `e1_forward` API projection and dashboard status showing progress to
  40. It derives status from the validated database record rather than parsing Markdown.
  The current record remains `ACCUMULATING` at 7/40; its running net mean is negative, but
  the preregistered decision is not evaluated early.
- Anchored those seven audited rows in
  `data/reports/experiments/e1-spy-monday-forward.json`; the immutable-prefix SHA-256 is
  `e2603b7c85f5e24e3b019a4ee7058c6732a792647b0c1c2e62a0d111fdf360ad`. Each successful
  writer run validates the old prefix before atomically advancing this checkpoint. The API
  requires the checkpoint to cover the current database prefix and otherwise returns
  `INVALID`. The fixed sample ends on the 40th eligible NYSE Monday, 2027-05-10; later
  dates cannot enter the result.
- Final verification: all 559 tests pass with warnings as errors; repository-wide Ruff,
  Python compilation, dependency integrity, shell syntax, local Markdown links, diff
  hygiene, and the Next.js production build pass. The managed API was restarted and its
  live `/meta` now reports sector `ACCUMULATING`, XS `WAITING`, and E1 `ACCUMULATING`
  at 7/40, all paper-only with `automatic_action: none`.

## 2026-09-07 — operational-health reconciliation and sector checkpoint v2

- Preserved the failed 2026-09-06 Sunday driver record but now reports it as `recovered`
  only because a later tightly grouped cohort contains all 18 currently replayable books
  exactly once and all jobs finished `done/complete`. The original enqueue stage, exit code,
  and timestamps remain visible. The live API reports `recovery_job_count=18` and the header
  no longer renders a false red incident.
- Kept all-time queue counts and historical job 315 unchanged. `/meta` now separates
  actionable failures from closed-charter sweep history; job 315 remains visible with its
  timeout while the actionable count is zero. Malformed sweeps, open charters, active
  equivalent retries, and every non-sweep failure still fail closed as actionable.
- Upgraded the sector-momentum forward artifact to schema v2 while the live store remained
  exactly at its 2026-09-04 one-row boundary. It freezes and reconciles cash, exact inherited
  positions, position counts, average costs, and dated marks for both sector momentum and
  SPY. Baseline-state SHA-256:
  `6009bf5f765b8f28e41636d60666af5d9319c121aa0668f214ba7a647cc0a902`.
- The monitor now hashes the permanent equity prefix and validates the full post-boundary
  order/fill/cost/attempt/settlement lifecycle. It permits a pending order's legitimate later
  terminal transition and excludes late-discovered dividend rows from historical event hashes;
  their cash effect remains protected when the next equity row is published. An `INVALID`
  artifact preserves the last valid checkpoint for recovery validation.
- Added the monitor itself to its source contract through normalized self-hashing. Runtime
  contract SHA-256:
  `430ae168f6e5a711d09cf686f637291f1b02a19698c5c5d8cfea312d9176c58b`.
  The regenerated live artifact remains `ACCUMULATING`, one shared session, zero return and
  zero post-boundary orders/fills. This improves evidence integrity; it does not add evidence
  of profitability or authorize any automatic/live action.
- Final verification on this revision: all 588 tests pass with warnings as errors;
  repository-wide Ruff, Python compilation, 58-package dependency integrity, shell syntax,
  local Markdown links, diff hygiene, and the Next.js production build pass. The persistent
  API is active/enabled with `Linger=yes`; live `/health` is readable and `/meta` reports
  sector `ACCUMULATING`, XS `WAITING`, E1 `ACCUMULATING` 7/40, weekly research `recovered`,
  zero actionable queue failures, and one preserved historical failure.
- Added a separate read-only stale-exposure projection using the same real-bar predicate as
  the paper league. It reports active-book holdings and all pending orders whose ticker did
  not trade on the latest market date; the persistent header renders that condition red.
  The 2026-09-04 store currently has seven stale active positions across CRNX/APGE and three
  pending FBRX sell orders. This does not classify the corporate event, alter a position, or
  invent a settlement price; those remain manual, evidence-backed decisions.

## 2026-09-07 — settlement/order lifecycle repair

- Closed the lifecycle gap exposed by the stale-order alert. A newly applied owner-supplied
  settlement now cancels every pending order for the same active book and ticker in the same
  transaction and records the affected order ids in `audit_log`. Dry runs show those ids
  without writing. Settlement replay remains pure cash/position arithmetic, so an old event
  cannot retroactively cancel intent created after its booking date.
- Added a conservative `sim.settle --reconcile-pending` path for settlements booked before
  this behavior existed. Its live dry run selected exactly FBRX orders 1005, 1017, and 1029;
  `--apply --ticker FBRX` cancelled those three and appended an audit row. It changed no
  positions, cash, fills, prices, settlement rows, or equity history. No other pending order
  matched, and no active FBRX position remains.
- Focused settlement tests cover atomic cancellation, dry-run visibility, conservative legacy
  selection, audit output, and the no-retroactive-cancellation rebuild invariant.
- Authoritative closing 8-Ks resolved the remaining stale holdings: Vertex acquired CRNX for
  $85.00 cash/share effective 2026-09-01, and AbbVie acquired APGE for $135.11 cash/share
  effective 2026-09-03. SEC Form 25 filings and Nasdaq's independent `symbol_not_found`
  responses corroborate delisting. Read-only dry runs selected exactly two CRNX and five APGE
  active holdings; those seven paper settlements were then booked with the closing filings as
  sources. The live stale-exposure projection is now zero positions and zero pending orders.
- Added `sim/settle.py` to both prospective monitors' frozen runtime contracts because their
  ledger validation depends on settlement semantics. New contract SHA-256 values are
  `2ffc24889541656457c28dcebfabc5a6532f62f38b234839292f228a0765fedd` (sector) and
  `f88712e1ffdeead2fc640fad667531ac57a684651f887fd4ae525403231dcb7e` (XS). Canonical
  reports regenerated successfully as `ACCUMULATING` and `WAITING`; no frozen observation,
  strategy decision, or automatic action changed.
- Final verification: all 593 tests pass with warnings as errors; repository-wide Ruff,
  Python compilation, 58-package dependency integrity, shell syntax, local Markdown links,
  diff hygiene, and the Next.js production build pass. The restarted API is active/enabled
  with `Linger=yes`; live `/health` is readable, `/meta.stale_exposure` is empty, queue
  actionable failures remain zero, and weekly walk-forward remains `recovered`.

## 2026-09-07 — current-document and league-report consistency

- Corrected current documentation that still printed superseded sector and XS runtime hashes.
  Clarified that `league.md` is the latest completed nightly mark-to-market snapshot, while
  `/meta.stale_exposure` is the current between-run operational projection. Dated audit
  snapshots retain their historical statements.
- Fixed the league stale-mark query to include active portfolios only, matching the standings
  and API contract. A retired archival holding can no longer keep a false stale warning alive
  after every active holding is settled. Regression coverage proves the distinction.
- Because `sim/league.py` is deliberately part of both frozen source contracts, this reporting-
  scope correction advanced the contract hashes to
  `2ffc24889541656457c28dcebfabc5a6532f62f38b234839292f228a0765fedd` (sector) and
  `f88712e1ffdeead2fc640fad667531ac57a684651f887fd4ae525403231dcb7e` (XS). It changes no
  signal, order, fill, position, equity, or strategy verdict.

## 2026-09-07 — legacy candidate closure and matched-static review

- Closed stale charter labels: `ew_dd_throttle` and `ew_sector_capped` are rejected,
  `ew_gross_voltarget` is `INCONCLUSIVE-LEGACY`, and `multi_asset_trend` is retired.
  Their original pre-registration text remains intact under dated outcome addenda.
- Drawdown throttle failed its required 8pp relief gate; its best-returning cell achieved
  only 1.07pp of relief with -6.71% median excess. Sector cap failed its 5pp relief gate;
  its best-returning cell had +0.72% median excess with a CI crossing zero and a worse
  worst-fold drawdown than EW, on the already disclosed static-sector data.
- Added a deterministic offline evaluator for the gross-volatility charter's superseding
  matched-static comparison. It validates complete grids/cohorts, ignores only duplicate
  benchmark run-time metadata, rejects substantive benchmark differences, and matches each
  dynamic fold to the nearest-volatility static-exposure fold.
- The resulting nine-cell review is `INCONCLUSIVE-LEGACY`: three 10%-target cells survive
  permissive original gates, but every mean timing-excess 90% CI contains zero, no
  volatility-slope interval is wholly positive, and the v2 artifacts lack complete
  source/data/profile provenance. No paper registration, parameter choice, rerun, or live
  action follows. The engine remains paper-only.
- Verification on the completed pass: all **600** collected tests pass with warnings as
  errors; repository-wide Ruff, Python compilation, 58-package dependency integrity, shell
  syntax, diff hygiene, and the Next.js production build pass. The persistent API remains
  active/enabled with `Linger=yes`; `/health` reports a readable database and `/meta` reports
  zero stale positions/orders, zero actionable queue failures, and weekly walk-forward
  `recovered`.

## 2026-09-07 — VIX-term SPY timing experiment

- Pre-registered one fixed research-only rule before calculating returns: hold SPY after
  `VIX / VIX3M < 0.95`, otherwise BIL, with next-open execution. The threshold is the
  existing frozen calm-state threshold; no grid or alternate threshold was tried.
- Added an exposure-matched static control at 80.6844819503% SPY / 19.3155180497% BIL,
  derived from 3,442 contango observations among 4,266 joined observations without reading
  returns. It shares candidate state-transition dates, separating timing from ordinary beta
  reduction while preserving the candidate's opportunities to trade.
- Kept both strategies outside production `CONFIGS` and `REGISTRY`. An opt-in walk-forward
  scratch hook reconstructs only VIX/VIX3M `fetch_as_of = obs_date` inside isolated stores;
  production macro rows, paper portfolios, ledgers, and schedules are unchanged. The exact
  3,019-session research input is hashed and all required sessions were present.
- The frozen 10-fold/120-month result is **`REJECT-V1`**. Baseline candidate paired growth
  was +117.74% versus static +261.17%; mean monthly timing excess was -0.42% with a 90% CI
  wholly below zero at [-0.67%, -0.17%]. At doubled costs, candidate growth fell to +47.05%
  versus static +260.76%, with -0.74% mean monthly excess and CI [-1.03%, -0.46%]. One fold's
  candidate drawdown was 8.47pp worse. Two symmetric final-session orders in fold 8 had no
  in-window next open, also failing the charter's literal no-pending gate. No paper book,
  tuning, recurring grid, automatic action, or live-capital step follows.
- Final verification after adding the experiment: all **611** collected tests pass with
  warnings as errors; repository-wide Ruff, Python compilation, 58-package dependency
  integrity, shell syntax, diff hygiene, and the Next.js production build pass. The API
  remains active/enabled with `Linger=yes`; `/health` is healthy and `/meta` still reports
  zero stale exposure, zero actionable queue failures, and weekly status `recovered`.

## 2026-09-07 — turn-of-month SPY timing experiment

- Pre-registered one research-only calendar rule before calculating returns: hold SPY for
  the final NYSE session and first three NYSE sessions of each month, otherwise BIL, with
  close-to-next-open signals. No alternate window, month subset, filter, or grid was tried.
- Added a static 19.1122888374% SPY / 80.8877111626% BIL control. Its SPY weight comes only
  from the declared window's 577 calendar sessions among 3,019 protocol sessions, not from
  returns. Candidate and control rebalance on the same transition dates.
- Kept both strategies outside production `CONFIGS` and `REGISTRY`. The four isolated
  replays hashed the exact complete SPY/BIL input from 2014-09-04 through 2026-09-04 and
  left production portfolios, ledgers, schedules, and canonical reports unchanged. The run
  used the disconnect-safe user service `trading-engine-turn-of-month-v1.service`, which
  exited successfully after writing all results.
- The frozen 10-fold/120-month result is **`REJECT-V1`**. Baseline candidate paired growth
  was +12.98% versus +61.30% for the static control; mean monthly timing excess was -0.28%
  with a 90% CI wholly below zero at [-0.54%, -0.02%]. Under doubled costs, candidate
  growth was -28.70% versus control +61.02%, with -0.66% mean monthly excess and CI
  [-0.92%, -0.39%]. Worst fold-level drawdown disadvantage was 9.35pp at baseline and
  12.22pp under doubled costs.
- All folds completed with no rejected or capacity-rejected orders, complete paired months,
  and matching ledger rebuilds. The execution gate also failed because terminal intents
  were asymmetric: candidate exits left two final-session intents in folds 5 and 9, while
  the control left zero and one. Every economic gate already failed independently. No paper
  book, calendar adjustment, recurring grid, automatic action, or live-capital step follows.
- Final verification: all **627** collected tests pass with warnings as errors;
  repository-wide Ruff, Python compilation, 58-package dependency integrity, shell syntax,
  local links in the changed current docs, diff hygiene, and the Next.js production build
  pass. The managed API was restarted to load the already frozen current monitor contracts;
  it remains active/enabled with `Linger=yes`. `/health` is readable and `/meta` reports
  sector `ACCUMULATING`, XS `WAITING`, E1 `ACCUMULATING` at 7/40, zero stale exposure,
  zero actionable queue failures, and weekly walk-forward `recovered`.

## 2026-09-07 — sell-in-May SPY timing experiment

- Before calculating returns, registered one conventional seasonal rule: hold SPY in
  November-April and BIL in May-October, switching from the final April/October close at
  the next session's open. No shifted boundary, month subset, filter, or grid was tried.
- Added a static 49.0228552501% SPY / 50.9771447499% BIL control. Its SPY weight comes
  only from the declared interval's 1,480 calendar sessions among 3,019 protocol sessions;
  candidate and control share the same two annual rebalance opportunities.
- Kept both strategies outside production `CONFIGS` and `REGISTRY`. Four isolated replays
  hashed the exact complete SPY/BIL input from 2014-09-04 through 2026-09-04 and changed no
  production portfolio, ledger, schedule, canonical report, or monitor. The disconnect-safe
  `trading-engine-sell-in-may-v1.service` completed successfully.
- The frozen 10-fold/120-month result is **`REJECT-V1`**. Baseline candidate paired growth
  was +99.38% versus +139.83% for the exposure-matched static control; cumulative excess
  was -40.45%, and mean monthly excess was -0.12% with 90% CI [-0.35%, +0.11%]. Under
  doubled costs, candidate growth was +91.33% versus control +139.62%, with -0.15% mean
  monthly excess and CI [-0.38%, +0.07%]. The worst fold-level drawdown disadvantage was
  16.30pp under both profiles.
- Execution, data, and accounting were clean: all folds and paired months were present,
  no orders were pending/rejected/capacity-rejected, and every ledger rebuild matched.
  The economic gates independently reject the rule. No paper book, calendar adjustment,
  recurring grid, automatic action, or live-capital step follows.
- Hardened the shared paired-walk-forward evaluator to reject malformed exact-fold sets,
  including duplicate fold geometry/indexes and extra failed folds. Dedicated tests cover
  symmetric and asymmetric terminal intents, nonterminal intents, count/detail mismatches,
  missing folds, duplicate folds, and extra failed folds.
- Final verification for the combined calendar-research pass: all **640** collected tests
  pass with warnings as errors; repository-wide Ruff, Python compilation, 58-package
  dependency integrity, shell syntax, 36 links in the changed current docs, diff hygiene,
  and the Next.js production build pass. Both generated calendar decisions reproduce from
  disk through the hardened evaluator. The persistent API remains active/enabled with
  `Linger=yes`; `/health` is readable and `/meta` reports sector `ACCUMULATING`, XS
  `WAITING`, E1 `ACCUMULATING` at 7/40, zero stale exposure, zero actionable queue failures,
  and weekly walk-forward `recovered`.
- Consolidated the duplicated VIX-term, turn-of-month, and sell-in-May cohort validation,
  paired-month statistics, execution checks, gates, and report tables into
  `farm/paired_walkforward.py`. Pending policy remains explicit per charter: VIX permits no
  pending intent, while calendar runs permit only symmetric final-session truncation. The
  shared evaluator now also requires numeric drawdown evidence for all 10 folds.
- Regression checks reproduce all three sealed JSON decisions (apart from generation time)
  and their Markdown reports byte-for-byte. Historical result files retain the source hash
  captured by their actual replay; this cleanup does not rewrite that provenance or rerun
  a closed hypothesis.
- Final verification after the shared-evaluator refactor: all **643** collected tests pass
  with warnings as errors; repository-wide Ruff, Python compilation, 58-package dependency
  integrity, shell syntax, diff hygiene, and the Next.js production build pass. Live API
  health and monitor states remain unchanged and valid.
- Extracted the common research-only SPY/BIL transition mechanics into
  `sim/strategies/research_spy_bil.py`: complete positive signal-date prices,
  inception/transition gating, binary SPY-or-BIL targets, and bounded static exposure.
  VIX-term, turn-of-month, and sell-in-May retain separate frozen state rules, weights,
  classes, and production-registry isolation. Direct helper tests cover missing prices,
  non-transition suppression, inception state, and invalid static weights.
- Final verification after this strategy cleanup: all **647** collected tests pass with
  warnings as errors; repository-wide Ruff, Python compilation, dependency integrity,
  shell syntax, diff hygiene, sealed-result reproduction, and the Next.js production build
  pass. The live API remains healthy and the forward-monitor contracts are unaffected.

## 2026-09-07 — persistent production UI and disconnect-safe verification

- Added the versioned `ui/trading-engine-ui.service` user unit and installed the matching
  unit under `~/.config/systemd/user/`. It builds before startup, serves the production
  Next.js application on `127.0.0.1:3000`, wants/starts after the API, restarts on failure,
  and is enabled under the lingering user manager. The existing API unit remains enabled
  and active on `127.0.0.1:8000`; both services therefore survive terminal, SSH, and Codex
  disconnections without exposing an unauthenticated listener to the network.
- Replaced the generic generated UI README with project-specific production-service,
  development-mode, restart, logging, and SSH-tunnel instructions. Updated the root README
  and current how-it-works guide with health checks and the two-service lifecycle. Added
  contract tests for both versioned units, including loopback binding, production startup,
  API dependency, restart policy, and default-target enablement.
- During migration, the old July `next dev` npm parent stopped but its exact child PIDs
  `1647007` and `1647028` remained orphaned on port 3000. The managed unit consequently hit
  `EADDRINUSE` twice. The service was stopped, only those resolved orphan PIDs were
  terminated, the socket was verified free, and the managed production unit then started
  successfully. No broad process pattern was killed.
- Proved a subsequent controlled `systemctl --user restart` end to end. The build pre-step
  exited successfully, the unit returned active/running with `NRestarts=0`, `/` returned
  HTTP 200, `/api/health` returned the healthy API payload, and `ss` showed only the unit's
  `next start` / `next-server` process tree listening on `127.0.0.1:3000`; no `next dev`
  process remained.
- Final verification: all **649** collected tests pass with warnings as errors;
  repository-wide Ruff, Python compilation, 58-package dependency integrity, shell syntax,
  both systemd unit contracts, diff hygiene, and the Next.js production build pass. Live
  checks show both services active/enabled with `Linger=yes`; the API and UI health paths
  are readable, and `/meta` still reports zero stale exposure, zero actionable queue
  failures, weekly walk-forward `recovered`, sector `ACCUMULATING`, XS `WAITING`, and E1
  `ACCUMULATING` at 7/40. All research and execution remain paper-only.
- Reconciled the evergreen documentation against authoritative runtime state. The current
  phase now says the recurring sweep allowlist is empty instead of claiming sweeps are
  open; the turn-of-month and Sell-in-May charter headers now identify their completed
  `REJECT-V1` decisions; and the docs index points readers to generated monitor reports for
  live observation counts rather than freezing those counters in prose. M1 remains pending:
  `origin` is configured, but `git ls-remote` returns “Repository not found” and `main` has
  no upstream.
- Clarified that `ui/run_ui.sh` is development-only, warns about the managed port-3000
  service, and fails early with a useful error when npm is unavailable. The persistent path
  remains the production systemd unit.
- Applied the same service-first wording and virtualenv preflight to the manual API launcher.
  CI now compiles all active Python and syntax-checks the operational shell launchers in
  addition to Ruff, pytest, and the production UI build.
- Added an explicit next-candidate admission boundary to the research ledger from a
  read-only store audit: universe and screen history each span 38 dates, fundamentals span
  8 as-of dates, and the intraday archive spans 43 one-minute / 96 five-minute sessions.
  Those inputs are not mature enough to turn long daily price history into unbiased stock,
  fundamental, event, or microstructure evidence. Such work must wait for prospective
  accumulation or use an independently sourced, timestamped point-in-time dataset; this
  does not weaken the fixed controls or authorize more variants of rejected ETF calendars.
- Extracted driver-log parsing, queue failure classification, walk-forward recovery, and
  stale-exposure projection from the oversized API route module into read-only
  `server/operations.py`. Moved the E1, sector, and XS artifact-validation adapters into
  `server/forward_status.py`; the underlying monitor modules still own strategy evaluation
  and immutable evidence. `server.main` now focuses on HTTP and ticket behavior, shrinking
  from roughly 1,250 to 646 lines. `/meta` and the focused tests call the owning modules
  directly; a repository search found no remaining health-helper compatibility consumers.
  The focused 55-test server-health suite proves the extracted behavior,
  including fail-closed malformed sweep handling, exact recovery-cohort validation, stale
  reports, changed contracts, and tampered evidence. No strategy or monitor contract changed.
- Full post-extraction verification was **649/649** tests with warnings as errors before
  the readiness endpoint; after its original four tests and four breadth/time edge cases,
  the final count is **657/657**;
  repository-wide Ruff, Python compilation, 58-package dependency integrity, shell syntax,
  systemd validation, diff hygiene, and the production UI build all pass. The managed API
  was restarted onto the extracted module and returned healthy `/health` and `/meta` data;
  the UI proxy remained healthy, both services stayed enabled with zero restart failures,
  and all forward-status projections were unchanged.
- Added read-only `GET /research/readiness` so future research can detect data maturity from
  the store instead of copying volatile counts into prose. It requires 756 shared
  universe/screen dates with at least 1,000 names over 1,095 calendar days for stock-selection
  work, 156 fundamentals snapshots with at least 1,000 names over the same span, and 252
  sessions with at least 500 tickers over 365 days in both 1m and 5m archives for intraday
  work. Counts and spans use qualifying dates, so a visible early thin bootstrap observation
  does not permanently poison later readiness. `READY_FOR_CHARTER` is explicitly
  non-promotional and cannot create a book or order.
  The live result is `WAITING` for every family: 37 shared stock dates, 8 fundamentals
  snapshots, and 43/96 one-/five-minute sessions. Eight focused tests cover absent and empty
  tables, exact shared-date/interval counting, independent breadth and elapsed-time gates,
  non-poisoning thin bootstrap dates, threshold behavior, and connection closure.
- Added the same readiness projection to the dashboard as neutral coverage counters. It is
  deliberately separate from operational alerts and repeats the API notice that clearing a
  data gate is not evidence of profitability or permission to activate a strategy.
- Extracted the remaining screen, league, candidate, position, order, and journal queries
  from `server/main.py` into the read-only `server/read_models.py`; the router now owns HTTP
  status/connection lifecycle and the existing ticket/risk write path remains untouched.
  `server.main` fell from 656 to 445 lines. Four focused read-model tests cover empty-store
  behavior, screen counts/order, persisted-capital league ranking, candidate and position
  valuation, joined ticket orders, fills, and malformed journal gate JSON. Before restart,
  all seven affected projections matched the old live API after FastAPI-equivalent JSON
  encoding, including complete production payload hashes for screen, league/equity, SPY,
  positions, orders, and journal. The full suite is now **661/661** with warnings as errors;
  repository-wide Ruff, Python compilation, dependency integrity, Bash syntax, systemd unit
  verification, diff hygiene, and the production UI build pass. The restarted API serves
  byte-equivalent canonical JSON for all seven routes with zero service restarts.
- Corrected the live league page's claim that it showed tombstoned portfolios: the API has
  always selected active books only, while retired evidence remains in generated reports.
  Added the live readiness endpoint/dashboard to the documentation map so the current
  candidate-admission source is discoverable without reading the chronological build log.
- Extracted discretionary ticket mutations from the HTTP router into `server/tickets.py`,
  reducing `server.main` from 445 to 236 lines while leaving risk policy in `server/risk.py`
  and fills exclusively in the nightly simulator. Fixed four write-path defects found in
  the extraction audit: responses now report the actual rolled-forward signal date stored
  on an order; side, boolean, and optional numeric fields are type/finite validated; pending
  sell intents reserve held quantity so multiple exits cannot oversubscribe a position; and
  cancellation/review writes are atomic with their audit rows. Fifteen in-memory tests cover
  commit and forced-audit rollback paths, malformed inputs, pending-exit reservation, signal
  dates, and HTTP error/connection handling. The full suite is now **676/676** with warnings
  as errors; repository-wide Ruff, Python compilation, 58-package dependency integrity,
  Bash syntax, systemd unit verification, diff hygiene, and the production UI build pass.
  Verification never submitted a live ticket.
- Hardened two remaining API input/artifact edges: malformed `/screen/{run_date}` values now
  return an explicit HTTP 400 instead of an internal 500, and `/meta` reports a missing,
  malformed, or wrong-shaped `_meta.json` via `meta_file` while continuing to serve the
  independently computed database, queue, exposure, and forward-monitor state. The header
  renders a red health-snapshot warning when that file is unavailable or invalid. Optional
  ticket prices must now be positive as well as finite, and current docs/source point to the
  actual execution-design §4 risk contract instead of a nonexistent root `rules.md`.
  The final suite is **681/681** with warnings as errors; repository-wide Ruff,
  compilation, dependency integrity, Bash syntax, systemd verification, diff hygiene, and
  the production UI build also pass.
- Corrected the contributor bootstrap command to match the repository's actual `uv`-managed
  environment. A fresh setup now uses `uv venv --python 3.12` and `uv pip install --python
  .venv/bin/python -r engine/requirements.txt ruff`; this avoids documenting a
  `.venv/bin/pip` executable that is absent from the installed environment.
- Removed the final ticket-logic compatibility alias from `server.main`; regression tests now
  call the owning `server.tickets.signal_date` function directly, leaving the router as HTTP
  composition rather than a second API for domain logic.
- Made the discretionary risk-control list an explicit runtime contract and tied both current
  operating documents to it with a regression test. The implementation, API ordering, and docs
  now agree on all 11 controls, so a future addition cannot silently repeat the stale “8 gates”
  mismatch. Hardened unattended `engine.sync` at the same time: it refuses a non-empty Git
  index, path-limits staging/commits to `data/`, restores only that path after dry runs or failed
  commits, and therefore cannot absorb or unstage an operator's code/documentation work. A real
  dirty-tree dry run staged the generated-data set and restored the empty index to the identical
  SHA-256. Temporary-repository integration tests also prove actual Git 2.20 commits contain only
  `data/`, preserve unrelated unstaged edits, and refuse pre-staged operator work without changing
  its index patch. The full suite is now **687/687** with warnings as errors; repository-wide Ruff,
  Python compilation, 58-package dependency integrity, Bash syntax, systemd unit verification,
  diff hygiene, and the production UI build pass.
- Replaced the ambiguous calendar-only API freshness signal with an explicit NYSE-session
  projection. `GET /meta.market_freshness` retains calendar age for context but declares data
  stale only when a scheduled session strictly before today is missing; weekends, Labor Day,
  and the current session's normal collection window no longer produce false alerts. The header
  now surfaces unknown, future-dated, or genuinely stale market data in red. Boundary tests cover
  the 2026 Labor Day weekend and a missed Tuesday. The shared latest-price projection and
  discretionary risk reads now also require an actually traded bar, so later zero-volume flat
  quotes cannot mask stale data, alter regime/market anchors, or future-date an order. A buy's
  `entry_anchored` control now also requires that ticker's real quote to match the market's latest
  real date; stale closes remain available for position valuation and closing sells but cannot
  authorize new exposure. The full suite is now **692/692** with warnings as errors;
  repository-wide Ruff, Python compilation, 58-package dependency integrity, Bash syntax,
  systemd unit verification, diff hygiene, and the production UI build pass.
- Separated “a newer real row exists” from “the nightly batch is complete enough to trade.”
  `engine.market_date` now resolves the latest date having real bars for at least 90% of the
  active liquid universe and at least 1,000 names (capped at universe size), failing closed when
  no initialized liquid universe or qualifying date exists. `run_daily.sh` resolves that date
  immediately after collection and passes it explicitly to the screen and league, so a partial
  upload or stray later quote remains archived but cannot advance paper state. The CLI also
  rejects a newer real-but-incomplete tail outright, stopping before corporate-action
  reconciliation or league processing. That closes the remaining raw-`MAX(date)` exposure in
  frozen `engine/actions.py` without changing either forward monitor's runtime contract. Tail
  detection deliberately uses every real price row—even inactive, illiquid, or orphaned names—
  because those frozen downstream consumers use the store-wide maximum. The production
  universe has 4,094 active liquid names, requires 3,685, and resolves to 2026-09-04 with 4,094
  real bars. Synthetic coverage proves 900/1,200 does not advance while 1,080/1,200 does. The
  frozen `engine/screen.py` and `sim/league.py` behavior was deliberately reused through their
  existing `--date` interfaces rather than changed for this safeguard. Four new tests cover the
  threshold, partial and phantom rows, empty-universe failure, exact driver arguments, and fatal
  stage ordering. Operational risk and position projections are capped at that same date, so a
  real quote from a partial later batch cannot create mixed-date equity or P&L; with no qualified
  date those projections expose no quote and ticket anchoring stays unknown. Stale-exposure
  detection likewise caps each ticker's last-traded date at the operational boundary, preventing
  a later partial quote from hiding an unusable as-of mark. A documentation contract test also
  binds both current operating guides to the runtime 90% / 1,000-name thresholds. The full suite
  is now **703/703** with warnings as errors; repository-wide
  Ruff, Python compilation, 58-package dependency integrity, Bash syntax, systemd unit
  verification, diff hygiene, and the production UI build also pass.
- Added a fail-closed league-continuity check to the non-frozen market-date gate. Every active
  portfolio must share one latest equity checkpoint, and a newer qualified date must be exactly
  the next NYSE session; same-date holiday reruns remain clean no-ops. The driver therefore cannot
  silently jump over a failed nightly. Automatic historical catch-up was deliberately rejected:
  the frozen screener reads current membership, and later corporate-action knowledge can make a
  reconstructed prior decision look point-in-time when it is not. Production currently has all
  21 active books continuous through 2026-09-04. Three tests cover same/next-session acceptance,
  skipped-session rejection, and divergent/missing active-book checkpoints. The full suite is now
  **708/708** with warnings as errors.
- Reconciled the remaining operator-facing portions of the engine design with the deployed
  system: yfinance is the sole primary EOD writer, Nasdaq is verification-only, Stooq is blocked,
  bootstrap uses `--bootstrap-floor` then `--backfill`, cron runs at 22:30 UTC weekdays, and the
  current pipeline includes the breadth-qualified date gate plus path-contained sync behavior.
  The same pass replaced the uninstalled catch-up schedule, nightly walk-forward claim, obsolete
  24-worker cap, and scaffold-era next step with the deployed Sunday cadence, width-8 cap, and
  current paper-evidence status. Dated examples remain intact. A docs regression test rejects
  those obsolete operational instructions. After the subsequent continuity coverage, the full
  suite is **708/708** with warnings as errors.
- Closed a parallel-research artifact race without changing strategy logic or evidence. Backtest
  and walk-forward workers now publish their per-job JSON through the existing same-directory
  atomic writer; backtest, walk-forward, sweep, and capital-sensitivity report files use the same
  primitive, so a killed process cannot expose a truncated JSON or Markdown artifact. Because
  every parallel replay worker also rebuilds a shared report index, the complete backtest and
  walk-forward rebuilds now take a process-level advisory lock under ignored `scratch/`. This
  prevents an earlier worker's stale snapshot from winning the final rename while preserving
  parallel replay compute and one-writer DuckDB behavior. The queue runner's own module contract
  and execution-design diagram now describe the deployed one-store-writer / eight-read-only-worker
  model instead of the obsolete sequential / 24-worker design, with a regression test over the
  current operating documents. Atomic replacement also preserves an existing artifact's mode
  (including private 0600 metadata) and gives newly created reports the normal 0644 mode. The
  same crash-safe publication primitive now covers the remaining non-frozen research exporters:
  immutable experiment pins, lock-contention fallback payloads, one-off experiment reports,
  execution-drag reports, and explicit autopsy exports. `farm/walkforward/monthly.py` remains
  byte-for-byte inside the frozen XS runtime contract; an attempted I/O-only edit was detected by
  its SHA-256 guard and removed before the scheduled run. The exact final state
  passes **713/713** tests with warnings as errors, repository-wide Ruff, Python compilation,
  Bash syntax, and diff hygiene; no index entry is staged and no production run was started
  manually.
- Hardened earnings-miner restart semantics after the 2026-09-07 nightly exposed the gap between
  its documentation and storage model. New append-only `earnings_fetch_log` rows distinguish
  `ok`, successful `empty`, and `failed` attempts per ticker/as-of. Each 25-name checkpoint now
  commits calendar rows and fetch outcomes in one transaction; same-day recovery skips only
  completed outcomes, retries genuine failures, and retains legacy `earnings_calendar` rows as
  completion evidence for runs predating the log. The queue now supervises earnings in a
  sequential child that releases DuckDB during per-name HTTP waits and leases the writer only for
  setup, 25-name transactional checkpoints, and final accounting. The process-level drain lock
  still owns the job and prevents concurrent drains, while API/UI readers can use the store
  between short commits. Five focused earnings tests and 38 queue tests include rollback,
  retry/skip, legacy compatibility, live-reader-during-fetch, and real subprocess lifecycle
  proofs. Full verification is **721/721** tests with warnings as errors plus repository-wide
  Ruff, Python compilation, Bash syntax, frozen sector/XS hashes, and diff hygiene. The old-code
  2026-09-07 nightly completed independently (2,980 pulled, 2,806 with dates, 174 empty, zero
  failures); its post-run audit found all 21 books unchanged at 2026-09-04, no paper-ledger
  mutation, zero actionable queue failures, and both API/UI services healthy with zero restarts.
- Applied the same bounded connection and recovery model to the Friday fundamentals miner after
  an adjacent audit showed it retained DuckDB through a 70–80 minute HTTP crawl. New append-only
  `fundamentals_fetch_log` rows record `ok` and `failed` attempts; unusable responses remain gaps
  and retryable rather than being mislabeled as valid empty observations. Snapshot rows and
  attempt outcomes commit together every 25 names. Fundamentals now runs as a supervised,
  sequential child and releases DuckDB between checkpoints, preserving the one-job queue rule
  while allowing API/UI reads. Focused proofs cover validation, retry/skip behavior, rollback,
  live-reader access during fetch, and real child lifecycle.
- Removed stale current-design claims that fundamentals or the paper league become decision-ready
  after 6–12 months. The enforced admission contract is 156 breadth-qualified fundamentals
  snapshots spanning 1,095 days; sector has its separate 12-month/200-session frozen boundary.
  Passing either maturity gate still does not establish an edge or authorize live capital.
- Tightened the fundamentals research-readiness denominator from all snapshot rows to usable
  value observations: equities with market cap and at least one of trailing P/E, price-to-book,
  or EV/EBITDA. The latest production snapshot has 2,865 such names versus 4,118 total rows
  (including 1,218 ETFs), so the 1,000-name breadth gate still passes while no longer allowing
  irrelevant/null rows to overstate future readiness. Time gates and the current `WAITING`
  decision are unchanged. The endpoint schema is versioned from 2 to 3 because the meaning of
  its fundamentals breadth fields changed; field names remain backward-compatible.
- The dashboard now shows the minimum usable-equity breadth beside the qualifying
  fundamentals-snapshot count, so a date total cannot hide a thin value dataset. A legacy table
  lacking the required valuation columns fails closed as zero qualifying snapshots.
- Final closeout verification after that dashboard/readiness change passes **731/731** tests with
  warnings as errors, repository-wide Ruff, Python compilation, Bash syntax, and diff hygiene.
  The production UI rebuilt and restarted successfully; API and UI health endpoints return 200,
  both user services are active with zero restarts, and user lingering plus enabled cron/systemd
  services keep them independent of an interactive connection. The production readiness endpoint
  serves schema v3 as paper-only and `WAITING` (fundamentals 8/156 qualifying snapshots; minimum
  usable-equity breadth 2,863). All 21 active books remain checkpointed at 2026-09-04 with 1,045
  orders, 975 fills, 697 equity rows, zero review markers, zero queued/running jobs, and zero
  actionable queue failures. Canonical frozen contracts remain exactly
  `2ffc24889541656457c28dcebfabc5a6532f62f38b234839292f228a0765fedd` (sector) and
  `f88712e1ffdeead2fc640fad667531ac57a684651f887fd4ae525403231dcb7e` (XS).

## 2026-09-08 — corporate-action recovery and explicit runtime-contract v2

- Resolved the corporate-action recovery issue through explicit forward-runtime contract v2.
  `actions_fetch_log` now preserves every attempt; resume skips only `ok`/valid `empty` outcomes
  and retries `failed`. Action facts and attempt outcomes commit in one transaction, and action
  backfills run as supervised sequential children that release DuckDB during HTTP waits. The
  migration preserved the sector baseline and XS pre-signal boundary because it changed no
  strategy, execution, portfolio, or statistical rule. Reports record both hashes: sector v2
  `1854c24767dddfa8e1f0eb2544b860c8e7c3897d82f5fb297888dd4e13eaad6d` supersedes
  `2ffc24889541656457c28dcebfabc5a6532f62f38b234839292f228a0765fedd`; XS v2
  `c30cacb7f7056908f6945f189f5e90088734438ba9e4c029b459e246dd7b3da1` supersedes
  `f88712e1ffdeead2fc640fad667531ac57a684651f887fd4ae525403231dcb7e`.
  Both v2 dependency lists now include `engine/lib/db.py`, so a future change to the action
  schema or write semantics invalidates the monitor just as a caller change would.
  A rehearsal and the live migration each preserved all 16,435 legacy action-log rows exactly;
  unknown historical attempt times remain NULL instead of being fabricated. Both reports then
  regenerated successfully (`ACCUMULATING` / `WAITING`) with their original observation dates,
  sector equity-prefix hash, and forward-ledger hash intact. Focused coverage includes retry,
  append-only attempt history, transactional rollback, legacy migration, concurrent reads, and a
  real detached queue-child lifecycle. Final verification is **739/739** tests with warnings as
  errors plus repository-wide Ruff, Python compilation, Bash syntax, diff hygiene, canonical
  contract self-checks, healthy API/UI services, and unchanged paper ledgers.
- Removed the remaining long network-held DuckDB lease from the intraday archiver. Production job
  392 showed the old path occupied one writer connection from 22:40:15 through 22:43:28 while
  downloading 1,005 names, making API/UI reconnects fail for roughly three minutes. The collector
  now resolves its universe under a short setup lease, performs Yahoo downloads and retry/batch
  sleeps with no DB handle, and opens a writer only to append each parsed batch through the
  unchanged idempotent `db.insert_intraday` path. Queue execution remains sequential,
  resource-guarded, timeout-supervised, and `supersedes=True`; only the lock lifetime changed.
  `limit=0` is now an explicit no-network path. Tests prove UTC parsing, batch persistence, a live
  read-only connection during each mocked download, zero HTTP calls at limit zero, and a real
  detached child followed by parent DB reacquisition. The final repository state passes
  **744/744** tests with warnings as errors plus repository-wide Ruff, Python compilation, Bash
  syntax, and diff hygiene; the sector/XS v2 hashes remain exactly
  `1854c24767dddfa8e1f0eb2544b860c8e7c3897d82f5fb297888dd4e13eaad6d` and
  `c30cacb7f7056908f6945f189f5e90088734438ba9e4c029b459e246dd7b3da1`. No production pull was
  started manually; the next scheduled nightly is the live-path validation.
- Closed the same writer-lifetime gap in the signal collector. Recent incremental jobs occupied
  the connection continuously for about 27 seconds despite eight external source functions not
  using DuckDB. Signals now runs as a supervised sequential child: external HTTP sources execute
  with no DB handle, internal breadth gets a read-only lease, each source result receives one
  short append-only writer lease, and final totals use a read-only lease. Source-level
  warn-and-continue behavior, first-observed point-in-time stamping, queue priority, and strategy
  behavior are unchanged. Tests prove concurrent-reader access during an external source, the
  DB-backed-source read path, and real detached-child completion/reacquisition. No production
  signal fetch was started manually; the next scheduled nightly will validate the live path.
- Narrowed the Saturday full-universe verifier's connection lifetime as well. Its 2026-09-05 pass
  consumed the full 10,800-second budget and previously retained a DuckDB read connection for all
  three hours. The verifier now materializes the deterministic sample, asset classes, and bounded
  five-session store bars first, closes DuckDB, and only then starts Nasdaq requests. Comparison,
  tolerances, fail-soft behavior, and `_meta.json` output are unchanged. A focused test opens a
  real writer and commits from inside the mocked first HTTP fetch, proving the verifier no longer
  blocks writers for its network-bound lifetime.
- Final verification for the combined connection-lifetime cleanup is **749/749** tests with
  warnings as errors, repository-wide Ruff, Python compilation, Bash syntax, and diff hygiene.
  Both frozen runtime contracts self-verify at their canonical v2 hashes. The API and UI remain
  active with zero restarts, the store is readable, the queue has no pending/running work, and the
  installed 22:30 UTC weekday cron points directly at this checkout. The only recent failed queue
  row is historical mean-reversion sweep job 315, already classified by `/meta` as non-actionable;
  actionable failures remain zero.
- Closed an evidence-integrity asymmetry in E1. Its YAML, forward registration, execution profile,
  row calculations, and seven-row prefix were already validated, but the source code selecting
  Mondays and applying the frozen kill rule had no explicit digest. Checkpoint schema v2 now pins
  a nine-file runtime contract at
  `6cf141a68d41b01d04f910d4d64aefd333605bbb758161ad9130c2f23348ca56`; normal runs and `/meta`
  fail closed if it changes. The explicit migration first validated checkpoint v1 against the
  independently pinned identity (7 observations through 2026-08-31, prefix
  `e2603b7c85f5e24e3b019a4ee7058c6732a792647b0c1c2e62a0d111fdf360ad`). Rehearsal and live
  migration both retained that count and prefix exactly. `superseded_runtime_contract_sha256` is
  intentionally null because schema v1 never recorded one; no historical hash was fabricated.
- Final verification after the E1 contract migration is **754/754** tests with warnings as
  errors plus repository-wide Ruff, Python compilation, Bash syntax, and diff hygiene. Sector,
  XS, and E1 runtime hashes all self-verify. The restarted API serves E1 as `ACCUMULATING` with
  checkpoint schema 2, runtime contract v1, 7/40 observations, and no automatic action; sector
  remains `ACCUMULATING`, XS remains `WAITING`, and actionable queue failures remain zero.

## 2026-09-08 — EOD collector lease narrowing and XS runtime-contract v3

- Removed the remaining routine network-held DuckDB connection from `engine.collect`. Bootstrap,
  backfill, weekly liquidity refresh, and nightly incremental collection now resolve their
  universe under a short read lease, perform Yahoo downloads/retries and politeness sleeps with
  no database handle, and open a writer only for each completed batch. Final health counters use
  a separate read lease. Backfill commits price rows, `backfill_done`, and job progress together.
- Made `--limit 0` an explicit no-network path and reject negative limits. Disk-backed tests open
  a real second DuckDB reader from inside mocked downloads and sleeps, proving the collector has
  released its connection; they also verify persisted bars and transactional backfill progress.
- Migrated the still-pre-signal XS paper monitor explicitly from runtime-contract v2
  `c30cacb7f7056908f6945f189f5e90088734438ba9e4c029b459e246dd7b3da1` to v3
  `629f91f40fd06f1730baa7f92332351b813fa6060373a6fdc48f6c7e27fd930a`. The migration command
  validates the exact prior artifact and refuses after a signal boundary, signal-date order, or
  post-fill observation exists. Live rehearsal found latest equity 2026-09-04, zero qualifying
  future orders/fills, and no signal boundary. Candidate/control configs, September 30 signal,
  October 1 observation start, and every statistical criterion remained byte-for-byte equal.
- Final verification passes **764/764** tests with warnings as errors, repository-wide Ruff,
  Python compilation, Bash syntax, and diff hygiene. Sector, XS, and E1 runtime hashes all
  self-verify. The restarted API is healthy with zero failure restarts and projects sector
  `ACCUMULATING`, XS `WAITING`, and E1 `ACCUMULATING` at 7/40; no manual production collection
  was started, leaving the next scheduled nightly as the live-network validation.

## 2026-09-08 — observable evidence contracts and reproducible packaging

- Made `/meta` expose the validated report schema, runtime-contract version, and runtime SHA-256
  for sector and XS, matching the evidence metadata already exposed for E1. The production UI
  header now renders sector v2, XS v3, and E1 v1 beside their statuses. Both services rebuilt or
  restarted cleanly; server-rendered HTML and live JSON were checked rather than inferred.
- Repaired the Python project metadata so standard `uv run`, editable installs, source builds,
  and wheel builds work with the intentional four-package flat layout. The wheel contains only
  `engine`, `farm`, `server`, and `sim` plus frozen experiment resources; runtime data, tests,
  logs, scratch files, and the archive are excluded. Modern SPDX license metadata removes the
  setuptools deprecation warning.
- Added explicit NumPy and PyYAML runtime requirements, moved pytest and Ruff to a `dev` extra,
  and made the generated `uv.lock` trackable. Local setup and CI now use the same frozen uv
  environment; CI also builds a wheel. A static regression test checks package discovery,
  package-qualified internal imports, and direct third-party dependency declarations. This also
  fixed the installed-package-only bare `import screen` path in historical M1 replay.

## 2026-09-08 — live walk-forward evidence freshness

- Separated weekly driver health from evidence freshness. The `walkforward_evidence` object in
  `GET /meta` now checks every eligible active result against its canonical live portfolio config
  plus its persisted initial capital, named execution profile, and declared control, and requires
  one complete source, anchor, train/validate/step, fill-model, universe-policy, initial-capital,
  execution-profile, data-snapshot, and comparison-protocol cohort. Missing,
  malformed, duplicate-ID, config-drift, mixed-cohort, and stale-source states fail visibly; the
  response exposes compact hashes and cohort fields without returning the full execution profile.
- Production currently reports the honest expected state: `stale-source`, 18/18 results, source
  `7727bc6b9af2964075d782037983414929cb53d9ffb78c59fa889b3974d29d9a` versus current
  `f0110ed8081daf9a6e49e0cff80ff425b3954b15865a0462f3ffa02c8c112d14`. The coherent cohort is
  anchored 2026-09-04 with 24/12/12-month windows, fill v4, universe `all`, $39,000 capital,
  `baseline_v1` profile hash `6340e47066716dbc6d3d221007033fb67069faf9cc9ec04aa95c89ec4de574db`,
  snapshot `b1b031ac37c5b658034fd5b6234fdbe61facab5cba9cdd4afb1159c542fa3785`, and comparison
  protocol `wf-controls-2026-09-07-v1`. Historical artifacts were not rewritten or manually rerun;
  the next scheduled Sunday cohort is responsible for refreshing source provenance.
- Reconciled current operator docs with the deployed interface and automation. The walk-forward
  README is described as the latest published historical cohort rather than unconditionally
  current evidence; the dated 2026-09-06 review retains its original figures under a 2026-09-08
  freshness addendum; `/meta.*` pseudo-routes now correctly name fields inside `GET /meta`; and
  the execution design no longer claims the retired model-driven `/watchlist-scan` and
  `/trading-review` loop runs on Sunday. Current counts and schedules were checked against the
  live database, crontab, user services, and `Linger=yes`.
- Aligned the fold-level walk-forward loader with the monthly loader's full cohort identity.
  The fold report now includes the versioned comparison protocol when selecting among same-anchor
  source/data/capital/execution cohorts, so partial refreshes cannot make the two reports choose
  different evidence. Regression coverage also pins the corrected current-doc endpoint syntax and
  retired model-loop description without changing the XS runtime-contract dependency.
- Closed an unattended-operation gap: the already tested `run_weekly_liquid.sh` existed to prevent
  post-bootstrap additions from remaining non-liquid forever, but had never been installed in the
  user crontab. It is now scheduled once at Sunday 02:00 UTC, four hours before walk-forward, with
  cron active and the host confirmed on UTC. No network-heavy refresh was started manually. `/meta`
  and the UI expose `weekly_liquidity`; until its first scheduled run the honest state is `null` /
  `not yet run`, while a terminal driver failure is highlighted. The runbook names all five
  unattended engine drivers and their slots, and the installed service units match repository
  copies exactly.
- Final verification passes **792/792** tests with warnings as errors, repository-wide Ruff,
  Python compilation, Bash syntax, wheel build/metadata inspection, UI production build, and diff
  hygiene. Sector v2, XS v3, and E1 v1 runtime contracts self-verify at their frozen hashes. API
  and UI were rebuilt/restarted and are active with zero restart failures; live health, JSON, and
  server-rendered status were checked. User lingering is enabled and the weekday nightly,
  Saturday verifier/sweeps, and Sunday walk-forward schedules remain installed. The Git index is
  empty.

## 2026-09-08 — truthful liquidity projection and XS runtime-contract v4

- Exercised the production liquidity path with the explicit no-network/no-write diagnostic
  `python -m engine.collect --refresh-liquid --dry-run --limit 0`. It exposed that dry-run
  `liquid_after` repeated the stored count instead of reporting the proposed reconciliation.
  `apply_liquid_flags` now reports `liquid_before`, computes the projected post-refresh count for
  dry runs, and checks the applied count against the same projection after a real update. The
  corrected production diagnostic reports 4,118 before, 90 admissions, 151 demotions, no held-name
  exceptions, and 4,057 projected after; a separate database query confirmed the dry run left all
  4,118 stored liquid flags unchanged. The network-heavy refresh remains delegated to the first
  scheduled Sunday 02:00 UTC run.
- Because `engine.collect` is inside the frozen XS forward contract, migrated the still-pre-signal
  checkpoint explicitly from v3
  `629f91f40fd06f1730baa7f92332351b813fa6060373a6fdc48f6c7e27fd930a` to v4
  `9407d627d32910a268983cb2db1a367c3a695458b0138788c2ee10a9edb7d668`. Rehearsal and live
  migration both required that exact v3 checkpoint and retained `WAITING`, a null signal boundary,
  zero shared sessions, zero paired complete months, and no qualifying future orders or fills.
  Candidate/control configuration, signal logic, execution/fill assumptions, and statistical gates
  are unchanged; v4 exists solely for truthful operational reporting before the first signal.
- The deployed research tree now hashes to
  `9c68cf34d53c43228e65d771b0567bab525d3ffb1bba3d898ac3963e9ee3d8dc` across 111 runtime
  files. The published 18/18 walk-forward cohort remains internally coherent at source
  `7727bc6b9af2964075d782037983414929cb53d9ffb78c59fa889b3974d29d9a` and is therefore
  correctly classified `stale-source` until the scheduled refresh. Current runtime-contract
  summary: sector v2, XS v4, E1 v1.
- Post-migration verification passes all **794/794** tests with warnings as errors, Ruff,
  compilation, Bash syntax, diff hygiene, an isolated wheel build/metadata inspection, and the
  production UI build. All three runtime hashes recompute from source. The restarted API and UI
  are active/enabled with zero restarts and repository-identical unit files; `Linger=yes` and all
  five engine cron entries remain installed. Live `/health` is true, `/meta` serves liquidity
  `null`, walk-forward `stale-source` at 18/18, sector `ACCUMULATING` v2, XS `WAITING` v4, and E1
  `ACCUMULATING` 7/40 v1. The UI renders the same states, the queue has no pending/running jobs or
  actionable failures, and the Git index remains empty.
- Removed the last developer-specific absolute home paths from current operator instructions:
  settlement commands now assume the documented repository root, and the liquidity cron example
  uses `${HOME}` like the other portable installation examples. A documentation regression test
  covers every current runbook and unattended driver. This comment-only driver change leaves all
  three frozen strategy contracts unchanged; because the broader freshness digest deliberately
  covers unattended scripts, the current 111-file source hash above includes it.
- Made malformed persisted discretionary gate results visible instead of silently rendering an
  empty journal summary. `GET /journal` now keeps `gates` type-stable as an array, preserves a bad
  source value in `gates_raw`, and emits `gates_parse_error` for invalid JSON or a valid non-array
  value; the journal page displays that error. Missing legacy gate data remains an honest empty
  list. This is API/UI observability only and is outside every research runtime contract.
- Upgraded the dashboard from Next.js 16.2.10 to 16.3.4 after a production dependency audit
  identified four high-severity advisory groups in Next.js and its PostCSS, Sharp, and NanoID
  dependencies. The exact lockfile now resolves the patched transitive versions, a clean
  `npm ci` and production build pass under the service's Node 24 runtime, and `npm audit
  --omit=dev --audit-level=high` reports zero vulnerabilities. The Debian 10 host cannot load
  16.3.4's native SWC binary because it requires glibc 2.29; the production build therefore uses
  Next's prescribed `--webpack` fallback, which supports its WASM compiler. CI now runs the same
  audit and build command.
- The first managed restart exposed that compatibility boundary: three `ExecStartPre` retries ran
  the then-default Turbopack build, loaded only the WASM compiler, and failed before starting the
  server. The UI was stopped to end the retry loop, the build script was changed to Webpack, and
  the exact stripped systemd environment then built successfully before the service was started.
  No request process ran the unverified bundle; `logs/ui.log` retains the failed attempts and the
  successful fallback build.
- Audited the exact frozen Python runtime graph by exporting `uv.lock` without the local editable
  project and disabling dependency re-resolution in `pip-audit`; no known vulnerabilities were
  found. CI now repeats that lock-derived audit after `uv sync --frozen`, with the scanner pinned
  at `pip-audit` 2.10.1. The frontend job likewise audits the installed production tree after
  `npm ci`, so both ecosystems fail CI on known dependency vulnerabilities rather than relying on
  an occasional manual check.

## 2026-09-08 — interrupted-driver observability

- Closed a read-only monitoring ambiguity in which a driver start marker without a terminal
  marker could remain `running` forever after a crash or reboot. `/meta` now checks each
  driver's existing advisory lock: a held lock is authoritative live evidence, while a free
  lock classifies an unterminated run as `interrupted`. Legacy deployments with an unreadable
  lock fall back to conservative per-driver elapsed-time ceilings, and malformed or future
  timestamps are explicit `invalid` states.
- Extended the projection from the two Sunday jobs to all five installed schedules: weekday
  nightly, Saturday price verification, Saturday research sweeps, Sunday liquidity refresh,
  and Sunday walk-forward. The dashboard highlights `failed`, `interrupted`, and `invalid`
  states while treating only `ok`, genuinely `running`, and reconciled walk-forward
  `recovered` as non-alerting. This remains diagnostic only and cannot restart a job, mutate a
  ledger, promote a strategy, or authorize capital.
- Added schedule-lateness checks so an old successful log cannot conceal that cron stopped
  launching a driver. After each job-specific completion grace, a missing current-slot start is
  `overdue`; a lock still held beyond the runtime ceiling is `stale-running`. The liquidity
  deadline begins with its first installed slot on 2026-09-13, avoiding a false alert before the
  job has ever been due. The header leaves that pre-deadline `not yet run` state neutral and will
  turn it red only if the API classifies the job `overdue` after the deadline.
- Lock inspection reads Linux's `/proc/locks` by device/inode and never tries to acquire the
  driver's non-blocking lock. Health polling therefore cannot race a cron launch and cause the
  real job to abort as an apparent overlap. Liveness samples bracket the log read, covering both
  starts and finishes that race a status request without interfering with either process.
- Unreadable logs and nonempty logs without a recognized start marker now fail closed as
  `invalid`; an actually empty file remains the neutral pre-first-run state. A damaged log can
  no longer take down all of `GET /meta` or masquerade as a job that was never scheduled.
- The persistent UI header now fails visibly when `GET /meta` itself cannot be fetched. Database
  contention, an HTTP failure, and a network/backend outage render distinct red API states instead
  of leaving a set of neutral `unknown` labels that could be mistaken for missing history.
- A controlled production check stopped only the API service, fetched the still-running UI, and
  observed a red `API error 500` (Next's proxy representation of the refused upstream). The
  cleanup trap restored the API immediately; both managed services returned active with zero
  failure restarts, `/health` returned true, and the alert disappeared on the next rendered page.
- Extracted the complete driver parsing and schedule-health subsystem from the mixed
  `server.operations` module into `server.driver_monitor`. The route now consumes one centralized
  five-driver projection; tests and the documentation schedule guard import that contract
  directly. This is a behavior-preserving code-structure cleanup that keeps queue, evidence, and
  exposure logic separate from Linux cron/log/lock concerns.
- Separated the fail-soft price verifier's shell status from its evidence health. `/meta` now
  validates `_meta.json.price_verify` accounting, timestamp, operational market date, latest
  nightly relationship, checked coverage, parse errors, and disagreements as the independent
  `price_verification` object. A clean wrapper can no longer conceal stale, absent, malformed,
  partial, or conflicting verification evidence; the dashboard highlights those states.
- Normalized `GET /health` to fail closed for every database-open/query failure, not only known
  DuckDB lock errors. Healthy, contended, and unreadable states are now explicit as `ok`, `busy`,
  and `unreadable`; failures return HTTP 503 without leaking filesystem or database exception text.
- The parser audit also found that the generic start-marker expression could mistake a terminal
  `=== done ... ===` line for a driver named `done`, and that drivers without stage files emit
  a valid shorter failure marker. Both historical formats now parse correctly and are covered
  by regression tests. Verification passes 828/828 tests with warnings as errors, Ruff,
  compilation, shell syntax, frozen-lock checks, diff hygiene, npm's production vulnerability
  audit, and the Webpack production UI build. No research-runtime file changed: the current
  source remains `9c68cf34d53c43228e65d771b0567bab525d3ffb1bba3d898ac3963e9ee3d8dc`
  across 111 files.

## 2026-09-08 — isolated optional `/meta` projections

- Prevented an unexpected defect in one optional research-health projection from taking down
  the complete `GET /meta` response. Walk-forward evidence and each of the three frozen forward
  monitors now fail closed independently, retain a server-side traceback, and expose only an
  `invalid`/`INVALID` status without exception details.
- Walk-forward driver reconciliation has a narrower fallback: if reconciliation itself fails,
  the API preserves the raw cron-driver result rather than hiding a real logged failure. Opening
  the database and reading its latest market watermark remain mandatory; store failures are not
  converted into a misleading HTTP 200.
- Added regression coverage for every isolated projection, preservation of unrelated queue and
  driver status, connection closure, and raw-driver fallback. This is observability-only: no
  strategy, execution, ledger, research artifact, or promotion rule changed.

## 2026-09-08 — preserve shared miner evidence across nightly collection

- Found that `collect.write_meta()` was the sole destructive writer of the otherwise shared
  `data/_meta.json`: every weekday EOD pass replaced the complete file before the screener and
  queued miners rebuilt only their own blocks. That erased Friday's valid `fundamentals` summary
  on Monday and also transiently reset the screener-owned regime, even though job 310 was complete
  and the store contains all 4,118 fundamentals rows for 2026-09-04.
- Changed collection publication to the existing atomic merge primitive and removed its write to
  the screener-owned `regime` field. A regression seeds screen, fundamentals, and independent
  price-verification evidence, refreshes collection counters from a real temporary DuckDB, and
  proves all sibling fields survive unchanged.
- The missing live fundamentals JSON block was not synthesized from logs or aggregate table
  counts. The queue row and source table remain authoritative, and the next scheduled Friday run
  will publish a fresh genuine block that subsequent nightlies now preserve.
- Added `GET /meta.miner_evidence`, which reconciles the latest intraday, signals, earnings, and
  fundamentals queue rows with each producer's timestamped and internally consistent summary.
  The dashboard now alerts on anything short of 4/4 current. Live status correctly reads
  `incomplete (3/4)`: the three Monday miners are current, while fundamentals names completed job
  310 but reports `evidence-missing` because the old collector erased its JSON block. The monitor
  matches the queue runner's canonical nightly parameters, with a static contract test, so a later
  manual backfill or partial-source diagnostic cannot replace scheduled-job health.
- Since `engine.collect` is intentionally covered by the frozen XS source contract, this
  operational-only fix was explicitly migrated from v4
  `9407d627d32910a268983cb2db1a367c3a695458b0138788c2ee10a9edb7d668` to v5
  `a3fa0ddb512cecbc9060d29ede14277f08e4fe30f6fee1892accd0ea8bd4494a`. The guarded live
  migration verified `WAITING`, a null signal boundary, zero observations, and no qualifying
  future orders or fills before replacing the report metadata. Candidate/control registrations,
  signal date, execution, and statistical rules remain unchanged.

## 2026-09-08 — explicit sweep idle/evidence state

- Separated the Saturday sweep wrapper result from actual research publication. The recurring
  allowlist remains deliberately empty, so live `sweep_evidence` now reports `idle` with
  `no-open-recurring-charters`; this is a healthy no-search state, not a claim that new evidence
  was produced.
- For a future explicitly opened charter, the projection requires the exact `(grid,
  charter_version)` queue row, coherent completion, and the isolated versioned `ranking.json`.
  It validates report identity, minute-resolution publication time, and complete trial accounting
  against the frozen grid. Missing, stale, malformed, failed, and active states stay distinct.
- Added endpoint-isolation and state-contract tests. The dashboard renders idle neutrally and
  alerts on every state except `idle`, `current`, and genuinely `updating`. No charter was opened,
  no sweep was run, and no strategy or parameter changed.

## 2026-09-08 — serialize shared metadata publication

- Closed the remaining lost-update race in `data/_meta.json`. Atomic replacement already kept
  readers from seeing partial JSON, but parallel miners could still read the same snapshot and
  overwrite the sibling that published first. The common shallow merge now holds one adjacent
  advisory lock across its complete read/merge/replace sequence. The screener's duplicate writer
  was removed and routed through the same helper, so every current metadata publisher shares one
  concurrency contract. Deterministic lock-boundary and real multi-process regressions cover it.
- Explicitly migrated the still-pre-signal XS monitor from runtime contract v5
  `a3fa0ddb512cecbc9060d29ede14277f08e4fe30f6fee1892accd0ea8bd4494a` to v6
  `386452fb31890a413bf0db78ceb6b24aaf1ca1c57d6b94f14b2f6de9ece3e406` and added the shared
  resource helper to its frozen manifest. The guard verified `WAITING`, no signal boundary, zero
  shared sessions/months, and no signal-date orders or post-fill observations. Candidate/control
  registrations, dates, fills, and statistical gates are unchanged.
- Explicitly migrated E1 runtime contract v1
  `6cf141a68d41b01d04f910d4d64aefd333605bbb758161ad9130c2f23348ca56` to v2
  `78ca95709bdcf6bcd4026af6a0417381111fb7baa5e056a237a7497757fe8610`. All seven observations,
  the 2026-08-31 boundary, and prefix SHA-256
  `e2603b7c85f5e24e3b019a4ee7058c6732a792647b0c1c2e62a0d111fdf360ad` are unchanged. No row,
  strategy rule, execution assumption, sample limit, or verdict rule was modified.
- Final verification passes all **853/853** tests with warnings as errors, repository-wide Ruff,
  Python compilation, shell and systemd-unit validation, frozen-lock and diff hygiene, an empty
  Git index, npm's production audit with zero vulnerabilities, and the Next.js 16.3.4 Webpack
  production build. Fresh read-only evaluations exactly match both migrated artifacts, all three
  frozen runtime hashes recompute, and the restarted API/UI are healthy with zero restarts,
  `Linger=yes`, and all five deterministic cron schedules installed.

## 2026-09-08 — liquidity artifact health

- Separated Sunday liquidity wrapper health from evidence health. Before the first scheduled run,
  `liquidity_evidence` is explicitly neutral `not-yet-run`; a live driver is `updating`. After a
  successful wrapper, the API now requires a non-dry-run artifact newer than that exact start,
  reconciled admission/demotion/held and download/backfill accounting, the correct preceding NYSE
  session, and a `liquid_after` total equal to the current store. The session rule deliberately
  keeps valid Sunday evidence current after later weekday price collection.
- The persistent header renders this evidence independently and alerts on missing, stale,
  malformed, failed, or degraded results. The projection is read-only and isolated from the rest
  of `/meta`; it neither triggers an early refresh nor changes universe membership.
- Verification passes all **863/863** tests with warnings as errors, repository-wide Ruff,
  compilation, shell/unit validation, lockfile and diff hygiene, an empty Git index, npm's
  production audit with zero vulnerabilities, and the Webpack production build. All three frozen
  runtime hashes still recompute exactly. The rebuilt API/UI are active with zero restarts; live
  `/meta` and the rendered header both show the neutral first-run state.

## 2026-09-08 — recover and reconcile nightly core evidence

- Found the remaining consequence of the old destructive metadata writer: the authoritative
  2026-09-04 screen still had all 3,881 rows, its dated/latest reports, 588 passers, 59 new names,
  and risk-on regime, but the summary fields in `_meta.json` were absent. A weekend idempotent run
  correctly skipped historical recomputation but did not restore those fields.
- The `--skip-if-done` screen path now validates the dated report header against aggregate
  `screen_results`, restores `screens/latest.md`, and republishes only proven summary values. It
  never rewrites screen rows. Unrecoverable stale/phantom/short and leverage-exclusion counters are
  set to null, and the historical `screen_date` is separate from a null unknown publication time.
  The live recovery left all 147,564 stored screen rows unchanged and preserved unrelated metadata.
- Added `nightly_evidence` independently of the shell driver status. It requires the operational
  date, screen database aggregate, screen reports, every active portfolio's equity row, league
  Markdown, and the full league CSV to reconcile. Missing, stale, incomplete, and malformed states
  fail closed in the API and persistent header.
- Because the screener is frozen into the still-empty XS forward comparison, explicitly migrated
  v6 `386452fb31890a413bf0db78ceb6b24aaf1ca1c57d6b94f14b2f6de9ece3e406` to v7
  `3d3d5550bdc4b1e2989f042fa1fefaa854eb89bc799e13af5c387c482dfd9bec`. The guard again proved
  `WAITING`, no signal boundary, zero observations, and no signal-date orders/post-fill records;
  strategy, selection, dates, execution, and statistical gates are unchanged.
- Verification passes all **873/873** tests with warnings as errors, repository-wide Ruff,
  compilation, shell/unit validation, lockfile/diff/index hygiene, npm's zero-vulnerability
  production audit, and the Next.js Webpack build. Fresh XS v7 evaluation exactly matches the
  published artifact, all frozen hashes recompute, and the rebuilt services are active with zero
  restarts. Live `nightly_evidence` is `current` at 2026-09-04 with all 21 active portfolios
  represented; the header renders the restored date and valid forward contract versions.

## 2026-09-08 — fail-closed shared-metadata recovery

- Closed the last destructive fallback in the shared metadata publisher. Read-only callers may
  still tolerate a missing or malformed `data/_meta.json`, but every update now takes the
  process-wide writer lock and refuses malformed JSON or a non-object top level before replacing
  any bytes. A regression proves a malformed snapshot remains byte-for-byte untouched.
- Explicitly migrated the still-pre-signal XS monitor from runtime contract v7
  `3d3d5550bdc4b1e2989f042fa1fefaa854eb89bc799e13af5c387c482dfd9bec` to v8
  `53c5b133e420fb875453c2ff707325906d90736e857ef449cbb7123684cc4031`.
  The guard proved `WAITING`, zero shared sessions, zero paired months, no signal boundary, and no
  signal-date orders or post-fill records. Strategy, selection, execution, dates, and statistical
  gates are unchanged.
- Explicitly migrated E1 runtime contract v2
  `78ca95709bdcf6bcd4026af6a0417381111fb7baa5e056a237a7497757fe8610` to v3
  `32b56bb6b2cb4d234cf0131bf27054a024820d8207ed4130ed988a8c340b0d72`. All seven
  observations through 2026-08-31 and prefix SHA-256
  `e2603b7c85f5e24e3b019a4ee7058c6732a792647b0c1c2e62a0d111fdf360ad` remain exact;
  no experiment row, strategy rule, execution assumption, sample limit, or verdict changed.
- Verification passes all **875/875** tests with warnings as errors, repository-wide Ruff,
  Python compilation, shell and systemd-unit validation, frozen-lock and diff hygiene, an empty
  Git index, npm's production audit with zero vulnerabilities, and the Next.js 16.3.4 Webpack
  production build. A fresh XS evaluation equals the published JSON, the E1 checkpoint reconciles
  exactly to its database prefix, and all three frozen runtime hashes recompute.

## 2026-09-08 — active-paper operational scope

- Found that recurring price verification, liquidity protection, and corporate-action selection
  treated nonzero positions in retired portfolios as current exposure. This kept the settled FBRX
  symbol in nightly verification solely because the archived `news_gated_momo` book still records
  its historical shares. Recurring operations now define “held” and “pending” as state belonging
  to an active portfolio. Archived ledgers remain untouched and available for audit; genuine split
  reconciliation still rebuilds all historical books consistently.
- Added regressions proving active holdings and active pending orders remain mandatory while
  retired holdings/orders do not consume verification, liquidity, fetch, or tripwire capacity.
  A fresh normal verifier pass checked all 162 selected names, with 162 agreements, zero unchecked
  names, zero disagreements, and zero parse errors. Live `price_verification` is now `current`.
- Added the missing fail-closed migration boundary to the sector monitor: an ordinary run rejects
  an older published runtime contract, while the explicit migration accepts only an exact prior
  report. Migrated sector v2
  `1854c24767dddfa8e1f0eb2544b860c8e7c3897d82f5fb297888dd4e13eaad6d` to v3
  `20c106ed0a6a7e29ac01ba8616c44909cbadaf90f53c8c8d2712b1e50631414a`, preserving its
  one-session equity prefix and complete execution-ledger hashes exactly.
- Explicitly migrated the still-pre-signal XS monitor from v8
  `53c5b133e420fb875453c2ff707325906d90736e857ef449cbb7123684cc4031` to v9
  `a2b0cd5f0765d1183fc52a309e3214017053eac1e7b1294971b8b945c41431b0`.
  The guard proved `WAITING`, zero shared sessions, zero paired months, no signal boundary, and no
  signal-date orders or post-fill records. No strategy, signal, execution, or statistical rule
  changed in either forward monitor.
- Verification passes all **882/882** tests with warnings as errors, repository-wide Ruff,
  Python compilation, shell syntax, lockfile and diff hygiene. Both migrated artifacts reproduce
  exactly from the read-only store, and E1 remains v3 with the same seven-observation prefix.

## 2026-09-08 — current-state dashboard boundary

- Closed the remaining active-versus-retired leak in the dashboard and health read models.
  `GET /positions` and `GET /orders` now join `portfolios` and expose active books only; an
  explicit retired or unknown position lookup returns 404 instead of rendering archival shares
  as current exposure. `stale_exposure` applies the same active-book rule to pending orders.
- No ledger row was deleted or rewritten. The live store still preserves 51 nonzero position
  rows across seven retired portfolios and 107 retired filled orders for audit, while the current
  positions projection contains only its 20 active portfolio IDs. Regressions cover active
  visibility, aggregate retirement filtering, explicit fail-closed lookup, discretionary stop
  fields, order filtering, and stale pending-order filtering.
- Ticket creation also refuses an inactive discretionary portfolio, preventing a future write
  path from appending new pending intent to a retired ledger. A missing discretionary portfolio
  is still created normally on the first valid paper ticket.
- The per-book league equity endpoint and discretionary risk-state projection now also require
  an active portfolio registration. This closes direct archival-equity access through a route
  whose parent league is active-only and prevents retired discretionary holdings from being
  valued as current risk state.
- The journal payload's recent league-event feed now filters to active portfolios as well;
  discretionary ticket and round-trip history remains available as an explicit journal, and no
  underlying fill is changed.
- Verification passes all **891/891** tests with warnings as errors, repository-wide Ruff,
  Python compilation, shell and systemd-unit validation, diff and empty-index hygiene, npm's
  zero-vulnerability production audit, and the Next.js 16.3.4 Webpack build. All three frozen
  strategy runtime contracts recompute exactly at sector v3, XS v9, and E1 v3; this read-only
  presentation change does not migrate or alter forward evidence. The restarted API/UI are
  active with zero restarts, and live HTTP checks prove active-only positions/orders, 404 for a
  retired book, a valid empty active XS book, and zero stale exposure.

## 2026-09-08 — generated league-report reconciliation

- Closed a generated-report gap where `nightly_evidence` accepted `league.md` from the correct
  date without reconciling its standings body. The stale file still listed retired
  Multi-Asset Trend and a retired `news_gated_momo` stale mark even though current API views were
  already active-only. The validator now parses the generated standings table, rejects malformed
  or duplicate rows, requires unique active portfolio names, and verifies an exact match to every
  active portfolio with equity on that nightly date. Its stale-mark identities must likewise
  match active held exposure exactly. Regressions prove that an extra retired standings row or a
  retired `news_gated_momo` stale mark fails closed even under a correct date header.
- Regenerated only `data/reports/league.md` and its companion CSV through a read-only DuckDB
  connection. Database size/mtime and counts for portfolios, orders, fills, positions, equity,
  dividends, settlements, and audit records remained exactly unchanged. Markdown now contains
  21 active rows and no retired names. `league.csv` remains the deliberate complete historical
  export: 697 rows across all 29 portfolio IDs, including all eight retired IDs.
- Documentation now states the active-current Markdown versus complete-historical CSV boundary.
  Verification passes all **893/893** tests with warnings as errors, repository-wide Ruff,
  Python compilation, shell and systemd-unit validation, diff and empty-index hygiene, npm's
  zero-vulnerability production audit, and the Next.js 16.3.4 Webpack build. Sector v3, XS v9,
  and E1 v3 frozen runtime hashes remain exact; no forward evidence was migrated or rewritten.

## 2026-09-08 — current walk-forward recovery visibility

- Found that `weekly_walkforward` could report an older completed recovery while a newer exact
  18-book recovery cohort was pending or running. Reconciliation now gives the newest complete
  eligible batch precedence, reports `updating` with per-state job counts until every book is
  complete, and reports `recovered` only for an entirely successful cohort. Partial or malformed
  batches still cannot hide the original scheduled-driver failure.
- The dashboard treats `updating` as a healthy transient driver state. Regressions cover mixed
  done/running recovery, partial-batch refusal, and precedence of newer work over an older
  completed recovery. Verification passes all **898/898** tests with warnings as errors,
  repository-wide Ruff, Python compilation, diff and empty-index hygiene, npm's
  zero-vulnerability production audit, and the Next.js 16.3.4 Webpack build. The research source
  hash remains unchanged while the replacement cohort runs.
- As jobs began publishing atomically, the evidence layer correctly observed a mixed-source file
  set but presented it as a terminal-looking `mixed-cohort`. When the independently reconciled
  exact recovery batch is healthy, it now reports `updating` while retaining `artifact_status`
  for diagnosis. Invalid files and registrations still fail closed and are never masked.
- The first completed refresh tranche (`dual_momentum`, its gated twin, `sector_momentum`, and
  `spy_benchmark`) reproduces every common economic output and fold metric exactly versus the
  prior cohort. Differences are confined to the current source/data provenance, run timings, and
  newly published execution-integrity fields; this is evidence refresh, not result selection.
- The persistent header now renders the recovery's done/running/pending breakdown and includes
  running work in its queue summary, making forward progress visible without inspecting DuckDB.
- Generalized the same exact-batch projection to routine successful/running Sunday drivers and
  manual refreshes. Neutral `refresh_*` fields describe all cases; failed-run responses retain
  `recovery_*` aliases. This prevents the next normal scheduled publication from flashing a false
  terminal evidence error while preserving compatibility with existing clients.
- The first two refresh batches advanced jobs 395–404 to `done`. All 10 artifacts reproduce every
  common economic output and fold metric exactly against their prior versions; changes remain
  confined to source/data provenance, runtime timing, and newly published empty integrity fields.
  Jobs 405–410 then started automatically, with 411–412 pending behind that parallel batch. The
  runtime research hash remained
  `1b6c004a6ad366a70f5450d8a646314d958dd3a526e221278108dd6c2a05c68c` across 111 files.
- Jobs 405–410 also completed without errors, and their six artifacts likewise have zero common
  economic or fold-level differences from the prior cohort. Jobs 411–412 (`mr_overlay` and its
  gated twin) started automatically as the final parallel batch; 16/18 artifacts are therefore
  reproducibility-verified while the disconnect-safe service continues the final two.
- Documented the queue's conservative parallel-batch accounting: child artifacts publish
  atomically, but the parent cannot reacquire DuckDB's writer to finalize individual rows while
  sibling read-only workers remain open. The exact service/PID state is therefore authoritative
  when an artifact timestamp leads its still-`running` row; no queue row was manually changed.
- Jobs 411–412 completed, all 18 rows are `done`/`complete` with no errors, and the transient
  refresh service exited successfully. `/meta.weekly_walkforward` is `recovered` and
  `/meta.walkforward_evidence` is `current` with one cohort signature
  `2dabf79467b5e2142c04c817cc5c87aa58db13fa5f343492f92d54f8be1bc0ba`, source
  `1b6c004a6ad366a70f5450d8a646314d958dd3a526e221278108dd6c2a05c68c`, and data snapshot
  `d16f6337aff010dd78090410db5786ac468e0be0f85aa8ff87932d069f572cbd`. There are no missing,
  invalid, duplicate, config, or registration mismatches.
- Compared every refreshed JSON artifact with its prior `HEAD` version. All 18 have zero
  differences outside source/data provenance, generated/runtime timing, and the new empty
  execution-integrity fields. The regenerated README and per-book pages retain the same
  economic results and verdicts; no strategy was selected or promoted from historical output.
- Replaced the one test-only use of multiprocessing `fork` with `spawn`. The concurrency test
  still exercises four real cross-process metadata publishers, now without inheriting pytest's
  background threads or emitting Python 3.12's fork/deadlock warning. After the UTC freshness
  regression below, the full suite passes **899/899** with warnings promoted to errors; Ruff,
  compilation, shell/systemd validation, npm's zero-
  vulnerability production audit, the Next.js build, diff hygiene, and empty-index hygiene pass.
  Sector v3, XS v9, and E1 v3 runtime-contract hashes remain exact.
- Reclaimed the project workspace after verifying no replay or queue child remained alive. Five
  abandoned `scratch/wf__sweep__*` directories from terminated September 5–6 sweep workers
  occupied about 3.8 GiB; their authoritative job/report outcomes were already persisted. They
  were moved intact to the user's recoverable Trash at
  `~/.local/share/Trash/files/trading-engine-stale-scratch-2026-09-08/`, leaving `scratch/` at
  about 400 KiB. No report, source file, paper ledger, or job row was deleted or rewritten.
- Made `/meta.market_freshness` derive its implicit `as_of` from UTC, matching the documented UTC
  cron/report boundary instead of inheriting an arbitrary host-local timezone. An explicit-date
  regression covers the default seam. The server-only change was deployed without changing the
  111-file research source hash; API/UI remained healthy and walk-forward evidence stayed current.
- Corrected the persistent header's completed-recovery label. The API deliberately retains the
  original failed driver's `stage=enqueue` for diagnosis, but the UI no longer renders that stale
  stage as though recovery failed; it now shows `weekly research recovered (18 done)`. The
  production UI rebuilt, restarted, and rendered that exact text with zero service restarts.
- Hardened the simulator's single no-look-ahead boundary: `attempt_fill` now rejects
  `fill_date <= signal_date` with an unconditional `ValueError`, so `python -O` cannot erase the
  no-same-bar rule. A real optimized-interpreter subprocess regression covers the failure mode.
- Explicitly migrated the exact published forward checkpoints because `sim/fills.py` is frozen
  into all three contracts. Sector v4
  `d8ad1e801ee5703ae8f29e7eb9e56fa0f2736c7f9b37afc10bad1704d27276ca` retains its complete
  one-session report; pre-signal XS v10
  `90f68c2616757a724c390fb65cb9e27a9b7654ba34e2d5aab08183b689be12a9` remains `WAITING` with
  no boundary or observations; E1 v4
  `da752d28c1b9bb18e3520139bbce71c885b89b192a47d00d5cd8fbfa0f1399ae` retains all seven
  observations through 2026-08-31 and prefix
  `e2603b7c85f5e24e3b019a4ee7058c6732a792647b0c1c2e62a0d111fdf360ad`. Disposable rehearsals
  proved that only the four changing contract metadata fields differed before live publication.
- The research source fingerprint is now
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f` across the same 111
  files. Jobs 413–430 ran through the normal guarded weekly wrapper under the disconnect-safe
  transient user service `trading-engine-walkforward-refresh.service`. All 18 rows completed
  without errors and the service exited successfully. `/meta.weekly_walkforward` is `recovered`;
  `/meta.walkforward_evidence` is `current` with one cohort signature
  `3082b8dd3fdbff35acc27643e94736b7a66a2916d6762883a842eca6664aced6`, source
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f`, and data snapshot
  `d16f6337aff010dd78090410db5786ac468e0be0f85aa8ff87932d069f572cbd`; all mismatch lists are
  empty. A recursive comparison of every artifact found zero differences outside source
  provenance and generated/runtime timing fields. This refresh changed provenance, not strategy
  economics, parameters, or promotion status.
- Added a documentation-integrity regression that derives the current walk-forward source and
  cohort signatures from all 18 published active artifacts and requires both current research
  guides to name those exact values. A future report refresh can no longer leave the operating
  narrative silently pinned to an older cohort.
- Post-migration verification passes all **901/901** tests with warnings treated as errors,
  repository-wide Ruff, Python compilation, Bash syntax, `uv lock --check`, dependency
  consistency, wheel build, npm's zero-vulnerability audit, the Next.js 16.3.4 Webpack production
  build, diff hygiene, and empty-index hygiene. The API was restarted onto the new validators and
  reports Sector `ACCUMULATING` v4, XS `WAITING` v10, and E1 `ACCUMULATING` v4 with 7/40 rows.
- Added a read-only scheduler-continuity projection to `/meta` and the persistent dashboard
  header. It verifies that the host cron daemon is active and that each of the five expected
  trading-engine entries occurs exactly once in the user crontab, reporting missing or duplicate
  driver names without exposing command output. Probe failures are isolated from the rest of
  `/meta`; the monitor diagnoses but never installs entries, starts services, or repairs state.
  It also checks that the selected cron unit is enabled across reboot, the host uses UTC, each
  target script is executable, and the log directory is writable; an extra altered invocation of
  a required driver is reported as a duplicate rather than hidden by its canonical line. The
  deployed projection reports `ok` with 5/5 exact entries and the rendered header shows
  `automation ok (5/5)`. The scheduler's complete fail-closed response now comes from one helper
  shared by direct probe failures and `/meta` projection isolation, preventing schema drift. All
  941 tests pass with warnings as errors; Ruff, Python and shell
  compilation, lock/dependency checks, wheel packaging, npm's zero-vulnerability audit, the
  production UI build, systemd unit validation, diff hygiene, and empty-index hygiene pass. Both
  loopback services are active with zero restarts. The 18/18 walk-forward cohort and all three
  frozen forward-contract hashes remain unchanged.
- Made the live league's evidence role explicit without changing any paper ledger or strategy.
  `GET /league` now identifies its rank as raw total return over each book's own inception window,
  labels `vs SPY` as same-window context, and declares `evidence_role = operational_only`. The
  dashboard and League page visibly state that unequal-window rank is not evidence of
  profitability or a promotion signal; proper comparative claims remain in coherent
  walk-forward and frozen forward reports.
- Added a network-free `source_control` object to `/meta` and the persistent header. It reports
  whether the current branch has a usable local tracking ref and its cached ahead/behind relation,
  while explicitly keeping `network_checked = false`; it never fetches, pushes, or exposes remote
  URLs. The current host correctly reports `local-only`, separating healthy cron execution from
  the still-unresolved off-machine-backup requirement. Its fail-closed response is isolated from
  every other `/meta` projection.
- Added a dashboard “Prospective strategy evidence” strip so the central research state is no
  longer scattered across terse header labels and generated reports. It shows Sector Momentum's
  shared-session count and earliest verdict date, XS Momentum's complete paired-month count, first
  signal and earliest verdict date, and E1's immutable-observation count and frozen sample end.
  The API now projects the monitor-owned 200-session, 48-month, and sample-end boundaries instead
  of making the UI duplicate them. The strip states that no candidate has established prospective
  positive excess return and that these paper-only gates cannot promote a strategy, allocate
  capital, or authorize live trading. No strategy runtime, parameter, ledger, evidence row, or
  scheduler behavior changed.
- Reconciled the current README and governing design language with the deployed source-control
  state. Generated public data is eligible for Git publication only when a usable upstream is
  configured; this host is currently `local-only`, so local nightly commits are persistence on
  one machine rather than an off-machine backup. A documentation regression now requires both
  the conditional-push boundary and the present local-only disclosure.
- Extracted walk-forward queue-cohort reconciliation and published-evidence validation from the
  mixed `server.operations` module into `server.walkforward_status`. Routes and tests now import
  that owner directly, with no compatibility aliases hiding the boundary. `operations.py` fell
  from 1,413 to 1,060 lines and no longer imports execution profiles, comparison controls, or
  runtime-source provenance; it remains responsible for nightly/miner/queue/sweep/liquidity and
  stale-exposure status. This is a read-only structure change: the live 18-result cohort signature,
  API schema, strategy runtime, queue state, and paper ledger are unchanged.
- Extracted queue health and recurring-sweep evidence into `server.queue_monitor`, keeping sweep
  identity parsing beside the rule that distinguishes actionable failures from closed-charter
  history. The route and tests use the new owner directly, again without compatibility aliases.
  `server.operations` is now 812 lines (601 fewer than before these two extractions) and has no
  farm imports; its remaining scope is nightly/miner/liquidity and stale-exposure health. Direct
  live evaluation preserves 416 done jobs, zero actionable failures, one historical closed-charter
  timeout, and the intentionally idle zero-charter sweep state.
- Decomposed the network-free source-control projection into explicit branch, tracking-config,
  tracking-count, and relation stages. The public schema and current `local-only` result are
  unchanged, while each stage now has one responsibility and the main projection no longer trips
  the complexity gate. Regressions inject Git unavailability at every one of the five subprocess
  probes and require the complete fail-closed response; detached/non-symbolic HEAD is likewise
  explicit. No probe fetches, pushes, or contacts a remote.
- Extracted scheduled-miner queue/evidence reconciliation into `server.miner_monitor`, with the
  route and tests using that owner directly. Strict metadata timestamp and non-negative-count
  parsing now live in the neutral `server.status_validation` helper shared by miner, liquidity,
  and nightly projections. This structure-only change leaves the API schema, queue state, miner
  receipts, paper ledger, and research runtime untouched.
- Extracted nightly screen/league database-and-report reconciliation into
  `server.nightly_monitor`, moving its Markdown/CSV parsers beside the projection they validate.
  `server.operations` is now focused on metadata, market freshness, price verification,
  liquidity evidence, and stale exposure; the API schema and nightly evidence result are
  unchanged.
- Decomposed the new miner and nightly monitors into selection, per-source validation, report
  validation, and aggregation stages. Both modules now pass Ruff's C901 complexity check while
  retaining exact live `miner_evidence` and `nightly_evidence` payloads.
- Decomposed price-verification and liquidity-evidence parsing, reconciliation, and state
  classification inside `server.operations`. That module now passes the C901 complexity gate;
  direct evaluation retained the exact deployed `price_verification` and `liquidity_evidence`
  payloads without touching collection, strategy, simulation, or research code.
- Decomposed recurring-sweep evidence into latest-job selection, per-charter queue handling,
  ranking validation, and aggregate-state precedence. `server.queue_monitor` now passes the C901
  complexity gate while preserving the empty-allowlist `idle` state and historical/actionable
  queue classification.
- Decomposed the cron-log parser into bounded reverse-line iteration, terminal validation, and
  lock-aware unterminated-run classification, and isolated expected-slot calculation from
  schedule status. `server.driver_monitor` now passes the C901 complexity gate while preserving
  all raw driver and scheduler projections; walk-forward recovery remains a separate reconciler.
- Decomposed the Sector and XS forward-status adapters into explicit envelope, portfolio
  registration, frozen-runtime, observation/maturity, live-reconciliation, and safe-projection
  stages. Both public adapters remain fail-closed and now pass Ruff's C901 complexity gate; the
  frozen strategy contracts, source trees, evidence records, and paper-only/no-action boundary
  are unchanged. Focused regressions preserve the pre-signal XS state, stale-report handling,
  live evaluator reconciliation, finite-metric checks, and the independent E1 projection.
- Decomposed walk-forward cohort-signature validation, scheduled-job reconciliation, artifact
  scanning, state classification, response construction, and recovery overlay into focused
  helpers. All functions in `server.walkforward_status` now pass Ruff's C901 complexity gate while
  preserving newest-exact-cohort precedence, malformed-first duplicate detection, fail-closed
  registration checks, and the distinction between invalid evidence and expected in-progress
  publication. Direct live evaluation remains exactly equal: the recovered 18-job driver cohort
  and current 18/18 evidence cohort retain source, data, and cohort signatures unchanged.
- Decomposed discretionary ticket evaluation into one explicit helper per risk-control family,
  with ordered orchestration and the existing eleven-name contract assertion retained in
  `evaluate_gates`. Gate names, order, statuses, detail strings, market anchoring, stop and sizing
  calculations, experiment caps, portfolio heat, earnings acknowledgement, regime overrides, and
  circuit-breaker behavior are unchanged. The complete `server/` package now passes Ruff's C901
  complexity gate.
- Added the clean `server/` complexity threshold to CI and documented its deliberate boundary.
  Ordinary Ruff and the full test suite still cover the whole active codebase, while C901 is not
  imposed retroactively on `engine/`, `farm/`, or `sim/`: style-only churn there would change the
  source fingerprint that anchors the current published research cohort without adding evidence
  of strategy quality.
- Final verification for this server-cleanup batch passes **950/950** tests with warnings treated
  as errors, repository-wide Ruff, the server-wide C901 gate, Python and shell compilation,
  lock/dependency consistency, wheel packaging, systemd unit validation, npm's zero-vulnerability
  audit, the production UI build, diff hygiene, and empty-index hygiene. After API deployment,
  parsed `/meta` equality held for scheduler, queue, miner, nightly, weekly walk-forward,
  walk-forward evidence, Sector, XS, and E1 projections. API/UI remain active with zero restarts;
  both user units are enabled, user lingering is enabled, and system cron is active and enabled,
  so deterministic operations survive logout. The research source remains
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f` (111 files), the 18/18
  cohort remains `3082b8dd3fdbff35acc27643e94736b7a66a2916d6762883a842eca6664aced6`, and no strategy
  has established prospective positive excess return.
- Clarified the disconnect boundary in the current operator guide: cron and the enabled API/UI
  services continue without an interactive connection, but a Codex coding session does not resume
  edits by itself after disconnection. The installed API/UI units match their versioned files,
  both are enabled with `Linger=yes`, and the deterministic nightly path still invokes no LLM.
- The final documentation-boundary regression brings the verified suite to **951/951** with
  warnings treated as errors. Live handoff checks again confirm scheduler `ok`, current 18/18
  walk-forward evidence, paper-only Sector/XS/E1 monitors, API health, UI HTTP 200, and enabled
  API/UI/cron services.
- Replaced dashboard read-model N+1 queries with bounded aggregate reads without changing public
  payloads. `/league` now loads active equity histories, open-position counts, and fill counts once
  and caches the existing dividend-aware SPY comparison by inception date; `/positions` resolves
  all latest real quotes at the breadth-qualified market date in one windowed query; `/journal`
  groups all fills by order after one read. FastAPI-encoded live comparisons are exact for all
  three projections. On the current 21-book/271-position store, warm direct reads fell to roughly
  306 ms for league, 224 ms for positions, and 21 ms for journal, with no strategy, ledger, or
  research-source change.
- Centralized the discretionary ticket module's transaction lifecycle in one context-managed
  boundary. Ticket creation, cancellation, and circuit-breaker review markers still commit their
  state plus audit row atomically and roll back on any write/audit failure. The deliberate
  over-sized-sell path still commits its rejection audit before returning the client error; no
  broker integration or automatic execution was introduced.
- Replaced the League page's 21 per-portfolio equity requests with one active-only bulk projection,
  `GET /league/equities`, fetched in parallel with `GET /league`. The compatibility per-book route
  remains unchanged. Before deployment, the bulk projection exactly matched all 624 rows captured
  from the 21 existing per-book responses; a direct live-store read took about 12 ms. Regressions
  cover empty stores, active books without history, retired-book exclusion, per-book equality, and
  removal of the UI request loop. No strategy, paper ledger, research evidence, or frozen research
  source changed.
- Post-deployment verification passes all **956/956** tests with warnings treated as errors,
  repository-wide Ruff, server-wide C901, Python and shell compilation, lock/dependency checks,
  wheel packaging, systemd unit validation, npm's zero-vulnerability audit, the Next.js production
  build, diff hygiene, and empty-index hygiene. The deployed bulk response and every compatibility
  route exactly match the captured 21-book/624-row baseline; `/league` is unchanged, the rendered
  League page returns HTTP 200, and API/UI are active with zero restarts. Scheduler continuity is
  still `ok` at 5/5, the research source remains
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f` across 111 files, and
  walk-forward evidence remains current and paper-only.
- Removed another dashboard request duplication without weakening freshness. Server-rendered
  components now call the loopback FastAPI origin directly instead of re-entering Next's `/api`
  proxy, while browser requests retain the same-origin proxy. Header and Dashboard share one
  React request-scoped `GET /meta` result, so they cannot compute two expensive operational
  snapshots during one render; no result persists across page requests. The internal origin is
  configurable with `UI_INTERNAL_API_ORIGIN` and defaults to the existing loopback API.
- Kept scheduled-driver log parsing reverse-scanned and memory-bounded while filtering raw bytes
  before UTF-8 decoding and regular-expression matching. On the current four populated cron logs,
  only 131 of roughly 219,000 lines are marker candidates; the five-driver projection now runs in
  about 10 ms median and avoids roughly 39,000 Python calls in a profiled `/meta` evaluation. The
  full live driver-status object remained exactly equal, and a regression covers a 20,000-line
  log containing invalid-byte non-marker output so the optimization cannot weaken marker parsing.
- Final verification for the combined League/UI/driver-read batch passes **958/958** tests with
  warnings treated as errors, repository-wide Ruff, server-wide C901, compilation and shell
  syntax, lock/dependency consistency, wheel packaging, systemd unit validation, npm's
  zero-vulnerability audit, the production UI build, diff hygiene, and empty-index hygiene. After
  API/UI deployment, the complete driver projection and all monitored `/meta` objects exactly
  match their pre-change baselines; the League and Dashboard return HTTP 200, both services have
  zero restarts, cron is active/enabled, and `Linger=yes`. The Dashboard access-log delta proves
  exactly one `/meta` request per render. The 18/18 evidence cohort, paper-only/no-action forward
  statuses, and 111-file research-source hash remain unchanged.
- Reconciled the current strategy backlog with the live candidate-admission store: 39 universe
  dates, 38 screen dates, and 37 breadth-qualified shared dates (rather than the stale “38 each”
  wording). Documented the verified unattended producer path: weekday nightlies continue both
  intraday resolutions and point-in-time selection observations, Fridays add fundamentals, and
  the genuinely missing old fundamentals receipt remains missing until a real producer publishes
  a fresh one. No receipt was synthesized and no research threshold was relaxed.
- The documentation/data-admission regression brings the final verified suite to **959/959**.
  Repository-wide Ruff, server-wide C901, lock/dependency checks, diff hygiene, and empty-index
  hygiene remain clean; API/UI/cron remain active and enabled with zero service restarts, and the
  research source is still the same 111-file hash.
- Made the bulk League UI fail visibly without discarding usable standings. A failed or malformed
  `GET /league/equities` response now produces a curve-specific warning and labels each curve
  `unavailable`; a legitimately short series still says `not enough points`. This closes the gap
  where transport failure could previously masquerade as an empty equity history, while retaining
  the two-request flow and active-only API contract.
- Restored the accidentally dropped `$39,000` `reference_notional` field in `GET /league`, which
  the Dashboard and League page already render. Added read-only `GET /tickets/context` so the
  candidate page receives the exact discretionary equity, operational market date, 1% base risk,
  0.25% experiment cap, and 4R heat limit used by server-side ticket gates. It distinguishes an
  active book, a genuinely not-yet-created book, an inactive book, and unavailable market state.
  The ticket form no longer silently sizes from hard-coded capital after a failed request; it
  emits no suggestion and says that manual quantity will be revalidated by the server. Context is
  fetched in parallel during server rendering, with no client-side loading race or state mutation.
- Deployed and live-verified the restored League contract and authoritative ticket context. The
  post-deployment `GET /league` payload is exactly equal to its captured predecessor after removing
  only the new `reference_notional: 39000` field. `GET /tickets/context` reports active equity
  `$40,116.71744485474` as of `2026-09-04`, exactly matching a direct `risk.disc_state` calculation,
  and the server-rendered ANRO ticket form visibly identifies the rounded `$40,117` current
  discretionary equity before a stop is entered. API and UI are active with zero restarts; the
  deployment left the store at exactly 7 tickets, 1,045 orders, and 29 portfolios. Scheduler status
  remains `ok` at 5/5, walk-forward evidence remains current at 18/18, all forward monitors remain
  paper-only with no automatic action, and the protected research source remains
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f` across 111 files. The final
  collected suite contains **963 tests**.
- Simplified the persistent UI header's fail-closed `/meta` boundary: one validated response now
  supplies all monitor projections instead of repeating the same success guard for every field.
  A production deployment produced exactly identical visible candidate-page HTML after stripping
  framework script payloads. Tightened ticket hints to accept only the complete authoritative
  context contract (discretionary identity, active/new status, matching equity source, dated
  market state, positive finite equity, and bounded risk fraction), and to display the current
  equity before a stop is entered. The complete **963-test** suite passed with warnings as errors,
  the Next production build passed, and the production dependency audit found zero vulnerabilities.
  Live API/UI remained active with zero restarts; scheduler 5/5, walk-forward 18/18, paper-only
  forward states, ledger counts, and the protected 111-file source hash were unchanged.
- Made the ticket-context status itself fail closed for unusable capital. An active discretionary
  row whose computed equity is zero, negative, NaN, or infinite now returns `inactive` with no
  equity/source instead of claiming an active sizing basis; the browser independently validates
  portfolio identity, status/source pairing, date shape, equity, and risk fraction before offering
  a quantity. Regression coverage exercises all four unusable-equity cases. After API deployment,
  the real active context still exactly matches `$40,116.71744485474` on `2026-09-04`; the full
  **963-test** suite, locked-environment compilation, package build, service-unit verification,
  dependency checks, and diff/index hygiene pass, with no paper-ledger or research-hash change.
- Centralized FastAPI's request-scoped connection ownership in one context manager and converted
  every read/write route without changing its projection or HTTP semantics. Existing success,
  404, and mapped ticket-error tests still prove closure, and a new regression proves closure when
  a projection raises an unexpected exception. The deployed `/health` and ticket-context payloads
  remain valid and `/league` is exactly equal to its pre-refactor capture. Packaging includes the
  refactored server, both services remain active with zero restarts, and the suite now contains
  **964 tests**.
- Reconciled the current strategy backlog's one stale sentence with its own live inventory table:
  the store has 39 universe dates, 38 screen dates, and 37 breadth-qualified shared dates. The
  docs regression now requires the narrative and table to agree and rejects the former 38-date
  universe claim.
- Aligned candidate pages with the ticket gates' current-market boundary. `GET /candidates/{ticker}`
  now caps chart and screen data at the breadth-qualified operational date, selects the displayed
  and prefilled close with the shared real-bar predicate, and declares both dates. The ticket form
  offers a sizing suggestion only when that real quote date equals the authoritative context date.
  Live ANRO output remained exactly equal after removing the two new date fields and still renders
  the `$40,117` sizing basis. APGE proves the fail-closed path: its archived tail reaches
  `2026-09-03`, its last real quote is `2026-09-02`, and the page now visibly withholds sizing
  against the `2026-09-04` operational date. The complete **965-test** suite and production build
  pass; API/UI have zero restarts, and ledger counts plus the 111-file research hash are unchanged.
- Capped current League standings at their declared breadth-qualified `as_of` date, while leaving
  bulk/per-book equity endpoints as complete active-book history. A regression inserts a future
  equity checkpoint and proves it cannot alter the current rank/equity, yet remains present in the
  historical endpoint. The deployed 21-row League payload is exactly equal to its pre-change
  capture because the live store is coherent. The complete suite now passes **966 tests**;
  scheduler 5/5, nightly `ok`, walk-forward 18/18, paper states, ledger counts, and source hash are
  unchanged.
- Capped dashboard `GET /screen/latest` at the same operational date and made it return no current
  screen when that date is unavailable; explicit `GET /screen/{run_date}` remains the archival
  diagnostic route. Regressions cover a newer partial screen and the missing-market-date path.
  The deployed 2026-09-04 screen remains exactly equal to its prior 3,881-row/588-passing
  projection, while future partial state can no longer leak into the current dashboard. The exact
  final tree passes **969 tests** with warnings as errors plus repository Ruff, server complexity,
  locked-environment compilation/dependency checks, shell syntax, diff hygiene, and empty-index
  hygiene.
- Added row-level freshness to the live League contract. Every active row declares `equity_as_of`
  and `current`; a book behind the operational date remains visible below current rows but receives
  no rank, is labelled stale in the League UI, and is excluded from the Dashboard summary. Its SPY
  context ends on its own equity date, and bulk history is filtered to the scoreboard date before
  rendering curves. All 21 deployed books are current on `2026-09-04`; after removing the two new
  metadata fields the response is exactly equal to its pre-change capture. The complete suite,
  production build, lint/complexity, compilation, dependency, audit, diff, and index checks pass;
  services have zero restarts and paper/research state is unchanged.
- Made `GET /orders` a consistently bounded current projection. Filtered and unfiltered requests
  now return the newest 500 matching active-book orders together with `limit`, `matching_count`,
  and `truncated`; retired rows remain preserved but do not affect the count. The Positions page
  renders an explicit notice when history is truncated. Live deployment reports 500 of 938 active
  orders overall and 500 of 868 filled orders, while the three cancelled orders remain complete.
  The exact tree passes all **973 tests** with warnings as errors, repository Ruff and server
  complexity, compilation, shell syntax, locked dependency and wheel checks, the zero-vulnerability
  production audit, and the Next production build. API/UI remain enabled and active with zero
  restarts; cron is active/enabled with `Linger=yes`. Ledger counts remain 7 tickets, 1,045 orders,
  975 fills, 543 position rows, 29 portfolios, and 1,792 audit rows; queue state remains 416 done,
  1 closed historical failure, and 13 superseded. The protected research fingerprint remains
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f` across 111 files.
- Reduced the Journal read path without changing its contract: discretionary-ticket fill lookup
  now asks DuckDB only for order IDs referenced by tickets instead of loading the complete fill
  ledger into Python. On the live store that reduces the ticket-fill working set from 975 rows to
  one; the separate newest-100 active-book league-event projection is unchanged. The deployed
  `/journal` canonical SHA-256 remains exactly
  `23e3ca5add758f617dfa259b6d388e4506d8e87b6714e080db76744bca415ba1`, with 7 tickets, one
  ticket-linked fill, zero closed discretionary round-trips, and 100 league events. The complete
  suite now passes all **974 tests** with warnings as errors; Ruff, server complexity, compilation,
  diff/index hygiene, the 1,045-order ledger, and the protected 111-file research hash are
  unchanged. The API remains active with zero restarts after deployment.
- Completed the Journal's previously dead league-event surface. `GET /journal` now declares the
  100-row limit, the total active-book fill count, and whether the feed is truncated; the UI
  renders those newest fills and explicitly labels the section as an operational feed rather than
  a complete archive. Counts and rows come from one windowed query, and retired-book fills affect
  neither. Live deployment renders “Showing newest 100 of 868 active-book fills.” The full
  **976-test** suite passes with warnings as errors along with the production UI build and all
  static gates. API/UI remain active with zero restarts; ledger counts and the protected 111-file
  research fingerprint are unchanged.
- Correction to the preceding verification count: collection on that exact deployed tree reports
  **977 tests**. The complete run covered and passed all 977; the earlier 976 figure was a counting
  typo, not a skipped or failing test.
- Tightened the `GET /orders` HTTP boundary to the four persisted states (`pending`, `filled`,
  `rejected`, and `cancelled`). A misspelled filter now fails validation with HTTP 422 instead of
  returning a misleading successful empty result, and FastAPI publishes the enum in OpenAPI.
  Valid live filters retain their bounded counts (868 filled, 3 cancelled). The full **978-test**
  suite and all static gates pass; the deployed API remains active with zero restarts, and this
  read-only validation change leaves the ledger and protected research source unchanged.
- Made the Positions page fail visibly on malformed HTTP-200 payloads from its positions, orders,
  or League/filter-option dependencies. Invalid shapes can no longer crash rendering or silently
  appear as an empty current book; the normal deployed page still renders its active portfolio
  controls and the “newest 500 of 938” order notice. The full **979-test** suite and production UI
  build pass, both services remain active with zero restarts, and the protected research hash is
  unchanged.
- Extracted reusable UI response-contract helpers and applied them to both Positions and Journal.
  Bounded collections must now contain exactly `min(matching_count, limit)` rows and internally
  consistent truncation metadata; Journal also requires array-shaped tickets and round-trips.
  Malformed successful payloads therefore render the existing visible error state instead of
  crashing or appearing empty. The full **979-test** suite, production build, static checks, and
  zero-vulnerability production audit pass. Both deployed pages retain their expected live tables
  and truncation notices; services remain active with zero restarts, cron is active/enabled with
  `Linger=yes`, and the research fingerprint remains unchanged.
- Applied the shared fail-visible response boundary to Dashboard, League, bulk equity, and
  Candidate projections. Each page now validates the minimum shape it relies on—including
  screen result counts, League evidence role, equity-map shape, and candidate bar count—before
  rendering. A malformed HTTP-200 response can no longer masquerade as ordinary empty data on a
  major read page. The full **981-test** suite and production build pass, all five live pages
  render their expected content, both services remain active with zero restarts, and the protected
  research fingerprint is unchanged.
- Fixed structured API-error rendering. FastAPI validation failures carry a list of detail
  objects; the UI fetch helper previously passed that array to React, causing the server-rendered
  page itself to fail with HTTP 500. Errors are now normalized centrally into readable
  location-plus-message text. Live `/positions?status=bogus` returns a stable HTTP-200 page with
  the exact rejected-query notice, while normal Positions remains unchanged. The full suite and
  production build pass; both services remain active with zero restarts.
- Added fail-closed success-contract validation to every UI mutation client. Ticket submission now
  requires a coherent accepted/rejected gate decision, cancellation must confirm the requested
  ticket and cancelled order, and review completion must explicitly identify a successful circuit-
  breaker marker before the browser reports success or refreshes. The full **982-test** suite and
  production build pass. Deployment used read-only verification only: Candidate, Positions, and
  Journal render normally, while ticket/order/fill/audit/review-marker counts remain exactly
  unchanged and both services retain zero restarts.
- Closed the Candidate page's remaining ticket-context success boundary. The page now accepts all
  four legitimate `GET /tickets/context` states (`active`, `not-created`, `inactive`, and
  `unavailable`) only when their date, equity, source, risk, experiment-cap, and heat fields are
  mutually coherent; contradictory HTTP-200 payloads become a visible warning while manual
  quantity entry remains available under the server's authoritative gates. On the deployed ANRO
  page, the valid active context still renders the `$40,117` current-discretionary-equity basis and
  no false warning. The full **983-test** suite and production build pass; read-only verification
  left the ledger unchanged, and the protected 111-file research hash remains unchanged.
- Tightened the League's two successful-response contracts without coupling their availability.
  Dashboard and League now share validation of dated/ranked operational rows; the bulk curve feed
  additionally requires every displayed book, coherent portfolio IDs, finite equity, and strictly
  increasing dates. A malformed or omitted curve can therefore no longer masquerade as legitimate
  short history: standings remain visible, while every curve is explicitly unavailable. The live
  contract contains 21 displayed books and 624 valid ordered points. The full **983-test** suite,
  production build, static/package gates, and zero-vulnerability production audit pass. After the
  UI-only deployment both services have zero failure restarts, the ledger remains at 7 tickets,
  1,045 orders, 29 portfolios, 975 fills, 543 positions, 1,792 audit rows, and zero review markers,
  and the protected 111-file research hash remains unchanged.
- Moved `GET /meta` success validation into the request-memoized shared accessor used by both the
  persistent Header and Dashboard. An empty or incomplete HTTP-200 object now becomes the same
  visible API warning in both consumers, while a present optional driver with a legitimate
  never-run `null` value remains distinct from an omitted field and monitor-specific `invalid`
  objects retain their detailed status. The deployed projection is accepted and renders
  automation 5/5, current 18/18 walk-forward evidence, and the expected paper-only forward states.
  The full **983-test** suite and production build pass; services, ledger counts, scheduler
  persistence, empty index, and the protected 111-file research hash remain unchanged.
- Closed the remaining nested-row gaps in the primary read pages. Dashboard screen results now
  require one coherent dated passing row per ticker and an exact new-name count; Positions checks
  requested-filter identity, unique positive holdings, quote-derived valuation fields, and
  discretionary stop fields; Orders checks requested status, unique IDs, persisted enums, dates,
  quantities, and nullable ticket fields; Journal checks tickets, gate details, ticket-linked
  fills, closed round-trips, and bounded League events before rendering. Legitimate missing quotes,
  absent optional ticket fields, and explicitly unreadable stored gate JSON remain visible states.
  The production build rendered Dashboard, unfiltered and filtered Positions, Journal, League,
  and ANRO successfully against live data. The full **983-test** suite and all static/security gates
  pass; after deployment both services have zero failure restarts, ledger counts are unchanged,
  cron and lingering remain enabled, and the protected 111-file research hash remains unchanged.
- Completed the read-page contract audit with Candidate market data and research readiness.
  Candidate now requires ordered, dated, positive OHLCV bars with coherent ranges, an exact latest
  real quote, and an optional ticker/date-consistent screen row. Dashboard now requires the fixed
  three-family admission schema, non-negative and chronologically coherent coverage, statuses that
  agree with the published thresholds, and an exact `ready_families` list. This preserves honest
  `WAITING` and zero-history states while preventing malformed success data from looking like
  missing evidence or a usable chart. The deployed Dashboard and ANRO page accept their live
  contracts with no warning. The full **983-test** suite, production build, and all static/security
  gates pass; services, ledger counts, scheduler persistence, empty index, and the protected
  111-file research hash remain unchanged.
- Reconciled the documentation map and unattended-operation wording. `docs/README.md` now names
  live `/meta`, Dashboard evidence cards, and generated forward reports as current authorities and
  classifies the dated execution/capital hardening report as a historical implementation snapshot.
  The operating guide distinguishes the installed deterministic cron/systemd path from an optional
  Codex scheduled review: none is installed for this repository, the CLI is not its scheduler, and
  any future local-project task would require the machine and desktop app to remain running. The
  docs/link integrity and service-contract set passes all **43 tests**; no runtime or research
  source changed.
- Closed the ticket request shape at both HTTP and mutation boundaries. FastAPI now publishes a
  12-field `TicketRequest` with `additionalProperties: false`; unknown keys return 422 before the
  handler opens DuckDB, and direct callers receive a 400 before schema initialization or writes.
  Scalar risk fields intentionally reach the existing domain validators without coercion, so JSON
  `true` cannot become quantity `1.0`; the live endpoint returns 400 for that case. Temporary and
  deployed probes left the ledger at 7 tickets, 1,045 orders, and 1,792 audit rows.
- The live probe also exposed DuckDB's same-process read-only/read-write configuration conflict as
  an unhandled 500 when a write overlapped API reads. The server connection adapter now classifies
  that exact transient conflict as `DBBusyError`, preserving the documented HTTP 503 busy boundary
  while unrelated connection failures still propagate. The full suite passes all **989 tests**;
  production build, lint/complexity, compilation, shell, lock, wheel, and dependency-audit gates
  pass, services have zero failure restarts, and the protected 111-file research hash is unchanged.
- Separated UI transport from successful-response contracts. `ui/app/lib/api.js` now contains only
  URL/fetch/error handling and the shared validation boundary, while pure structural and coherence
  checks live in `ui/app/lib/response-contracts.js`. Dashboard screen/readiness and Candidate
  market/ticket-context checks moved out of page components; every other UI consumer imports the
  same contract primitives directly, with a regression enforcing the one-way dependency. This
  reduces Dashboard from 485 to 283 lines, Candidate from 245 to 161, and the transport helper from
  255 to 89 without changing accepted live payloads or fail-visible behavior. Both full runs pass
  all **990 tests**, including warnings-as-errors; the production build, live/malformed contract
  probes, static/package/security gates, temporary rendering of all five primary pages, diff/index
  hygiene, and systemd-unit checks pass. Seven dependency-free Node contract suites now exercise
  valid and adversarial shapes directly, run through `npm test`, and are enforced by CI before the
  production build. The ledger remains unchanged and the protected source is still
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f` across 111 files.
- Extended the same separation to operational read models: Positions, Orders, and Journal now use
  pure validators from `ui/app/lib/operations-contracts.js`, reducing Positions from 340 to 246
  lines and Journal from 325 to 225 while leaving fetch/error/render behavior local to each page.
  Three additional Node suites directly cover filter identity, quote-dependent valuation fields,
  uniqueness, bounded histories, nested gates/fills, round trips, and League events. Temporary
  production rendering caught two constants that also power the Positions filter/display layer;
  neither broken bundle was deployed, both dual-use constants were restored with regressions, and
  all unfiltered/filtered render sizes now match the deployed UI exactly.
- Moved the final League bulk-equity payload rule into the shared pure-contract module and added an
  eleventh Node suite for omitted books, mismatched portfolio IDs, unordered dates, and non-finite
  equity. League is now 179 lines rather than 205; its temporary production render is byte-for-byte
  identical to the deployed page, and the corrected batch again passes all **990 tests** with
  warnings treated as errors.
- Extracted the remaining client-mutation contracts and ticket sizing calculation from TicketForm,
  CancelButton, and ReviewDoneButton into `ui/app/lib/mutation-contracts.js`. Five new direct suites
  cover coherent submitted/rejected responses, cancellation identity, review-marker identity,
  same-date equity provenance, and bounded positive sizing inputs, bringing `npm test` to 16 suites.
  TicketForm is now 254 lines rather than 290; the clean-install UI pipeline, full **990-test**
  warnings-as-errors suite, and read-only temporary renders all pass without changing ledger state.
- Final unattended audit reports scheduler `ok` at 5/5 entries, zero actionable queue failures,
  current 18/18 walk-forward evidence, active/enabled cron, and `Linger=yes`. Weekly liquidity is
  honestly `not-yet-run`: its driver and scheduler integration landed Tuesday 2026-09-08, after the
  prior Sunday window, so its first expected execution is Sunday 2026-09-13 at 02:00 UTC. No early
  store-writing run was fabricated merely to create a receipt; the existing monitor will make a
  missing scheduled run visible after that boundary.
- Reconciled the UI guide with the final four-module contract layout and removed the obsolete `M3`
  milestone from application metadata while retaining the prominent paper-only MOCK warning.
  Header status classification and scheduler/walk-forward labels now live in the pure
  `ui/app/lib/header-status.js`; three direct suites cover healthy, updating, recovered, and fully
  degraded states. Header falls from 279 to 238 lines, `npm test` now runs 19 suites, and the full
  Python suite passes all **991 tests** with warnings treated as errors. Temporary renders preserve
  every live operational/evidence label and all primary routes return 200 without contract warnings.
- Tightened the final browser-side temporal and mutation boundaries. Exact `YYYY-MM-DD` values now
  require a real Gregorian calendar date, and timestamps require an ISO date/time with valid clock
  fields while preserving DuckDB's timezone-less microseconds and standard zoned forms. Ticket
  responses now require positive IDs, a valid signal date, non-empty typed gate results, string
  reasons, and coherent accepted/rejected outcomes; cancellation and review success payloads now
  validate positive identities, review time, and detail. Adversarial direct tests cover impossible
  dates, malformed timestamps, empty/invalid gates, invalid reasons, and zero IDs, bringing `npm
  test` to 20 suites. The root README now identifies the strategy backlog as the current decision
  ledger, live `/meta`/Dashboard/generated reports as current runtime evidence, and the 2026-09-06
  review as a detailed dated historical snapshot, with a drift regression. The production build,
  full **992-test** warnings-as-errors suite, Ruff/complexity/compile/lock/diff gates, zero-vulnerability
  production audit, and six read-only temporary production renders pass. Ledger counts remain
  unchanged, the index remains empty, and the protected source stays
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f` across 111 files.
- Consolidated positive-ID and risk-gate validation into the shared response-contract module and
  strengthened the Journal projection around persisted relationships. Rejected tickets must have
  no order; submitted/cancelled/filled ticket records must retain a positive linked order; fills
  must match their ticket's ticker and side and carry positive prices; round-trip and league-event
  prices must also be positive. Historical malformed gate JSON remains intentionally renderable
  only when the server supplies coherent non-empty raw/error metadata, preserving the visible
  corruption notice instead of hiding evidence. Direct adversarial coverage and source guards were
  extended; all 20 UI suites, the production build, full **992-test** Python suite, static/package/
  security gates, and six temporary production routes pass with no contract warnings. No paper
  state or protected research source changed.
- Closed the remaining internal-coherence gaps in Positions and Orders responses. Quoted holdings
  now require positive closes and scale-tolerant agreement between quantity/prices and market
  value, unrealized P&L, return, stop distance, and R multiple while retaining the legitimate
  no-real-quote projection. Orders now require non-empty reasons exactly for rejected/cancelled
  terminal states, null reasons for pending/filled states, and positive optional stop/target
  prices. The live 271-position and newest-500-order projections satisfy these invariants;
  adversarial fixtures cover inconsistent calculations and status/reason pairs. All 20 UI suites,
  the production build, full **992-test** suite, static/security gates, and six isolated production
  renders pass. Ledger counts, the empty index, and the protected 111-file source hash are
  unchanged.
- Split the 525-line catch-all UI response-contract module by ownership. The original file is now
  an 85-line shared primitive layer; market/screen (110 lines), league/equity (84), research/meta
  (224), operations (234), and mutation/context (125) contracts have direct one-way imports with
  no compatibility re-exports or cycles. Pages, server-side meta access, direct Node tests, the UI
  guide, and source-level architecture guards all point to the owning modules. All 20 UI suites,
  the production build, full **992-test** Python suite, static/security gates, and six isolated
  routes pass; parsed visible text and DOM structure match the deployed UI exactly. Paper state
  and the protected research source remain unchanged.
- Aligned the contract tests and final League boundary with the domain split. The aggregate
  projection suite is now named for what it covers, ticket-context checks live with mutation
  contracts, and shared non-empty strings reject whitespace-only values. League responses require
  the server's explicit `risk-on`/`risk-off`/`unknown` enum, while bulk equity requires an exact
  one-to-one key set with the validated League rows so retired or unexplained series cannot be
  silently accepted. The live 21-book League and 21-series equity responses pass. The final batch
  passes 21 direct UI suites, production build, full **992-test** Python suite, Ruff/complexity/
  compile/lock/diff gates, zero-vulnerability production audit, and six warning-free isolated
  renders; the ledger, index, and protected research hash remain unchanged.
- Corrected the preceding bulk-equity wording and contract after auditing the server's legitimate
  new-book lifecycle: `/league/equities` includes every active portfolio, including an empty series
  before its first equity snapshot, while `/league` omits books without history. The validator now
  requires every displayed League book to have a non-empty series, allows additional active-book
  keys only when their series is empty, and rejects every point after the League's authoritative
  `as_of`; the page no longer silently filters future points. Live League/equity payloads and an
  explicit empty-new-book fixture pass, while unexplained non-empty and future series fail. The
  corrected batch again passes 21 direct UI suites, the production build, all **992 Python tests**,
  and the static/security gates without changing paper or research state.
- Hardened the nested `/meta` browser contract around every field used by the persistent Header and
  prospective-evidence Dashboard cards. Runtime dates, freshness, verifier counts, queue counts,
  scheduled-driver states, scheduler continuity, source-control counts, evidence totals, and stale
  exposure now reject malformed values instead of supporting misleading labels. Legitimate sparse
  fail-closed projections, pre-first-run `null` drivers, degraded evidence states, recovery states,
  and mature forward outcomes remain accepted. All three forward monitors must retain `paper_only:
  true` and `automatic_action: "none"`; their exact three-field `INVALID` envelope cannot carry
  invented evidence, and terminal statuses require their displayed sample threshold. The exact live
  `/meta` response passes, 22 direct UI suites and the production build pass, all **992 Python
  tests** pass with warnings treated as errors, and six isolated production routes render with no
  contract warnings. Static, lock, dependency, diff/index, ledger, scheduler, and protected-source
  checks remain clean; no strategy state or research evidence changed.
- Split that newly hardened 522-line mixed research/status module by endpoint ownership:
  `meta-contracts.js` now owns `/meta` operational and prospective-monitor validation, while the
  181-line `research-contracts.js` owns only `/research/readiness`. The server-side fetch path and
  dedicated direct tests import the new owner without compatibility re-exports or dependency
  cycles, and source guards prevent the contracts from being merged back together. The documented
  UI module map now matches the implementation. The apparent 3/4 miner gap was audited but not
  rewritten: the current ledger correctly records that an old fundamentals receipt was lost before
  merge ownership existed, and only the next real Friday producer may replace it.
  A follow-up producer audit replaced the broad shared evidence-status allowlist with exact
  nightly, liquidity, miner, sweep, and walk-forward status sets, so a valid status from one
  subsystem cannot masquerade as a valid status from another. Adversarial direct tests pin those
  boundaries; recovery-only states are limited to the reconciled walk-forward driver, and the
  common nonnegative-integer primitive is tested directly. All 23 direct suites pass while the
  live payload remains valid. Queue failures, miner totals, sweep totals, stale-exposure counts,
  and source-control relation labels must also reconcile with the nested rows/counts carried by
  the same response, preventing internally contradictory status summaries from rendering. Miner
  and sweep aggregate labels are derived again from validated child-state vocabularies using the
  server's precedence, with positive coverage for fully current cohorts and adversarial coverage
  for contradictory or invented child states.
- Removed the untracked `ui/ui/tests/operations-contracts.test.mjs` orphan after confirming it was
  an older, unreferenced predecessor of the canonical `ui/tests/operations-contracts.test.mjs` and
  was outside the `npm test` glob. The canonical suite retains the old cases plus the newer
  position, order, and journal regressions; no application or research source changed.
- Removed the retired `M3` milestone branding from the active API package, connection helper, and
  OpenAPI title. The service now describes its durable role as the local paper-trading and research
  backend; a documentation regression keeps active server metadata milestone-neutral while dated
  design history remains unchanged.
- Split scheduler-installation auditing from run-log parsing: `server/driver_monitor.py` now owns
  only observed driver-run state, while `server/scheduler_monitor.py` owns exact crontab, daemon,
  boot-enablement, timezone, executable, and log-directory checks. `/meta`, direct tests, and the
  operating-guide module map now use the owning module without compatibility re-exports; the
  scheduler response schema and behavior are unchanged.
- Split the 577-line catch-all server read model by route domain: market date/screen/candidate,
  league/equity, and paper ticket-context/position/order/journal projections now have separate
  modules with one shared cursor-row primitive. Routes and direct tests import their owning module
  without a compatibility facade; response schemas and read-only behavior remain unchanged.
- Removed the generic `forward_status()` compatibility alias and made `/meta` call the explicitly
  owned `sector_status()` projection. The response field remains `forward_review`; this is a
  source-level ownership cleanup with no monitor or evidence change.
- Verified the cleanup batch with all **993 Python tests** under warnings-as-errors, 23 direct UI
  suites, the production Next build, Ruff and complexity checks, Python/shell compilation, frozen
  lock validation, zero production npm vulnerabilities, and diff/index hygiene. After deployment,
  eleven read-route payloads matched their pre-refactor JSON exactly; scheduler continuity remained
  `ok` at 5/5, both services remained active with zero restarts, paper-ledger counts were unchanged,
  and the protected 111-file research hash remained
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f`.
- Split the 479-line mixed forward adapter into explicit Sector, cross-sectional-momentum, and E1
  projection owners plus a small shared fail-closed contract module. `/meta` now invokes each owner
  directly and the old `server/forward_status.py` facade is absent; strategy-specific registration,
  runtime, observation, and live-reconciliation rules remain local to their monitor.
- Re-ran all **993 Python tests**, 23 direct UI suites, production build, Ruff/complexity,
  compilation, lock, dependency-audit, and diff/index gates after the forward split. The deployed
  `/meta` payload matches its pre-split capture exactly; Sector remains `ACCUMULATING`, XS remains
  `WAITING`, and E1 remains `ACCUMULATING`. Both services have zero restarts and the protected
  research hash remains unchanged across 111 files.
- Consolidated the three identical cursor-to-dictionary implementations used by API read models,
  stale-exposure monitoring, and queue monitoring into `server/read_model_utils.py`. This removes
  duplicate mechanics while preserving each domain's SQL and response ownership.
- Split the 436-line operational catch-all into explicit snapshot loading, market freshness/price
  verification, liquidity-evidence, and stale-exposure owners. `/meta`, direct tests, and current
  architecture docs now name each boundary; `server/operations.py` is absent rather than retained
  as a compatibility facade.
- Re-ran all **993 Python tests**, 23 direct UI suites, the production build, Ruff/complexity,
  compilation, lock, dependency-audit, and diff/index gates after the operations split. The
  deployed `/meta` response matches its pre-split capture exactly; both services remain active
  with zero restarts and the protected research hash remains unchanged across 111 files.
- Moved the dozen-monitor `/meta` composition and optional-projection isolation out of the FastAPI
  route module into `server/meta_projection.py`. `server/main.py` now owns only the HTTP boundary
  and request-scoped connection for this endpoint; monitor validation and payload fields are
  unchanged.
- Re-ran all **993 Python tests**, 23 direct UI suites, the production build, Ruff/complexity,
  compilation, lock, dependency-audit, and diff/index gates after extracting the composer. The
  deployed `/meta` payload again matches its pre-refactor capture exactly; scheduler continuity is
  `ok` at 5/5, both services have zero restarts, and the protected 111-file research hash remains
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f`.
- Split the 3,073-line server-health test catch-all into endpoint- and module-owned suites for HTTP
  routes, `/meta` composition and snapshots, market/miner/liquidity/nightly evidence, driver and
  scheduler monitoring, walk-forward and sweep evidence, queue and exposure monitoring, and the
  three forward-status adapters. Private setup helpers remain beside their consumers, the largest
  resulting file is 453 lines, and collection remains exactly **993 tests** with all 193 moved
  cases accounted for and passing under warnings-as-errors. This changes test ownership only; no
  production or protected research source is part of the split.
- Aligned the remaining 596-line dashboard read-model test file with the production split: market,
  league, and paper projections now have module-owned suites, three intentional cross-domain
  contracts have an explicit integration suite, and their small database setup primitives live in
  one test-only helper. All 24 original test names and the **993-test** repository collection are
  preserved; the largest resulting read-model suite is 263 lines.
- Split discretionary risk internals by domain while preserving `server/risk.py` as the policy
  coordinator used by ticket submission. `server/risk_book.py` now owns book identity, valuation,
  stops, and pending/open risk; `server/risk_history.py` owns FIFO round trips and circuit-breaker
  state; read models and ticket mutations import those owners directly. The coordinator fell from
  614 to 386 lines with no compatibility re-exports, and the current operating-guide module map
  names all three boundaries. Direct tests mirror the same boundary with 18 gate-policy, 3
  book-state, and 5 loss-history cases backed by one test-only setup helper. All **993 Python
  tests** pass under warnings-as-errors together with Ruff/complexity, compilation, shell, lock,
  diff, and empty-index gates. After the API restart, `/tickets/context`, aggregate and
  discretionary `/positions`, and `/journal` matched their pre-split payloads byte-for-byte; both
  services report zero failure restarts, and ledger counts plus the protected 111-file research
  fingerprint remain unchanged.
- Split the 456-line walk-forward status module by evidence boundary. The 131-line
  `server/walkforward_recovery.py` reconciles scheduled-driver state with exact queue cohorts;
  the 331-line `server/walkforward_evidence.py` validates live registrations, published artifacts,
  cohort consistency, and source provenance. `/meta`, current docs, and direct tests use the new
  owners without a compatibility facade; the former 29-test suite is now 6 recovery and 23
  evidence cases with shared setup isolated to a test helper. All **993 Python tests** and static
  gates pass; after deployment, the complete `/meta` and `/research/readiness` responses match
  their pre-split bytes exactly. Both services report zero failure restarts, and ledger counts plus
  the protected 111-file research fingerprint remain unchanged.
- Split raw driver-log interpretation from schedule policy. The new 220-line
  `server/driver_log.py` owns bounded reverse parsing, exact timestamp validation, advisory-lock
  observation, and terminal/unterminated run state; the 183-line `server/driver_monitor.py` now
  owns only expected UTC slots, grace periods, first-run boundaries, and aggregation of the five
  installed schedules. Direct tests mirror that boundary with 17 parser and 8 schedule cases,
  preserving all 25 prior cases without compatibility re-exports. All **993 Python tests**, 23 UI
  contract suites, the production UI build, Ruff/complexity, Python and shell compilation,
  lock/dependency audit, clean wheel packaging, diff hygiene, and the empty-index gate pass. A
  clean wheel contains both current owners and none of the retired server facades. After restarting
  only the API, `/meta` matches its 10,913-byte pre-split capture byte-for-byte (SHA-256
  `5a33591b9d179b4361747e80144e679978d4cc71df1ae4af80dc514177c12e4d`). API/UI remain active
  with zero failure restarts; system cron is active and enabled with all five schedules installed,
  `Linger=yes`, ledger counts are unchanged, and the protected source fingerprint remains
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f` across 111 files.
- Split generated nightly-artifact validation from nightly state projection. The 201-line
  `server/nightly_reports.py` now owns strict screen Markdown, league Markdown, stale-mark, and
  complete equity-CSV reconciliation; the 135-line `server/nightly_monitor.py` owns driver state,
  source-table checks, screen metadata, active-equity completeness, and the final evidence payload.
  The original eight scenarios remain represented as three monitor-state and five report-integrity
  cases with shared setup isolated to a test helper. All **993 Python tests**, 23 UI contract
  suites, the production UI build, Ruff/complexity, Python and shell compilation, lock validation,
  clean wheel packaging, diff hygiene, and the empty-index gate pass. After restarting only the API,
  `/meta` again matches its 10,913-byte pre-split capture byte-for-byte (SHA-256
  `5a33591b9d179b4361747e80144e679978d4cc71df1ae4af80dc514177c12e4d`). API/UI remain active
  with zero failure restarts; cron continuity, ledger counts, and the protected 111-file research
  fingerprint remain unchanged.
- Split recurring-sweep evidence from general queue health. The 203-line
  `server/sweep_monitor.py` owns recurring-charter identities, latest sweep-job selection,
  published ranking validation, and aggregate sweep evidence; the 91-line
  `server/queue_monitor.py` now owns queue counts, latest research work, and
  actionable-versus-historical failure classification. The latter consumes the sweep owner's
  identity and registry boundary explicitly, and `/meta` calls both owners directly. The existing
  13 queue and 5 sweep-evidence cases all remain in their domain suites. All **993 Python tests**,
  23 UI contract suites, the production UI build, Ruff/complexity, Python and shell compilation,
  lock validation, diff hygiene, and the empty-index gate pass. After restarting only the API,
  `/meta` again matches its 10,913-byte pre-split capture byte-for-byte (SHA-256
  `5a33591b9d179b4361747e80144e679978d4cc71df1ae4af80dc514177c12e4d`). API/UI remain active
  with zero failure restarts; system cron is active and enabled, all five schedules remain
  installed, `Linger=yes`, ledger counts are unchanged, and the protected source fingerprint is
  still `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f` across 111 files.
- Split the three independent research-data admission policies out of the aggregate readiness
  projection. `server/stock_readiness.py`, `server/fundamentals_readiness.py`, and
  `server/intraday_readiness.py` now own their exact SQL, breadth/time thresholds, and limitations;
  `server/readiness_common.py` owns only date/count normalization; and the 34-line
  `server/research_readiness.py` preserves the paper-only, non-promotional endpoint envelope and
  ready-family aggregation. No threshold or strategy state changed, and all ten readiness cases
  now patch the actual policy owner instead of coordinator internals. All **993 Python tests**, 23
  UI contract suites, the production UI build, Ruff/complexity, Python and shell compilation,
  lock validation, diff hygiene, and the empty-index gate pass. After restarting only the API,
  `/research/readiness` matches its 2,256-byte pre-split response byte-for-byte (SHA-256
  `7d7bc56c04513126f41933a69d721b6bbaac184d280f6c70f189d550939d085b`) and `/meta` retains
  SHA-256 `5a33591b9d179b4361747e80144e679978d4cc71df1ae4af80dc514177c12e4d` over 10,913 bytes.
  API/UI remain active with zero failure restarts, continuity checks remain green, the paper ledger
  is unchanged, and the protected 111-file research fingerprint is unchanged.
- Split discretionary-ticket input contracts from transactional mutations. The 132-line
  `server/ticket_contract.py` now owns the closed HTTP dataclass, allowed field set, scalar type
  checks, normalization, and client-visible validation error; the 243-line `server/tickets.py`
  retains signal timing plus atomic portfolio, order, ticket, audit, cancellation, and review
  writes. FastAPI and tests import the actual owner directly, with no compatibility re-export. All
  21 ticket cases plus the full **993-test** Python suite pass under warnings-as-errors, alongside
  23 UI contract suites, the production UI build, Ruff/complexity, Python and shell compilation,
  lock validation, diff hygiene, and the empty-index gate. After restarting only the API,
  `/tickets/context`, `/positions`, `/orders`, and `/journal` matched their pre-split payloads
  byte-for-byte. API/UI remain active with zero failure restarts, and the protected 111-file
  research fingerprint remains unchanged.
- Aligned ticket tests with the production boundary: 11 request-shape and normalization cases now
  live in `tests/test_ticket_contract.py`, eight atomic state-transition cases remain in
  `tests/test_server_tickets.py`, and two FastAPI error/connection adapters live in
  `tests/test_ticket_routes.py`; shared setup moved to `tests/ticket_test_helpers.py`. All 21
  original cases and the full **993-test** collection remain present and passing under
  warnings-as-errors. This was test ownership only; runtime state and the research fingerprint did
  not change.
- Split published walk-forward artifacts from live portfolio registration. The 217-line
  `server/walkforward_artifacts.py` now owns result schema validation, cohort signatures, bounded
  file scanning, registration mismatch detection, status classification, and response shaping;
  the 128-line `server/walkforward_evidence.py` retains DuckDB registration identity, current
  source provenance, recovery overlay, and orchestration. Tests and documentation import the real
  provenance, execution-profile, control, and artifact owners directly, with no compatibility
  re-exports. All 23 evidence and six recovery scenarios remain represented; the focused
  evidence/recovery/docs run passes 58 tests, and the full **993-test** suite passes with warnings
  as errors. Repository Ruff, server complexity, Python and shell compilation, locked dependency
  validation, wheel packaging, all 23 UI contract suites, the production UI build, and diff/index
  hygiene pass. After restarting only the API, `/meta` matches its 10,913-byte pre-split capture
  byte-for-byte (SHA-256
  `5a33591b9d179b4361747e80144e679978d4cc71df1ae4af80dc514177c12e4d`). Both services are active
  with zero failure restarts; cron remains active/enabled with all five schedules and `Linger=yes`.
  Walk-forward evidence remains current at 18/18, paper-ledger counts remain 7 tickets, 1,045
  orders, 29 portfolios, 975 fills, 543 position rows, 1,792 audit rows, and zero review markers,
  and the protected source fingerprint remains
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f` across 111 files.
- Completed the discretionary-risk ownership split without changing admission policy.
  `server/risk_market.py` now owns the 200-session SPY regime read and latest point-in-time
  earnings-window evidence; `server/risk.py` remains the ordered ticket-gate coordinator and fell
  from 386 to 331 lines. Direct earnings evidence moved to `tests/test_risk_market.py`, while
  cross-boundary regime/admission behavior remains in the policy suite; no compatibility aliases
  were retained. The focused risk/read-model/docs run passes 99 tests and the full **993-test**
  suite passes with warnings as errors. Repository Ruff, server complexity, Python and shell
  compilation, locked dependency validation, wheel packaging, all 23 UI contract suites, the
  production UI build, and diff/index hygiene pass. After restarting only the API,
  `/tickets/context` matches its 206-byte pre-split response (SHA-256
  `c4e6a784b309962d7348fc289685d27f72a87970ee27dffcf9be6217d5062010`) and `/meta` remains
  byte-identical at 10,913 bytes (SHA-256
  `5a33591b9d179b4361747e80144e679978d4cc71df1ae4af80dc514177c12e4d`).
  Both services remain active with zero failure restarts; this structural change did not modify
  the protected research implementation, paper ledger, strategy thresholds, or accrued evidence.
- Replaced the remaining mixed paper read-model module with direct endpoint owners.
  `server/position_read_models.py` owns active holdings and operational-date marks,
  `server/order_read_models.py` owns bounded active-book order history, and
  `server/journal_read_models.py` owns discretionary ticket/fill history plus the bounded league
  event feed. The 53-line `server/paper_read_models.py` now owns only ticket sizing context, and
  FastAPI imports each endpoint owner directly—there is no compatibility façade. The original 12
  direct cases are preserved as one ticket-context, four position, three order, and four journal
  tests, with the three cross-domain integration cases retained. The full **993-test** Python suite
  passes with warnings as errors; repository Ruff, server complexity, Python and shell
  compilation, locked dependency validation, wheel packaging, all 23 UI contract suites, the
  production UI build, and diff/index hygiene pass. After restarting only the API, all affected
  live responses match their pre-split bytes exactly: `/positions` 64,560 bytes (SHA-256
  `1920fc9fffcaeea6c1fabec4f801cf106122a832a105465c3ba6697d7b1dd3bc`), `/orders` 111,723
  bytes (`7e34ed8d659c1b9913bdd68bdb0757f35c7d4561692d4577c1207ae4abc92065`), `/journal`
  22,639 bytes (`d74130b507b9c3d0e83f6a2ffffadbf68aa91c97be9c25889a6f0ed66dacd4ed`), and
  `/tickets/context` 206 bytes (`c4e6a784b309962d7348fc289685d27f72a87970ee27dffcf9be6217d5062010`).
  Both services remain active with zero failure restarts.
- Split deterministic schedule evaluation from host inspection. The 76-line
  `server/scheduler_host.py` owns read-only `crontab`, `systemctl`, and timezone probes; the
  167-line `server/scheduler_monitor.py` retains exact schedule rendering, duplicate/missing
  detection, launch-readiness classification, fail-closed response shape, and orchestration.
  Seven host-probe cases moved to `tests/test_scheduler_host.py`; all existing schedule-policy,
  aggregate-meta, and documentation cases remain direct. The focused run passes 64 tests and the
  full **993-test** suite passes with warnings as errors. Repository Ruff, server complexity,
  Python and shell compilation, locked dependency validation, wheel packaging, all 23 UI contract
  suites, the production UI build, and diff/index hygiene pass. After restarting only the API,
  the canonical scheduler object matches its 307-byte pre-split capture byte-for-byte (SHA-256
  `4f662b15d065ef20982f0cf5c310f42abd225d514fef7691820b4df9d39c988f`). The independently
  scheduled nightly launched from cron at exactly `2026-09-08T22:30:01Z`, remained alive through
  that API restart, and `/meta` correctly projected `nightly.status=running`, `lock_held=true`, and
  `nightly_evidence.status=updating`. This directly verifies disconnect-safe execution rather than
  inferring it from configuration alone.
- Corrected the current strategy backlog's evidence-authority boundary while the independently
  scheduled nightly was advancing the store. Rapidly changing universe, screen, fundamentals,
  intraday, and miner counts are now explicitly labeled as the **2026-09-08 pre-nightly baseline**;
  `GET /research/readiness` and `GET /meta` are named as the live authorities. Documentation tests
  enforce that boundary without freezing observation counts that become stale during a normal
  unattended run. All **993 Python tests** pass with warnings as errors, together with repository
  Ruff, server complexity, Python and shell compilation, locked-dependency validation, all 23 UI
  contract suites, the production UI build, diff hygiene, and the empty-index gate. The protected
  strategy/research fingerprint remains
  `44641be995d3b1dda59732f52076138b40d983d94eda22211dbae17a17a5d82f` across 111 files;
  strategy rules, admission thresholds, accrued evidence, and automation are unchanged.
- Updated Next's permitted transitive `baseline-browser-mapping` dependency from 2.10.43 to
  2.11.21, removing GHSA-w5vr-8v7q-w6rv without changing direct UI dependency versions. A clean
  `npm ci`, all 23 UI contract suites, the production build, and a full low-threshold npm audit
  pass with zero vulnerabilities. CI and the contribution guide now reject moderate-or-higher
  production npm advisories instead of only high-or-higher findings.
- Applied the same live-authority boundary to E1: the current strategy backlog no longer embeds
  its advancing observation count as present-tense truth. The generated E1 report and
  `GET /meta`'s `e1_forward` projection own the current count and running statistics, while the
  exact seven-observation 2026-08-31 checkpoint and its hash remain documented as immutable
  historical provenance. The frozen 40-observation decision gate is unchanged.
- Relabeled the operating guide's APH/VFLO discussion as a dated 2026-09-05 incident rather than
  current verifier state. `GET /meta`'s validated `price_verification` and `price_quarantines`
  projections are now explicitly authoritative for live status, while the linked incident audit
  remains historical evidence.
- Removed the current guides' hard-coded claim that this host is `local-only`. The read-only
  `source_control` projection now owns that mutable host state; the guides retain the durable rule
  that a remote URL without a usable branch tracking ref cannot pull, push, or provide an
  off-machine backup.
- Audited Ruff formatting separately from the enforced lint and complexity gates. The formatter
  reports 189 pre-existing files that it would rewrite, including protected research source; a
  bulk style-only rewrite was deliberately not applied because it would invalidate published
  source fingerprints without changing behavior. The contribution guide now states that
  formatting is not yet a repository gate and requires an explicit evidence migration before a
  protected-source formatter pass.
- Final verification after the authority and dependency cleanup passes all **994 Python tests**
  under warnings-as-errors, all 23 UI contract suites, the production Next build, repository
  Ruff, server complexity, Python/shell compilation, frozen lock validation, Python and npm
  dependency audits, wheel packaging, Markdown-link checks, diff hygiene, and the empty-index
  gate. Both deployed services remain active with zero restarts, and the protected 111-file
  research fingerprint remains unchanged.
- Split the 572-line documentation-test catch-all by evidence ownership without changing its 30
  contracts. General guide/link checks remain in `tests/test_docs.py` (271 lines), deployment and
  source-ownership checks moved to `tests/test_docs_architecture.py` (141 lines), and live-versus-
  dated research evidence checks moved to `tests/test_docs_research_evidence.py` (177 lines). The
  focused three-file run collects 16 + 6 + 8 unique cases and passes under warnings-as-errors;
  production code and protected research source are untouched.
- The independently scheduled 2026-09-08 nightly completed at 23:29:35 UTC with API/UI continuity
  and zero service restarts. Earnings job 433 pulled its pre-fix 2,983-name universe successfully:
  2,806 names returned dates, 177 returned honest empty outcomes, and none failed. A live source
  audit then found that the default selector's fundamentals/latest-screen union admitted 118 ETFs
  and 23 inactive names. `engine.earnings` now applies the authoritative final `universe.active`
  and non-ETF boundary after the union, reducing the current default set from 2,983 to 2,842 while
  preserving Yahoo mappings. The fresh-store fallback is active/liquid/non-ETF; an explicit ticker
  override remains unrestricted and order-preserving. Eight focused earnings cases cover source
  age, failed screens, missing universe rows, eligibility, fallback, mapping, and override behavior.
- Because that correction changed the protected 111-file source fingerprint to
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, the active 18-book
  walk-forward cohort was refreshed without changing strategy rules. An initial jobs 434–451 batch
  accidentally inherited the moving 2026-09-08 anchor; it was stopped before any artifact
  publication and every row was marked `superseded` with the reason recorded in DuckDB. The
  corrected jobs 452–469 explicitly pinned the frozen 2026-09-04 anchor and ran to completion under
  the disconnect-safe user service
  `trading-engine-walkforward-earnings-selector-refresh-pinned-20260908.service`. All 18 rows are
  `done`/`complete`, no queue or worker remains, the service result is success, and `/meta` reports
  `weekly_walkforward = recovered` plus current 18/18 evidence with no missing, invalid, duplicate,
  config, or registration mismatches.
- The replacement cohort has data snapshot
  `a3823b32b5f04344fb909d1fd72c6db6e27812752f8ec99ce8408ed28ff4d668` and signature
  `6830280328e305fceb9bfa469d0142d956a2ddc40a7cb6600dc2133546f6a960`; fill model v4,
  `baseline_v1`, $39,000 capital, the 24/12/12-month protocol, and comparator protocol
  `wf-controls-2026-09-07-v1` are unchanged. Strict comparison with the saved prior 18-artifact
  snapshot found six books different only in approved provenance/runtime fields. Eleven
  screen-driven books also have 1,107,456 rather than 1,107,457 passing historical-screen rows and
  changed screen timing. XS alone changed economically at full precision in its last fold: validate
  return 44.9166529% → 44.9167235% and ending equity $94,960.2749 → $94,960.3212, with derived
  summary statistics moving correspondingly below displayed precision. The nightly advanced the
  data snapshot and Yahoo's mutable historical cache between cohorts, so exact economic
  reproduction is not claimed. Rounded reports, rankings, and research decisions are unchanged;
  no strategy was selected or promoted.
- After every refresh worker terminated, the four unpublished wrong-anchor scratch trees were
  moved intact to recoverable Trash under
  `~/.local/share/Trash/files/trading-engine-aborted-wf-2026-09-09/`; no `scratch/wf__*` directory
  remains. The operating guide now states the earnings selector's active/non-ETF boundary and its
  unrestricted explicit override, backed by a documentation regression. Final verification passes
  the complete 1,026-test Python suite with warnings as errors, repository Ruff and server C901, Python and
  shell compilation, frozen-lock validation, strict Python and npm dependency audits, wheel
  packaging, all 23 UI contract suites, the Next production build, Markdown/documentation checks,
  diff hygiene, and the empty-index gate. API and UI remain active with HTTP 200 and zero restarts;
  all three prospective runtime contracts recompute exactly at Sector v4, XS v10, and E1 v4.
- Added `tools/audit_walkforward_migration.py`, a reusable fail-closed old/new cohort comparator.
  The saved baseline directory defines scope; missing replacements fail, unrelated retained
  artifacts are disclosed, and only whole data-snapshot provenance, source/Git/generated stamps,
  top-level scratch/runtime timing, and per-fold runtime are accepted automatically. Every other
  changed JSON path is emitted and causes exit 1. Twenty-one direct cases cover approved drift,
  exact-path diagnostic/economic reporting, missing artifacts, malformed JSON, CLI exit semantics,
  and fail-closed validation of source/Git hashes, timestamps, timings, and snapshot structure.
  Snapshot validation also recomputes the canonical SHA-256 of `tables`, rejecting a well-formed
  but false digest even when both compared artifacts contain the same invalid snapshot.
  `CONTRIBUTING.md` now gives the exact command and explicitly forbids widening the allowlist merely
  to make a migration pass. Applied to the 2026-09-09 refresh, the tool compares all 18 saved
  artifacts, reports the eight unrelated retained files separately, and exits 1 with the same 34
  reviewed differences recorded above.
- Preserved immutable copies of both 18-artifact migration cohorts under
  `data/reports/walkforward/migrations/2026-09-09-earnings-selector/`, replacing the temporary-only
  baseline as the reproducible audit source. A regression pins all 36 JSON paths and bytes to
  aggregate digest `6584e73a7535ee1101ff58ffca990fab7f2e87d2cb0fce5cc7d20150f91aed24`
  and reproduces the reviewed 34-path result. Generated timestamps must now include an explicit
  timezone; date-only and timezone-naive values fail closed.
- Hardened intraday candidate admission so a ticker appearing for one or two bars can no longer
  inflate research coverage. Schema-v6 readiness derives expected bars from the published NYSE
  schedule and counts a ticker-session toward breadth only with at least 75% coverage. This admits
  legitimate early closes, rejects truncated normal sessions, and assigns zero usable breadth to
  unknown/closed dates. The projection exposes observed and usable minimum breadth and carries the
  rule through the strict UI contract. On the live store all 44 one-minute
  and 97 five-minute dates still clear the 500-name gate, now with measured minimum usable breadth
  of 709 and 907 names respectively; all intraday research remains `WAITING` on time/sample size.
- Schema-v7 stock-selection readiness now measures the actual same-date ticker intersection
  between `universe_snapshot` and `screen_results`; two disjoint tables with individually large
  row counts can no longer clear the breadth gate. All 38 live shared dates have exact screen-to-
  universe membership, so the current 3,878-name minimum and `WAITING` verdict are unchanged.
- Schema-v8 fundamentals readiness now requires finite positive market cap and at least one finite
  valuation value. It rejects future `NaN`/infinite payloads without imposing a positive-ratio
  selection bias: finite negative P/E, price-to-book, and EV/EBITDA remain valid observations.
  The live eight-snapshot minimum remains 2,863 usable equities and the verdict remains `WAITING`.
- Schema-v9 makes source shape explicit for every readiness family: `ready`, `missing`, or
  `invalid-schema`, with exact missing tables and columns. Malformed legacy stock/intraday tables
  now return a safe diagnostic `WAITING` projection instead of raising SQL errors, and neither the
  backend nor strict UI contract can derive `READY_FOR_CHARTER` unless inputs are `ready`.
  Discovery is scoped to DuckDB's current catalog/schema, so an attached or shadow relation with
  the same table name cannot satisfy an absent main-store input or redirect a readiness query.
- Schema-v10 extends the same fail-closed source contract to column types. Rightly named legacy
  columns stored as incompatible strings/integers now produce exact `incompatible_columns`
  diagnostics and `WAITING` instead of reaching an `isfinite`, date, or interval SQL error.
- Closed the retained-migration snapshot-integrity gap: the auditor now recomputes each
  `data_snapshot.sha256` from the canonical compact, key-sorted `tables` payload instead of merely
  accepting a 64-character digest. One-sided and identical-on-both-sides forged hashes each fail
  once at `$.data_snapshot`. The live walk-forward evidence validator enforces the same invariant,
  so malformed or mismatched snapshots cannot be reported as a current cohort. Both readers also
  reject duplicate JSON keys and non-finite numeric encodings rather than silently retaining the
  last value or accepting Python-only JSON extensions. A shared strict server reader now applies
  that policy to walk-forward registrations/results, sector/XS reports, E1 checkpoints, sweep
  rankings and queue identities, scheduled-miner identities, ticket-gate metadata, and the health
  snapshot. Unregistered legacy result files are classified before strict evidence validation, so
  their historical Python-only `NaN` values remain ignorable without weakening validation of any
  registered artifact. The immutable 36-file evidence digest remains
  `6584e73a7535ee1101ff58ffca990fab7f2e87d2cb0fce5cc7d20150f91aed24`, and the real audit still
  compares 18/18 artifacts, reports exactly 34 reviewed paths, and exits 1 intentionally.
- Verification after this hardening passes all **1,053 Python tests** with warnings as errors,
  23 UI contract tests, the production UI build, repository Ruff and server C901, Python and shell
  compilation, frozen-lock validation, strict Python and npm dependency audits, wheel packaging,
  diff hygiene, and the empty-index gate. The protected research source remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` across 111 files. API and UI
  remain active with zero restarts; `/health` is healthy, the dashboard returns HTTP 200, and live
  schema-v10 readiness still has no family eligible for a charter.
- Closed the walk-forward completeness gap between the frozen ten-fold plan and each artifact's
  self-reported retained count. Every eligible live registration now carries `N_FOLDS = 10` into
  evidence validation. Retained protocol/result folds and explicit drops must jointly account for
  indices 1–10 exactly once; a drop requires `status: dropped`, a non-empty reason, and valid
  train/split/validate geometry. Honest retained terminal states remain `ok`, `inert`, or
  `skipped`—the gate proves complete disclosure, not profitability. Adversarial tests cover an
  undisclosed missing fold, retained/drop overlap, an index outside the planned grid, malformed
  drop records, and the valid production shape of nine retained plus one disclosed drop.
- Verification after planned-fold accounting passes all **1,065 Python tests** with warnings as
  errors, 23 UI contract tests, the production UI build, repository Ruff and server C901, Python
  and shell compilation, frozen-lock validation, strict Python and npm dependency audits, wheel
  packaging, diff hygiene, and the empty-index gate. Direct validation of the live cohort remains
  `current`: 18/18 artifacts, with no invalid files, missing results, duplicate IDs, config or
  registration mismatches. The retained migration audit still compares 18/18 artifacts, reports
  exactly 34 reviewed differences, and exits 1 intentionally. The protected research fingerprint
  remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`
  across 111 files. After an API-only restart, `/health` is healthy, the dashboard returns HTTP
  200, walk-forward evidence remains `current` at 18/18, sector/E1 are `ACCUMULATING`, XS is
  `WAITING`, and research readiness still reports `ready_families=[]`. Both persistent user
  services remain enabled and active with `Linger=yes`; the five unattended schedules are intact.
- Bound each artifact's fold dates to the protocol that it declares. Evidence validation now
  reconstructs the ten calendar windows from `anchor`, train/validate/step months, and the
  registered fold count, then applies the producer's disclosed `data_floor` rule exactly: folds
  whose validation opens at or before the floor must be dropped, and retained folds may only clamp
  their training start up to that floor. This rejects internally self-consistent shifted dates,
  omitted floor-driven drops, invalid/exhausting floors, and geometry the producer could not have
  emitted while preserving `sector_momentum`'s real one-drop/two-clamp history.
- Verification after fold-date binding passes all **1,070 Python tests** with warnings as errors,
  23 UI contract tests, the production UI build, repository Ruff and server C901, Python and shell
  compilation, frozen-lock validation, strict Python and npm dependency audits, wheel packaging,
  and diff hygiene. Direct live validation remains `current` at 18/18 with no invalid files or
  registration/config mismatches. The retained migration audit remains 18/18 with exactly 34
  reviewed differences and intentional exit 1; the protected 111-file research fingerprint and
  empty Git index are unchanged.
- Removed the artifact-controlled trust edge from that geometry check. Walk-forward registration
  now independently derives each active book's data floor from the live `prices` history using the
  producer's exact required-ticker map and 252-session warmup, and requires the artifact's floor to
  match. A forged earlier floor can no longer justify extra retained folds; missing required bars
  or an unavailable price table invalidate the affected registration instead of accepting stale
  geometry. The real 18-book cohort still matches every independently derived floor.
- Verification after live-floor binding passes all **1,073 Python tests** with warnings as errors,
  repository Ruff and server C901, Python and shell compilation, frozen-lock validation, strict
  Python dependency audit, wheel packaging, diff hygiene, and the retained 18/18 migration audit
  with exactly 34 reviewed differences and intentional exit 1. UI code was unchanged from the
  immediately preceding green 23-test production build and zero-vulnerability npm audit. The
  protected 111-file research fingerprint and empty Git index remain unchanged.
- Bound the cohort to the frozen live protocol constants as well as to its internally consistent
  geometry. Every active registration now requires 24-month train, 12-month validate, and
  12-month step windows plus ten planned folds. A uniformly rewritten cohort can no longer evade
  mixed-cohort detection and call a different experiment `current`. The anchor remains the latest
  stored session at the weekly run rather than today's weekday price date, preserving the intended
  weekly refresh semantics.
- The final protocol-identity verification again passes all **1,073 Python tests** with warnings as
  errors, repository Ruff/server C901, Python and shell compilation, frozen-lock validation,
  strict Python dependency audit, wheel packaging, diff hygiene, and the retained 18/18 migration
  audit with exactly 34 reviewed differences and intentional exit 1. The immediately preceding UI
  build remains applicable because no UI files changed.
- Made every published walk-forward summary a derived claim instead of a second trusted input. The
  live validator now runs the producer's `summarize()` over retained fold records and requires
  exact canonical equality with the artifact summary, covering fold/inert counts, validate fills,
  win rate, mean/median/best/worst return, train and validate CAGR, decay, Sharpe, drawdown, latest
  return, and the closed field set. Twelve adversarial variants prove that a plausible edited
  headline metric or an extra summary field invalidates the result. All 18 live summaries
  recompute exactly from their folds.
- Verification after summary binding passes all **1,085 Python tests** with warnings as errors,
  23 UI contract tests, the production UI build, repository Ruff/server C901, Python and shell
  compilation, frozen-lock validation, strict Python and npm dependency audits, wheel packaging,
  and diff hygiene. The retained migration audit remains 18/18 with exactly 34 reviewed
  differences and intentional exit 1; the protected source fingerprint and empty index remain
  unchanged.
- Hardened the underlying successful-fold records that feed those summaries. The live validator
  now requires coherent first/split/last session bounds, exact train-to-validation equity handoff,
  initial-capital and return-base agreement, endpoint-derived total return and CAGR, elapsed-year
  and overlapping-session arithmetic, valid fill counts, truthful data-floor clamp flags, ordered
  monthly points that span the validation endpoints, and finite/domain-valid risk statistics.
  Overflowing CAGR inputs fail closed. `inert` and `skipped` remain honest non-results when they
  carry an explicit reason and remain excluded from the summary.
- Verification after fold-level arithmetic binding passes all **1,111 Python tests** with warnings
  as errors, 23 UI contract tests, the production UI build, repository Ruff/server C901, Python
  and shell compilation, frozen-lock validation, strict Python and npm dependency audits, wheel
  packaging, and diff hygiene. All 179 successful folds in the active 18-book cohort satisfy the
  new checks; the retained migration audit remains 18/18 with exactly 34 reviewed differences and
  intentional exit 1. Daily-path statistics such as Sharpe and maximum drawdown are range-checked,
  not independently recomputed, because compact artifacts do not retain their daily equity path.
- Bound producer-owned cohort labels to live implementation identity. Every active registration
  now requires the simulator's current fill-model version, the producer's resolved leveraged-
  product universe policy, and the strategy classifier's data-quality label. Uniformly rewriting
  all files can no longer turn a different fill arithmetic, inclusion policy, or survivorship/
  look-ahead disclosure into a coherent `current` cohort. A malformed live policy fails closed as
  invalid registrations instead of crashing projection.
- Verification after producer-assumption binding passes all **1,113 Python tests** with warnings as
  errors, 23 UI contract tests, the production UI build, repository Ruff/server C901, Python and
  shell compilation, frozen-lock validation, strict Python and npm dependency audits, wheel
  packaging, and diff hygiene. Direct live validation remains `current` at 18/18 with no invalid
  files or registration/config mismatches; the protected source fingerprint and empty index are
  unchanged.
- Removed an ambiguity in the current documentation map: its rule said a dated top-level title
  denotes a historical snapshot, while the current strategy decision ledger itself carried a date
  in that title. The backlog now has an undated current-ledger heading, records when it was last
  reconciled, and explicitly delegates advancing runtime state to `GET /meta`,
  `GET /research/readiness`, and generated forward reports. A documentation contract protects the
  distinction while leaving all dated measurements and historical evidence unchanged.
- Bound the current operator guide and strategy backlog to the readiness producers' exact stock,
  fundamentals, and intraday admission constants. The regression contract now checks sample
  counts, calendar spans, breadth floors, required 1m/5m resolutions, and per-ticker session
  coverage directly from the live server modules, preventing prose from silently lowering or
  overstating the data gate while unattended evidence accumulates.
- Verification for the documentation cleanup passes all **1,114 Python tests** with warnings as
  errors, repository Ruff and server C901, and diff hygiene. The API health check remains healthy,
  the production UI returns HTTP 200, both user services are enabled and active with lingering,
  and all five trading-engine cron schedules remain installed. The protected research source is
  unchanged at `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`
  across 111 files, and the Git index remains empty.
- Corrected four completed fixed-instrument charter titles that still described themselves as
  prospective despite their explicit `REJECT-V1` outcomes. A lifecycle contract now binds each
  displayed charter ID and closed status to its published machine-readable decision and verifies
  the paper-only/no-action envelope, preventing rejected experiments from looking like open
  authorization for another run or paper book.
- Extended the charter lifecycle contract to executable registration state: the XS momentum
  control must remain active, `multi_asset_trend` must remain explicitly retired, and the
  withdrawn XS reversal design must remain absent from `CONFIGS`. This keeps current prose from
  silently disagreeing with which strategies the paper league can instantiate.
- Removed an unused server database-settings re-export and replaced suppressions around the
  FastAPI database-contention handler with explicit request/exception types and intentionally
  unused parameter names. A route contract now proves that its stable HTTP 503 response does not
  disclose the underlying DuckDB lock detail.
- Added a dynamic documentation-index contract over `docs/charters/*.md`, so every frozen,
  completed, retired, or withdrawn research charter must remain discoverable from the current
  documentation map instead of becoming an unreviewed orphan.
- Added the missing sweep-family guide and corrected the documentation map's overly broad claim
  that every report family has a root README. The guide inventories every retained legacy grid,
  makes the current strategy backlog authoritative over old “next step” ranking prose, and binds
  its no-rerun statement to the actually empty `OPEN_RECURRING_GRIDS` mapping.
- Added family indexes for experiment and capital-sensitivity evidence. Dynamic contracts require
  every experiment directory and every sampled-capital strategy to remain listed. The guides
  separate E1's still-accumulating 40-observation record from five closed historical studies and
  state explicitly that cost tolerance or sampled capacity is not proof of a profitable edge.
- Hardened the shared discretionary-ticket transaction boundary to roll back on process-level
  interruption as well as ordinary exceptions. A regression test interrupts an audit after writes
  begin and proves that no portfolio, order, or ticket survives and that the connection can start
  a fresh transaction, preventing cancellation from stranding partial paper state.
- Removed a stale lint suppression from the optional `/meta` projection boundary while preserving
  its documented fail-isolated behavior. The broad catch remains intentional: one diagnostic
  monitor may report `invalid` without hiding unrelated operational and research state.
- Verification after the charter/report-family and transaction cleanup passes all **1,122 Python
  tests** with warnings as errors, 23 UI contract tests, the production UI build, repository Ruff
  and server C901, Python and shell compilation, frozen-lock validation, strict Python and npm
  dependency audits, wheel packaging, and diff hygiene. The protected research source fingerprint
  and empty Git index remain unchanged.
- Unified discretionary buy-ticket timing around one captured submission timestamp. The earnings
  blackout horizon, next-fill signal date, ticket `created_at`, and audit timestamp can no longer
  cross different wall-clock boundaries inside one request. Direct and full-path tests freeze the
  timestamp and verify the seven-day earnings edge plus persisted timestamps deterministically.
- Made the earnings risk gate point-in-time at that same submission instant. Its latest-snapshot
  query now excludes `as_of` dates in the future, so prematurely loaded or malformed future
  metadata cannot replace information actually available when the ticket was judged. A regression
  test proves the current snapshot still triggers the blackout when a later snapshot is present.
- Final verification for this cleanup increment passes all **1,124 Python tests** with warnings as
  errors, 23 UI contract tests, the production UI build, repository Ruff and server C901, Python
  and shell compilation, frozen-lock validation, zero known Python/npm dependency vulnerabilities,
  wheel packaging, and diff hygiene. The protected 111-file research source fingerprint and empty
  Git index remain unchanged.
## 2026-09-09 — generated-evidence map and ticket event consistency

- Added `data/reports/README.md` as the root evidence map and linked it from the documentation
  index. It classifies all nine top-level report entries by lifecycle and authority, distinguishes
  active-only standings from the complete retired-inclusive CSV, and makes explicit that
  historical validation, rankings, capacity, execution drag, or partial paper observations do not
  establish profitability or authorize promotion. A dynamic documentation contract requires every
  future top-level report entry to remain discoverable from that map.
- Added the forward-family guide and a dynamic artifact-index contract. It identifies each
  Markdown/JSON monitor pair, records the distinct 12-month/200-session and five-year/48-month
  maturity boundaries, and separates generated evidence detail from `/meta` validity. Waiting,
  accumulating, and eventual continue states remain explicitly non-promotional and paper-only.
- Unified the circuit-breaker review event around one captured timestamp. Its review marker,
  audit-row timestamp, audit payload, and API response can no longer disagree across a clock
  boundary, while the existing transaction still commits or rolls back both writes together.
- Verification for this increment passes all **1,127 Python tests** with warnings as errors,
  23 UI contract tests, the production UI build, repository Ruff and server C901, Python and shell
  compilation, frozen-lock validation, strict Python and npm dependency audits, wheel packaging,
  systemd-unit validation, and diff hygiene. The protected research source remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`
  across 111 files, and the Git index remains empty.
- Clarified the walk-forward directory's four evidence layers: generated human-readable pages,
  moving canonical JSON results, dated monthly snapshots, and immutable migration comparisons.
  The guide explicitly separates the 18 active/replayable summary pages from eight retained legacy
  pages. Dynamic contracts bind that split to the live registry, require every page to have its
  sibling result and every monthly snapshot to retain its Markdown/JSON pair; archived results
  cannot be mistaken for live validity or independent prospective evidence.
- Indexed all 15 detailed legacy backtest pages from their family guide and bound every retained
  machine-readable result to an indexed book. The guide keeps the whole cohort explicitly
  `legacy_unstamped`, in-sample, non-promotional, and unable to authorize another run.
- Kept those two navigation layers durable by placing them in stable `GUIDE.md` files rather than
  generated `README.md` outputs that the next backtest or walk-forward renderer overwrites.
- Extended documentation discoverability contracts to every top-level guide and design spec, and
  require every top-level report directory to retain its own family README. New evidence or
  operating documents can no longer become silent orphans as the repository evolves.
- Centralized strict `YYYY-MM-DD` parsing at API/evidence boundaries. Python's permissive ISO
  parser previously normalized compact dates and ISO week dates; screen routes, nightly and
  liquidity metadata, prospective monitor artifacts, and walk-forward artifacts now reject those
  alternate spellings instead of silently treating them as canonical producer output.
- Consumer-level regressions now exercise that strict boundary through market verification,
  liquidity and nightly reconciliation, sector/XS/E1 prospective status, and walk-forward
  protocol geometry. Final verification passes all **1,146 Python tests** with warnings as errors,
  23 UI contract tests, the production UI build, repository Ruff and server C901, Python and shell
  compilation, frozen-lock validation, zero known Python/npm dependency vulnerabilities, wheel
  packaging, systemd-unit validation, and diff hygiene. The retained migration audit remains
  intentionally `changed` (exit 1) at 18/18 artifacts with no missing/additional files and exactly
  34 reviewed differences. The deployed API rejects noncanonical route dates, both services remain
  active and enabled with zero restarts and `Linger=yes`, all five application schedules remain
  installed, the Git index is empty, and protected research source remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`
  across 111 files.
- Extended the same canonical-input rule to evidence timestamps. Shared validation now rejects
  non-string, compact, week-date, space-separated, naive, and noncanonical fractional timestamp
  spellings instead of coercing them through `str()` or Python's permissive ISO parser. Price
  verification, liquidity reconciliation, and walk-forward recovery fail closed when publication
  or driver boundaries are malformed; valid `Z` and explicit-offset timestamps retain their
  existing UTC semantics. Verification after this increment passes all **1,160 Python tests** with
  warnings as errors, repository Ruff and server C901, Python and shell compilation, frozen-lock
  and environment checks, wheel packaging, diff hygiene, the unchanged protected 111-file source
  fingerprint, and an empty Git index. Dependency and UI inputs were unchanged from the immediately
  preceding zero-vulnerability audit, 23-test run, and successful production build.
- Bounded every growing Journal feed. The API now returns only the newest 100 discretionary
  tickets, newest 100 completed round-trips, and newest 100 active-book fills, with independent
  limit/count/truncation metadata. Ticket-linked fill loading is restricted to displayed order
  IDs instead of scanning all historical discretionary fills. The UI validates and discloses each
  bound; the circuit breaker still computes from complete round-trip history. Verification passes
  all **1,163 Python tests** with warnings as errors, 23 UI contract tests, the production UI build,
  repository Ruff/server C901, and diff hygiene. Protected research source and the empty Git index
  remain unchanged.
- Bounded `/meta.queue` failure detail to the newest 100 actionable and newest 100 historical
  rows. Classification still scans the complete failed-job history and exposes exact all-time
  totals, while independent limits and truncation flags prevent the operational response from
  growing forever. The UI contract verifies total/detail consistency, and the persistent header
  continues to alert from the complete actionable total rather than the bounded detail length.
  Verification passes all **1,165 Python tests** with warnings as errors, 23 UI contract tests,
  the production UI build, repository Ruff/server C901, Python and shell compilation, and diff
  hygiene. The protected 111-file research fingerprint remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and the Git index is empty.
- Bounded both active-book equity-history routes to the newest 500 observations per portfolio.
  Exact per-book matching counts and truncation flags remain visible, returned points stay in
  chronological display order, and the League UI discloses shortened curves. Operational League
  returns, rankings, and max drawdowns still use complete history. The current 21-book projection
  has 645 matching points, so deployment preserves every live point while preventing unbounded
  future response growth. Verification passes all **1,166 Python tests** with warnings as errors,
  23 UI contract tests, the production UI build, repository Ruff/server C901, Python and shell
  compilation, and diff/index hygiene. After deployment, both routes report all 645 current
  points across 21 active books with no truncation; API/UI are active with zero restarts and the
  League page returns HTTP 200. Protected research source remains unchanged.
- Aligned both equity-history projections to the same breadth-qualified operational `as_of` date
  used by League standings, so a later-dated equity row cannot leak into or invalidate a current
  curve. The response declares that boundary and its counts cover eligible rows through it;
  complete-history League analytics retain the same boundary. The `/meta` client contract now
  also validates every returned queue failure and latest-research-job field instead of trusting
  count coherence alone. The complete verification set remains **1,166 Python tests** with
  warnings as errors, 23 UI tests, production build, Ruff/C901, compilation, and diff/index
  hygiene.
- Normalized queue `updated_at` values to explicit UTC ISO timestamps at the read boundary. Queue
  producers write UTC instants into DuckDB's timezone-naive `TIMESTAMP` column; the API now restores
  the declared `+00:00` interpretation instead of emitting ambiguous wall-clock strings, and the
  UI contract rejects queue timestamps without an offset. Historical job rows were not rewritten.
  Final verification for the combined queue/equity cleanup passes all **1,167 Python tests** with
  warnings as errors, 23 UI contract tests, the production UI build, repository Ruff/server C901,
  Python and shell compilation, and diff/index hygiene.

## 2026-09-11 — bounded screen navigation

- Paginated both latest and dated screen projections at 100 passing names per page. Complete
  screened/passing/new-today totals remain unchanged; stable RS-rank/ticker order, page offsets,
  page-local new counts, total-page accounting, and previous/next flags make every candidate
  reachable without returning the whole universe-derived list at once. The dashboard preserves
  server rendering, validates the requested page identity, exposes previous/next links, and offers
  a last-page recovery link for an out-of-range page. A temporary HTTP audit on the 2026-09-10
  screen reached all 495 passers exactly once across five pages, preserved all 45 new-today names,
  and returned 422 for zero, negative, non-integer, or over-limit page values. The full verification
  set passes all **1,170 Python tests** with warnings as errors, 23 UI contract tests, the production
  UI build, repository Ruff/server C901, Python and shell compilation, and diff/index hygiene.
  Production pages 1–5 expose all 495 unique September 10 passers, page 6 offers a last-page recovery
  link, and both API/UI services remain active and enabled with zero restarts.
- Bounded stale-exposure details defensively for outage conditions: `/meta` now returns at most 100
  stale positions and 100 stale pending orders while preserving exact full counts and a complete
  distinct-ticker total for the header alert. One shared latest-real-price scan computes both
  classes and their totals; the current 20-million-row store reads in roughly 44 ms warm versus
  roughly 79 ms before. Consumer validation covers detail lengths, truncation, row identities,
  positive quantities, signal dates, and the strict pre-`as_of` stale relationship. Final combined
  verification passes all **1,173 Python tests** with warnings as errors, 23 UI contract tests,
  the production UI build, repository Ruff/server C901, Python and shell compilation, and
  diff/index hygiene; the protected 111-file research fingerprint remains unchanged.
- Separated published walk-forward result validation from cohort reconciliation. The artifact
  module now owns only the deep result schema and canonical cohort signature; the new cohort
  module owns filesystem scanning, registration mismatch detection, status classification, and
  response shaping. The live evidence orchestrator and operating map use those explicit owners,
  reducing the former 543-line mixed-responsibility module to a 416-line validator plus a
  133-line cohort owner without changing evidence semantics. Verification passes the complete
  Python suite with warnings as errors, repository Ruff/server C901, Python compilation, and diff
  hygiene. The protected fingerprint remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` across 111 files, and the
  Git index remains empty. All 23 UI contract tests and the production build also pass. After the
  API-only deployment, `/health` is healthy, the service is active with zero failure restarts, and
  the complete live `walkforward_evidence` object is identical to its pre-deployment snapshot:
  `current`, 18/18 results, one cohort signature, and no invalid or mismatched artifacts.
- Removed another unbounded operational read from recurring-sweep evidence. The monitor now scans
  historical sweep jobs newest-first in 256-row batches and stops as soon as the newest job for
  every open charter is found, rather than materializing every sweep job ever recorded on each
  `/meta` request. A focused cursor regression proves newest-job precedence, malformed-row
  tolerance, traversal across batches, and the early-stop boundary. The public projection is
  unchanged; with the current empty recurring allowlist it remains explicitly healthy `idle` and
  does not authorize a strategy search. Combined verification passes all **1,174 Python tests**
  with warnings as errors, repository Ruff/server C901, Python compilation, and diff/index
  hygiene. After API deployment the complete `sweep_evidence` object is identical to its captured
  predecessor; API/UI remain active and enabled, dashboard and League return HTTP 200, scheduler
  continuity is 5/5, and `Linger=yes` keeps unattended work independent of this connection.
- Reworked discretionary FIFO history as a shared streaming primitive. Journal still exposes the
  newest 100 closed round trips with an exact complete-history count, but retains only that bounded
  deque instead of constructing every round-trip dictionary. The circuit breaker now consumes the
  same stream while retaining only the last three post-review trips and the exact trailing-session
  R sum, eliminating its second full-history list. Fill rows are read in 256-row batches; ticket
  risk metadata is deduplicated by newest ticket ID before joining. Regressions preserve partial
  FIFO matching, missing-stop fallback R, marker reset, trailing-window behavior, minimal-schema
  empty history, and exact newest-row/count behavior across multiple cursor batches. Final
  verification passes all **1,176 Python tests** with warnings as errors, repository Ruff/server
  C901, Python compilation, protected fingerprint and diff/index hygiene. After API deployment,
  `/health` is healthy and the complete `/journal` JSON is identical to its pre-deployment
  snapshot; the active service has zero failure restarts.
- Made nightly League CSV reconciliation streaming and exact. The validator now advances the
  generated CSV reader and ordered `sim_equity` cursor in lockstep, fetching database history in
  256-row batches instead of building two complete all-history lists on every `/meta` request.
  Identity, order, and tight equity-value comparisons are unchanged; a sentinel boundary still
  rejects either an extra published row or a missing one. A regression crosses the cursor batch
  boundary and corrupts the final row, proving that the complete stream is checked. Direct
  production reconciliation remains `current` for all 21/21 active portfolios. Final combined
  verification passes all **1,177 Python tests** with warnings as errors, all 23 UI contract tests,
  the production UI build, repository Ruff/server C901, Python compilation, protected fingerprint,
  and diff/index hygiene. After API deployment the complete live `nightly_evidence` object is
  identical to its predecessor; API/UI are healthy, active, enabled, and independently persistent.
- Removed the discretionary valuation N+1 query pattern. `risk_book.disc_state()` now loads all
  held positions, their latest real marks at the operational date, and their latest valid stops in
  one bulk query restricted to held tickers, rather than issuing one price query and one stop query
  per position. The query excludes phantom zero-volume flat bars, ignores cancelled stop tickets,
  preserves deterministic ticker order, and handles a missing ticket table. A query-count
  regression proves that growing from one to four holdings adds no SQL round trips; focused ticket,
  risk, and context suites pass, and production valuation remains $39,959.04 with the same DELL
  mark and stop at roughly 9–12 ms warm.
- Final verification for bulk discretionary valuation passes all **1,179 Python tests** with
  warnings as errors, repository Ruff/server C901, Python compilation, the exact protected
  111-file fingerprint, and diff/index hygiene. After API deployment, `/tickets/context`, the
  complete `/journal` response, and nightly/sweep/walk-forward/stale-exposure projections are
  identical to captured predecessors. Candidate and Journal pages return HTTP 200; both services
  remain active, enabled, and connection-independent with `Linger=yes`.
- Bounded walk-forward driver recovery scans. Reconciliation now reads jobs newer than the driver
  boundary in newest-first 256-row batches, retains at most one candidate cohort, and stops at the
  newest exact eligible set instead of materializing every later walk-forward job. Oversized,
  malformed, and partial newer cohorts remain non-authoritative while an older exact cohort can
  still recover the driver. A cross-batch regression proves that fallback, and direct production
  reconciliation remains the same genuine recovered 18/18 cohort published at
  `2026-09-09T02:21:39.988557`.
- Final bounded-recovery verification passes all **1,180 Python tests** with warnings as errors,
  repository Ruff/server C901, Python compilation, the exact protected fingerprint, and empty-index
  hygiene. After API deployment, the complete `weekly_walkforward`, `walkforward_evidence`, and
  queue objects are identical to captured predecessors; API/UI remain active and enabled with
  zero failure restarts and the dashboard returns HTTP 200.
- Changed League standings aggregation from complete in-memory equity arrays to streaming,
  constant-size per-book summaries. The calculation still consumes every active-book equity row
  through the operational date, but retains only the latest date/value, running peak and maximum
  drawdown, and six values needed for the five-session return. A regression forces multiple cursor
  batches and verifies a drawdown whose peak lies outside the retained tail, proving the metric is
  still complete-history. Current warm latency remains roughly 253–259 ms; this is a bounded-memory
  cleanup, not a performance claim.
- Final streaming-standings verification passes all **1,181 Python tests** with warnings as errors,
  repository Ruff/server C901, compilation, protected fingerprint, and diff/index hygiene. After
  deployment, the complete `/league` response is identical to its predecessor across all 21 books,
  including ranks, full-history drawdowns, five-session returns, SPY context, and freshness; the
  League page returns HTTP 200 and both persistent services remain healthy.
- Bounded scheduled-miner reconciliation. The monitor now scans miner jobs newest-first in 256-row
  batches and stops after finding the newest canonical nightly invocation for intraday, signals,
  earnings, and fundamentals, rather than materializing all history for those four kinds. Strict
  JSON identity still rejects malformed parameters and ignores newer ad-hoc variants. A cross-batch
  regression proves newest-canonical precedence and the early-stop boundary. Production remains
  honestly `incomplete` at 3/4 because fundamentals job 310 still lacks its historical receipt; no
  evidence was reconstructed and no research job was started.
- Final bounded-miner verification passes all **1,182 Python tests** with warnings as errors, all
  23 UI contract tests, the production UI build, repository Ruff/server C901, Python compilation,
  documentation/link contracts, the exact protected fingerprint, and diff/index hygiene. After
  API deployment the complete `miner_evidence` object and related nightly/walk-forward projections
  are identical to captured predecessors. Both services are active and enabled with zero failure
  restarts, `Linger=yes`, and the dashboard returns HTTP 200.

## 2026-09-11 — bounded operational market-date reads

- Profiled the live API rather than treating remaining `fetchall()` calls as automatic cleanup
  targets. The dominant shared read cost was breadth-qualified market-date resolution: its
  exhaustive query joined about 18.8 million live price rows and grouped all 16,281 stored dates
  whenever `/meta`, league, positions, screens, or ticket context needed the current date.
- `server/market_read_models.py` now probes at most 32 newest stored dates against the unchanged
  active-liquid breadth and real-bar rules. The normal current-date query takes about 8 ms on the
  live store. If no recent date qualifies, it invokes the canonical exhaustive implementation,
  preserving an exact answer even after an unusually long partial or phantom tail.
- Consolidated discretionary risk reads onto that same server-owned resolver. The protected
  engine/farm/sim/pyproject research boundary and canonical engine market-date implementation are
  unchanged. Regressions prove both the no-fallback current-date path and exact long-tail fallback.
- Full verification passes all **1,184 Python tests** with warnings as errors, documentation,
  packaging and service-contract tests, repository Ruff/server C901, Python compilation, the exact
  protected 111-file fingerprint, diff hygiene, and an empty index. After API deployment, all nine
  captured responses (`/meta`, League and equities, positions, orders, journal, latest screen,
  research readiness, and ticket context) are byte-for-byte identical. Typical warm latency fell
  from about 0.66 s to 0.44–0.47 s for `/meta`, 0.39 s to 0.12 s for League, 0.36 s to 0.13 s for
  positions, 0.32 s to 0.06–0.08 s for the latest screen, and 0.33 s to 0.07 s for ticket context.
  API/UI remain active and enabled with zero failure restarts, `Linger=yes`, and HTTP 200 health.
- Narrowed stale-exposure quote reconciliation to the union of tickers in active held positions
  and active pending orders. It first checks those names on the current operational date and only
  scans complete quote history for the subset that is genuinely stale. The prior query grouped
  history for all 12,023 stored symbols even though only 118 symbols currently have active
  exposure; the measured all-current path now takes about 5–7 ms. Exact counts, ordering,
  truncation, and last-real-quote diagnostics remain intact for every stale ticker.
- Removed a second full JSON decode for each registered walk-forward result. The scanner still
  rejects duplicate keys at every nesting level, identifies unregistered legacy artifacts before
  applying strict numeric rules, and recursively rejects non-finite values in every registered
  payload. On the current 26-file/18-registration result set, parsing falls from roughly 16–18 ms
  to 11 ms without caching or weakening live artifact validation.
- Final verification after both follow-up changes passes all **1,189 Python tests** with warnings
  as errors, documentation/packaging/service contracts, repository Ruff/server C901, compilation,
  diff/index hygiene, and the exact protected fingerprint. After deployment, the complete `/meta`
  payload remains byte-for-byte identical. Warm `/meta` requests are now typically 0.37–0.40 s;
  both services remain active and enabled with zero failure restarts and `Linger=yes`.
- Bulk-loaded the 253rd-bar data floors for all tickers required by active walk-forward
  registrations. Eighteen books currently share only 13 distinct required tickers; one windowed
  query now replaces repeated per-book/per-ticker lookups while preserving book-specific missing-
  history failures. The bulk SQL itself takes roughly 9–14 ms, and the complete live registration
  phase falls from about 105–120 ms to 28–35 ms.
- Final verification passes all **1,190 Python tests** with warnings as errors, documentation,
  packaging and service-contract checks, repository Ruff/server C901, compilation, the exact
  protected 111-file fingerprint, diff hygiene, and an empty index. The deployed `/meta` payload
  remains byte-for-byte identical and now typically completes in 0.28–0.29 s warm, versus the
  original 0.66–0.78 s samples. Scheduler 5/5, nightly current, walk-forward 18/18, sweep idle,
  and the honest miner 3/4 state are unchanged; both persistent services remain healthy.
- Cached only the deterministic NYSE schedule generated for an observed intraday date range.
  Building that schedule repeatedly cost about 172–196 ms, while the 28-million-row database
  coverage aggregation remains live on every readiness request. The cache is bounded to 16 date
  ranges and cannot hide new bars or change readiness counts.
- Final verification passes all **1,191 Python tests** with warnings as errors, documentation,
  packaging and service-contract checks, repository Ruff/server C901, compilation, the exact
  protected fingerprint, and diff/index hygiene. The deployed readiness payload is byte-for-byte
  identical. After one cold schedule build, repeated `/research/readiness` requests complete in
  about 0.15–0.21 s instead of 0.38–0.40 s, while all database coverage is still recomputed.
  Research admission remains honestly closed: `ready_families=[]`, with intraday at 46/252 1m
  sessions and 99/252 5m sessions.
- Reused the already-resolved operational market date when ticket risk evaluation computes the
  SPY regime. Standalone regime callers retain automatic date resolution, while one ticket no
  longer repeats the breadth-qualified date query inside the same database transaction.
- Final verification passes all **1,192 Python tests** with warnings as errors, the expanded
  documentation/packaging/API/ticket contract suite, repository Ruff/server C901, compilation,
  the exact protected fingerprint, and diff/index hygiene. After deployment, `/meta` and
  `/tickets/context` remain byte-for-byte identical to their captured predecessors. Both services
  are active and enabled with zero failure restarts; warm `/meta` remains about 0.27–0.37 s.
- Added a credential-free Friday postflight that reads the live `/meta` projection after the
  scheduled producer window and fails closed unless the Friday nightly, fatal-core evidence, and
  all four canonical miner receipts are current from that same run. The auxiliary check never
  creates jobs, reconstructs evidence, or changes paper state. Corrected the operator guide to the
  current official Codex contract: `codex exec` can run in scheduled jobs, but this host's CLI is
  not authenticated and no unattended model review is installed. The postflight is scheduled for
  Saturday 05:15 UTC, after the nightly's 04:30 completion boundary and the weekly verifier's
  05:00 runtime ceiling but before the 06:00 sweep driver; the earlier 03:30 placement could have
  reported a false failure for a slow but still in-window producer. The narrow
  postflight is therefore used for evidence verification without adding an LLM to the deterministic
  trading/research dependency chain. Verification passes all **1,202 Python tests** with warnings
  as errors, 23 UI contract tests, repository Ruff/server C90, Python and shell compilation, lock
  consistency, wheel packaging, the exact protected 111-file fingerprint, diff/index hygiene, and
  live scheduler continuity at 5/5.
- Made the auxiliary postflight observable rather than leaving its result in a log that required
  manual inspection. The tool atomically replaces `logs/friday-postflight.json`; a dedicated
  server validator reconciles schema, Friday/Saturday slot identity, observation time, nightly
  window, all four canonical job IDs, and every receipt timestamp. `/meta.friday_postflight` is
  neutral before the first run and during a 15-minute grace, then reports current, failed, stale,
  overdue, or invalid. The strict UI payload contract validates every shape and the persistent
  header alerts only actionable states. This remains an observer: no queue, producer metadata,
  research artifact, or paper ledger is modified. Verification passes all **1,214 Python tests**
  with warnings as errors, 24 UI contracts, the production UI build, repository Ruff/server C90,
  compilation, lock and wheel checks, the exact protected fingerprint, and diff/index hygiene.
- Made manual Friday postflight inspection non-publishing. Non-publishing is the default, while
  explicit `--dry-run` documents operator intent; both execute the same strict API and evidence
  checks, print the same bounded JSON result, and return the same success/failure code without
  calling the atomic receipt writer. The installed Saturday cron uses explicit `--publish` for the
  authoritative receipt, and an alternate `--receipt` path is rejected without that opt-in.
  Regression tests cover successful, failed, default, and invalid-path invocations so inspection cannot
  replace production postflight state. A live pre-run check returned the expected failure for the
  previous Thursday nightly and left the not-yet-created production receipt absent. Verification
  passes all **1,228 Python tests** with warnings as errors, 24 UI contracts, the production UI
  build, repository Ruff/server C90, compilation, shell syntax, lock and wheel checks, the exact
  protected 111-file fingerprint, diff hygiene, and the empty-index gate.
- Clarified the documentation authority map for unattended Friday evidence. The raw receipt is an
  input, not a live status by itself: operators use `/meta.miner_evidence` for the canonical
  producer cohort and `/meta.friday_postflight` for schedule/grace/staleness interpretation. A
  documentation contract prevents that distinction from disappearing while old but structurally
  valid receipts remain possible.
- Closed the remaining explicit-publication foot-gun at the producer boundary. The canonical
  receipt now rejects non-Friday dates, pre-monitor dates, any Friday other than the most recent
  UTC Friday, and execution before the corresponding Saturday 05:15 UTC slot, before it reads the
  API or writes a file. Explicit alternate receipt paths remain available for isolated forensic
  capture. The producer and consumer now enforce the same schedule semantics.
- Split postflight nightly-window, miner-cohort, and per-miner receipt validation into focused
  helpers without changing its schema or failure messages. The operator tool now passes C901, and
  CI extends the established support-code complexity gate from `server/` to `server/ tools/` while
  continuing to leave evidence-anchored `engine/`, `farm/`, and `sim/` outside style-only churn.
  CI's explicit byte-compilation set now includes `tools/`; the changed tool and focused tests are
  formatter-clean without imposing a repository-wide formatting migration.
- Tightened Friday evidence identity across producer, API projection, and browser validation. All
  four canonical miner receipts must now carry distinct positive queue job IDs; one completed job
  cannot masquerade as multiple producer kinds even if a malformed payload repeats it. The tool
  imports the canonical miner set from the schedule-aware server validator instead of duplicating
  that constant.
- Aligned failed-receipt production with its consumer schema. Producer errors are stripped,
  defaulted if empty, and capped at the shared 1,000-character limit, while Python and browser
  consumers reject oversized reasons. An unusually long transport/path error can no longer make
  the postflight tool publish a receipt that `/meta` immediately classifies as invalid. A direct
  producer-to-server round trip covers the failed form, and the browser counts Unicode code points
  rather than UTF-16 units so the same 1,000-character contract holds across Python and JavaScript.
- Final verification for this support cleanup passes all **1,231 Python tests** with warnings as
  errors, 24 UI contracts, the production UI build, repository Ruff, the expanded `server tools`
  C901 gate, compilation, shell syntax, lock/wheel checks, Python and npm vulnerability audits,
  the exact protected 111-file fingerprint, diff hygiene, and an empty index. After API/UI
  deployment, `/meta` remained byte-for-byte identical; jobs/orders/fills stayed
  475/1,064/1,039 with zero pending/running jobs. Both services are active and enabled with zero
  failure restarts, and the authoritative postflight receipt remains absent before its first slot.
- Bounded the postflight HTTP input to 1 MiB by reading at most limit-plus-one bytes before strict
  JSON decoding. The live `/meta` response was about 11 KiB at implementation time, leaving ample
  headroom while preventing an operator-supplied URL from streaming unbounded data into cron.
  Boundary tests cover exact-limit acceptance and one-byte-over rejection.
- Corrected postflight observation-time semantics: schedule admission and default-Friday selection
  use the pre-request clock, while receipt `checked_at` is sampled after fetch and validation. A
  response whose nightly completes during the HTTP request can no longer produce a receipt that
  the schedule-aware consumer rejects for claiming evidence newer than its observation. A direct
  round-trip regression simulates that boundary.
- Extended scheduler observability to the disconnect-safe Friday postflight without changing the
  five-production-driver contract. `scheduler` still reports production continuity as 5/5, and
  now separately validates the exact Saturday 05:15 UTC auxiliary command as 1/1, including
  missing and duplicate detection. The browser validates those fields and renders both counts in
  the persistent automation label, so a deleted or altered postflight schedule is actionable
  before the first receipt becomes due. The live read-only host probe reports 5/5 production and
  1/1 postflight with active, boot-enabled UTC cron. Final verification passes all **1,232 Python
  tests** with warnings as errors, all 24 UI contracts, the production UI build, repository Ruff,
  `server tools` C901, Python/shell compilation, lock and wheel checks, diff hygiene, the exact
  protected 111-file fingerprint, and an empty Git index. The deployed API and UI are active and
  enabled with zero restart failures; the dashboard renders `ok (5/5 · postflight 1/1)`. Database
  counts remain 475 jobs, 1,064 orders, and 1,039 fills with no pending/running job, while Friday
  evidence remains correctly `not-yet-run` before tonight's nightly and Saturday's first slot.
- Hardened the same auxiliary scheduler check from command presence to launch readiness. The
  read-only probe now also requires the cron-selected `.venv/bin/python` to be executable and
  `tools/verify_friday_postflight.py` to be readable; either absence makes scheduler health
  `misconfigured` and names `friday_postflight` as unlaunchable. The API/browser schema and header
  diagnostics carry that condition explicitly, and a temporary-repository test proves a perfect
  5/5 + 1/1 crontab still fails closed when those launch prerequisites are absent.
- Broadened duplicate detection to recognize both the canonical `python -m
  tools.verify_friday_postflight` invocation and direct `tools/verify_friday_postflight.py` paths.
  An alternate spelling or schedule can no longer create two writers while the monitor reports
  the canonical entry as healthy.
- Tightened scheduler launch checks to require regular files, not merely paths that satisfy
  `os.access`. A directory placed at a production-driver, virtual-environment Python, or verifier
  module path now fails closed; a regression covers both production and auxiliary impostors.
- Reconciled a remaining generated-report wording conflict without mutating frozen research code
  or a renderer-owned artifact. `data/reports/walkforward/GUIDE.md` now explicitly identifies the
  generated index's “Sunday review loop” sentence as retained historical workflow language,
  records the 2026-08-18 model-loop retirement, and directs decisions to the current ledger and
  prospective monitors. A documentation contract preserves that distinction until a deliberate
  evidence migration can update the protected walk-forward renderer.
- Removed the matching ambiguity from the current root README: Sunday is now described as
  deterministic walk-forward revalidation, while the retired autonomous model review and the
  non-authorizing role of any explicit human review are stated directly. A documentation contract
  prevents the obsolete “feeds the Sunday review” shorthand from returning to the current entry
  point.
- Added the remaining dependency-maintenance layer from the dated architecture review. A
  version-2 Dependabot configuration proposes grouped weekly minor/patch updates for the root
  `uv` dependency set, GitHub Actions, and the `ui/` npm tree, while major updates remain separate.
  The ecosystem names were checked against GitHub's current support table so `uv.lock` is owned by
  the dedicated `uv` updater rather than the legacy `pip` ecosystem. It grants no automatic merge
  or deployment path; existing CI still decides whether any proposal is safe. A parsed
  configuration contract verifies all three ecosystems, directories, cadence, and the absence of
  automatic-merge language.
- Reduced CI's ambient authority by declaring workflow-level `contents: read`. Checkout, audits,
  builds, and tests need no repository write token; a contract rejects any future `contents:
  write` expansion in the current workflow.
- Added a compact current architecture flow to the operating guide. It maps public collection and
  all five production schedules through the resource-capped queue and single local DuckDB, then
  separates paper-state mutation, generated evidence, read-only API/UI projection, the auxiliary
  postflight receipt, and upstream-conditional Git sync. A documentation contract preserves the
  component and authority boundaries so the diagram cannot silently regress into an aspirational
  or broker-connected design. The cron branch distinguishes the weekday nightly from queued
  research and weekly verification/liquidity maintenance instead of implying that every schedule
  invokes the collectors.
- Reconciled the governing deployment docs with the actual service boundary. The API-to-postflight
  arrow now reflects that the verifier reads `GET /meta`; both design specs and `SECURITY.md` state
  that API/UI ports bind loopback and are accessed through an SSH tunnel, replacing the stale
  “corp intranet” description. A contract prevents that exposure guidance from drifting back.
- Hardened the Friday postflight's strict JSON boundary against pathologically deep but bounded
  responses. Decoder `RecursionError` now follows the same controlled `PostflightError` path as
  malformed JSON and transport failures, so the unattended producer publishes a bounded,
  schema-valid failed receipt instead of terminating without evidence. Regressions exercise both
  the real HTTP/decode boundary and alternate-path atomic publication. Verification passes all
  **1,242 Python tests** with warnings as errors, 24 UI contracts, the production UI build,
  repository Ruff and `server tools` C901, Python/shell compilation, lock and wheel checks, and
  Python/npm vulnerability audits. The protected research fingerprint remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` across 111 files; the Git
  index is empty, and no API/UI deployment is required because cron imports the tool afresh.
- Consolidated excessive-nesting handling in the shared strict JSON loader rather than requiring
  every API monitor and operator tool to understand CPython decoder internals. Deep JSON now
  becomes a stable `ValueError`; API-facing readers fail soft, the postflight still emits its
  bounded failure receipt, and the walk-forward migration auditor reuses the same duplicate-key,
  finite-number, object-shape, and depth policy instead of maintaining a private decoder copy.
  The legacy cohort's finite-number walk is iterative as well, so an already-decoded deep tree
  cannot overflow that validation stage. Focused tests cover the shared string/bytes/file paths,
  metadata projection, postflight publication, and migration audit; the retained 18-artifact
  migration still reports exactly 34 reviewed differences with its intentional exit 1.
  The two forward-report reconcilers retain narrow `RecursionError` guards around serialization
  of live evaluator output, which is outside the shared decoder; regressions prove both return
  `INVALID` rather than an API error for a pathological live tree. Final verification passes all
  **1,250 Python tests** with warnings as errors, 24 UI contracts,
  the production UI build, repository Ruff and `server tools` C901, compilation, lock and wheel
  checks, and the npm production audit. After the API-only deployment, `/meta` is byte-for-byte
  unchanged; API/UI are active and enabled with zero failure restarts, scheduler continuity is
  5/5 plus postflight 1/1, and the ledger remains 475 jobs, 1,064 paper orders, and 1,039 fills
  with no pending/running jobs. The first authoritative receipt remains correctly absent before
  its Saturday slot.
- Removed the last two current-spec remnants of the superseded intranet deployment model. The
  execution-design topology now says that services are loopback-only and accessed through an SSH
  tunnel, and its formerly-open access question now explicitly rejects direct intranet/public
  exposure. The documentation contract rejects both stale phrases going forward.
- Clarified the same execution spec's weekly cadence: Sunday automation performs deterministic
  evidence revalidation only. Portfolio membership or strategy refinement requires a separate,
  explicit human decision and pre-registration; scheduled revalidation cannot mutate either.
- Hardened both persistent user services with the subset verified to work in this host's
  unprivileged systemd 241 manager: `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`,
  protected control-group/kernel-tunable paths, locked personality, disabled realtime scheduling,
  and `UMask=0077`. A real deployment test found that adding `ProtectKernelModules` caused both
  units to fail before exec with status `218/CAPABILITIES`; the original units were restored
  immediately, that directive was isolated with transient probes, and only the supported subset
  was then retained.
- Corrected the API hardening subset after the live scheduler projection exposed a second
  host-specific constraint: the setgid `crontab` helper cannot read this user's spool when the
  kernel no-new-privileges bit is set, making `/meta.scheduler` fail closed as
  `crontab-unreadable`. Isolated transient probes showed that systemd 241 sets that bit for each of
  `NoNewPrivileges`, `ProtectKernelTunables`, `LockPersonality`, and `RestrictRealtime`, while
  `PrivateTmp`, `ProtectSystem=full`, `ProtectControlGroups`, and `UMask=0077` preserve crontab
  access. The API now uses the latter proven subset; the UI retains all supported directives.
  Service contracts and the operating guide document this deliberate asymmetry.
  After deployment, the API process reports kernel `NoNewPrivs: 0` and `/meta.scheduler` is
  `ok` with all 5 production entries and the 1 auxiliary postflight entry matched. API and UI
  remain loopback-only, active with zero restarts, and HTTP 200; the ledger remains 475 jobs,
  1,064 paper orders, and 1,039 fills with no pending/running jobs. The protected 111-file
  fingerprint remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Narrowed the discretionary earnings gate's fail-soft boundary from every Python exception to
  `duckdb.Error`. Missing or unreadable earnings evidence still yields the explicit `unknown`
  safety gate, while programmer defects now surface to tests and request handling instead of being
  silently mislabeled as absent market data.
- Made strict-JSON nesting deterministic across Python builds with a shared 100-container-level
  ceiling. The iterative depth check rejects structures that may decode successfully on a build
  with a generous C-decoder limit but would endanger recursive downstream comparison code; the
  exact boundary and the lower-level decoder-overflow normalization are both tested.
  Final verification after the nesting and earnings-risk boundary changes passes all **1,254
  Python tests** with warnings as errors, 24 UI contracts, the production UI build, repository
  Ruff and `server tools` C901, compilation, lock consistency, and wheel packaging.
- Added the matching 1 MiB bound for filesystem JSON reads in the shared loader. Current consumed
  operational artifacts are far smaller (the largest live walk-forward result is about 48 KiB),
  and exact-limit/one-byte-over tests preserve a deterministic acceptance boundary without
  affecting report schemas.
  The postflight HTTP reader now aliases that shared ceiling rather than duplicating the numeric
  policy, while retaining its existing public constant and error contract.
  Final verification passes all **1,257 Python tests** with warnings as errors, 24 UI contracts,
  the production UI build, repository Ruff and `server tools` C901, compilation, lock and wheel
  checks, and the npm production audit.
- Added a deterministic, read-only release-candidate manifest for the recoverability workstream.
  It binds the Git commit/tree and full tracked-plus-unignored working-tree contents, Python/UI
  dependency locks, the 111-file research runtime, frozen experiment and prospective evidence,
  strategy registrations, execution profiles, schema-defining source, the live DuckDB catalog
  schema, service units, and scheduler source. A second working-tree scan fails closed if files
  change while the manifest is assembled. It reads no application rows or credentials, performs
  no network or host mutation, and cannot certify database backup or restore integrity.
  The current diagnostic is intentionally `non-releasable`: its identity is complete, but the
  working tree is dirty and required deployment files remain untracked. Strict mode exits 1;
  `--allow-dirty` only permits collection of that explicitly non-releasable diagnostic.
- Added an idempotent automation installer with an audit-only default and explicit `--apply`
  boundary. It validates the checkout and all six launch targets, preserves unrelated crontab
  content, migrates exact legacy entries into one marked block, installs byte-identical API/UI
  units, restarts only changed services, and requires the post-install scheduler projection to be
  healthy. Malformed or duplicate managed blocks fail closed, and focused tests exercise both
  no-op and selective-change paths without mutating host state.
  The live apply migrated the six exact existing entries into the marked block without changing
  either service unit or restarting either service. A second audit returned `ok` with no changes;
  `/meta.scheduler` remained 5/5 production plus 1/1 postflight, and unrelated news-scraper
  entries and retired-workflow comments remained installed.
- Added a transactionally consistent local recovery-bundle tool. It refuses repository-internal or
  existing destinations, takes all cooperating driver/queue locks without waiting, attaches the
  writable target before the read-only source for DuckDB 1.5 compatibility, copies through DuckDB,
  and atomically publishes owner-only database, manifest, and prospective-evidence files only after
  verification. The independent verifier checks exact evidence membership and paths as well as
  database bytes, full table counts, catalog identity, queue state, active portfolios, and release
  identity; malformed, absolute, and traversal-style evidence records fail closed. Fifteen focused
  tests, Ruff, and the support-layer complexity gate pass. The release manifest now owns the backup
  source, and operator documentation explicitly leaves encryption, retention, off-machine storage,
  and an independent restore drill unresolved.
  A real local exercise outside the checkout then copied and independently verified the 3.6 GB
  live store in about 75 seconds: 3,655,872,512 bytes, 28 tables, and all three prospective files.
  Snapshot and live ledger counts matched at 475 jobs, 1,064 orders, 1,039 fills, and zero
  pending/running work; the protected 111-file fingerprint was unchanged. The owner-private final
  bundle was published with no temporary directory left behind, while both services retained zero
  restarts and scheduler health remained 5/5 production plus 1/1 postflight. It remains a local,
  unencrypted same-disk artifact and is not represented as completion of off-machine recovery.
  Final verification passes all **1,296 Python tests** with warnings as errors, all 24 UI contract
  tests, the Next.js production build, repository Ruff and `server tools` C901, Python and shell
  compilation, `uv lock --check`, wheel/sdist packaging, the pinned `pip-audit==2.10.1` runtime
  audit, and the npm production audit with zero known vulnerabilities. The retained migration
  audit still exits 1 intentionally for its reviewed economic differences. Release-manifest v3
  remains identity-complete but correctly non-releasable for the dirty tree and untracked required
  files; automation drift audit is `ok`, the Git index is empty, and the protected runtime remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` across 111 files.
- Added a read-only recursive working-tree ownership audit and dated review. The audit expands
  untracked directories, handles NUL-delimited paths and rename origins, identifies staged paths,
  binds the protected runtime fingerprint, marks release-required untracked files, and fails strict
  mode for an unknown owner or nonempty index. The reviewed tree has 288 individual paths: 102
  tracked modifications and 186 untracked files, all assigned to protected research, support/API,
  tests, UI, documentation/configuration, or generated evidence. There are no staged or unknown
  paths, and no untracked empty file or symlink; no discard candidate was found. This closes the
  recoverability audit's inventory/intent decisions, not its commit, upstream, or off-machine
  recovery gates. The 2026-09-06 review's former operational addendum is now explicitly historical
  instead of presenting its superseded `stale-source` observation as live state.
  Release-manifest schema v4 now identifies the worktree reviewer as an audit source separately
  from the database recovery source. Focused audit, release, documentation, and research-evidence
  checks pass, and the strict live audit confirms an empty index, complete ownership, 12 untracked
  release-required files, and the unchanged protected 111-file fingerprint.
- Decomposed two large support-layer projections without touching strategy or simulator source.
  `server.tickets.create` fell from 111 to 52 lines by separating risk/closing-order decisions,
  constrained ID allocation, pending-order insertion, and ticket insertion. Its transaction still
  commits the short-rejection audit before raising the client error and rolls back portfolio,
  order, ticket, and audit writes together on interruption. `server.exposure_monitor.status` fell
  from 107 to 10 lines by separating empty shape, active exposure, exposure-scoped stale-price
  lookup, deterministic ordering, bounded detail shaping, and response assembly; source rows are
  copied instead of mutated. Fifty-seven ticket/risk tests and 37 exposure/meta tests pass.
- Reconciled the current strategy ledger with the 2026-09-11 read-only admission endpoint. All
  schemas are healthy, but no family is ready: stock selection is 40/756 qualifying dates,
  fundamentals 8/156 snapshots, and intraday 46/252 one-minute plus 99/252 five-minute sessions,
  with every required calendar span also immature. This supports unattended data accumulation,
  not another historical search, and changes no strategy, evidence checkpoint, or paper ledger.
  Final verification passes all **1,301 Python tests** with warnings as errors, all 24 UI tests,
  the Next.js production build, repository Ruff, `server tools` C901, compilation, shell syntax,
  and lock consistency. Repeated worktree and release scans are byte-identical; worktree strict
  mode passes, while release-manifest v4 remains identity-complete and correctly non-releasable
  for the dirty tree and 12 untracked required files. The local recovery bundle independently
  re-verifies, automation has no drift, and the index and protected fingerprint remain unchanged.
- Continued support-layer decomposition without altering paper, strategy, or research state.
  `meta_projection.project` fell from 106 to 29 lines by separating host status, nightly evidence,
  walk-forward reconciliation, and prospective monitors while retaining per-monitor fail-closed
  isolation. `queue_monitor.status` fell from 90 to 32 lines by separating sweep context,
  closed-charter classification, bounded streaming failure summaries, and latest-research lookup;
  it still retains at most 100 details per class while counting the complete history, and a broken
  recurring registry still makes every failure actionable. `intraday_readiness.assess` fell from
  103 to 23 lines by separating empty shape, cached NYSE expectations, SQL aggregation, row
  decoding, and maturity evaluation. The dated 2026-09-02 architecture review now has a resolution
  addendum distinguishing its original no-package/no-tests findings from current operating truth.
  Final verification passes all **1,302 Python tests** with warnings as errors, all 24 UI tests,
  the Next.js production build, repository Ruff and `server tools` C901, Python/shell compilation,
  lock consistency, and wheel/sdist packaging. Worktree strict audit and release-manifest v4 remain
  deterministic; the former passes and the latter correctly remains non-releasable. Automation
  drift audit is `ok`, the Git index is empty, and the protected 111-file fingerprint is unchanged.
- Decomposed scheduler evaluation after the broader monitor cleanup. Exact cron parsing, production
  and auxiliary match classification, and service/timezone/launch readiness now have separate
  owners; `evaluate_scheduler` fell from 88 to 33 lines. The behavior remains exact: alternate
  invocations count as duplicates, missing or duplicated entries are misconfigured, unknown host
  probes remain unknown/invalid rather than healthy, non-executable files and directory impostors
  fail launch readiness, and the API continues to distinguish five production entries from the one
  evidence-only postflight. All 71 scheduler/host/meta/service/installer tests pass, and the live
  read-only installer audit still reports `ok` with no unit or crontab drift. Final verification
  passes all **1,302 Python tests** with warnings as errors. After the API-only deployment, the
  complete `/meta` payload is byte-for-byte identical to its pre-restart baseline: scheduler health
  remains 5/5 production plus 1/1 postflight, queue actionable failures remain zero, walk-forward
  evidence remains current, and all prospective/stale-exposure projections are unchanged. API and
  UI remain active and enabled with zero failure restarts and `Linger=yes`; the live ledger remains
  475 jobs, 1,064 paper orders, and 1,039 fills with no pending/running job. Worktree strict audit
  passes, release-manifest v4 remains identity-complete and correctly non-releasable only for the
  dirty tree and 12 untracked required files, the Git index is empty, and the protected 111-file
  fingerprint remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Decomposed the fundamentals and stock-selection research-admission projections without changing
  their thresholds, SQL eligibility rules, or fail-closed schema handling. Each now separates its
  empty shape, aggregate query, normalized coverage, readiness decision, and response assembly;
  `fundamentals_readiness.assess` fell from 63 to 20 lines and `stock_readiness.assess` from 55 to
  16 lines. All 69 focused readiness, documentation, meta, and route tests pass, as do all **1,302
  Python tests** with warnings as errors, repository Ruff and `server tools` C901, compilation,
  lock consistency, and wheel/sdist packaging. After API-only deployment, both the complete
  `/research/readiness` response and complete `/meta` response are byte-for-byte identical to
  their pre-change baselines. No family is admitted: stock selection remains 40/756 qualifying
  dates, fundamentals 8/156 snapshots, and intraday 46/252 one-minute plus 99/252 five-minute
  sessions. Services, automation, ledger counts, worktree audit, release classification, empty
  index, and the protected 111-file fingerprint are unchanged.
- Decomposed the fail-closed E1 prospective monitor without altering its frozen experiment,
  checkpoint, schedule validation, statistical verdict, or exception boundary. Evidence loading
  and validation, verdict mapping, response construction, and fail-closed projection now have
  separate owners; `e1_forward_status.status` fell from 59 to 18 lines. All 36 focused E1/meta/API
  tests and the complete **1,302-test** warnings-as-errors suite pass, together with Ruff,
  `server tools` C901, compilation, lock consistency, and wheel/sdist packaging. The live E1
  projection remains honestly `ACCUMULATING` at 7/40 observations with mean net return
  `-0.0033563692688385488`; after API-only deployment the complete `/meta` response is
  byte-for-byte identical to baseline. Services remain active/enabled with zero failure restarts
  and `Linger=yes`; automation, the 475/1,064/1,039 ledger with no active job, worktree/release
  audits, empty index, and protected fingerprint are unchanged.
- Decomposed discretionary risk-history processing while preserving streaming and exact FIFO
  semantics. Fill retrieval, risk normalization, sale matching, review-marker/window lookup,
  breaker aggregation, and verdict formatting now have separate owners;
  `iter_closed_round_trips` fell from 63 to 15 lines and `circuit_breaker` from 56 to 11 lines.
  Added regressions for unmatched sells followed by partially closed lots and for the established
  rule that missing price history is tolerated only while no closed trip exists. All **1,304
  Python tests** pass with warnings as errors, along with Ruff, `server tools` C901, compilation,
  lock consistency, and wheel/sdist packaging. The direct live risk-history projection and complete
  `/meta` response are byte-for-byte unchanged after API-only deployment; the circuit breaker
  remains `pass` because there are no closed discretionary round trips. Services, automation,
  ledger counts, worktree/release audits, empty index, and protected fingerprint remain unchanged.
- Decomposed the active-position read model without changing its operational-date, active-book,
  valuation, or discretionary-stop semantics. Portfolio validation, row retrieval, base valuation,
  and discretionary risk decoration now have separate owners; `position_read_models.positions`
  fell from 56 to 25 lines. Added direct regressions for a missing portfolio catalog and zero-cost
  percentage handling. All **1,306 Python tests** pass with warnings as errors, along with Ruff,
  `server tools` C901, compilation, lock consistency, and wheel/sdist packaging. The complete live
  `/positions` and `/meta` responses are byte-for-byte unchanged after API-only deployment. API/UI
  remain healthy and persistent, automation has no drift, ledger counts remain 475/1,064/1,039
  with no active job, and worktree/release audits, empty index, and protected fingerprint remain
  unchanged.
- Decomposed the screen read model without changing latest/through-date selection, aggregate
  counts, rank ordering, bounded paging, or response compatibility. Date resolution, header query,
  page query, and payload assembly now have separate owners; `market_read_models.screen` fell from
  55 to 20 lines. All **1,306 Python tests** pass with warnings as errors, together with Ruff,
  `server tools` C901, compilation, lock consistency, and wheel/sdist packaging. After API-only
  deployment, the complete `/screen/latest?page=1` response (3,884 names, 495 passers, 100 displayed)
  and complete `/meta` response are byte-for-byte identical to baseline. API/UI remain healthy and
  persistent, automation has no drift, ledger counts remain 475/1,064/1,039 with no active job,
  and worktree/release audits, empty index, and protected fingerprint remain unchanged.
- Reconciled current-state documentation after adding the four risk/position regression tests:
  the architecture resolution addendum and dated worktree review now report the verified **1,306
  Python tests**, while historical build-log counts remain untouched. All 57 documentation/audit
  contract tests and the complete 1,306-test warnings-as-errors suite pass after this docs-only
  update; no service restart was required. Final strict worktree and release-manifest checks retain
  the same 288-path inventory, 12 required untracked files, empty index, and protected fingerprint.
- Decomposed planned-fold artifact validation without weakening the evidence boundary. Dropped-fold
  shape, complete retained/dropped index partitioning, expected geometry construction, and exact
  geometry validation now have separate owners; `_validate_planned_folds` fell from 67 to 30 lines.
  Validation order and failure messages remain stable, including data-floor drops and retained-fold
  train-start clamping. All 115 focused walk-forward evidence/meta/recovery tests and the complete
  **1,306-test** warnings-as-errors suite pass, along with Ruff, `server tools` C901, compilation,
  lock consistency, and wheel/sdist packaging. After API-only deployment, the complete `/meta`
  payload is byte-for-byte unchanged and walk-forward evidence remains current at 18/18 with one
  cohort signature. Services, automation, ledger counts, worktree/release audits, empty index, and
  protected fingerprint remain unchanged.
- Decomposed release-manifest assembly while preserving deterministic field/reason order and its
  fail-closed double scan of the worktree. Database path resolution, named file-group collection,
  reason-name mapping, and body assembly now have separate owners; `build_manifest` fell from 69
  to 28 lines. All 43 focused release/backup/worktree/documentation tests and the complete **1,306
  Python tests** pass with warnings as errors, together with Ruff, `server tools` C901, compilation,
  lock consistency, and wheel/sdist packaging. Two consecutive post-change manifests are
  byte-for-byte identical. Compared with the pre-change manifest, only the intentionally
  self-referential whole-worktree identity and resulting manifest hash changed; schema,
  classification, reasons, database identity, group membership, and protected runtime are
  unchanged. The live manifest remains identity-complete and correctly non-releasable for the
  dirty tree and 12 untracked required files. No service restart was required.
- Decomposed the unattended Friday postflight CLI without changing its evidence checks or
  publication boundary. Argument construction, evidence fetch/verification, receipt rendering,
  atomic publication, and exit-code handling now have separate owners; `main` fell from 64 to 20
  lines. All 91 focused postflight/status/scheduler/installer/service tests and the complete
  **1,306-test** warnings-as-errors suite pass, together with Ruff, `server tools` C901,
  compilation, lock consistency, and wheel/sdist packaging. The installer remains drift-free and
  cron still schedules the verifier for Saturday 05:15 UTC; no receipt was published early on
  Friday. The complete live `/meta` response remains byte-for-byte unchanged, scheduler health is
  5/5 plus 1/1, and services, ledger counts, worktree/release audits, empty index, and protected
  fingerprint remain unchanged. No service restart was required because cron launches this module
  in a fresh process.
- Decomposed the walk-forward evidence projection without weakening registration, cohort, source,
  or recovery reconciliation. Runtime-source lookup, fail-closed fallback, cohort extraction,
  classification, and payload assembly now have separate owners; `evidence_status` fell from 52
  to 30 lines. All 115 focused walk-forward evidence/meta/recovery tests and the complete **1,306
  Python tests** pass with warnings as errors, together with Ruff, `server tools` C901,
  compilation, lock consistency, and wheel/sdist packaging. After API-only deployment, the
  complete `/meta` payload is byte-for-byte identical to baseline and walk-forward evidence remains
  current at 18/18 with one cohort signature. Services, automation, ledger counts,
  worktree/release audits, empty index, and protected fingerprint remain unchanged.
- Decomposed scheduled-driver log projection without changing newest-run selection, bounded reverse
  reads, malformed-marker handling, or the lock samples that distinguish live work from interrupted
  runs. Reverse marker discovery and file-read orchestration now have separate owners;
  `driver_status` fell from 52 to 33 lines. All 42 focused driver/meta/nightly tests and the complete
  **1,306-test** warnings-as-errors suite pass, together with Ruff, `server tools` C901,
  compilation, lock consistency, and wheel/sdist packaging. After API-only deployment, the
  complete `/meta` response is byte-for-byte identical to baseline, including all five driver
  projections. Services remain active/enabled with zero failure restarts and `Linger=yes`;
  automation, ledger counts, worktree/release audits, empty index, and protected fingerprint remain
  unchanged.
- Decomposed market freshness and independent-price evidence projection without changing session
  semantics or fail-closed status precedence. Freshness payload construction, completed-session
  enumeration, UTC observation normalization, and price-evidence response shaping now have
  separate owners; `freshness` fell from 49 to 38 lines and `price_verification` from 42 to 28.
  All 44 focused market-health/meta/route tests and the complete **1,306-test** warnings-as-errors
  suite pass, together with Ruff, `server tools` C901, compilation, lock consistency, and
  wheel/sdist packaging. After API-only deployment, the complete `/meta` payload is byte-for-byte
  identical to baseline, including freshness and price-verification fields. Services, automation,
  ledger counts, worktree/release audits, empty index, and protected fingerprint remain unchanged.
- Decomposed the operational league and bounded-equity projections without changing their SQL
  ordering, response field order, per-portfolio limits, exact matching counts, stale-book ranking,
  or same-window SPY context. Standings collection/ranking and single/bulk equity retrieval now
  have separate owners; `league`, `equity`, and `equities` fell from 50/43/48 to 17/17/19 lines.
  All 28 focused league/integration/route tests and the complete **1,306-test** warnings-as-errors
  suite pass, together with Ruff, `server tools` C901, compilation, lock consistency, and
  wheel/sdist packaging. After API-only deployment, `/league`, `/league/equities`, and the complete
  `/meta` payload are byte-for-byte identical to baseline. The scoreboard remains explicitly
  operational-only—not profitability evidence. API/UI are active and enabled with zero restarts,
  automation has no drift, ledger counts remain 475/1,064/1,039 with no active job, and the
  worktree/release audits, empty index, and protected fingerprint remain unchanged.
- Decomposed expected-slot driver monitoring without changing the public schedule tuples, failure
  precedence, UTC/grace semantics, first-run boundary, or five-driver response order. Name
  validation, missed-slot detection, overdue shaping, and per-schedule projection now have separate
  owners; `scheduled_driver_status` fell from 46 to 25 lines and `driver_statuses` from 38 to 17.
  All 103 focused driver/log/meta/scheduler/installer/backup/route tests and the complete **1,306-test**
  warnings-as-errors suite pass, together with Ruff, `server tools` C901, compilation, lock
  consistency, and wheel/sdist packaging. After API-only deployment, the complete `/meta` payload
  is byte-for-byte identical to baseline. Scheduler health remains 5/5 plus 1/1; API/UI are active
  and enabled with zero restarts and `Linger=yes`; automation has no drift; ledger counts remain
  475/1,064/1,039 with no active job; and worktree/release audits, empty index, and the protected
  fingerprint remain unchanged. Prospective strategy states remain sector 4/200, E1 7/40, and XS
  0/48, so this operational cleanup adds no profitability evidence.
- Decomposed published walk-forward result validation without weakening registration identity,
  protocol windows, planned/retained/dropped fold geometry, data-floor clamps, terminal-fold
  metrics, or summary reconciliation. Registration checks, required-section extraction,
  protocol/fold alignment, and summary validation now have separate owners; `validate_result` fell
  from 54 to 16 lines. All 136 focused evidence/recovery/meta/documentation tests and the complete
  **1,306-test** warnings-as-errors suite pass, together with Ruff, `server tools` C901,
  compilation, lock consistency, and wheel/sdist packaging. After API-only deployment, the
  complete `/meta` payload is byte-for-byte identical to baseline; walk-forward evidence remains
  current at 18/18 with one cohort signature. Scheduler health remains 5/5 plus 1/1, API/UI are
  active and enabled with zero restarts and `Linger=yes`, automation has no drift, ledger counts
  remain 475/1,064/1,039 with no active job, and worktree/release audits, empty index, and the
  protected fingerprint remain unchanged. Prospective strategy states remain sector 4/200, E1
  7/40, and XS 0/48; no profitability claim follows from this validator cleanup.
- Decomposed discretionary ticket submission without changing normalization-before-schema-init,
  market-date rejection, transactional portfolio/order/ticket/audit writes, risk-gate output, or
  the committed rejection audit for unsupported short exposure. Submission persistence and
  response assembly now have one owner; `tickets.create` fell from 52 to 31 lines. All 78 focused
  ticket/risk/settlement tests and the complete **1,306-test** warnings-as-errors suite pass,
  together with Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist
  packaging. After API-only deployment, OpenAPI, `/tickets/context`, and the complete `/meta`
  payload are byte-for-byte identical to baseline. No live mutation endpoint was called, and
  before/after row counts remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and
  1,792 audit rows. API/UI remain active and enabled with zero restarts and `Linger=yes`;
  automation has no drift; scheduler health is 5/5 plus 1/1; and worktree/release audits, empty
  index, and the protected fingerprint remain unchanged. Strategy evidence remains sector 4/200,
  E1 7/40, and XS 0/48, so no profitability conclusion changed.
- Decomposed discretionary risk-gate evaluation without changing its one-snapshot market/book
  inputs, latest-real-quote anchor, 11-control order, control details, or fail-closed assertion.
  Context collection and ordered gate construction now have separate owners; `evaluate_gates`
  fell from 48 to 12 lines. All 83 focused risk/ticket/regression tests and the complete
  **1,306-test** warnings-as-errors suite pass, together with Ruff, `server tools` C901,
  compilation, lock consistency, and wheel/sdist packaging. After API-only deployment, OpenAPI,
  `/tickets/context`, and the complete `/meta` payload are byte-for-byte identical to baseline.
  No live mutation endpoint was called, and before/after row counts remain 475 jobs, 1,064 orders,
  1,039 fills, 7 discretionary tickets, and 1,792 audit rows. API/UI remain active and enabled
  with zero restarts and `Linger=yes`; automation has no drift; scheduler health is 5/5 plus 1/1;
  and worktree/release audits, empty index, and the protected fingerprint remain unchanged.
  Strategy evidence remains sector 4/200, E1 7/40, and XS 0/48, so no profitability conclusion
  changed.
- Decomposed recurring-sweep evidence projection without changing open-charter lookup, bounded
  newest-job scanning, ranking validation, status precedence, or response field order. Empty-state,
  missing-jobs, and final payload construction now have separate owners; `evidence_status` fell
  from 46 to 21 lines. All 55 focused sweep/queue/meta/documentation tests and the complete
  **1,306-test** warnings-as-errors suite pass, together with Ruff, `server tools` C901,
  compilation, lock consistency, and wheel/sdist packaging. After API-only deployment, the
  complete `/meta` payload is byte-for-byte identical to baseline; recurring-sweep evidence remains
  intentionally `idle` because no charter is open, and no sweep was launched. Scheduler health is
  5/5 plus 1/1; API/UI are active and enabled with zero restarts and `Linger=yes`; automation has
  no drift; ledger counts remain 475/1,064/1,039 with no active job; and worktree/release audits,
  empty index, and the protected fingerprint remain unchanged. Prospective evidence remains sector
  4/200, E1 7/40, and XS 0/48, so no profitability conclusion changed.
- Decomposed nightly evidence reconciliation without changing driver-state precedence, required
  table checks, screen/database/metadata matching, active-equity completeness, generated-report
  validation, or response field order. Prerequisite classification and current-payload assembly
  now have separate owners; `evidence_status` fell from 45 to 23 lines. All 63 focused
  nightly/report/meta/postflight tests and the complete **1,306-test** warnings-as-errors suite
  pass, together with Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist
  packaging. After API-only deployment, the complete `/meta` payload is byte-for-byte identical to
  baseline; nightly evidence remains `current` at 2026-09-10 with 3,884 screened symbols, 495
  passers, 45 new names, and equity for all 21 active portfolios. Scheduler health remains 5/5 plus
  1/1; API/UI are active and enabled with zero restarts and `Linger=yes`; automation has no drift;
  ledger counts remain 475/1,064/1,039 with no active job; and worktree/release audits, empty index,
  and the protected fingerprint remain unchanged. Prospective strategy states remain sector 4/200,
  E1 7/40, and XS 0/48, so no profitability conclusion changed.
- Decomposed scheduled liquidity-evidence reconciliation without changing driver-state precedence,
  canonical evidence validation, point-in-time market-date checks, store-count reconciliation,
  exception handling, or response field order. Driver-state classification and final payload
  assembly now have separate owners; `evidence_status` fell from 43 to 23 lines. All 44 focused
  liquidity/meta/documentation tests and the complete **1,306-test** warnings-as-errors suite pass,
  together with Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist
  packaging. After API-only deployment, the complete `/meta` payload is byte-for-byte identical to
  baseline at SHA-256 `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`;
  liquidity evidence remains truthfully `not-yet-run` before its first scheduled Sunday refresh.
  Scheduler health remains 5/5 plus 1/1; API/UI are active and enabled with zero restarts and
  `Linger=yes`; automation has no drift; ledger counts remain 475/1,064/1,039 with no active job;
  and worktree/release audits, empty index, and the protected fingerprint remain unchanged.
  Prospective strategy states remain sector 4/200, E1 7/40, and XS 0/48, so no profitability
  conclusion changed.
- Decomposed walk-forward registration projection without changing active-book selection,
  exclusion rules, the single bulk price-floor query, per-registration fail-closed handling,
  execution/profile identity, frozen protocol windows, or cohort validation. One registration's
  validation and identity construction now have a dedicated owner;
  `_eligible_walkforward_configs` fell from 45 to 21 lines. All 126 focused walk-forward/meta/docs
  tests and the complete **1,306-test** warnings-as-errors suite pass, together with Ruff,
  `server tools` C901, compilation, lock consistency, and wheel/sdist packaging. After API-only
  deployment, the complete `/meta` payload is byte-for-byte identical to baseline at SHA-256
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`; walk-forward evidence
  remains current at 18/18 artifacts with one cohort signature. Scheduler health remains 5/5 plus
  1/1; API/UI are active and enabled with zero restarts and `Linger=yes`; automation has no drift;
  ledger counts remain 475/1,064/1,039 with no active job; and worktree/release audits, empty index,
  and the protected fingerprint remain unchanged. Prospective strategy states remain sector 4/200,
  E1 7/40, and XS 0/48, so no profitability conclusion changed.
- Decomposed successful walk-forward fold validation without changing validation order, session
  boundary rules, train/validation joins, return-base checks, session/fill reconciliation, monthly
  equity checks, or error propagation. Session parsing and statistic-block reconciliation now have
  separate owners; `_validate_successful_fold` fell from 43 to 15 lines. All 126 focused
  walk-forward/meta/docs tests and the complete **1,306-test** warnings-as-errors suite pass,
  together with Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist
  packaging. After API-only deployment, the complete `/meta` payload is byte-for-byte identical to
  baseline at SHA-256 `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`;
  walk-forward evidence remains current at 18/18 artifacts with one cohort signature. Scheduler
  health remains 5/5 plus 1/1; API/UI are active and enabled with zero restarts and `Linger=yes`;
  automation has no drift; ledger counts remain 475/1,064/1,039 with no active job; and
  worktree/release audits, empty index, and the protected fingerprint remain unchanged. Prospective
  strategy states remain sector 4/200, E1 7/40, and XS 0/48, so no profitability conclusion
  changed.
- Decomposed walk-forward cohort response projection without changing status precedence, cohort
  identity fields, scan diagnostics, sorting/deduplication, or serialized key order. Cohort identity
  and scan-count payloads now have separate owners; `result_payload` fell from 42 to 20 lines. All
  134 focused walk-forward/recovery/meta/docs tests and the complete **1,306-test**
  warnings-as-errors suite pass, together with Ruff, `server tools` C901, compilation, lock
  consistency, and wheel/sdist packaging. After API-only deployment, the complete `/meta` payload
  is byte-for-byte identical to baseline at SHA-256
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`; walk-forward evidence
  remains current at 18/18 artifacts with one cohort signature. Scheduler health remains 5/5 plus
  1/1; API/UI are active and enabled with zero restarts and `Linger=yes`; automation has no drift;
  ledger counts remain 475/1,064/1,039 with no active job; and worktree/release audits, empty index,
  and the protected fingerprint remain unchanged. Prospective strategy states remain sector 4/200,
  E1 7/40, and XS 0/48, so no profitability conclusion changed.
- Decomposed scheduler launch-prerequisite probing without changing host-probe order, exact cron
  matching, daemon classification, fail-closed behavior, or response field order. Executability,
  postflight readability, and log-directory checks now have a dedicated owner; `status` fell from
  42 to 33 lines. All 65 focused scheduler/meta/installer/docs tests and the complete
  **1,306-test** warnings-as-errors suite pass, together with Ruff, `server tools` C901,
  compilation, lock consistency, and wheel/sdist packaging. After API-only deployment, the
  complete `/meta` payload is byte-for-byte identical to baseline at SHA-256
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`. Scheduler health remains
  5/5 production plus 1/1 postflight; API/UI are active and enabled with zero restarts and
  `Linger=yes`; automation has no drift; ledger counts remain 475/1,064/1,039 with no active job;
  and worktree/release audits, empty index, and the protected fingerprint remain unchanged.
  Prospective strategy states remain sector 4/200, E1 7/40, and XS 0/48, so no profitability
  conclusion changed.
- Decomposed scheduled-miner job/evidence reconciliation without changing latest-job selection,
  queue-state precedence, evidence timestamp checks, per-miner accounting, fail-closed handling,
  or response key order. Nonterminal-job projection and completed-job evidence reconciliation now
  have separate owners; `_job_status` fell from 42 to 23 lines. All 44 focused miner/meta/docs
  tests and the complete **1,306-test** warnings-as-errors suite pass, together with Ruff,
  `server tools` C901, compilation, lock consistency, and wheel/sdist packaging. After API-only
  deployment, the complete `/meta` payload is byte-for-byte identical to baseline at SHA-256
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`. Miner evidence remains
  honestly `incomplete`: intraday, signals, and earnings are current, while the latest scheduled
  fundamentals job has no evidence block. Scheduler health remains 5/5 plus 1/1; API/UI are active
  and enabled with zero restarts and `Linger=yes`; automation has no drift; ledger counts remain
  475/1,064/1,039 with no active job; and worktree/release audits, empty index, and the protected
  fingerprint remain unchanged. Prospective strategy states remain sector 4/200, E1 7/40, and XS
  0/48, so no profitability conclusion changed.
- Decomposed discretionary-book state projection without changing active-book selection, fallback
  cash, point-in-time real-bar marks, latest valid stop selection, fixed query count, valuation, or
  response field order. Active-book loading and marked-position assembly now have separate owners;
  `disc_state` fell from 40 to 21 lines. All 64 focused risk/ticket/meta/docs tests and the complete
  **1,306-test** warnings-as-errors suite pass, together with Ruff, `server tools` C901,
  compilation, lock consistency, and wheel/sdist packaging. After API-only deployment, both the
  complete `/meta` payload and `/tickets/context` are byte-for-byte identical to baseline. No
  mutation endpoint was called; ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7
  discretionary tickets, and 1,792 audit rows, with no active job. Scheduler health remains 5/5
  plus 1/1; API/UI are active and enabled with zero restarts and `Linger=yes`; automation has no
  drift; and worktree/release audits, empty index, and the protected fingerprint remain unchanged.
  Prospective strategy states remain sector 4/200, E1 7/40, and XS 0/48, so no profitability
  conclusion changed.
- Decomposed the discretionary position query without changing its CTE text, bind ordering,
  point-in-time real-bar filter, latest submitted/filled stop selection, deterministic position
  order, or fixed query count. Quote and stop CTE construction now have separate owners;
  `_disc_positions` fell from 41 to 17 lines. All 64 focused risk/ticket/meta/docs tests and the
  complete **1,306-test** warnings-as-errors suite pass, together with Ruff, `server tools` C901,
  compilation, lock consistency, and wheel/sdist packaging. After API-only deployment, both the
  complete `/meta` payload and `/tickets/context` are byte-for-byte identical to baseline. No
  mutation endpoint was called; ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7
  discretionary tickets, and 1,792 audit rows, with no active job. Scheduler health remains 5/5
  plus 1/1; API/UI are active and enabled with zero restarts and `Linger=yes`; automation has no
  drift; and worktree/release audits, empty index, and the protected fingerprint remain unchanged.
  Prospective strategy states remain sector 4/200, E1 7/40, and XS 0/48, so no profitability
  conclusion changed.
- Decomposed discretionary earnings-window evaluation without changing the point-in-time snapshot
  query, UTC submission-date anchor, seven-day inclusive horizon, estimate/confirmed labeling, or
  fail-closed database-error boundary. Snapshot lookup now has a dedicated owner;
  `earnings_window` fell from 39 to 31 lines, while programming errors still propagate. All 53
  focused market-risk/ticket/docs tests and the complete **1,306-test** warnings-as-errors suite
  pass, together with Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist
  packaging. After API-only deployment, both the complete `/meta` payload and `/tickets/context`
  are byte-for-byte identical to baseline. No mutation endpoint was called; ledger counts remain
  475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and 1,792 audit rows, with no active
  job. Scheduler health remains 5/5 plus 1/1; API/UI are active and enabled with zero restarts and
  `Linger=yes`; automation has no drift; and worktree/release audits, empty index, and the protected
  fingerprint remain unchanged. Prospective strategy states remain sector 4/200, E1 7/40, and XS
  0/48, so no profitability conclusion changed.
- Decomposed recurring-sweep ranking validation without changing artifact lookup, identity checks,
  exact expected-trial accounting, minute-resolution publication tolerance, status precedence, or
  fail-closed handling. Ranking identity/timestamp parsing and trial accounting now have separate
  owners; `_ranking_status` fell from 43 to 27 lines. All 40 focused sweep/meta/docs tests and the
  complete **1,306-test** warnings-as-errors suite pass, together with Ruff, `server tools` C901,
  compilation, lock consistency, and wheel/sdist packaging. After API-only deployment, the
  complete `/meta` payload is byte-for-byte identical to baseline at SHA-256
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`; recurring-sweep evidence
  remains intentionally `idle` with no open charter, and no sweep was launched. Scheduler health
  remains 5/5 plus 1/1; API/UI are active and enabled with zero restarts and `Linger=yes`;
  automation has no drift; ledger counts remain 475/1,064/1,039 with no active job; and
  worktree/release audits, empty index, and the protected fingerprint remain unchanged. Prospective
  strategy states remain sector 4/200, E1 7/40, and XS 0/48, so no profitability conclusion
  changed.
- Decomposed scheduled-driver run projection without changing start/terminal marker selection,
  strict UTC validation, terminal-state precedence, advisory-lock sampling, stale-run handling, or
  response field order. Start-marker validation and state-specific field selection now have
  separate owners; `_run_status` fell from 41 to 27 lines, and a direct future-start regression
  test now fixes its exact response contract. All 58 focused driver/meta/docs tests and the
  complete **1,307-test** warnings-as-errors suite pass, together with Ruff, `server tools` C901,
  compilation, lock consistency, and wheel/sdist packaging. After API-only deployment, the
  complete `/meta` payload and `/tickets/context` are byte-for-byte identical to baseline at
  SHA-256 `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156` and
  `4dfe58d3c8263482a148cb9a0bb0d26fbcc80365ea37fb84e30a3a93644c34db`; no mutation endpoint was
  called. Scheduler health remains 5/5 plus 1/1; API/UI are active and enabled with zero restarts
  and `Linger=yes`; automation has no drift; ledger counts remain 475 jobs, 1,064 orders, 1,039
  fills, 7 discretionary tickets, and 1,792 audit rows, with no active job. The strict audit remains
  288 changed paths with an empty index and complete ownership; release identity remains complete
  and correctly non-releasable for the dirty tree and 12 required untracked files; and the
  protected 111-file fingerprint remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Prospective strategy
  states remain sector 4/200, E1 7/40, and XS 0/48, so no profitability conclusion changed.
- Decomposed Friday postflight receipt validation without changing fail-closed validation order,
  schedule-slot derivation, observation-window bounds, failed-reason rules, nightly/miner evidence
  requirements, or response projection. Common header validation and success-only evidence
  validation now have separate owners; `_validate_receipt` fell from 38 to 13 lines. All 72
  focused postflight/meta/docs tests and the complete **1,307-test** warnings-as-errors suite pass,
  together with Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist
  packaging. After API-only deployment, the complete `/meta` payload is byte-for-byte identical
  to baseline at SHA-256 `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`;
  Friday postflight remains truthfully `not-yet-run` before its first scheduled observation.
  Scheduler health remains 5/5 plus 1/1; API/UI are active and enabled with zero restarts and
  `Linger=yes`; automation has no drift; ledger counts remain 475/1,064/1,039 with no active job;
  and worktree/release audits, empty index, and the protected fingerprint remain unchanged.
  Prospective strategy states remain sector 4/200, E1 7/40, and XS 0/48, so no profitability
  conclusion changed.
- Decomposed intraday-readiness coverage preparation without changing its observed date-range
  query, cached NYSE schedule derivation, expected-bar table, live coverage query, bind order,
  breadth thresholds, or admission semantics. Expected schedule construction now has a dedicated
  owner; `_coverage_rows` fell from 39 to 27 lines while retaining exactly two database queries.
  All 73 focused readiness/meta/docs tests and the complete **1,307-test** warnings-as-errors suite
  pass, together with Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist
  packaging. After API-only deployment, the complete `/meta` payload is byte-for-byte identical
  to baseline at SHA-256 `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`.
  Scheduler health remains 5/5 plus 1/1; API/UI are active and enabled with zero restarts and
  `Linger=yes`; automation has no drift; ledger counts remain 475/1,064/1,039 with no active job;
  and worktree/release audits, empty index, and the protected fingerprint remain unchanged.
  Prospective strategy states remain sector 4/200, E1 7/40, and XS 0/48, so no profitability
  conclusion changed.
- Decomposed league-row return comparison without changing persisted-capital normalization,
  inception-window selection, shared-window SPY caching, stale-book handling, row field order,
  ranking, or the operational-only evidence warning. Total-return and benchmark comparison now
  have a dedicated owner; `_league_row` fell from 40 to 34 lines. All 47 focused league/read-model/
  route/docs tests and the complete **1,307-test** warnings-as-errors suite pass, together with
  Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist packaging. After
  API-only deployment, both the complete `/meta` payload and `/league` are byte-for-byte identical
  to baseline at SHA-256 `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`
  and `949c156adc9eb585e7cce2d7f28aeef7d97c0026849ef00dae75e1198f548fde`. Scheduler health remains
  5/5 plus 1/1; API/UI are active and enabled with zero restarts and `Linger=yes`; automation has
  no drift; ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and
  1,792 audit rows, with no active job; and worktree/release audits, empty index, and the protected
  fingerprint remain unchanged. Prospective strategy states remain sector 4/200, E1 7/40, and XS
  0/48, so no profitability conclusion changed.
- Decomposed market-freshness projection without changing UTC defaulting, future-date handling,
  completed-NYSE-session semantics, next-session calculation, or response field order. Known-date
  session analysis now has a dedicated owner; `freshness` fell from 38 to 19 lines. All 48 focused
  market-health/meta/docs tests and the complete **1,307-test** warnings-as-errors suite pass,
  together with Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist
  packaging. After API-only deployment, the complete `/meta` payload is byte-for-byte identical
  to baseline at SHA-256 `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`;
  market freshness remains `ok` with no missing completed session. Scheduler health remains 5/5
  plus 1/1; API/UI are active and enabled with zero restarts and `Linger=yes`; automation has no
  drift; ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and
  1,792 audit rows, with no active job; and worktree/release audits, empty index, and the protected
  fingerprint remain unchanged. Prospective strategy states remain sector 4/200, E1 7/40, and XS
  0/48, so no profitability conclusion changed.
- Decomposed operational market-date probing without changing active-liquid universe admission,
  the 90%/1,000-name breadth floor, real-bar predicate, newest-first bounded scan, query order, or
  canonical exhaustive fallback. Required-breadth and per-date real-bar counting now have separate
  owners; `latest_prices_date` fell from 37 to 21 lines. All 48 focused read-model/position/meta/
  docs tests and the complete **1,307-test** warnings-as-errors suite pass, together with Ruff,
  `server tools` C901, compilation, lock consistency, and wheel/sdist packaging. After API-only
  deployment, the complete `/meta` payload is byte-for-byte identical to baseline at SHA-256
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`; the operational market
  date remains 2026-09-10 and freshness remains `ok`. Scheduler health remains 5/5 plus 1/1;
  API/UI are active and enabled with zero restarts and `Linger=yes`; automation has no drift;
  ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and 1,792
  audit rows, with no active job; and worktree/release audits, empty index, and the protected
  fingerprint remain unchanged. Prospective strategy states remain sector 4/200, E1 7/40, and XS
  0/48, so no profitability conclusion changed.
- Decomposed candidate market-data projection without changing ticker normalization, operational-
  date capping, the newest 250-bar window, latest-real-quote selection, point-in-time screen lookup,
  query order, or response field order. Bounded bar history and eligible-screen lookup now have
  separate owners; `candidate` fell from 39 to 22 lines. All 57 focused market/read-model/route/
  meta/docs tests and the complete **1,307-test** warnings-as-errors suite pass, together with
  Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist packaging. After
  API-only deployment, both the complete `/meta` payload and the live AAPL candidate payload are
  byte-for-byte identical to baseline at SHA-256
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156` and
  `a9743d2b666b7201b9e72cab1da42ad139f2ab9c60b8df9536a9bd37181ffd5c`. Scheduler health remains
  5/5 plus 1/1; API/UI are active and enabled with zero restarts and `Linger=yes`; automation has
  no drift; ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and
  1,792 audit rows, with no active job; and worktree/release audits, empty index, and the protected
  fingerprint remain unchanged. Prospective strategy states remain sector 4/200, E1 7/40, and XS
  0/48, so no profitability conclusion changed.
- Decomposed active order projection without changing active-portfolio filtering, optional status
  filtering, ticket enrichment, one-query window counting, descending ID order, bounded output, or
  response field order. Query construction and internal count-field cleanup now have separate
  owners; `orders` fell from 37 to 5 lines. All 42 focused order/read-model/route/docs tests and the
  complete **1,307-test** warnings-as-errors suite pass, together with Ruff, `server tools` C901,
  compilation, lock consistency, and wheel/sdist packaging. After API-only deployment, both the
  complete `/meta` payload and `/orders` are byte-for-byte identical to baseline at SHA-256
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156` and
  `177eb98fe45d444494c2ed8324d3bd8b389f397cd53bddc4a0b151609a59810f`. Scheduler health remains
  5/5 plus 1/1; API/UI are active and enabled with zero restarts and `Linger=yes`; automation has
  no drift; ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and
  1,792 audit rows, with no active job; and worktree/release audits, empty index, and the protected
  fingerprint remain unchanged. Prospective strategy states remain sector 4/200, E1 7/40, and XS
  0/48, so no profitability conclusion changed.
- Decomposed discretionary ticket-context projection without changing inactive-book precedence,
  operational-date admission, missing-book initial-capital fallback, point-in-time equity, finite-
  positive validation, or response field order. Portfolio lookup and the sizing-state decision
  table now have separate owners; `ticket_context` fell from 39 to 14 lines. All 40 focused paper/
  read-model/route/docs tests and the complete **1,307-test** warnings-as-errors suite pass,
  together with Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist
  packaging. After API-only deployment, both the complete `/meta` payload and `/tickets/context`
  are byte-for-byte identical to baseline at SHA-256
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156` and
  `4dfe58d3c8263482a148cb9a0bb0d26fbcc80365ea37fb84e30a3a93644c34db`. Scheduler health remains
  5/5 plus 1/1; API/UI are active and enabled with zero restarts and `Linger=yes`; automation has
  no drift; ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and
  1,792 audit rows, with no active job; and worktree/release audits, empty index, and the protected
  fingerprint remain unchanged. Prospective strategy states remain sector 4/200, E1 7/40, and XS
  0/48, so no profitability conclusion changed.
- Decomposed shared research-input schema validation without changing current-schema isolation,
  required-table iteration order, sorted missing-column diagnostics, accepted decimal typing,
  incompatible-type reporting, or `invalid-schema` precedence over `missing`. Per-table inspection
  now has a dedicated owner; `input_schema_status` fell from 39 to 28 lines. All 73 focused
  readiness/meta/docs tests and the complete **1,307-test** warnings-as-errors suite pass,
  together with Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist
  packaging. After API-only deployment, both the complete `/meta` payload and
  `/research/readiness` are byte-for-byte identical to baseline at SHA-256
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156` and
  `a4beda0c265c18a791ad207e047b1d423658b35086a153d4121d11d5f87a62ab`. Scheduler health remains
  5/5 plus 1/1; API/UI are active and enabled with zero restarts and `Linger=yes`; automation has
  no drift; ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and
  1,792 audit rows, with no active job; and worktree/release audits, empty index, and the protected
  fingerprint remain unchanged. Prospective strategy states remain sector 4/200, E1 7/40, and XS
  0/48, so no profitability conclusion changed.
- Decomposed liquidity evidence parsing and reconciliation without changing strict timestamp/date
  parsing, ticker-outcome disjointness, count/backfill rules, store-count query count, validation
  precedence, expected NYSE date, or response field order. Observation-time normalization,
  liquidity accounting, publication coherence, and market-date coherence now have separate owners;
  `_evidence` fell from 36 to 19 lines and `_evidence_state` from 41 to 7. All 44 focused liquidity/
  meta/docs tests and the complete **1,307-test** warnings-as-errors suite pass, together with
  Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist packaging. After
  API-only deployment, the complete `/meta` payload is byte-for-byte identical to baseline at
  SHA-256 `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`; liquidity evidence
  remains truthfully `not-yet-run`. Scheduler health remains 5/5 plus 1/1; API/UI are active and
  enabled with zero restarts and `Linger=yes`; automation has no drift; ledger counts remain 475
  jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and 1,792 audit rows, with no active
  job; and worktree/release audits, empty index, and the protected fingerprint remain unchanged.
  Prospective strategy states remain sector 4/200, E1 7/40, and XS 0/48, so no profitability
  conclusion changed.
- Decomposed nightly league-markdown validation without changing report-date precedence, standings
  parsing, active-equity membership, duplicate-name rejection, stale-position semantics, query
  order, or fail-closed errors. Expected active names and stale held-position identities now have
  separate query owners; `_validate_league_markdown` fell from 41 to 13 lines. All 42 focused
  nightly-report/monitor/meta/docs tests and the complete **1,307-test** warnings-as-errors suite
  pass, together with Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist
  packaging. After API-only deployment, the complete `/meta` payload is byte-for-byte identical
  to baseline at SHA-256 `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`;
  no generated report was rewritten. Scheduler health remains 5/5 plus 1/1; API/UI are active and
  enabled with zero restarts and `Linger=yes`; automation has no drift; ledger counts remain 475
  jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and 1,792 audit rows, with no active
  job; and worktree/release audits, empty index, and the protected fingerprint remain unchanged.
  Prospective strategy states remain sector 4/200, E1 7/40, and XS 0/48, so no profitability
  conclusion changed.
- Decomposed XS forward-status orchestration without changing file-existence handling, report-
  envelope status allowlist, frozen registration/runtime checks, observation maturity rules, live
  evaluation reconciliation, projection field order, or the fail-closed exception boundary. The
  validated load/reconcile/project pipeline now has a dedicated owner; `status` fell from 37 to 19
  lines. All 64 focused XS/meta/docs tests and the complete **1,307-test** warnings-as-errors suite
  pass, together with Ruff, `server tools` C901, compilation, lock consistency, and wheel/sdist
  packaging. After API-only deployment, the complete `/meta` payload is byte-for-byte identical
  to baseline at SHA-256 `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`;
  XS evidence remains truthfully `WAITING` at 0/48 paired months with no automatic action.
  Scheduler health remains 5/5 plus 1/1; API/UI are active and enabled with zero restarts and
  `Linger=yes`; automation has no drift; ledger counts remain 475 jobs, 1,064 orders, 1,039 fills,
  7 discretionary tickets, and 1,792 audit rows, with no active job; and worktree/release audits,
  empty index, and the protected fingerprint remain unchanged. No strategy search, sweep, broker
  connection, ticket mutation, or live-capital action occurred.
- Decomposed discretionary risk-gate assembly without changing eager evaluation, database-call
  order, the published eleven-control sequence, gate details, contract verification, or allow/deny
  semantics. Ticket-local/market-anchor gates and portfolio/external-context gates now have
  separate owners; `_ordered_gates` fell from 40 to 7 lines. All 78 focused risk/ticket/docs tests
  and the complete **1,307-test** warnings-as-errors suite pass, together with Ruff,
  `server tools` C901, compilation, lock consistency, and wheel/sdist packaging. After API-only
  deployment, both the complete `/meta` payload and `/tickets/context` are byte-for-byte identical
  to baseline at SHA-256 `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`
  and `4dfe58d3c8263482a148cb9a0bb0d26fbcc80365ea37fb84e30a3a93644c34db`. No mutation endpoint was
  called; ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and
  1,792 audit rows, with no active job. Scheduler health remains 5/5 plus 1/1; API/UI are active
  and enabled with zero restarts and `Linger=yes`; automation has no drift; and worktree/release
  audits, empty index, and the protected fingerprint remain unchanged. Prospective strategy states
  remain sector 4/200, E1 7/40, and XS 0/48, so no profitability conclusion changed.
- Decomposed the fail-closed walk-forward migration audit without changing baseline-cohort scope,
  missing/additional artifact handling, deterministic artifact/path order, metadata validation,
  allowed provenance/runtime drift, diagnostics, or CLI status and exit semantics. Per-artifact
  comparison and final result projection now have separate owners; `audit` fell from 47 to 16
  lines. All 25 focused migration-audit tests and the complete **1,307-test** warnings-as-errors
  suite pass, together with 54 documentation-contract tests, repository Ruff and `server tools`
  C901, compilation, lock consistency, and fresh wheel/sdist packaging. The retained 18-artifact
  earnings-selector audit remains byte-for-byte identical to baseline at 6,067 bytes and SHA-256
  `10f6c0945df599866efd94e855bf218c2124dd8b3b65981ab9f7059aeae8f8fc`, including its expected
  changed exit because the reviewed migration contains 34 economic/diagnostic differences. This
  non-runtime tool required no deployment; API/UI remain active and enabled with zero restarts and
  `Linger=yes`, scheduler health remains 5/5 plus 1/1, and automation has no drift. Ledger counts
  remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and 1,792 audit rows, with
  no active job. The strict audit remains 288 changed paths with complete ownership, zero staged
  files, 12 required untracked files, and protected fingerprint
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` across 111 files; the
  release manifest remains truthfully non-releasable only for the dirty tree and required untracked
  files. Prospective evidence remains sector 4/200, E1 7/40 with mean net return
  `-0.0033563692688385488`, and XS 0/48 before its 2026-09-30 signal, so no profitability
  conclusion changed. No strategy search, sweep, broker connection, ticket mutation, or
  live-capital action occurred.
- Extracted sorted per-table row counting from the transactional recovery snapshot without
  changing required-table admission, catalog/query order, identifier quoting, restore invariants,
  returned field order, or fail-closed copy/verification behavior; `database_snapshot` fell from
  39 to 34 lines. All 15 focused backup tests and the complete **1,307-test** warnings-as-errors
  suite pass, together with 54 documentation-contract tests, repository Ruff and `server tools`
  C901, compilation, lock consistency, and fresh wheel/sdist packaging. A read-only snapshot of
  the live 28-table store remains byte-for-byte identical at 1,094 canonical JSON bytes and
  SHA-256 `7b209f340b7b689f5a030b49ab2d89eb147829d6ee07dd8da7344fb21bce0395`, including schema hash,
  sorted row counts, latest price date, job-state counts, and active-portfolio identity. This
  offline recovery tool required no service restart; API/UI remain active and enabled with zero
  restarts and `Linger=yes`, scheduler health remains 5/5 plus 1/1, and automation has no drift.
  The strict audit remains 288 changed paths with complete ownership and an empty index; the
  protected 111-file fingerprint remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. The release manifest
  remains identity-complete and truthfully non-releasable only for the dirty tree and 12 required
  untracked files; its recovery-source hash changed as expected because this tool is explicitly
  part of that identity. No strategy evidence, paper ledger, broker state, or live capital was
  changed.
- Decomposed the recursive worktree inventory without changing porcelain parsing, Git invocation
  order, ownership/status counting, path order, gate semantics, protected-source hashing, JSON
  field order, or strict exit behavior. Deterministic change grouping and summary projection now
  have separate owners; `build_audit` fell from 47 to 30 lines. All 3 focused audit tests and the
  complete **1,307-test** warnings-as-errors suite pass, together with repository Ruff and
  `server tools` C901, compilation, lock consistency, and fresh wheel/sdist packaging. The complete
  strict report is byte-for-byte identical to baseline at 77,758 pretty-printed bytes (canonical
  55,703 bytes, SHA-256 `d6df9a227c649d214446664c2a25ad1c69975d3d2760481f4a0c6c77bc7d365c`), retaining exactly
  288 changed paths, 102 tracked modifications, 186 untracked files, zero staged or unknown-owner
  paths, and 12 required untracked files. The protected research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` across 111 files. This
  offline audit tool required no runtime deployment and changed no strategy evidence, paper
  ledger, broker state, or live capital.
- Decomposed release database-schema identity without changing repository/external location
  handling, read-only DuckDB access, catalog query order, stable DDL fields, connection cleanup,
  missing/unreadable fail-closed reasons, projection field order, or row-independent hashing.
  Catalog reads and failure projection now have separate owners; `_database_schema` fell from 55
  to 25 lines. All 11 focused release-manifest tests and the complete **1,307-test** warnings-as-
  errors suite pass, together with repository Ruff and `server tools` C901, compilation, lock
  consistency, and fresh wheel/sdist packaging. The live 28-table/0-view/3-index schema projection
  remains byte-for-byte identical at 224 canonical JSON bytes and SHA-256
  `fef89df5034978e1d70f33cd33bf5320e2e069b6020a5d56c2e5adf0ed267e79`, retaining schema hash
  `da107569daef105ff7ccd712fbad08d817fef7ae3808c0b90ea7e97778846265`. The current production
  maintainability scan now finds no function of 36 lines or longer in either `server/` or `tools/`.
  This offline identity tool required no runtime deployment and changed no research source,
  strategy evidence, paper ledger, broker state, or live capital.
- Split the dashboard's 302-line request-and-render body into four server-rendered section owners:
  operational league summary, prospective strategy evidence, research data readiness, and the
  paginated screen table. `ui/app/page.js` now owns only bounded page parsing, parallel request
  fan-out, endpoint-contract admission, and section composition, falling from 336 to 67 lines.
  The existing fail-visible response boundaries, page cap, stale-book exclusion, non-promotional
  evidence wording, monitor-owned thresholds, screen pagination, and reference-notional display
  are unchanged. Source-contract tests now follow each responsibility to its new owner, and a new
  documentation contract pins that ownership map in both UI and operating guides. All 24 Node UI
  contracts, 72 focused Python source/documentation contracts, and the complete **1,308-test**
  warnings-as-errors Python suite pass, together with the production Next.js build, repository
  Ruff and `server tools` C901, compilation, lock consistency, and fresh wheel/sdist packaging.
  After UI-only deployment, the complete visible homepage DOM remains identical at 3,652 ordered
  element/text events and SHA-256
  `696773a621663555c3bd7605ea1f32eea1f83768c4f8d49c0d13db54ba923981`; only React's internal
  server-component serialization changed. `/meta` and `/research/readiness` remain byte-for-byte
  identical at SHA-256 `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`
  and `a4beda0c265c18a791ad207e047b1d423658b35086a153d4121d11d5f87a62ab`. API/UI remain active and
  enabled with zero restarts and `Linger=yes`; automation has no drift; ledger counts remain 475
  jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and 1,792 audit rows, with no active
  job. The strict inventory is now 292 fully owned paths, 102 tracked modifications, 190 untracked
  files, zero staged paths, and the same 12 required untracked files; protected fingerprint
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` remains unchanged across
  111 files. Prospective evidence remains sector 4/200, E1 7/40 with mean net return
  `-0.0033563692688385488`, and XS 0/48 before its 2026-09-30 signal, so no profitability
  conclusion changed. No strategy search, sweep, broker connection, ticket mutation, or
  live-capital action occurred.
- Split the 230-line persistent header into a 21-line fetch/navigation shell, a 9-line validated-
  result coordinator, and ordered operational/research status sections. The `/meta` request remains
  request-memoized in `Header.js`; alert classification and labels remain delegated to
  `header-status.js`; the MOCK banner, status order, missing-data fallbacks, and fail-visible CSS
  classes are unchanged. Source contracts now follow the status rendering to its new owners, and
  documentation names the boundary. Focused service/documentation tests, all 24 Node UI contracts,
  and the production Next.js build pass. After UI-only deployment, the complete homepage visible
  DOM remains identical to its post-dashboard-split baseline at 3,652 ordered element/text events
  and SHA-256 `696773a621663555c3bd7605ea1f32eea1f83768c4f8d49c0d13db54ba923981`; only React's internal
  server-component serialization changed. No API or paper state was mutated.
- Split presentation out of the 232-line discretionary `TicketForm`: trade/sizing inputs,
  journal/override inputs, and validated outcome display now have separate component owners, while
  the 137-line parent retains every hook, server-derived sizing-context decision, automatic
  quantity update, exact POST body, `/tickets` call, response validation, and success/error state.
  New source contracts explicitly forbid API calls or response-validation claims in the three
  presentation children. Focused service/documentation tests, all 24 Node UI contracts, and the
  production Next.js build pass. After UI-only deployment, the AAPL candidate page remains
  identical at 980 ordered visible DOM events and SHA-256
  `4e82b46db4c5939836a5ddc5ffa14643f2efbc110964bf90d2cdb5863194f0be`; no ticket endpoint was
  called. Across both UI cleanups, the complete **1,308-test** warnings-as-errors Python suite,
  repository Ruff and `server tools` C901, compilation, lock consistency, and fresh wheel/sdist
  packaging pass. API/UI remain active and enabled with zero restarts and `Linger=yes`; `/meta`
  and `/research/readiness` remain byte-for-byte identical; automation has no drift; ledger counts
  remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and 1,792 audit rows, with
  no active job. Prospective states remain sector 4/200, E1 7/40 at mean net return
  `-0.0033563692688385488`, and XS 0/48. No strategy search, broker connection, or live-capital
  action occurred.
- Split the Positions & Orders page into two server-rendered presentation owners while retaining
  query parsing, all three parallel API reads, filter-bound response validation, and option
  derivation in `ui/app/positions/page.js`. The page function fell from 209 to 54 lines;
  `PositionsOpenPositions.js` owns the open-position filter/table and fail-visible notices, while
  `PositionsOrders.js` owns bounded-history disclosure, the status filter/table, and delegation to
  the existing cancellation client. Source contracts now require both children to remain free of
  API calls and response admission, and the UI/operating guides document that ownership boundary.
  All 1,308 warnings-as-errors Python tests, 36 focused documentation/source tests, 24 Node UI
  contracts, the production Next.js build, repository Ruff and `server tools` C901, compilation,
  lock consistency, zero-vulnerability production dependency audit, and fresh wheel/sdist builds
  pass. After UI-only deployment, the complete `/positions` visible DOM remains identical at
  30,574 ordered element/text events and SHA-256
  `cbf26efa010f93f4abeb5f4652024b1ba4966496d7bbfdbe4594f6374b56699e`; only React's internal
  server-component serialization may differ. API/UI remain active and enabled with zero restarts
  and `Linger=yes`; automation has no drift; `/meta` and `/research/readiness` remain byte-for-byte
  identical. Ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets,
  and 1,792 audit rows, with no queued or running job. Prospective evidence remains sector 4/200,
  E1 7/40 at mean net return `-0.0033563692688385488`, XS 0/48 before its 2026-09-30 signal, miner
  evidence 3/4, and recurring sweeps idle with no open charter. No strategy search, broker
  connection, cancellation, ticket mutation, or live-capital action occurred.
- Split the Journal's 209-line render body into four ordered server-rendered section owners while
  retaining the `/journal` read, projection validation, and top-level fail-visible boundary in
  `ui/app/journal/page.js`. The page function fell to 24 lines: `JournalCircuitBreaker.js`
  delegates the existing validated review mutation, `JournalTickets.js` owns gate/fill detail,
  `JournalRoundTrips.js` owns realized-R history, and `JournalLeagueEvents.js` owns the bounded
  active-book feed. Source contracts require all four sections to remain free of API fetching and
  response admission, and the UI/operating guides now document this ownership map. All 1,308
  warnings-as-errors Python tests, 54 focused documentation/source tests, 24 Node UI contracts,
  the production Next.js build, repository Ruff and `server tools` C901, compilation, lock
  consistency, zero-vulnerability production dependency audit, and fresh wheel/sdist builds pass.
  After UI-only deployment, the complete `/journal` visible DOM remains identical at 3,602 ordered
  element/text events and SHA-256
  `d69b2425c7f2230c4c539daf9a53718d470007a1a31fcbf64f8a67e89450d46d`; only React's internal
  server-component serialization may differ. API/UI remain active and enabled with zero restarts
  and `Linger=yes`; automation has no drift; `/meta` and `/research/readiness` remain byte-for-byte
  identical. Ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets,
  and 1,792 audit rows, with no queued or running job. Prospective evidence remains sector 4/200,
  E1 7/40 at mean net return `-0.0033563692688385488`, XS 0/48 before its 2026-09-30 signal, miner
  evidence 3/4, and recurring sweeps idle with no open charter. No strategy search, broker
  connection, review mutation, ticket mutation, or live-capital action occurred.
- Split the League page's operational presentation into `LeagueOverview.js` and
  `LeagueStandings.js` while retaining both parallel API reads, league admission, bulk-equity
  validation against the admitted rows/as-of date, and the top-level failure/empty boundary in
  `ui/app/league/page.js`. The page function fell from 164 to 58 lines. The overview owns curve
  failure/truncation notices, stale-book exclusion disclosure, and operating context; standings
  owns display-series derivation, operational metrics, stale/dormant labels, and sparkline
  fallback. Source contracts now enforce that neither child fetches or admits API responses, and
  the UI/operating guides document the ownership map. All 1,308 warnings-as-errors Python tests,
  54 focused documentation/source tests, 24 Node UI contracts, the production Next.js build,
  repository Ruff and `server tools` C901, compilation, lock consistency, zero-vulnerability
  production dependency audit, and fresh wheel/sdist builds pass. After UI-only deployment, the
  complete `/league` visible DOM remains identical at 1,112 ordered element/text events and
  SHA-256 `2bb5a9be9d0c90fdc773ee70e448d696de451b3a286dd16d756ced3aac183f37`; only React's internal
  server-component serialization may differ. API/UI remain active and enabled with zero restarts
  and `Linger=yes`; automation has no drift; `/meta` and `/research/readiness` remain byte-for-byte
  identical. Ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets,
  and 1,792 audit rows, with no queued or running job. Prospective evidence remains sector 4/200,
  E1 7/40 at mean net return `-0.0033563692688385488`, XS 0/48 before its 2026-09-30 signal, miner
  evidence 3/4, and recurring sweeps idle with no open charter. No strategy search, broker
  connection, mutation, or live-capital action occurred.
- Split the Candidate page's summary, template checks, and ticket-panel composition into
  `CandidateSummary.js`, `CandidateTemplateChecks.js`, and `CandidateTicketPanel.js`, while
  retaining route-parameter normalization, both parallel reads, ticker-bound candidate admission,
  sizing-context admission, and candidate 404 handling in `ui/app/candidates/[ticker]/page.js`.
  The route function fell from 111 to 50 lines. Presentation children cannot fetch or validate
  endpoints; the ticket panel delegates all interactive sizing and mutation behavior to the
  existing validated `TicketForm.js` client. Source/documentation contracts and both UI guides now
  pin this ownership boundary. All 1,308 warnings-as-errors Python tests, 54 focused
  documentation/source tests, 24 Node UI contracts, the production Next.js build, repository Ruff
  and `server tools` C901, compilation, lock consistency, zero-vulnerability production dependency
  audit, and fresh wheel/sdist builds pass. After UI-only deployment, the complete AAPL candidate
  visible DOM remains identical at 953 ordered element/text events and SHA-256
  `392d9af502059ef798f933f2f05793a3447a15798071669e2e86057bc7ba4c57`; no ticket endpoint was
  called. API/UI remain active and enabled with zero restarts and `Linger=yes`; automation has no
  drift; `/meta` and `/research/readiness` remain byte-for-byte identical. Ledger counts remain
  475 jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and 1,792 audit rows, with no queued
  or running job. Prospective evidence remains sector 4/200, E1 7/40 at mean net return
  `-0.0033563692688385488`, XS 0/48 before its 2026-09-30 signal, miner evidence 3/4, and recurring
  sweeps idle with no open charter. No strategy search, broker connection, mutation, or
  live-capital action occurred.
- Replaced the 657-line UI `/meta` contract monolith with a 19-line public composition facade and
  focused pure validators for core snapshot fields, queue/driver state, scheduler/postflight/source
  control, aggregate evidence, bounded stale exposure, and prospective forward studies. Shared
  optional/nullable/timestamp predicates live in `meta-contract-utils.js`; callers still import
  only `isMetaProjection` from `meta-contracts.js`. No domain module exceeds 173 lines, and source
  contracts now pin the one-way dependency boundary while the existing exhaustive mutation suite
  preserves every covered acceptance/rejection rule. Both UI/operating guides document the module
  map. All 1,308 warnings-as-errors Python tests, 54 focused documentation/source tests, 24 Node UI
  contracts, the production Next.js build, repository Ruff and `server tools` C901, compilation,
  lock consistency, zero-vulnerability production dependency audit, and fresh wheel/sdist builds
  pass. After UI-only deployment, the complete homepage and persistent-header visible DOM remains
  identical at 3,633 ordered element/text events and SHA-256
  `da99f53e57a968a773109ae58c32584bcb20bd18bf79a0d8d4e3080e47da8292`. API/UI remain active and
  enabled with zero restarts and `Linger=yes`; automation has no drift; `/meta` and
  `/research/readiness` remain byte-for-byte identical. Ledger counts remain 475 jobs, 1,064
  orders, 1,039 fills, 7 discretionary tickets, and 1,792 audit rows, with no queued or running
  job. Prospective evidence remains sector 4/200, E1 7/40 at mean net return
  `-0.0033563692688385488`, XS 0/48 before its 2026-09-30 signal, miner evidence 3/4, and recurring
  sweeps idle with no open charter. No strategy search, broker connection, mutation, or
  live-capital action occurred.
- Replaced the operational response-contract monolith with a five-line stable public facade and
  three pure domain owners: `positions-contracts.js` validates filter identity, valuation fields,
  and row coherence; `orders-contracts.js` validates bounded status-filtered history and unique
  order rows; and `journal-contracts.js` validates tickets, gates, linked fills, round trips, and
  league events. Existing page imports remain unchanged. Source contracts now pin each rule to its
  domain owner and require all three modules to remain free of fetching and response-admission
  logic; the UI and operating guides document the ownership map. All 1,308 warnings-as-errors
  Python tests, 33 focused documentation/source tests, 24 Node UI contracts, the production Next.js
  build, repository Ruff and `server tools` C901, compilation, lock consistency, zero-vulnerability
  production dependency audit, and fresh wheel/sdist builds pass. After UI-only deployment, the
  saved pre-change and deployed `/positions` and `/journal` ordered non-script DOM event streams
  match exactly; raw response sizes also remain 865,471 and 124,591 bytes. API payload hashes remain
  unchanged at `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156` for
  `/meta` and `a4beda0c265c18a791ad207e047b1d423658b35086a153d4121d11d5f87a62ab` for
  `/research/readiness`. API/UI are active and enabled with zero restarts and `Linger=yes`;
  automation has no drift. Ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7
  discretionary tickets, and 1,792 audit rows, with no queued or running job. The strict inventory
  contains 319 fully owned changed paths, zero staged or unknown paths, and the same 12 required
  untracked files; the protected 111-file fingerprint remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Release identity is
  complete and remains non-releasable only for `dirty-working-tree` and
  `required-files-untracked`. Prospective evidence remains sector 4/200, E1 7/40 at mean net
  return `-0.0033563692688385488`, XS 0/48 before its 2026-09-30 signal, miner evidence 3/4, and
  recurring sweeps idle with no open charter. No strategy search, broker connection, mutation, or
  live-capital action occurred.
- Extracted reusable research input-schema, dated-coverage, and intraday-coverage validation from
  the 238-line `research-contracts.js` into the pure 152-line
  `research-coverage-contracts.js`. The public aggregate contract and dashboard import remain
  unchanged, while `research-contracts.js` is now a 94-line owner of response identity, derived
  family statuses, and the exact ready-family set. Source contracts pin the one-way dependency and
  no-fetch boundary, and both UI guides document the ownership split. All 1,308
  warnings-as-errors Python tests, 33 focused documentation/source tests, 24 Node UI contracts,
  the production Next.js build, repository Ruff and `server tools` C901, compilation, lock
  consistency, zero-vulnerability production dependency audit, and fresh wheel/sdist builds pass.
  After UI-only deployment, the saved pre-change and deployed homepage contain identical ordered
  non-script DOM event streams (3,757 events), and both raw responses remain 123,333 bytes. API
  payload hashes remain unchanged at
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156` for `/meta` and
  `a4beda0c265c18a791ad207e047b1d423658b35086a153d4121d11d5f87a62ab` for
  `/research/readiness`. API/UI are active and enabled with zero restarts and `Linger=yes`;
  automation has no drift. Ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7
  discretionary tickets, and 1,792 audit rows, with no queued or running job. The strict inventory
  contains 320 fully owned changed paths, zero staged or unknown paths, and the same 12 required
  untracked files; the protected 111-file fingerprint remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Prospective evidence
  remains sector 4/200, E1 7/40 at mean net return `-0.0033563692688385488`, XS 0/48 before its
  2026-09-30 signal, miner evidence 3/4, and recurring sweeps idle with no open charter. No strategy
  search, broker connection, mutation, or live-capital action occurred.
- Replaced the 485-line mixed-responsibility walk-forward artifact validator with a 56-line stable
  facade and focused owners for registration/cohort identity, planned/data-floor fold geometry,
  and terminal-fold statistics/summary coherence. `walkforward_cohort.py` still calls only
  `walkforward_artifacts.validate_result()` and `.signature()`, and validation retains the same
  identity → section shape → protocol geometry → planned folds → terminal statistics → summary
  order and error messages. The operating guide and architecture contracts pin that public
  boundary. The live documentation inventory was also reconciled to the authoritative audit and
  current suite count. All 1,309 warnings-as-errors Python tests, 157 focused walk-forward/docs
  tests, 24 Node UI contracts, the production Next.js build, repository Ruff and `server tools`
  C901, compilation, lock consistency, zero-vulnerability production dependency audit, and fresh
  wheel/sdist builds pass. After API-only deployment, `/meta` and `/research/readiness` remain
  byte-for-byte identical at SHA-256
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156` and
  `a4beda0c265c18a791ad207e047b1d423658b35086a153d4121d11d5f87a62ab`. API/UI are active and
  enabled with zero restarts and `Linger=yes`; automation has no drift. Ledger counts remain 475
  jobs, 1,064 orders, 1,039 fills, 7 discretionary tickets, and 1,792 audit rows, with no queued or
  running job. Prospective evidence remains sector 4/200, E1 7/40 at mean net return
  `-0.0033563692688385488`, XS 0/48 before its 2026-09-30 signal, miner evidence 3/4, and recurring
  sweeps idle with no open charter. No strategy search, broker connection, mutation, or
  live-capital action occurred.
- Extracted bounded single-book and bulk equity-history queries from `league_read_models.py` into
  the 148-line `league_equity_read_models.py`, while retaining `league_read_models.equity()`,
  `.equities()`, and `EQUITY_SERIES_LIMIT` as the stable public surface. Operational-date
  resolution stays in the facade, preserving existing test injection and the shared date boundary;
  standings streaming/ranking remains with its own owner. The original module fell from 325 to 211
  lines. A source contract prevents FastAPI routes from bypassing the facade, and the operating
  guide documents both owners. All 1,310 warnings-as-errors Python tests, 45 focused
  league/route/docs tests, 24 Node UI contracts, the production Next.js build, repository Ruff and
  `server tools` C901, compilation, lock consistency, zero-vulnerability production dependency
  audit, and fresh wheel/sdist builds pass. After API-only deployment, `/league`,
  `/league/equities`, and `/league/sector_momentum/equity` remain byte-for-byte identical at
  SHA-256 `949c156adc9eb585e7cce2d7f28aeef7d97c0026849ef00dae75e1198f548fde`,
  `72ad017de9439990a6bc5e7bb5b08610dc17d186b939dcf4f21bdbb37970212d`, and
  `9bfa40f4d4acdcded52e9701677da37dbd8c13e5033c0daca888c7132b13fabf`.
  `/meta` and `/research/readiness` also retain their prior hashes. API/UI are active and enabled
  with zero restarts and `Linger=yes`; automation has no drift. Ledger counts remain 475 jobs,
  1,064 orders, 1,039 fills, 7 discretionary tickets, and 1,792 audit rows, with no queued or
  running job. The strict inventory contains 324 fully owned changed paths, zero staged or unknown
  paths, and the same 12 required untracked files; the protected 111-file fingerprint remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Prospective evidence
  remains sector 4/200, E1 7/40 at mean net return `-0.0033563692688385488`, XS 0/48 before its
  2026-09-30 signal, miner evidence 3/4, and recurring sweeps idle with no open charter. No strategy
  search, broker connection, mutation, or live-capital action occurred.
- Extracted the six deterministic ticket-local controls from `server/risk.py` into the 201-line
  `server/risk_ticket_gates.py`, leaving the 260-line facade responsible for public policy
  constants, database-derived context, portfolio and market controls, and the exact eleven-gate
  order consumed by `tickets.py`. Policy values are passed into the helper on every evaluation,
  preserving runtime monkeypatch behavior. All 1,311 warnings-as-errors Python tests, 90 focused
  risk/book/history/market/regression/ticket/route/docs tests, 24 Node UI contracts, the production
  Next.js build, repository Ruff and `server tools` C901, compilation, lock consistency,
  zero-vulnerability production dependency audit, and fresh wheel/sdist builds pass. After an
  API-only restart, `/tickets/context`, `/meta`, and `/research/readiness` remain byte-for-byte
  identical at SHA-256 `4dfe58d3c8263482a148cb9a0bb0d26fbcc80365ea37fb84e30a3a93644c34db`,
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`, and
  `a4beda0c265c18a791ad207e047b1d423658b35086a153d4121d11d5f87a62ab`. API/UI are active and
  enabled with zero restarts and `Linger=yes`; all six managed cron entries and both installed
  service units match their sources. Ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7
  discretionary tickets, and 1,792 audit rows, with no queued or running job. The strict inventory
  contains 325 fully owned changed paths: 102 tracked modifications and 223 untracked files, zero
  staged or unknown paths, and the same 12 required untracked files. The protected 111-file
  fingerprint remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
  Release identity remains complete but non-releasable only for `dirty-working-tree` and
  `required-files-untracked`. No strategy search, broker connection, mutation, or live-capital
  action occurred.
- Hardened the release manifest's changed-path inventory to consume NUL-delimited porcelain
  records. Legal filenames containing newlines can no longer inflate the count, and staged rename
  or copy records count once while their required origin record is validated. A real Git fixture
  covers a staged rename alongside a newline-bearing untracked path. Focused release, worktree,
  and packaging tests pass; Ruff, tool-layer complexity, compilation, and diff hygiene remain
  green. The live manifest still reports 326 changed paths and remains identity-complete but
  intentionally non-releasable only for `dirty-working-tree` and `required-files-untracked`.
  The protected 111-file research fingerprint remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, the Git index remains
  empty, and no strategy evidence, schedule, service, broker, or capital state changed.
- Hardened recovery-bundle verification so a passing bundle is self-contained rather than a set
  of links to mutable files elsewhere. Creation now refuses dangling destination symlinks before
  path resolution; verification rejects symlinked bundle roots, manifests, databases, and every
  component of a prospective-evidence path. Five filesystem-backed regressions exercise those
  cases alongside the existing tamper, schema, lock, and atomic-publication checks. Verification
  now also requires the exact manifest fields, a UTC creation timestamp, a safe source location,
  coherent release status, valid Git/working-tree/research hashes, and a positive research file
  count; nine malformed-metadata cases fail closed even with a recomputed manifest digest.
  Operator and contributor documentation now state these boundaries explicitly. The change is confined to
  support tooling, tests, and documentation; no live database, prospective checkpoint, service,
  schedule, broker, or capital state was mutated.
- Tightened unattended-service deployment identity: versioned unit sources must be regular files,
  and an installed unit reached through a symlink is now drift even when its bytes currently match
  the source. Two focused tests cover both boundaries. The live read-only installer audit still
  reports `ok`: six managed cron entries and both deployed units are independent regular files
  matching their repository sources. No service restart or host configuration write occurred.
- Made named release-critical inputs self-contained. Dependency locks, registrations, execution
  profiles, evidence checkpoints, schema/recovery/audit/schedule sources, and service units now
  count as incomplete when represented by a symlink, even if the linked external bytes match.
  The full working-tree identity still binds ordinary Git symlinks by path, type, and target.
  A filesystem-backed regression proves an external identical `uv.lock` cannot satisfy release
  identity. Parent path components are checked too; additional regressions reject a release input,
  service-unit source, or prospective checkpoint below a symlinked directory. No current release
  input is a symlink, so live manifest status remains unchanged.
- Closed the same external-source gap for the protected runtime identity. The release layer now
  rejects a symlink anywhere under `engine/`, `farm/`, or `sim/`, or at a root protected source
  file, instead of accepting a research hash derived from bytes outside the checkout. The broader
  tree hash still records the link itself for diagnostics. A regression uses byte-identical
  external Python source and proves release identity fails closed. Recovery remains available in
  degraded mode: explicitly null Git, working-tree, or research hashes are accepted only when the
  embedded release status remains `non-releasable`; release candidates require complete hashes.
- Closed the release-identity bootstrap gap by adding `tools/release_manifest.py` itself to the
  named audit-source group and bumping the manifest schema from 4 to 5. The certification code is
  now a required tracked regular file rather than merely an unnamed member of the whole-tree hash.
  Consequently the strict inventory truthfully reports 13 release-required untracked files instead
  of 12. Current ownership documentation and its contract were updated; historical build-log
  snapshots retain the counts they observed at the time.
- Aligned strict worktree review with the hardened release identity and bumped its output schema
  from 1 to 2. The audit now emits untracked-symlink and empty-untracked-file inventories, fails
  strict mode on an untracked symlink, and rejects an incomplete protected research identity rather
  than reporting a hash sourced through an external link. Empty regular files remain reviewable
  diagnostics because legitimate package markers may be empty. The live tree reports zero in both
  inventories and retains a complete 111-file protected identity.
- Made recovery verification enforce the privacy guarantee already applied during creation. It now
  rejects a group/world-accessible bundle root, manifest, database, or prospective checkpoint and
  wraps missing/unreadable bundle paths in the stable `BackupError` contract. Five focused cases
  cover each sensitive path plus a missing bundle. The existing 3,655,872,512-byte local bundle
  still verifies with 28 tables and three evidence files under the stricter permission checks.
- Final integrated verification after the release/recovery hardening passes 1,358 Python tests with
  warnings as errors, 24 Node UI contracts, the production UI build, fresh wheel and source builds,
  lock/environment consistency, repository Ruff, `server tools` C901, Python compilation, shell
  syntax, and diff/index hygiene. Release manifest schema 5 is identity-complete and intentionally
  non-releasable only for `dirty-working-tree` and `required-files-untracked`; worktree audit schema
  2 reports 326 fully owned paths, 13 required untracked files, no staged/unknown/untracked-symlink/
  empty-untracked paths, and the unchanged protected 111-file fingerprint. Both services remain
  enabled and active with zero restarts, automation is healthy at six managed entries, the ledger
  is unchanged with zero active jobs, and no strategy family is ready for admission.
- Exercised the existing verified local recovery bundle through a temporary isolated API process on
  `127.0.0.1:18000`, with database and data-directory environment overrides pointing only at bundle
  contents. Eight read endpoints (`/health`, `/meta`, `/research/readiness`, `/league`, `/positions`,
  `/orders`, `/journal`, and `/tickets/context`) returned HTTP 200; health named the backup database,
  latest price date was 2026-09-10, and all prospective states remained non-promotional. The process
  was stopped, port 18000 closed, production remained healthy with zero restarts, and ledger counts
  did not change. This is a successful same-host read-only application drill, not an independent
  clean-checkout/UI/service restore and not closure of the external recoverability gate.
- Extended that same-host drill through the already-built production Next.js server on
  `127.0.0.1:13000`, with server-side requests pointed at the backup API on port 18000. Dashboard,
  league, positions, journal, and SPY candidate routes all returned HTTP 200; rendered output
  contained expected forward statuses and no application/fetch/contract-error markers. The browser
  rewrite remains fixed to production port 8000, so no browser mutation was exercised. Both
  temporary processes were terminated, ports 13000/18000 closed, production API/UI remained HTTP
  200 with zero restarts, and ledger counts were unchanged. The clean-checkout, isolated-home
  service-install, and independent-machine portions of the restore gate remain open.
- Closed the UI isolation defect found by that drill. A new pure `ui/api-origin.mjs` validator now
  provides one origin to both server-rendered API calls and Next.js `/api/*` rewrites. It defaults
  to `http://127.0.0.1:8000`, accepts an explicit alternate loopback port, and rejects non-loopback,
  HTTPS, credentialed, path-bearing, query-bearing, fragment-bearing, and portless destinations at
  build/start time. Three new Node contracts pass; an alternate-origin production build succeeds,
  a remote-origin build fails closed, and an isolated UI on port 13000 proved `/api/health`,
  `/api/meta`, and `/` reached the backup API on port 18000. The proxied health response named the
  bundled database, both temporary processes were stopped, and production remained untouched.
- Rebuilt with the normal default origin and restarted only the production UI after that isolated
  proof. The deployed dashboard and `/api/health` both return HTTP 200, the proxy names the live
  database on port 8000, and the service remains active with zero crash restarts. The recursive
  inventory now contains 329 paths (103 tracked modifications and 226 untracked files), including
  66 UI-owned paths; 13 release-required files remain untracked and the Git index remains empty.
- Reconciled the persistent live-readiness handoff with completed Workstream A groundwork. It no
  longer tells a future session to recreate the existing recoverability/worktree audits or local
  backup, release-identity, and automation tooling. It now names the actual open release work:
  reviewable commits, a user-authorized encrypted off-machine destination, and an independent
  restore drill. It also directs future work to preserve the active 111-file research identity,
  let unattended producers accrue new observations, and avoid duplicate searches or reconstructed
  evidence. Documentation contracts pass. A read-only Friday preflight correctly refused to
  certify 2026-09-11 before that night's 22:30 UTC run; the deployed projection remains neutral
  `not-yet-run` until the scheduled 2026-09-12 05:15 UTC postflight. Cron is active and all six
  managed entries remain installed. No receipt was published and no research, ledger, broker, or
  live-capital state changed.
- Added direct route-adapter coverage for valid dated screens, league summary, filtered orders,
  journal, candidate ticker normalization, missing single-book equity, and review-marker
  delegation. Added in-memory ledger tests proving that risk-rejected buys create no order and
  that unknown tickets, rejected tickets, missing linked orders, and non-pending orders cannot be
  cancelled or audited as successful. The tests verify model arguments, route-owned 404 behavior,
  request-scoped connection cleanup, and every distinct cancellation refusal without touching the
  live store. All 1,328 warnings-as-errors Python tests pass, including 24 focused route tests and
  20 focused mutation tests. The repository-wide formatter audit reports 185 legacy
  files that would change, including protected research source; formatting is not a configured CI
  gate and no bulk rewrite was applied because it would invalidate active evidence identity for a
  style-only change. Ruff, `server tools` C901, compilation, package builds, UI contracts, and the
  production UI build remain green. No service restart was required for this tests/docs-only
  addition, and no strategy search, evidence mutation, broker connection, or live-capital action
  occurred.
- Extracted discretionary-book SQL from `server/tickets.py` into the 171-line
  `server/ticket_store.py`, reducing the public mutation facade from 309 to 236 lines. The facade
  remains the sole route-facing owner of request normalization, risk admission, signal dating,
  transaction scope, audit timing, error semantics, and the `create()`, `cancel()`, and
  `mark_review_done()` API; the store performs only subordinate persistence inside those
  caller-owned transactions. A source contract prevents routes from bypassing the facade, and a
  regression preserves the distinction between a missing order and an existing order with a null
  status. All 1,314 warnings-as-errors Python tests, 67 focused ticket/regression/docs tests, 24
  Node UI contracts, the production Next.js build, repository Ruff and `server tools` C901,
  compilation, lock consistency, zero-vulnerability production dependency audit, and fresh
  wheel/sdist builds pass. After an API-only restart, `/tickets/context`, `/meta`, and
  `/research/readiness` remain byte-for-byte identical at SHA-256
  `4dfe58d3c8263482a148cb9a0bb0d26fbcc80365ea37fb84e30a3a93644c34db`,
  `e572f39804caa4edf0a63a932207743af8e6b5d1fb4cfbab743e601b3b2b9156`, and
  `a4beda0c265c18a791ad207e047b1d423658b35086a153d4121d11d5f87a62ab`. API/UI are active and
  enabled with zero restarts and `Linger=yes`; all six managed cron entries and both installed
  service units match their sources. Ledger counts remain 475 jobs, 1,064 orders, 1,039 fills, 7
  discretionary tickets, and 1,792 audit rows, with no queued or running job. The strict inventory
  contains 326 fully owned changed paths: 102 tracked modifications and 224 untracked files, zero
  staged or unknown paths, and the same 12 required untracked files. The protected 111-file
  fingerprint remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
  Release identity remains complete but non-releasable only for `dirty-working-tree` and
  `required-files-untracked`. No strategy search, broker connection, mutation, or live-capital
  action occurred.
- Corrected the current architecture resolution note from 24 to the actual 27 UI contract tests
  while retaining historical BUILDLOG counts, and corrected current packaging guides that had
  described the present untracked `uv.lock` as tracked. Hardened unattended automation validation
  so every cron driver and the Saturday postflight verifier, like service-unit sources, must be a
  regular file reached through non-symlinked checkout paths. The live scheduler projection now
  applies the same source rule. The read-only installer audit also reports each managed unit's
  enabled and active states plus user lingering, treating disabled, stopped, non-lingering, or
  unobservable states as actionable drift;
  `--apply` repairs state-only drift without reinstalling or restarting byte-identical units.
  Regressions cover linked launch sources, linked installed-unit parents, unavailable `systemctl`,
  state-only repair, unavailable host probes, and unhealthy system prerequisites. It also refuses
  a symlinked parent of the installed user-unit directory, preventing `--apply` from writing
  through an unexpected external path. The dry-run now
  also fails closed when the system cron daemon is inactive/disabled, timezone is not UTC, or the
  log directory is unwritable or symlinked outside the checkout, while leaving those privileged
  repairs to the operator. Apply mode now re-plans immediately before mutation, preserving an
  unrelated crontab edit made after an earlier dry-run and refusing a launch source that becomes
  unsafe in the interim. All 1,375 warnings-as-errors Python tests, 27
  Node UI tests, the production UI build, repository Ruff and `server tools` C901, Python and shell
  compilation, frozen-lock/environment checks, Python and npm vulnerability audits, fresh
  wheel/sdist builds, diff hygiene, and empty-index hygiene pass. The installed automation remains
  drift-free at five production schedules plus one evidence-only postflight; both enabled user
  services are active with zero restarts and `Linger=yes`. The verified local recovery bundle still
  passes with its 3,655,872,512-byte database, 28 tables, and three prospective evidence files.
  Release identity is complete and remains non-releasable only for the dirty tree and 13 required
  untracked files. After an API-only restart, `/meta` remained byte-for-byte identical and both
  services retained zero crash restarts. The protected 111-file fingerprint remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. No strategy search,
  evidence mutation, broker connection, or live-capital action occurred.
- Hardened recovery-bundle verification so schema-v1 manifests are structurally validated before
  large file hashing or DuckDB inspection. Database and evidence sizes, catalog counts, row counts,
  job-state counts, and active-portfolio counts must now be non-negative integers (with booleans
  rejected); hashes, the latest-price date, filenames, and exact snapshot fields are validated as
  well. The verifier remains compatible with the first schema-v1 bundle, whose snapshot predates
  `index_count`. Twenty-one malformed-manifest/compatibility cases raise the suite to 1,396 tests.
  All 1,396 warnings-as-errors Python tests, 27 Node UI tests, the production UI build, repository
  Ruff and `server tools` C901, Python and shell compilation, frozen-lock/environment checks,
  Python and npm vulnerability audits, fresh wheel/sdist builds, and diff hygiene pass. The
  existing 3,655,872,512-byte recovery bundle still verifies with unchanged database and manifest
  hashes. The strict worktree audit still reports 329 fully owned changed paths, zero staged files,
  no unknown-owner paths or untracked symlinks, and 13 required untracked files. Release identity
  remains complete and non-releasable only for the dirty tree and required untracked files. Both
  enabled services are active with zero restarts, direct and UI-proxied health reach the live
  database, automation drift remains zero, and the protected 111-file fingerprint remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Hardened the schedule-aware Friday postflight projection before its first eligible run. Receipt
  schema versions now reject booleans, `current` and `failed` receipts each require their exact
  status-specific field set, and symlinked, dangling-symlink, directory, or other non-regular
  receipt paths fail closed as invalid. Seven regressions raise the suite to 1,403 tests; 121
  focused postflight/meta/documentation tests and the full 1,403-test warnings-as-errors suite
  pass, together with 27 Node UI tests, the production UI build, npm audit, repository Ruff,
  `server tools` C901, Python/shell compilation, frozen-lock/environment checks, fresh wheel/sdist
  builds, and diff hygiene. After an API-only restart, the live projection remained correctly
  `not-yet-run` before the first 2026-09-12 05:15 UTC slot; direct and UI-proxied health still
  reached the live database, both enabled services had zero crash restarts, and scheduler health
  remained clean. This changes only observation of the evidence-only receipt and does not run or
  modify any producer, strategy, or portfolio state.
- Made the optional shared `data/_meta.json` loader fail closed on a symlink, dangling symlink,
  directory, or other non-regular path instead of following it and exposing external bytes as
  local producer evidence. A genuinely absent snapshot remains the distinct neutral `missing`
  state, and independent live database/queue/forward projections remain available when the file is
  invalid. Three focused regressions raise the suite to 1,406 tests; 79 focused meta/documentation
  tests and the full 1,406-test warnings-as-errors suite pass, together with 27 Node UI tests, the
  production UI build, repository Ruff, `server tools` C901, Python/shell compilation,
  frozen-lock/environment checks, fresh wheel/sdist builds, and diff hygiene. The deployed
  snapshot is already an owner-only regular file, and after an API-only restart `meta_file`
  remained `ok`, scheduler health remained `ok`, the pre-slot postflight remained `not-yet-run`,
  direct and UI-proxied health reached the live database, and both enabled services retained zero
  crash restarts. This is preventative hardening and does not alter generated evidence.
- Hardened the shared operational JSON loader at the file-descriptor boundary: it opens final
  artifacts without following symlinks, verifies the opened object is a regular file, and uses a
  nonblocking open so a FIFO cannot hang an API request. This protection now covers the shared
  health snapshot, frozen sector/XS/E1 checkpoints, recurring-sweep rankings, postflight receipt,
  recovery manifest, and migration-audit inputs without forbidding an intentionally configured
  alternate parent directory. Five loader regressions raise the suite to 1,411 tests. All 1,411
  warnings-as-errors Python tests, 27 Node UI tests, the production UI build, repository Ruff,
  `server tools` C901, Python/shell compilation, frozen-lock/environment checks, and diff hygiene
  pass, along with fresh wheel/sdist builds. After an API-only restart, all covered live evidence
  projections were byte-for-byte unchanged: sector remained 4/200 and `ACCUMULATING`, XS remained
  0/48 and `WAITING`, E1 remained 7/40 and `ACCUMULATING`, recurring sweeps remained intentionally
  idle, the metadata snapshot remained `ok`, and the postflight remained `not-yet-run`. Direct and
  UI-proxied health still reached the live database, and both enabled services retained zero crash
  restarts.
- Closed the remaining cron redirection gap before the first scheduled Friday/Saturday evidence
  cycle. Scheduler health and the idempotent installer now require every managed production and
  postflight log target to be absent or an existing regular non-symlink file; a symlink, dangling
  symlink, directory, FIFO, or other special target is reported by name and fails closed before a
  shell redirection can redirect or block an unattended job. The API contract and persistent
  dashboard expose the new `unsafe_log_targets` field, and operator documentation records the
  prerequisite. Eight focused regressions raise the suite to 1,419 tests. All 1,419
  warnings-as-errors Python tests, 27 Node UI tests, the production UI build, repository Ruff,
  `server tools` C901, Python and interpreter-correct shell compilation, frozen-lock/environment
  checks, Python and npm vulnerability audits, fresh wheel/sdist builds, and diff hygiene pass.
  The live installer dry-run reports no drift and no unsafe log targets; no producer, sweep,
  strategy, broker, or portfolio state was invoked or changed by this hardening. After an API-only
  restart, the deployed scheduler remained `ok` at 5/5 production plus 1/1 postflight and exposed
  `unsafe_log_targets: []`; every prior `/meta` field was byte-for-byte unchanged. The UI was then
  rebuilt and restarted so its persistent header uses the same contract; its proxy returned the
  exact API payload. Both enabled services retained zero crash restarts, and direct plus UI-proxied
  health reached the live database.
- Hardened scheduled-driver log reads at the descriptor boundary as a defense independent of the
  scheduler prerequisite check. The API now opens each final log path without following symlinks,
  uses nonblocking mode, and verifies the descriptor is a regular file; symlinks (including
  dangling links), directories, FIFOs, and other special paths return `invalid` with
  `log-not-regular`, while a genuinely absent log retains the pre-first-run `null` meaning. Four
  focused regressions cover every unsafe path class, including a FIFO that could previously block
  `/meta` indefinitely. All 1,423 warnings-as-errors Python tests, repository Ruff, `server tools`
  C901, Python/shell compilation, frozen-lock/environment checks, fresh wheel/sdist builds, and
  diff hygiene pass. After an API-only restart, the complete live `/meta` payload was
  byte-for-byte unchanged: all five driver projections remained correct, scheduler health stayed
  `ok`, both enabled services retained zero crash restarts, and direct plus UI-proxied health
  reached the live database. This is read-only monitor hardening and does not alter any generated
  log, schedule, strategy, or evidence artifact.
- Consolidated the repeated descriptor-safe open logic into `server/file_utils.py` and extended it
  to every remaining request-time generated-report reader. Operational JSON, cron logs, nightly
  screen/league Markdown and CSV, and published walk-forward result JSON now share nonblocking,
  no-follow, opened-descriptor regular-file validation. Nightly and walk-forward artifacts also
  have a 1 MiB per-file request ceiling; all current artifacts are below 50 KiB. Sixteen new
  helper and consumer regressions cover exact/oversize limits, symlinks, dangling links,
  directories, FIFOs, and an intentional symlinked parent root, raising the suite to 1,439 tests.
  All 1,439 warnings-as-errors Python tests, repository Ruff, `server tools` C901, Python/shell
  compilation, frozen-lock/environment checks, fresh wheel/sdist builds, and diff hygiene pass.
  After an API-only restart, the full live `/meta` payload was byte-for-byte identical: nightly
  evidence remained `current`, walk-forward evidence remained `current`, scheduler health stayed
  `ok`, both services retained zero crash restarts, and direct plus UI-proxied health reached the
  live database. This refactors only support-layer reads and does not modify report producers,
  strategy code, or evidence files.
- Removed raw exception strings from operational API failure payloads. Driver-log, metadata-file,
  nightly-report, liquidity, and independent-price validation failures now expose only stable
  status/reason fields, while full exception context is retained in the owner-only API journal.
  The browser contract requires an exact status-specific metadata-file reason and rejects any
  reintroduced raw `detail` field. All 1,439 warnings-as-errors Python tests, all 27 UI contract
  tests, the production UI build, repository Ruff, `server tools` C901, Python compilation,
  frozen-lock/environment checks, and diff hygiene pass. After API and UI restarts, the healthy
  `/meta` payload remained byte-for-byte unchanged, the UI proxy matched it exactly, both enabled
  services retained zero crash restarts, and direct plus proxied health reached the live database.
  This changes only failure diagnostics and does not alter healthy projections or research
  evidence.
- Upgraded the transactionally consistent local recovery bundle from schema v1 to schema v2 after
  an isolated restore showed that database and prospective checkpoints alone could not reproduce
  current `/meta` monitoring state. New bundles now preserve exactly seven hashed, owner-private
  operational artifacts under their original relative layout: collector metadata, Friday
  postflight, latest/date-bound screens, and league Markdown/CSV. Verification still accepts the
  retained v1 bundle and reports zero operational artifacts, while v2 rejects missing, extra,
  remapped, symlinked, non-private, or byte-altered artifacts and unmanifested evidence files.
  The focused backup suite, 21 documentation architecture tests, Ruff, and diff hygiene
  pass. A narrow validation-helper extraction keeps the support-layer C901 gate clean without
  changing the format contract. The final integrated run, after the special-node hardening below,
  passes all 1,508 Python tests with
  warnings as errors, all 31 UI tests, the production UI build, repository Ruff, wheel/sdist
  builds, strict ownership/release audits, and empty-index/diff hygiene.
- Created and verified a fresh 3,702,796,288-byte schema-v2 bundle, copied it to a separate restore
  directory, and verified both copies at database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28` and manifest SHA-256
  `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`. A temporary API using only
  the copied database and evidence tree returned healthy read models, retained current nightly and
  Friday-postflight state, honestly retained the verifier's 17 material issues, kept all research
  paper-only with no ready family, and rejected a hostile Host with HTTP 400. Its copied ledger had
  479 jobs, 1,120 orders, 1,039 fills, 21 active portfolios, and zero pending/running jobs. The
  temporary API was stopped. This proves same-host isolated-directory recovery, not encrypted,
  independent-machine, or off-machine disaster recovery; both v2 copies and the original v1 drill
  remain retained outside the checkout.
- Clarified the recoverability audit's opening disposition after the schema-v2 drill: its original
  no-backup finding is now explicitly historical, while the current local same-host proof and the
  still-open source-control, encryption, off-machine, and independent-machine gates are stated
  before the dated detail. A documentation contract prevents those scopes from being conflated
  again. Consolidated prospective and operational manifest-record validation and bundle-file
  verification through shared helpers, preserving their specific fail-closed diagnostics. The
  backup tests, focused recovery/architecture suite, repository Ruff, support C901 gate, and
  real retained schema-v1/v2 bundle verification pass after the cleanup. A read-only automation
  audit also reports no drift: six managed cron entries match, both user services are active and
  enabled with zero restarts, user lingering is enabled, and all launch files remain regular and
  executable where required.
- Tightened the schema-v2 exact-evidence-tree check so an unmanifested FIFO, socket, device, or
  other special node is rejected just like an extra regular file or symlink. A FIFO regression
  test raises the focused backup suite to 70 tests; the operator docs now state this boundary.
- Made schema-v2 verification prove operational coherence, not only file identity. The backup tool
  now calls the same read-only nightly reconciliation used by `/meta`, requiring copied collector
  metadata, screen Markdown, league membership/stale marks, and the complete league CSV to match
  the copied DuckDB snapshot. Backup fixtures now model a coherent miniature nightly cohort; two
  attacks that alter metadata or league equity and then recompute both artifact and manifest hashes
  still fail. Both retained real v2 copies pass the stronger verifier, and the original v1 bundle
  remains compatible without retroactively requiring artifacts it never contained.
- Added the shared `data/_meta.json.lock` to the backup's non-blocking capture window. This covers
  direct/manual metadata producers as well as driver-wrapped runs, preventing `_meta.json` from
  changing between the DuckDB copy and operational reconciliation. A held-lock regression proves
  creation fails before publication and cleans its temporary directory.
- Reconciled the current strategy decision ledger against both live authorities. The deployed
  18-result walk-forward cohort is current and internally complete; sector remains 4/200 and
  `ACCUMULATING`, XS remains 0/48 and `WAITING`, and E1 remains 7/40 and `ACCUMULATING` with a
  currently negative running estimate that cannot be judged before its frozen terminal gate.
  `/research/readiness` has no ready family (stock 40/756, fundamentals 8/156, intraday 46/252 at
  1m and 99/252 at 5m), recurring sweeps are correctly idle, and miner evidence is the expected
  pre-Friday 3/4. The backlog now distinguishes the primary deployable candidate from the shorter
  E1 falsification experiment and explicitly records that no new strategy run is admitted before
  the scheduled 2026-09-11 22:30 UTC producer cycle. A documentation regression pins those
  distinctions and raises the complete warnings-as-errors suite to 1,440 tests; the full suite,
  repository Ruff, `server tools` C901, and diff hygiene pass.
- Closed the remaining request-time diagnostic exposure in the discretionary journal. Malformed
  persisted risk-gate JSON, non-array values, and invalid gate entries now produce only one of
  three stable `gates_error` codes; the API no longer returns the arbitrary source text or Python
  parser exception. Valid gate records are size-bounded and reduced to the admitted `name`,
  `status`, and `detail` fields before serialization, while the UI retains a fixed visible corruption warning and
  rejects any reintroduced legacy diagnostic fields. The ticket query now names its public
  columns explicitly, so a future schema addition cannot become an accidental response field.
  Four focused Python regressions bring the complete warnings-as-errors suite to 1,444 tests; all
  27 Node UI tests, the production UI build, repository Ruff and `server tools` C901, Python/shell
  compilation, frozen-lock/environment checks, Python and npm vulnerability audits, fresh
  wheel/sdist builds, worktree/release audits, and diff/index hygiene pass. After API and UI
  restarts, the healthy seven-ticket `/journal` response and complete `/meta` payload remained
  byte-for-byte unchanged, both UI proxies matched the API, and both enabled services remained
  active with zero crash restarts. This is API/UI hardening only: it does not mutate stored
  tickets, strategy code, portfolio state, or research evidence.
- Removed the remaining source-table wildcard projections from the operational order and market
  read models. `GET /orders`, screen pages, and candidate screen context now select only their
  documented public columns; browser contracts require those exact row keys and reject accidental
  additions. Screen responses continue to expose the stored `universe_policy` provenance, while
  legacy pre-column stores truthfully project the historical `all` default. Added database-schema
  growth, legacy-policy, migrated-policy, and browser-contract regressions. The complete 1,448-test
  warnings-as-errors Python suite, all 27 Node UI tests, production UI build, repository Ruff and
  `server tools` C901, Python/shell compilation, frozen-lock/environment checks, worktree audit,
  protected fingerprint, and diff/index hygiene pass. After API and UI restarts, `/orders`,
  `/screen/latest`, `/candidates/SPY`, `/journal`, and `/meta` remained byte-for-byte unchanged;
  every UI proxy matched its API response, both enabled services retained zero crash restarts, and
  automation reported no drift or unsafe log targets. This changes no source data, strategy
  behavior, or evidence.
- Bounded every discretionary-ticket text field before database initialization, risk evaluation,
  or audit persistence: ticker 32 characters, playbook 128, emotion 32, override reason 512, and
  notes 4,096. The browser mirrors the three free-form journal limits with native `maxLength`
  controls, while server validation remains authoritative for all clients. Boundary tests cover
  every field, exact-limit acceptance, and prove an oversized request leaves orders, tickets, and
  audit rows untouched. OpenAPI advertises the same limits without adding a new direct runtime
  dependency. The complete 1,457-test warnings-as-errors Python suite, all 27 Node UI
  tests, production UI build, repository Ruff and `server tools` C901, Python/shell compilation,
  frozen-lock/environment checks, npm vulnerability audit, worktree audit, protected fingerprint,
  Python dependency audit, fresh wheel/sdist builds, and diff/index hygiene pass. After API and UI
  restarts, OpenAPI remained closed and now advertises the five limits; `/orders`,
  `/screen/latest`, `/candidates/SPY`,
  `/journal`, and `/meta` remained byte-for-byte unchanged; every UI proxy matched; both enabled
  services retained zero crash restarts; and automation remained drift-free with safe log targets.
  This is input hardening only and does not submit a ticket or alter any existing paper or research
  state.
- Removed a package-build race from the Markdown link-integrity test. Documentation discovery is
  now limited to repository-owned root Markdown and the `archive/`, `data/`, `docs/`, and `ui/`
  trees, while generated/cache subtrees are excluded. A regression proves that a transient
  top-level package extraction tree is ignored without dropping any owned documentation surface.
  Twelve consecutive documentation runs passed while a fresh `uv build` created both the sdist
  and wheel, including overlap with the real extraction and `build/` windows. The final focused
  documentation/packaging/worktree/release set passes all 43 tests, and the complete
  warnings-as-errors suite passes all 1,458 tests; repository Ruff, `server tools` C901, fresh
  package builds, diff hygiene, and empty-index hygiene pass. The strict audit reports 331 owned
  changed paths, 103 tracked modifications, 228 untracked files, no unsafe files or symlinks, and
  the unchanged protected 111-file fingerprint
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Release identity remains
  complete and correctly non-releasable only because the working tree is dirty and required files
  remain untracked. Both enabled services remain active with zero crash restarts and `Linger=yes`;
  this test/documentation-only change requires no restart and does not mutate strategy, portfolio,
  or prospective evidence state.
- Closed unbounded identifier inputs at the FastAPI request boundary. Candidate tickers now share
  the discretionary ticket's 32-character ceiling, portfolio path/query identifiers must contain
  1–128 characters, and cancellation IDs must be positive. This also prevents an explicitly empty
  `portfolio=` query from silently becoming an unfiltered positions request. OpenAPI publishes all
  four constraints, and request-level ASGI regressions prove seven invalid forms return 422 before
  either database connection factory can run. All 78 focused route/read-model/documentation tests
  and the complete 1,466-test warnings-as-errors Python suite pass, together with all 27 Node UI tests, the production
  Next.js build, repository Ruff and `server tools` C901, Python compilation, frozen lock/environment
  checks, Python and npm vulnerability audits, and diff/index hygiene. After an API-only restart, all nine sampled valid API
  payloads remained byte-for-byte unchanged; the oversized/empty read requests returned 422, both
  enabled services remained active with zero crash restarts, and `Linger=yes`. This changes only
  input admission and does not submit/cancel a ticket or alter strategy, portfolio, or evidence state.
- Closed the browser-form mutation path on the unauthenticated loopback API. All three paper-state
  POST routes now require an explicit `application/json` content type before opening a write
  connection; missing headers fail validation, and `text/plain`, form-encoded, and multipart media
  types return 415. This forces cross-origin browser requests onto the CORS-preflight path, while
  preserving the existing same-origin UI client and JSON-with-charset compatibility. Request-level
  ASGI regressions cover all three mutations and prove rejected requests cannot invoke the write
  connection. The focused mutation/docs/service suite passes all 106 tests and the complete
  warnings-as-errors Python suite passes all 1,481 tests, together with repository Ruff and
  `server tools` C901, Python/shell compilation, frozen lock/environment checks, and fresh
  wheel/sdist builds. After an API-only restart, all nine sampled valid GET responses remained
  byte-for-byte unchanged; all three live mutation routes rejected form/plain media types with
  415 and missing content types with 422, while order, ticket, audit, and review-marker row counts
  remained unchanged. OpenAPI marks `content-type` required, both enabled services retain zero
  crash restarts, and `Linger=yes`. This is a request-admission safeguard, not authentication, and
  the services must remain bound to loopback.
- Centralized candidate-route admission and link generation in `ui/app/lib/candidate-route.js`.
  Every in-app candidate link now percent-encodes its data-derived ticker, and the candidate page
  safely decodes the incoming segment before enforcing the API's nonblank 32-character boundary.
  Blank and oversized decoded routes return the normal 404, while malformed Unicode values are
  rejected by link/contract code. Thirty Node UI tests and the production Next.js build pass; live
  `SPY`, `BRK.B`, and `BRK%2EB` routes return 200 and a blank encoded ticker returns 404. Direct
  malformed UTF-8 percent sequences remain an explicit framework-boundary limitation: Next.js
  rejects them before page code runs and returns a bare 500. Those requests produced no UI
  application-log event or state change, but this work does not claim that case is fixed. The
  complete 1,481-test warnings-as-errors Python suite, repository Ruff, `server tools` C901, npm
  audit, fresh wheel/sdist builds, and diff/index hygiene pass. No service, strategy, portfolio, or
  evidence state was changed by the final documentation-only correction.
- Closed the DNS-rebinding path to both unauthenticated loopback services. The FastAPI boundary
  now rejects a missing, duplicate, external, suffix-confused, or invalid-port Host header before
  route dispatch or database access. Next's root `proxy.js` applies the same exact `127.0.0.1` /
  `localhost` hostname policy before rendering or forwarding `/api`; valid optional ports preserve
  isolated local development. Focused ASGI tests prove rejected hosts cannot open the database,
  and an isolated production Next server returned 200 for valid page and `/api/health` requests
  while returning 400 for external, suffix-confused, and invalid-port hosts. The complete 1,495-test
  warnings-as-errors Python suite, all 31 Node UI tests, production Next.js build, repository Ruff,
  `server tools` C901, Python/shell compilation, frozen lock/environment checks, npm audit, strict
  worktree audit, and diff/index hygiene pass. The audit now contains 335 owned paths (103 tracked
  modifications and 232 untracked files), no staged/unknown/unsafe paths, and the unchanged
  protected 111-file fingerprint
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
  The installed services were intentionally left unchanged until the scheduled Friday producer
  finished successfully. They were then restarted once; all eight sampled valid API responses
  remained byte-for-byte unchanged, valid UI page and proxied-health requests returned 200, and
  hostile Host headers returned 400 on the API, UI page, and UI proxy. Both enabled services
  remained active with zero crash restarts, and discretionary tickets, audit rows, and review
  markers remained unchanged. This boundary change does not alter strategy or evidence state.
- Observed the scheduled 2026-09-11 Friday producer from its 22:30:01 UTC cron launch through its
  00:52:18 UTC terminal marker without restarting or duplicating it. Price verification compared
  640 bars across all 160 selected names with zero disagreements; queued jobs 476–479 all
  completed, adding 350,995 one-minute and 106,279 five-minute rows, refreshing signals, loading
  2,783 dated earnings rows, and publishing 4,118 fundamentals rows with zero terminal ticker
  failures. `nightly_evidence` is current for 2026-09-11, all 21 active portfolios have equity,
  miner evidence advanced honestly from 3/4 to 4/4, and the queue has no actionable failures.
  Sector momentum advanced from 4 to 5 of 200 required shared sessions and remains
  `ACCUMULATING`; XS remains `WAITING` at 0/48 paired months and E1 remains `ACCUMULATING` at
  7/40. No strategy is admitted, tuned, activated, or claimed profitable from these immature
  observations.
- Reconciled the current working-tree ownership review with the host-policy test that had already
  raised the authoritative UI suite from 30 to 31 tests. Added a documentation-contract assertion
  so that exact current count cannot silently regress. The complete 1,495-test warnings-as-errors
  Python suite, the focused 21-test documentation architecture suite, all 31 Node UI tests, the
  production UI build, repository Ruff and `server tools` C901, Python/shell compilation,
  frozen-lock/environment checks, pinned Python and npm dependency audits, fresh wheel/sdist
  builds, strict worktree audit, diff hygiene, and empty-index hygiene pass. The release manifest
  remains identity-complete and expectedly non-releasable because the tree is dirty and required
  files are untracked. This documentation/test-only correction does not change services, strategy
  behavior, portfolio state, or prospective evidence.
- Observed the scheduled Saturday full-universe verifier from its 02:00:01 UTC cron launch through
  its 05:00:04 terminal marker without restarting or duplicating it. The explicit three-hour cap
  checked 3,968/4,093 names: 3,963 agreed, five produced 49 field disagreements (17 material), 114
  were transparently left unchecked at the time budget, and 11 had source fetch/symbol failures.
  There were no parse failures or store-missing sessions; `/meta` correctly reports
  `price_verification.status = issues`. Read-only triage found no active position or pending order
  in any of the five names and a fresh yfinance pull matched the store. Nasdaq's current VFLO quote
  was $53.88 while its history endpoint returned implausible 83,000–87,000 values; the other four
  cross-source differences were 11–62 bp. Because this does not confirm a primary-store defect, no
  price was rewritten and no quarantine was activated. The separate 05:15 UTC Friday postflight
  then published `current` at 05:15:02, reconciling the 2026-09-11 nightly and miner jobs 476–479.
- Observed the scheduled 06:00 UTC weekend-sweep driver through its 06:00:01 terminal marker. With
  `OPEN_RECURRING_GRIDS` intentionally empty, it reported no open recurring grids and exited
  cleanly without creating a job; the database has zero actionable sweep jobs and no sweep created
  on 2026-09-12, while `/meta.sweep_evidence` remains `idle` for
  `no-open-recurring-charters`. No grid was reopened and no historical path was reused as new
  evidence.
- Closed the remaining local recovery-bundle privacy and release-identity gaps. New bundles now
  create every directory below their `0700` root with an explicit `0700` mode, and verification
  rejects any nested directory that grants group or other access. Regression coverage checks
  generated modes, evidence-directory modes at several depths, and an unexpected non-private
  directory. The two retained schema-v2 source/restore copies first failed the stricter check as
  expected; after changing only their directory modes from `0755` to `0700`, both verified with
  their unchanged database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28` and manifest SHA-256
  `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`. The retained schema-v1
  bundle also remains compatible and verifies with its original hashes.
- Expanded release recovery identity from the entry point alone to the complete 18-file local
  validator/helper closure loaded by `tools.backup_database`; its current hash is
  `272727ffcd400a79779440d934b0896575eb1c22f59097fee52d5504a2c20081`. The strict worktree
  inventory remains 334 fully owned paths (102 tracked modifications and 232 untracked files),
  with an empty index, no unknown or unsafe paths, and 21 release-required untracked files.
  Release identity is complete and expectedly non-releasable only for the dirty tree and those
  untracked required files. The complete 1,516-test warnings-as-errors Python suite, focused
  recovery/release/worktree/docs tests, repository Ruff and `server tools` C901, all three retained
  bundle verifications, diff hygiene, automation drift audit, and live health checks pass. Both
  enabled services remain active with zero crash restarts, all six schedules match, and the ledger
  remains at 7 discretionary tickets, 1,792 audit rows, 0 review markers, 1,120 orders, and 479 jobs
  with none pending/running. The protected 111-file fingerprint remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
  Research readiness still admits no family and remains paper-only with `automatic_action: none`;
  no search, gate change, evidence mutation, broker connection, or live-capital action occurred.
- Extended recovery verification from an exact evidence subtree to an exact whole-bundle
  inventory. A passing schema-v1 or schema-v2 bundle now contains only `market.duckdb`,
  `manifest.json`, manifest-declared evidence files, and the directories required to contain
  them. Root-level or nested unmanifested regular files, empty directories, symlinks, FIFOs,
  sockets, devices, and other special nodes fail closed. A schema-v1 compatibility fixture now
  removes the v2-only empty directories when modeling a real legacy tree instead of weakening the
  invariant. Focused recovery/release/worktree/docs tests, all 1,519 warnings-as-errors Python
  tests, repository Ruff and `server tools` C901, and diff hygiene pass. The retained v1 source,
  v2 source, and v2 restore bundles all pass with their existing database and manifest hashes.
  Recovery identity remains an 18-file closure and is now
  `7f59c4d7932f43f2a08ad1aa751e22f82757ffde5b1cbcd09c53344c1369246c`.
  The strict worktree audit remains at 334 owned paths with an empty index and 21 required
  untracked files; the protected research fingerprint remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
  Both services remain active/enabled with zero crash restarts and all six schedules match.
- Made the recovery release boundary self-auditing. A source-level test now parses the recursive
  local import closure rooted at `tools/backup_database.py`, includes package initializers, and
  requires exact equality with `RECOVERY_SOURCE_FILES`. This prevents a future validator/helper
  import from changing recovery semantics while being accidentally omitted from release identity.
  The current derived and declared sets match at 18 files; the recovery hash remains
  `7f59c4d7932f43f2a08ad1aa751e22f82757ffde5b1cbcd09c53344c1369246c`.
- Closed a publication race in the backup creator. The initial destination-absence check occurred
  before the multi-gigabyte copy, while the final `os.replace` could still replace an empty
  directory created during that window. Publication now uses Linux `renameat2` with
  `RENAME_NOREPLACE`, preserving atomic visibility while refusing every intervening destination.
  A regression inserts an empty destination immediately before publication and proves its inode
  survives untouched and the temporary bundle is removed. All 1,521 warnings-as-errors Python
  tests, repository Ruff and `server tools` C901, diff/index hygiene, and all three retained
  bundle verifications pass. Recovery identity is now
  `365741967dffcd6cc010cbdd56f7d30b36eec2f14d8d7df91d8355032b838837`;
  the protected research identity is unchanged.
- Hardened the backup coordination boundary against redirected or special lock nodes. Backup
  creation now opens every lock with no-follow/nonblocking flags, verifies the opened descriptor
  is a regular file, rejects symlinked parents, and normalizes non-directory-parent failures to a
  bounded `BackupError` before copying. Tests cover a final symlink, directory, FIFO, symlinked
  parent, non-directory parent, and real contention. All eight live lock files open through the
  hardened path. The complete 1,526-test warnings-as-errors Python suite, repository Ruff and
  `server tools` C901, diff/index hygiene, and live API/readiness checks pass. The current 18-file
  recovery identity is
  `da27c1d147f169f102711e6fca6775105c80be17b724bbe80ee6fc30b6bedda4`;
  research remains paper-only with no ready family or automatic action.
- Removed the check/open races from recovery source-artifact capture. Evidence is now opened from
  the resolved repository directory through no-follow directory descriptors for every component,
  read once from the verified regular-file descriptor with the existing 1 MiB operational bound,
  and rejected if the descriptor or pathname identity/size/timestamps change during that read.
  Platforms without `O_NOFOLLOW`/`O_DIRECTORY` fail closed. Tests cover final symlinks,
  directories, FIFOs, oversized input, in-place mutation, pathname replacement, symlinked parent
  directories, and unavailable secure-open flags. This does not change any strategy or evidence.
- Reverified that descriptor-relative source capture against the complete tree and retained
  recovery material. All 1,533 warnings-as-errors Python tests, repository Ruff and `server tools`
  C901, strict worktree/diff/index checks, all three retained v1/v2 bundle verifications, and the
  automation audit pass. API/UI remain active and enabled with zero crash restarts, six schedules
  match, and the live research endpoint remains paper-only with no ready family or automatic
  action. The current 18-file recovery identity is
  `6cc6e2e797917d9499a0739231512cdb88acf16ce599b7b193235f46bef5cbf7`;
  the protected research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Closed the remaining destination-resolution race and added a durability barrier to recovery
  publication. Creation now resolves only the destination parent, rechecks the final leaf after
  parent creation, and relies on atomic no-replace rename, so an intervening leaf symlink cannot
  redirect publication. After successful verification it fsyncs every file and directory in the
  private temporary bundle, publishes it, and fsyncs the destination parent before returning
  success. Tests prove the inserted-symlink case, verify-before-publish ordering, parent sync after
  publication, and cleanup after pre-publication sync failure.
- Reverified the complete durability-enabled tree. All 1,537 warnings-as-errors Python tests,
  repository Ruff and `server tools` C901, strict worktree/diff/index checks, all three retained
  v1/v2 bundles, and the drift-free automation audit pass. A parent-sync failure after publication
  is now explicitly tested to report failure while preserving the already verified bundle for
  inspection rather than deleting recovery data whose directory-entry durability is uncertain.
  The current 18-file recovery identity is
  `aa6b565666f0a6f5d494102d4a446b4c9fdfb0da5adebebb0d6ec4a4297ea06a`;
  the protected research identity remains unchanged and the index remains empty.
- Anchored recovery publication to one no-follow destination-parent descriptor. Private temporary
  creation, atomic no-replace rename, cleanup, and the final durability sync now remain relative to
  that opened directory instead of reopening its pathname after the long database copy. Creation
  carries the verified pre-publication result across the rename without reopening the published
  bundle by pathname and compares the opened and visible parent identities before and after
  publication. Deterministic
  tests rename the parent and install a replacement both before and during publication: the
  replacement receives nothing; pre-publication failure removes the temporary tree from the
  original directory; and post-publication detection reports failure while preserving the verified
  bundle in the displaced original directory. This changes recovery support and documentation
  only; no strategy, research evidence, portfolio, service, schedule, or live-capital state changed.
- Reverified the resulting tree with all 1,539 warnings-as-errors Python tests, 31 UI contract
  tests, the production UI build, repository Ruff and `server tools` C901, Python and shell
  compilation, frozen-lock consistency, wheel/sdist builds, strict Python and production npm
  dependency audits, documentation/release/worktree contracts, diff hygiene, and an empty index.
  All four retained original/restored v1/v2 recovery bundles still verify. Automation remains
  drift-free with six managed entries; API/UI are active and enabled with zero restarts and
  `Linger=yes`. The 18-file recovery identity is
  `fb84df61bf94515fc176f8184d6bae851c76f714142cbc9c335e4ca1644ed7be`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Tightened documentation and interrupted-backup cleanup without touching the protected research
  boundary. The documentation index contract now parses links and requires every owned document,
  design, and charter to be reachable by its exact path rather than accepting filename mentions in
  prose. The contributor guide now states the descriptor-anchored destination-parent behavior.
  Backup creation uses unconditional pre-publication cleanup, including `KeyboardInterrupt` and
  `SystemExit`, while retaining the existing rule that an already published verified bundle is
  preserved. A deterministic interrupt regression proves that no private temporary tree remains.
  All 1,540 warnings-as-errors Python tests, 31 UI contracts, the production UI build and npm
  audit, repository Ruff and `server tools` C901, compilation, frozen-lock validation, strict
  ownership/diff/index checks, automation drift audit, and all four retained bundle verifications
  pass. The current 18-file recovery identity is
  `e861f46f18cc2e77255bcf3648d5405acb6cac35a71519011abe43254b2550c3`;
  the protected research identity remains unchanged.
- Anchored the private temporary bundle itself, closing the remaining pathname reopen inside the
  anchored destination parent. Creation now retains a no-follow directory descriptor for the
  random temporary leaf, writes, verifies, and syncs through that descriptor, and requires the
  parent entry to retain the same inode before no-replace publication. A deterministic regression
  replaces and displaces that leaf after the database copy: the requested destination remains
  absent, neither ambiguous private tree is deleted, and the replacement is never published. A
  second regression proves unavailable Linux descriptor-path traversal fails closed and cleans the
  unchanged temporary entry. The exact resulting tree passes all 1,542 warnings-as-errors Python
  tests, 31 UI contracts, production UI/package/dependency gates, repository lint/complexity/
  compilation checks, all four retained bundle verifications, and strict diff/index/worktree
  hygiene. Its 18-file recovery identity is
  `442b2bc945094722c854cf2891854f3d453e0f7dc7f3f5f8d58f1b504ac92df4`;
  the protected 111-file research identity remains unchanged.
- Removed the backup source database's check/attach race. After acquiring every cooperating lock,
  creation now opens every canonical source-parent component and the database leaf without
  following symlinks, copies through the retained descriptor, and requires its inode, size,
  modification time, and change time to remain
  stable and match the requested pathname before publication. Release schema identity reads that
  same descriptor while still recording the requested repository location. Tests replace the
  source pathname with another valid database and mutate source metadata after copying; both abort
  without publishing or deleting the replacement source. A parent-symlink swap immediately before
  secure traversal also fails closed. Source identity is checked again after publication; a
  deterministic swap during the atomic rename reports failure while preserving the verified
  published bundle. The final identity check also re-traverses every visible source-parent
  component without following symlinks and compares the resulting parent descriptor. A regression
  replaces the source parent with a symlink back to the unchanged original directory after copying;
  creation still detects the path-chain substitution and aborts before publication. The exact
  resulting tree passes all 1,548
  warnings-as-errors Python tests, the previously green 31-test UI/build/dependency gates, package
  builds, repository lint/complexity/compilation checks, all four retained bundle verifications,
  and strict diff/index/worktree hygiene. Its 18-file recovery identity is
  `b78fb3bf466166bac7d214b194fabc0d5b387415aed772267f0d87b11f25df8b`;
  the protected research identity remains unchanged.
- Anchored independent recovery-bundle verification instead of repeatedly trusting its public
  pathname. The verifier now opens every absolute parent component and the bundle root without
  following symlinks, performs all verification through the retained root descriptor, records the
  complete descriptor-rooted tree's inode, type, size, modification-time, and change-time identity
  before verification, and requires the same tree plus the same visible no-follow parent/root
  identity before returning success. Deterministic regressions prove that replacing the root with
  a byte-identical valid bundle after manifest loading, replacing a nested operational artifact
  with identical bytes after evidence validation, or substituting a parent with a symlink back to
  the unchanged original bundle all fail instead of returning `ok`. The complete 1,551-test
  warnings-as-errors Python suite, 31 UI contract tests, production UI build, repository Ruff and
  `server tools` C901, Python and shell compilation, documentation/release/worktree contracts,
  diff hygiene, and empty-index hygiene pass. All four retained original/restored v1/v2 bundles
  verify with their existing database and manifest hashes. The strict audit still reports 334
  fully owned paths, 102 tracked modifications, 232 untracked files, 21 required-untracked files,
  no unsafe symlinks, and an empty index. Release identity is complete and remains correctly
  non-releasable only for `dirty-working-tree` and `required-files-untracked`.
  The current 18-file recovery identity is
  `f411fa27f2718f9d36f059a21d756b786294cbeb65a0f993fc29fee21d109f03`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
  The API and UI remain active/enabled with zero restarts, `Linger=yes`, and six matching managed
  cron entries. Research remains paper-only with no ready family or automatic action; this change
  did not alter a strategy, portfolio, schedule, evidence checkpoint, or live-capital state.
- Made release identity one coherent filesystem observation and secured its public DuckDB schema
  read. The deterministic manifest still publishes path/type/executable/content hashes only, but
  now privately snapshots inode, mode, size, modification time, and change time for every
  Git-visible file and parent before and after construction. A regression changes a required lock
  file only during its named dependency hash and restores the original bytes before the final
  content scan; the candidate now fails with `working-tree-changed-during-scan` instead of being
  certified from mixed states. Public schema inspection now traverses every absolute database
  parent and opens the leaf without following symlinks, reads the catalog through the retained
  descriptor, and requires the opened leaf, anchored leaf, visible leaf, and visible parent chain
  to retain identity and metadata. Regressions cover an initial leaf symlink, an initial parent
  symlink, valid-database leaf replacement, parent substitution, and same-inode metadata mutation
  during catalog inspection; each fails with `database-schema-path-unsafe`. Backup creation's
  private schema read remains bound to its separately secured source descriptor. Recovery
  verification also now proves rejection of an initial symlinked bundle parent and of a nested
  operational file swapped only for semantic validation and restored before the final scan.
  The exact tree passes all 1,559 warnings-as-errors Python tests, 31 UI contract tests, the
  production UI build, repository Ruff and `server tools` C901, Python and shell compilation,
  documentation/release/worktree contracts, diff hygiene, and empty-index hygiene. All four
  retained original/restored v1/v2 recovery bundles still verify. The current 18-file recovery
  identity is `5cdfb9e387b1a8e4dc7f633c743b2dc202a3ca0dd436ac1f4b28afb7fbec27fd`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
  Release identity remains complete and correctly non-releasable only for
  `dirty-working-tree` and `required-files-untracked`. No strategy, portfolio, schedule,
  prospective observation, or live-capital state changed.
- Extended the release manifest's private ignored-database coherence guard across the complete
  absolute parent chain, not only the immediate parent and database leaf. A deterministic external
  database regression swaps a higher ancestor for a separately valid tree and restores the
  original before manifest completion; full parent-chain inode/type/size/timestamp identity now
  detects the substitution and reports `database-schema-path-unsafe`. This metadata remains an
  internal stability check and is not serialized into the deterministic release identity.
- Closed the inverse ignored-database state transition in release identity: a database absent at
  the initial private snapshot but created before catalog inspection can no longer become a valid
  release input mid-scan. A deterministic regression requires `database-schema-path-unsafe` for
  that transition while the unchanged missing-database case retains `database-missing`.
- Closed the corresponding non-Git research-runtime coherence gap. The manifest now computes the
  protected runtime identity again after its other scans and refuses release eligibility with
  `research-runtime-changed-during-scan` if the result differs. A deterministic regression creates
  an ignored Python source only during the first runtime hash and removes it before return; the
  mixed identity can no longer be certified. Protected source bytes were not changed.
- Closed the Git-reference side of the same release-scan coherence boundary. Commit, tree, branch,
  status/count state, and required-file tracking identity are now re-read before eligibility is
  decided. A deterministic empty commit during manifest construction leaves every working-tree
  byte unchanged but now fails with `git-identity-changed-during-scan` instead of combining the
  old Git identity with later file observations.
- Reverified the final release-coherence implementation after extracting Git/worktree reason
  assembly to remain below the enforced C901 threshold. All 1,565 warnings-as-errors Python tests,
  repository Ruff and `server tools` C901, Python/shell compilation, documentation/release/
  worktree contracts, diff hygiene, and empty-index hygiene pass. The 31 UI contracts and
  production build passed in the same work unit, and all four retained recovery bundles verify.
  Two consecutive real-tree release manifests are identical and expose no private filesystem
  metadata. The current 18-file recovery identity is
  `124cc714101ce2147c718917776f6037575b0bcb45fc8328f7f80990ebc6cfe3`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Removed the automation installer's re-plan-to-copy races for user service units. Planning now
  records a SHA-256 for each source unit; apply securely re-reads bounded bytes through a stable
  no-follow checkout chain, compares every changed unit before the first mutation, and installs
  those pinned bytes with descriptor-relative temporary creation, file synchronization, atomic
  replacement, and directory synchronization. The user unit directory is created/opened through a
  no-follow home-relative chain and its ancestors plus leaf inode are revalidated before any cron
  or systemd action. Regressions prove a source changed after re-plan aborts before installation, a
  destination directory replaced before opening receives no writes, and replacement after opening
  sends writes only to the retained displaced directory before failing closed. Existing crontab,
  enable/start, idempotence, invalid-host, and post-apply convergence contracts remain intact.
- Reverified the complete coherence-hardened tree. All 1,564 warnings-as-errors Python tests,
  repository Ruff and `server tools` C901, Python and shell compilation, documentation/release/
  worktree contracts, diff hygiene, and empty-index hygiene pass. The 31 UI contract tests and
  production UI build passed in the same work unit, and all four retained original/restored v1/v2
  bundles pass the final verifier. The current 18-file recovery identity is
  `d2b6a43302c522ac2140c18cdc4764599962fbc857d8da0630fc28f793a33994`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.

## 2026-09-12 — just-in-time crontab merge and final installer verification

- Proved and closed the automation installer's remaining stale-crontab window across service-unit
  preparation and installation. Apply now reads the current user crontab again immediately before
  replacement and renders the managed block over those latest bytes. A deterministic regression
  injects an unrelated cron line after changed units are installed and proves that line survives.
  Debian cron 3.0pl1 exposes no compare-and-swap install operation, so an external edit during the
  final `crontab -` subprocess itself remains an operator-coordination boundary and is documented
  explicitly rather than described as atomic.
- Final verification passes all **1,572 warnings-as-errors Python tests** across 104 files, all 31
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  shell compilation, documentation contracts, diff hygiene, and an empty index. All four retained
  original/restored v1/v2 recovery bundles verify. The read-only automation audit is drift-free:
  both services match, are active and enabled with zero restarts, `Linger=yes`, cron is active and
  enabled, and all six managed entries match. The 18-file recovery identity remains
  `124cc714101ce2147c718917776f6037575b0bcb45fc8328f7f80990ebc6cfe3`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Release identity remains complete and correctly non-releasable only for `dirty-working-tree`
  and `required-files-untracked`. Research remains paper-only with no automatic action and no
  ready family: sector momentum has 5/200 shared sessions, cross-sectional momentum has 0/48
  paired months, and E1 has 7/40 observations with mean net return
  `-0.0033563692688385488` and t-statistic `-1.4164938109635417`. No strategy threshold,
  evidence, portfolio, schedule, broker connection, or live-capital state changed.
- Anchored installed-unit inspection to the same bounded no-follow reader used for source units.
  Planning and post-apply verification now retain a descriptor while reading each installed unit
  and recheck its complete home-relative parent chain and visible leaf identity. A deterministic
  regression replaces an installed unit with a symlink during the descriptor read and proves the
  result is reported as drift rather than a false byte match.
- Reverified that follow-up with all **1,573 warnings-as-errors Python tests**, 31 UI contract
  tests, the production UI build, repository Ruff and `server tools` C901, Python/shell
  compilation, documentation contracts, diff hygiene, and an empty index. The real automation
  audit remains drift-free and all four retained recovery bundles still verify. Release identity
  is complete and non-releasable only for the unchanged dirty/untracked reasons; recovery identity
  remains `124cc714101ce2147c718917776f6037575b0bcb45fc8328f7f80990ebc6cfe3` and the
  protected research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Extended the same pre-mutation coherence check to service-unit sources that the re-plan found
  already installed and byte-identical. Apply now re-reads and compares both planned source hashes
  before any cron or systemd command, while retaining pinned installation bytes only for drifted
  units. A regression changes a previously matching source after re-plan while cron needs repair
  and proves apply aborts before invoking any external mutation.
- Final verification after that extension passes all **1,574 warnings-as-errors Python tests**
  across 104 files, repository Ruff and `server tools` C901, Python/shell compilation,
  documentation contracts, diff hygiene, and empty-index hygiene. The 31 UI contract tests and
  production UI build had already passed in this work unit and no UI source changed afterward.
- Extended plan/apply coherence to all six files invoked directly by managed cron. The plan now
  publishes a path and SHA-256 for each of the five executable drivers and the readable postflight
  verifier. Each is read through a bounded no-follow descriptor with parent-chain and leaf
  revalidation, and apply verifies all six identities before its first mutation. Regressions prove
  both a post-plan driver edit and an edit during descriptor reading fail closed without invoking
  cron or systemd. This changes installer audit metadata only; the managed schedule and launch
  commands are unchanged.
- Reverified the launch-source extension with all **1,576 warnings-as-errors Python tests** across
  104 files, all 31 UI contract tests, the production UI build, repository Ruff and `server tools`
  C901, Python/shell compilation, documentation contracts, diff hygiene, and an empty index. The
  read-only live automation audit remains `ok` with no planned changes and now reports all six
  launch-source hashes.
- Made unstable service-unit sources explicitly invalidate a dry-run plan instead of presenting
  them as repairable installed-unit drift. Installed targets remain repairable, but an unsafe or
  concurrently changing versioned source cannot authorize apply. A descriptor-read mutation
  regression proves the plan returns `invalid` with a null source hash.
- Final verification passes all **1,577 warnings-as-errors Python tests** across 104 files, all 31
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  shell compilation, documentation contracts, diff hygiene, and an empty index. The live
  automation plan remains valid and drift-free after the stricter source classification.
- All four retained original/restored v1/v2 recovery bundles still verify. Release identity is
  complete and remains non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the 18-file recovery identity remains
  `124cc714101ce2147c718917776f6037575b0bcb45fc8328f7f80990ebc6cfe3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Bounded the remaining direct server-side filesystem read: scheduled-driver liveness now scans
  `/proc/locks` incrementally instead of materializing the entire kernel table. It stops at the
  first matching advisory lock, accepts a bounded no-match result, and treats a no-match table over
  1 MiB as unavailable. Tests cover chunk-boundary matching and the exact size ceiling; lock-path
  pinning and replacement detection remain unchanged.
- Added one shared bounded runner for read-only host probes. Scheduler `crontab`/`systemctl`/
  `timedatectl` calls and local-only Git tracking calls now share a five-second wall-clock deadline
  and 1 MiB combined output ceiling, drain stdout and stderr concurrently, reject invalid UTF-8,
  and kill/reap children on timeout, overflow, or read failure. Process-level tests cover normal
  output and nonzero exit status, the exact byte boundary, overflow, invalid text, ordinary timeout,
  and a child that closes both pipes before sleeping. `server/host_command.py` is explicitly part of
  the release-critical scheduler source set.
- The host-probe change passes all **1,613 warnings-as-errors Python tests** across 106 files, all
  31 UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python
  compilation, interpreter-aware shell syntax, diff hygiene, and the empty-index gate. After an
  intentional API-only restart, all eight checked JSON routes return HTTP 200; scheduler state is
  `ok`, source control remains truthfully `local-only`, and all five driver projections retain their
  prior meanings. Both user services are active with zero unexpected restarts, automation is fully
  converged with `Linger=yes`, and all four retained recovery bundles verify.
- Strict inventory now contains 336 owned paths (102 tracked modifications and 234 untracked
  files), including the new helper and its tests; 22 release-required files remain untracked, with
  no staged, unknown-owner, empty-untracked, or unsafe-symlink paths. Release identity is complete
  and remains non-releasable only for `dirty-working-tree` and `required-files-untracked`. The
  pre-ledger manifest identity is
  `6a28d1fdb3901f2639ae53d62dbc1692dc50e508206b2b29b80f26c8195a4078`, working-tree identity is
  `95bc539d5f39be912f256d55e7444c6141cf4a501f54b2bdc6bf01c0f3d10012`, schedule-source identity is
  `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity is
  `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Bounded the final unbounded collection exposed directly by a dashboard route. `GET /positions`
  now returns at most 500 active holdings in deterministic portfolio/ticker order, reports the full
  `matching_count` and an exact `truncated` flag, and limits quote/stop enrichment to returned
  tickers. The UI validates those relationships and shows an explicit partial-exposure notice when
  rows are omitted. The current live 275-position set remains below the cap.
- Made the just-in-time cron reconciliation authoritative even when the immediately preceding
  plan observed no cron drift. A regression changes a previously matching crontab while source
  identities are being checked; apply now merges and installs the latest unrelated line, restores
  the managed block, and reports that late repair instead of performing service-manager actions
  and failing only during post-apply verification.
- Final verification passes all **1,578 warnings-as-errors Python tests** across 104 files, all 31
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  shell compilation, documentation contracts, diff hygiene, and an empty index. The read-only
  live installer audit remains `ok` with no drift.
- Made apply converge two kinds of state that can drift after a matching re-plan. User lingering
  is checked again immediately before its action and enabled if it became disabled, with the late
  repair reflected in the returned change summary. Installed-unit comparison and publication now
  happen through one retained destination-directory descriptor; newly drifted units are repaired
  from pinned source bytes and added to the reload/restart set. A regular-directory substitution
  between comparison and opening can no longer receive writes: publication stays on the original
  descriptor and apply fails before cron or systemd after the visible-path identity check.
- Closed the remaining regular-directory substitution window inside the secure unit-directory
  opener. It now requires device/inode continuity for the complete home-relative chain between
  its create and verification opens before exposing the write descriptor. The check deliberately
  ignores timestamp changes caused by creating missing descendants. A regression swaps an
  ordinary directory between those opens and proves the replacement remains empty, the displaced
  units remain untouched, and no external command runs.
- Final verification passes all **1,582 warnings-as-errors Python tests** across 104 files, all 31
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  shell compilation, documentation contracts, diff hygiene, and an empty index. The live
  installer audit remains `ok` with no planned changes.
- Made service-manager actions both minimal and based on a fresh mutation-boundary snapshot.
  Apply now enables only units currently disabled, starts only currently inactive units whose
  files were not already restarted, and issues no mutating systemd command when state is fully
  converged. A unit disabled or stopped after the complete re-plan is repaired and included in the
  returned change summary. Regressions prove both late drift and mutation-free idempotence.
- Final verification passes all **1,584 warnings-as-errors Python tests** across 104 files, all 31
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  shell compilation, documentation contracts, diff hygiene, and an empty index. The read-only
  live installer audit remains `ok` with no planned changes.
- Updated the contributor automation contract to match the final installer implementation: six
  cron launch-source hashes plus two service-unit source hashes, bounded no-follow reads and
  pre-mutation revalidation, one retained destination-directory descriptor for comparison and
  publication, symlink and ordinary-directory substitution detection, just-in-time cron/linger/
  service-state reconciliation, mutation-free converged apply, and the native `crontab` final-
  command concurrency boundary. Regression assertions now keep this concise contributor summary
  aligned with the detailed runbook. All 68 focused documentation and installer tests pass, as do
  repository Ruff, `server tools` C901, diff hygiene, and the empty-index gate.
- Rechecked the live unattended deployment after the documentation update. The read-only installer
  reports `ok`: all six cron entries and source hashes match, both service units match and are
  enabled/active, `Linger=yes`, and no mutation is planned. Strict inventory remains 334 owned
  changed paths (102 tracked modifications and 232 untracked files), with no staged, unknown-owner,
  empty-untracked, or unsafe-symlink paths. Release identity is complete and non-releasable only for
  `dirty-working-tree` and `required-files-untracked`; the immediately preceding pre-ledger
  checkpoint's manifest identity was
  `4764777055335a576248e773db2d94d0ea83468c79cdc33099808e71ceb6beca`. The 18-file recovery
  identity remains `124cc714101ce2147c718917776f6037575b0bcb45fc8328f7f80990ebc6cfe3`, and
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Hardened the shared operational-artifact reader used by API evidence projections. It now rejects
  invalid byte ceilings, requires two bounded descriptor reads to return identical bytes, compares
  descriptor identity, type, size, modification time, and change time across the read, then requires
  the visible final path to identify the same regular file. Deterministic regressions prove that an
  equal-length in-place mutation, pathname replacement, and removal fail closed while intentional
  alternate data roots reached through a symlinked parent remain supported. The operating guide now
  states this stable-read boundary.
- Reverified the production-support change with all **1,591 warnings-as-errors Python tests** across
  105 files, including 521 focused reader/monitor/read-model/documentation tests; all 31 UI contract
  tests; the production UI build; repository Ruff and `server tools` C901; Python and shell
  compilation; diff hygiene; and an empty index. After one intentional API restart, all eight
  health/meta/readiness/league/positions/orders/journal/ticket-context probes returned HTTP 200 with
  valid JSON, the UI remained active, and both services report zero unexpected restarts. All four
  retained original/restored schema-v1/v2 recovery bundles still verify. The hardened 18-file
  recovery identity is `cdbd2aeebcc92b53c051ec01e0823b3ff7a87de18f356e6477b4c97aa81de89b`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Strengthened the stable-read proof after an equal-length rewrite demonstrated that immediate
  filesystem metadata alone is not a sufficient deterministic test oracle. Immutable operational
  artifacts are now read twice through the same bounded descriptor and both byte sequences must
  match in addition to the metadata and visible-path checks. The append-only driver-log parser
  deliberately retains its separate streaming reader because an active scheduled job may extend
  that log normally. The final full 1,591-test, UI test/build, lint, complexity, compilation, shell,
  diff, and empty-index gates pass; the final API process serves all eight checked routes after its
  intentional restart; and all four retained recovery bundles verify. The final 18-file recovery
  identity is `72cd639f9703d15e270b365c16836e0ec936b5f6238c929b26bed45d61226ebc`;
  the protected research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Hardened scheduled-driver monitoring without imposing immutable-file semantics on logs that are
  legitimately appended while a job runs. The parser now requires the visible log path to retain
  the identity of its opened descriptor after parsing and reports concurrent replacement as
  `log-changed-during-read`. Lock probes now open a regular final path without following symlinks,
  retain that descriptor while consulting `/proc/locks`, and reject ordinary or symlink
  substitution; an unsafe lock remains conservatively unavailable rather than borrowing another
  inode's liveness. Tests cover each substitution case, and the liveness comment now accurately
  states that only unterminated runs receive the second lock sample.
- The final tree passes all **1,595 warnings-as-errors Python tests** across 105 files, all 31 UI
  contract tests, the production UI build, repository Ruff and `server tools` C901, Python/shell
  compilation, diff hygiene, and the empty-index gate. The API was intentionally restarted to load
  the new monitor; all eight checked JSON routes return HTTP 200, all five driver projections remain
  coherent, the UI stayed active, automation remains drift-free, and all four retained original/
  restored schema-v1/v2 recovery bundles verify. No protected research source or strategy evidence
  changed.
- Closed a pathname-race gap in the read-only scheduler launch audit. Repository-owned cron drivers,
  the Friday postflight module, and `logs/` are now inspected through no-follow descriptors rooted at
  the checkout; kernel access checks target the opened object, and a second traversal must retain the
  same parent-chain and leaf metadata identity. Deterministic tests replace a launch leaf, its parent
  directory, and the log directory during inspection and prove each case fails closed. Existing
  managed log targets use the same stable inspection, while stable absence remains valid so cron
  can create a target; replacement, removal, or appearance during the probe fails closed, while
  legitimate append growth remains valid. The normal
  `.venv/bin/python` interpreter symlink remains supported and is still checked separately.
- The resulting tree passes all **1,602 warnings-as-errors Python tests** across 105 files, all 31 UI
  contract tests, the production UI build, repository Ruff and `server tools` C901, Python
  compilation, interpreter-aware shell syntax, diff hygiene, and the empty-index gate. The API was
  intentionally restarted; all eight checked JSON routes return HTTP 200, `/meta.scheduler` reports
  production 5/5 plus postflight 1/1 with no launch or log findings, and both user services remain
  active with zero unexpected restarts. The automation dry-run remains converged with `Linger=yes`.
- A final recovery check found that only the original schema-v1 source bundle's five nested evidence
  directories retained their pre-hardening `0755` modes. Their group/other directory permissions
  were tightened to `0700`; no bundle contents or manifest were changed, and the preserved
  `~/trading-engine-restore-drill.Uol8Ay` tree was untouched. All four retained
  original/restored schema-v1/v2 bundles now verify. Strict inventory remains 334 fully owned paths
  (102 tracked modifications and 232 untracked files), with an empty index and no unknown, empty,
  staged, or unsafe-symlink paths. Release identity remains complete and non-releasable only for
  `dirty-working-tree` and `required-files-untracked`; the pre-ledger manifest identity is
  `a5573b465606a018d43d6bd60465c51b06d4a87b2a9088deb6111026da3f64bf`, working-tree identity is
  `361efa8245269e9fb0f05ecc10759ff1e1aadb1da7b69a941370692c99c91792`, recovery-source identity
  remains `cc52daefa99410b0ffba4e507181eeffd803ce4f8bb8f6eda1773243abdf5b11`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Bounded both dimensions of the live League projection without changing its analytical
  semantics. `GET /league` now computes returns, drawdowns, comparisons, and ranks over the
  complete eligible active cohort before deterministically returning at most 100 rows; it exposes
  exact `limit`, `matching_count`, and `truncated` metadata. `GET /league/equities` independently
  derives the same ranked selection, returns curves only for those displayed IDs, repeats the
  portfolio-level bound metadata, and retains the existing newest-500-observations bound for each
  curve. The UI requires the declared ranking/comparison basis, persisted-capital fields, current-
  before-stale and descending-return order, and exact agreement between both responses before
  rendering; it visibly reports either table or curve truncation. A high-cardinality regression
  proves selection is by complete ranking rather than alphabetical registration order.
- The resulting tree passes all **1,615 warnings-as-errors Python tests** across 106 files, all 31
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  interpreter-aware shell compilation, diff hygiene, and the empty-index gate. After intentional
  API/UI restarts, all eight checked JSON routes and the League page return HTTP 200; the live
  standings and bulk curves expose the same 21 IDs and coherent 21-of-100 non-truncated metadata.
  Both services are enabled and active with `NRestarts=0`; the six-entry automation configuration
  is converged with `Linger=yes`; and all four retained original/restored schema-v1/v2 recovery
  bundles verify. Strict inventory remains 336 fully owned changed paths with no staged, unknown,
  empty-untracked, or unsafe-symlink paths. Release identity remains complete and non-releasable
  only for `dirty-working-tree` and `required-files-untracked`; the pre-ledger manifest identity is
  `797135a2b67157dbf789bdbe19aa156b712c1cbace84779b109a316beabbfe8d`, working-tree identity is
  `326da6db17a2140cd8f8c40686c6b0bcdedf7e3c81f5294c7106b5cf2e7cee83`, schedule-source identity
  remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity
  remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Bounded the remaining database-backed detail collection in `GET /meta`. Active price
  quarantines now expose an exact complete count, at most 100 ticker-sorted details, an explicit
  list truncation flag, and a per-row flag when ticker/reason/evidence text was clipped to its
  public diagnostic ceiling. This is projection-only: persisted adjudication records and the
  per-ticker buy-blocking lookup remain complete. The UI contract validates the bounded metadata,
  row ordering, unique tickers, timestamps, text limits, and truncation markers before admitting a
  successful response.
- The resulting tree passes all **1,617 warnings-as-errors Python tests** across 106 files, all 32
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  interpreter-aware shell compilation, diff hygiene, and the empty-index gate. After intentional
  API/UI restarts, all ten checked JSON routes and the dashboard return HTTP 200; live quarantine
  metadata is coherent at 0 of 100 rows, and both services remain enabled and active with
  `NRestarts=0`. Automation is converged at six entries with `Linger=yes`, and all four retained
  original/restored schema-v1/v2 recovery bundles verify. Strict inventory remains 336 fully owned
  changed paths with no staged, unknown, empty-untracked, or unsafe-symlink paths. Release identity
  remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `b2b1575e3f863306cd7e021290db46d88ab19a176ed84c1717ab20d8aced39ec`, working-tree identity is
  `78c066fe343582befd0de51f1daa88e0f7a6a9038590850520b75a6c721d1a8b`, schedule-source identity
  remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity
  remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Current strategy-readiness evidence still requires prospective time rather than another tuning
  run: stock selection has 41/756 qualifying shared dates, fundamentals has 9/156 qualifying
  snapshots, intraday has 47/252 one-minute and 100/252 five-minute sessions, sector momentum has
  5/200 shared forward sessions, and the frozen cross-sectional momentum observation boundary has
  not started. No strategy, gate, evidence artifact, broker integration, or capital state changed.
- Closed the remaining variable-text path in the bounded queue projection. The full stored sweep
  parameters are still parsed before actionable-versus-historical classification, while public
  failure copies cap `kind` at 64 characters and `params`, `progress`, and `last_error` at 4,096
  characters. The latest-research-job summary caps its variable diagnostic text at the same
  boundary. Both shapes expose `detail_truncated`, and the UI rejects missing markers or oversized
  successful payloads. Complete failure counts, newest-100 ordering, and queue state are unchanged.
- The resulting tree passes all **1,618 warnings-as-errors Python tests** across 106 files, all 32
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  interpreter-aware shell compilation, diff hygiene, and the empty-index gate. After intentional
  API/UI restarts, all ten checked JSON routes and the dashboard return HTTP 200. The live queue
  remains zero actionable and one historical failure; both that row and the latest research job
  publish coherent non-truncated detail metadata. Both services remain enabled and active with
  `NRestarts=0`; automation is converged at six entries with `Linger=yes`; and all four retained
  recovery bundles verify. Strict inventory remains 336 fully owned changed paths with no staged,
  unknown, empty-untracked, or unsafe-symlink paths. Release identity remains complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`; the pre-ledger
  manifest identity is `740e10576005a080cea1e95d1246fee101b29b387c4f651d8ef54e781f07e044`,
  working-tree identity is `bca9a24503eeb8e0a51b063e2c0f5faed97496583caa8f898d64318216f7b198`,
  schedule-source identity remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`,
  recovery-source identity remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`,
  and the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`.
- Bounded all six walk-forward evidence diagnostic categories without weakening the evidence
  decision. The server still scans the complete active artifact cohort, but `missing_results`,
  `invalid_files`, config/registration mismatches, duplicate config IDs, and invalid registrations
  now each expose an exact count, at most 100 sorted values, a list-truncation flag, and an
  independent value-truncation flag; public values are capped at 256 Unicode code points. The UI
  validates those relationships, code-point ordering, uniqueness whenever clipping cannot create
  duplicate prefixes, and the only permitted sparse `projection-error` fallback. Adversarial
  coverage with non-empty diagnostics also exposed and fixed a previously dormant missing UI
  predicate import. The operator guide now documents the complete-scan versus bounded-projection
  boundary.
- The resulting tree passes all **1,623 warnings-as-errors Python tests** across 106 files, all 33
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  interpreter-aware shell compilation, frozen-lock validation, a fresh wheel build, zero production
  npm vulnerabilities, diff hygiene, and the empty-index gate. After intentional API/UI restarts,
  eleven direct JSON routes, the dashboard, League page, and UI health/meta proxies return HTTP 200.
  Live walk-forward evidence remains `current` at 18/18 with one cohort signature and six coherent
  empty bounded diagnostic categories. Both services remain enabled and active with `NRestarts=0`;
  automation is converged at six entries with `Linger=yes`; and all four retained original/restored
  schema-v1/v2 recovery bundles verify. The preserved
  `~/trading-engine-restore-drill.Uol8Ay` tree was not modified.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `8842547c1a7972f7314c2eef3d2aae563087e9695f0241c97c951132dce537f4`, working-tree identity is
  `01866bad830fa8f8d22fe6113059c51330c5e385368c2179be76e64788fcbe2a`, schedule-source identity
  remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity
  remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Strategy profitability
  remains unproven; no search, strategy tuning, gate change, evidence rewrite, broker connection,
  or live-capital action occurred.
- Removed the remaining raw producer-snapshot pass-through from `GET /meta`. The complete bounded
  `_meta.json` object still reaches nightly, miner, liquidity, and price-verification reconcilers,
  but the public `meta` object now contains only validated `regime`, `last_run`, `last_screen`, and
  `screen_date` fields. Present malformed summary fields fail that summary closed, and `meta_file`
  no longer reveals the local filesystem path. The UI requires the exact public field allowlist and
  timezone-aware timestamps. Integration coverage proves private producer bookkeeping remains
  available to all four internal evidence consumers while being absent from the API response.
- The change passes all **1,632 warnings-as-errors Python tests** across 106 files, all 33 UI
  contract tests, the production UI build, repository Ruff and `server tools` C901, Python/shell
  compilation, frozen-lock validation, a fresh wheel build, zero production npm vulnerabilities,
  diff hygiene, and the empty-index gate. After intentional API/UI restarts, all eleven direct JSON
  routes and six checked UI pages/proxies return HTTP 200. `GET /meta` fell from 18,124 to 8,359
  bytes, while twelve operational/evidence subtrees were byte-for-byte unchanged. Both services
  remain enabled and active with `NRestarts=0`; automation remains converged at six entries with
  `Linger=yes`.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `f450b00c2b9d40f8395517561ddfd65648ac8d93822d1518b8bfc65a1b3ebcc0`, working-tree identity is
  `259e2dd62c6b355345a33b1c703e57679c46479796f4b438a8e05638b8d08fd8`, schedule-source identity
  remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity
  remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. The source snapshot and
  retained recovery trees were not changed.
- Bounded legacy/manual free text in the paper-history projections without rewriting DuckDB.
  Each of the newest 500 active-book orders now caps display-only `playbook` at 128 characters and
  `reject_reason` at 4,096; each of the newest 100 discretionary tickets caps `playbook`, `emotion`,
  and `notes` at their existing 128-, 32-, and 4,096-character submission limits. Every returned
  row publishes `detail_truncated`, and the UI rejects missing markers, oversized fields, or a true
  marker with no field at its clipping boundary. Existing gate JSON limits, row counts, status
  filtering, ordering, and stored append-only values remain unchanged.
- The change passes all **1,634 warnings-as-errors Python tests** across 106 files, all 33 UI
  contract tests, the production UI build, repository Ruff and `server tools` C901, Python/shell
  compilation, frozen-lock validation, a fresh wheel build, zero production npm vulnerabilities,
  documentation contracts, diff hygiene, and the empty-index gate. After intentional API/UI
  restarts, all eleven direct JSON routes and six checked UI pages/proxies return HTTP 200. The
  live 500 order rows and seven journal tickets are byte-equivalent to their pre-deployment rows
  after removing the new false markers; none required clipping. Both services remain enabled and
  active with `NRestarts=0`, and automation remains converged at six entries with `Linger=yes`.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `dc1fed26f6df8ef799534a24885eaccfe25bbf9d51d14d8b46129cc1184ad186`, working-tree identity is
  `e91f32fbf12d89fa1556019eb059d527b3f277a84e42d80c641d6fc18968bfa1`, schedule-source identity
  remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity
  remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Strategy evidence and
  profitability status remain unchanged.
- Bounded the remaining one-to-many expansion inside each visible discretionary journal ticket.
  The schema and execution path intentionally model one fill per order, and the live ledger still
  confirms a maximum of one across 1,039 fills and 1,039 distinct orders, but `sim_fills.order_id`
  has no uniqueness constraint. Each visible ticket now returns at most its newest 100 linked fills
  with exact `fills_matching_count`, `fills_limit`, and `fills_truncated` metadata. The retained
  newest rows are presented chronologically, while circuit-breaker analysis continues to stream
  the complete fill ledger. The shared display-only text clipping primitive was also extracted for
  the order and journal projections without changing stored values or their public limits.
- The change passes all **1,636 warnings-as-errors Python tests** across 106 files, all 33 UI
  contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  interpreter-aware shell compilation, frozen-lock validation, a fresh wheel build, environment
  compatibility, zero production npm vulnerabilities, documentation contracts, diff hygiene, and
  the empty-index gate. After intentional API/UI restarts, all eleven direct JSON routes and six
  checked UI pages/proxies return HTTP 200. The live seven-ticket journal uses a 100-fill per-ticket
  limit, exact counts of zero or one, and no truncation; after removing the three new metadata
  fields, its parsed response is identical to the pre-deployment snapshot. Both services remain
  enabled and active with `NRestarts=0`; automation remains converged at six entries with
  `Linger=yes`; and all five discoverable retained original/restored schema-v1/v2 bundle trees
  verify. The preserved `~/trading-engine-restore-drill.Uol8Ay` tree was not
  modified.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `e3cc773a53d9efec601496a0e45d7f7c5d71b9fa09f9c17bf5611acf30dd6744`, working-tree identity is
  `d2296e613f3cc97419922ce7987f18f505d27161db17767bb82a025045249111`, schedule-source identity
  remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity
  remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Forward evidence remains
  untouched: sector and E1 are `ACCUMULATING`, cross-sectional momentum is `WAITING`, and strategy
  profitability remains unproven. No search, tuning, gate change, broker connection, or live-capital
  action occurred.
- Corrected two operator-guide summaries after comparing them to the deployed source and live host
  state. The opening topology now says five deterministic production cron schedules plus one
  evidence-only Saturday postflight, matching the installer's six-entry managed block while
  preserving `/meta.scheduler`'s intentional 5/5 production and 1/1 auxiliary counters. The
  component map now credits `read_model_utils.py` with both row materialization and shared
  display-text bounds introduced by the preceding journal/order cleanup. Regression assertions
  pin both descriptions so the high-level map cannot silently drift from those contracts again.
- The 49 focused documentation and architecture tests pass with warnings as errors, as do Ruff,
  diff hygiene, and the empty-index gate. No runtime source changed, so the API/UI services were
  not restarted; both remain enabled and active with `NRestarts=0`. The read-only automation audit
  is converged at six managed entries with `Linger=yes`. The pre-ledger manifest identity is
  `794aaf0954300e8f89dbe54d2b61be72695ef58f897f9328cf12985100383545`, working-tree identity is
  `7d0ec9972b06e8c31cdbb79c3184083557274cf0aaf2eec55fd7971fd384ff75`, schedule-source identity
  remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity
  remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Release status remains
  identity-complete but non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; strategy evidence is unchanged.
- Removed the absolute DuckDB filename from the public `GET /health` response, closing the same
  host-filesystem disclosure class previously removed from `GET /meta`. The endpoint still opens
  the configured database and runs its probe, still returns HTTP 503 with stable `busy` or
  `unreadable` states, and now has one exact three-field public shape in every state: `ok`,
  `status`, and `db_readable`. Tests assert the complete healthy and failure payloads rather than
  checking only selected keys, and the operator guide records that neither exception detail nor
  the configured path is public.
- The change passes all **1,639 warnings-as-errors Python tests** across 106 files, all 33 UI
  contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  interpreter-aware shell compilation, frozen-lock validation, a fresh wheel build, environment
  compatibility, zero production npm vulnerabilities, documentation contracts, diff hygiene, and
  the empty-index gate. After restarting only the changed API service, all eleven direct JSON
  routes and six checked UI pages/proxies return HTTP 200. Live `/health` is 44 bytes and matches
  the exact three-field contract; removing the old `db_path` field from the captured predecessor
  yields the new response exactly. Both services remain enabled and active with `NRestarts=0`,
  automation remains converged at six entries with `Linger=yes`, and all five discoverable retained
  original/restored schema-v1/v2 bundle trees verify.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `8f3a89231976c3d8830d4bef77aab312af090fec0cc612d67cdd8a7ce716f601`, working-tree identity is
  `1ae6481172805828573edc29d04f15bc60751029ab50c15cc5bb762a51cd6e49`, schedule-source identity
  remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity
  remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. The scheduled Friday
  nightly, Saturday postflight, verifier, and no-op sweep all reached their expected terminal
  states; the verifier's five-name secondary-source disagreement remains already adjudicated and
  has no active position or pending-order exposure. No stored price, quarantine, strategy, gate,
  evidence artifact, broker connection, or capital state changed.
- Removed absolute cron-log filenames from the five public scheduled-driver objects in `GET /meta`.
  Raw driver status still carries those paths through server-side nightly, price-verification,
  liquidity, and walk-forward recovery reconciliation; a final projection strips only `log` before
  serialization. Sparse optional-monitor fallbacks remain sparse, and the browser contract now
  rejects any reintroduced driver `log` field. The operator guide documents that schedule, stage,
  timing, exit, and recovery state remain public while host log locations do not.
- The resulting tree passes all **1,642 warnings-as-errors Python tests** across 106 files, all 33
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  interpreter-aware shell compilation, frozen-lock validation, a fresh wheel build, environment
  compatibility, zero production npm vulnerabilities, documentation contracts, diff hygiene, and
  the empty-index gate. After intentional API/UI restarts, all eleven direct JSON routes and six
  checked UI pages/proxies return HTTP 200. `/meta` fell from 8,359 to 8,101 bytes; removing only
  the four present `log` fields from the captured predecessor yields the new response exactly,
  weekly liquidity remains legitimately `null` before its first scheduled slot, and no
  `/data00/home/` path remains. `/health` retains its exact three-field path-free response. Both
  services remain enabled and active with `NRestarts=0`; automation remains converged at six
  entries with `Linger=yes`; and all five discoverable retained original/restored schema-v1/v2
  bundle trees verify.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `c23ec5c373a581ae7871f9c1db223d01ecc5b74b214bb7024ed72a21802d1036`, working-tree identity is
  `7412d5e166007047eaec30e079fe238bb0c50a1e2404b03ceeee870d8dbd9b86`, schedule-source identity
  remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity
  remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Strategy evidence and
  profitability status remain unchanged.
- Removed the final latent host-path field from recurring-sweep evidence. The sweep monitor still
  resolves, reads, and validates the exact versioned `ranking.json` internally, including its
  identity, publication time, and complete trial accounting, but a current public charter now
  exposes only evidence identity and counts rather than the absolute ranking filename. The browser
  contract accepts only exact status-specific envelope and charter shapes and rejects `ranking`
  or any other unreviewed property. Raw queue progress and worker-error text are no longer repeated
  in charter evidence, while the separately bounded queue projection remains available. Synthetic
  current and failed-charter tests prove the dormant branches' exact path-free shapes, and the
  operator guide records the boundary.
- The resulting tree passes all **1,644 warnings-as-errors Python tests** across 106 files, all 33
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  interpreter-aware shell compilation, frozen-lock validation, a fresh wheel build, environment
  compatibility, zero production npm vulnerabilities, documentation contracts, diff hygiene, and
  the empty-index gate. After intentional API/UI restarts, all eleven direct JSON routes and six
  checked UI pages/proxies return HTTP 200. Live sweep evidence remains legitimately idle and
  `/meta` remains 8,101 bytes; a recursive scan of all eleven JSON responses finds no absolute-path
  value. Both services remain enabled and active with `NRestarts=0`; automation remains converged
  at six entries with `Linger=yes`; and all five discoverable retained original/restored
  schema-v1/v2 bundle trees verify.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `0b89cbf3241e1d0083e251f4bf703143fb499ab106121e2aa4506699ddf9650f`, working-tree identity is
  `a1b6bddf443992d2e51db269b76fe09fb0376e0c3e9a84cbd06d3aacca879697`, schedule-source identity
  remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity
  remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. No strategy, gate,
  evidence artifact, database row, broker connection, or capital state changed.
- Narrowed the public queue projection to the operational fields its dashboard consumer needs.
  Failure rows now expose only `id`, bounded `kind`, and `updated_at`, plus the fixed historical
  classification when applicable; the latest research job adds only `state`. Full parameters,
  progress, and worker errors remain unchanged in DuckDB and complete sweep parameters still drive
  actionable-versus-historical classification before projection. The browser contract now rejects
  unknown queue states, extra queue-envelope fields, and extra detail-row fields.
- The resulting tree passes all **1,645 warnings-as-errors Python tests** across 106 files, all 33
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  interpreter-aware shell compilation, frozen-lock validation, a fresh wheel build, environment
  compatibility, zero production npm vulnerabilities, documentation contracts, diff hygiene, and
  the empty-index gate. After intentional API/UI restarts, all eleven direct JSON routes and six
  checked UI pages/proxies return HTTP 200. `/meta` fell from 8,101 to 7,911 bytes; removing only
  `params`, `progress`, `last_error`, and `detail_truncated` from the predecessor's queue-detail
  records makes the complete responses equal. Queue totals remain 447 done, one failed, and 31
  superseded; the one failed sweep remains correctly classified as closed history. No absolute
  path appears in the response. Both services remain enabled and active with `NRestarts=0`;
  automation remains converged at six entries with `Linger=yes`; and all five discoverable
  retained original/restored schema-v1/v2 bundle trees verify.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `d2f504f84eacea4543e7fbf72d1fec26aeee262ac1227aa09ebfa3227931f6fd`, working-tree identity is
  `96f1fa2f7ebc01bd1dbae045e0e5b61048ee734f9fb5f9c74a74e76cf2a4a302`, schedule-source identity
  remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity
  remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Strategy evidence and
  profitability status remain unchanged.
- Replaced the scheduled-driver public projection's `log` blacklist with an explicit 19-field
  allowlist after all internal parsing, schedule reconciliation, and walk-forward recovery work.
  Future parser or recovery members such as command lines, filesystem paths, and private state can
  no longer become public merely by being added to an internal dictionary. The browser contract
  accepts exactly the same reviewed fields, validates timestamps, exit and lock types, known queue
  states, and paired job totals/counts, and rejects unknown properties. Regression tests prove the
  public result is a separate value, leaves internal status untouched, and applies the same
  projection when optional walk-forward reconciliation fails.
- The resulting tree passes all **1,645 warnings-as-errors Python tests** across 106 files, all 33
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  interpreter-aware shell compilation, frozen-lock validation, a fresh wheel build, environment
  compatibility, zero Python/runtime and production npm vulnerabilities, documentation contracts,
  diff hygiene, and the empty-index gate. After intentional API/UI restarts, all eleven direct JSON
  routes and six checked UI pages/proxies return HTTP 200. The complete pre/post-deployment `/meta`
  objects are semantically equal at 7,911 bytes, the live payload passes the stricter browser
  contract, and no absolute path appears. Both services remain enabled and active with
  `NRestarts=0`; automation remains converged at six entries with `Linger=yes`; and all five
  discoverable retained original/restored schema-v1/v2 bundle trees verify.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `8c8e3c675d21e7aeed73e26f22b168b267a40c67a196ac93d6cefaf5a4076bc7`, working-tree identity is
  `4102598ac0fc1aa0321aa3cbd5db1b6667afdb95928f2f923f0e12eb74dcc951`, schedule-source identity
  remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity
  remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Strategy evidence and
  profitability status remain unchanged; no search, tuning, gate, database row, broker connection,
  or capital state changed.
- Tightened the browser's scheduled-driver contract from a global field/type check to the exact
  states produced by log parsing, schedule reconciliation, and walk-forward queue reconciliation.
  Known invalid reasons now have reason-specific shapes; a driver-name mismatch must carry the
  expected canonical name for its `/meta` slot; shell-driver timestamps use the producer's
  whole-second UTC `Z` form; completed, running, interrupted, stale, and overdue states reject
  fields that belong to other states; and overdue metadata must describe a coherent preserved
  prior state. Walk-forward validation reconstructs and validates that base state separately from
  its queue overlay, then checks count-pair totals, allowed predecessor states, updating versus
  completed timestamps, and recovery fields that may exist only after a failed driver. The
  operator guide now records this status-and-transition boundary, including the intentional
  timezone-naive database timestamps used only by the recovery overlay. Regression fixtures cover
  every accepted state and reject unknown reasons, wrong driver identity, malformed timestamp
  forms, misplaced fields, and impossible recovery transitions.
- The resulting tree passes all **1,647 warnings-as-errors Python tests**, all 33 UI contract tests,
  the production UI build, repository Ruff and `server tools` C901, Python, JavaScript, and shell
  compilation, frozen-lock validation, a fresh wheel build, environment compatibility, zero
  production npm vulnerabilities, documentation contracts, diff hygiene, and the empty-index
  gate. After restarting only the changed UI, twelve read-only direct API requests and six UI
  pages/proxies return HTTP 200. Direct and proxied `/meta` are byte-identical at 7,911 bytes,
  pass the source-tree browser validator, and expose no `/data00/home/` path. Both services remain
  enabled and active with `NRestarts=0`; the read-only automation plan is converged at six managed
  entries with `Linger=yes`; and all five retained original/restored schema-v1/v2 recovery trees
  verify. Strategy evidence remains an honest wait: Sector is `ACCUMULATING` at 5/200, XS is
  `WAITING` at 0/48, E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic,
  walk-forward evidence is current at 18/18, and recurring sweeps are idle with no open charter.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `5730b3edd6f54b212ee39040340efd32ffec9277a8c2000b88309a66cc87fc6f`, working-tree identity is
  `6cce8f2178825c1f2c6d07eee20500b365c724837351d4a81ee10d1983c11a62`, schedule-source identity
  remains `2beb556abe60234cf74ccd61cc841a27031e6708627ceb146deada5fe2d4b7f3`, recovery-source identity
  remains `84395bac7ab1caec089111d8c2e7381921324081d5d3b4d33e188d38ea8897f3`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. No strategy, gate,
  generated evidence, database row, broker connection, or capital state changed.
- Made the `/meta` boundary deny-by-default at both levels. The backend now projects the complete
  composed response through an explicit 28-field top-level allowlist as well as the existing
  19-field driver allowlist, requires every documented top-level member, and has cross-language
  regressions proving both backend inventories remain ordered and identical to their browser
  contracts. Unknown internal top-level fields are omitted without mutating the composed value,
  while an omitted required field fails at composition instead of becoming an incomplete HTTP-200
  response. The operating guide records this shared server/browser boundary.
- Corrected scheduled-driver identity ordering so an already-invalid parser result retains its
  specific failure reason, but a `stale-running` log carrying the wrong driver name is normalized
  to `invalid` with the expected slot name before schedule handling. This removes a latent state
  that the stricter browser contract would correctly reject. A focused regression covers that
  path, and another regression prevents the backend and browser driver allowlists from drifting.
- The resulting tree passes all **1,652 warnings-as-errors Python tests**, all 33 UI contract tests,
  the production UI build, repository Ruff and `server tools` C901, Python, JavaScript, and shell
  compilation, frozen-lock validation, a fresh wheel build, environment compatibility, zero
  production npm vulnerabilities, documentation contracts, diff hygiene, and the empty-index
  gate. After restarting only the changed API, the complete `/meta` response remains byte-for-byte
  unchanged at 7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`; direct and proxied
  copies pass the browser validator and contain no home-directory path. Twelve direct read-only API
  routes and six UI pages/proxies return HTTP 200. Both services remain enabled and active with
  `NRestarts=0`; automation is converged at six managed entries with `Linger=yes`; and all five
  retained original/restored schema-v1/v2 recovery trees verify.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `c9e953bcafb93db9751dfa817d658b2f159aee4f7f88ddaf501281c3e021d965`, working-tree identity is
  `9b5abbccc24d324481ce69b9a33ace84ee5ae0fe7a52c5a165c8302a27394da7`, schedule-source identity
  is `b99f0dd3fb0b6895d3619bdafbc2b001d874391c7eb50a476f29586704c1b74e`, recovery-source identity
  is `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Current strategy evidence
  remains unchanged and unready; no search, tuning, gate, generated evidence, database row, broker
  connection, or capital state changed.
- Hardened the browser's host-status boundary to accept only the scheduler, Friday-postflight, and
  source-control states the backend can actually produce. Scheduler diagnostics now use the exact
  five production driver names and one auxiliary postflight name, require sorted unique known-name
  subsets, enforce exact 5+1 expected counts and coherent matched/missing/duplicate counts, derive
  UTC timezone consistency, and recompute `ok`, `unknown`, `inactive`, or `misconfigured` with the
  backend's precedence. Scheduler, postflight, and source-control invalid fallbacks use closed
  producer reason sets; invalid source-control fallbacks also require every repository identity and
  count field to be null. Positive fixtures cover every derived scheduler state, while negative
  fixtures reject invented names or reasons, duplicate diagnostics, wrong counts, contradictory
  timezones, and inconsistent statuses. The operating guide and its documentation regression record
  this fail-closed contract. Also corrected the preceding ledger's top-level `/meta` allowlist count
  from 29 to its actual 28 fields.
- The resulting tree passes all **1,653 warnings-as-errors Python tests**, all 33 UI contract tests,
  the production UI build, a fresh wheel build, zero production npm vulnerabilities, strict
  worktree ownership, diff hygiene, and the empty-index gate. After restarting only the changed UI,
  twelve read-only direct API requests and six UI pages/proxies return HTTP 200. Direct and proxied
  `/meta` remain byte-identical at 7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`, pass the source-tree
  browser validator, and expose no `/data00/home/` path. Both services remain enabled and active
  with `NRestarts=0`; the read-only automation plan is converged at six managed entries with
  `Linger=yes`; and all five retained original/restored schema-v1/v2 recovery trees verify.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `03d32c4c8317f8f35c8f6e0533d97e0a9e8ebfac64f10013d761b52b8d1f04ab`, working-tree identity is
  `971727104358670fa3188743272f80df3b0e592f480592d9578b6bfe6e62117c`, schedule-source identity
  remains `b99f0dd3fb0b6895d3619bdafbc2b001d874391c7eb50a476f29586704c1b74e`, recovery-source identity
  remains `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Strategy evidence remains
  an honest wait: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48, E1 is
  `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current at
  18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Closed the remaining browser/backend parity gap in Friday-postflight schedule geometry. The
  browser now derives the receipt slot from a validated Friday `expected_date`, requires that slot
  to be exactly the following Saturday at 05:15 UTC, pins `not-yet-run` to the monitor's actual
  first eligible slot, and rejects current or failed receipts checked before their slot. Stale
  receipts require both expected dates to be Fridays and their recorded check to be no earlier
  than the observed receipt's slot. Nightly start dates are compared after normalizing offset-aware
  timestamps to UTC, matching the Python producer instead of relying on the timestamp's literal
  date prefix. Regression fixtures accept an equivalent positive-offset instant and reject
  non-Friday dates, shifted schedule times or days, premature receipts, and an invented future
  first-run boundary. A cross-language regression binds the browser's weekday, hour, minute, and
  first-run constants to the Python producer. The operating guide records the exact browser-side
  invariant.
- The resulting tree passes all **1,654 warnings-as-errors Python tests**, all 33 UI contract tests,
  the production UI build, focused Ruff, a fresh wheel build, zero production npm vulnerabilities,
  strict worktree ownership, diff hygiene, and the empty-index gate. After restarting only the
  changed UI, twelve read-only direct API requests and six UI pages/proxies return HTTP 200. Direct
  and proxied `/meta` remain byte-identical at 7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`, pass the source-tree
  browser validator, and expose no `/data00/home/` path. Both services remain enabled and active
  with `NRestarts=0`; the read-only automation plan is converged at six managed entries with
  `Linger=yes`; and all five retained original/restored schema-v1/v2 recovery trees verify.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `f744a9299ca8160888a22d901df782bcbca81f5ce44db2f5f698e89ac44f94ae`, working-tree identity is
  `cdbdfe8db2cac74fe629f96eae8683ecdca63e8b13c2814835f6053efdcd9dea`, schedule-source identity
  remains `b99f0dd3fb0b6895d3619bdafbc2b001d874391c7eb50a476f29586704c1b74e`, recovery-source identity
  remains `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Strategy evidence remains
  unchanged and unready; no search, tuning, gate, generated evidence, database row, broker
  connection, or capital state changed.
- Centralized the public invalid-reason vocabularies in the scheduler, Friday-postflight, and
  source-control producers, and made their helper constructors reject undocumented reasons rather
  than emitting an unrecognized public state. Source-control `local-only` construction now has the
  same closed helper boundary for `no-upstream` and `tracking-ref-missing`; its successful payloads
  are unchanged. A cross-language regression now binds the browser to the backend's exact five
  scheduled driver names, one auxiliary name, scheduler invalid reasons, postflight invalid
  reasons, source-control invalid reasons, and source-control local-only reasons. Together with the
  existing schedule-constant parity test, future producer vocabulary or scheduling changes must
  update the browser contract in the same reviewed change.
- The resulting tree passes all **1,658 warnings-as-errors Python tests**, all 33 UI contract tests,
  the production UI build, repository Ruff and `server tools` C901, Python, JavaScript, and
  interpreter-aware shell compilation, frozen-lock validation, a fresh wheel build, zero
  production npm vulnerabilities, strict worktree ownership, diff hygiene, and the empty-index
  gate. After restarting both changed services, the complete `/meta` response is byte-for-byte
  unchanged at 7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`; direct and proxied
  copies pass the source-tree browser validator and expose no `/data00/home/` path. Twelve direct
  read-only API routes and six UI pages/proxies return HTTP 200. Both services remain enabled and
  active with `NRestarts=0`; automation is converged at six managed entries with `Linger=yes`; and
  all five retained original/restored schema-v1/v2 recovery trees verify.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `388c7d9b191beff77907ad6c3052db8f727d64b0f56d431bc97d69d387ec3f2b`, working-tree identity is
  `20a65b783106c69f42ec52519001f53ebfc3ee8e98f60a308e38951fa1b6f0a5`, schedule-source identity is
  `5c6e9faa64f3fb2991a68b9dc8614eb47197b53dfeb7e2d831e6fd4c2debf25f`, recovery-source identity
  remains `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Strategy evidence remains
  unchanged and unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48, E1 is
  `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current at
  18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Extended host-contract parity to all public scheduler, Friday-postflight, and source-control
  status vocabularies and to the only cron service units the backend probes, `cron` and `crond`.
  The browser now rejects invented unit names, an unidentified service paired with non-unknown
  active or boot state, and an identified unit paired with an unknown active probe. Backend cron
  probing uses the same named unit inventory, and the cross-language regression binds those units
  and all three status sets to their browser counterparts. Negative browser fixtures cover both
  invented units and contradictory null/unit combinations; a producer regression also keeps the
  unit inventory unique and ordered.
- The resulting tree passes all **1,659 warnings-as-errors Python tests**, all 33 UI contract tests,
  the production UI build, repository Ruff and `server tools` C901, Python, JavaScript, and
  interpreter-aware shell compilation, frozen-lock validation, a fresh wheel build, zero
  production npm vulnerabilities, strict worktree ownership, diff hygiene, and the empty-index
  gate. After restarting both changed services, the complete `/meta` response is byte-for-byte
  unchanged at 7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`; direct and proxied
  copies pass the source-tree browser validator and expose no `/data00/home/` path. Twelve direct
  read-only API routes and six UI pages/proxies return HTTP 200. Both services remain enabled and
  active with `NRestarts=0`; automation is converged at six managed entries with `Linger=yes`; and
  all five retained original/restored schema-v1/v2 recovery trees verify.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `69a0d8068267ebd242215676ce201971cf57a53b6ffdeca9e1092c7387e3d6c0`, working-tree identity is
  `0855ce5e7b2b3d1458bdb60b9d3dd3bf93fa42343e2c68cc6e5d5c4b50a77f0c`, schedule-source identity is
  `3d8922291fc4b5f39bfa2d0e5c6be11590479212fe3f9603d17b7d813a6348bb`, recovery-source identity
  remains `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Strategy evidence remains
  unchanged and unready; no search, tuning, gate, generated evidence, database row, broker
  connection, or capital state changed.
- Closed the remaining arbitrary-text path in scheduler host status. The backend now preserves the
  documented systemd active states (`active`, inactive/failure states, and transition states) and
  enablement states (enabled/runtime, linked/runtime, masked/runtime, static, indirect, disabled,
  generated, and transient), but normalizes empty or undocumented command output to `unknown`.
  The browser accepts exactly those normalized vocabularies plus the fail-closed sentinel, and a
  cross-language regression binds both sets to the Python producer. Focused host-probe regressions
  exercise invented active and enablement output, while browser regressions reject either value if
  it bypasses producer normalization. Legitimate degraded states remain visible to operators.
- The resulting tree passes all **1,661 warnings-as-errors Python tests**, all 33 UI contract tests,
  the production UI build, repository Ruff and `server tools` C901, Python, JavaScript, and
  interpreter-aware shell compilation, frozen-lock validation, a fresh wheel build, zero
  production npm vulnerabilities, strict worktree ownership, diff hygiene, and the empty-index
  gate. After restarting both changed services, the complete `/meta` response is byte-for-byte
  unchanged at 7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`; direct and proxied
  copies pass the source-tree browser validator and expose no `/data00/home/` path. Twelve direct
  read-only API routes and six UI pages/proxies return HTTP 200. Both services remain enabled and
  active with `NRestarts=0`; automation is converged at six managed entries with `Linger=yes`; and
  all five retained original/restored schema-v1/v2 recovery trees verify.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `8e414c2cae10546488dcb44cb50a0ffff4a0dcbcdbfa6de00c02beb3f64f55eb`, working-tree identity is
  `fd650cb93d05be70d0ddb36bfae97965f8dc4c601b6aaccf5c0dbc3214e32ecd`, schedule-source identity is
  `0b9ad42e7c9724b3345886240c0e63096ce43cea0a92c8b7fc36ce1e6377a539`, recovery-source identity
  remains `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Strategy evidence remains
  unchanged and unready; no search, tuning, gate, generated evidence, database row, broker
  connection, or capital state changed.
- Bounded the remaining public host-identity strings before they enter `/meta`. The shared host
  command layer now accepts only trimmed, nonempty, printable single lines under an explicit
  character budget. Scheduler timezone output is capped at 255 Unicode characters and malformed
  values normalize to `unknown`; Git branch, remote, merge-ref, and upstream output is capped at
  4,096 characters per value. A malformed branch maps to `branch-unavailable`, while malformed
  configured tracking values map to the new closed `tracking-identity-invalid` reason instead of
  being mislabeled as an absent upstream. The browser independently enforces the same single-line
  and size rules, and a cross-language regression binds both limits and the expanded reason set to
  the Python producers. Exact-limit positive cases and multiline, tab/NUL, blank, and oversized
  negative cases cover each boundary. The operating guide records the public limits and fail-closed
  mappings.
- The resulting tree passes all **1,680 warnings-as-errors Python tests** across 105 files, all 33
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python,
  JavaScript, and interpreter-aware shell compilation, frozen-lock validation, a fresh wheel
  build, zero production npm vulnerabilities, strict worktree ownership, diff hygiene, and the
  empty-index gate. After restarting the changed services, the complete `/meta` response remains
  byte-for-byte unchanged at 7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`; direct and proxied
  copies pass the source-tree browser validator and expose no `/data00/home/` path. Thirteen direct
  read-only API routes and six UI pages/proxies return HTTP 200. Both services remain enabled and
  active with `NRestarts=0`; automation is converged at six managed entries with `Linger=yes`; and
  all five retained original/restored schema-v1/v2 recovery trees verify.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `f863f604bc9236a8fbdf8ef89e4a23186b430a5d902a7e727cd606464cb2f7a7`, working-tree identity is
  `9adf049d59a29f6d942d939be40cb79cf8642de7bf72de3d3f2d87ceee77a98c`, schedule-source identity is
  `04685ee219713b4f90add9aa16f58e308d963dfdb9531e282736f1d1c2a1584d`, recovery-source identity
  remains `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Strategy evidence remains
  unchanged and unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48, E1 is
  `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current at
  18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Closed the numeric half of the source-control transport boundary. Git ahead/behind counts now
  fail closed as `tracking-count-invalid` when either exceeds `9,007,199,254,740,991`, the largest
  integer JSON consumers can represent exactly in JavaScript. The browser independently enforces
  that same ceiling, and cross-language parity binds it to the producer. Regressions accept the
  exact boundary and reject either field one above it, preventing a syntactically valid Python
  integer from being silently rounded into a different repository state in the UI.
- The resulting tree passes all **1,683 warnings-as-errors Python tests** across 105 files, all 33
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  JavaScript compilation, frozen-lock validation, a fresh wheel build, zero production npm
  vulnerabilities, strict worktree ownership, diff hygiene, and the empty-index gate. After
  restarting both changed services, `/meta` remains byte-for-byte unchanged at 7,911 bytes with
  SHA-256 `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`; direct and proxied
  copies pass the source-tree browser validator and expose no `/data00/home/` path. Thirteen direct
  read-only API routes and six UI pages/proxies return HTTP 200. Both services remain enabled and
  active with `NRestarts=0`, and automation remains converged at six entries with `Linger=yes`.
- Strict inventory remains 336 fully owned changed paths (102 tracked modifications and 234
  expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `41cc4a4a0bb6934c6efd58ae1ebdabb371ac67035d341f85047b741bc887349e`, working-tree identity is
  `1e529548a5977e81ed71a8caca4b56c8cf55c7639312e5c9593e3c5293af3334`, schedule-source identity
  remains `04685ee219713b4f90add9aa16f58e308d963dfdb9531e282736f1d1c2a1584d`, recovery-source identity
  remains `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, and the protected
  111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. Strategy evidence remains
  unchanged and unready; no search, tuning, gate, generated evidence, database row, broker
  connection, or capital state changed.
- Hardened the public portfolio-identifier boundary without changing its documented data model.
  Portfolio IDs remain nonblank strings of at most 128 Unicode characters, but API projections and
  route parameters now additionally require canonical trimmed, printable, single-line text. The
  server validates IDs before opening DuckDB where possible and validates every relational or JSON
  object key emitted by league, equity, position, order, journal, and stale-exposure projections.
  Invalid stored keys fail the affected projection instead of being truncated, silently omitted,
  or rewritten; this avoids collisions between distinct portfolio records. The browser applies the
  same shared 128-character contract to every consuming surface, with a cross-language regression
  binding its limit to the Python producer. Exact-limit Unicode IDs remain valid, while blank,
  padded, control-character, and oversized IDs are covered at utility, projection, route, and UI
  boundaries. The operating guide records the contract and failure semantics.
- The resulting tree passes all **1,707 warnings-as-errors Python tests** across 106 files, all 34
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python,
  JavaScript, and shell compilation, frozen-lock validation, a fresh wheel build, zero npm
  vulnerabilities, strict worktree ownership, diff hygiene, and the empty-index gate. After a
  controlled API/UI restart, oversized route IDs fail with HTTP 422 before database access and
  `/meta` remains byte-for-byte unchanged at 7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`; direct and proxied
  copies are identical, pass the source-tree browser validator, and expose no `/data00/home/`
  path. Thirteen direct read-only API routes and six UI pages/proxies return HTTP 200. Both services
  remain enabled and active with `NRestarts=0`; automation is drift-free at six managed entries
  with `Linger=yes`; and all five retained original/restored schema-v1/v2 recovery trees verify.
- Strict pre-ledger inventory contains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `6be2732763c7a7c234b10908d7c57acdfe0fe04ea53cda82e2a09faab2d0b885`, working-tree identity is
  `bb0e82053acdd3d06c33e801a0e557b141067ee950887e9022f29332182190dc`, and schedule-source
  identity is `7fd28dbb07fb026fca81d60ed21d488d09de605a952ef9a90e83da59d835efe7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
- Closed the corresponding public ticker-identity boundary while preserving the intentionally
  broad symbol model. Tickers remain case-normalized at request/ticket admission and may contain
  any route-encodable printable text, but they must now be canonical trimmed, nonblank, printable
  single lines of at most 32 Unicode characters. The server applies that shared rule before a
  candidate route opens DuckDB and to database-backed ticker keys crossing screen, candidate,
  position, order, journal fill/round-trip/event, stale-exposure, and active-quarantine projections.
  Invalid stored keys fail the affected projection without truncation or database rewriting; in
  particular, quarantine identity keys are no longer clipped into potentially colliding values,
  while their descriptive reason/evidence fields retain bounded clipping. Browser contracts reuse
  the same printable-line primitive on every consuming surface, and a cross-language regression
  binds the 32-character limit to the Python producer. Focused regressions cover exact-limit
  Unicode text, padding, controls, oversize values, route-before-database rejection, and unchanged
  malformed rows. The operating guide records the shared contract and fail-closed semantics.
- The resulting tree passes all **1,729 warnings-as-errors Python tests** across 106 files, all 34
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python,
  JavaScript, and shell compilation, frozen-lock validation, a fresh wheel build, zero production
  npm vulnerabilities, strict worktree ownership, diff hygiene, and the empty-index gate. After a
  controlled API/UI restart, malformed ticker route forms fail with HTTP 422 before database access
  and `/meta` remains byte-for-byte unchanged at 7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`; direct and proxied
  copies are identical, pass the source-tree browser validator, and expose no `/data00/home/`
  path. Thirteen direct read-only API routes and six UI pages/proxies return HTTP 200. Both services
  remain enabled and active with `NRestarts=0`; automation is drift-free at six managed entries
  with `Linger=yes`; and all five retained original/restored schema-v1/v2 recovery trees verify.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `9ea3fd607558c1976f83bbd1ebeb2068b8263ef57e9ce68e7d19b4db94f0d4a7`, working-tree identity is
  `d934ed53231570558da82e4d2c8f6cb609ee55673558c65ef49cafae3da272bc`, and schedule-source
  identity remains `7fd28dbb07fb026fca81d60ed21d488d09de605a952ef9a90e83da59d835efe7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Closed the shared public-integer transport boundary at `9,007,199,254,740,991`, the largest
  integer represented exactly by interoperable JSON and JavaScript. Queue failure/latest-job,
  scheduled miner, recurring-sweep, Friday-postflight, paper order/ticket/fill-event, and stale
  pending-order identifiers now fail their affected backend projection when stored outside the
  positive safe range. The cancellation route advertises and enforces the same maximum before
  opening DuckDB, while the transaction-layer entry point independently validates both its direct
  ticket ID and the stored linked order ID. New paper orders and tickets may allocate the exact
  maximum; an exhausted or malformed ledger maximum becomes a controlled 503 only after the whole
  portfolio/order/ticket/audit transaction rolls back. No stored row is clipped or rewritten.
  Browser integer predicates and bounded-collection metadata use `Number.isSafeInteger`, direct
  market/research checks follow the same rule, and source-control tracking counts now reuse the
  shared backend/browser constants. The operating guide records the limit and failure semantics.
  The two previously completed portfolio/ticker ledger units were also moved intact to the end of
  this chronological log before this entry.
- The resulting tree passes all **1,759 warnings-as-errors Python tests** across 106 files, all 34
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python,
  non-JSX JavaScript, and shell compilation, frozen-lock validation, a fresh wheel build, zero
  production npm vulnerabilities, documentation contracts, strict worktree ownership, diff
  hygiene, and the empty-index gate. After a controlled API/UI restart, an oversized cancellation
  ID returns HTTP 422, `/meta` remains byte-for-byte unchanged at 7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`, and direct/proxied
  copies are identical and pass the source-tree browser validator. Thirteen direct read-only API
  routes and six UI pages/proxies return HTTP 200. Both services remain enabled and active with
  `NRestarts=0`; automation is drift-free at six managed entries with `Linger=yes`; and all five
  retained original/restored schema-v1/v2 recovery bundles verify.
- Strict pre-ledger inventory contains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `43d247acb97e1a125095aa7aa86923529a8a94b9f650f8163eaff3b97bb58298`, working-tree identity is
  `d8879653e341ddcaa05830bae85320eddb479312a3e7e18a83a6a137a3438116`, and schedule-source
  identity is `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Paper state remains 479 jobs, 1,120 orders, 1,039 fills, seven tickets, zero active jobs, and 56
  pending orders. Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is
  `WAITING` at 0/48, E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic,
  walk-forward evidence is current at 18/18, and recurring sweeps are idle with no open charter.
  No search, tuning, gate, generated evidence, database row, broker connection, or capital state
  changed.
- Closed the public-count half of the interoperable JSON boundary. A shared backend validator now
  accepts only exact integers from zero through `9,007,199,254,740,991` and rejects booleans,
  floats, negatives, nulls, and oversized values without coercion. Screen totals, bounded
  position/order/journal counts, ticket-fill and league-event counts, league position/fill totals,
  single/bulk equity counts, queue state/failure counts, quarantine totals, research-readiness
  aggregates, nightly projection counts, liquidity store/evidence totals, price-verification
  counts, and miner evidence counts now apply that contract before pagination arithmetic or public
  serialization. Positive IDs retain their separate stricter `1..MAX_SAFE_INTEGER` contract. The
  nightly check is deliberately applied at `/meta` composition rather than importing support code
  into the recovery-sensitive monitor closure. The operating guide records the nonnegative range
  and fail-closed behavior.
- The resulting tree passes all **1,781 warnings-as-errors Python tests** across 106 files, all 34
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python,
  non-JSX JavaScript, and shell compilation, frozen dev-lock validation, a fresh wheel build, zero
  production npm vulnerabilities, documentation/route integration contracts, strict worktree
  ownership, diff hygiene, and the empty-index gate. After a controlled API/UI restart, `/meta`
  remains byte-for-byte unchanged at 7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`; direct/proxied copies
  are identical, pass the source-tree browser validator, and expose no `/data00/home/` path.
  Thirteen direct read-only API routes and six UI pages/proxies return HTTP 200. Both services are
  enabled and active with `NRestarts=0`; automation is drift-free at six managed entries with
  `Linger=yes`; and all five retained original/restored schema-v1/v2 recovery bundles verify.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `d1f2f694e88ee0de4671aedbe763985b1f962afa156d050f6f0ad84889b1c838`, working-tree identity is
  `85a21e9c0322fd4c0499c473f6a7da73e016cfd7741e12bc328e1fac6ffe5504`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Paper state remains 479 jobs, 1,120 orders, 1,039 fills, seven tickets, 1,792 audit rows, 29
  portfolios, zero active jobs, and 56 pending orders. Strategy evidence remains unready: Sector
  is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48, E1 is `ACCUMULATING` at 7/40 with negative
  mean and t-statistic, walk-forward evidence is current at 18/18, and recurring sweeps are idle
  with no open charter. No search, tuning, gate, generated evidence, database row, broker
  connection, or capital state changed.
- Closed the equity-history row boundary shared by the single-book and bulk League projections.
  Every serialized point now requires its canonical expected portfolio identifier, a real calendar
  date no later than the response `as_of`, finite equity and cash values, and a nonnegative
  JSON-safe `n_positions` value; dates within each book must remain strictly increasing. The
  browser contract independently requires finite cash and safe position counts in addition to its
  existing portfolio/date/equity/order checks. Malformed stored or query-derived rows fail the
  affected projection without clipping, omission, or database rewriting. The operating guide now
  states the complete point-level contract.
- The resulting tree passes all **1,788 warnings-as-errors Python tests** across 106 files, all 34
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python,
  non-JSX JavaScript, and shell compilation, frozen dev-lock validation, a fresh wheel build, zero
  production npm vulnerabilities, documentation/route integration contracts, strict worktree
  ownership, diff hygiene, and the empty-index gate. The active database has 781 equity rows,
  zero rows with non-finite equity/cash or negative position counts, and a maximum stored position
  count of 50. After a controlled API/UI restart, direct League and bulk-equity payloads pass the
  source-tree browser contracts; `/meta` remains byte-for-byte unchanged at 7,911 bytes with
  SHA-256 `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f` and matches its
  proxied copy. Thirteen direct read-only API routes and six UI pages/proxies return HTTP 200. Both
  services remain enabled and active with `NRestarts=0`; automation is drift-free at six managed
  entries with `Linger=yes`; and all five retained original/restored schema-v1/v2 recovery bundles
  verify.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `0272b4a0b02a66b89a51f07f670669dd7b6c33137ab332676b65e86840354c9d`, working-tree identity is
  `914ea568dfad345d6b68d6e5b97af8041506b3c1d47ec0e17571225d6e81b916`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Paper state remains 479 jobs, 1,120 orders, 1,039 fills, seven tickets, 1,792 audit rows, 29
  portfolios, zero active jobs, and 56 pending orders. Strategy evidence remains unready: Sector
  is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48, E1 is `ACCUMULATING` at 7/40 with negative
  mean and t-statistic, walk-forward evidence is current at 18/18, and recurring sweeps are idle
  with no open charter. No search, tuning, gate, generated evidence, database row, broker
  connection, or capital state changed.
- Closed the remaining market/position numeric gap between the read-only API producers and their
  browser contracts. Shared read-model primitives now reject booleans, non-numeric values,
  non-finite values (including Python integers too large for a finite float), and nonpositive or
  negative domain values as appropriate; League equity rows reuse that common finite-number
  primitive instead of carrying a duplicate implementation. Screen rows now require their exact
  run date, a positive finite close, exact ranks in `1..99`, exact template scores in `0..8`, finite
  distance metrics, real booleans, and a recognized universe policy. Candidate bars require exact,
  strictly increasing dates through `as_of`, positive finite OHLC, coherent high/low geometry, and
  finite nonnegative volume; any latest quote must exactly match its returned bar, and candidate
  screen context reuses the same screen-row validator. Screen page numbers and derived offsets must
  remain exact JSON-safe integers.
- Active position rows now require positive finite quantity and average cost, optional closes and
  discretionary stops require positive finite values, and every computed valuation/P&L/risk field
  must remain finite. The query continues to omit zero-quantity simulator tombstones as closed
  positions, but no longer silently omits negative, null, or non-finite quantities. Malformed stored
  values fail the affected projection without clipping, omission, or database rewriting. Focused
  regressions cover shared-number boundaries, malformed stored rows, screen rank/score/boolean and
  metric domains, bar ordering/OHLC/volume, exact quote coherence, position inputs, and overflowed
  derived values. The source-tree browser suite independently exercises the corresponding screen,
  candidate, position, cost, quantity, volume, and stop boundaries.
- The resulting tree passes all **1,845 warnings-as-errors Python tests** across 106 files, all 34
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python,
  non-JSX JavaScript, and shell compilation, frozen dev-lock validation, a fresh wheel build, zero
  production npm vulnerabilities, documentation/route integration contracts, strict worktree
  ownership, diff hygiene, and the empty-index gate. Source-tree projections validate all 532
  current screen passers, 275 returned active positions, and a 250-bar healthy candidate. The
  database contains no malformed active position or screen rows. It does contain 369 pre-existing
  Yahoo OHLC rows across 358 tickers that violate the browser's long-standing bar geometry contract;
  five symbols on the first current screen page (`CXW`, `DK`, `ECO`, `FRO`, and `PARR`) expose this
  debt. Their candidate APIs now fail closed and their UI pages visibly report the read failure;
  no source row was changed, omitted, or rewritten.
- After a controlled API/UI restart, 13 direct read-only API routes and six healthy UI/proxy
  surfaces return HTTP 200. Live meta, screen, candidate, positions, League, and bulk-equity JSON
  pass the source-tree browser validators. `/meta` remains byte-for-byte unchanged at 7,911 bytes
  with SHA-256 `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`
  and matches its proxied copy. Both services remain enabled and active with `NRestarts=0`;
  automation is drift-free at six managed entries with `Linger=yes`; and all five retained
  original/restored schema-v1/v2 recovery bundles verify.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `2c713b505c4332f4eb7e837e6572a0e4962cb2b42dd49845f5747deb4dec0b62`, working-tree identity is
  `24a115b514e14d7ddff5e7b17faf3abaa1e3a9e460c695d2af247460be0fb76a`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Paper state remains 479 jobs, 1,120 orders, 1,039 fills, seven tickets, 1,792 audit rows, 29
  portfolios, zero active jobs, and 56 pending orders. Strategy evidence remains unready: Sector
  is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48, E1 is `ACCUMULATING` at 7/40 with negative
  mean and t-statistic, walk-forward evidence is current at 18/18, and recurring sweeps are idle
  with no open charter. No search, tuning, gate, generated evidence, database row, broker
  connection, or capital state changed.
- Closed the order/journal producer gap against the existing browser contracts. Active-book order
  rows now require unique positive JSON-safe IDs, canonical portfolio/ticker identities, known
  side/status values, positive finite quantity, real signal dates, status-coherent rejection
  reasons, optional safe ticket links, string-or-null playbooks, and positive finite attached stops
  and targets. Journal tickets now require known side/status values, positive finite quantity,
  finite optional entry/stop/target values, string-or-null display fields, real timestamps, and
  status-coherent order linkage. Nested ticket fills and active-book league events require valid
  sides/dates and positive finite quantity/price; nested fills must match their parent ticket's
  ticker and side. Projected round trips require positive finite quantity/prices and finite realized
  R. Existing display-only text clipping remains unchanged, while malformed ledger values fail the
  affected read without being rewritten.
- The resulting tree passes all **1,883 warnings-as-errors Python tests** across 106 files, all 34
  UI contract tests, repository documentation and route-integration contracts, and the empty-index
  gate. Live source-tree browser validators accept the unfiltered, pending, filled, rejected, and
  cancelled order projections plus the journal projection: the active books expose 1,013 matching
  orders (500 returned by the bounded unfiltered endpoint), seven discretionary tickets, zero
  closed discretionary round trips, and 932 League fill events. Thirteen direct read-only API
  routes and six UI/proxy surfaces return HTTP 200. `/meta` remains byte-for-byte unchanged at
  7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f` and matches its proxied
  copy. Both services remain enabled and active with `NRestarts=0`; the read-only automation audit
  is drift-free at six managed entries with `Linger=yes`; and all five retained original/restored
  schema-v1/v2 recovery bundles verify.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `7298271970d2deb29a3ba770194fabd701959271d4062b4fd309bfcb7a8425b3`, working-tree identity is
  `a346f843c44a3da33b6872eb4262612d606b527f14380651ac7eff347deeb60e`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Paper state remains 479 jobs, 1,120 orders, 1,039 fills, seven tickets, 1,792 audit rows, 29
  portfolios, zero active jobs, and 56 pending orders. Strategy evidence remains unready: Sector
  is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48, E1 is `ACCUMULATING` at 7/40 with negative
  mean and t-statistic, walk-forward evidence is current at 18/18, and recurring sweeps are idle
  with no open charter. No search, tuning, gate, generated evidence, database row, broker
  connection, or capital state changed.
- Closed the remaining League-standings and discretionary ticket-context producer gaps against
  their browser contracts. Shared read-model helpers now require exact calendar dates and
  nonblank display strings without rewriting them. Every visible League row requires a canonical
  portfolio ID, nonblank name and optional execution-profile ID, an exact inception/equity date,
  positive finite persisted initial capital when present, finite equity, and JSON-safe position
  and fill counts. Derived total return, SPY-relative return, drawdown, and five-session return must
  remain finite before ranking or serialization; a zero starting point makes the five-session
  return unavailable. The top-level League projection also requires an exact `as_of`, recognized
  regime, and positive finite reference notional. Single and bulk equity projections now reject a
  malformed `as_of` even when their returned series is empty.
- Ticket context now requires an exact optional market date, an actual boolean active flag,
  positive finite configured or current equity, positive finite risk constants, `risk_pct <= 1`,
  and `experiment_max_pct <= risk_pct`. No market date remains explicitly `unavailable`; an
  inactive book or unusable active equity remains unavailable for sizing. Malformed dates, flags,
  or constants fail the projection. Focused regressions cover malformed portfolio metadata,
  non-finite source and derived League values, invalid comparison returns/regimes, zero-start
  recent returns, malformed equity `as_of` values, ticket-context status/date coherence, and risk
  limits. Invalid stored values are neither clipped, omitted when they would be public, nor
  rewritten.
- The resulting tree passes all **1,912 warnings-as-errors Python tests** across 106 files, all 34
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python,
  non-JSX JavaScript, and shell compilation, frozen dev-lock validation, a fresh wheel build, zero
  production npm vulnerabilities, documentation/route integration contracts, strict worktree
  ownership, diff hygiene, and the empty-index gate. The active store has 21 visible active books
  and 708 active-book equity points, with no malformed active portfolio metadata, non-finite or zero
  equity, or duplicate portfolio/date checkpoints. After an API-only restart, deployed League,
  bulk-equity, and ticket-context payloads pass the source-tree browser validators. Thirteen direct
  read-only API routes and six UI/proxy surfaces return HTTP 200. `/meta` remains byte-for-byte
  unchanged at 7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f` and matches its proxied
  copy. Both services remain enabled and active with `NRestarts=0`; automation is drift-free at six
  managed entries with `Linger=yes`; and all five retained original/restored schema-v1/v2 recovery
  bundles verify.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `436329d3099cc0ef47d6b7c35924e0cbb214f296d9cfbcccd6d4256fa3e52a1b`, working-tree identity is
  `29a10aff5e06806128b253c4aaee35da8782875c7c42f6c6f42e66cc2d479f10`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Paper state remains 479 jobs, 1,120 orders, 1,039 fills, seven tickets, 1,792 audit rows, 29
  portfolios, zero active jobs, and 56 pending orders. Research readiness has no ready family and
  `automatic_action` remains `none`; strategy evidence remains unready. No search, tuning, gate,
  generated evidence, database row, broker connection, or capital state changed.
- Closed the mutation-response producer boundary without exercising a live write. Ticket submission
  now validates its positive JSON-safe ticket/order IDs, exact signal date, boolean decision,
  nonempty valid gate list, string reason list, and accepted/rejected status coherence after all
  writes are assembled but before the transaction commits. Cancellation similarly validates the
  requested ticket identity, linked order ID, and cancelled status before commit. Review completion
  requires its exact success/kind values, a timezone-aware timestamp with an interoperable offset,
  and nonblank detail before committing its marker and audit row. The browser now also rejects
  timezone-less review-success timestamps. Any malformed internal success result rolls back the
  complete portfolio/order/ticket/audit or review-marker transaction instead of committing state
  that the UI must reject.
- Focused in-memory regressions prove rollback for empty/non-object/malformed gates, incoherent
  accepted and rejected decisions, non-string reasons, non-date signal results, invalid
  cancellation results, invalid review results, and timezone-less review timestamps. The resulting
  tree passes all **1,924 warnings-as-errors Python tests** across 106 files, all 34 UI contract
  tests, the production UI build, repository Ruff and `server tools` C901, Python, non-JSX
  JavaScript, and shell compilation, frozen dev-lock validation, a fresh wheel build, zero
  production npm vulnerabilities, documentation/route integration contracts, strict worktree
  ownership, diff hygiene, and the empty-index gate.
- After controlled API/UI restarts, all 13 direct read-only API routes and six UI/proxy surfaces
  return HTTP 200 and their source-tree browser validators pass. No live mutation route was called.
  The paper ledger remains exactly 479 jobs, 1,120 orders, 1,039 fills, seven tickets, 1,792 audit
  rows, zero review markers, 29 portfolios, zero active jobs, and 56 pending orders. `/meta` remains
  byte-for-byte unchanged at 7,911 bytes with SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f` and matches its proxied
  copy. Both services remain enabled and active with `NRestarts=0`; automation is drift-free at six
  managed entries with `Linger=yes`; and no recovery source changed after all five retained
  original/restored schema-v1/v2 bundles last verified.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `08d0ed8f6c7026a4c7999e995924768d0d8179f907fb96e9858460fbd012d6e0`, working-tree identity is
  `733d9104641f8bef670f9eb2ff7ef8368102b2b563814ae04cb02c28e8370073`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Research readiness has no ready family and `automatic_action` remains `none`; strategy evidence
  remains unready. No search, tuning, gate, generated evidence, database row, broker connection, or
  capital state changed.
- Closed the `/research/readiness` producer/browser contract boundary without changing any
  admission threshold. The backend now validates positive JSON-safe thresholds, the finite `(0,
  1]` intraday bar-coverage fraction, exact configured input-schema diagnostics, nonnegative safe
  aggregate counts, observed/qualifying date bounds, calendar spans, breadth relationships,
  per-interval key sets, family status derivation, and the sorted top-level `ready_families`
  summary before returning a projection. Missing or invalid schemas may no longer carry stale
  nonzero coverage. The browser independently enforces the same relationships, including exact
  known table/column diagnostic names and qualifying ranges contained by observed ranges.
- Added adversarial Python and browser regressions for unsafe/boolean/zero thresholds, non-finite
  or out-of-range fractions, invented schema diagnostics, contradictory missing-input coverage,
  impossible date spans, extra intraday intervals, and invented ready summaries. The operating
  guide now documents this fail-closed boundary and explicitly preserves the distinction between
  data admission and evidence of profit.
- The resulting tree passes all **1,935 warnings-as-errors Python tests** across 106 files, all 34
  UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python,
  non-JSX JavaScript, and shell compilation, frozen dev-lock validation, a fresh wheel build, and
  Python/npm production dependency audits with no known vulnerabilities. After controlled API/UI
  restarts, all 13 read-only API routes and six UI/proxy surfaces return HTTP 200. The live
  readiness response remains byte-for-byte unchanged at 3,047 bytes with SHA-256
  `dbc5d1647d5977be79eaded93580a460b51ff91a2f77fa3ccf8de61cec389a68` and passes the stricter
  source-tree browser validator.
- The live gate remains non-promotional and unready: stock selection is 41/756 qualifying dates,
  fundamentals is 9/156 snapshots, intraday is 47/252 1m sessions and 100/252 5m sessions,
  `ready_families=[]`, and `automatic_action=none`. No mutation route was called. Paper state still
  matches the preceding verified baseline at 479 jobs, 1,120 orders, 1,039 fills, seven tickets,
  1,792 audit rows, zero review markers, 29 portfolios, zero active jobs, and 56 pending orders.
  Both services are active/enabled with `NRestarts=0`; automation is converged at six managed
  entries with `Linger=yes`.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `fd9cfba464f473116f1d448101583f0a80990bc62b0a7936391852ef10f38e61`, working-tree identity is
  `daec9bea58e0985ca65f5bf8cc35082ffae730e4764dfb946c79f30f1ca303a8`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
- Closed the screen/candidate producer boundary without changing screening or strategy logic. The
  API now validates each final screen page for its exact envelope and row fields, positive
  JSON-safe page limit, coherent full/page counts, exact offset and page count, boolean pagination
  flags, unique rank/ticker ordering, and page-local `new_today` count. Candidate responses now
  require an exact envelope and exact bar fields, one through 250 ordered bars, a complete optional
  quote date/value pair matching a returned bar, and a same-ticker, not-future attached screen row.
  The browser independently rejects extra envelope/bar fields and histories beyond the producer's
  fixed 250-bar bound.
- Added adversarial regressions for incoherent screen headers, pagination, flags, duplicate rows,
  invalid page/bar limits, extra candidate fields, mismatched bar counts, and incomplete quotes.
  The operating guide now states the final producer validation and exact 250-bar candidate bound.
  The resulting tree passes all **1,948 warnings-as-errors Python tests** across 106 files, all 34
  UI contract tests, production UI build, Ruff and `server tools` C901, Python/non-JSX
  JavaScript/shell compilation, frozen dev-lock validation, a fresh wheel build, and zero known npm
  production vulnerabilities.
- After controlled API/UI restarts, all 13 read-only API routes and six UI/proxy surfaces return
  HTTP 200. The live first screen page and `ANRO` candidate remain byte-for-byte unchanged across
  deployment and pass the stricter browser contracts: screen SHA-256
  `e9ef330204bd100fa46b37760fbe63b2353a6b29c9c2c965a93d8e6985971cbe`; 250-bar candidate
  SHA-256 `3e81ed55828d94e27dc9d58b700c98aea3e5e7627d26d2d0cacddf214d964e8e`.
  No mutation route was called. Paper state remains 479 jobs, 1,120 orders, 1,039 fills, seven
  tickets, 1,792 audit rows, zero review markers, 29 portfolios, zero active jobs, and 56 pending
  orders. Both services are active/enabled with `NRestarts=0`; automation remains converged at six
  entries with `Linger=yes`.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `d61d5d9fa4d1b322e1545cea45db4a36e5a0a9a46851505c79eca108d2dc7b12`, working-tree identity is
  `35e4a62bfc60bd07c6fdd6f726adae758927d2384bae1d1605665522a0970a2e`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
- Completed the exact-schema follow-up for `/research/readiness`. The backend and browser now reject
  missing or unreviewed fields in the top-level projection and all three family objects, while
  retaining exact interval-key and configured input-schema diagnostics. The public notice,
  limitations, and usable-observation rules must also contain nonblank text. This closes silent
  response expansion without changing a threshold, coverage calculation, status, or response byte.
- Added backend and browser regressions for extra top-level/family fields and blank explanatory
  text. The resulting tree passes all **1,956 warnings-as-errors Python tests** across 106 files,
  all 34 UI contract tests, the production UI build, repository Ruff and `server tools` C901,
  Python/non-JSX JavaScript compilation, frozen dev-lock validation, a fresh wheel build, and zero
  known npm production vulnerabilities. After API/UI restart, the 3,047-byte readiness response is
  unchanged at SHA-256 `dbc5d1647d5977be79eaded93580a460b51ff91a2f77fa3ccf8de61cec389a68`,
  passes the stricter source-tree browser contract, reports `ready_families=[]`, and retains
  `automatic_action=none`.
- Core read-only API routes and six UI/proxy surfaces return HTTP 200. No mutation route was called;
  paper state remains 479 jobs, 1,120 orders, 1,039 fills, seven tickets, 1,792 audit rows, zero
  review markers, 29 portfolios, zero active jobs, and 56 pending orders. Both services remain
  active/enabled with `NRestarts=0`; automation is converged at six entries with `Linger=yes`.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `2e4e2550128eec916e36e78321b8c33ca4752a47aef33a6188e0c4e956c92652`, working-tree identity is
  `88459d24e2a6deb15e5e4161590d44d104ea5847506b11d232decd931523e2f4`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Corrected the ledger chronology by moving the completed exact-schema `/research/readiness` unit
  after the screen/candidate unit at true EOF. Then closed the next demonstrated read-boundary gap:
  league, single-book equity, and bulk-equity producers now validate their exact reviewed envelope
  and row fields before returning data, and the browser independently rejects extra standings,
  bulk-envelope, and nested equity-row fields. Final producer checks also enforce coherent bounded
  counts, truncation flags, active-book key sets, dates, rank typing/order, and finite public values.
  This prevents accidental internal-field exposure without changing ranking, selection, limits,
  strategy logic, or stored state. The operating guide records the exact-schema boundary.
- Added adversarial Python and browser regressions for unreviewed league/equity fields. The resulting
  tree passes all **1,959 warnings-as-errors Python tests**, all 34 UI contract tests, the production
  UI build, repository Ruff and `server tools` C901, Python and non-JSX JavaScript compilation,
  documentation tests, diff hygiene, and the empty-index gate. After controlled API/UI restarts,
  direct read-only API routes and all six UI/proxy surfaces sampled return HTTP 200, both services
  remain active/enabled with `NRestarts=0`, and automation is drift-free at six managed entries
  with `Linger=yes`.
- The deployed league and bulk-equity responses are byte-for-byte unchanged and pass the stricter
  source-tree contracts: league is 8,118 bytes at SHA-256
  `52335f774aab4fdacb7c675f909b07f94d15cc60c3148a55fa276c5ce117029c`; bulk equity is 87,306
  bytes at SHA-256 `673f88e7c7812c8f8ff47273f28c83238d661652685275c8c68b9c3a272bad10`.
  `/meta` remains `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`, and readiness remains
  `dbc5d1647d5977be79eaded93580a460b51ff91a2f77fa3ccf8de61cec389a68` with no ready family and
  `automatic_action=none`. No mutation route was called. Paper state remains 479 jobs, 1,120
  orders, 1,039 fills, seven tickets, 1,792 audit rows, zero review markers, 29 portfolios, zero
  active jobs, and 56 pending orders.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `5a30dc15290ae991ee538f7aad0a6583980567fd24ec475400dd15bcadef9d8a`, working-tree identity is
  `2fe5531aaac109c178d0ce71d47fa08ce4bc0ce04d1ae76d397077771b4d5d54`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Closed the positions/orders exact-schema boundary without changing selection, valuation, filter,
  or truncation behavior. The producers now validate each final response envelope and every
  conditional position/order row shape after assembly. Position rows admit valuation fields only
  with a quote and risk fields only for the discretionary book in the applicable stop/quote state;
  they also require unique deterministic portfolio/ticker order and coherent derived values. Order
  rows require the exact reviewed fields, descending unique IDs, coherent bounded metadata, and a
  truthful display-text truncation marker. The browser independently enforces the same exact
  envelope and conditional row schemas, and the operating guide records the boundary.
- Added adversarial Python and browser regressions for extra envelope/row fields, fields from the
  wrong position state, unordered orders, and false truncation claims. The resulting tree passes all
  **1,964 warnings-as-errors Python tests**, all 34 UI contract tests, the production UI build,
  repository Ruff and `server tools` C901, Python and non-JSX JavaScript compilation, documentation
  tests, diff hygiene, and the empty-index gate. After controlled service restarts, all sampled
  read-only API and UI/proxy routes return HTTP 200, both services remain active/enabled with
  `NRestarts=0`, and automation remains drift-free at six managed entries with `Linger=yes`.
- The deployed projections are byte-for-byte unchanged and pass the stricter source-tree browser
  contracts: positions is 65,539 bytes at SHA-256
  `184582603ce7385f6016199868d6345324aa5ab6e32872b0c52a4986cb0d94e0`; orders is 124,414 bytes
  at SHA-256 `13e7f30c58ebef1344827b066025b48b117cc1d0a49ce22a3c0067c918ea7d12`.
  `/meta` remains `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`, and readiness remains
  `dbc5d1647d5977be79eaded93580a460b51ff91a2f77fa3ccf8de61cec389a68` with no ready family and
  `automatic_action=none`. No mutation route was called. Paper state remains 479 jobs, 1,120
  orders, 1,039 fills, seven tickets, 1,792 audit rows, zero review markers, 29 portfolios, zero
  active jobs, and 56 pending orders.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `fda154a5c3e13a5ed0ee1dc4887c46c7be9221a769e2d8b6f811be197bbdcd23`, working-tree identity is
  `7be35cdbd9a1f953282f632ae459f8688bdfd746260278428f2b0191f5114be7`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Closed the journal exact-schema boundary without changing journal selection, risk-history, or
  truncation behavior. The producer now validates the exact top-level and discretionary envelopes,
  exact ticket, gate, nested-fill, round-trip, and league-event fields, fixed bounded limits and
  coherent counts, deterministic ticket/fill/event ordering, unique ticket IDs, finite values, and
  truthful ticket-text truncation after final assembly. The optional `gates_error` field remains a
  deliberate parse-failure disclosure, admitted only with an empty gate list and one of the three
  public codes. The browser independently enforces the same closed schemas and ordering; the
  operating guide records both the boundary and that admission is not profitability evidence.
- Added adversarial Python and browser regressions for extra fields at every envelope/row layer,
  invalid or unnecessary gate-error disclosure, and false truncation claims. The resulting tree
  passes all **1,972 warnings-as-errors Python tests**, all 34 UI contract tests, the production UI
  build, repository Ruff and `server tools` C901, Python and non-JSX JavaScript compilation,
  documentation tests, diff hygiene, and the empty-index gate. After controlled API/UI restarts,
  the direct API, Journal page, and proxied Journal route return HTTP 200; both services remain
  active/enabled with `NRestarts=0`, and automation is drift-free at six managed entries with
  `Linger=yes`.
- The deployed Journal response is byte-for-byte unchanged and passes the stricter source-tree
  browser contract: 23,937 bytes at SHA-256
  `25a0f080a221dd6e42c4172d604c43247712160c777937adc19576ea1013c243`.
  `/meta` remains `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`, and readiness remains
  `dbc5d1647d5977be79eaded93580a460b51ff91a2f77fa3ccf8de61cec389a68` with no ready family and
  `automatic_action=none`. No mutation route was called. Paper state remains 479 jobs, 1,120
  orders, 1,039 fills, seven tickets, 1,792 audit rows, zero review markers, 29 portfolios, zero
  active jobs, and 56 pending orders.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `793e5f977d379e7d8770f56d93771a8eb837260cc0454484a8b4cb215a9aa139`, working-tree identity is
  `c3fd0674546873dd3a06c037fa2409bd87c6008896627ee853a6b19997a539a2`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Closed the final module-level read-model producer gap by adding an exact eight-field validation
  boundary to discretionary ticket context. The producer now rechecks portfolio identity,
  recognized status, status-specific date/equity/source relationships, positive finite risk
  values, and the risk/experiment ordering after assembling the response. The browser independently
  requires the same exact envelope, so added or omitted backend fields fail visibly instead of
  silently becoming position-sizing input. No sizing formula, risk limit, status behavior, or
  stored state changed; every `server/*read_models.py` module now has a final projection validator.
- Added Python and browser regressions for extra and omitted ticket-context fields and the inactive
  versus unavailable date boundary. The resulting tree passes all **1,974 warnings-as-errors
  Python tests**, all 34 UI contract tests, the production UI build, repository Ruff and
  `server tools` C901, Python and non-JSX JavaScript compilation, documentation tests, diff hygiene,
  and the empty-index gate. After controlled API/UI restarts, the direct context route, Candidate
  page, and proxied context route return HTTP 200; both services remain active/enabled with
  `NRestarts=0`, and automation remains drift-free at six managed entries with `Linger=yes`.
- The deployed ticket-context response is byte-for-byte unchanged and passes the stricter
  source-tree browser contract: 207 bytes at SHA-256
  `a710d2e9b503e4611d86760db29dd05320010f8ee04aa34e089967b455827c51`.
  `/meta` remains `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`, and readiness remains
  `dbc5d1647d5977be79eaded93580a460b51ff91a2f77fa3ccf8de61cec389a68` with no ready family and
  `automatic_action=none`. No mutation route was called. Paper state remains 479 jobs, 1,120
  orders, 1,039 fills, seven tickets, 1,792 audit rows, zero review markers, 29 portfolios, zero
  active jobs, and 56 pending orders.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `68918e9ab4ab649d3e95f649709872ae87158b4a20bc2d087e5f55c33f38366f`, working-tree identity is
  `93abca06284299b4e7f48abc1f115581174853b9fa3170a08e562c33bf27fba4`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Closed the successful paper-mutation response boundary without changing any risk decision or
  write workflow. Ticket submission, cancellation, and review-completion producers now require
  their exact reviewed result fields before committing, and submitted risk-gate rows require the
  exact `name`/`status`/`detail` shape. The browser independently enforces those same exact result
  and gate schemas. Existing in-transaction validation therefore continues to roll back malformed
  internally assembled success responses instead of committing state the UI would reject.
- Added adversarial Python and browser regressions for extra submission, gate, cancellation, and
  review fields. The resulting tree passes all **1,977 warnings-as-errors Python tests**, all 34 UI
  contract tests, the production UI build, repository Ruff and `server tools` C901, Python and
  non-JSX JavaScript compilation, documentation tests, diff hygiene, and the empty-index gate.
  After controlled API/UI restarts, the sampled read-only API/UI surfaces return HTTP 200; both
  services remain active/enabled with `NRestarts=0`, and automation remains drift-free at six
  managed entries with `Linger=yes`. No live mutation route was called.
- `/meta`, readiness, Journal, and ticket context remain byte-for-byte unchanged at SHA-256
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`,
  `dbc5d1647d5977be79eaded93580a460b51ff91a2f77fa3ccf8de61cec389a68`,
  `25a0f080a221dd6e42c4172d604c43247712160c777937adc19576ea1013c243`, and
  `a710d2e9b503e4611d86760db29dd05320010f8ee04aa34e089967b455827c51`, respectively. Readiness
  still reports no ready family and `automatic_action=none`. Paper state remains 479 jobs, 1,120
  orders, 1,039 fills, seven tickets, 1,792 audit rows, zero review markers, 29 portfolios, zero
  active jobs, and 56 pending orders.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `c8c56b2b1ad1b4f530e8f4f59a511d4980f3670c2d3355150367467e8993a49a`, working-tree identity is
  `a1e859037f419c5cbabcb94442a27d1ff9647456df828a9d4786b54871a1db20`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Added a final runtime contract to `GET /health`, which already constructed and documented an
  exact three-field response. Before returning, the endpoint now requires exactly `ok`, `status`,
  and `db_readable`, recognizes only `ok`, `busy`, or `unreadable`, and requires both booleans to
  agree with readability. Focused regressions cover an added field and contradictory status; no
  database behavior or error disclosure changed.
- The resulting tree passes all **1,978 warnings-as-errors Python tests**, the immediately preceding
  complete 34-test UI suite and production UI build, repository Ruff and `server tools` C901,
  Python and non-JSX JavaScript compilation, documentation tests, diff hygiene, and the empty-index
  gate. After an API-only restart, direct and proxied health plus the dashboard return HTTP 200;
  both services remain active/enabled with `NRestarts=0`, and automation remains drift-free at six
  managed entries with `Linger=yes`.
- The deployed health response remains byte-for-byte unchanged at 44 bytes with SHA-256
  `7ca59d0b31f4d46c89b2e8c861b49b5b682cdffdbb1dfff2cfd6919398bef751`.
  `/meta` remains `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`, and readiness remains
  `dbc5d1647d5977be79eaded93580a460b51ff91a2f77fa3ccf8de61cec389a68` with no ready family and
  `automatic_action=none`. No mutation route was called. Paper state remains 479 jobs, 1,120
  orders, 1,039 fills, seven tickets, 1,792 audit rows, zero review markers, 29 portfolios, zero
  active jobs, and 56 pending orders.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `fca7f8e7a4c53e79a7883a76ee8a44fecdc480e33f65632ec65547950ea327c7`, working-tree identity is
  `602ce1f9155a5d135f55e3c04fe5d8b5f6cf0518e355e55f65a0c74f9ef7d9ef`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Bounded the remaining nested text and collection surface in successful ticket submissions. The
  producer and browser now admit at most 32 exact-shape gates and 32 nonblank reasons; gate names
  are capped at 128 characters, details at 4,096, and derived reason text at 4,241. These limits
  cover the existing fixed eleven-control response with margin and preserve every current risk
  decision. Producer validation remains inside the write transaction, so malformed internal output
  rolls back rather than being committed or exposed.
- Added adversarial backend/browser regressions for oversized gate names/details and blank or
  oversized reasons. The resulting tree passes all **1,981 warnings-as-errors Python tests**, all
  34 UI contract tests, the production UI build, repository Ruff and `server tools` C901, Python
  and non-JSX JavaScript compilation, documentation tests, diff hygiene, and the empty-index gate.
  After controlled API/UI restarts, sampled read-only API/UI surfaces return HTTP 200; both services
  remain active/enabled with `NRestarts=0`, and automation remains drift-free at six managed entries
  with `Linger=yes`. No live mutation route was called.
- Health, `/meta`, readiness, Journal, and ticket context remain byte-for-byte unchanged at SHA-256
  `7ca59d0b31f4d46c89b2e8c861b49b5b682cdffdbb1dfff2cfd6919398bef751`,
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`,
  `dbc5d1647d5977be79eaded93580a460b51ff91a2f77fa3ccf8de61cec389a68`,
  `25a0f080a221dd6e42c4172d604c43247712160c777937adc19576ea1013c243`, and
  `a710d2e9b503e4611d86760db29dd05320010f8ee04aa34e089967b455827c51`, respectively. Readiness
  still reports no ready family and `automatic_action=none`. Paper state remains 479 jobs, 1,120
  orders, 1,039 fills, seven tickets, 1,792 audit rows, zero review markers, 29 portfolios, zero
  active jobs, and 56 pending orders.
- Strict pre-ledger inventory remains 337 fully owned changed paths (102 tracked modifications and
  235 expanded untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths.
  Release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `f668244a94e7a275ec9c92e932a0c92ca7cbe47c2426c580a9e43a87d8d890b5`, working-tree identity is
  `2576261160d7fddd046b1ac86a26af6a68b11465dc69f94fb81507f62a38699c`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Corrected the shared UI transport's 503 classification: it now reports retryable database
  contention only for the exact public lock-error envelope or the exact coherent busy-health
  envelope. An unreadable-health 503, an unrelated service 503, or a widened lookalike remains a
  visible error instead of being falsely described as a nightly database lock. The helper also
  normalizes standard `HeadersInit` values, retains its JSON default when callers add headers, and
  still permits an explicit content-type override. No backend route, mutation, risk decision, or
  research behavior changed.
- Added direct transport regressions for both accepted busy envelopes, unreadable/unrelated/widened
  503s, structured FastAPI validation details, merged and overridden headers, and network failures.
  The operating guide now records the exact busy classification and request-header behavior. The
  resulting tree passes all **1,981 warnings-as-errors Python tests**, all 40 UI tests, the
  production UI build, repository Ruff and `server tools` C901, Python and non-JSX JavaScript
  compilation, shell syntax, documentation tests, diff hygiene, and the empty-index gate. After a
  UI-only restart, Dashboard, Journal, and proxied read-only routes return HTTP 200; both services
  remain active/enabled with `NRestarts=0`, and automation is drift-free at six managed entries
  with `Linger=yes`. No live mutation route was called.
- Health, `/meta`, readiness, Journal, and ticket context remain byte-for-byte unchanged at SHA-256
  `7ca59d0b31f4d46c89b2e8c861b49b5b682cdffdbb1dfff2cfd6919398bef751`,
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`,
  `dbc5d1647d5977be79eaded93580a460b51ff91a2f77fa3ccf8de61cec389a68`,
  `25a0f080a221dd6e42c4172d604c43247712160c777937adc19576ea1013c243`, and
  `a710d2e9b503e4611d86760db29dd05320010f8ee04aa34e089967b455827c51`, respectively. Readiness
  still reports no ready family and `automatic_action=none`. Paper state remains 479 jobs, 1,120
  orders, 1,039 fills, seven tickets, 1,792 audit rows, zero review markers, 29 portfolios, zero
  active jobs, and 56 pending orders.
- Strict pre-ledger inventory is 339 fully owned changed paths (103 tracked modifications and 236
  untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths. Release
  identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `671c580049b3d5256c97d43da54d987a9732a2b9a1b37109b0b673314cba3d89`, working-tree identity is
  `524af5f763fd8782db742d61dbca575c22f704cab51334523f672887c037c230`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `880d7f7f68b0039117403c3e0843b95687c5ac0f11e697786b45f7c692e9bdd9`, the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Bounded the remaining shared UI error surface. Plain text, structured `detail`, and network
  exception messages are normalized to one trimmed printable line and at most 4,096 Unicode
  characters. Structured validation responses admit only the first 16 issues, normalize valid
  string/integer location segments, replace malformed or over-deep locations with `request`, and
  reserve room for an explicit omission marker. The exact database-busy classification remains
  unchanged. Added direct browser regressions for oversized Unicode text, control/line separators,
  validation fan-out, guaranteed omission disclosure, malformed locations, and network text.
- Removed a real release-manifest flake discovered by the full suite. Secure DuckDB schema reads
  had treated ordinary lock/WAL child-entry churn as an attack because they compared mutable
  size/time metadata on the immediate database directory. They now retain full metadata checks for
  the database leaf and higher ancestors while requiring the immediate directory's device/inode
  identity to remain stable. Initial symlinks, leaf replacement or mutation, parent/ancestor
  substitution, and database appearance/change during the wider scan still fail closed. A new
  regression admits only benign immediate-directory metadata churn, and the formerly flaky schema
  and required-untracked cases each passed ten consecutive isolated runs before the complete suite.
- Updated the operating and contributor documentation for both boundaries. The resulting tree
  passes all **1,982 warnings-as-errors Python tests**, all 45 UI tests, the production UI build,
  repository Ruff and `server tools` C90, Python and non-JSX JavaScript compilation, shell syntax,
  documentation/release/source-contract tests, diff hygiene, and the empty-index gate. After a
  UI-only restart, Dashboard, Journal, and proxied read-only routes return HTTP 200; both services
  remain active/enabled with `NRestarts=0`, and automation is drift-free at six managed entries
  with `Linger=yes`. No live mutation route was called.
- Health, `/meta`, readiness, Journal, and ticket context remain byte-for-byte unchanged at SHA-256
  `7ca59d0b31f4d46c89b2e8c861b49b5b682cdffdbb1dfff2cfd6919398bef751`,
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`,
  `dbc5d1647d5977be79eaded93580a460b51ff91a2f77fa3ccf8de61cec389a68`,
  `25a0f080a221dd6e42c4172d604c43247712160c777937adc19576ea1013c243`, and
  `a710d2e9b503e4611d86760db29dd05320010f8ee04aa34e089967b455827c51`, respectively. Readiness
  still reports no ready family and `automatic_action=none`. Paper state remains 479 jobs, 1,120
  orders, 1,039 fills, seven tickets, 1,792 audit rows, zero review markers, 29 portfolios, zero
  active jobs, and 56 pending orders.
- Strict pre-ledger inventory remains 339 fully owned changed paths (103 tracked modifications and
  236 untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths. Release
  identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `ee0b70aa5a991b82823a5bc2ebb7895d38035a0e8042c3432f37d8bbf62ab64a`, working-tree identity is
  `dc922f320f1cec2d356f87fce16649b675d22e2bedcb031bd725dd5220a81051`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity changed as expected with the reviewed manifest implementation to
  `66c4032627397ab131a56ef58a883b0135f01cd60c02266721f98347de1c07e0`; the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Bounded the shared UI response reader before parsing. Direct server-component and proxied browser
  requests now admit at most 1 MiB of response bytes, reject an oversized numeric
  `Content-Length` before reading, and otherwise count streamed bytes and cancel as soon as the
  ceiling is crossed. A response exactly at the limit remains valid; an oversized success or error
  becomes a stable fail-visible result with no parsed data and cannot be mislabeled as database
  contention. Declared lengths use bounded lexical decimal comparison instead of attacker-sized
  integer parsing. This aligns the browser transport with the existing 1 MiB operational-artifact
  and postflight HTTP ceilings.
- Added direct transport regressions for the exact byte boundary, multibyte streamed overflow, and
  pre-read rejection/cancellation from declared length, and an attacker-sized length header. The
  resulting tree passes all **1,982 warnings-as-errors Python tests**, all 49 UI tests, repository
  Ruff and `server tools` C90, Python and non-JSX JavaScript compilation, shell syntax,
  documentation/release/source-contract tests, diff hygiene, and the empty-index gate. After a
  UI-only restart, Dashboard, Journal, and proxied read-only routes return HTTP 200; both services
  remain active/enabled with `NRestarts=0`, and automation is drift-free at six managed entries
  with `Linger=yes`. No live mutation route was called.
- Health, `/meta`, readiness, Journal, and ticket context remain byte-for-byte unchanged at SHA-256
  `7ca59d0b31f4d46c89b2e8c861b49b5b682cdffdbb1dfff2cfd6919398bef751`,
  `c43a029dd9d84c525e14ad88edb5106a7bf332b9edf283d15dff9b1b5c5fd66f`,
  `dbc5d1647d5977be79eaded93580a460b51ff91a2f77fa3ccf8de61cec389a68`,
  `25a0f080a221dd6e42c4172d604c43247712160c777937adc19576ea1013c243`, and
  `a710d2e9b503e4611d86760db29dd05320010f8ee04aa34e089967b455827c51`, respectively. Readiness
  still reports no ready family and `automatic_action=none`. Paper state remains 479 jobs, 1,120
  orders, 1,039 fills, seven tickets, 1,792 audit rows, zero review markers, 29 portfolios, zero
  active jobs, and 56 pending orders.
- Strict pre-ledger inventory remains 339 fully owned changed paths (103 tracked modifications and
  236 untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths. Release
  identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`. Current post-ledger identities are reported in the handoff rather
  than embedded self-referentially; schedule-source identity remains
  `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `66c4032627397ab131a56ef58a883b0135f01cd60c02266721f98347de1c07e0`; the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Extended the repository documentation-integrity gate from local target existence to local
  Markdown fragment validity. It now derives Unicode-aware GitHub-style IDs from ATX headings,
  handles duplicate-heading suffixes, ignores apparent headings inside backtick or tilde fenced
  code, checks same-document anchors, URL-decodes paths and fragments, and rejects paths that
  resolve outside the repository. The current documentation has one local fragment link and it
  resolves to the measured capital-sensitivity heading. A focused fixture proves a valid heading,
  a duplicate heading, and rejection of a fenced-code pseudo-heading. Also corrected the preceding
  build-log validation wording from the malformed “the `server tools` C90” phrase.
- The resulting tree passes all **1,983 warnings-as-errors Python tests**, the immediately
  preceding complete 49-test UI suite and production UI build, repository Ruff and `server tools`
  C90, Python and non-JSX JavaScript compilation, shell syntax, documentation/release/source-contract
  tests, diff hygiene, and the empty-index gate. No runtime restart was required for this test/docs
  unit; both services remain active/enabled with `NRestarts=0`, and automation remains drift-free
  at six managed entries with `Linger=yes`. Protected research, prospective evidence, schedule,
  paper ledger, broker, and capital state were not changed.
- Strict pre-ledger inventory remains 339 fully owned changed paths (103 tracked modifications and
  236 untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths. Release
  identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `5dbbf1373567437de57f3cfb4920382a73a7046abc11d292c56a84aac9690f2f`, working-tree identity is
  `3eeae9fa39c67cefcc323af15e6fde510f9cdad26d90f834489a0112af5f3445`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `66c4032627397ab131a56ef58a883b0135f01cd60c02266721f98347de1c07e0`; the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Reconciled the governing engine design's historical sibling-store language with the implemented
  exporter. The documented EOD window now covers the optional private watchlist plus the top 100
  passing names, matching `engine.screen`; it also states that passing names still export when the
  optional watchlist is absent. The template path is identified as private-sibling content, and
  §9 now explicitly records an unrealized 2026-07-16 sibling-integration plan rather than implying
  that its proposed skills or absent `DATA-SOURCES.md` file are current repository interfaces. A
  focused documentation contract pins these provenance and current-output boundaries.
- The resulting tree passes all **1,984 warnings-as-errors Python tests**, all 49 UI tests, the
  production UI build, repository Ruff and `server tools` C90, documentation tests, diff hygiene,
  and the empty-index gate. The read-only automation audit remains drift-free at six managed cron
  entries; both versioned services match their installed units and remain active/enabled with
  `NRestarts=0` and `Linger=yes`. No restart was required for this documentation/test-only unit.
- Strict pre-ledger inventory remains 339 fully owned changed paths (103 tracked modifications and
  236 untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths. Release
  identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `526c12ef531565d28fcd6c38b15f24950b38292aae2dd5e416d777e564b7a115`, working-tree identity is
  `064e8822a897b49f3e286491d2a068a4a07fb1bd8fd1a693d79a889bcd018b6b`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `66c4032627397ab131a56ef58a883b0135f01cd60c02266721f98347de1c07e0`; the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Made local-link validation ignore Markdown links shown inside fenced code examples, matching how
  rendered documentation treats those examples. The masker preserves every original character
  offset and newline, so diagnostics after a fence retain their exact source line. It supports
  backtick and tilde fences, longer closing runs, and CommonMark's requirement that a closing fence
  contain no trailing information text; a lookalike such as `````not-a-close`` remains inside the
  block. The focused fixture proves both fence styles, a false closer, a real missing link after the
  block, duplicate anchors, and fenced pseudo-headings.
- The complete **1,984-test warnings-as-errors Python suite**, repository Ruff and `server tools`
  C90, Python/non-JSX JavaScript and shell compilation, documentation checks, diff hygiene, and
  the empty-index gate pass. The immediately preceding 49-test UI suite and production build remain
  applicable because this refinement changes only the Python documentation test. The read-only
  automation audit remains `ok`: six managed cron entries, matching active/enabled API and UI
  units, and `Linger=yes`; no service restart was needed.
- Strict pre-ledger inventory remains 339 fully owned changed paths (103 tracked modifications and
  236 untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths. Release
  identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `2781fefcca4b7d52b44446a0cfb8491f2e25cb4f39a4f4c6fa82d745b9bfe732`, working-tree identity is
  `7bb1eb2da6f46396d47dfdd31a6b0dab7a2fcf72263fedccdb309ac69a0cacf4`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `66c4032627397ab131a56ef58a883b0135f01cd60c02266721f98347de1c07e0`; the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Made current independent-price issues self-contained in `GET /meta`. The read-only projection now
  publishes the verifier's existing worst-first disagreement records under an exact 20-item cap,
  with complete count, truncation state, and the relative, absolute-dollar, and material thresholds.
  Each row is restricted to ticker, date, OHLC field, primary-store value, independent-source value,
  and basis-point gap. Backend and browser contracts reject malformed or extra fields, duplicate
  ticker/date/field identities, future dates, nonpositive/non-finite prices, below-threshold rows,
  non-finite or incoherent thresholds, incorrect material/ticker/count accounting, and non-descending
  diagnostics. This is observability only: it does not rewrite prices or infer quarantines.
- The deployed 2026-09-11 evidence now reports 20 visible records out of 49 total with
  `disagreements_truncated=true`: 17 material records are Nasdaq's already-documented implausible
  VFLO scale response, followed by smaller VTEC/VTEI records; the primary store still has zero
  active price quarantines. The complete **1,993-test warnings-as-errors Python suite**, all 50 UI
  tests, production UI build, repository Ruff and `server tools` C90, Python/non-JSX JavaScript and
  shell compilation, documentation checks, diff hygiene, and the empty-index gate pass. After the
  API/UI restart, Dashboard, Journal, proxied health, and proxied meta return HTTP 200; both services
  remain active/enabled with `NRestarts=0`, and the browser contract accepts the live response.
- Strict pre-ledger inventory remains 339 fully owned changed paths (103 tracked modifications and
  236 untracked files), with no staged, unknown, empty-untracked, or unsafe-symlink paths. Release
  identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `4d192bbdc92e6f6dd5284dc92209c4e8809fd8b9d68392ce3c276fb53ffd121b`, working-tree identity is
  `b9988a9de1c743f28b89b76bc355d8a7ceb3e4fb7a15181c57d833c658a531e7`, and schedule-source
  identity remains `c8b044dfab70509b7bfb46ff0fc4c295a3132b5177a5f5b6c6ae07fbe2c3d6a7`.
  Recovery-source identity remains
  `66c4032627397ab131a56ef58a883b0135f01cd60c02266721f98347de1c07e0`; the protected 111-file
  research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Reconciled every published price-disagreement gap with its two public prices. The backend and
  browser now independently recompute `abs(store - source) / max(store, source) * 10,000` and
  require the reported `diff_bp` to agree within the producer's two-decimal rounding envelope.
  This closes a contract hole that previously allowed a malformed artifact to exaggerate severity,
  alter worst-first order, or misstate materiality while retaining otherwise plausible values.
  Focused regressions reject understated, exaggerated, and non-finite gaps, and synthetic bounded
  fixtures now contain mathematically coherent prices and gaps. The projection remains read-only;
  no verifier producer, price, quarantine, or research code changed.
- The complete **1,996-test warnings-as-errors Python suite**, all 50 UI tests, production UI build,
  repository Ruff and `server tools` C90, Python/non-JSX JavaScript and shell compilation,
  documentation checks, diff hygiene, and the empty-index gate pass. After the API/UI restart,
  Dashboard, Journal, direct/proxied health, and direct/proxied meta return HTTP 200; both services
  remain active/enabled with `NRestarts=0`. The strict browser contract accepts the live 20-of-49
  truncated disagreement projection, and the read-only automation audit remains `ok` with six
  managed cron entries, `Linger=yes`, and no pending changes.
- Strict pre-ledger inventory remains 339 fully owned changed paths, with no staged, unknown,
  empty-untracked, or unsafe-symlink paths. Release identity is complete and non-releasable only
  for `dirty-working-tree` and `required-files-untracked`; the pre-ledger manifest identity is
  `c6374b78b9213aa2887e64b68cd3badefc3e13fcbf6b3e1c6f2b4dbb1b5c4af3`, and working-tree
  identity is `9d9fdf8ecade33ad91e08c5eea168a52d2e31a5d4d34fd6a96ed83f88269c406`.
  Schedule-source identity remains
  `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`; recovery-source
  identity remains `66c4032627397ab131a56ef58a883b0135f01cd60c02266721f98347de1c07e0`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`; and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Made price-verification status labels self-consistent in the browser contract. After validating
  the complete evidence envelope, the client now derives the backend's public precedence from the
  latest market date, latest successful nightly start, checked-name coverage, parse-error count,
  and disagreement count. It rejects a clean snapshot labelled `issues`, issue rows labelled
  `current` or `partial`, incorrect reasons, and arbitrary sparse invalid reasons. Positive
  regressions retain valid current, partial, incomplete, issue, market-date, and nightly-staleness
  states; the server remains authoritative for `future-verification`, which depends on its exact
  request-time clock. This changes display validation only and does not alter producer evidence.
- The complete **1,996-test warnings-as-errors Python suite**, all 50 UI tests, production UI build,
  repository Ruff and `server tools` C90, Python/non-JSX JavaScript and shell compilation,
  documentation checks, diff hygiene, and the empty-index gate pass. After the UI-only restart,
  Dashboard, Journal, proxied health, and proxied meta return HTTP 200; both API and UI remain
  active/enabled with `NRestarts=0`. The strict browser contract accepts the live issue projection,
  and the read-only automation audit remains `ok` with six managed cron entries, `Linger=yes`, and
  no pending changes.
- Strict pre-ledger inventory remains 339 fully owned changed paths, with no staged, unknown,
  empty-untracked, or unsafe-symlink paths. Release identity is complete and non-releasable only
  for `dirty-working-tree` and `required-files-untracked`; the pre-ledger manifest identity is
  `f371c5b1feeb9e697b66d4bbdb4d30a0c8921f59e7cede05f9851de506251729`, and working-tree
  identity is `b47ff7e42c299752f2cda344bc9c69cce240a725645b9df94603df099b6ef668`.
  Schedule-source identity remains
  `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`; recovery-source
  identity remains `66c4032627397ab131a56ef58a883b0135f01cd60c02266721f98347de1c07e0`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`; and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Closed the browser boundary around active price-quarantine details. Each item must now contain
  exactly the five reviewed public fields, so an unexpected producer field cannot pass validation
  or become an accidental disclosure. A positive `detail_truncated` claim is accepted only when
  reason or evidence text reaches the producer's 1,024-character cap. Length checks count Unicode
  code points, matching DuckDB's string semantics rather than JavaScript UTF-16 code units; a valid
  capped non-BMP string therefore remains accepted. This changes response validation only and does
  not alter quarantine rows or trading gates.
- The complete **1,996-test warnings-as-errors Python suite**, all 50 UI tests, production UI build,
  repository Ruff and `server tools` C90, Python/non-JSX JavaScript and shell compilation,
  documentation checks, diff hygiene, and the empty-index gate pass. After the UI-only restart,
  Dashboard, Journal, proxied health, and proxied meta return HTTP 200; both services remain
  active/enabled with `NRestarts=0`, and the browser contract accepts the live zero-of-zero active
  quarantine projection. The read-only automation audit remains `ok` with six managed cron entries,
  `Linger=yes`, and no pending changes.
- Strict pre-ledger inventory remains 339 fully owned changed paths, with no staged, unknown,
  empty-untracked, or unsafe-symlink paths. Release identity is complete and non-releasable only
  for `dirty-working-tree` and `required-files-untracked`; the pre-ledger manifest identity is
  `3af69cd60f79d86dc9e189b274df9a2ba06fa69fe915133af181d10ec8f16ff9`, and working-tree
  identity is `3d51b467cca5971efc8c55d362a76ad01ab1abe2861ce21e1247e27886a3363b`.
  Schedule-source identity remains
  `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`; recovery-source
  identity remains `66c4032627397ab131a56ef58a883b0135f01cd60c02266721f98347de1c07e0`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`; and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Made active price-quarantine projection fail closed on incomplete stored rows. The API now
  requires a canonical ticker, nonblank reason and evidence, a real confirmation timestamp,
  bounded projected text, and a truncation flag consistent with the displayed 1,024-character
  fields before serializing an active quarantine. Five regression cases cover null or blank text
  and a missing timestamp and prove that read validation does not repair or rewrite the malformed
  row. Together with the browser's exact five-field, Unicode-code-point-aware contract, this keeps
  quarantine diagnostics complete and prevents unreviewed fields or false truncation claims.
- The complete **2,001-test warnings-as-errors Python suite**, all 50 UI tests, production UI build,
  repository Ruff and `server tools` C90, Python/non-JSX JavaScript and shell compilation,
  documentation checks, diff hygiene, and the empty-index gate pass. After restarting API and UI,
  Dashboard, Journal, direct/proxied health, and direct/proxied meta return HTTP 200; both services
  remain active/enabled with `NRestarts=0`, and the strict browser contract accepts the live
  zero-of-zero quarantine projection. The read-only automation audit remains `ok` with six managed
  cron entries, `Linger=yes`, and no pending changes.
- Strict pre-ledger inventory remains 339 fully owned changed paths, with no staged, unknown,
  empty-untracked, or unsafe-symlink paths. Release identity is complete and non-releasable only
  for `dirty-working-tree` and `required-files-untracked`; the pre-ledger manifest identity is
  `f3f8740d50a59d95fbbd572c5068077175e8628c995a0a0a37ae0f79a1dbcb7e`, and working-tree
  identity is `ac94d35efffb7873218d26ffa8709abceef9110a18dad43e9c86aba7e9d3d53a`.
  Schedule-source identity remains
  `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`; recovery-source
  identity remains `66c4032627397ab131a56ef58a883b0135f01cd60c02266721f98347de1c07e0`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`; and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Hardened the current stale-exposure boundary without changing portfolio or order state. The API
  now validates finite positive quantities, `buy`/`sell` pending-order sides, real signal dates not
  later than the operational date, and complete record-type shapes. Its query continues excluding
  intentional zero-quantity position tombstones but no longer silently hides null, negative, NaN,
  or infinite active-position quantities; those malformed rows fail the read projection and remain
  untouched. The browser now requires the exact top-level and per-row envelopes, the fixed 100-row
  caps, valid values, unique position/order identities, producer order, and an empty projection
  when the operational date is unavailable. The redundant duplicate `positions` dictionary key in
  the producer was removed.
- The complete **2,012-test warnings-as-errors Python suite**, all 51 UI tests, production UI build,
  repository Ruff and `server tools` C90, Python/non-JSX JavaScript and shell compilation,
  documentation checks, diff hygiene, and the empty-index gate pass. After restarting API and UI,
  Dashboard, Journal, direct/proxied health, and direct/proxied meta return HTTP 200; both services
  remain active/enabled with `NRestarts=0`. The strict browser contract accepts the live current
  zero-ticker/zero-position/zero-pending-order stale-exposure projection. The read-only automation
  audit remains `ok` with six managed cron entries, `Linger=yes`, and no pending changes.
- Strict pre-ledger inventory remains 339 fully owned changed paths, with no staged, unknown,
  empty-untracked, or unsafe-symlink paths. Release identity is complete and non-releasable only
  for `dirty-working-tree` and `required-files-untracked`; the pre-ledger manifest identity is
  `a0296b041abd2ea0e0d1cea43ec51fc9e1bc84979e4fedd48ef1d70f0d2f99de`, and working-tree
  identity is `7a570852a3c9e150436b7ef8d52e4c8bc6b0f994e734d73f314f297f824c6b81`.
  Schedule-source identity remains
  `c8b044dfab70509b7bfb46ff0fc4c295a3132b517a5f5b6c6ae07fbe2c3d6a7`; recovery-source
  identity remains `66c4032627397ab131a56ef58a883b0135f01cd60c02266721f98347de1c07e0`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`; and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No search, tuning, gate, generated
  evidence, database row, broker connection, or capital state changed.
- Corrected the stale-exposure browser ordering check to compare Unicode code points, matching
  Python's producer sort instead of JavaScript's UTF-16 code-unit order. A focused regression uses
  printable U+F900 and non-BMP U+10000 portfolio IDs, whose order differs under those two rules, so
  valid producer output can no longer be rejected only because an identifier contains non-BMP
  text. All 51 UI tests, non-JSX syntax, diff/index/worktree gates, and the production UI build pass
  on the exact final source; the immediately preceding 2,012-test Python result remains applicable
  because this follow-up changes only browser code and its test. After the UI-only restart,
  Dashboard, Journal, proxied health, and proxied meta return HTTP 200; both services remain active
  with `NRestarts=0`, and the strict live meta contract passes.
- Strict pre-ledger inventory remains 339 fully owned changed paths. Release identity remains
  complete and non-releasable only for `dirty-working-tree` and `required-files-untracked`; the
  pre-ledger manifest identity is
  `25079299abd2f63513573c24ee4bc9e6037d53e78d4050942732e3620217453f`, and working-tree
  identity is `1c510d9048f80dec0617a7d16efa4d497f6756f52a784447b490a360a7208506`.
  The protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  No strategy search, tuning, gate, generated evidence, database row, broker connection, or capital
  state changed.
- Closed four related browser-admission gaps in the bounded operational projections. League and
  screen responses must now retain their producer-owned 100-row caps, while bulk equity,
  positions, and orders must retain their producer-owned 500-row caps; a smaller internally
  coherent response can no longer masquerade as the reviewed public contract. Orders must be
  newest-first by ID, positions must follow canonical portfolio/ticker order, and League/screen
  ties must follow the producer's textual tie-breaks. A shared browser comparator now uses Unicode
  code points, matching Python and DuckDB rather than JavaScript UTF-16 code units; regressions use
  U+F900 and U+10000 to exercise the divergent case. Existing stale-exposure and walk-forward
  diagnostic validation now reuse that same primitive. The backend already enforced these
  semantics; focused producer tests pin the cross-language ordering. Journal fill/event rows were
  deliberately left unchanged because the append-only ledger has no fill identifier and can
  legitimately contain multiple events for one order.
- The complete **2,015-test warnings-as-errors Python suite**, all 52 UI tests, production UI build,
  repository Ruff and `server tools` C90, Python/non-JSX JavaScript and shell compilation,
  documentation checks, zero production npm vulnerabilities, diff hygiene, strict worktree audit,
  and empty-index gate pass. After restarting only the UI, Dashboard, League, Positions, Journal,
  and all affected direct/proxied API routes return HTTP 200 and pass the actual browser validators.
  Both services remain active/enabled with `NRestarts=0`; the read-only automation audit remains
  `ok` with six managed cron entries, `Linger=yes`, and no pending changes.
- Strict pre-ledger inventory remains 339 fully owned changed paths, with no staged, unknown,
  empty-untracked, or unsafe-symlink paths. Release identity is complete and non-releasable only
  for `dirty-working-tree` and `required-files-untracked`; the pre-ledger manifest identity is
  `8c8dd697f476e6cb79138f275cfd131abbc5e5fe9bd1160e2da83e76105103f2`, and working-tree
  identity is `00bae2ce4d80b3a27e7c76fbe441b5bbbd3e5bba130e71d76511e2a87e221ed6`.
  Schedule-source identity remains
  `c8b044dfab70509b7bfb46ff0fc4c295a3132b5177a5f5b6c6ae07fbe2c3d6a7`; recovery-source
  identity remains `66c4032627397ab131a56ef58a883b0135f01cd60c02266721f98347de1c07e0`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`; and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, and recurring sweeps are idle with no open charter. No strategy search, tuning, gate,
  generated evidence, database row, broker connection, or capital state changed.
- Closed the remaining queue, journal, and empty-order response admission gaps. Journal gate names
  and details and queue failure kinds now use Unicode code-point bounds consistently across Python
  and JavaScript. A forged empty orders projection cannot echo an unsupported requested status.
  The queue producer now validates its final public envelope: exact shapes, fixed 100-row detail
  limits, known states, safe counts, bounded nonblank kinds, canonical UTC timestamps, unique job
  identifiers across both failure classes, newest-first `(updated_at, id)` ordering, exact
  historical classification, and a coherent latest-research-job row. The browser mirrors those
  rules and compares canonical timestamp text directly, preserving producer microseconds that a
  JavaScript date conversion would discard. Malformed queue kinds fail closed instead of being
  coerced to strings, and focused producer/browser regressions cover each boundary.
- The complete **2,019-test warnings-as-errors Python suite**, all 52 UI tests, production UI build,
  repository Ruff and `server`/`tools` C90, Python/non-JSX JavaScript and shell compilation,
  documentation checks, zero production npm vulnerabilities, diff hygiene, strict worktree audit,
  and empty-index gate pass. After restarting API and UI, Dashboard, League, Positions, Journal,
  and direct/proxied health, meta, league, equity-series, screen, positions, orders, and journal
  routes return HTTP 200. Every JSON route passes the shipped browser validator through both
  origins, and the proxy preserves each payload exactly. Both services are active/enabled with
  `NRestarts=0`; the read-only automation audit is `ok` with six managed cron entries,
  `Linger=yes`, and no pending changes.
- Strict pre-ledger inventory remains 339 fully owned changed paths, with no staged, unknown,
  empty-untracked, or unsafe-symlink paths. Release identity is complete and non-releasable only
  for `dirty-working-tree` and `required-files-untracked`; the pre-ledger manifest identity is
  `b8b9e738a4aa6bb2a61e81e53ced2c5f45120be7bb3309c1e3e4c467688c4ff5`, and working-tree
  identity is `97457da3b29286f991c2c4746c5c9e5e0efc206fe9f4d0b92a97ea3afb94bd38`.
  Schedule-source identity remains
  `c8b044dfab70509b7bfb46ff0fc4c295a3132b5177a5f5b6c6ae07fbe2c3d6a7`; recovery-source
  identity remains `66c4032627397ab131a56ef58a883b0135f01cd60c02266721f98347de1c07e0`;
  the protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`; and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Strategy evidence remains unready: Sector is `ACCUMULATING` at 5/200, XS is `WAITING` at 0/48,
  E1 is `ACCUMULATING` at 7/40 with negative mean and t-statistic, walk-forward evidence is current
  at 18/18, recurring sweeps are idle with no open charter, and price verification remains
  `issues`. No search, tuning, gate, generated evidence, database row, broker connection, or
  capital state changed.
- Corrected the Journal ticket ordering contract to preserve DuckDB microseconds end to end.
  Tickets are produced newest-first by `(created_at, id)` from a naïve `TIMESTAMP`; FastAPI emits
  whole seconds or six fractional digits, while JavaScript date conversion retains only
  milliseconds. The producer now explicitly rejects timezone-aware ticket timestamps, and the
  browser admits only that canonical naïve form and compares it lexically before using ID as the
  exact-timestamp tie-break. A regression proves that correctly ordered `.123999` and `.123001`
  tickets remain valid even though `Date.parse` collapses them to the same millisecond, and that
  the reverse order plus offset, `Z`, millisecond-only, and over-precise spellings fail closed.
  Stored tickets and their producer ordering are unchanged.
- The complete **2,020-test warnings-as-errors Python suite**, all 52 UI tests, production UI build,
  repository Ruff and `server`/`tools` C90, Python/non-JSX JavaScript and shell compilation,
  documentation checks, zero production npm vulnerabilities, diff hygiene, strict worktree audit,
  and empty-index gate pass. After restarting API and UI, all four rendered pages return HTTP 200;
  direct/proxied health, meta, league, equity-series, screen, positions, orders, and journal pass
  the shipped browser validators with byte-equivalent JSON. The seven live ticket timestamps all
  match the canonical form and remain newest-first. Both services are active/enabled with
  `NRestarts=0`; automation remains `ok` with six managed cron entries and `Linger=yes`.
- Strict pre-ledger inventory remains 339 fully owned changed paths. Release identity is complete
  and non-releasable only for `dirty-working-tree` and `required-files-untracked`; the pre-ledger
  manifest identity is `437182a9d9939182d2fd20ef8ca7d45ac804279bdd08028df29fdc57920490b5`,
  and working-tree identity is
  `762f110ad9e65d34fe05f76181fd953754255a7aa22ebd61aa2ce317ab86d981`.
  The protected 111-file research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  No strategy search, tuning, gate, generated evidence, database row, broker connection, or capital
  state changed; profitability remains unproven.
- Closed the remaining offset-timestamp precision gap in the browser `/meta` contract. Canonical
  operational timestamps now require the same whole-second or six-microsecond-digit form accepted
  by Python, and a shared comparator orders equivalent-offset instants by UTC milliseconds plus
  the retained sub-millisecond digits. Price-verification freshness and Friday-postflight nightly
  and miner-evidence windows now use that exact comparison, so two values inside one JavaScript
  millisecond cannot reverse or hide the backend's classification. Regressions cover equivalent
  offsets, exact equality, noncanonical fractional precision, evidence just beyond a finish, and a
  verification timestamp just after versus just before a nightly boundary.
- All 53 UI tests, the production UI build, repository Ruff and `server`/`tools` C90,
  Python/non-JSX JavaScript and shell compilation, focused documentation/status tests, zero
  production npm vulnerabilities, diff hygiene, strict worktree audit, and empty-index gate pass.
  The immediately preceding complete 2,020-test Python result remains applicable because this
  follow-up changes only browser code, its tests, and documentation. After restarting only the UI,
  all four rendered pages return HTTP 200 and the live microsecond-bearing direct/proxied `/meta`
  payload passes the deployed browser contract unchanged. API/UI remain active/enabled with
  `NRestarts=0`; automation remains `ok` with six managed cron entries and `Linger=yes`.
- Strict pre-ledger inventory remains 339 fully owned changed paths. Release identity remains
  complete and non-releasable only for `dirty-working-tree` and `required-files-untracked`; the
  pre-ledger manifest identity is
  `a2ca5f1cc657bb72451fbebc50c7e7462221902108445d9a5460e28c53a0747f`, and working-tree
  identity is `cfb5fb1180181853fe3a259e15575b8e6e4c516d883f411f7cb32dfe8813cd70`.
  The protected research identity remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  No strategy or evidence state changed; profitability remains unproven.
- Clarified the dated 2026-09-11 worktree review's authority boundary without rewriting its
  historical counts. Its opening and decision now use snapshot tense, say explicitly that the
  336-path/22-required-untracked figures are provenance rather than live status, and direct
  operators to the strict worktree audit and release manifest for the current tree. The older
  architecture review now calls that file a dated snapshot, while the operating guide separately
  records the current manifest fact that `uv.lock` is still untracked and therefore not
  recoverable from `HEAD`. A documentation regression pins those distinctions.
- All 58 focused documentation tests, Ruff, diff hygiene, strict worktree audit, and empty-index
  hygiene pass. No runtime file changed, so no service restart was required; API/UI remain
  active/enabled with `NRestarts=0`. Pre-ledger manifest identity is
  `21c5b505f405a346f18e8e09c14024d620518f2035bcdf342425dab71aee3081`, working-tree identity is
  `171376e0882ac9ff0a5765c81fde0dd45fa27fac226f55a50f388571b9c0c197`, protected research remains
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective evidence
  remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
- Finished the offset-timestamp canonicality edge and a related UI ordering cleanup. The browser
  now rejects an explicit `.000000` fraction because Python's canonical `datetime.isoformat()`
  emits that instant in whole-second form, while retaining exact six-digit nonzero microseconds.
  The Positions portfolio selector now uses the shared Unicode code-point comparator instead of
  JavaScript's UTF-16 default, matching the validated producer order for non-BMP identifiers.
  Current documentation now clearly distinguishes the 2026-09-11 worktree review's historical
  336-path/22-required-untracked snapshot from the executable audit and manifest that own live
  state; it still states truthfully that `uv.lock` is currently untracked and not recoverable from
  `HEAD`.
- All 53 UI tests, the production UI build, 73 focused documentation/status tests, repository Ruff
  and `server`/`tools` C90, non-JSX JavaScript and shell syntax, diff hygiene, strict worktree
  audit, and empty-index gate pass. The prior complete 2,020-test Python run remains applicable
  because this follow-up changes UI/docs/tests only. After the UI-only restart, all four pages and
  direct/proxied meta and positions return valid responses; both services remain active/enabled
  with `NRestarts=0`, and automation remains `ok` at six entries with `Linger=yes`.
- Strict pre-ledger inventory remains 339 fully owned paths. Release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`; pre-ledger manifest
  identity is `7e40e5b26d575ddae703636bb9372caeb1555960f39a02de5e02ca0a9e7e75cb`, and working-tree
  identity is `c4c0de2be48e75073b9d16bb2f0f71dd343c81ff51165d4a6af50d50a0339116`.
  Protected research and prospective evidence remain unchanged. No research gate currently admits
  a new charter, so no strategy search or tuning was started; profitability remains unproven.
- Closed an unattended-automation permission race. Managed cron sources now check their required
  read/execute access relative to the same anchored parent descriptor used for the stable no-follow
  read, and require mode metadata to remain unchanged across that observation. A driver that loses
  execute permission between the former pathname check and descriptor admission—or during the
  descriptor read—now makes the plan/apply fail closed before any crontab or service mutation.
  Two focused regressions pin both timing windows, and the operating documentation records the
  descriptor-bound permission invariant.
- The complete **2,023-test warnings-as-errors Python suite**, 107 focused installer/documentation
  tests, repository Ruff and `server`/`tools` C90, Python/non-JSX JavaScript and Bash syntax,
  diff hygiene, strict worktree audit, and empty-index gate pass. The live read-only automation
  audit remains `ok`: six managed cron entries, both source-matched services active/enabled,
  `Linger=yes`, UTC host time, and no pending changes. No deployed runtime module changed, so no
  restart was required; both services retain `NRestarts=0`, and Dashboard, League, Positions, and
  Journal return HTTP 200.
- Strict pre-ledger inventory remains 339 fully owned paths. Release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`; pre-ledger manifest
  identity is `aa34ebd8466323c32c0a5cf8bb7e5c64d1e5b4ff3373148647286b83a5e38b46`, working-tree
  identity is `83294e48da9ab04ece39186bef2cc27f43c299068cde929e472273163cadbe90`, and schedule-source
  identity is `2082de68e5b0f5d2e94e508719735f399345916c801e489e4f886337f289fd67`.
  Protected research remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`,
  and prospective evidence remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  No strategy, gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Tightened the recovery-manifest creation-time contract. Verification now accepts only the exact
  canonical UTC spelling emitted by `datetime.now(timezone.utc).isoformat()`: a `T` separator,
  `+00:00` offset, and either whole seconds or six fractional digits for a nonzero microsecond
  value. Parser-equivalent spaces, `Z`, compact offsets, abbreviated fractions, explicit all-zero
  fractions, and over-precise values that Python would silently truncate are rejected even when a
  manifest is rehashed. Six rejection cases and both valid producer forms are pinned by regression
  tests, and the recovery documentation states the canonical boundary.
- The complete **2,031-test warnings-as-errors Python suite**, 178 focused recovery/documentation
  tests, repository Ruff and `server`/`tools` C90, Python and Bash syntax, diff hygiene, strict
  worktree audit, and empty-index gate pass. The preserved schema-v2 recovery bundle also passes
  the updated verifier unchanged: its 3,702,796,288-byte database hash, 28 tables, three prospective
  evidence files, seven operational artifacts, and manifest hash all verify. No deployed service
  module changed, so no restart was required.
- Strict pre-ledger inventory remains 339 fully owned paths. Release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`; pre-ledger manifest
  identity is `b1e943f7e38ff628ce1596df85c440a58526a7d498a18f7ca64928dfcc245321`, working-tree
  identity is `364b817005521d0e1f932a5fd86ae11d6971bd33c5084c097cce441b2b7950df`, and recovery-source
  identity is `af6bbd0582cb72b0853494d720e54f834917074edd4299dd8b862cb538dc147d`.
  Protected research remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`,
  and prospective evidence remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  No strategy, gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Canonicalized the recovery manifest's repository-contained source location. Verification now
  accepts only the exact nonempty relative POSIX path emitted by `Path.relative_to(...).as_posix()`;
  leading-dot aliases, duplicate separators, a path that normalizes to the repository root, and
  parent traversal are rejected even when the manifest is rehashed. Positive coverage retains both
  legitimate provenance forms: canonical repository-relative paths and external sources with an
  omitted path. The recovery documentation now states this provenance boundary explicitly.
- The complete **2,036-test warnings-as-errors Python suite**, 183 focused recovery/documentation
  tests, repository Ruff and `server`/`tools` C90, Python and Bash syntax, diff hygiene, strict
  worktree audit, and empty-index gate pass. The preserved schema-v2 3,702,796,288-byte recovery
  bundle passes the combined canonical timestamp/path verifier unchanged, including its 28 tables,
  three prospective evidence files, seven operational artifacts, database hash, and manifest hash.
  No deployed service module changed, so no restart was required.
- Strict pre-ledger inventory remains 339 fully owned paths. Release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`; pre-ledger manifest
  identity is `80fdcc43c3ca48b4bef8b78dbce7e84c5b3b32ffade50356500ab5a94673fcd7`, working-tree
  identity is `36a019f342d67b8cdb4c5fa7ec1ec70818dbc4d38b57534b6fb8dc34c6e00c3d`, and recovery-source
  identity is `1576fc4cd5bfce2861474bbd0df146ee43fb0b7f3c54496010c680eb3cd8a4e0`.
  Protected research remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`,
  and prospective evidence remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  No strategy, gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Closed a release-identity file-admission race. Release-critical file groups and ordinary
  working-tree regular files now read bytes and executable mode through stable no-follow leaf and
  parent descriptors. A file swapped after preliminary validation to a symlink, FIFO, or another
  regular inode fails closed at the read boundary; the manifest no longer follows external bytes
  or risks blocking on a special node while waiting for the later whole-tree stability check.
  Git-visible symlink target text is likewise read relative to stable parent descriptors without
  following the target, and a changing symlink becomes an unstable path. Regressions pin post-check
  symlink/FIFO substitution, same-byte regular-file replacement, symlink-target replacement, and a
  classified symlink replaced by a FIFO.
- The complete **2,041-test warnings-as-errors Python suite**, 94 focused release/documentation
  tests, repository Ruff and `server`/`tools` C90, Python and Bash syntax, diff hygiene, strict
  worktree audit, and empty-index gate pass. The live release-manifest command successfully reads
  the current reviewable tree through the new descriptor boundary and retains complete identity.
  No deployed service module changed, so no restart was required.
- Strict pre-ledger inventory remains 339 fully owned paths. Release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`; pre-ledger manifest
  identity is `4a690bffd54704e90cdb864a7ca0900137dae0d137c6de6991db30c3bc97df09`, working-tree
  identity is `03b85003b7af780bbe277d519545081a7611a163c901d58d0c0ad7c904c660c4`, audit-source
  identity is `8f953ee0afc4170d3b7b6f5fe5988791d1b346ae541d0a613e0946ee38a6e813`, and recovery-source
  identity is `7e0450f506c125125e285ff485138a8f365ab13a498747c2a032f2154a627e0a`.
  Protected research remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`,
  and prospective evidence remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  No strategy, gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Upgraded the recursive worktree inventory to schema v3. Every Git-reported untracked leaf now
  receives two descriptor-relative, no-follow metadata observations; stable regular and empty
  files remain distinguishable, while symlinks, special nodes, vanished/replaced paths, and parent
  substitutions are reported in explicit unsafe/unstable lists. The audit also requires Git's
  recursive porcelain output to remain byte-identical across the scan, so it cannot publish a
  mixed-time inventory after concurrent path-set changes. Strict mode fails closed on every unsafe
  or unstable reported path. Regressions cover special-node classification, same-byte leaf
  replacement, and a changed Git inventory.
- The complete **2,044-test warnings-as-errors Python suite**, 123 focused worktree/release/docs
  tests, repository Ruff and `server`/`tools` C90, Python and Bash syntax, diff hygiene, strict
  schema-v3 worktree audit, and empty-index gate pass. The live audit still inventories 339 fully
  owned paths with no untracked symlink, special, unstable, empty, staged, or unknown path. No
  deployed service module changed, so no restart was required.
- Release identity remains complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`; the pre-ledger manifest identity is
  `c323b59ada594de7f4961de5bc348c0b0999bc7b4b7f0112f864213606f73df9`, working-tree identity is
  `9d140ca32ee8959d9c831cdcd0757dd8e41c450b95dcec14f6e5c7a28f027277`, audit-source identity is
  `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`, and recovery-source
  identity remains `7e0450f506c125125e285ff485138a8f365ab13a498747c2a032f2154a627e0a`.
  Protected research remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`,
  and prospective evidence remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  No strategy, gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Closed a mixed-time cohort race in the walk-forward migration auditor. Baseline and replacement
  directory chains are now retained through descriptor-relative no-follow traversal; every
  immediate `.json` artifact must be a bounded regular file whose discovered identity, metadata,
  bytes, and visible leaf remain stable. Both JSON inventories and directory paths must also remain
  unchanged through the complete comparison. Regressions pin symlinked cohort directories,
  symlink/FIFO artifacts, inventory drift, post-inventory leaf replacement, and whole-directory
  replacement without changing the established allowlist or report schema. Contributor and
  operating documentation now state this coherent-snapshot boundary.
- The complete **2,051-test warnings-as-errors Python suite**, 111 focused migration/documentation
  tests, repository Ruff and `server`/`tools` C90, Python and Bash syntax, diff hygiene, strict
  schema-v3 worktree audit, and empty-index gate pass. The retained 18-artifact earnings-selector
  report is byte-for-byte unchanged at 6,067 bytes and SHA-256
  `10f6c0945df599866efd94e855bf218c2124dd8b3b65981ab9f7059aeae8f8fc`, including its 34 reviewed
  economic/diagnostic differences. The live automation audit remains `ok` with six managed cron
  entries and no pending changes; API/UI remain active and enabled with zero restarts, `Linger=yes`,
  and Dashboard, League, Positions, and Journal returning HTTP 200. No deployed module changed, so
  no restart was required.
- Strict pre-ledger inventory remains 339 fully owned paths. Release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`; pre-ledger manifest
  identity is `3155e1bb12793b239b593f53395e2065347f88fc0ef102f053302f9f8edc84de`, working-tree
  identity is `493d38bc3a6f86125a171e9578adf898daa78f1529cbd4db70e2abd27b6b76c5`, audit-source
  identity remains `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`, and recovery-source
  identity remains `7e0450f506c125125e285ff485138a8f365ab13a498747c2a032f2154a627e0a`.
  Protected research remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`,
  and prospective evidence remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  No strategy, gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Closed the Friday postflight receipt's authorization/publication path races. Canonical-path
  admission now compares normalized pathnames without following aliases; publication opens or
  creates every parent component without following symlinks and retains that directory descriptor.
  Existing symlink, FIFO, or directory leaves fail before mutation. The durable atomic commit uses
  no-replace for an initially absent target and exchange-plus-displaced-inode verification for an
  existing regular target, so last-moment creation or replacement cannot be silently overwritten.
  Target metadata and parent identity must remain stable around staging and publication, existing
  modes are preserved, and uncertain post-publication durability is reported rather than hidden.
  Regressions cover parent aliases and replacement, special leaves, in-place mutation, target
  creation/replacement at the atomic operation, mode preservation, cleanup, and the bounded CLI
  failure envelope. The operating guide records the complete boundary.
- The complete **2,064-test warnings-as-errors Python suite**, 113 focused postflight/status/
  resource/documentation tests, repository Ruff and `server`/`tools` C90, Python and Bash syntax,
  diff hygiene, strict schema-v3 worktree audit, and empty-index gate pass. A live dry-run accepted
  Friday 2026-09-11 without changing the canonical receipt, whose SHA-256 remains
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`. Automation remains
  `ok` with six entries, no pending changes, and the updated postflight launch-source hash
  `19acd5400fd1fe06e58e24eb716ad810b8c54ef414bb2addf1186b9bbaaa5113`. No resident service
  module changed, so no restart was required.
- Strict pre-ledger inventory remains 339 fully owned paths. Release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`; pre-ledger manifest
  identity is `2a49a96112716140ce310297e7263870bfeb721786e40a08d419777fcc5ed7c1`, working-tree
  identity is `fe099992c6ca0ebfe110a221c125c2d4d8403e6268dc47c22f175de6f8264fed`, and schedule-source
  identity is `da82b25b9c23fc926ed661935ca79e473631204280d5ad1e9c5006126eb0dfed`.
  Audit and recovery source identities remain
  `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a` and
  `7e0450f506c125125e285ff485138a8f365ab13a498747c2a032f2154a627e0a`; protected research
  remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective
  evidence remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  No strategy, gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Completed the Friday receipt's matching read-side boundary. The shared bounded operational reader
  now has an opt-in strict-parent policy while preserving intentional symlinked data-root aliases
  for every existing default caller. The canonical postflight projection opts in: it retains every
  absolute parent component without following symlinks, opens the leaf relative to that directory,
  performs both bounded reads through one regular-file descriptor, then requires the leaf and
  complete visible parent chain to remain identical. Initial aliases and post-admission parent or
  leaf disappearance/substitution report `receipt-invalid`; only a genuinely absent path retains
  the schedule-aware missing/overdue meaning. Regression coverage pins default alias compatibility,
  strict initial alias rejection, parent replacement/removal, JSON-policy propagation, and public
  postflight classification. The operating guide records this scoped exception.
- The complete **2,071-test warnings-as-errors Python suite**, 255 focused file/JSON/postflight/
  meta/route/documentation tests, repository Ruff and `server`/`tools` C90, Python and Bash syntax,
  diff hygiene, strict schema-v3 worktree audit, and empty-index gate pass. The preserved schema-v2
  recovery bundle verifies unchanged: its 3,702,796,288-byte database hash, 28 tables, three
  prospective evidence files, seven operational artifacts, and manifest hash all pass. API-only
  deployment started PID 1007518 cleanly with `NRestarts=0`; all eight direct API probes and four
  UI pages return HTTP 200, the UI remains on PID 355332 with zero restarts, and the canonical
  receipt remains current at SHA-256
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`. Automation remains
  `ok` with six entries and no pending changes.
- Strict pre-ledger inventory remains 339 fully owned paths. Release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`; pre-ledger manifest
  identity is `1d8d3dc265bcfc9c5d036fa81cca28a2a06f44c383d7b1d4c5cc3fd32e174508`, working-tree
  identity is `6f470274bc16ab75a7d17872c374a8a4b8468e6801e1823cf8cc0444a97e663d`, schedule-source
  identity is `f395b386bc183016c89fb1c68d6c6d18cdc191740c68f59a1b5a19dc74fdfe94`, and recovery-source
  identity is `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`.
  Audit sources remain `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`, protected research
  remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective
  evidence remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  No strategy, gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Hardened the shared bounded host-command boundary used by scheduler and source-control status.
  Every probe now starts in a private process session, and timeout, oversized output, read failure,
  invalid UTF-8, or another unsuccessful capture kills the complete process group before returning
  fail-closed. A reproduced child that inherited the probe's output pipes previously survived its
  parent's 0.1-second timeout; regressions now prove both timeout and post-parent invalid-output
  descendants reach a terminal state. The operating guide records the lifecycle guarantee. The
  complete **2,073-test warnings-as-errors Python suite**, focused host/scheduler/source/meta/
  documentation tests, repository Ruff and `server`/`tools` C90, Python and Bash syntax, and diff
  hygiene pass. Strict pre-ledger inventory remains 339 fully owned paths with an empty index;
  release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`. Pre-ledger manifest identity is
  `c40fb6af3fab1593a4be72a66acc75742ff1799a9d963220414a233179e4dd8d`, working-tree identity
  is `806aea8bc267407937081ffdf85dd3653bdc2c1e3fe41e74b7cafe5e1d948e34`, and schedule-source
  identity is `9d54b3e82d56d5233980e8c3adebf7b60149f60c065c08cb0b94f9ca824210a0`.
  The schema-v2 recovery bundle verifies unchanged, automation remains `ok` at 5+1 schedules, and
  the final API-only deployment started PID 1117318 with zero restarts; eight API routes and four
  UI pages return HTTP 200. Audit and recovery source identities remain
  `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a` and
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`; protected research and
  prospective-evidence identities remain
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`. No strategy, gate,
  generated evidence, database row, broker connection, or capital state changed, and profitability
  remains unproven.
- Closed the remaining bounded-host-probe timeout race and tightened source-control classification.
  A `wait()` timeout now explicitly kills the probe's private process group even when the leader
  exits before final cleanup observes it. Git tracking status treats `no-upstream` only as both
  branch-tracking keys returning Git's clean absent-key result; command failures, unexpected
  diagnostics, partial key pairs, malformed merge refs, and unexpected upstream-resolution errors
  now fail closed instead of resembling intentional local-only state. Valid configured-but-missing
  tracking refs retain `tracking-ref-missing`, and the real checkout remains correctly
  `local-only/no-upstream` without a network check. The operating guide and regression suite cover
  these distinctions.
- The complete **2,085-test warnings-as-errors Python suite**, focused host/source/scheduler/meta/
  documentation tests, repository Ruff and `server`/`tools` C90, Python and Bash syntax, diff
  hygiene, strict schema-v3 worktree audit, and empty-index gate pass. The preserved schema-v2
  recovery bundle verifies unchanged. Strict pre-ledger inventory remains 339 fully owned paths;
  release identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`. Pre-ledger manifest identity is
  `c47eba597d2f9421a15b7c2a7d90fc991ce45ca363957fcd0d3431dcd018fb24`, working-tree identity
  is `9f5a57a1dafb02788be39cb7910176e6e82dc2e07c63f5f25495c523e5070394`, and schedule-source
  identity is `0d2c38c650f8e8303503176cda6e9569ceb1ad424039098e7765f1a0ebdb6763`.
  Automation remains `ok` at 5+1 schedules with no pending changes and `Linger=yes`; API-only
  deployment started PID 1220606 with zero restarts, eight API routes and four UI pages return HTTP
  200, and the Friday receipt remains current. Audit, recovery, protected-research, and prospective-
  evidence identities remain respectively
  `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`,
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`,
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`. No strategy, gate,
  generated evidence, database row, broker connection, or capital state changed; profitability
  remains unproven.
- Completed the structured local-upstream boundary. Source-control status now resolves the exact
  full upstream ref and its display name in one structured Git record without requiring a fetched
  object, probes that full ref separately as a commit, and uses the full ref for ahead/behind
  computation. Only a clean absent-object result maps to `tracking-ref-missing`; other object or
  count-command failures map to `git-unavailable`, malformed successful counts remain
  `tracking-count-invalid`, and the shortened ref is display-only. A temporary-repository
  regression proves the configured-before-fetch transition, and a call-boundary regression pins
  full-ref comparison. The operating guide records the complete protocol.
- The complete **2,093-test warnings-as-errors Python suite**, 152 focused host/source/scheduler/
  meta/documentation tests, repository Ruff and `server`/`tools` C90, Python and Bash syntax, diff
  hygiene, strict schema-v3 worktree audit, and empty-index gate pass. The preserved schema-v2
  recovery bundle verifies unchanged at 3,702,796,288 bytes, 28 tables, three prospective-evidence
  files, seven operational artifacts, database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, and manifest SHA-256
  `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
  Strict pre-ledger inventory remains 339 fully owned paths; release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`. Pre-ledger manifest
  identity is `aacdf47300f5f0e46319d359ddf491b9c1cb559ee714cf02a9632bffe2367f6f`,
  working-tree identity is `6e14844dd1a920ef3d1252051c4a4f675ed0917343d44dd1ea9fe5df0e00ef8e`,
  and schedule-source identity remains
  `0d2c38c650f8e8303503176cda6e9569ceb1ad424039098e7765f1a0ebdb6763`.
- Automation remains `ok` at five production schedules plus one postflight, with no pending
  changes and `Linger=yes`. API-only deployment started PID 1275239 with zero restarts; UI remains
  PID 355332 with zero restarts; eight API routes and four UI pages return HTTP 200. Friday's
  receipt remains current at SHA-256
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`; all four miners are
  current and the queue has zero actionable failures. The checkout remains correctly
  `local-only/no-upstream` without a network check. Audit, recovery, protected-research, and
  prospective-evidence identities remain respectively
  `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`,
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`,
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  Research remains paper-only: sector momentum is `ACCUMULATING` at 5/200, E1 is
  `ACCUMULATING` at 7/40 with negative mean return and t-statistic, XS momentum is `WAITING` at
  0/48, no family is ready for a charter, and `automatic_action` remains `none`; profitability
  remains unproven.
- Bounded host-probe cleanup no longer contains an unbounded reap after failure. After killing the
  private process group, the shared runner gives its leader at most one additional second to reap;
  a pathological `wait()` therefore cannot hold scheduler or source-control `/meta` projection
  indefinitely beyond the five-second command deadline. A direct regression proves timeout during
  reap is contained, and the operating guide records the cleanup envelope. Accounting correction:
  the immediately preceding entry's exact suite and focused counts were 2,094 and 151 after its new
  full-ref regression, not 2,093 and 152; that historical entry remains append-only.
- The current complete **2,095-test warnings-as-errors Python suite**, 152 focused host/source/
  scheduler/meta/documentation tests, repository Ruff and `server`/`tools` C90, Python and Bash
  syntax, diff hygiene, strict schema-v3 worktree audit, and empty-index gate pass. The preserved
  schema-v2 recovery bundle verifies unchanged at 3,702,796,288 bytes, 28 tables, three prospective-
  evidence files, seven operational artifacts, database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, and manifest SHA-256
  `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
  Strict pre-ledger inventory remains 339 fully owned paths; release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`. Pre-ledger manifest
  identity is `86c547ff8b13fe5d5cfcf9fba41a02eae92450a4be968625d114c4c76a2f8bea`,
  working-tree identity is `281c0897bad8d0d1c0b6a3bc4ca296f258955ca04d01b695149bf76232cae4f9`,
  and schedule-source identity is
  `ae0242f1805aa5cf5b265930371e2bd83dec91dbaa90073c592f856b0a25daf1`.
- Automation remains `ok` at five production schedules plus one postflight, with no pending
  changes and `Linger=yes`. API-only deployment started PID 1327275 with zero restarts; UI remains
  PID 355332 with zero restarts; eight API routes and four UI pages return HTTP 200. Friday's
  receipt remains current at SHA-256
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`; all four miners are
  current and the queue has zero actionable failures. Audit, recovery, protected-research, and
  prospective-evidence identities remain respectively
  `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`,
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`,
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`. No strategy,
  gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Tightened the final source-control machine-output boundary. Ahead/behind parsing now accepts only
  Git's canonical two ASCII-decimal fields separated by one tab and terminated by one newline;
  signs, Unicode digits, spaces, missing or extra framing, and extra fields fail closed as
  `tracking-count-invalid` rather than being normalized by Python. Eight adversarial cases and the
  operating guide pin that grammar. The complete **2,103-test warnings-as-errors Python suite**,
  160 focused host/source/scheduler/meta/documentation tests, repository Ruff and `server`/`tools`
  C90, Python and Bash syntax, diff hygiene, strict schema-v3 worktree audit, and empty-index gate
  pass. The preserved schema-v2 recovery bundle verifies unchanged at 3,702,796,288 bytes, 28
  tables, three prospective-evidence files, seven operational artifacts, database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, and manifest SHA-256
  `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
- Strict pre-ledger inventory remains 339 fully owned paths; release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`. Pre-ledger manifest
  identity is `ee14dfcc50d388adc8331a8daf37ed45234af7e150dbfeb40d520f52a3e5e778`,
  working-tree identity is `e9ea4b852011e36d685e9cf8e0641d40aae269f84537bf70c667889736575a7e`,
  and schedule-source identity remains
  `ae0242f1805aa5cf5b265930371e2bd83dec91dbaa90073c592f856b0a25daf1`.
  API-only deployment started PID 1377543 with zero restarts; UI remains PID 355332 with zero
  restarts; all eight API routes and four UI pages return HTTP 200. Automation remains `ok` at five
  production schedules plus one postflight with no pending changes and `Linger=yes`; the Friday
  receipt remains current at SHA-256
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`; all four miners are
  current and the queue has zero actionable failures. Audit, recovery, protected-research, and
  prospective-evidence identities remain respectively
  `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`,
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`,
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`. Research remains
  paper-only with no ready family and `automatic_action = none`; profitability remains unproven.
- Closed the remaining Git diagnostic-output ambiguity in the read-only source-control projection.
  A clean, silent `symbolic-ref` exit 1 alone now means `branch-unavailable`; abnormal exits,
  unexpected stdout on that exit, or stderr on any branch probe fail closed as `git-unavailable`.
  Either successful branch tracking-config read emitting stderr now also fails as
  `git-unavailable`, matching the operating guide instead of trusting noisy identity data. Six
  regressions pin detached-HEAD, command-failure, and both successful-config diagnostic paths.
- The complete **2,109-test warnings-as-errors Python suite**, 166 focused host/source/scheduler/
  meta/documentation tests, repository Ruff and `server`/`tools` C90, Python and Bash syntax, diff
  hygiene, strict schema-v3 worktree audit, and empty-index gate pass. The preserved schema-v2
  recovery bundle verifies unchanged at 3,702,796,288 bytes, 28 tables, three prospective-evidence
  files, seven operational artifacts, database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, and manifest SHA-256
  `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
  Strict pre-ledger inventory remains 339 fully owned paths; release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`. Pre-ledger manifest
  identity is `8a740dac2dabc70982b1aaf4d3d5eee14c734066ade1ec1d5f45fcf1b0a67512`,
  working-tree identity is `6de96a09bd39e12b51bc618f8ca803b0ea7f3d5176b54d582613c08b236f423c`,
  and schedule-source identity remains
  `ae0242f1805aa5cf5b265930371e2bd83dec91dbaa90073c592f856b0a25daf1`.
- API-only deployment started PID 1427553 with zero restarts; UI remains PID 355332 with zero
  restarts; all eight API routes and four UI pages return HTTP 200. Automation remains `ok` at five
  production schedules plus one postflight with no pending changes and `Linger=yes`; the Friday
  receipt remains current at SHA-256
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`; all four miners are
  current, market freshness is `ok`, and the queue has zero actionable failures. Audit, recovery,
  protected-research, and prospective-evidence identities remain respectively
  `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`,
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`,
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`. No strategy,
  gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Made scheduler host-state classification fail closed on noisy or contradictory command results.
  Healthy service, enablement, and timezone observations now require one canonical stdout line, no
  stderr, and a return code consistent with the documented systemd state. Clean inactive states
  remain visible and the first valid `cron` observation survives an unavailable alternate `crond`
  probe. A successful crontab read rejects stderr, while the no-crontab special case now requires
  empty stdout and the canonical diagnostic prefix. Five regressions cover noisy success,
  ambiguous absence, contradictory exits, framing, and alternate-unit fallback; the operating
  guide records the boundary.
- The complete **2,114-test warnings-as-errors Python suite**, 125 focused scheduler/meta/
  documentation tests, repository Ruff and `server`/`tools` C90, Python and Bash syntax, diff
  hygiene, strict schema-v3 worktree audit, and empty-index gate pass. The preserved schema-v2
  recovery bundle verifies unchanged at 3,702,796,288 bytes, 28 tables, three prospective-evidence
  files, seven operational artifacts, database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, and manifest SHA-256
  `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
  Strict pre-ledger inventory remains 339 fully owned paths; release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`. Pre-ledger manifest
  identity is `0ad1aaa4193cdc5eabe466eaf88f9b1b78d2d38d04c369c84031d9ef1878ba13`,
  working-tree identity is `59a8f5ab201c9c97da2d06987e419b511bc52308bd9491c03fc44688e77607e9`,
  and schedule-source identity is
  `5f26fd81a31f4afb596eb0d0b9b03b624b93ae61965905ceee6bbcf61e0a774f`.
- API-only deployment started PID 1478889 with zero restarts; UI remains PID 355332 with zero
  restarts; all eight API routes and four UI pages return HTTP 200. The stricter live installer and
  `/meta` projection both report scheduler `ok`: five production schedules plus one postflight,
  active/enabled cron, UTC, safe writable logs, no pending changes, and `Linger=yes`. Friday's
  receipt remains current at SHA-256
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`; all four miners are
  current, market freshness is `ok`, and the queue has zero actionable failures. Audit, recovery,
  protected-research, and prospective-evidence identities remain respectively
  `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`,
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`,
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`. No strategy,
  gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Made failed host-probe cleanup best-effort and non-throwing. A process-group signaling error now
  falls back to directly killing the probe leader; signaling and bounded-reap OS errors are
  contained so scheduler/source-control callers retain their documented unavailable status instead
  of leaking cleanup exceptions into `/meta`. A direct regression exercises simultaneous group-
  kill, leader-kill, and reap failures, and the operating guide records the fallback.
- The complete **2,115-test warnings-as-errors Python suite**, 211 focused host/source/scheduler/
  meta/documentation tests, repository Ruff and `server`/`tools` C90, Python and Bash syntax, diff
  hygiene, strict schema-v3 worktree audit, and empty-index gate pass. The preserved schema-v2
  recovery bundle verifies unchanged at 3,702,796,288 bytes, 28 tables, three prospective-evidence
  files, seven operational artifacts, database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, and manifest SHA-256
  `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
  Strict pre-ledger inventory remains 339 fully owned paths; release identity is complete and
  non-releasable only for `dirty-working-tree` and `required-files-untracked`. Pre-ledger manifest
  identity is `4d2f67de6474e0a51c815351bacc976c515e20e0d787ac72e4d6442729119eb0`,
  working-tree identity is `85632c28b371dfae0ca39284083c34fc2f48dae524f836863191c9b8dd88c14f`,
  and schedule-source identity is
  `26466739b2dffdfc5c539554b8763658029dfd617161dc3146cdf11b100e1040`.
- API-only deployment started PID 1528715 with zero restarts; UI remains PID 355332 with zero
  restarts; all eight API routes and four UI pages return HTTP 200. Automation remains `ok` at five
  production schedules plus one postflight with no pending changes and `Linger=yes`; Friday's
  receipt remains current at SHA-256
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`; all four miners are
  current, market freshness is `ok`, and the queue has zero actionable failures. Audit, recovery,
  protected-research, and prospective-evidence identities remain respectively
  `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`,
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`,
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`. No strategy,
  gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Repaired the ordering of the six operational-hardening records added after the 2,085-test
  baseline. Their text and historical measurements are unchanged, but they now appear in actual
  completion order: structured upstream identity, bounded reap, strict count grammar, Git
  diagnostics, scheduler diagnostics, then non-throwing cleanup. A unique append-only tail marker
  now anchors future additions, and a documentation regression requires each recent record exactly
  once, in that order, with the marker at true EOF. The complete **2,116-test warnings-as-errors
  Python suite**, repository Ruff and `server`/`tools` C90, Python and Bash syntax, diff hygiene,
  strict schema-v3 worktree audit, and empty-index gate pass. The preserved schema-v2 recovery
  bundle verifies unchanged. Strict pre-entry inventory remains 339 fully owned paths; release
  identity is complete and non-releasable only for `dirty-working-tree` and
  `required-files-untracked`. Pre-entry manifest identity is
  `a7c0fcee200ecacb03d022cb01ef7504fa971b0e2066cdbfe2b35964a845c15d`, working-tree identity
  is `62ce468f2b82400a7afbec8bafb2be02a879ce238c13946e09e3cfbf76e25172`, and schedule-source
  identity remains `26466739b2dffdfc5c539554b8763658029dfd617161dc3146cdf11b100e1040`.
  No runtime source changed after the verified API deployment: API PID 1528715 and UI PID 355332
  remain active with zero restarts and `Linger=yes`. Audit, recovery, protected-research, and
  prospective-evidence identities remain respectively
  `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`,
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`,
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`. No strategy,
  gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Made source-control status one coherent optimistic snapshot. The read-only, network-free
  projection now captures the branch, tracking configuration, full/display upstream identity,
  cached upstream commit, and local `HEAD` commit; computes ahead/behind from the two immutable
  commit IDs; and publishes only after an identical second observation. Concurrent checkout,
  commit, tracking-config, or cached-ref changes therefore fail closed as the existing
  `invalid/git-unavailable` state instead of producing a mixed-instant relation. Stable
  `no-upstream` and `tracking-ref-missing` results receive the same second-observation guard. Mocked
  regressions cover each mutable identity and both local-only transitions, while a real temporary
  repository test moves the cached upstream ref between counting and validation. The operating
  guide documents this snapshot boundary; the public payload and browser vocabulary are unchanged.
- The complete **2,133-test warnings-as-errors Python suite**, 53 UI contract tests, repository
  Ruff and `server`/`tools` C90, Python and Bash syntax, diff hygiene, strict schema-v3 worktree
  audit, and empty-index gate pass. The preserved schema-v2 bundle and restored copy both verify at
  3,702,796,288 bytes, 28 tables, three prospective-evidence files, seven operational artifacts,
  database SHA-256 `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`,
  and verifier-reported manifest SHA-256
  `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
  Strict pre-ledger inventory remains 339 fully owned paths with an empty index; release identity is
  complete and non-releasable only for `dirty-working-tree` and `required-files-untracked`.
  Pre-ledger manifest identity is
  `2f301d2a53d7e9b72ae692f53c3d2cf6dfbcb4898c1d2a45e6b2ca9c7125445f` and working-tree
  identity is `63b8a8cb11b019e9aedb675d03511eb7f1572a1fa7b6b2b70c07ffaf7c22c892`.
- API-only deployment started PID 1633595 with zero restarts; UI remains PID 355332 with zero
  restarts, and both are active with `Linger=yes`. Ten fixed read-only API routes and all four UI
  pages return HTTP 200. Automation remains `ok` at five production schedules plus one postflight
  with no pending changes; Friday's current receipt remains SHA-256
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`; all four miners are
  current, market freshness is `ok`, and the queue has zero actionable failures. Audit, recovery,
  protected-research, prospective-evidence, and schedule-source identities remain respectively
  `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`,
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`,
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`,
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`, and
  `26466739b2dffdfc5c539554b8763658029dfd617161dc3146cdf11b100e1040`.
  Sector momentum remains `ACCUMULATING` at 5/200, E1 remains `ACCUMULATING` at 7/40 with
  negative mean net return, XS momentum remains `WAITING` at 0/48, and no research family is ready.
  No strategy, admission gate, generated evidence, database row, broker connection, or capital
  state changed; profitability remains unproven.
- Bounded the complete source-control snapshot to one command budget. Both stable observations and
  the immutable-ID ahead/behind calculation now share one request-local five-second deadline rather
  than receiving up to five seconds for each of fifteen Git subprocesses. Every launched command
  receives only the remaining time; an exhausted budget starts no further process and returns the
  existing fail-closed `invalid/git-unavailable` result. Context-local deadline state is reset even
  after an unexpected projection exception, so concurrent or later API requests cannot inherit it.
  Scheduler probes retain their documented independent per-command bounds, and the operating guide
  now distinguishes those two latency contracts.
- The complete **2,136-test warnings-as-errors Python suite**, repository Ruff and `server`/`tools`
  C90, Python and Bash syntax, diff hygiene, strict schema-v3 worktree audit, and empty-index gate
  pass. The preserved schema-v2 recovery bundle verifies unchanged at 3,702,796,288 bytes, 28
  tables, three prospective-evidence files, seven operational artifacts, database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, and verifier-reported
  manifest SHA-256 `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
  Strict pre-ledger inventory remains 339 fully owned paths with an empty index; release identity is
  complete and non-releasable only for `dirty-working-tree` and `required-files-untracked`.
  Pre-ledger manifest identity is
  `f472b733eacb5abc8ab02403d5ff35e2b1350773cb310a27e37bd41bb2e8534a` and working-tree
  identity is `f0ea841a71ecc35e4301e91a57222bae04431e731119652ed0677b340af44299`.
  Audit, recovery, protected-research, prospective-evidence, and schedule-source identities remain
  respectively `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`,
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`,
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`,
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`, and
  `26466739b2dffdfc5c539554b8763658029dfd617161dc3146cdf11b100e1040`.
  No strategy, gate, generated evidence, database row, broker connection, or capital state changed;
  profitability remains unproven.
- Consolidated host-projection deadlines into one shared command-budget primitive. The complete
  scheduler and source-control projections now each receive one context-local five-second budget;
  nested budgets retain the earliest deadline, each subprocess is clamped to the remaining time,
  and an exhausted budget launches nothing. Standalone installer probes retain their five-second
  per-command default. This prevents scheduler host failures from serially consuming roughly 25
  seconds and avoids duplicating deadline state between monitor modules. Tests cover nested
  clamping, expiry before process launch, context restoration, and both projection wrappers.
- Removed a UTC-midnight test race exposed during full verification. Earnings-window tests now use
  their existing injected-time seam and one fixed UTC instant instead of capturing the date at
  module import while production reads it at assertion time. Production risk logic and its
  seven-day earnings boundary are unchanged.
- The complete **2,140-test warnings-as-errors Python suite**, 53 UI contract tests, repository
  Ruff and `server`/`tools` C901, Python and Bash syntax, diff hygiene, strict schema-v3 worktree
  audit, automation drift audit, and empty-index gate pass. Both preserved schema-v2 bundle copies
  verify unchanged at 3,702,796,288 bytes, 28 tables, three prospective-evidence files, seven
  operational artifacts, database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, and verifier-reported
  manifest SHA-256 `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
  Strict pre-ledger inventory remains 339 fully owned paths with an empty index; release identity is
  complete and non-releasable only for `dirty-working-tree` and `required-files-untracked`.
  Pre-ledger manifest identity is
  `ca1ce3dec55d929977315dc81afa159c98adb01eb9c6a5ce792d0512b6334681` and working-tree
  identity is `1d6d519f8eb3cae0d11b3cc58a660a20daf9e9a547060f7c4c818e04a4f127e3`.
  Audit, recovery, protected-research, prospective-evidence, and schedule-source identities are
  respectively `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`,
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`,
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`,
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`, and
  `fff419b92ea97a00b3617a8d279cb422dd4313e3094c3fb1455552d4a20f7720`.
  No strategy, admission gate, generated evidence, database row, broker connection, or capital
  state changed; profitability remains unproven.
- Final API-only deployment started PID 1838468 with zero restarts; UI remains PID 355332 with
  zero restarts. Ten fixed read-only API routes and all four UI pages return HTTP 200, and the live
  `/meta` request completed in 0.44 seconds with scheduler `ok`, source control truthfully
  `local-only/no-upstream`, all four miners current, market freshness `ok`, and zero actionable queue
  failures. Automation remains `ok` at five production schedules plus one postflight with no
  pending changes and `Linger=yes`; Friday's current receipt remains SHA-256
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`. Sector momentum is
  still 5/200, E1 is 7/40 with negative mean net return, XS momentum is 0/48, and the 18/18
  walk-forward cohort is current. No family is ready and no automatic action is authorized.
- Made scheduler status one coherent optimistic snapshot. The read-only monitor now captures raw
  crontab text/error, daemon state and selected unit, boot enablement, timezone, executable driver
  sources, auxiliary launch readiness, managed log-target safety, and log-directory writability
  twice inside the shared five-second host-command budget. It evaluates and publishes only equal
  observations; a concurrent crontab, host-service, timezone, checkout-permission, or log-path
  transition returns the existing `invalid/projection-error` envelope instead of combining facts
  from different instants. Ten mocked field transitions and a real temporary-tree executable-mode
  transition exercise the boundary without changing scheduler configuration.
- The complete **2,151-test warnings-as-errors Python suite**, 53 UI contract tests, repository
  Ruff and `server`/`tools` C901, Python and Bash syntax, diff hygiene, strict schema-v3 worktree
  audit, automation drift audit, and empty-index gate pass. Both preserved schema-v2 bundle copies
  verify unchanged at 3,702,796,288 bytes, 28 tables, three prospective-evidence files, seven
  operational artifacts, database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, and verifier-reported
  manifest SHA-256 `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
  Strict pre-ledger inventory remains 339 fully owned paths with an empty index; release identity is
  complete and non-releasable only for `dirty-working-tree` and `required-files-untracked`.
  Pre-ledger manifest identity is
  `1b12d4962ca474346dd10573bde76a267a20e6b44cd6ecf4b0a5ff7406744b1d` and working-tree
  identity is `4225b82ab0b1f6536b978234921e4360dbe4f515777fa8b555ffa10ca85cec3d`.
  Audit, recovery, protected-research, prospective-evidence, and schedule-source identities are
  respectively `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`,
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`,
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`,
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`, and
  `923bddb67e56c29c6a405d55d73c943cb0a98b46ea47ba9c19241931867dd907`.
  No strategy, admission gate, generated evidence, database row, broker connection, or capital
  state changed; profitability remains unproven.
- Final scheduler-snapshot deployment started API PID 1890619 with zero restarts; UI remains PID
  355332 with zero restarts, and both services remain active with `Linger=yes`. Ten fixed read-only
  API routes and all four UI pages return HTTP 200. The live `/meta` request completed in 0.43
  seconds with scheduler `ok`, source control truthfully `local-only/no-upstream`, all four miners
  current, market freshness `ok`, and zero actionable queue failures. Automation remains `ok` at
  five production schedules plus one postflight with no pending changes, and Friday's current
  receipt remains SHA-256
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`. No research evidence
  or admission decision changed during deployment.
- Bound scheduler snapshot coherence to launch and log identities. The private observation now
  retains stable inode/metadata identities for every driver, the auxiliary postflight module and
  interpreter, and the log directory, so replacement by another still-readable or still-executable
  object cannot pass merely because its readiness boolean stayed true. Managed log targets retain
  inode/type identity only: replacement or disappearance is detected, while normal append growth
  remains valid. The refactor removed the superseded duplicate log helper. Integration-style tests
  replace an executable and a log file between complete observations and separately prove that an
  append does not cause a false `projection-error`.
- The complete **2,153-test warnings-as-errors Python suite**, 53 UI contract tests, repository
  Ruff and `server`/`tools` C901, Python and Bash syntax, diff hygiene, strict schema-v3 worktree
  audit, automation drift audit, and empty-index gate pass. Both preserved schema-v2 bundle copies
  verify unchanged at 3,702,796,288 bytes, 28 tables, three prospective-evidence files, seven
  operational artifacts, database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, and verifier-reported
  manifest SHA-256 `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
  Strict pre-ledger inventory remains 339 fully owned paths with an empty index; release identity is
  complete and non-releasable only for `dirty-working-tree` and `required-files-untracked`.
  Pre-ledger manifest identity is
  `03f8ab75cfc906cf95e4ab3d8c2a77d7f0b7ca5fd6339f3ea0b804e6b5778058` and working-tree
  identity is `b524166e70571a8f90e09c46123ea46c53310f6b5639ebfcce57f19cacb9e88c`.
  Audit, recovery, protected-research, prospective-evidence, and schedule-source identities are
  respectively `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`,
  `fed08155138997dbb95b715ad1fc32aea16e6c75b78496b4c71eb715084a3c66`,
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`,
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`, and
  `7e2a74c81d18d5d0774c77c40b62b3c193a04d5ce5cc55c70f944fdfdc8b4d34`.
  No strategy, admission gate, generated evidence, database row, broker connection, or capital
  state changed; profitability remains unproven.
- Recorded the final identity-aware scheduler deployment handoff. API PID 1943745 and UI PID
  355332 are enabled and active with zero restarts and `Linger=yes`; ten fixed read-only API routes
  and all four human-facing UI pages return HTTP 200. A live `/meta` request completed in 0.33
  seconds with scheduler `ok` at five production schedules plus one postflight, source control
  truthfully `local-only/no-upstream` without a network check, all four miners current, market
  freshness `ok`, zero actionable queue failures, and the 18/18 walk-forward cohort current. The
  read-only automation installer audit reports no pending changes, and Friday's receipt remains
  SHA-256 `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`.
  The coherent pre-entry release manifest is
  `935af07b46882520eadf0cd0f503b3e13c5ba0fa112780306eccbc89faee3144`, with working-tree
  identity `08d90d57d4909d5c70f8fe3b1e3e8a36996e83fcc041201956f8bce9297f995b`: all 339 changed
  paths are owned, the index is empty, identity is complete, and release remains blocked only by
  `dirty-working-tree` and 22 `required-files-untracked`. Protected research and prospective
  evidence remain respectively
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`. Sector momentum is
  still `ACCUMULATING` at 5/200, E1 is `ACCUMULATING` at 7/40 with negative mean net return and
  t-statistic, XS momentum is `WAITING` at 0/48, and no family is ready. No strategy, gate,
  generated evidence, database row, broker connection, or capital state changed; profitability
  remains unproven.
- Corrected cross-distribution cron-unit discovery without changing scheduler policy or installed
  automation. `systemctl is-active` reports a nonexistent unit as `inactive`, so probing `cron`
  before `crond` could attribute a stopped scheduler to the absent alias and hide an installed but
  failed `crond`. The read-only host probe now obtains `LoadState` and `ActiveState` together from
  one `systemctl show` call per candidate, skips only a validated `not-found` alias, preserves the
  first installed inactive/failed observation when no candidate is active, and reports `unknown`
  when both aliases are absent. Duplicate, missing, noisy, noncanonical, or undocumented property
  output still fails closed. New regressions cover active fallback, absent-alias/failed-unit
  attribution, both aliases absent, malformed observations, and the exact command shape; the
  operating guide documents the load-state boundary.
- The complete **2,155-test warnings-as-errors Python suite**, 53 UI contract tests, production UI
  build, repository Ruff and `server`/`tools` C901, Python and Bash syntax, frozen-lock checks,
  Python and npm production dependency audits, diff hygiene, strict schema-v3 worktree audit,
  read-only automation drift audit, and empty-index gate pass. Both matching schema-v2 recovery
  copies verify unchanged at 3,702,796,288 bytes, 28 tables, three prospective-evidence files,
  seven operational artifacts, database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, and verifier-reported
  manifest SHA-256 `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
  Strict pre-ledger inventory remains 339 fully owned paths with an empty index; release identity is
  complete and non-releasable only for `dirty-working-tree` and `required-files-untracked`.
  Pre-ledger manifest identity is
  `44d52d7e3ec14e7cc753c4c89d0c77155f7a7ebac51761adc210661ad03aa56f`, working-tree identity is
  `4a6bd65cbea5027031f209ef5d15b8cb9c86092ef2bf8b797f9108ae6ac63d2b`, and schedule-source
  identity is `6131c8c1134d4143d38004298d15bd35dc7168439a1a736ca7f8cf88b35e8fe3`.
  Protected-research and prospective-evidence identities remain respectively
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`; no strategy,
  admission gate, generated evidence, database row, broker connection, or capital state changed.
- API-only deployment of the load-state-aware scheduler probe started PID 2004362 with zero
  restarts; UI remains PID 355332 with zero restarts, and both units are enabled and active with
  `Linger=yes`. Ten fixed read-only API routes and all four human-facing UI pages return HTTP 200.
  The deployed `/meta` request completed in 0.78 seconds and reports the installed `cron` unit
  active and enabled, scheduler `ok` at five production entries plus one postflight, source control
  `local-only/no-upstream` without a network check, all four miners current, market freshness `ok`,
  zero actionable queue failures, and the 18/18 walk-forward cohort current. The independent
  installer dry-run also reports `ok` with no pending changes. Friday's receipt remains SHA-256
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`.
  Sector momentum remains `ACCUMULATING` at 5/200, E1 remains `ACCUMULATING` at 7/40 with
  negative mean net return and t-statistic, XS momentum remains `WAITING` at 0/48, and no research
  family is ready. No strategy, evidence, database, broker, or capital state changed during
  deployment; profitability remains unproven.
- Closed shell-grammar gaps in scheduler duplicate detection without changing the installed
  crontab. Alternate managed-driver and Friday-postflight invocations are now recognized after
  POSIX shell tokenization, including quoted command paths and paths immediately followed by a
  control operator such as `;`. The parser honors unquoted shell comments and applies cron's own
  first-unescaped-`%` command boundary before tokenization, so executable prefixes remain visible
  while escaped-percent literals, suffix lookalikes, quoted display text, and malformed shell text
  do not create false duplicates. Direct adversarial checks reproduce the old false `ok` result
  for `run_daily.sh;` and `tools.verify_friday_postflight;` and verify the corrected
  `misconfigured` result. Regression coverage includes command operators, quoting, cron stdin,
  comments, malformed quoting, escaped percent, and partial names; the operating guide records the
  parsing boundary.
- The complete **2,162-test warnings-as-errors Python suite**, repository Ruff and
  `server`/`tools` C901, Python and Bash syntax, diff hygiene, strict schema-v3 worktree audit,
  read-only automation drift audit, and empty-index gate pass. The unchanged UI had already passed
  all 53 contract tests, its production build, and the npm production dependency audit in this
  verification cycle; the frozen Python lock and production dependency audit also pass. Both
  matching schema-v2 recovery copies remain verified at 3,702,796,288 bytes, 28 tables, three
  prospective-evidence files, seven operational artifacts, database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, and verifier-reported
  manifest SHA-256 `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
  Strict pre-ledger inventory remains 339 fully owned paths with an empty index; release identity is
  complete and non-releasable only for `dirty-working-tree` and `required-files-untracked`.
  Pre-ledger manifest identity is
  `602f87541ad1003e447c7a9130381a163726b89b95318ce790744091bea2a729`, working-tree identity is
  `e66c3ec44d586a8c332a8b795b338eb61fb9b7c85c3db04d729117b062eff82b`, and schedule-source
  identity is `84ee0ee91633fdd085d03a8eebb756f166ddb96454f44f8b008e2aec146ac2e9`.
  Protected-research and prospective-evidence identities remain respectively
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`; no strategy,
  admission gate, generated evidence, database row, broker connection, or capital state changed.
- API-only deployment of the shell- and cron-aware duplicate detector started PID 2105160 with
  zero restarts; UI remains PID 355332 with zero restarts, and both units are enabled and active
  with `Linger=yes`. Ten fixed read-only API routes and all four human-facing UI pages return HTTP
  200. The deployed `/meta` request completed in 0.81 seconds with the installed `cron` unit active
  and enabled, scheduler `ok` at five production entries plus one postflight, source control
  `local-only/no-upstream` without a network check, all four miners current, market freshness `ok`,
  zero actionable queue failures, and the 18/18 walk-forward cohort current. The independent
  installer dry-run reports `ok` with no pending changes, and Friday's receipt remains SHA-256
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`.
  Sector momentum remains `ACCUMULATING` at 5/200, E1 remains `ACCUMULATING` at 7/40 with
  negative mean net return and t-statistic, XS momentum remains `WAITING` at 0/48, and no research
  family is ready. No strategy, evidence, database, broker, or capital state changed during
  deployment; profitability remains unproven.
- Tightened the atomic systemd service observation so only the coherent
  `LoadState=not-found`/`ActiveState=inactive` pair is treated as an absent distribution alias. A
  contradictory missing-but-active unit now fails closed as an unidentified service instead of
  being skipped; an adversarial regression fixes that invariant. The complete **2,163-test
  warnings-as-errors Python suite**, all 53 UI contract tests, the production UI build, repository
  Ruff and `server`/`tools` C901, Python compilation, diff hygiene, strict schema-v3 worktree audit,
  read-only automation audit, and empty-index gate pass. Pre-ledger manifest identity is
  `f3005392e99a7cfa4a296b1b9d19161ec9169cfb3287ae1dd514088b7da16643`, working-tree identity is
  `671aaffbd680b673960311675fe292d4d773d53bb8ddad0a2626cdff12f2c5b0`, and schedule-source
  identity is `710ea27676525d11945cd7c64d0eeb2b16626fe1684a42d7ad0e5bf6d362609f`.
  The 339-path inventory remains fully owned with an empty index, and release remains blocked only
  by `dirty-working-tree` and 22 `required-files-untracked`. Protected-research and prospective-
  evidence identities remain respectively
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`; no strategy,
  admission gate, generated evidence, database row, broker connection, or capital state changed.
- Final deployment of the coherent systemd-state invariant started API PID 2156508 with zero
  restarts; UI remains PID 355332 with zero restarts, both services are enabled and active, and
  `Linger=yes`. Ten fixed read-only API routes and all four human-facing UI pages return HTTP 200.
  `/meta` completed in 0.45 seconds with scheduler `ok` at five production entries plus one
  postflight, the installed `cron` unit active/enabled, source control
  `local-only/no-upstream` without a network check, all four miners current, market freshness `ok`,
  zero actionable queue failures, and the 18/18 walk-forward cohort current. The independent
  automation dry run is `ok` with no pending changes; Friday's receipt remains SHA-256
  `0b5b817408e2e6a0ebee0f18b9ca92fd55d030e50dee360dc7832140a18de2da`.
  Sector momentum remains `ACCUMULATING` at 5/200, E1 remains `ACCUMULATING` at 7/40 with
  negative mean net return and t-statistic, XS momentum remains `WAITING` at 0/48, and no research
  family is ready. The unattended system is healthy, but profitability remains unproven.
- Hardened scheduled-driver log interpretation at the final run boundary. Direct adversarial
  probes demonstrated that contradictory or duplicate terminals could previously select the
  newest terminal and report `ok`, malformed producer-looking terminals could masquerade as an
  unterminated run, and a malformed newest `run_*` start could be skipped so an older completion
  appeared current. The parser now requires at most one exact terminal after the newest valid
  start, treats malformed starts as hard boundaries, and reports dedicated `invalid` reasons for
  malformed or multiple terminal markers. Unrelated operational `TODO:` lines and the historical
  manual `=== marker:` records remain ordinary output. It also compares descriptor identity,
  mode, size, mtime, and ctime before and after parsing and against the visible path, so same-inode
  append/truncation and path replacement report `log-changed-during-read` instead of publishing a
  mixed snapshot. The browser contract and operator guide now enforce and explain those states.
- The final **2,174-test warnings-as-errors Python suite**, all 53 UI contract tests, production UI
  build, repository Ruff and `server`/`tools` C901, Python compilation, Bash syntax, frozen lock,
  Python and npm production dependency audits, diff hygiene, strict schema-v3 worktree audit,
  read-only automation audit, and empty-index gate pass. The pre-ledger manifest identity is
  `b18e210382db7f76cb4c3b3765f8bf9328fd1177d577102401f7800399806ab0`, working-tree identity is
  `6745b315f03b18443bf53a2c413d97c94c192bbde6f88805c11a2c018b340d4d`, schedule-source identity
  remains `710ea27676525d11945cd7c64d0eeb2b16626fe1684a42d7ad0e5bf6d362609f`, audit-source identity
  remains `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`, and recovery-source
  identity is `2b87079ff192b16cf96262d1923fc91c581b7d814360b297b2b2b2871faa39b9`.
  The 339-path inventory remains fully owned with an empty index, and release remains
  non-releasable only for `dirty-working-tree` and 22 `required-files-untracked`. Protected
  research and prospective-evidence identities remain respectively
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`;
  no strategy, admission gate, generated evidence, database row, broker connection, or capital
  state changed, and profitability remains unproven.
- Deployed the hardened driver-log reader and matching browser contract. API PID 2262807 and UI
  PID 2263236 are enabled, active, and at `NRestarts=0`, with `Linger=yes`. Ten fixed read-only API
  routes and all four human-facing UI pages return HTTP 200; `/meta` completed in 0.386 seconds and
  passes the browser contract. It reports scheduler `ok` at five production entries plus one
  postflight, the installed `cron` unit active/enabled, source control
  `local-only/no-upstream` without a network check, all four miners current, market freshness
  `ok`, zero actionable queue failures, and the 18/18 walk-forward cohort current. The previous
  walk-forward enqueue failure remains honestly visible as `recovered`; liquidity remains
  `not-yet-run` before its first Sunday slot. The independent automation dry run is `ok` with no
  pending changes. Both preserved schema-v2 recovery copies reverify at 3,702,796,288 bytes, 28
  tables, three prospective-evidence files, seven operational artifacts, database SHA-256
  `5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, and manifest SHA-256
  `7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`.
  Sector momentum remains `ACCUMULATING` at 5/200, E1 remains `ACCUMULATING` at 7/40 with negative
  mean return and t-statistic, XS momentum remains `WAITING` at 0/48, and no family is ready. The
  unattended system remains paper-only; profitability is not proven.
- Hardened the inaugural Sunday liquidity-evidence transition before its first 02:00 UTC run.
  Direct browser-contract probes showed that status-only validation accepted fabricated reasons,
  malformed timestamps, unsafe or irreconcilable counts, and extra private fields. The browser now
  accepts only the exact backend-produced envelope for neutral, updating, driver-failure, missing,
  stale, unknown, invalid, current, and source-download-issue states; it independently validates
  canonical dates/timestamps, safe integer bounds, download failure totals, and
  `liquid_before + admitted - demoted = liquid_after`. Backend reconciliation now also requires a
  successful artifact publication to fall within the exact driver run. Because metadata retains
  microseconds while the shell finish marker has whole-second precision, publication within the
  displayed finish second is accepted and the following second is rejected. Future-evidence
  classification precedes store-count comparison, preventing a future artifact from being
  mislabeled merely stale. Regression coverage includes every producer state, microsecond
  boundaries, store and scheduled-market mismatches, unavailable/behind market data, malformed
  driver finishes, unsafe integers, contradictory arithmetic, and extra fields.
- The final **2,189-test warnings-as-errors Python suite**, all 54 UI contract tests, production UI
  build, repository Ruff and `server`/`tools` C901, Python compilation, Bash syntax, frozen lock,
  Python and npm production dependency audits, diff hygiene, strict schema-v3 worktree audit,
  read-only automation audit, and empty-index gate pass. The pre-ledger manifest identity is
  `edd395b92e16ff32347b8ede8b6f4d1d36f02a0eed62871774e027c11a487283`, working-tree identity is
  `daf7f962378a8d86f962e37c738e8d057b25b95b0621d0026343ca665c3c29a0`, schedule-source identity
  remains `710ea27676525d11945cd7c64d0eeb2b16626fe1684a42d7ad0e5bf6d362609f`, audit-source identity
  remains `bc8bc8c2f59eaa4a7d376d4412a6d80853e376acd8207d632c81a60466da876a`, recovery-source identity
  remains `2b87079ff192b16cf96262d1923fc91c581b7d814360b297b2b2b2871faa39b9`, protected-research
  identity remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  The 339-path inventory remains fully owned with an empty index; release remains non-releasable
  only for `dirty-working-tree` and 22 `required-files-untracked`. No schedule, strategy, admission
  gate, generated evidence, database row, broker connection, or capital state changed.
- Deployed the exact liquidity-evidence producer/consumer boundary ahead of its inaugural Sunday
  run. API PID 2325585 and UI PID 2326027 are enabled, active, and at `NRestarts=0`, with
  `Linger=yes`. Ten fixed read-only API routes and all four human-facing UI pages return HTTP 200;
  `/meta` completed in 0.471 seconds and passes the tightened browser contract. At 01:10 UTC,
  before the 02:00 slot, `weekly_liquidity` remains `null` and `liquidity_evidence` remains the
  exact neutral `{status: not-yet-run, reason: no-scheduled-run}` envelope. The scheduler is `ok`
  with all five production entries plus the postflight, the installed `cron` service is active and
  enabled, and the independent automation dry run reports `ok` with no pending changes. The cron
  schedule itself was not changed or manually invoked; it remains responsible for the first
  unattended run. No research evidence or strategy state changed, and profitability remains
  unproven.
- Bound the strict liquidity-evidence schema to explicit producer and browser vocabularies. The
  backend now rejects any undocumented public status or reason before projection, while a
  cross-language test requires the JavaScript status/reason sets to equal those Python allowlists.
  This closes the maintenance path where a future producer branch could silently emit an envelope
  that the browser either rejected or accepted too broadly. Dedicated producer tests reject
  invented status and reason values. The complete **2,192-test warnings-as-errors Python suite**,
  all 54 UI contract tests, production UI build, repository Ruff and `server`/`tools` C901, Python
  compilation, Bash syntax, frozen lock, Python and npm production dependency audits, diff
  hygiene, strict schema-v3 worktree audit, read-only automation audit, and empty-index gate pass.
  Pre-ledger manifest identity is
  `2b6e2f72a6cdfebe465ca317a6ce7434aeb7a115d22c16d7903e81e1fdaec3e9`, working-tree identity is
  `bd3e4efbf0265e4d5480dcf1b6498b117ca914147eee39524b2f4e272bf7ec4c`, and protected-research and
  prospective-evidence identities remain respectively
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  The 339-path inventory remains fully owned with an empty index and the same two release blockers;
  no schedule, research, evidence, database, broker, or capital state changed.
- Deployed the parity-locked liquidity contract. API PID 2383429 and UI PID 2383870 are enabled,
  active, and at `NRestarts=0`, with `Linger=yes`. Ten fixed read-only API routes and all four
  human-facing UI pages return HTTP 200; `/meta` completed in 0.463 seconds, passes the browser
  contract, and still reports the exact neutral pre-run liquidity envelope. Automation remains
  `ok` with no pending changes. Post-ledger manifest identity is
  `48b0ae9ee565ebd4dabf59a455c5323dc54d97a510f98f6c6173a4ccd90db882`, working-tree identity is
  `e44657159155a113ba98fc93852f7659efa458c5095c70da64cf25aedf9571ec`, protected-research identity
  remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  The normal 02:00 UTC cron entry remains untouched and responsible for the first run.
- Closed a remaining liquidity-result honesty gap before the first unattended run. The producer
  already recorded resumable historical-backfill totals, but the public monitor reported `issues`
  only for candidate-download failures and could label a completed wrapper `current` despite
  nonzero backfill failures. Successful and degraded evidence now expose safe non-negative
  `backfill_processed` and `backfill_failed` counts, enforce `failed <= processed`, and distinguish
  candidate-only, backfill-only, and combined failures. These totals cover the complete pending
  liquid backfill set and therefore are deliberately not equated with names newly admitted in the
  current refresh. Zero-admission runs without a backfill block project explicit zero counts. The
  strict browser contract derives status/reason from both failure counters and rejects omitted,
  unsafe, or contradictory backfill accounting.
- The final **2,197-test warnings-as-errors Python suite**, all 54 UI contract tests, production UI
  build, repository Ruff and `server`/`tools` C901, Python compilation, Bash syntax, frozen lock,
  Python and npm production dependency audits, diff hygiene, strict schema-v3 worktree audit, and
  empty-index gate pass. The pre-ledger manifest identity is
  `1da8fcc70a15f543bc757c343612d08f317c72a1dd3b77aff6696e86f2fdf262`, working-tree identity is
  `dc1128c5a5cbab9f09b324f0a2b1e0abaf9e6b1d0593da09c6d85d362fec0be2`, and protected-research and
  prospective-evidence identities remain respectively
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53` and
  `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  The 339-path inventory remains fully owned with an empty index and the same two release blockers;
  no schedule, strategy, generated evidence, database row, broker connection, or capital state
  changed.
- Deployed the backfill-aware liquidity evidence projection. API PID 2443966 and UI PID 2444365
  are enabled, active, and at `NRestarts=0`, with `Linger=yes`. Ten fixed read-only API routes and
  all four human-facing UI pages return HTTP 200; `/meta` completed in 0.499 seconds and passes the
  browser contract. Before the first scheduled slot, the new success-only counters are correctly
  absent from the neutral `{status: not-yet-run, reason: no-scheduled-run}` envelope. Scheduler,
  market freshness, and miner evidence remain healthy, queue actionable failures remain zero, and
  the independent automation dry run is `ok` with no pending changes. Post-ledger manifest
  identity is `4a857502cd04da9fd5b54a34673e21d7de19ed1573888e364436c9cfbb7cc8d2`, working-tree identity is
  `9a735aa4fa1c545c07548187bfac43d0df79aa276c18d1f31e6c8ee50dd4f6f7`, protected-research identity
  remains `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`, and prospective-evidence
  identity remains `3ed9db8ff4bd9926d76d801f7e134e008d9b2f380b3ff3b3246ae38de7e23d1e`.
  The normal 02:00 UTC cron entry remains untouched and responsible for publishing the first real
  counters.
- 2026-09-13 · Closed the weekly liquidity producer's unattended retry gap before its first
  scheduled run. Every non-dry-run refresh now drains the complete resumable
  `liquid = TRUE AND backfill_done = FALSE` set even when the current refresh admits no names,
  and it always publishes an explicit backfill block, including `{processed: 0, failed: 0}` for
  an empty set. A failed ticker remains pending for the next weekly run. Integration tests prove
  zero-admission success marks an older pending ticker complete, zero-admission failure remains
  resumable and projects `issues/backfill-failures`, and an empty pending set performs no network
  backfill call. Dry-run behavior remains unchanged.
- Because `engine/collect.py` is deliberately inside the XS prospective monitor's frozen source
  boundary, the exact pre-signal `WAITING` checkpoint was explicitly migrated from runtime
  contract v10 to v11
  `2dc2b853419cadb448f45c2b895998be0f73c617183cd9c3afc70c53876b8455`. The guarded migration
  accepted only the existing zero-observation checkpoint with no signal boundary, and an
  independent structural comparison proved that exactly four runtime-contract metadata fields
  changed. XS remains paper-only `WAITING` at 0/48; strategy parameters, signal rules, execution
  economics, portfolio/database state, and return evidence did not change. The 18-result
  walk-forward cohort now truthfully reports `stale-source` against protected-research identity
  `8b07673b0d6e14522c3d8955c4c737f48f6f7d0116b0cc911f2148323146e35a` until the normal Sunday
  06:00 UTC revalidation; no artifact was reconstructed and no research job was launched early.
- Final verification passes all **2,202 warnings-as-errors Python tests**, all 54 browser contract
  tests, the production UI build, repository Ruff plus `server`/`tools` C901, Python and Bash
  compilation, frozen-lock validation, pinned Python and npm production dependency audits, fresh
  wheel/sdist builds, diff hygiene, strict schema-v3 worktree audit, and the empty-index gate. The
  pre-ledger manifest identity is
  `acdebd05163346f459a647ebee6da66c39cf091e11818220ecc8748d6559bdac`, working-tree identity is
  `50d5dc0f1c04cd08abe821513958cceb96ef7cd2a8a0c41bc3e58071a697a4c3`, protected-research
  identity is `8b07673b0d6e14522c3d8955c4c737f48f6f7d0116b0cc911f2148323146e35a`, and prospective-evidence
  identity is `737346d9827fc41d53a45ce70e94a44f3447c4e18f51f9bef80d13a8f4c23882`.
  The fully owned inventory is 340 paths (104 tracked modifications and 236 safe untracked files),
  with only `dirty-working-tree` and 22 `required-files-untracked` blocking release.
- API-only deployment started PID 2569078; UI remains PID 2444365. Both units are enabled and
  active at `NRestarts=0`, with `Linger=yes`. Ten fixed read-only API routes and all four
  human-facing UI pages return HTTP 200, live `/meta` passes the browser contract, and the
  independent automation audit is `ok` with no pending changes. At 01:32 UTC the first 02:00
  liquidity run remained unstarted with zero pending liquid backfills and the exact neutral
  `{status: not-yet-run, reason: no-scheduled-run}` envelope. The cron schedule was neither
  changed nor manually invoked and remains responsible for the real run.
- The identity snapshot taken immediately before this identity-record line had manifest
  identity
  `e5b4556c597c36f08248f27d88f7f854e97c3dc4510bb7e31435f15b70d0b600`, working-tree identity is
  `fa7a779905021c4887ba46e8034a2b976750780c7faf902dd825a74f71be962b`, protected-research
  identity remains `8b07673b0d6e14522c3d8955c4c737f48f6f7d0116b0cc911f2148323146e35a`, and prospective-evidence
  identity remains `737346d9827fc41d53a45ce70e94a44f3447c4e18f51f9bef80d13a8f4c23882`.
- Reconciled the undated documentation map, strategy decision ledger, and continuation handoff
  with the deployed v11 source transition. They now distinguish the latest published complete
  18-result cohort from a source-matching current cohort, identify the live
  `walkforward_evidence.status = stale-source` state and both source hashes, and direct operators
  to the normal Sunday 06:00 UTC revalidation without reconstructing or relabeling evidence.
  Historical BUILDLOG entries, dated audit snapshots, and generated cohort metrics remain
  untouched. The documentation/link/architecture focused suite passes, diff hygiene passes, and
  the Git index remains empty; no executable source, evidence, schedule, or runtime state changed.
- 2026-09-13 · The first independent Sunday liquidity refresh started from cron at 02:00:01 UTC
  and finished successfully at 02:05:14 UTC. It requested 8,293 active non-liquid candidates,
  admitted 141, demoted 162, and reconciled the liquid count from 4,118 to 4,097. The producer then
  drained the complete pending history set: all 138 names backfilled successfully, the latest job
  finished 138/138, and no liquid name remains pending. The public evidence honestly reports
  `issues/candidate-download-failures` because 69 candidate downloads failed; it does not hide
  those failures behind the successful reconciliation or backfill.
- Reconciled all 69 failures against the cached 13,214-row Nasdaq directory. Sixty-seven are
  rights, warrants, or separately traded units missed by the old singular-only checks, `FBYDP` is
  a preferred class, and `SVA` is an ordinary share for which Yahoo returned no data. Corrected
  the parser to recognize singular and plural rights/warrants, explicit preferred security-class
  phrases, and dedicated `.U`/terminal-`U` unit symbols while preserving authoritative ETFs,
  issuer names such as Preferred Bank, and common/limited-partnership units including CQP, ET,
  MPLX, and PAA. Against the cached directory, the corrected policy keeps 11,807 rows versus
  12,387 before, newly excludes 583 non-common rows, and restores three legitimate descriptive
  unit names. Its 13 active-liquid removals are genuine preferred/corporate-unit instruments and
  intersect neither held positions nor pending orders. No live universe or database row was
  changed by this parser correction.
- Because `engine/universe.py` is inside the XS prospective source boundary, explicitly migrated
  the exact pre-signal checkpoint from runtime-contract v11 to v12
  `158ed6666d4005c9a555f41ea829925503214838199e4887acfc94169b9c32d9`. A recursive before/after
  comparison proved that exactly the version, current digest, superseded digest, and migration
  explanation changed. XS remains paper-only `WAITING` at 0/48 with no signal boundary; strategy,
  signal, execution, statistical, portfolio, database, and return-evidence state did not change.
  The protected 111-file research identity is now
  `8c5a4e74716ff48ef730ad01c746c05c4fe242c6196f43fe174a04344c8fc165`; the published 18-result
  walk-forward cohort remains honestly `stale-source` pending its normal Sunday 06:00 UTC run.
  No artifact was reconstructed, no strategy was tuned, and no research job was launched early.
- Final verification passes all 2,205 warnings-as-errors Python tests, all 54 browser contract
  tests, the production UI build, repository Ruff plus the configured `server`/`tools` complexity
  gate, Python and Bash compilation, frozen-lock validation, pinned Python and npm production
  dependency audits, fresh source/wheel builds, documentation contracts, diff hygiene, strict
  schema-v3 worktree audit, and the empty-index gate. The pre-ledger manifest identity is
  `685f412293b25b472643bf9429806dad08bf2c5213a5ade53090927f7c790c32`, working-tree identity is
  `afc4e2ecc4fac26b93cf88ab19de56a058add894393cc6fb78d4e771f888c1da`, protected-research
  identity is `8c5a4e74716ff48ef730ad01c746c05c4fe242c6196f43fe174a04344c8fc165`, and prospective-evidence
  identity is `a5309551e3bdadcf98fe7966d5e095a2e15f0cb2a370a16880ac0f1f58b1d32e`.
  API PID 2685655 and UI PID 2444365 are active and enabled with `NRestarts=0` and `Linger=yes`;
  all checked read-only API routes and four human-facing pages return HTTP 200, live `/meta`
  passes the browser contract with XS v12 and the truthful liquidity issue, and the read-only
  automation audit is `ok` with no planned changes. Release remains blocked only by the existing
  dirty working tree and 22 required untracked files; no file was staged, committed, or pushed.
- 2026-09-13 · Closed the universe publisher's mixed-state failure window. Nasdaq directory
  inserts, metadata refreshes, deactivations, and the append-only daily snapshot now commit in one
  DuckDB transaction and roll back together on any error. The temporary registered relation is
  unregistered on both success and failure, the database connection closes on every main-path
  outcome, and the derived `data/universe.csv` is atomically replaced so readers never observe a
  torn export. In-memory integration tests prove rollback after a snapshot failure, relation
  cleanup after a real duplicate-key failure, preservation of existing membership/liquidity/
  backfill state, conservative defaults for new rows, deactivation without deletion, idempotent
  same-day snapshots, and atomic CSV publication. The normal weekday universe stage owns the next
  live reconciliation; no out-of-schedule database or historical-snapshot rewrite was performed.
- Explicitly migrated the unchanged zero-observation XS checkpoint from runtime-contract v12 to
  v13 `345fcea5fd72606b1fc3a0700c1b22c9c977f6ded0cbd5b297cd4c875b6de1d5` because
  `engine/universe.py` is frozen in that prospective boundary. A recursive audit again found
  exactly four changed metadata leaves. XS remains paper-only `WAITING` at 0/48 with no signal
  boundary; strategy, signal, execution, statistical, portfolio, database, and return-evidence
  state did not change. The protected 111-file runtime identity is now
  `0f626743a3a91cfeee237c3bf405c023e821e16be8f0bf64a1e536f211fea5b1`, and the normal Sunday
  06:00 UTC walk-forward revalidation remains solely responsible for publishing a matching
  historical cohort.
- Closed an intermittent release-manifest race exposed by the full suite. The scanner now retains
  device/inode identity for every parent component of the DuckDB path, while continuing to bind
  the database leaf by full metadata and rechecking the complete path identity at schema-open and
  after the manifest scan. Unrelated sibling-entry churn in a shared ancestor such as `/tmp` no
  longer creates a false unsafe result; actual leaf, symlink, parent, ancestor, and restored-swap
  replacements still fail closed. All 37 focused release-manifest tests pass, including the new
  shared-ancestor-churn regression and the existing adversarial replacement cases, and the formerly
  flaky deterministic-manifest test passed 50 consecutive repetitions.
- Final verification passes all **2,210 warnings-as-errors Python tests**, all 54 browser contract
  tests, the production UI build, repository Ruff plus the configured `server`/`tools` complexity
  gate, Python and Bash compilation, frozen-lock validation, Python and npm production dependency
  audits, a fresh wheel build, diff hygiene, and the empty-index gate. The pre-ledger manifest
  identity is `2b7375e2f91d28dcb05dc0ab858670d28f519e69bd962e123fd94f84c5532f2b`, working-tree identity is
  `aabe8d38e6f1cfe5b3bde0b581c102eba1a800ddc61e86b9083afb887e014fd5`, protected-research
  identity is `0f626743a3a91cfeee237c3bf405c023e821e16be8f0bf64a1e536f211fea5b1`, and prospective-evidence
  identity is `ca760d85c202f7f82f0c3bdc7a5da270059017f45716ad81bf6386740af12be2`.
  Release remains blocked only by the existing dirty working tree and 22 required untracked files;
  no file was staged, committed, or pushed.
- Deployed the v13 runtime to API PID 2899879; UI remains PID 2444365. Both units are enabled and
  active at `NRestarts=0`, with `Linger=yes`. Eleven checked read-only API routes and all four
  human-facing UI pages return HTTP 200, live `/meta` passes the browser contract with XS
  paper-only `WAITING` at 0/48, the truthful liquidity candidate-download issue, and the current
  protected source hash. The independent automation audit is `ok` with six managed cron entries
  and no planned changes. At 02:38 UTC the normal 06:00 Sunday walk-forward had not started; its
  schedule was left untouched and no duplicate run was launched.
- The identity snapshot taken immediately before this identity-record line had manifest identity
  `b48b1d1dc44840abd908f50342cb87d5881526c95fd27ef869bac516d808b7af`, working-tree identity
  `d855051951749c924d35ffe7b69c2ee1ea8dff37fda4721d36a5b28725fe0d48`, protected-research
  identity `0f626743a3a91cfeee237c3bf405c023e821e16be8f0bf64a1e536f211fea5b1`, and prospective-evidence
  identity `ca760d85c202f7f82f0c3bdc7a5da270059017f45716ad81bf6386740af12be2`.
- Clarified the disconnect-safe automation boundary against current official Codex guidance and
  the live host state. The six deterministic trading-engine cron entries and both enabled user
  services continue independently of this chat, but no Codex scheduled review is installed and
  `codex login status` reports `Not logged in`. A local-project Scheduled task would still require
  the computer and desktop app to remain running; any later model review must use an isolated
  worktree, a narrow sandbox, and report-only output because unattended full access is unsafe for
  this dirty evidence-bearing tree. No agent task, credential, schedule, strategy, or evidence was
  changed. Extended the append-only build-log ordering test through the Sunday liquidity/parser,
  v13 migration, release-manifest fix, deployment, and identity records so the newest history can
  no longer be silently duplicated or reordered.
- Final verification after that documentation-contract change passes all **2,212 collected Python
  tests** with warnings as errors, repository Ruff and the `server`/`tools` complexity gate,
  Python compilation, Bash syntax, diff hygiene, strict schema-v3 worktree ownership, and the
  empty-index gate. API health, `/meta`, `/research/readiness`, and the UI root return HTTP 200;
  both services remain active at `NRestarts=0`, and the automation dry run remains `ok` with six
  managed entries and no planned changes. The pre-ledger manifest identity is
  `f53d329ebe9bb5c7ef554d0ec8ad2c4ebb9f402b9eca531526eec6213e8e2a12`, working-tree identity is
  `be0204eecf0bdaf4ad6e45798497f7022291843a6610a3f1eb36df161bc32505`, protected-research
  identity remains `0f626743a3a91cfeee237c3bf405c023e821e16be8f0bf64a1e536f211fea5b1`, and prospective-evidence
  identity remains `ca760d85c202f7f82f0c3bdc7a5da270059017f45716ad81bf6386740af12be2`.
- Removed the final two production `assert` statements from the support/API layer so host-status
  probes remain fail-closed under optimized Python. The bounded subprocess runner now explicitly
  rejects and cleans up a malformed child missing either requested capture pipe, while the driver-
  log parser explicitly reports `invalid-started-at` if timestamp parsing returns no value without
  a reason. Direct regressions exercise both defensive states, including a `python -O` probe.
  CI and `CONTRIBUTING.md` now enforce Ruff `S101` over `server/` and `tools/`, alongside the
  existing complexity gate, preventing runtime assertions from returning to these fail-closed
  boundaries. This support-only change does not alter the frozen research runtime or evidence.
- The final **2,215-test warnings-as-errors Python suite** passes, as do repository Ruff, both
  support-layer C901/S101 gates, Python compilation, Bash syntax, diff hygiene, and the empty-index
  gate. The pre-ledger manifest identity is
  `857885720c808fac3016c78443382b9304fa78c3b9370d75be05d43915c89aac`, working-tree identity is
  `c090cf18b9fc9ffb035d4ef4f686070a64acad6d7ac27003ad94b3f071eb2bcd`, protected-research
  identity remains `0f626743a3a91cfeee237c3bf405c023e821e16be8f0bf64a1e536f211fea5b1`, and prospective-evidence
  identity remains `ca760d85c202f7f82f0c3bdc7a5da270059017f45716ad81bf6386740af12be2`.
  API-only deployment started PID 3060393 at `NRestarts=0`; all 12 checked read-only routes return
  HTTP 200, live `/meta` passes the browser contract, the UI remains healthy at PID 2444365, and
  the six-entry automation audit remains `ok` with no planned changes. The normal Sunday 06:00
  walk-forward remains unstarted at 02:56 UTC and was not invoked early.
- Removed the remaining replay-runtime assertion from `farm/backtest/replay.py`. The scratch
  database now fails explicitly unless it contains exactly one portfolio, preserving the
  one-book-per-job invariant under ordinary and optimized Python. Focused tests cover zero, one,
  and two portfolio rows, including a direct `python -O` two-row regression; all 10 backtest-grid
  tests and the 177-test backtest/provenance/walk-forward suite pass. The pre-edit replay source
  and protected-runtime checkpoint are preserved under
  `/tmp/replay-invariant-before.A53Jdb`; the protected 111-file runtime identity advanced from
  `0f626743a3a91cfeee237c3bf405c023e821e16be8f0bf64a1e536f211fea5b1` to
  `583c5c0f6be10cda5be45f24489402189bdc7a2c151fce80f83a5c1714d75acc`.
  `farm/backtest/replay.py` is outside the frozen XS and sector prospective runtime-contract
  lists, so neither prospective checkpoint was migrated and no evidence was rewritten. The
  historical 18-result cohort remains honestly `stale-source` until the normal Sunday 06:00 UTC
  revalidation; no strategy parameter, schedule, database state, or trading authority changed.
- Replaced all 22 removable assertions in the standalone corporate-actions shakedown with an
  explicit proof-failure primitive and descriptive `RuntimeError` diagnostics. Both ordinary and
  direct `python -O` regressions prove that a false condition still terminates the proof. The CI
  S101 gate now covers every executable package (`engine`, `farm`, `sim`, `server`, and `tools`),
  and the full scan finds no remaining runtime assertions. The pre-edit shakedown source and
  protected-runtime checkpoint are preserved under `/tmp/corp-shakedown-before.xJAfpj`; the
  protected 111-file runtime identity advanced from
  `583c5c0f6be10cda5be45f24489402189bdc7a2c151fce80f83a5c1714d75acc` to
  `d1e0849c8a4396f913869f84f2f945fe4fcb51e06579c6a91c65948fce5cfb4a`.
  This proof-only source is outside the frozen XS and sector prospective runtime contracts, so no
  checkpoint or evidence artifact was migrated or rewritten.
- Final verification passes all **2,221 warnings-as-errors Python tests**, all 54 browser contract
  tests, the production UI build, repository Ruff, support-layer C901, the repository-wide S101
  gate, Python compilation, Bash syntax, frozen-lock validation, Python environment compatibility,
  the npm production audit, diff hygiene, strict schema-v3 worktree ownership, and the empty-index
  gate. The pre-ledger manifest identity is
  `8f416c8c203180547de4181a50f21184e038924f987bbc7b740c6d40e08eac4c`, working-tree identity is
  `b8a4b9b7b5e84d69d7b40ed34120403757d41b0a7135a8f1287401f9af31e1b2`, protected-research
  identity is `d1e0849c8a4396f913869f84f2f945fe4fcb51e06579c6a91c65948fce5cfb4a`, and prospective-evidence
  identity remains `ca760d85c202f7f82f0c3bdc7a5da270059017f45716ad81bf6386740af12be2`.
  Both services remain active at `NRestarts=0`; live `/meta` reports the new source and the
  historical cohort as `stale-source`. The owned inventory is 329 paths (105 tracked modifications
  and 224 safe untracked files), with only `dirty-working-tree` and 22 required untracked files
  blocking release. Nothing was staged, committed, pushed, or run against the live database.
- Closed the failure-path DuckDB handles exposed by the new explicit replay/proof guards.
  Historical scratch construction now closes its connection on success and failure; replay closes
  the currently owned connection before deleting scratch state, including around the M1 screening
  reconnect; the M1 probe closes after a failed query; and corporate-action proof initialization
  and both proof arms close on every exit. Injected failures prove each ownership boundary and
  verify that replay scratch cleanup occurs only after connection closure. The focused 37-test
  replay/actions suite passes with warnings as errors, and static, compilation, S101, diff, and
  empty-index checks pass. The protected 111-file runtime identity advanced from
  `d1e0849c8a4396f913869f84f2f945fe4fcb51e06579c6a91c65948fce5cfb4a` to
  `000506ebe15ec9337ef650bff4881d2eb316be339dc8309bc88d580e94eed5d9`. These remain historical
  replay/proof-only changes outside the frozen XS and sector prospective contracts; no checkpoint,
  evidence artifact, live database, or schedule was changed.
- Final verification after the connection-ownership correction passes all **2,227
  warnings-as-errors Python tests**, all 54 browser contract tests, the production UI build and
  npm production audit, repository Ruff, support-layer C901, repository-wide S101, Python
  compilation, Bash syntax, frozen-lock and Python-environment checks, diff hygiene, strict
  schema-v3 worktree ownership, and the empty-index gate. The pre-ledger manifest identity is
  `1be6f938f780724c76c3f21cacf623f2aaecfdfa269f8e52fd16dd4e62b16c0f`, working-tree identity is
  `76e07c0840e8dc2208e04849e41873f41336d6a7a79d48037c3404a4e8a72ef7`, protected-research
  identity is `000506ebe15ec9337ef650bff4881d2eb316be339dc8309bc88d580e94eed5d9`, and prospective-evidence
  identity remains `ca760d85c202f7f82f0c3bdc7a5da270059017f45716ad81bf6386740af12be2`.
  API PID 3060393 and UI PID 2444365 remain active at `NRestarts=0`; live `/meta` reports the exact
  current source and `stale-source`. The inventory remains 329 owned paths with an empty index;
  release remains blocked only by the dirty working tree and 22 required untracked files.
- Applied the same exception-safe ownership rule to the scheduled walk-forward runner. A fold or
  report-preparation failure now closes the book's scratch DuckDB handle before its PID-namespaced
  scratch directory is removed. An injected fold failure proves both close and cleanup, and the
  complete 176-test walk-forward/provenance suite passes with warnings as errors. The protected
  111-file runtime identity advanced from
  `000506ebe15ec9337ef650bff4881d2eb316be339dc8309bc88d580e94eed5d9` to
  `2e9a74f24b77970c534778af5796ab683d33687c0eaf288798250c515f79d296`.
  The runner is outside the frozen XS and sector prospective runtime contracts, so no checkpoint
  or forward evidence was migrated. The normal Sunday 06:00 UTC job remains the sole owner of the
  next historical revalidation and was not started early.
- Final verification after walk-forward ownership hardening passes all **2,228
  warnings-as-errors Python tests**, repository Ruff, support-layer C901, repository-wide S101,
  Python compilation, Bash syntax, frozen-lock and Python-environment checks, documentation
  contracts, diff hygiene, strict schema-v3 worktree ownership, and the empty-index gate. The
  immediately preceding Python-only state also passed all 54 browser contract tests, the
  production UI build, and the npm production audit. The pre-ledger manifest identity is
  `6f7954af0bf9e487cc6ad10165fe9b7be8283422743c0ed702456913f71d246f`, working-tree identity is
  `98615b19b587474e78cbb31d2cc4f37c1d376773712a5df187a307e4bcd2370e`, protected-research
  identity is `2e9a74f24b77970c534778af5796ab683d33687c0eaf288798250c515f79d296`, and prospective-evidence
  identity remains `ca760d85c202f7f82f0c3bdc7a5da270059017f45716ad81bf6386740af12be2`.
  API PID 3060393 and UI PID 2444365 remain active at `NRestarts=0`; live `/meta` reports that exact
  current source and the expected `stale-source` cohort. The inventory remains 329 owned paths
  with an empty index, and release remains blocked only by the dirty tree and 22 required
  untracked files.
- Closed the remaining success-only DuckDB handles in the historical proof drivers. Screen-
  equivalence preparation and readback, replay-fidelity preparation and per-book comparison,
  machinery-shakedown screen lookup, its empty-window return, and its execution loop now close on
  every exit. Seven injected-failure tests cover all ownership boundaries without copying or
  running the large historical store. The protected 111-file runtime identity advanced from
  `2e9a74f24b77970c534778af5796ab683d33687c0eaf288798250c515f79d296` to
  `7d50ee1282edfbaddb9870f49afa0f532eb1061f729183813c719d5f55c7ecfc`.
  These proof-only changes are outside the frozen XS and sector prospective runtime contracts;
  no strategy, evidence artifact, live database, or schedule was changed, and the heavyweight
  proof harness was deliberately not launched alongside the normal Sunday schedule.
- Final verification after proof-driver ownership hardening passes all **2,235
  warnings-as-errors Python tests**, repository Ruff, support-layer C901, repository-wide S101,
  Python compilation, Bash syntax, frozen-lock and Python-environment checks, documentation and
  resource-ownership contracts, diff hygiene, strict schema-v3 worktree ownership, and the
  empty-index gate. The pre-ledger manifest identity is
  `d944658f3b971033c354c978cf2551a531c494f74cae4322ba68303d777432cd`, working-tree identity is
  `809e934285f9c74bdad306e99060f2b8b88b3f8e85e757f5b538588545235e43`, protected-research
  identity is `7d50ee1282edfbaddb9870f49afa0f532eb1061f729183813c719d5f55c7ecfc`, and prospective-evidence
  identity remains `ca760d85c202f7f82f0c3bdc7a5da270059017f45716ad81bf6386740af12be2`.
  API PID 3060393 and UI PID 2444365 remain active at `NRestarts=0`; live `/meta` reports the exact
  current source and `stale-source`. The owned inventory is 331 paths (106 tracked modifications
  and 225 safe untracked files), with only the dirty tree and 22 required untracked files blocking
  release. Nothing was staged, committed, pushed, or run against the live database.
- Extended exception-safe DuckDB ownership through the remaining non-frozen command-line
  boundaries found by a structural connection audit. The historical-screen and execution-drag
  readers now close on query, schema, and downstream failures; execution-drag releases its read
  lease before report calculation or publication. Both backtest and walk-forward queue grids now
  own schema initialization inside their cleanup boundary, as do the queue runner and the legacy
  dividend catch-up. Six injected-failure regressions exercise those exact boundaries. The scan's
  only remaining top-level owners are two helpers that deliberately return open handles and
  `engine/screen.py` / `sim/league.py`; the latter pair belongs to frozen prospective contracts and
  was left unchanged rather than triggering an unrelated evidence migration. The protected
  111-file runtime identity advanced from
  `7d50ee1282edfbaddb9870f49afa0f532eb1061f729183813c719d5f55c7ecfc` to
  `13c8c3df4fbf0be9d8e9cd920d21f4ac96d0cec443fd44c5d5575e6b9f4975f7`. The frozen XS, sector,
  and E1 runtime contracts and the prospective-evidence identity are unchanged; no strategy,
  admission gate, generated evidence, database row, broker connection, schedule, or capital state
  changed.
- Final verification after the command-line ownership pass has all **2,241 warnings-as-errors
  Python tests** passing, along with repository Ruff, support-layer C901, repository-wide S101,
  Python compilation, Bash syntax, frozen-lock and Python-environment checks, documentation
  contracts, diff hygiene, strict worktree ownership, and the empty-index gate. The pre-ledger
  manifest identity is `04c8741197332d0e63436d309fa10f145e4766c683f01f055344d8bf7289b8b0`,
  working-tree identity is `d813b4b51a0761b8f14e7b44ab081af5ba3fb43f845aa064898ab4eedc096d06`,
  protected-research identity is
  `13c8c3df4fbf0be9d8e9cd920d21f4ac96d0cec443fd44c5d5575e6b9f4975f7`, and prospective-evidence
  identity remains `ca760d85c202f7f82f0c3bdc7a5da270059017f45716ad81bf6386740af12be2`.
  The automation audit is `ok`: cron is active and enabled, user lingering is on, all six managed
  entries match source, and API PID 3060393 plus UI PID 2444365 remain active at `NRestarts=0`
  with both health endpoints returning HTTP 200. At 03:35 UTC the normal Sunday 06:00 walk-forward
  had not started and was not launched manually. The owned inventory is 346 paths (108 tracked
  modifications and 238 safe untracked files), with only the dirty tree and 22 required untracked
  files blocking release. Nothing was staged, committed, or pushed.
- Closed the final two owned runtime connection gaps with explicit prospective-contract
  migrations. `engine.screen.run` now delegates its unchanged screening body through one outer
  connection owner, and `sim.league.run` now closes through schema initialization, date
  resolution, initialization, no-portfolio, step, and exception exits. Direct injected schema and
  step failures prove both boundaries. A structural scan of every executable Python package now
  reports only three intentional connection factories/helpers that return or transfer their open
  handle; it finds no remaining success-only or exceptional-path owner. Because `engine/screen.py`
  and `sim/league.py` are frozen prospective dependencies, this was not treated as an invisible
  cleanup: sector runtime contract v4 was explicitly migrated to v5
  (`8e95ee4603923aa6d51faefedb0cb85800b018f927368a362fdefdb45622d7b9`) and pre-signal XS v13
  was explicitly migrated to v14
  (`71ed966bca01af6c5a4b9f9cbf00d67c115ecf17c1c3a607588d9c100dcf6d5a`). Both migration
  validators accepted the exact published checkpoint against the read-only live store. Recursive
  before/after comparison proves only runtime-contract version, current hash, superseded hash, and
  migration description changed: sector remains `ACCUMULATING` at 5/200 with identical baseline,
  equity-prefix, and forward-ledger hashes; XS remains `WAITING` at 0/48 with no signal boundary.
  Strategy rules, execution economics, statistical gates, database rows, and schedules are
  unchanged.
- Final verification after the explicit v5/v14 migrations has all **2,243 warnings-as-errors
  Python tests** passing, plus all 54 browser contract tests, repository Ruff, support-layer C901,
  repository-wide S101, Python compilation, Bash syntax, frozen-lock and Python-environment checks,
  documentation contracts, diff hygiene, strict worktree ownership, and the empty-index gate.
  The pre-ledger manifest identity is
  `1310f1932c11988368a654b8c6a0fbecab4dfecf545517600ab246da20b3cf7d`, working-tree identity is
  `7020cc3b707cb2e6cbaa155eebedbdef70bcd4a4f5edb61b24721f530c9ddab1`, protected-research
  identity is `66b796b7aaced84dd8a5dcb44f53c4b3217bb11ed667cf6e8a1b4fdefb09f86e`, and the explicitly
  migrated prospective-evidence identity is
  `dd5f9721511a71a7cade9bf235dbe6189bb41f5b5d6145aba82d9bd1666f502a`. API PID 3513447 and UI
  PID 2444365 are active at `NRestarts=0`; health, meta, research-readiness, and UI routes return
  HTTP 200. The deployed API projects sector v5 `ACCUMULATING` at 5/200 and XS v14 `WAITING` at
  0/48, both paper-only with no automatic action. At 03:43 UTC the normal Sunday 06:00
  walk-forward had not started and was not launched manually. The owned inventory is 348 paths
  (110 tracked modifications and 238 safe untracked files), with the dirty tree and 22 required
  untracked files still blocking release. Nothing was staged, committed, or pushed.
- Replaced the remaining direct writes of published runtime artifacts with the shared
  same-directory atomic writer. The raw Nasdaq directory cache, dated and latest screen Markdown,
  screen and per-ticker EOD CSVs, league Markdown/CSV, and monthly walk-forward Markdown/JSON can
  no longer be exposed as truncated files after a process interruption. The only remaining direct
  runtime-tree file write is inside the backup tool's private unpublished bundle, which is fully
  verified before the whole directory is atomically published. Four producer-level tests prove
  the universe cache, EOD export, league report, and monthly report route every target through the
  tested atomic primitive and leave no temporary residue. Because these publishers are frozen
  dependencies, sector v5 was explicitly migrated to runtime-contract v6
  (`43ff467d091a9777703c9a260899fc14c536a552dc28f2d5270034ca63ad2ffe`) and pre-signal XS v14
  to v15 (`28a53cfaaa4803d23123c7d7e9f3efbcec3f98b57da08f8f9522cc5926e544eb`). Both validators
  accepted the exact live checkpoint, and recursive before/after comparison again proves that only
  contract version, current hash, superseded hash, and migration text changed. Sector remains
  `ACCUMULATING` at 5/200 with identical baseline/equity/ledger hashes; XS remains `WAITING` at
  0/48 before its first signal. No strategy rule, execution assumption, statistical gate, database
  row, schedule, broker state, or capital state changed.
- Final verification after atomic publication and the explicit v6/v15 migrations has all **2,245
  warnings-as-errors Python tests** passing, all 54 browser contract tests, a production UI build,
  npm production audit with zero vulnerabilities, repository Ruff, support-layer C901,
  repository-wide S101, Python compilation, Bash syntax, frozen-lock and Python-environment checks,
  documentation contracts, diff hygiene, strict worktree ownership, and the empty-index gate. The
  pre-ledger manifest identity is
  `91e18cdc198109bbed06a855484c948fb79bb12f25c08a93259c232d3e49b229`, working-tree identity is
  `d82d05bd238d14c2cbce807beec10d1fb1924b709be571eacd1be82522297de5`, protected-research
  identity is `cfcdcb5dc3bb690567173dd87d85adff49e32b76863f4a8e0494f923dcf34592`, and the explicitly
  migrated prospective-evidence identity is
  `f0a5f66816104cc1ed677c07519e1958380e6ec7349593b224c9456225110e67`. API PID 3580600 and UI
  PID 2444365 are active at `NRestarts=0`; health, meta, research-readiness, and UI routes return
  HTTP 200. The deployed API projects sector v6 `ACCUMULATING` at 5/200 and XS v15 `WAITING` at
  0/48, both paper-only with no automatic action. At 03:49 UTC the normal Sunday 06:00
  walk-forward had not started and was not launched manually. The owned inventory remains 348
  paths (110 tracked modifications and 238 safe untracked files), with the dirty tree and 22
  required untracked files still blocking release. Nothing was staged, committed, or pushed.
- Closed the companion-artifact recovery gap after committed screen and league runs. An
  idempotently skipped screen now validates its stored report/rows and reconstructs the dated CSV,
  top-passing/watchlist EOD exports, latest summary, and shared metadata; an idempotently skipped
  league step reconstructs both Markdown and CSV reports from committed ledger state. The real
  recovery regressions prove the screen rows and all league ledger tables remain unchanged, while
  the artifact writers retain same-directory atomic replacement. Missing watchlist prices retain
  the established fail-soft EOD behavior. Because `engine/screen.py` and `sim/league.py` are frozen
  prospective dependencies, sector v6 was explicitly migrated to runtime-contract v7
  (`8bc5fae78807daadc9502060659a05df4ca022fb046ecea39b93b4d4ef0926b5`) and pre-signal XS v15
  to v16 (`86942578863d96b1005aab08ae06cd63e789874124f7b9c0da6cfced8b643d21`). Both validators
  accepted the exact read-only live checkpoint; canonical recursive comparison proved that only
  contract version, current hash, superseded hash, and migration text changed. Sector remains
  `ACCUMULATING` at 5/200 with identical baseline/equity/ledger hashes, XS remains `WAITING` at
  0/48 with no signal boundary, and E1 remains 7/40. No strategy rule, execution assumption,
  statistical gate, database row, schedule, broker state, or capital state changed.
- Final verification after the explicit v7/v16 migrations has all **2,246 warnings-as-errors
  Python tests** passing, all 54 browser contract tests, a production UI build, Python and npm
  runtime audits with zero known vulnerabilities, repository Ruff, support-layer C901,
  repository-wide S101, Python compilation, Bash syntax, frozen-lock and Python-environment checks,
  wheel packaging, documentation contracts, diff hygiene, strict worktree ownership, and the
  empty-index gate. The pre-ledger manifest identity is
  `9061522a056430e304d7a3ffb2a3b26c3dc4f079ee58fbc2834393a5a3a6917d`, working-tree identity is
  `a5ba582d2149cb5c1cdd63e5859c80941102f30d42456dce2938b28c316a08cd`, protected-research
  identity is `ba408869539beb89254cb663d33bd683dff278482b78b4222cf03dc99283163c`, and the explicitly
  migrated prospective-evidence identity is
  `896e242451fbe0812fdf24a487e3748d1b21a00ee7b59d913f6becc0b8c193aa`. API PID 3655268 and UI
  PID 2444365 are active at `NRestarts=0`; health, meta, research-readiness, and UI routes return
  HTTP 200. The deployed API projects sector v7 `ACCUMULATING` at 5/200, XS v16 `WAITING` at
  0/48, and E1 `ACCUMULATING` at 7/40, all paper-only with no automatic action. At 03:59 UTC the
  normal Sunday 06:00 walk-forward had not started and was not launched manually. The owned
  inventory remains 348 paths (110 tracked modifications and 238 safe untracked files), with the
  dirty tree and 22 required untracked files still blocking release. Nothing was staged,
  committed, or pushed.
- Removed the remaining unattended path that could recompute committed append-only screen rows.
  The dated Markdown report contains regime and exclusion context that `screen_results` does not,
  so a legacy or corrupt state with rows but no report now fails closed and preserves every row
  instead of deleting and rerunning that date. New screens atomically publish the dated recovery
  anchor before their row insert; an interruption before commit can therefore leave only a harmless
  orphan anchor that the next ordinary run overwrites, while an interruption after commit remains
  fully recoverable. Injected-failure tests prove both ordering and non-mutation. Because
  `engine/screen.py` is frozen in the pre-signal XS boundary, the exact v16 checkpoint was
  explicitly migrated to v17
  (`4c6bfa198684a82bf05d500856039214a2ad105ab63afa107eb36603bae42906`). The validator accepted
  the read-only live store, and canonical comparison proved that only contract version, current
  hash, superseded hash, and migration text changed. XS remains `WAITING` at 0/48 with no signal
  boundary; sector remains v7 `ACCUMULATING` at 5/200 and E1 remains 7/40. No database row,
  strategy rule, execution assumption, statistical gate, schedule, broker state, or capital state
  changed.
- Final verification after the explicit XS v17 migration has all **2,248 warnings-as-errors Python
  tests** passing, repository Ruff, support-layer C901, repository-wide S101, Python compilation,
  Bash syntax, frozen-lock and Python-environment checks, documentation contracts, diff hygiene,
  strict worktree ownership, and the empty-index gate. The unchanged frontend remains covered by
  the immediately preceding 54 browser tests, production build, and zero-vulnerability npm audit;
  the Python runtime audit likewise found no known vulnerabilities. The pre-ledger manifest
  identity is `682cb861cb8a7e7f1ad45934a1a002b2fff72aa4d5fc970a5ec02839aeb854ec`, working-tree identity
  is `2d719c20859d9c50d5ab525767d8276f48959c739a818a5d4174bd1e316c0f18`, protected-research
  identity is `fa9ec8c7959cadf854de57224bdc40092e985d1f5f4268db2f365d47d3fc15ce`, and the explicitly
  migrated prospective-evidence identity is
  `e269a873d76ac756861b69df86880fe95df1d456d9eb07efc7769f4454442f43`. API PID 3715439 and UI
  PID 2444365 are active at `NRestarts=0`; health, meta, research-readiness, and UI routes return
  HTTP 200. The deployed API projects sector v7 `ACCUMULATING` at 5/200, XS v17 `WAITING` at
  0/48, and E1 `ACCUMULATING` at 7/40, all paper-only with no automatic action. The normal Sunday
  06:00 UTC walk-forward was not launched manually. The owned inventory remains 348 paths (110
  tracked modifications and 238 safe untracked files), with the dirty tree and 22 required
  untracked files still blocking release. Nothing was staged, committed, or pushed.
- Removed the screener's last accidental borrowed-connection close. The inner `_run` helper now
  returns its no-eligible-names failure without closing the handle supplied by its outer owner; a
  regression proves that handle remains usable, and the outer `run` cleanup still closes it exactly
  once. A structural AST scan now reports only the queue runner's two intentional, documented
  close-and-rebind ownership transfers. Because `engine/screen.py` is frozen in the pre-signal XS
  boundary, the exact v17 checkpoint was explicitly migrated to v18
  (`1ddc09660316ab2479855298b73bd5c8481a76b7b93553d4963e3b92ceb13211`). The read-only live
  validator accepted it, and canonical comparison proved only contract version, current hash,
  superseded hash, and migration text changed. XS remains `WAITING` at 0/48 with no signal boundary;
  sector remains v7 `ACCUMULATING` at 5/200 and E1 remains 7/40. No database row, strategy rule,
  execution assumption, statistical gate, schedule, broker state, or capital state changed.
- Final verification after the explicit XS v18 migration has all **2,249 warnings-as-errors Python
  tests** passing, repository Ruff, support-layer C901, repository-wide S101, Python compilation,
  Bash syntax, frozen-lock and Python-environment checks, documentation contracts, diff hygiene,
  strict worktree ownership, and the empty-index gate. The unchanged frontend remains covered by
  the preceding 54 browser tests, production build, and zero-vulnerability npm audit. The
  pre-ledger manifest identity is
  `85aa667e5f1cf86dc025b75d6e8eb266aa13e62c3df1de321da2bbe48202e461`, working-tree identity is
  `feaefc9c53286bff3589ad68de7523bc496115429e2d642db421bc84383e29dc`, protected-research
  identity is `f20ea9a5322e13480b07c760af226dc7e7ec1b2d3e0aee56501352384bb22ad8`, and the explicitly
  migrated prospective-evidence identity is
  `053a552ba82117d03076579ae18bcd86488a8bd9d97d7058c5ce703df59866c9`. API PID 3772384 and UI
  PID 2444365 are active at `NRestarts=0`; health, meta, research-readiness, and UI routes return
  HTTP 200. The deployed API projects sector v7 `ACCUMULATING` at 5/200, XS v18 `WAITING` at
  0/48, and E1 `ACCUMULATING` at 7/40, all paper-only with no automatic action. The normal Sunday
  06:00 UTC walk-forward was not launched manually. The owned inventory remains 348 paths (110
  tracked modifications and 238 safe untracked files), with the dirty tree and 22 required
  untracked files still blocking release. Nothing was staged, committed, or pushed.
- Made every temporary DuckDB DataFrame registration exception-safe. The shared
  `engine.lib.db.registered_frame` context manager now unregisters its transient relation in a
  `finally` block, and all production registrations in ingestion, screening, universe sync,
  experiment persistence, and replay screen copying use that one lifetime boundary. A structural
  guard rejects raw registrations outside the helper; injected-failure regressions prove cleanup
  both at the helper and at the experiment/replay/universe callers. Because the helper and its
  callers are frozen prospective dependencies, the exact live checkpoints were explicitly
  migrated from sector v7 to v8
  (`c0788167bf63f734c6c9b3428b425a0054f1cead1754048aa00a6cc48eb5662f`), pre-signal XS v18 to
  v19 (`7f4085fca17872a9ef1125c64ed03f58b2191abe68286e9720441df74f8f06f3`), and E1 v4 to v5
  (`31ff0e06dad3ee1063dc25210cf049df5dffba1662621bc6a97de30e535420a2`). Read-only preflight and
  post-migration validation canonically proved that only runtime-contract version, current hash,
  superseded hash, and migration text changed. Sector remains `ACCUMULATING` at 5/200, XS remains
  `WAITING` at 0/48 with no signal boundary, and E1 retains its exact seven-observation prefix
  through 2026-08-31. No strategy rule, execution assumption, statistical gate, database row,
  schedule, broker state, portfolio state, or capital state changed.
- Final verification after the explicit v8/v19/v5 migrations has all **2,253 warnings-as-errors
  Python tests** passing, all 54 browser contract tests, a production UI build, a wheel build,
  Python and npm runtime audits with zero known vulnerabilities, repository Ruff, support-layer
  C901, repository-wide S101, Python compilation, Bash syntax, frozen-lock and Python-environment
  checks, documentation contracts, diff hygiene, strict worktree ownership, and the empty-index
  gate. The pre-ledger manifest identity is
  `da0c936c5cd7b881a349d7e1bde90b076ea996204d866d1792eeee332949f6a7`, working-tree identity is
  `2533e55378e98d9fb20a03bea1a625a50687c3ab1dc5d30d54a2becea53bb621`, protected-research
  identity is `16f391c935f90971765947c21f611e8ea4f53c6d6ec5c0eb9e725de64d4eefe0`, and the explicitly
  migrated prospective-evidence identity is
  `8e5dd48fd4e96ff7d4f2cc93dcb259c3f759dafcefa9a8f2d9175cb1a5e39f87`. API PID 3863516 and UI
  PID 2444365 are active at `NRestarts=0`; health, meta, research-readiness, and UI routes return
  HTTP 200. The deployed API projects sector v8 `ACCUMULATING` at 5/200, XS v19 `WAITING` at
  0/48, and E1 v5 `ACCUMULATING` at 7/40 with the unchanged negative running mean, all paper-only
  with no automatic action. At 04:36 UTC the normal Sunday 06:00 UTC walk-forward had not started
  and was not launched manually. The owned inventory is 351 paths (113 tracked modifications and
  238 safe untracked files), with the dirty tree and 22 required untracked files still blocking
  release. Nothing was staged, committed, or pushed.
- Made the signal breadth reader's temporary universe exception-safe. `src_breadth` now drops
  `_sig_universe` from its reusable caller-owned read connection in a `finally` block, including
  when its universe validation or breadth calculation fails. A real DuckDB injected-failure
  regression proves the relation is absent afterward, and the focused signals/queue integration
  suite passes. Historical-screen temporary tables remain scoped to scratch connections whose
  owners already close them on every exit, so this batch does not broaden into a strategy or replay
  rewrite. Sector v8, pre-signal XS v19, and E1 v5 hashes remain exact; no prospective artifact,
  database row, signal formula, strategy rule, execution assumption, schedule, broker state, or
  capital state changed.
- Final verification after breadth temporary-state cleanup has all **2,254 warnings-as-errors
  Python tests** passing, all 54 browser contract tests, a production UI build, Python and npm
  runtime audits with zero known vulnerabilities, repository Ruff, support-layer C901,
  repository-wide S101, Python compilation, Bash syntax, frozen-lock and Python-environment checks,
  documentation contracts, diff hygiene, strict worktree ownership, and the empty-index gate. The
  pre-ledger manifest identity is
  `135edeee5bb7698e047310b9b87a66e0a7eb1c11d757f6c1c9c06155337ba186`, working-tree identity is
  `77c20fbce1dccaaab1e816e3bdbae2c941d5928671b0aca055f62a56a509a618`, protected-research
  identity is `290d761477744c0f9f22dda2b2f563dd80fe9d3b36a6f74dbccba35b98859797`, and the unchanged
  prospective-evidence identity is
  `8e5dd48fd4e96ff7d4f2cc93dcb259c3f759dafcefa9a8f2d9175cb1a5e39f87`. API PID 3863516 and UI
  PID 2444365 are active at `NRestarts=0`; health, meta, research-readiness, and UI routes return
  HTTP 200, and automation audit status remains `ok`. At 04:42 UTC the normal Sunday 06:00 UTC
  walk-forward had not started and was not launched manually. The owned inventory remains 351
  paths (113 tracked modifications and 238 safe untracked files), with the dirty tree and 22
  required untracked files still blocking release. Nothing was staged, committed, or pushed.
- Made historical-screen temporary tables call-scoped on every exit. `screen_sessions()` now
  removes all `_hs_*` relations plus the optional leverage-exclusion table in a `finally` block,
  including when an intermediate ranking or insert statement fails. A real DuckDB regression
  injects a late failure, proves every temporary relation is gone, and proves the borrowed
  connection remains usable. Successful screen formulas, point-in-time membership, rankings,
  persisted rows, and universe policy are unchanged. Sector v8, pre-signal XS v19, and E1 v5
  hashes remain exact because this scratch replay helper is outside those contracts; no prospective
  artifact, database row, strategy rule, execution assumption, schedule, broker state, or capital
  state changed.
- Final verification after historical-screen temporary-state cleanup has all **2,255
  warnings-as-errors Python tests** passing, all 54 browser contract tests, a production UI build,
  Python and npm runtime audits with zero known vulnerabilities, repository Ruff, support-layer
  C901, repository-wide S101, Python compilation, Bash syntax, frozen-lock and Python-environment
  checks, documentation contracts, diff hygiene, strict worktree ownership, and the empty-index
  gate. The pre-ledger manifest identity is
  `ddc0f853f2021316f32f6fa751f71f48104fd3e0034bd423463afc41e4776e81`, working-tree identity is
  `2b821342b352aa0e5815a13765553c222cc358c88fef26c7064b6ba2f4fc6ecc`, protected-research
  identity is `8ed2b751127c17ab3631583ae4f0e9e87b8b041250263b447092c5c5c8711d90`, and the unchanged
  prospective-evidence identity is
  `8e5dd48fd4e96ff7d4f2cc93dcb259c3f759dafcefa9a8f2d9175cb1a5e39f87`. API PID 3863516 and UI
  PID 2444365 are active at `NRestarts=0`; health, meta, research-readiness, and UI routes return
  HTTP 200, and automation audit status remains `ok`. The normal Sunday 06:00 UTC walk-forward
  remains scheduled and was not launched manually. The owned inventory remains 351 paths (113
  tracked modifications and 238 safe untracked files), with the dirty tree and 22 required
  untracked files still blocking release. Nothing was staged, committed, or pushed.
- Centralized every explicit production DuckDB transaction. `engine.lib.db.transaction` now owns
  begin, commit, deliberate dry-run rollback, and failure rollback for all 17 former hand-written
  transaction blocks. Cleanup covers `BaseException`, so `KeyboardInterrupt` and `SystemExit`
  cannot leave a caller-owned connection inside an open transaction; if rollback itself fails, the
  original body or commit exception remains primary and receives the cleanup failure as a note.
  Real DuckDB regressions prove interrupted writes are absent and the same connection can begin and
  commit another transaction, while a synthetic rollback failure proves exception preservation. A
  structural test now rejects raw `BEGIN TRANSACTION`, `COMMIT`, or `ROLLBACK` literals outside the
  helper. Because the helper and converted callers are frozen prospective dependencies, read-only
  canonical preflight proved that only the four runtime metadata fields would change, then the
  exact checkpoints were explicitly migrated from sector v8 to v9
  (`c430b451ee510c858705ba4235f81b68f9d7443745a60b4716035acb32741788`), pre-signal XS v19 to
  v20 (`8bdfdf2ce028964de6c49d10a95132ac66d66e5a900b4173109355e1945d781e`), and E1 v5 to v6
  (`5a665966f7bad78474dab9367618aab4016ea847fec8bba9a92966e7706e5612`). Post-migration canonical
  comparison again found exactly version, current hash, superseded hash, and migration text changed.
  Sector remains `ACCUMULATING` at 5/200, XS remains `WAITING` at 0/48 with no signal boundary, and
  E1 retains its exact seven-observation prefix through 2026-08-31. No strategy rule, execution
  assumption, statistical gate, evidence row, database row, schedule, broker state, portfolio
  state, or capital state changed.
- Final verification after interruption-safe transaction cleanup has all **2,259
  warnings-as-errors Python tests** passing, all 54 browser contract tests, a production UI build,
  a wheel build, Python and npm runtime audits with zero known vulnerabilities, repository Ruff,
  support-layer C901, repository-wide S101, Python compilation, Bash syntax, frozen-lock and
  Python-environment checks, documentation contracts, diff hygiene, strict worktree ownership,
  and the empty-index gate. The pre-ledger manifest identity is
  `6f247ec1bfcabaf498d488e32ed83f55a3fda2a5908ad42df70f853701641b75`, working-tree identity is
  `ac31fb4ea316097d32b701c1996bd678203218838b7d47c2eef5aacb24c1c861`, protected-research
  identity is `2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75`, and the explicitly
  migrated prospective-evidence identity is
  `ddaa9c3841cd4f9973e71ff9e722584ee4679e907f96ecd5ec4da937a8651953`. API PID 4069169 and UI
  PID 2444365 are active at `NRestarts=0`; health, meta, research-readiness, and UI routes return
  HTTP 200. The deployed API projects sector v9 `ACCUMULATING` at 5/200, XS v20 `WAITING` at
  0/48, and E1 v6 `ACCUMULATING` at 7/40 with the unchanged negative running mean, all paper-only
  with no automatic action. Automation audit status is `ok`; at 05:00 UTC the normal Sunday 06:00
  UTC walk-forward had not started and was not launched manually. The owned inventory is 353 paths
  (115 tracked modifications and 238 safe untracked files), with the dirty tree and 22 required
  untracked files still blocking release. Nothing was staged, committed, or pushed.
- Locked the atomic-publication boundary against direct production path writes. A structural AST
  test now rejects `Path.write_text` and `Path.write_bytes` across `engine`, `sim`, `farm`,
  `server`, and `tools` outside the shared atomic publisher. The sole documented exception is the backup builder's copy
  into a private, unpublished staging directory: that complete bundle is independently verified,
  made durable, and atomically published without overwrite. The source audit found no other direct
  path writes, so this is a regression guard rather than a behavior rewrite. No frozen runtime
  source, prospective artifact, database row, strategy rule, execution assumption, schedule,
  broker state, portfolio state, or capital state changed.
- Final verification after the atomic-publication source guard has all **2,260
  warnings-as-errors Python tests** passing, repository Ruff, support-layer C901,
  repository-wide S101, Python compilation, documentation ordering/contracts, diff hygiene,
  strict worktree ownership, and the empty-index gate. The unchanged frontend remains covered by
  the immediately preceding 54 browser tests, production build, zero-vulnerability npm audit, and
  successful wheel build; the Python runtime dependency audit also found zero known
  vulnerabilities. The pre-ledger manifest identity is
  `47749faa05ad5bbe172d4b6e3742be9083d0527931e21239de49935474f3137a`, working-tree identity is
  `83cb0dc79f0f7c3bc7b983eadc3f889644a1d5423966954c5de29f400f2fb872`, protected-research
  identity remains `2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75`, and prospective-evidence
  identity remains `ddaa9c3841cd4f9973e71ff9e722584ee4679e907f96ecd5ec4da937a8651953`.
  API PID 4069169 and UI PID 2444365 remain active at `NRestarts=0`; health, meta,
  research-readiness, and UI routes return HTTP 200, and automation audit status remains `ok`.
  At 05:09 UTC the Sunday 06:00 UTC walk-forward remained pending and was not launched manually.
  The owned inventory remains 353 paths (115 tracked modifications and 238 safe untracked files),
  with the dirty tree and 22 required untracked files still blocking release. Nothing was staged,
  committed, or pushed.
- Made the next evidence-authorized strategy actions explicit. The current decision ledger now
  separates the scheduled 06:00 source-parity refresh from profitability evidence and orders the
  next valid actions by their actual gates: continue the three frozen prospective records; permit
  one theory-led intraday charter only after both intervals clear 252 qualifying sessions and one
  calendar year (no earlier than roughly 2027-07-08 under the current limiting series); and admit
  stock-selection or fundamentals research only after its three-year point-in-time gate (roughly
  July 2029 at the earliest). It also states that rejected forward tests are recorded rather than
  rescued by changing their rule, and that an independently acquired point-in-time source must be
  audited and separately versioned. Documentation regressions pin this queue and the current
  protected runtime identity. No experiment was launched, no charter or strategy was registered,
  and no evidence, database, portfolio, schedule, broker, or capital state changed.
- Made the evidence-authorized queue directly discoverable from both repository entry points.
  The root README and documentation map now link to the decision ledger's ordered “Next
  admissible actions” anchor, and a documentation regression prevents that operator path from
  being lost. The exact current tree passes all **2,261 warnings-as-errors Python tests**, all 54
  browser contract tests, the production UI build, a fresh Python wheel build, repository Ruff,
  support-layer C901, executable-source S101, Python compilation, Bash syntax, frozen-lock and
  Python-environment checks, strict pinned Python and production npm audits with zero known
  vulnerabilities, documentation contracts, diff hygiene, strict schema-v3 worktree ownership,
  the empty-index gate, and the drift-free six-entry automation audit. Before this ledger entry,
  release-manifest identity was
  `acaba69d1ae89ea4f85d84ad6e1b78b4845a65d8fd4a14ce3c6f7b6a2656574c` and working-tree
  identity was `8f0ef19c522e45ad50570cfe6f0fdeb13c22e3e0773b7c9885964b6fc5535a79`;
  protected-research identity remains
  `2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75` and prospective-evidence
  identity remains `ddaa9c3841cd4f9973e71ff9e722584ee4679e907f96ecd5ec4da937a8651953`.
  API PID 4069169 and UI PID 2444365 remain active at `NRestarts=0`; health, meta,
  research-readiness, and UI return HTTP 200. At 05:17 UTC the normal 06:00 walk-forward was
  still pending and was not launched manually. The owned inventory remains 353 paths (115
  tracked modifications and 238 safe untracked files), and release remains blocked only by
  `dirty-working-tree` and 22 `required-files-untracked`. Nothing was staged, committed, pushed,
  or run against the live database; no strategy, evidence, portfolio, schedule, broker, or
  capital state changed.
- Kept raw database values distinct from validated public values in the league-equity and
  position read models. This is behavior-preserving support-layer cleanup: validation results now
  use separate names instead of overwriting loop inputs, making the public trust boundary explicit.
  CI and the contributor guide now preserve the corresponding `PLW2901` support-layer gate. The
  141 focused read-model/route tests, the documentation contracts, repository Ruff, and combined
  support C90/PLW2901 checks pass; the exact post-change tree then passed all **2,261
  warnings-as-errors Python tests**. The protected 111-file research runtime is outside these
  edits and remains unchanged; no database, strategy, evidence, portfolio, schedule, broker, or
  capital state changed.
- Exact-tree verification after the support trust-boundary cleanup passes all **2,261
  warnings-as-errors Python tests**, all 54 browser contract tests, the production UI build, a
  fresh Python wheel, repository Ruff, support-layer C90/PLW2901, executable-source S101, Python
  and Bash compilation, frozen-lock/environment checks, pinned Python and production npm audits
  with zero known vulnerabilities, diff/index hygiene, strict worktree ownership, and the
  drift-free automation audit. The pre-ledger release-manifest identity is
  `b81cba2988c8be0fde687c61682769f1b0aae31f15ff465d4a420d02ffbaf37b` and working-tree identity
  is `2c3e0d3a8c30f8550f347a09b31641fcf460744bb0197090ffdc6209eabc43fe`;
  protected-research identity remains
  `2a45f846b7a4628661c4539adf71074377c529a450c90cb07cd4125aafed7d75` and prospective-evidence
  identity remains `ddaa9c3841cd4f9973e71ff9e722584ee4679e907f96ecd5ec4da937a8651953`.
  The API was restarted to load only this support-layer change and is healthy at PID 197489 with
  `NRestarts=0`; meta, research-readiness, and the unchanged UI return HTTP 200. At 05:30 UTC the
  06:00 walk-forward remained pending and was not launched manually. The owned inventory remains
  353 paths (115 tracked modifications and 238 safe untracked files); release remains blocked only
  by `dirty-working-tree` and 22 `required-files-untracked`. Nothing was staged, committed, or
  pushed.
- Removed the sole dead return intermediate in the recovery/support layer: the backup lock opener
  now returns its owned text handle directly after validating the descriptor. CI and contributor
  guidance add a support-layer `RET504` regression gate, and a high-confidence active-source
  dead-code scan found no removable definitions. All 186 focused backup/documentation tests and
  the exact **2,261-test warnings-as-errors Python suite** pass, as do repository Ruff,
  support-layer C90/PLW2901/RET504, executable-source S101, Python/Bash compilation, diff hygiene,
  strict worktree ownership, and the empty-index gate. This support-only cleanup does not change
  the protected research runtime, prospective evidence, database, strategy rules, schedules,
  portfolios, broker state, or capital authority.
<!-- buildlog-format-v2 -->
## 2026-09-18 — Operating contract: maintain mode, scope ledger, drift metrics, plans

- **Why:** owner review of 2026-09-18 (`docs/feedback.md`): loop had drifted into building
  governance for a broker that has no authority; asked for docs, metrics and feedback layers
  that stop long LLM sessions doing work not needed yet, plus follow-up plans.
- **What:** `AGENTS.md` + `CLAUDE.md` (contract, admission test, budgets, session shape, this
  entry format); `docs/scope.md` (in scope / not yet / never / parking list);
  `docs/scope-budget.json` (LOC ceilings for `server`, `tools`, research runtime; entry budget;
  doc-test ceiling); `docs/metrics.md` + `tools/metrics_snapshot.py` publishing
  `data/reports/metrics/`; `docs/feedback.md` seeded; `docs/plans/` P1–P4 proposed;
  `tests/test_operating_contract.py` enforcing all of it; banner on `live-readiness-goal.md`.
  No runtime, strategy, evidence, schedule, or database change.
- **Evidence:** `python -m tools.metrics_snapshot --check-budget` → `budget.ok = true`;
  `pytest -q -W error tests/test_operating_contract.py tests/test_docs*.py` green. Full suite on
  macOS: 345 failures, byte-identical set on untouched HEAD (pre-existing; upstream CI on `main`
  was already red after the 2026-09-17 commit with 42 C901 errors). No new failures.
- **Metrics:** server 45,769 (unchanged) · tools +331 (this tool) · product unchanged ·
  last-10-entry mean 741 lines, 913 hashes — the baseline this format replaces.
- **Next:** nothing admitted. Owner promotes P1 (recommended) in `docs/plans/README.md`.

## 2026-09-18 — Public release: history scrubbed, visibility flipped

- **Why:** owner decision (`docs/feedback.md`, second 2026-09-18 entry) to publish the repo as a
  showcase and case-study target for junxiong.dev/trading-engine.
- **What:** history rewritten with
  `git filter-repo --replace-text` / `--replace-message` for an employer email, the devbox home
  path, an internal tool name and an agent co-author trailer; force-pushed; visibility public.
  201 commits, dates unchanged. Backdating was requested and refused.
- **Evidence:** fresh clone, `git log main -p | grep -ciE '<the four patterns>'` → 0;
  `gh repo view --json visibility` → PUBLIC.
- **Metrics:** unchanged (docs only).
- **Next:** nothing admitted. Existing clones (devbox) must be re-cloned before the next session.

<!-- append-only-tail: insert new verified entries immediately above this line -->
