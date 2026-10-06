"""M2 fill-simulator / paper-league schema.

Extends the engine's DuckDB store with the paper-trading tables. Everything is
CREATE TABLE IF NOT EXISTS — safe to call on every run, and it never touches the
engine's own tables (prices / screen_results are read-only from sim's side).

Append-only discipline (mirrors screen_results):
  - sim_orders   : rows are appended; only the `status` column mutates
                   (pending → filled | rejected | cancelled).
  - sim_fills    : append-only, one row per fill event.
  - sim_equity   : one row per (portfolio, date); rewritten only by an explicit
                   same-date league rerun.
  - sim_positions: current state — mutated in place (a position's qty/avg_cost).
  - portfolios   : `cash` is current state; the rest is set at creation.
"""
from __future__ import annotations

from datetime import datetime, timezone

import duckdb

from .execution import DEFAULT_PROFILE_ID

# Reference notional per paper portfolio: S$50k ≈ US$39,000 (spec §12.4).
INITIAL_CASH = 39_000.0
ORDER_SEQUENCE = "sim_order_id_seq"
PORTFOLIO_ACCOUNT_DEFAULTS = {
    "engine": "league",
    "cost_profile": "baseline_v1",
    "account_type": "cash_legacy",
    "visibility": "public",
    "price_source": "prices",
    "day_trade_rule": "pdt_25k_legacy",
    "allow_short": False,
}
PORTFOLIO_ACCOUNT_FIELDS = frozenset({
    *PORTFOLIO_ACCOUNT_DEFAULTS,
    "status",
    "updated_at",
})
PORTFOLIO_ACCOUNT_JOIN = "LEFT JOIN portfolio_accounts pa USING (portfolio_id)"


def bootstrap_order_sequence(con: duckdb.DuckDBPyConnection) -> None:
    """Create the order sequence once, starting above every legacy order id.

    DuckDB sequences are not transactional counters and deliberately survive row
    deletion.  Creating the sequence only when it is absent preserves that
    monotonic history while upgrading old stores from ``MAX(id) + 1``.
    """
    exists = con.execute(
        "SELECT 1 FROM duckdb_sequences() WHERE sequence_name = ?",
        [ORDER_SEQUENCE],
    ).fetchone()
    if exists is not None:
        return
    next_id = int(
        con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM sim_orders").fetchone()[0]
    )
    con.execute(f"CREATE SEQUENCE {ORDER_SEQUENCE} START {next_id}")


def next_order_id(con: duckdb.DuckDBPyConnection) -> int:
    """Return a never-reused order id from the persistent DuckDB sequence."""
    bootstrap_order_sequence(con)
    maximum = int(con.execute("SELECT COALESCE(MAX(id),0) FROM sim_orders").fetchone()[0])
    candidate = int(con.execute(f"SELECT nextval('{ORDER_SEQUENCE}')").fetchone()[0])
    if candidate <= maximum:
        con.execute(
            f"CREATE OR REPLACE SEQUENCE {ORDER_SEQUENCE} START {maximum + 1}"
        )
        candidate = int(
            con.execute(f"SELECT nextval('{ORDER_SEQUENCE}')").fetchone()[0]
        )
    return candidate


def portfolio_account(con: duckdb.DuckDBPyConnection, portfolio_id: str) -> dict:
    """Return effective account settings, including defaults for legacy books."""
    row = con.execute(
        "SELECT pa_engine,pa_cost_profile,pa_account_type,pa_visibility,pa_status,"
        "pa_price_source,pa_day_trade_rule,pa_allow_short,pa_updated_at "
        "FROM portfolio_accounts_v WHERE portfolio_id=?",
        [portfolio_id],
    ).fetchone()
    if row is None:
        raise KeyError(f"unknown portfolio {portfolio_id!r}")
    keys = (
        "engine", "cost_profile", "account_type", "visibility", "status",
        "price_source", "day_trade_rule", "allow_short", "updated_at",
    )
    return dict(zip(keys, row, strict=True))


