"""DuckDB storage layer for the trading engine.

One connection factory (`connect`), one schema initializer, and a price upsert
that never stores a fabricated bar (rows with a NaN close are dropped).

`connect` is THE way to open the store — read-write or read-only — so the
single-writer discipline (§12.7) lives in one function instead of nine
hand-rolled retry loops (refactor step 2, 2026-09-03). tests/test_no_bare_connect.py
fails the suite if `duckdb.connect(` appears anywhere else in the packages.
"""
from __future__ import annotations

import math
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from engine.lib import settings
from engine.lib.log import get_logger

log = get_logger("db")

REPO_ROOT = settings.REPO_ROOT
DEFAULT_DB = settings.DEFAULT_DB

# A bar that represents an actual market session for the name. yfinance keeps
# emitting a dead quote — the last close repeated as o=h=l=c with volume 0 —
# for days after a name stops trading (BUILDLOG 2026-08-20c: EA, TALK), and
# those rows are otherwise indistinguishable from real ones. Every consumer
# that picks an "as-of" bar (screen, hist_screen, the stale list in _meta.json,
# the league's stale-mark detector) keys on this predicate, not on MAX(date).
# `volume = 0` alone is not proof of a phantom (thin names have legitimate
# zero-volume days), so a zero-volume bar is excluded as an AS-OF bar but never
# deleted from the series. Column names are bare so it composes into any query
# whose FROM has `prices` in scope.
REAL_BAR_SQL = "volume > 0 AND NOT (open = high AND high = low AND low = close)"
MARKET_DATE_MIN_NAMES = 1_000
MARKET_DATE_MIN_COVERAGE = 0.90


@contextmanager
def registered_frame(con: duckdb.DuckDBPyConnection, name: str, frame: pd.DataFrame):
    """Register a temporary DataFrame view and always release its name."""
    con.register(name, frame)
    try:
        yield
    finally:
        con.unregister(name)


@contextmanager
def transaction(con: duckdb.DuckDBPyConnection, *, commit: bool = True):
    """Commit atomically and leave a borrowed connection reusable on failure.

    Process-level interruptions receive the same cleanup as ordinary errors.
    If rollback itself fails, preserve the original body/commit exception and
    attach the cleanup failure as a diagnostic note.
    """
    con.execute("BEGIN TRANSACTION")
    try:
        yield
        con.execute("COMMIT" if commit else "ROLLBACK")
    except BaseException as exc:
        try:
            con.execute("ROLLBACK")
        except BaseException as rollback_exc:
            exc.add_note(f"transaction rollback also failed: {rollback_exc!r}")
        raise


def latest_real_prices_date(con: duckdb.DuckDBPyConnection) -> date | None:
    """Latest date containing at least one actually traded daily bar."""
    return con.execute(
        f"SELECT MAX(date) FROM prices WHERE {REAL_BAR_SQL}"
    ).fetchone()[0]


def latest_operational_market_date(
    con: duckdb.DuckDBPyConnection,
    *,
    minimum_names: int = MARKET_DATE_MIN_NAMES,
    minimum_coverage: float = MARKET_DATE_MIN_COVERAGE,
) -> date | None:
    """Latest real-bar date broad enough to advance nightly trading state.

    With an initialized liquid universe, a date must cover at least 90% of its
    active names and, for production-sized universes, at least 1,000 names. The
    absolute floor is capped at universe size so small initialized stores can
    still establish a date. Without an initialized active liquid universe,
    return no operational date rather than trusting an arbitrary price row.
    """
    if minimum_names < 1:
        raise ValueError("minimum_names must be positive")
    if not 0 < minimum_coverage <= 1:
        raise ValueError("minimum_coverage must be in (0, 1]")
    has_universe = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'universe'"
    ).fetchone()
    if has_universe is None:
        return None
    active_liquid = int(
        con.execute(
            "SELECT COUNT(*) FROM universe WHERE active = TRUE AND liquid = TRUE"
        ).fetchone()[0]
    )
    if active_liquid == 0:
        return None
    required = min(
        active_liquid,
        max(minimum_names, math.ceil(active_liquid * minimum_coverage)),
    )
    row = con.execute(
        f"SELECT p.date FROM prices p JOIN universe u ON u.ticker = p.ticker "
        f"WHERE u.active = TRUE AND u.liquid = TRUE AND {REAL_BAR_SQL} "
        "GROUP BY p.date HAVING COUNT(DISTINCT p.ticker) >= ? "
        "ORDER BY p.date DESC LIMIT 1",
        [required],
    ).fetchone()
    return None if row is None else row[0]

