# Architecture & open-source readiness review — 2026-09-02

Scope: the working tree at `master` (158 commits, no remote), ~20k lines of tracked Python across
`engine/` (6.3k), `farm/` (6.3k), `sim/` (4.6k), `agents/` (1.8k, retired), `server/` (1.0k), plus a
29-file Next.js `ui/`. Read: `README.md`, `docs/how-it-works.md`, `.gitignore`, `BUILDLOG.md`
(head + 2026-08-18 onward), every shell driver, every `__init__.py`, the DB/queue/sync modules,
and the import graph. Nothing was edited or committed.

---

## Part A — Architecture

### A1. Module boundaries and the dependency graph

Measured with `grep -rnE "^\s*(from|import) +(engine|sim|farm|server|agents|lib)"` over the five
packages (81 internal import lines, 33 of them `from lib import ...`).

```
engine/lib/{db,resources,leverage}      <- leaf; imported by everyone as bare `lib` (NOT `engine.lib`)
engine/*.py  (collect, screen, actions, universe, intraday, earnings, fundamentals, signals, verify)
        |-- lib only, except actions.py -> sim.schema
sim/    (schema, fills, portfolio, calendar, league, strategies/*)
        |-- lib.db (league.py, shakedowns); strategies/base.py -> agents/ DIR via AGENTS_DIR env
server/ (main, db, risk, sizing)
        |-- lib.db, sim.league (private helpers _max_drawdown/_spy_return!), sim.schema
farm/   (experiment, experiment_runner, stats, autopsy, execution_drag, backtest/, walkforward/, sweep/)
        |-- lib.db, lib.leverage, sim.league, sim.portfolio, sim.schema, sim.strategies.configs, sim.fills
engine/queue_runner.py
        |-- lib + farm.backtest.replay + farm.sweep + farm.walkforward.runner + engine/{intraday,...}
agents/ (retired) -- sim.portfolio, sim.strategies, lib.db
```

Layering intent is `lib -> engine/sim -> farm -> queue_runner`, and it mostly holds. Three real
violations:

| Edge | Where | Why it matters |
|---|---|---|
| `engine/queue_runner.py -> farm.*` | `engine/queue_runner.py:130-146` | The nightly driver's queue imports research code; a farm import error breaks the nightly's farm section (pinned exit 0, so survivable, but the layering is inverted) |
| `server/main.py -> sim.league._max_drawdown, _spy_return` | `server/main.py:28-30` | API depends on underscore-private helpers of a batch module |
| `sim/strategies/base.py -> agents/` | `sim/strategies/base.py:24-26, 309` | Core strategy base class reads gate files from the retired agents tree |

**`engine/` is not a package.** There is no `engine/__init__.py`; every entry point does
`sys.path.insert(0, <engine dir>)` so `from lib import db` resolves. That is **40 `sys.path.insert`
sites in 30 files**, four distinct idioms (`parent`, `parents[1]/"engine"`, `REPO_ROOT`, `if _p not in
sys.path`), and `engine/lib/db.py:20-23` explicitly says it duplicates `server/db.py`'s
`_LOCK_MARKERS` because a proper import "would be a cycle". This is the single largest source of
accidental coupling and the reason nothing can be `pip install -e .`'d or unit-tested in isolation.

### A2. Duplication

| Cluster | Files | Verdict |
|---|---|---|
| Shell drivers | `engine/run_daily.sh`, `run_weekly_walkforward.sh`, `run_weekend_sweeps.sh`, `run_weekly_verify.sh`, `agents/run_gaters.sh`, `run_tuners.sh`, `news_analyst.sh` | Same 25-line preamble (resolve root, flock on fd 9, `PY=`, `LOG=`, tee block) copied 7 times. Extract `engine/lib/driver.sh` (sourced), keep bodies. Zero runtime risk. |
| Stats | `farm/stats.py` (Sharpe/DSR/bootstrap CI, 298 lines) vs `farm/backtest/stats.py` (equity-curve CAGR/vol/DD/worst-month, 129 lines) | Different jobs; both define `max_drawdown` with different input conventions (returns vs equity). Rename to `farm/stats/{inference,equity}.py` or merge under one module with one drawdown function. |
| `*_prep.py` | `engine/news_analyst_prep.py`, `agents/gater_prep.py`, `agents/tuner_prep.py` | `utcnow`, `read`, `connect_ro` (retry loop) copy-pasted 3x. All retired with the agentic layer; move together to `agents/` or `archive/`. |
| Read-only connect with retry | 9 definitions: `lib.db.connect`, `server/db._connect`, `farm/experiment._connect_ro/_connect_rw_retry`, `farm/autopsy.connect_readonly`, `verify_prices._connect_ro`, 3x `connect_ro` in prep files | One `lib.db.connect(path, read_only=..., wait_s=...)` should serve all. Today `lib.db.connect` has no `read_only` parameter, which is *why* everyone rolls their own. |
| Small helpers | `utcnow` x4, `_pct` x6, `_num` x6, `_median` x4, `_table_exists` x3, `_select_universe` x4, `write_reports` x4 | Belongs in `lib/`. |
| REPO_ROOT resolution | 28 files compute `Path(__file__).resolve().parents[N]` with N varying by depth | One `lib.paths.REPO_ROOT`. |