def set_portfolio_account(con: duckdb.DuckDBPyConnection, portfolio_id: str,
                          **fields) -> dict:
    """Create or update only validated account-side settings."""
    unknown = set(fields) - PORTFOLIO_ACCOUNT_FIELDS
    if unknown:
        raise ValueError(f"unknown portfolio-account fields: {sorted(unknown)}")
    if con.execute("SELECT 1 FROM portfolios WHERE id=?", [portfolio_id]).fetchone() is None:
        raise KeyError(f"unknown portfolio {portfolio_id!r}")
    allowed = {
        "engine": {"league", "p15", "p16", "account"},
        "account_type": {"cash_legacy", "margin"},
        "visibility": {"public", "private"},
        "status": {None, "inactive", "active", "halted", "retired"},
        "price_source": {"prices", "massive_daily"},
        "day_trade_rule": {"pdt_25k_legacy", "intraday_margin_2026"},
    }
    for field, choices in allowed.items():
        if field in fields and fields[field] not in choices:
            raise ValueError(f"invalid {field}: {fields[field]!r}")
    if "cost_profile" in fields and (
        not isinstance(fields["cost_profile"], str) or not fields["cost_profile"]
    ):
        raise ValueError("cost_profile must be a non-empty string")
    if "allow_short" in fields and type(fields["allow_short"]) is not bool:
        raise ValueError("allow_short must be boolean")
    fields.setdefault("updated_at", datetime.now(timezone.utc).replace(tzinfo=None))
    exists = con.execute(
        "SELECT 1 FROM portfolio_accounts WHERE portfolio_id=?", [portfolio_id]
    ).fetchone()
    names = list(fields)
    if exists is None:
        columns = ",".join(["portfolio_id", *names])
        placeholders = ",".join("?" for _ in range(len(names) + 1))
        con.execute(
            f"INSERT INTO portfolio_accounts ({columns}) VALUES ({placeholders})",
            [portfolio_id, *(fields[name] for name in names)],
        )
    else:
        assignments = ",".join(f"{name}=?" for name in names)
        con.execute(
            f"UPDATE portfolio_accounts SET {assignments} WHERE portfolio_id=?",
            [*(fields[name] for name in names), portfolio_id],
        )
    return portfolio_account(con, portfolio_id)