# Substrings DuckDB uses when the single-writer on-disk lock is contended or the
# file is open elsewhere. The bare "lock" (formerly only in server/db.py) is the
# superset the API relied on to answer 503 rather than 500; the specific
# phrases stay for documentation.
_LOCK_MARKERS = (
    "could not set lock on file",
    "conflicting lock is held",
    "already open",
    "being used",
    "lock",
)
_LOCK_RETRY_S = 5.0


class DBBusyError(RuntimeError):
    """The DB could not be opened because another process holds a lock.

    Raised by `connect(..., wait_s=0)` callers that must never wait (the API's
    503 path). `connect` itself re-raises DuckDB's own exception after its
    retry window; use `is_lock_error` to classify it.
    """


def is_lock_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _LOCK_MARKERS)


_is_lock_error = is_lock_error  # back-compat alias


def connect(path: str | Path | None = None, *,
            read_only: bool = False,
            wait_s: float | None = None) -> duckdb.DuckDBPyConnection:
    """Open the store. The ONLY sanctioned `duckdb.connect` on a store path.

    path       None -> settings.DEFAULT_DB (honours TRADING_ENGINE_DB).
    read_only  False opens the single writer (creating parent dirs); True opens
               a reader, which still needs the writer lock to be free.
    wait_s     Lock-retry window when another process holds the lock:
                 None  -> TRADING_ENGINE_LOCK_WAIT_S (default 60s);
                 0     -> exactly one attempt, no retry (callers that must fail
                          fast, e.g. the API mapping contention to HTTP 503);
                 >0    -> max(env window, wait_s): an explicit value raises the
                          floor for callers that KNOW they may race a long writer
                          (the queue drain reacquiring the store after a parallel
                          batch can land inside a nightly's ~4-minute collect).
    After the window the original DuckDB exception is re-raised unchanged.
    """
    path = Path(path) if path is not None else settings.DEFAULT_DB
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)

    if wait_s is None:
        wait_s = settings.lock_wait_s()
    elif wait_s > 0:
        wait_s = max(settings.lock_wait_s(), float(wait_s))
    # ceil so the window is at least covered: 60s/5s -> 12 tries, 6s/5s -> 2.
    tries = max(1, math.ceil(wait_s / _LOCK_RETRY_S)) if wait_s > 0 else 1
    for attempt in range(1, tries + 1):
        try:
            return duckdb.connect(str(path), read_only=read_only)
        except Exception as exc:  # duckdb.IOException et al.
            if not is_lock_error(exc) or attempt >= tries:
                raise
            log.info(f"[db] store locked (attempt {attempt}/{tries}) — "
                  f"retrying in {_LOCK_RETRY_S:.0f}s")
            time.sleep(_LOCK_RETRY_S)
    raise AssertionError("unreachable")  # pragma: no cover


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create all tables IF NOT EXISTS. Safe to call on every run."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            ticker     VARCHAR NOT NULL,
            date       DATE    NOT NULL,
            open       DOUBLE,
            high       DOUBLE,
            low        DOUBLE,
            close      DOUBLE,
            volume     BIGINT,
            source     VARCHAR DEFAULT 'yfinance',
            fetched_at TIMESTAMP,
            PRIMARY KEY (ticker, date)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS universe (
            ticker        VARCHAR PRIMARY KEY,
            yf_ticker     VARCHAR,
            name          VARCHAR,
            exchange      VARCHAR,
            etf           BOOLEAN,
            member        VARCHAR,
            added         DATE,
            active        BOOLEAN DEFAULT TRUE,
            liquid        BOOLEAN DEFAULT FALSE,
            backfill_done BOOLEAN DEFAULT FALSE
        )
        """
    )
    # Append-only point-in-time record of the universe as filed each day.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS universe_snapshot (
            snapshot_date DATE,
            ticker        VARCHAR,
            name          VARCHAR,
            exchange      VARCHAR,
            etf           BOOLEAN,
            member        VARCHAR,
            active        BOOLEAN,
            liquid        BOOLEAN,
            PRIMARY KEY (snapshot_date, ticker)
        )
        """
    )
    # Populated by the screener in M1 — created now so the schema is stable.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS screen_results (
            run_date        DATE,
            ticker          VARCHAR,
            close           DOUBLE,
            rs_rank         INTEGER,
            template_score  INTEGER,
            passes_template BOOLEAN,
            dist_50d        DOUBLE,
            dist_200d       DOUBLE,
            off_52w_low     DOUBLE,
            off_52w_high    DOUBLE,
            base_tight      BOOLEAN,
            vol_dryup       BOOLEAN,
            new_today       BOOLEAN,
            PRIMARY KEY (run_date, ticker)
        )
        """
    )
    # Minimal job bookkeeping — backfill uses this for progress/resumability.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id         INTEGER PRIMARY KEY,
            kind       VARCHAR,
            params     VARCHAR,
            state      VARCHAR DEFAULT 'queued',
            progress   VARCHAR,
            created_at TIMESTAMP,
            updated_at TIMESTAMP
        )
        """
    )


