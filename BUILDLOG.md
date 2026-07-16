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

## Next

1. **Tonight 22:30 UTC**: verify cron ran clean (logs/cron.log, _meta.json, screen 2026-07-16 committed by sync.py). If clean → **stamp M0 exit** (backfill done + clean nightly over 4k+ names from cron). M1 exit still needs the GitHub remote (owner: create `ong6/trading-engine`, then `git remote add origin ssh://git@ssh.github.com:443/ong6/trading-engine.git` + pull on laptop).
2. M2 in flight: sim core (fills/portfolio/league/strategies) being built by Opus subagent against a **copy** of the DB. Do NOT wire league into run_daily.sh until after tonight's clean M0 run.
3. After M0 stamp: wire league into run_daily.sh; league goes live next nightly run.

## Blockers

- None hard. Soft: GitHub remote needed before M1 exit (owner action — create the repo).
