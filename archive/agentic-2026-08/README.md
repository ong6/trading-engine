# Archive — agentic layer (built 2026-08-04, retired 2026-08-18, archived 2026-09-03)

Frozen as it stood on retirement. Nothing here is imported, cron'd or tested; paths inside
the files still say `agents/…` and `engine/news_analyst*` because that is where they ran.
Design spec (private): store `trading/trading-engine/agentic-strategies-design.md`.

## What it was

Five league books whose **core is code** and whose AI agent (a `claude -p` session, zero tools,
one turn, JSON out) could only make bounded, pre-registered adjustments, each paired with a
frozen twin running the identical algorithm untouched. The spread vs the twin at 26 weeks
(2027-02-01) was the only pre-registered measure.

| AI book | twin | agent role | driver |
|---|---|---|---|
| `news_gated_momo` | `momo_stopped` | daily entry gate (veto / downscale, never add) | `agents/run_gaters.sh` |
| `earnings_context_pead` | `pead_ear` | daily entry gate | `agents/run_gaters.sh` |
| `adaptive_mr` | `adaptive_mr_frozen` | weekly parameter tuner inside charter bounds | `agents/run_tuners.sh` |
| `agentic_alloc` | `agentic_alloc_frozen` | weekly sleeve-weight tuner | `agents/run_tuners.sh` |
| `stop_tuner_turtle` | `turtle` | weekly stop tuner | `agents/run_tuners.sh` |

Plus the **news analyst** (`engine/news_analyst.sh` + `news_analyst_prep.py` + `_prompt.md`):
an 11:00 UTC weekday brief over RSS headline titles for the watchlist, holdings and macro
context, written to `data/reports/news/<date>.md`. The gaters read that brief.

Layout here (structure preserved from the repo root):

| path | contents |
|---|---|
| `agents/<book>/charter.md` | frozen charter — bounds block is what `validator.py` enforced |
| `agents/<book>/lessons.md`, `changes.jsonl`, `proposals/` | append-only agent memory / change log (one applied row, `earnings_context_pead`) |
| `agents/earnings_context_pead/gate-2026-08-04.json` | the only gate file ever produced |
| `agents/{gater,tuner}_prep.py`, `*_prompt.md`, `validator.py`, `report.py` | prep, prompts, code-side validator, AI-vs-twin scoreboard renderer |
| `agents/run_gaters.sh`, `agents/run_tuners.sh`, `engine/news_analyst.sh` | cron drivers |
| `data/reports/agentic/` | scoreboard, frozen at 2026-08-17, stamped RETIRED |
| `data/reports/news/` | the one brief the analyst ever produced (2026-08-04) |
| `data/news_analyst_state.json`, `data/news_positions_cache.json` | analyst cursor + last-good holdings snapshot |

## Why it was retired (BUILDLOG 2026-08-18)

Every `claude -p` session failed from **2026-08-05 to 2026-08-17** — 10 analyst runs, both daily
gaters, all three weekly tuners. Root cause was an expired subscription OAuth token, not code;
the fail-open contract held (no gate file → pure algo) so nothing traded on guessed input. The
defect was the silence: a 13-day outage surfaced only as `TODO:` lines in an untailed log.
The operator chose to **remove the crons rather than repair them** — the token spend was not
wanted. The AI acted on exactly one session (2026-08-04), so the AI-vs-twin pairs sat at
identical returns and the 26-week criterion never accrued valid evidence.

## What is still live

The seven books (`news_gated_momo`, `earnings_context_pead`, `adaptive_mr`, `agentic_alloc`,
`stop_tuner_turtle`, `adaptive_mr_frozen`, `agentic_alloc_frozen`) remain rows in `portfolios`
with `active = FALSE` (seven `portfolio_retired` rows in `audit_log`, actor
`operator.retire_agentic`). They were **retired, not killed**. Their `sim_equity` history is
kept; they do not step, order or appear in `league.md`. They still appear by id in
`sim/strategies/configs.py` (registration record) and in `data/reports/walkforward/` as
NO-DATA rows. `sim/strategies/base.py::apply_agent_gate` still exists: it returns the algo
orders unchanged when `settings.AGENTS_DIR` (default `agents/`) does not exist.

## Re-enabling

1. `git mv archive/agentic-2026-08/agents agents` and
   `git mv archive/agentic-2026-08/engine/news_analyst* engine/`; move `data/…` back likewise.
   `AGENTS_DIR` defaults to `agents/`, so the gate read resumes with no code change.
2. Re-activate the books: `UPDATE portfolios SET active = TRUE WHERE id IN (…)` via the
   sanctioned writer, with a matching `audit_log` row.
3. Crontab (from BUILDLOG 2026-08-04/18):
   ```
   0  11 * * 1-5  <repo>/engine/news_analyst.sh >> <repo>/logs/news-analyst-cron.log 2>&1
   40 21 * * 1-5  <repo>/agents/run_gaters.sh   >> <repo>/logs/agentic-gater-cron.log 2>&1
   30 10 * * 0    <repo>/agents/run_tuners.sh   >> <repo>/logs/agentic-tuner-cron.log 2>&1
   ```
   and restore the `agentic-report` stage in `engine/run_daily.sh` (`python -m agents.report`),
   fixing `report.py` to filter `active = TRUE` first.
4. A valid `claude` login on the box (`~/.claude/.credentials.json`), and a health check that
   makes a failed session loud — the reason it died unnoticed.

## Public-readiness note

`data/reports/news/2026-08-04.md` (and its `latest.md` copy) was assembled from the owner's
private `watchlist.md` and `market-context.md`: it restates personal trading theses
(CBOE / VIRT thesis legs, the Hormuz / USD "war-premium unwind" read, 50d-reclaim triggers)
and names watchlist and paper-book holdings as of that date. No credentials or account data;
`news_analyst_prep.py` references `~/news-scraper/data/news.jsonl` by path only. Decide
before making the repo public whether that brief stays; nothing here has been deleted.