def init_queue_schema(con: duckdb.DuckDBPyConnection) -> None:
    """M4 additions: extend the minimal `jobs` table with the §12.7 queue
    columns and create the append-only `intraday_prices` table.

    Kept SEPARATE from init_schema so the nightly collect path is untouched;
    every statement is ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS so
    it is safe to run against the live single-writer DB. Assumes `jobs` already
    exists (call init_schema first).
    """
    # Extend jobs in place — backward compatible with the backfill rows already
    # present (they simply get priority=100, mem_mb=0, last_error=NULL).
    for ddl in (
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS priority   INTEGER DEFAULT 100",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS mem_mb     INTEGER DEFAULT 0",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_error VARCHAR",
    ):
        con.execute(ddl)

    # Intraday archive: append-only, UTC timestamps. The (ticker, ts, interval)
    # primary key + the anti-join insert together guarantee we never update or
    # overwrite a captured bar.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS intraday_prices (
            ticker   VARCHAR   NOT NULL,
            ts       TIMESTAMP NOT NULL,
            interval VARCHAR   NOT NULL,
            open     DOUBLE,
            high     DOUBLE,
            low      DOUBLE,
            close    DOUBLE,
            volume   BIGINT,
            source   VARCHAR DEFAULT 'yfinance',
            as_of    DATE,
            PRIMARY KEY (ticker, ts, interval)
        )
        """
    )


def init_screen_policy_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Stamp every screen row with the UNIVERSE POLICY that produced it.

    WHY a column and not a note in the report: `ew_benchmark` is the yardstick
    every other book is scored against, and it is defined by whatever the screen
    passed that day. If the screen's universe policy can change without leaving
    a trace in the row, two screens built under different policies look
    identical in `screen_results` and every downstream comparison silently mixes
    them. Making the row self-describing is the only place the check cannot be
    forgotten.

    DEFAULT 'all' is deliberate and it is TRUE of the existing rows: every
    screen stored before 2026-08-20 ran with no exclusions, so backfilling them
    as 'all' states a fact rather than guessing one.

    Kept SEPARATE from init_schema (same reasoning as init_queue_schema) and
    written as ADD COLUMN IF NOT EXISTS so it is safe against the live
    single-writer store. Assumes `screen_results` exists — call init_schema
    first.
    """
    con.execute(
        "ALTER TABLE screen_results ADD COLUMN IF NOT EXISTS "
        "universe_policy VARCHAR DEFAULT 'all'"
    )