### A3. Configuration and hardcoded paths

Grep `"/data00\|/home/jun.ong"` over `*.py *.sh *.md *.mjs *.js *.json` (excl. `node_modules`,
`BUILDLOG.md`, `data/`) — **14 hits in 10 files**:

| File:line | Content | Fix |
|---|---|---|
| `engine/screen.py:55` | `WATCHLIST_PATH = Path("/data00/home/jun.ong/personal-data-store/trading/watchlist.md")` | env `TRADING_ENGINE_WATCHLIST`, default None → skip |
| `engine/news_analyst_prep.py:36` | `STORE = Path("/data00/home/jun.ong/personal-data-store/trading")` | same env; module is retired anyway |
| `engine/news_analyst.sh:19`, `agents/run_gaters.sh:19`, `agents/run_tuners.sh:20` | `export HOME="${HOME:-/data00/home/jun.ong}"` | drop the default (cron sets HOME) |
| `ui/run_ui.sh:10` | `export PATH=/data00/home/jun.ong/tools/node/bin:$PATH` | `NODE_BIN` env or rely on PATH |
| `engine/run_weekly_verify.sh:23-24`, `run_weekend_sweeps.sh:20-21`, `run_weekly_walkforward.sh:14-15` | cron examples in comments | replace with `$REPO_ROOT` placeholder |
| `docs/how-it-works.md:149,151` | restart instructions | placeholder |

The nightly path (`run_daily.sh` → collect/screen/actions/league/sync/queue) is **already
path-independent** except `screen.py:55`, which is a soft dependency (watchlist ∪ passing). Good.
Existing env knobs are ad hoc: `TRADING_ENGINE_DB` (server only — `lib.db` ignores it),
`TRADING_ENGINE_LOCK_WAIT_S`, `TRADING_ENGINE_DRAIN_BUDGET_S`, `TRADING_ENGINE_AGENTS_DIR`,
leverage `POLICY_ENV`. There is no single settings module; the DB path is resolved in two places
with different rules (`engine/lib/db.py:18` vs `server/db.py:17,29`).

### A4. The DuckDB single-writer rule — structural or convention?

**Convention, with three partial structural guards.** DuckDB itself enforces one writer per file at
the OS level; the engine's job is to avoid *colliding* with it.

- Structural: `flock` on `.nightly.lock` / `.walkforward.lock` / `.sweeps.lock` / `.verify.lock`
  (per driver, not shared) and `.queue-drain.lock` (`queue_runner.py:391-414`, taken *before*
  connecting — correct ordering). `server/db.py` maps a contended lock to HTTP 503 rather than
  waiting. Parallel children are forced `read_only=True` (`cmd_run_one`, `queue_runner.py:297-330`).
- Convention: there are **four independent write-open paths** — `lib.db.connect`
  (`engine/lib/db.py:40`), `server/db.write_con` (`server/db.py:52`),
  `farm/experiment._connect_rw_retry` (`farm/experiment.py:661`), and any `scratch/*.py`. Nothing
  stops a new module from calling `duckdb.connect(path)` directly; `farm/experiment.py` already
  does. The two lock-marker tuples (`lib/db.py:23-28`, `server/db.py:20`) differ in content
  (`"lock"` alone in server matches more) and are hand-synced.
- The 2026-08-19 incident (7h40m 503 outage, BUILDLOG 2026-08-20) was exactly this class: the
  drain legitimately held the writer. Fixed by releasing the lock during parallel batches, but the
  fix is a discipline inside `queue_runner`, not a property of the connection layer.

Making it structural is cheap: one `lib.db.connect(read_only=...)` that every module must use,
plus a `ruff`/grep CI rule forbidding bare `duckdb.connect(` outside `lib/db.py`.

### A5. Job queue