def init_sim_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create all sim_* / portfolios tables IF NOT EXISTS."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolios (
            id       VARCHAR PRIMARY KEY,
            name     VARCHAR,
            strategy VARCHAR,
            config   VARCHAR,   -- json blob of the registered strategy config
            created  DATE,
            active   BOOLEAN DEFAULT TRUE,
            cash     DOUBLE,
            initial_cash DOUBLE,
            execution_profile VARCHAR
        )
        """
    )
    # Safe migration for stores created before capital/profile persistence.
    # Backfilling these immutable assumptions must never alter current cash.
    con.execute("ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS initial_cash DOUBLE")
    con.execute("ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS execution_profile VARCHAR")
    con.execute("UPDATE portfolios SET initial_cash = ? WHERE initial_cash IS NULL",
                [INITIAL_CASH])
    con.execute("UPDATE portfolios SET execution_profile = ? "
                "WHERE execution_profile IS NULL", [DEFAULT_PROFILE_ID])
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio_accounts (
            portfolio_id   VARCHAR PRIMARY KEY,
            engine         VARCHAR NOT NULL DEFAULT 'league',
            cost_profile   VARCHAR NOT NULL DEFAULT 'baseline_v1',
            account_type   VARCHAR NOT NULL DEFAULT 'cash_legacy',
            visibility     VARCHAR NOT NULL DEFAULT 'public',
            status         VARCHAR,
            price_source   VARCHAR NOT NULL DEFAULT 'prices',
            day_trade_rule VARCHAR NOT NULL DEFAULT 'pdt_25k_legacy',
            allow_short    BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at     TIMESTAMP
        )
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE VIEW portfolio_accounts_v AS
        SELECT p.portfolio_id,
               COALESCE(pa.engine, 'league') AS pa_engine,
               COALESCE(pa.cost_profile, 'baseline_v1') AS pa_cost_profile,
               COALESCE(pa.account_type, 'cash_legacy') AS pa_account_type,
               COALESCE(pa.visibility, 'public') AS pa_visibility,
               COALESCE(pa.status, CASE WHEN p.active THEN 'active' ELSE 'inactive' END)
                   AS pa_status,
               COALESCE(pa.price_source, 'prices') AS pa_price_source,
               COALESCE(pa.day_trade_rule, 'pdt_25k_legacy') AS pa_day_trade_rule,
               COALESCE(pa.allow_short, FALSE) AS pa_allow_short,
               pa.updated_at AS pa_updated_at
        FROM (SELECT id AS portfolio_id, active FROM portfolios) p
        {PORTFOLIO_ACCOUNT_JOIN}
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_account_specs (
            account_id VARCHAR PRIMARY KEY, payload VARCHAR NOT NULL,
            sha256 VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL,
            schema_version INTEGER DEFAULT 1
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS paper_account_intakes (
            intent_id VARCHAR PRIMARY KEY, account_id VARCHAR NOT NULL,
            order_id BIGINT UNIQUE NOT NULL, payload VARCHAR NOT NULL,
            sha256 VARCHAR NOT NULL, received_at TIMESTAMP NOT NULL,
            receipt VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS account_state (
            portfolio_id VARCHAR PRIMARY KEY, peak_equity DOUBLE NOT NULL,
            prior_close_equity DOUBLE, drawdown_anchor_equity DOUBLE,
            halted_at TIMESTAMP, halt_reason VARCHAR, resumed_at TIMESTAMP,
            resumed_by VARCHAR, pdt_flagged_at TIMESTAMP,
            pdt_restricted_until DATE, retired_at TIMESTAMP,
            updated_at TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS account_events (
            id BIGINT PRIMARY KEY, portfolio_id VARCHAR, kind VARCHAR,
            payload VARCHAR, created_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS account_reconciliations (
            portfolio_id VARCHAR, session_date DATE, expected_sha256 VARCHAR,
            observed_sha256 VARCHAR, status VARCHAR, detail VARCHAR,
            created_at TIMESTAMP, PRIMARY KEY (portfolio_id, session_date)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS account_watch (
            portfolio_id VARCHAR, ticker VARCHAR, created_at TIMESTAMP NOT NULL,
            PRIMARY KEY (portfolio_id, ticker)
        )
        """
    )
    con.execute("ALTER TABLE paper_account_specs ADD COLUMN IF NOT EXISTS "
                "schema_version INTEGER DEFAULT 1")
    con.execute("ALTER TABLE paper_account_intakes ADD COLUMN IF NOT EXISTS receipt VARCHAR")
    con.execute("ALTER TABLE account_state ADD COLUMN IF NOT EXISTS "
                "drawdown_anchor_equity DOUBLE")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_orders (
            id            BIGINT PRIMARY KEY,
            portfolio_id  VARCHAR,
            ticker        VARCHAR,
            side          VARCHAR,   -- 'buy' | 'sell'
            qty           DOUBLE,
            signal_date   DATE,
            status        VARCHAR,   -- 'pending' | 'filled' | 'rejected' | 'cancelled'
            reject_reason VARCHAR
        )
        """
    )
    bootstrap_order_sequence(con)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS instruments (
            instrument_id  VARCHAR PRIMARY KEY,
            kind           VARCHAR NOT NULL,
            underlying     VARCHAR,
            multiplier     DOUBLE NOT NULL,
            expiry         DATE,
            strike         DOUBLE,
            "right"        VARCHAR,
            exercise_style VARCHAR,
            settlement     VARCHAR,
            deliverable    VARCHAR,
            currency       VARCHAR DEFAULT 'USD',
            source         VARCHAR,
            first_seen     DATE,
            last_seen      DATE
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_order_details (
            order_id        BIGINT PRIMARY KEY,
            instrument_id   VARCHAR NOT NULL,
            instrument_kind VARCHAR NOT NULL,
            order_type      VARCHAR NOT NULL,
            side            VARCHAR NOT NULL,
            tif             VARCHAR NOT NULL DEFAULT 'day',
            limit_px        DOUBLE,
            session_date    DATE NOT NULL,
            received_at     TIMESTAMP NOT NULL,
            created_at      TIMESTAMP,
            parent_order_id BIGINT,
            leg_no          INTEGER,
            leg_ratio       INTEGER,
            contingent_on   BIGINT,
            state           VARCHAR NOT NULL,
            state_reason    VARCHAR,
            state_at        TIMESTAMP,
            source_sha256   VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_fill_details (
            order_id     BIGINT PRIMARY KEY,
            fill_ts      TIMESTAMP,
            fill_kind    VARCHAR,
            price_source VARCHAR,
            bar_ref      VARCHAR,
            reference_px DOUBLE,
            multiplier   DOUBLE DEFAULT 1,
            late_settled BOOLEAN DEFAULT FALSE,
            settled_at   TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_fill_fees (
            order_id      BIGINT PRIMARY KEY,
            cost_profile  VARCHAR NOT NULL,
            commission    DOUBLE,
            exchange_fee  DOUBLE,
            clearing_fee  DOUBLE,
            pass_through  DOUBLE,
            cat_fee       DOUBLE,
            sec_fee       DOUBLE,
            finra_taf     DOUBLE,
            occ_fee       DOUBLE,
            orf_fee       DOUBLE,
            total_usd     DOUBLE NOT NULL
        )
        """
    )
    con.execute("ALTER TABLE sim_fill_fees ADD COLUMN IF NOT EXISTS cat_fee DOUBLE")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_cash_events (
            portfolio_id VARCHAR NOT NULL,
            event_date   DATE NOT NULL,
            seq          INTEGER NOT NULL,
            kind         VARCHAR NOT NULL,
            amount       DOUBLE NOT NULL,
            instrument_id VARCHAR,
            ref_order_id BIGINT,
            note          VARCHAR,
            created_at    TIMESTAMP NOT NULL,
            PRIMARY KEY (portfolio_id, event_date, seq)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_position_lots (
            portfolio_id  VARCHAR,
            instrument_id VARCHAR,
            opened_session DATE,
            open_order_id BIGINT,
            qty            DOUBLE,
            avg_px         DOUBLE,
            PRIMARY KEY (portfolio_id, instrument_id, open_order_id)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_day_trades (
            portfolio_id  VARCHAR,
            session_date  DATE,
            instrument_id VARCHAR,
            open_order_id BIGINT,
            close_order_id BIGINT,
            PRIMARY KEY (portfolio_id, close_order_id)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_book_breaks (
            portfolio_id VARCHAR,
            break_date DATE,
            kind VARCHAR,
            from_value VARCHAR,
            to_value VARCHAR,
            registration_revision INTEGER,
            note VARCHAR,
            created_at TIMESTAMP,
            PRIMARY KEY (portfolio_id, break_date, kind)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_fills (
            order_id     BIGINT,
            portfolio_id VARCHAR,
            ticker       VARCHAR,
            side         VARCHAR,
            qty          DOUBLE,
            fill_date    DATE,
            open_px      DOUBLE,    -- the raw day t+1 open we filled against
            fill_px      DOUBLE,    -- open adjusted for slippage (worse than open)
            slippage_bps DOUBLE,    -- per-side market friction applied to open
            cost_bps     DOUBLE     -- total per-side cost embedded in fill_px
        )
        """
    )
    # Cost decomposition lives beside, rather than inside, sim_fills so the
    # original append-only ledger remains compatible with old readers and
    # explicit/positional INSERTs. Existing fills are intentionally unstamped.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_fill_costs (
            order_id          BIGINT PRIMARY KEY,
            execution_profile VARCHAR,
            participation     DOUBLE,
            market_bps        DOUBLE,
            impact_bps        DOUBLE,
            fee_bps           DOUBLE,
            total_bps         DOUBLE
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_execution_attempts (
            order_id          BIGINT,
            attempt_date      DATE,
            execution_profile VARCHAR,
            raw_notional      DOUBLE,
            median_dollar_vol DOUBLE,
            participation     DOUBLE,
            outcome           VARCHAR,
            reject_reason     VARCHAR,
            PRIMARY KEY (order_id, attempt_date)
        )
        """
    )
    # Human-adjudicated source defects. Verification disagreement alone never
    # inserts here; only a confirmed primary-store defect may activate a row.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS price_quarantine (
            ticker      VARCHAR PRIMARY KEY,
            status      VARCHAR,
            reason      VARCHAR,
            evidence    VARCHAR,
            confirmed_at TIMESTAMP,
            resolved_at TIMESTAMP,
            resolution  VARCHAR
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_positions (
            portfolio_id VARCHAR,
            ticker       VARCHAR,
            qty          DOUBLE,
            avg_cost     DOUBLE,
            PRIMARY KEY (portfolio_id, ticker)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_equity (
            portfolio_id VARCHAR,
            date         DATE,
            equity       DOUBLE,
            cash         DOUBLE,
            n_positions  INTEGER,
            PRIMARY KEY (portfolio_id, date)
        )
        """
    )
    # Append-only cash-dividend ledger: one row per (portfolio, ticker, ex_date)
    # credited by the league day-step's phase a0. Entitlement is the position held
    # at the close of ex_date−1, i.e. sim_positions BEFORE that day's fills.
    # `--rerun` deletes the day's rows and the state rebuild replays them, so cash
    # stays a pure function of (sim_fills, sim_dividends).
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS sim_dividends (
            portfolio_id VARCHAR,
            ticker       VARCHAR,
            ex_date      DATE,
            qty          DOUBLE,
            dps          DOUBLE,
            amount       DOUBLE,
            PRIMARY KEY (portfolio_id, ticker, ex_date)
        )
        """
    )
    # --- M3 discretionary paper-trading (server/) tables --------------------- #
    # A discretionary ticket is a human trade intent gated server-side before it
    # becomes a sim_orders row. disc_tickets is append-only except `status`/
    # `order_id`, mirroring the sim_orders discipline.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS disc_tickets (
            id         BIGINT PRIMARY KEY,
            ticker     VARCHAR,
            side       VARCHAR,   -- 'buy' | 'sell'
            qty        DOUBLE,
            entry_ref  DOUBLE,
            stop       DOUBLE,
            target     DOUBLE,
            playbook   VARCHAR,
            emotion    VARCHAR,
            notes      VARCHAR,
            gates      VARCHAR,   -- json array of gate results
            status     VARCHAR,   -- 'submitted'|'rejected'|'cancelled'|'filled'
            order_id   BIGINT,    -- linked sim_orders.id (NULL if rejected)
            created_at TIMESTAMP
        )
        """
    )
    # Append-only audit trail: every ticket submit/cancel/review-done writes one row.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            ts      TIMESTAMP,
            actor   VARCHAR,
            action  VARCHAR,
            payload VARCHAR   -- json blob
        )
        """
    )
    # Circuit-breaker clear markers (POST /review-done).
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS review_markers (
            ts   TIMESTAMP,
            kind VARCHAR
        )
        """
    )