def init_mining_schema(con: duckdb.DuckDBPyConnection) -> None:
    """M4 §12.2 additions: the append-only, point-in-time `fundamentals`
    (weekly snapshot), `earnings_calendar` (daily), and their per-attempt fetch
    logs.

    Kept SEPARATE from init_schema so the nightly collect path is untouched;
    every object creation is guarded by IF NOT EXISTS, so it is safe to run
    against the live single-writer DB and first-run on the real store just works.

    Both tables are keyed by (ticker, ..., as_of) with as_of = the pull date, so
    a re-run on the same day is a no-op (see insert_fundamentals / insert_earnings
    anti-joins) and a past snapshot is NEVER updated — point-in-time discipline.
    """
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals (
            ticker             VARCHAR NOT NULL,
            as_of              DATE    NOT NULL,
            market_cap         DOUBLE,
            trailing_pe        DOUBLE,
            forward_pe         DOUBLE,
            price_to_book      DOUBLE,
            price_to_sales     DOUBLE,
            enterprise_value   DOUBLE,
            ev_to_ebitda       DOUBLE,
            ev_to_revenue      DOUBLE,
            ebitda             DOUBLE,
            trailing_eps       DOUBLE,
            forward_eps        DOUBLE,
            profit_margins     DOUBLE,
            dividend_yield     DOUBLE,
            beta               DOUBLE,
            shares_outstanding DOUBLE,
            sector             VARCHAR,
            industry           VARCHAR,
            quote_type         VARCHAR,
            currency           VARCHAR,
            source             VARCHAR DEFAULT 'yfinance',
            fetched_at         TIMESTAMP,
            PRIMARY KEY (ticker, as_of)
        )
        """
    )
    # A missing fundamentals row is a gap rather than an empty observation.
    # Preserve every attempt so operators can distinguish an untried ticker
    # from a failed response while failures remain eligible for retry.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals_fetch_log (
            ticker       VARCHAR   NOT NULL,
            as_of        DATE      NOT NULL,
            status       VARCHAR   NOT NULL CHECK (status IN ('ok', 'failed')),
            n_fields     INTEGER   NOT NULL,
            source       VARCHAR   DEFAULT 'yfinance',
            attempted_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS fundamentals_fetch_log_resume_idx
        ON fundamentals_fetch_log (as_of, ticker, status)
        """
    )
    # Earnings dates are forward-looking estimates that move; every daily pull is
    # its own as_of-stamped snapshot so a gate lookup uses the LATEST snapshot per
    # ticker. is_estimate = the source returned a date window (not a confirmed day).
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS earnings_calendar (
            ticker        VARCHAR NOT NULL,
            earnings_date DATE    NOT NULL,
            as_of         DATE    NOT NULL,
            is_estimate   BOOLEAN,
            source        VARCHAR DEFAULT 'yfinance',
            fetched_at    TIMESTAMP,
            PRIMARY KEY (ticker, earnings_date, as_of)
        )
        """
    )
    # A calendar row can prove that a ticker returned a date, but the absence of
    # one cannot distinguish a successful empty response from an interrupted or
    # failed request. Preserve every attempt so same-day recovery can skip only
    # completed pulls while retaining failures for retry and diagnosis.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS earnings_fetch_log (
            ticker       VARCHAR   NOT NULL,
            as_of        DATE      NOT NULL,
            status       VARCHAR   NOT NULL CHECK (status IN ('ok', 'empty', 'failed')),
            n_dates      INTEGER   NOT NULL,
            source       VARCHAR   DEFAULT 'yfinance',
            attempted_at TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS earnings_fetch_log_resume_idx
        ON earnings_fetch_log (as_of, ticker, status)
        """
    )


def init_signals_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Macro/market-regime signal additions: the append-only, point-in-time
    `macro_signals` table (engine/signals.py writes it, sim/strategies/
    macro_composite.py reads it).

    Kept SEPARATE from init_schema so the nightly collect path is untouched;
    every statement is CREATE TABLE IF NOT EXISTS so it is safe against the live
    single-writer DB and a first run on the real store just works.

    Two dates per row, and the distinction is the whole point:
      * obs_date    — the date the DATA is about (a VIX close, a claims week, a
                      margin-debt month-end).
      * fetch_as_of — the date WE first stored the value. A strategy reading
                      as-of D must gate on BOTH (obs_date <= D AND
                      fetch_as_of <= D), which makes publication lag and
                      backfill-after-the-fact impossible to accidentally
                      look-ahead through.

    DECISION D-MS1 — first-observed value wins, no restatement. Inserts are
    append-only via an anti-join on (series, obs_date): a value that arrives
    REVISED later (ICSA is revised weekly; NFCI and the FINRA margin series get
    restated; CFTC reissues reports) is silently dropped rather than overwriting
    what we first saw. That is the honest real-time series — the number a
    decision made on fetch_as_of actually had in front of it. Revisions are only
    ever accepted as NEW obs_dates. If a fully-revised (non-real-time) history is
    ever wanted it belongs in a separate table, not by rewriting this one.
    """
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS macro_signals (
            series      VARCHAR NOT NULL,   -- e.g. 'dix', 'vix', 'icsa'
            obs_date    DATE    NOT NULL,   -- the data's own date
            value       DOUBLE  NOT NULL,
            fetch_as_of DATE    NOT NULL,   -- when WE first stored it
            PRIMARY KEY (series, obs_date)
        )
        """
    )


