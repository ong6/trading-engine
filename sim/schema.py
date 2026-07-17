"""M2 fill-simulator / paper-league schema.

Extends the engine's DuckDB store with the paper-trading tables. Everything is
CREATE TABLE IF NOT EXISTS — safe to call on every run, and it never touches the
engine's own tables (prices / screen_results are read-only from sim's side).

Append-only discipline (mirrors screen_results):
  - sim_orders   : rows are appended; only the `status` column mutates
                   (pending → filled | rejected | cancelled).
  - sim_fills    : append-only, one row per fill event.
  - sim_equity   : append-only, one row per (portfolio, date).
  - sim_positions: current state — mutated in place (a position's qty/avg_cost).
  - portfolios   : `cash` is current state; the rest is set at creation.
"""
from __future__ import annotations

import duckdb

# Reference notional per paper portfolio: S$50k ≈ US$39,000 (spec §12.4).
INITIAL_CASH = 39_000.0


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
            cash     DOUBLE
        )
        """
    )
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
            slippage_bps DOUBLE,    -- per-side bps applied to open
            cost_bps     DOUBLE     -- per-side cost embedded in fill_px (== slippage_bps)
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
