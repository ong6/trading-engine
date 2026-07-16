# trading-engine

A local, single-box market-data engine and research workspace — the data layer for a
personal mock trading bot. It maintains a US common-stock + ETF universe, stores end-of-day
price bars in DuckDB, and (later) runs screeners over them. Everything runs on this devbox;
no accounts, no credentials, no paid data.

**Stage: M0** — universe build + full-universe EOD collect + a nightly driver.

The design specs live in [`../personal-data-store/trading/`](../personal-data-store/trading/)
(engine design §12, execution design §7). Build state is tracked in [`BUILDLOG.md`](BUILDLOG.md).

## Data sources (verified on this network)

- **yfinance** — primary EOD source (batch + `period=max` both work).
- **nasdaqtrader.com** `nasdaqtraded.txt` — the universe list, over HTTPS with a browser
  User-Agent and retries; completeness is checked via the `File Creation Time:` footer.
- Stooq is **blocked** here (anti-bot challenge); FTP is blocked. We never fall back to
  fabricated data — failed tickers are recorded as stale/missing, never filled in.

## Layout

```
engine/
  lib/db.py        DuckDB connection, schema, price upsert (drops NaN closes)
  universe.py      nasdaqtraded.txt -> universe + append-only daily snapshot
  collect.py       yfinance -> prices (bootstrap floor / backfill / incremental)
  run_daily.sh     nightly driver (universe -> incremental collect), logged
  requirements.txt
store/             market.duckdb + cached raw symbol files   (gitignored)
data/              universe.csv, _meta.json  (health output)
logs/              run-YYYY-MM-DD.log        (gitignored)
```

## How to run

```bash
# 1. Build/refresh the universe (writes data/universe.csv + a daily snapshot)
.venv/bin/python engine/universe.py

# 2. Bootstrap: pull ~90d for every active name, then compute the liquidity floor
.venv/bin/python engine/collect.py --bootstrap-floor
#    (--limit N pulls only the first N names — for smoke tests)

# 3. Backfill max history for liquid names (resumable; safe to re-run / interrupt)
.venv/bin/python engine/collect.py --backfill          # add --limit N to cap

# 4. Incremental daily pull (calendar-gated to NYSE trading days)
.venv/bin/python engine/collect.py                     # --force to ignore the calendar

# Nightly driver (does step 1 + step 4, tees to logs/)
bash engine/run_daily.sh
```

Every collect run writes `data/_meta.json` — a health snapshot (universe/price counts,
stale tickers, per-source status). The liquidity floor is: last close ≥ $3 **and** median
`close × volume` ≥ $5M over the stored window.

## Guardrails

Never fabricate a price. Point-in-time tables (`universe_snapshot`, `screen_results`) are
append-only. No credentials, no network calls beyond yfinance + nasdaqtrader.com. Polite
pulls only: batched requests, sleeps between batches, one backoff retry on failure.