`engine/queue_runner.py` (649 lines) is the best-designed component: a `jobs` table with
`queued/pending/running/done/failed`, priority ordering, idempotent enqueue (dedup on
`(kind, params)`), stale-`running` reclaim on next drain, resource guards (load 28 / 8 GiB free /
48 GB RAM budget / disk watchdog), a 4h drain budget that stops *starting* rather than killing,
and `parallel_safe` batching of adjacent same-priority read-only kinds via subprocesses. Every
constant is annotated with the measurement that set it (2026-08-20). Weak points:

- `JOB_TYPES` loaders do their own `sys.path.insert` per kind (`:118-146`) — packaging fixes this.
- Child exit code is the whole protocol; a child that hangs is bounded only by the 4h budget.
  No per-job timeout column.
- `run_daily.sh` embeds enqueue policy (priorities 100/105/110/120, Friday gate) in bash; a
  `queue_runner.py --enqueue-nightly` subcommand would make it testable.
- Dedup is on identical params only; no notion of "supersede older pending of same kind".

### A6. Error handling and logging

No `logging` module anywhere: **289 `print(` calls in 36 files**, prefixed by hand (`[db]`,
`[queue]`, `[sync]`, `[farm]`). 75 `except Exception` sites, mostly with the reason annotated
(`# noqa: BLE001 - lock contention is expected`). Zero bare `except:`. Failure semantics are
deliberate and well documented in `run_daily.sh` (fatal vs WARN-continue per stage) and the farm
subshell pins exit 0. Consistent in spirit, uncheckable in practice: nothing can raise the log
level, filter a subsystem, or emit JSON for `_meta.json`. The BUILDLOG's own recurring lesson
("the defect is the silence" — 13-day agentic outage; stale marks; inert books) is a logging and
alerting gap, not a code-path gap.

### A7. Tests

**None.** No `tests/`, `conftest.py`, `test_*.py`, or `pytest` in requirements (`.pytest_cache/`
is in `.gitignore`, suggesting it was once run ad hoc). Verification is "prove by running" on a
store copy, logged in BUILDLOG, plus `sim/*_shakedown.py`, `farm/backtest/proofs.py`, and
`docs/repro_fill_integer_clamp.py`. Those are excellent *integration* proofs but they need a
multi-GB store and are not repeatable by anyone else. Pure functions that deserve unit tests
today: `sim/fills.py` (slippage, liquidity cap, integer clamp), `sim/portfolio.py`,
`farm/stats.py` + `farm/backtest/stats.py`, `engine/lib/leverage.py` classifier,
`farm/walkforward/protocol.py` fold dates, `server/risk.py` gates, `sim/calendar.py`.

### A8. Packaging

`engine/requirements.txt` only (unpinned lower bounds; no `numpy`/`pyyaml` though both are
imported — `farm/stats.py`, `farm/experiment.py`). No `pyproject.toml`, no lockfile, no
`__init__.py` in `engine/`, no console entry points. Python 3.12 assumed via `.venv`. `ui/` has
`package.json` + `package-lock.json` tracked and `node_modules/`, `.next/` correctly ignored;
`ui/README.md` is untouched create-next-app boilerplate.

### A9. The retired `agents/` layer

1.8k lines Python + 7 markdown charters + 5 `changes.jsonl` + 2 shell drivers, all live in tree
and still imported: `sim/strategies/base.py` resolves `AGENTS_DIR` and reads gate files at `:309`;
`engine/run_daily.sh:99-107` carries the commented-out stage. `agents/report.py` selects books
without the `active` filter (BUILDLOG 2026-08-18). Retired but not quarantined — a reader of the
public repo will assume it works.

### Verdict

**Sound:** the data honesty model (append-only PIT tables, next-open fills, pre-registration with
kill criteria) is encoded in the schema and drivers, not just prose. `run_daily.sh`'s stage/failure
table is exemplary. The queue is measured, resumable, and priority-correct. `BUILDLOG.md` is the
best engineering log I have reviewed in a personal repo; the 2026-08-20 "inert book" class fix at
the measurement layer is exactly the right place.

**Top 5 structural debts (ranked by blast radius):**

1. `engine/` is not a package → 40 `sys.path` hacks, `lib` vs `engine.lib` ambiguity, no
   installability, no tests.
2. Single-writer discipline lives in four connect functions and comments, not one gateway.
3. Zero automated tests; all proof requires the 3.4 GB live store.
4. Config is scattered: hardcoded `/data00/home/jun.ong` in 10 files, DB path resolved two ways,
   env knobs undocumented.
5. Retired `agents/` still wired into `sim/strategies/base.py` and 7 near-identical shell
   preambles.

### Refactor plan — incremental, nightly-safe

Rule for every step: land on a branch, run `sim/backtest_shakedown.py` + one `run_daily.sh` dry
pass on a store copy (`TRADING_ENGINE_DB=...`), merge before 22:00 UTC, watch `logs/cron.log`.