def insert_macro_signals(con: duckdb.DuckDBPyConnection,
                         rows: "list[tuple[str, date, float]]",
                         fetch_as_of: date | None = None) -> int:
    """Append-only insert into `macro_signals` via anti-join. Returns rows added.

    `rows` is [(series, obs_date, value)]. fetch_as_of defaults to today (UTC).
    Rows with a None/NaN value or a missing date are dropped — we never store a
    fabricated observation. Existing (series, obs_date) keys are NEVER updated
    (decision D-MS1 above), so a re-run of the same backfill inserts 0 rows.

    `fetch_as_of` may be a single date (the normal case: the run's own date) or a
    per-row callable taking (series, obs_date) and returning a date — used ONLY
    by the opt-in `--pit-lag` reconstruction (decision D-MS2 in engine/signals.py)
    on scratch copies, never by the nightly.
    """
    if not rows:
        return 0
    stamp = fetch_as_of or datetime.now(timezone.utc).date()
    per_row = callable(stamp)

    clean: list[tuple[str, date, float, date]] = []
    seen: set[tuple[str, date]] = set()
    for series, obs_date, value in rows:
        if series is None or obs_date is None or value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isnan(value) or math.isinf(value):
            continue
        if isinstance(obs_date, datetime):
            obs_date = obs_date.date()
        key = (series, obs_date)
        if key in seen:      # guard the PK against dupes inside one batch
            continue
        seen.add(key)
        clean.append((series, obs_date, value,
                      stamp(series, obs_date) if per_row else stamp))
    if not clean:
        return 0

    df = pd.DataFrame(clean, columns=["series", "obs_date", "value", "fetch_as_of"])
    before = con.execute("SELECT COUNT(*) FROM macro_signals").fetchone()[0]
    with registered_frame(con, "_incoming_signals", df):
        con.execute(
            """
            INSERT INTO macro_signals (series, obs_date, value, fetch_as_of)
            SELECT i.series, i.obs_date, i.value, i.fetch_as_of
            FROM _incoming_signals i
            LEFT JOIN macro_signals m
                   ON m.series = i.series AND m.obs_date = i.obs_date
            WHERE m.series IS NULL
            """
        )
    after = con.execute("SELECT COUNT(*) FROM macro_signals").fetchone()[0]
    return after - before


