# engine/ — agent notes

The data layer and the scheduled drivers: collection, the point-in-time store, corporate actions,
the nightly screen, the job queue and the engine-owned paper accounts.

- **Drivers** (cron, UTC): `run_daily.sh` (weekday nightly), `run_weekly_verify.sh`,
  `run_weekend_sweeps.sh`, `run_weekly_liquid.sh`, `run_weekly_walkforward.sh`; shared stages in
  `lib/driver.sh`. Schedules and logs: [`../docs/operate/how-it-works.md`](../docs/operate/how-it-works.md#scheduled-work).
- **Store**: `lib/db.py` is the only sanctioned `duckdb.connect` on a store path
  (`tests/test_no_bare_connect.py` enforces it); paths and overrides in `lib/settings.py`;
  immutable snapshots in `lib/snapshots.py`; catalog migrations in `schema_migrations.py` and
  `migrations/`.
- **Collection**: `universe.py`, `collect.py`, `actions.py` (splits, dividends, reconciler),
  `verify_prices.py` (a verifier, never a failover), `intraday.py`, `earnings.py`,
  `fundamentals.py`, `signals.py`, `tradingview_history_archive.py`, `free_*.py` (isolated free
  research sources), `sec_acceptance.py`, `bitemporal_facts.py`.
- **Nightly decisions**: `market_date.py` (breadth-qualified date), `screen.py`, `forward_review.py`,
  `xs_forward_review.py`, `daily_opportunities.py` (P8 inputs), `p15_*` and `p16_*` inputs.
- **Queue**: `queue_runner.py` (one `jobs` table, priority-ordered pool), `job_contract.py`,
  `job_resolutions.py`.
- **Accounts and money**: `accounts/` (`python -m engine.accounts`; fold, settle, late, results),
  `money/` (limits, halts, alerts), `paper_accounts.py`.
- **Repairs**: `repair_integrity.py`, `refetch_ticker.py`, `history_recovery.py`,
  `price_quarantine.py`; each is explicit and single-writer. To fix a data defect, reproduce it on
  the published snapshot (`tools.check_invariants --snapshot latest`), fix the producer, and repair
  stored rows only through one of these tools inside a maintenance window, keeping the evidence.

Local rules: never fabricate a price or bar; point-in-time tables are append-only; one writer at a
time, heavy work through the queue; network waits release the writer. Files pinned by the
P15 registration change only with a re-pin
([`../docs/change/deploy.md`](../docs/change/deploy.md#land-a-branch)); check a file with
`grep -F '"engine/x.py":' server/*-registration.json` (a printed line means pinned). Design: [`../docs/architecture/architecture-reference.md`](../docs/architecture/architecture-reference.md).