| Step | Change | Nightly risk | Effort |
|---|---|---|---|
| 0 | Add `pyproject.toml` (name `trading_engine`, deps from requirements + numpy + pyyaml, `pytest` extra, ruff config). Do **not** yet change imports. | none | 1h |
| 1 | Add `engine/__init__.py`; add `lib/__init__.py` shim at repo root doing `from engine.lib import *`? No — instead make `engine.lib` canonical and add a one-line `sys.path` bootstrap module `_paths.py` that all entry points import. Cut 40 sites to 1. | low — each file diff is 1-3 lines, greppable | 3h |
| 2 | `lib.db.connect(path=None, *, read_only=False, wait_s=None)`; honour `TRADING_ENGINE_DB`; delete the 8 other connect helpers one file at a time. Add CI grep: `duckdb.connect(` allowed only in `engine/lib/db.py`. | low; server first (503 path already tested) | 3h |
| 3 | `lib/settings.py`: `REPO_ROOT`, `DB_PATH`, `WATCHLIST_PATH` (optional), `NODE_BIN`; remove all 14 hardcoded paths. | none | 1h |
| 4 | `tests/` with pytest for the pure modules in A7, tiny in-memory DuckDB fixtures (`duckdb.connect(":memory:")` + `init_schema`). Target 30 tests, <10 s. | none | 1 day |
| 5 | `engine/lib/driver.sh` sourced by the 4 live drivers (preamble only; bodies untouched). Ship one driver per night. | low | 2h |
| 6 | Move `agents/` + `engine/news_analyst*` + prep files to `archive/agentic-2026-08/` (or a git tag + delete); make `sim/strategies/base.py` gate-file read a no-op when `AGENTS_DIR` is absent. | low — books are `active=FALSE` | 2h |
| 7 | `logging` with a `[tag]` formatter that preserves current log text byte-for-byte; convert `print(` per module. Optional; do last. | low | 1 day |
| 8 | GitHub Actions: `ruff` + `pytest` on push; a nightly-independent smoke that builds the schema in `:memory:` and runs one strategy on synthetic bars. | none | 2h |

Steps 0-3 remove debts 1, 2, 4 in under a day and unblock everything else.

---

## Part B — Public readiness

### B1. Secret and personal-data scan

**Secrets — clean.** `git log -p --all | grep -inE "(api[_-]?key|secret|token|password|...|AKIA|ghp_|sk-|xox)"`
returned only prose ("Please supply a token" error tables, "zero tokens", ticker `TKNQ`,
`ANTHROPIC_API_KEY` mentioned by name in comments). No credential files were ever added
(`git log --all --diff-filter=A --name-only | grep -iE "\.env|\.pem|\.key|credentials|id_rsa|token"`
→ empty). `.env*`, `*.pem` are ignored in `ui/.gitignore` only — add them to the root `.gitignore`.

**Personal / corporate data — several items to fix before going public:**

| Item | Where | Severity | Action |
|---|---|---|---|
| Git author on all 158 commits: `jun.ong <jun.ong@bytedance.com>` | history | **High** for public — reveals employer + corporate email | `git filter-repo --mailmap` to a personal identity before the *first* push; trivially done now with no remote, painful later |
| Home path `/data00/home/jun.ong` | 10 files (A3) + ~10 BUILDLOG lines | Medium — username + corp box layout | fix per A3; BUILDLOG lines are history, scrub with sed |
| GitHub handle `ong6`, SSH key filename `~/.ssh/id_ed25519_github` | `BUILDLOG.md:116,1129-1130,1934` | Low (public handle anyway); key *name* is harmless | optional |
| "corp tool (`galaxy_selector.py`)" at `/usr/local/bin/gh`, box specs, network/TLS-interception notes | `BUILDLOG.md` Environment truth table, 2026-08-18 | Low-Medium — fingerprints an internal corporate environment | scrub the tool name; keep the rest |
| Sibling `../personal-data-store/trading/` links | `README.md:12`, `docs/how-it-works.md:9-11`, `BUILDLOG.md:4`, `screen.py:55`, `news_analyst_prep.py:36` | Medium — broken for every reader; points at a private repo | replace with a `docs/design/` copy of the two spec files, or a "specs are private" note |
| News briefs containing the owner's trading theses and market read | `data/reports/news/2026-08-04.md`, `latest.md` (built from the private `watchlist.md`/`market-context.md`) | Medium — personal opinions on named stocks, published under a Claude-generated byline | drop from public tree (retired feature); keep in private history or `git rm` + filter |
| `ui/AGENTS.md` / `ui/CLAUDE.md` | Next.js agent-rule boilerplate | none | keep or delete |
| No hits for `tiktok`, `byted.org`, corp proxies | — | — | — |