def init_actions_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Corporate-actions additions: `corporate_actions` (the point-in-time record
    of splits + dividends as reported by the source), `split_adjustments` (the
    reconciliation watermark — one row per split we have DECIDED about, so a
    restatement is never applied twice) and `actions_fetch_log` (per-name pull
    bookkeeping, the backfill's resume set).

    Kept SEPARATE from init_schema so the nightly collect path is untouched; every
    statement is CREATE TABLE IF NOT EXISTS so it is safe against the live store.

    `corporate_actions` is append-only in spirit: INSERT OR REPLACE on the PK is a
    same-value idempotent re-fetch, never a rewrite of history with new meaning.
    """
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS corporate_actions (
            ticker     VARCHAR NOT NULL,
            ex_date    DATE    NOT NULL,
            kind       VARCHAR NOT NULL,   -- 'split' | 'dividend'
            value      DOUBLE  NOT NULL,   -- split: ratio new/old; dividend: $/share
            source     VARCHAR DEFAULT 'yfinance',
            fetched_at TIMESTAMP,
            PRIMARY KEY (ticker, ex_date, kind)
        )
        """
    )
    # The reconciliation watermark. One row per (ticker, ex_date) split the
    # reconciler has ADJUDICATED, whatever the verdict:
    #   applied           - the stored series showed the pre-split scale, we restated
    #   noop_restated     - the stored series already matched the post-split scale
    #                       (the normal case for history the July backfill pulled)
    #   skipped_sanity    - observed move disagrees with BOTH hypotheses -> never guess
    #   skipped_ambiguous - ratio too close to 1 to tell the cases apart
    #   skipped_no_bars   - not enough stored bars around ex_date to decide
    # Presence of a row is what makes reconciliation idempotent: a split is only
    # ever considered once.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS split_adjustments (
            ticker        VARCHAR NOT NULL,
            ex_date       DATE    NOT NULL,
            ratio         DOUBLE,
            outcome       VARCHAR,
            observed      DOUBLE,   -- the stored one-session close ratio at the break
            break_date    DATE,     -- session where the stored scale actually changes
            rows_restated BIGINT,
            applied_at    TIMESTAMP,
            PRIMARY KEY (ticker, ex_date)
        )
        """
    )
    # Per-name pull bookkeeping so a killed backfill resumes where it stopped.
    # Preserve every attempt: completed `ok`/`empty` rows are resume evidence,
    # while `failed` rows remain eligible for a later retry.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS actions_fetch_log (
            ticker      VARCHAR   NOT NULL,
            fetched_on  DATE      NOT NULL,
            n_splits    INTEGER   NOT NULL,
            n_dividends INTEGER   NOT NULL,
            status      VARCHAR   NOT NULL CHECK (status IN ('ok', 'empty', 'failed')),
            source      VARCHAR   DEFAULT 'yfinance',
            attempted_at TIMESTAMP NOT NULL
        )
        """
    )
    action_log_cols = {
        row[1] for row in con.execute("PRAGMA table_info('actions_fetch_log')").fetchall()
    }
    if "attempted_at" not in action_log_cols:
        # v1 keyed the table by (ticker, fetched_on), overwriting failed attempts
        # on retry. Replace it atomically while retaining every legacy outcome.
        with transaction(con):
            con.execute("ALTER TABLE actions_fetch_log RENAME TO actions_fetch_log_v1")
            con.execute(
                """
                CREATE TABLE actions_fetch_log (
                    ticker       VARCHAR   NOT NULL,
                    fetched_on   DATE      NOT NULL,
                    n_splits     INTEGER   NOT NULL,
                    n_dividends  INTEGER   NOT NULL,
                    status       VARCHAR   NOT NULL
                                 CHECK (status IN ('ok', 'empty', 'failed')),
                    source       VARCHAR   DEFAULT 'yfinance',
                    attempted_at TIMESTAMP
                )
                """
            )
            con.execute(
                """
                INSERT INTO actions_fetch_log
                    (ticker, fetched_on, n_splits, n_dividends, status, source, attempted_at)
                SELECT ticker, fetched_on, COALESCE(n_splits, 0),
                       COALESCE(n_dividends, 0), status, 'yfinance',
                       NULL
                FROM actions_fetch_log_v1
                """
            )
            con.execute("DROP TABLE actions_fetch_log_v1")
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS actions_fetch_log_resume_idx
        ON actions_fetch_log (fetched_on, ticker, status)
        """
    )


def upsert_actions(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """INSERT OR REPLACE corporate-action rows.

    df columns: ticker, ex_date, kind, value. Rows with a NaN/None value, a NaT
    ex_date or a non-positive value are dropped — a split ratio of 0 or a NaN
    dividend is not a fact, and we never store a fabricated action. Returns the
    number of rows written.
    """
    cols = ["ticker", "ex_date", "kind", "value"]
    if df is None or df.empty:
        return 0
    df = df[cols].copy()
    df = df.dropna(subset=["ex_date", "value"])
    df = df[df["value"] > 0]
    df = df.drop_duplicates(subset=["ticker", "ex_date", "kind"])
    if df.empty:
        return 0

    df["source"] = "yfinance"
    df["fetched_at"] = datetime.now(timezone.utc)

    with registered_frame(con, "_incoming_actions", df):
        con.execute(
            """
            INSERT OR REPLACE INTO corporate_actions
                (ticker, ex_date, kind, value, source, fetched_at)
            SELECT ticker, ex_date, kind, value, source, fetched_at
            FROM _incoming_actions
            """
        )
    return len(df)


def insert_actions_fetch_log(
    con: duckdb.DuckDBPyConnection,
    rows: list[dict],
    fetched_on: date | None = None,
) -> int:
    """Append validated per-ticker action-fetch outcomes, retaining retries."""
    if not rows:
        return 0
    fetched_on = fetched_on or datetime.now(timezone.utc).date()
    attempted_at = datetime.now(timezone.utc)
    values = []
    for row in rows:
        status = row.get("status")
        n_splits = int(row.get("n_splits", 0))
        n_dividends = int(row.get("n_dividends", 0))
        if status not in {"ok", "empty", "failed"}:
            raise ValueError(f"invalid actions fetch status: {status!r}")
        if n_splits < 0 or n_dividends < 0:
            raise ValueError("action fetch counts must be non-negative")
        if status in {"empty", "failed"} and (n_splits or n_dividends):
            raise ValueError("inconsistent actions fetch outcome")
        if status == "ok" and not (n_splits or n_dividends):
            raise ValueError("inconsistent actions fetch outcome")
        values.append(
            [row["ticker"], fetched_on, n_splits, n_dividends, status,
             row.get("source", "yfinance"), attempted_at]
        )
    con.executemany(
        """
        INSERT INTO actions_fetch_log
            (ticker, fetched_on, n_splits, n_dividends, status, source, attempted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return len(values)


# Columns the fundamentals miner supplies (order-independent; as_of/source/
# fetched_at are stamped by insert_fundamentals). Kept next to the schema so the
# two never drift.
_FUNDAMENTAL_COLS = [
    "ticker", "market_cap", "trailing_pe", "forward_pe", "price_to_book",
    "price_to_sales", "enterprise_value", "ev_to_ebitda", "ev_to_revenue",
    "ebitda", "trailing_eps", "forward_eps", "profit_margins", "dividend_yield",
    "beta", "shares_outstanding", "sector", "industry", "quote_type", "currency",
]


def insert_fundamentals(con: duckdb.DuckDBPyConnection, df: pd.DataFrame,
                        as_of: date | None = None) -> int:
    """Append-only, point-in-time insert into `fundamentals` via anti-join.

    df carries one row per ticker with any subset of _FUNDAMENTAL_COLS present;
    missing columns are stored as NULL (never fabricated). Only (ticker, as_of)
    keys not already stored are inserted — an existing snapshot is NEVER updated.
    as_of defaults to today (UTC). Returns rows inserted.
    """
    if df is None or df.empty:
        return 0
    as_of = as_of or datetime.now(timezone.utc).date()

    df = df.copy()
    for col in _FUNDAMENTAL_COLS:
        if col not in df.columns:
            df[col] = None
    df = df[_FUNDAMENTAL_COLS]
    df = df.drop_duplicates(subset=["ticker"])
    if df.empty:
        return 0

    df["as_of"] = as_of
    df["source"] = "yfinance"
    df["fetched_at"] = datetime.now(timezone.utc)

    insert_cols = _FUNDAMENTAL_COLS + ["as_of", "source", "fetched_at"]
    before = con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
    select_list = ", ".join(f"i.{c}" for c in insert_cols)
    with registered_frame(con, "_incoming_fund", df):
        con.execute(
            f"""
            INSERT INTO fundamentals ({', '.join(insert_cols)})
            SELECT {select_list}
            FROM _incoming_fund i
            LEFT JOIN fundamentals f
                   ON f.ticker = i.ticker AND f.as_of = i.as_of
            WHERE f.ticker IS NULL
            """
        )
    after = con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
    return after - before


def insert_fundamentals_fetch_log(
    con: duckdb.DuckDBPyConnection,
    rows: list[dict],
    as_of: date | None = None,
) -> int:
    """Append per-ticker fundamentals outcomes without erasing retries.

    `ok` accompanies a committed snapshot row. `failed` covers transport errors
    and unusable responses; those attempts remain visible and retryable.
    """
    if not rows:
        return 0
    as_of = as_of or datetime.now(timezone.utc).date()
    values = []
    for row in rows:
        status = row.get("status")
        if status not in {"ok", "failed"}:
            raise ValueError(f"invalid fundamentals fetch status: {status!r}")
        n_fields = int(row.get("n_fields", 0))
        if n_fields < 0 or (status == "ok") != (n_fields > 0):
            raise ValueError(
                "inconsistent fundamentals fetch outcome: "
                f"status={status!r}, n_fields={n_fields}"
            )
        values.append([
            row["ticker"],
            as_of,
            status,
            n_fields,
            "yfinance",
            row.get("attempted_at") or datetime.now(timezone.utc),
        ])
    con.executemany(
        """
        INSERT INTO fundamentals_fetch_log
            (ticker, as_of, status, n_fields, source, attempted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return len(values)


def insert_earnings(con: duckdb.DuckDBPyConnection, df: pd.DataFrame,
                    as_of: date | None = None) -> int:
    """Append-only insert into `earnings_calendar` via anti-join.

    df columns: ticker, earnings_date, is_estimate. as_of defaults to today
    (UTC). Only (ticker, earnings_date, as_of) keys not already stored are
    inserted — existing rows are NEVER touched. Rows with a NaT earnings_date are
    dropped (never store a fabricated date). Returns rows inserted.
    """
    cols = ["ticker", "earnings_date", "is_estimate"]
    if df is None or df.empty:
        return 0
    as_of = as_of or datetime.now(timezone.utc).date()

    df = df[[c for c in cols if c in df.columns]].copy()
    for col in cols:
        if col not in df.columns:
            df[col] = None
    df = df.dropna(subset=["earnings_date"])
    df = df.drop_duplicates(subset=["ticker", "earnings_date"])
    if df.empty:
        return 0

    df["as_of"] = as_of
    df["source"] = "yfinance"
    df["fetched_at"] = datetime.now(timezone.utc)

    before = con.execute("SELECT COUNT(*) FROM earnings_calendar").fetchone()[0]
    with registered_frame(con, "_incoming_earn", df):
        con.execute(
            """
            INSERT INTO earnings_calendar
                (ticker, earnings_date, is_estimate, as_of, source, fetched_at)
            SELECT i.ticker, i.earnings_date, i.is_estimate, i.as_of, i.source, i.fetched_at
            FROM _incoming_earn i
            LEFT JOIN earnings_calendar e
                   ON e.ticker = i.ticker AND e.earnings_date = i.earnings_date
                  AND e.as_of = i.as_of
            WHERE e.ticker IS NULL
            """
        )
    after = con.execute("SELECT COUNT(*) FROM earnings_calendar").fetchone()[0]
    return after - before


def insert_earnings_fetch_log(
    con: duckdb.DuckDBPyConnection,
    rows: list[dict],
    as_of: date | None = None,
) -> int:
    """Append per-ticker earnings fetch outcomes without erasing retries.

    `ok` means at least one usable date was returned, `empty` means the request
    succeeded without a usable date, and `failed` means the request exhausted
    its retry. Failed attempts remain visible and do not count as completed for
    resume purposes.
    """
    if not rows:
        return 0
    as_of = as_of or datetime.now(timezone.utc).date()
    allowed = {"ok", "empty", "failed"}
    values = []
    for row in rows:
        status = row.get("status")
        if status not in allowed:
            raise ValueError(f"invalid earnings fetch status: {status!r}")
        n_dates = int(row.get("n_dates", 0))
        if n_dates < 0 or (status == "ok") != (n_dates > 0):
            raise ValueError(
                f"inconsistent earnings fetch outcome: status={status!r}, n_dates={n_dates}"
            )
        values.append([
            row["ticker"],
            as_of,
            status,
            n_dates,
            "yfinance",
            row.get("attempted_at") or datetime.now(timezone.utc),
        ])
    con.executemany(
        """
        INSERT INTO earnings_fetch_log
            (ticker, as_of, status, n_dates, source, attempted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return len(values)


def insert_intraday(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Append-only insert into intraday_prices via anti-join.

    df must have columns: ticker, ts, interval, open, high, low, close, volume.
    ts must already be UTC (tz-naive). Only (ticker, ts, interval) keys not
    already stored are inserted — existing rows are NEVER touched. Rows with a
    NaN close are dropped (never store a fabricated bar). Returns rows inserted.
    """
    cols = ["ticker", "ts", "interval", "open", "high", "low", "close", "volume"]
    if df is None or df.empty:
        return 0

    df = df[cols].copy()
    df = df.dropna(subset=["close"])
    # Guard the primary key against dupes within a single incoming batch.
    df = df.drop_duplicates(subset=["ticker", "ts", "interval"])
    if df.empty:
        return 0

    df["source"] = "yfinance"
    df["as_of"] = datetime.now(timezone.utc).date()

    before = con.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
    with registered_frame(con, "_incoming_intraday", df):
        con.execute(
            """
            INSERT INTO intraday_prices
                (ticker, ts, interval, open, high, low, close, volume, source, as_of)
            SELECT i.ticker, i.ts, i.interval, i.open, i.high, i.low, i.close,
                   i.volume, i.source, i.as_of
            FROM _incoming_intraday i
            LEFT JOIN intraday_prices p
                   ON p.ticker = i.ticker AND p.ts = i.ts AND p.interval = i.interval
            WHERE p.ticker IS NULL
            """
        )
    after = con.execute("SELECT COUNT(*) FROM intraday_prices").fetchone()[0]
    return after - before


def upsert_prices(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """INSERT OR REPLACE price bars.

    df must have columns: ticker, date, open, high, low, close, volume.
    Rows with a NaN close are dropped — we never store an empty/fabricated bar.
    Returns the number of rows written.
    """
    cols = ["ticker", "date", "open", "high", "low", "close", "volume"]
    if df is None or df.empty:
        return 0

    df = df[cols].copy()
    df = df.dropna(subset=["close"])
    if df.empty:
        return 0

    df["source"] = "yfinance"
    df["fetched_at"] = datetime.now(timezone.utc)

    with registered_frame(con, "_incoming_prices", df):
        con.execute(
            """
            INSERT OR REPLACE INTO prices
                (ticker, date, open, high, low, close, volume, source, fetched_at)
            SELECT ticker, date, open, high, low, close, volume, source, fetched_at
            FROM _incoming_prices
            """
        )
    return len(df)
