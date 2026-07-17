# BUILDLOG — trading-engine

Source of truth for build state. Read at the start of every loop iteration; trust this over
remembered state. Specs live in `../personal-data-store/trading/` (engine design §12 wins on
conflict; execution design §7 has exit criteria).

## Current phase: M0 — scaffold + full-universe EOD collect + nightly cron

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

## Next

1. **After tonight 22:30 UTC**: verify cron ran clean end-to-end (logs/cron.log shows `=== done`, _meta.json last_run stamped by cron, screen 2026-07-17 committed by sync.py). If clean → **stamp M0 exit** (backfill done + clean nightly over 4k+ names from cron). M1 exit still needs the GitHub remote (owner: create `ong6/trading-engine`, then `git remote add origin ssh://git@ssh.github.com:443/ong6/trading-engine.git` + pull on laptop).
2. After M0 stamp, wire the nightly: league step + intraday enqueue/drain into run_daily.sh (league live + archive daily from the next nightly run). Then the M3 exit demonstration: owner (or browser automation) submits a discretionary paper trade through the UI's gates end-to-end on the real DB.
3. M4 continues: experiment framework (pre-registered configs, locked holdout, results table, report generator) with E1 SPY-Monday as the first pre-registered report; then fundamentals weekly + earnings calendar daily miners as queue job types.

## Blockers

- None hard. Soft: GitHub remote needed before M1 exit (owner action — create the repo).