### B2. Repo hygiene — tracked data

`git count-objects -vH`: 5,760 loose objects, **54.6 MiB**, never packed (`git gc` will roughly
halve it). `.git/` is 56 MB. Tracked files by top dir: `data/` **614** of 792.

| Path | Files | Size | Belongs in git? |
|---|---|---|---|
| `data/screens/*.{csv,md}` | 66 | 20 MB | **No.** ~550 KB CSV/day forever; 34 versions already. Move to a `data` branch or GitHub Release asset; keep `latest.md` only |
| `data/eod/*.csv` | 281 | 6.6 MB | **No.** Yahoo-derived OHLCV redistributed publicly is a ToS grey area and grows daily. Gitignore; regenerate from the store |
| `data/universe.csv` | 1 | 860 KB, 34 versions (largest blobs in history) | Borderline — Nasdaq symbol directory is public; but 30 MB of history for a derived file. Snapshot table already lives in DuckDB → gitignore |
| `data/reports/backtests/**`, `walkforward/**`, `sweeps/**` (incl. 194 `results/*.json`) | 245 | 3.2 MB | Yes for markdown reports (they are the evidence). JSON results are fine at this size; cap growth by committing only the latest per book |
| `data/reports/league.{md,csv}`, `_meta.json`, `experiments/` | ~5 | small | Yes |
| `data/reports/agentic/`, `data/reports/news/`, `data/news_*` | 11 | 56 KB | Retired; see B1 |

Untracked lock files `.queue-drain.lock`, `.sweeps.lock`, `.verify.lock` are not in `.gitignore`
(only 5 of the 8 locks are). Replace the list with `*.lock`. `data/_meta.json` is modified in the
working tree by the last nightly (expected; `sync.py` picks it up).

Recommended split: **public `master` = code + docs + markdown reports; `data/screens`, `data/eod`,
`data/universe.csv` gitignored**, with `engine/sync.py` pushing them to an orphan `data` branch
(one `git worktree`, same cron, no change to the nightly's stage order). Rewrite history once with
`git filter-repo --path data/screens --path data/eod --path data/universe.csv --invert-paths`
*before the first push* — this also shrinks the repo from ~55 MB to a few MB.

### B3. Missing files for a public repo

| File | Recommendation |
|---|---|
| `LICENSE` | **MIT.** Simple, permissive, carries the warranty disclaimer that matters for trading code. Choose Apache-2.0 instead only if you want an explicit patent grant; GPL would deter reuse of the fill model, which is the reusable part. Add a one-paragraph "not investment advice, paper trading only" notice to `README.md`. |
| `pyproject.toml` | Step 0 above. Include `[project.scripts]` for `te-collect`, `te-screen`, `te-league`, `te-queue`. |
| `CONTRIBUTING.md` | Short: run `pytest`, the honesty rules, "every strategy is pre-registered in `configs.py` with a kill criterion", how to run on a synthetic store. |
| `docs/architecture.md` (diagram) | One Mermaid graph: yfinance/Nasdaq → `collect/universe` → DuckDB → `screen` → `league` → `sync`; side-lane `queue_runner` → farm; `server` ↔ `ui`. `how-it-works.md` has the prose; it needs the picture. |
| `.github/workflows/ci.yml` | `ruff check`, `pytest`, `python -c "import duckdb; ..."` schema init on `:memory:`, `npm ci && npm run build` in `ui/`. Matrix: py3.12 only. |
| `.github/dependabot.yml` | pip + npm weekly. |
| `SECURITY.md` | One line: local-only, no auth by design, do not expose ports. |
| `docs/design/*.md` | Copies (or a redacted export) of the two spec documents currently linked from the private store. |
| Root `.gitignore` additions | `*.lock`, `.env*`, `*.pem`, `data/screens/`, `data/eod/`, `data/universe.csv`, `docs/**/*.html` |

### Sequencing for the push

1. **Before any push** (private included, since history is what leaks): `git filter-repo` for
   author identity and the three data paths; scrub `/data00/home/jun.ong` and the corp tool name
   from `BUILDLOG.md`; `git gc`.
2. Push private. Add `LICENSE`, `pyproject.toml`, CI, `.gitignore` fixes (steps 0, 8, B3).
3. Steps 1-6 of the refactor plan over 2-3 weeks, one per night, watching the cron.
4. Flip to public once `pytest` is green in CI and the `data` branch split has run unattended
   for a week.
