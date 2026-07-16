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

## Done

- 2026-07-16 · Environment truth pass (table above). Stooq contingency triggered → yfinance is primary.
- 2026-07-16 · Repo scaffolded at `~/trading-engine` (git init, local-only), `.venv` with Python 3.12 + deps.

## Decisions

- 2026-07-16 · **yfinance is the primary EOD source** (Stooq blocked from this network — spec §3 contingency). `source` column = 'yfinance'.
- 2026-07-16 · **Universe list via HTTPS nasdaqtraded.txt** with browser UA + retries; completeness check = `File Creation Time:` footer present, else retry/keep last good file. FTP unusable.
- 2026-07-16 · **Repo local-only** (no GitHub CLI on box). M1's sync exit criterion needs a remote — flag to owner before M1 completes: create `ong6/trading-engine` on GitHub and we'll add the SSH remote.
- 2026-07-16 · Owner directive: **Fable plans, Opus subagents write code** (token efficiency). Verification still done by running end-to-end in the main loop.
- 2026-07-16 · Backfill is a **resumable job** in a minimal DuckDB `jobs` table from day one (§12.7: no ad-hoc pools; backfill of ~5k names must survive interruption).

## Next

1. M0 code: `lib/db.py` (schema), `universe.py` (nasdaqtraded → universe + append-only snapshot), `collect.py` (yfinance batch backfill --full, incremental daily), `run_daily.sh`, requirements.
2. Run universe build end-to-end; then start max-history backfill (long-running, resumable).
3. Nightly cron entry (6:30pm ET trading days, market-calendar gated) + `_meta.json` health output.
4. M0 exit: `_meta.json` shows a clean nightly run over ~4k+ names from cron, backfill done.

## Blockers

- None hard. Soft: GitHub remote needed before M1 exit (owner action — create the repo).
