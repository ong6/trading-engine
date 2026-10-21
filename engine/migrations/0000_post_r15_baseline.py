"""Exact post-r15 baseline and fresh/legacy bootstrap migration."""
from __future__ import annotations

import importlib

import duckdb

MIGRATION_ID = 0
DESCRIPTION = "post-r15 operational catalog baseline"
STATEMENTS: tuple[str, ...] = ()
EXPECTED_CATALOG_SHA256 = "dcd1a8ea73f4136bc935f37d506b16b0d65f7928c88788c96a0f2bde809165b7"
SUPPORTED_CATALOG_SHA256 = {
    "pre-v2": "3ea2d60e7c575d4e4e249f3d13ae3ede031a9c5eabf8e7d8b56c6b6205ef6fba",
    "v2": "62bf42557342666325c3b7ee19bf0fb15c564df4c6516be93eb0cf974cbb6034",
    "r15": EXPECTED_CATALOG_SHA256,
}

EXPECTED_TABLES = frozenset({
    "account_events", "account_reconciliations", "account_state", "account_watch",
    "actions_fetch_log", "agent_corporate_action_observations",
    "agent_daily_price_observations", "agent_evaluation_decisions",
    "agent_evaluation_execution_links", "agent_evaluation_labels",
    "agent_evaluation_labels_v2", "agent_evaluation_traces", "agent_fault_drill_runs",
    "agent_independent_price_observations", "agent_independent_price_responses",
    "agent_paper_book_attribution", "agent_paper_decision_receipts",
    "agent_paper_order_attribution", "agent_proposals", "agent_provider_response_links",
    "agent_provider_responses", "agent_provider_source_observations",
    "agent_shadow_attempts", "agent_shadow_events", "audit_log", "bitemporal_facts",
    "corporate_actions", "daily_opportunity_alert_events", "daily_opportunity_alerts",
    "daily_opportunity_assessments", "daily_opportunity_execution_quality",
    "daily_opportunity_exit_events", "daily_opportunity_exit_rules",
    "daily_opportunity_news_responses", "daily_opportunity_order_attribution",
    "daily_opportunity_runs", "daily_opportunity_tool_attempts", "disc_tickets",
    "earnings_calendar", "earnings_fetch_log", "fundamentals", "fundamentals_fetch_log",
    "instruments", "intraday_prices", "jobs", "macro_signals", "p15_book_contracts",
    "p15_book_fills", "p15_book_state", "p15_book_windows",
    "p15_evaluation_look_anchors", "p15_evaluation_looks",
    "p15_evaluation_origin_grid", "p15_event_calls", "p15_event_decisions",
    "p15_event_labels", "p15_event_source_state", "p15_event_triggers",
    "p15_event_windows", "p15_execution_quality", "p15_limit_attempts",
    "p15_limit_labels", "p15_open_label_fetch_receipts", "p15_order_intents",
    "p15_position_rules", "p15_preopen_decisions", "p15_preopen_news_responses",
    "p15_preopen_runs", "p15_price_fetch_batches", "p15_rss_checkpoints",
    "p15_rss_failures", "p15_scoring_news_responses", "p15_scoring_runs",
    "p15_scoring_samples", "paper_account_intakes", "paper_account_specs",
    "pit_import_batches", "pit_import_rows", "portfolio_accounts", "portfolios",
    "price_fetch_attempts", "price_observation_rejects", "price_quarantine", "prices",
    "review_markers", "screen_results", "sim_book_breaks", "sim_cash_events",
    "sim_day_trades", "sim_dividends", "sim_equity", "sim_execution_attempts",
    "sim_fill_costs", "sim_fill_details", "sim_fill_fees", "sim_fills",
    "sim_order_details", "sim_orders", "sim_position_lots", "sim_positions",
    "source_response_receipts", "split_adjustments", "tradingview_history_attempts",
    "tradingview_history_cohorts", "tradingview_history_symbols", "universe",
    "universe_snapshot",
})
EXPECTED_VIEWS = frozenset({"portfolio_accounts_v"})
EXPECTED_SEQUENCES = frozenset({"sim_order_id_seq"})

BOOTSTRAP_CALLS = (
    ("engine.lib.db", "init_schema"),
    ("engine.lib.db", "init_queue_schema"),
    ("engine.lib.db", "init_screen_policy_schema"),
    ("engine.lib.db", "init_mining_schema"),
    ("engine.lib.db", "init_signals_schema"),
    ("engine.lib.db", "init_actions_schema"),
    ("sim.schema", "init_sim_schema"),
    ("engine.bitemporal_facts", "init_schema"),
    ("engine.p15_evaluation", "init_look_schema"),
    ("engine.p15_event_sources", "init_schema"),
    ("engine.paper_accounts", "init_schema"),
    ("engine.pit_import", "init_schema"),
    ("engine.tradingview_history_archive", "init_schema"),
    ("sim.p15_books", "init_schema"),
    ("server.agent_corporate_action_observations", "init_schema"),
    ("server.agent_evaluation", "init_schema"),
    ("server.agent_fault_drills", "init_schema"),
    ("server.agent_independent_price_evidence", "init_schema"),
    ("server.agent_paper_attribution", "init_schema"),
    ("server.agent_paper_decisions", "init_schema"),
    ("server.agent_price_observations", "init_schema"),
    ("server.agent_provider_responses", "init_schema"),
    ("server.agent_shadow_store", "init_schema"),
    ("server.agent_store", "init_schema"),
    ("server.daily_opportunity_store", "init_schema"),
    ("server.p15_preopen", "init_schema"),
    ("server.p15_price_fetch_attempts", "init_schema"),
    ("server.p15_scoring_store", "init_schema"),
)
DEPENDENCIES = tuple(
    sorted({module_name.replace(".", "/") + ".py" for module_name, _name in BOOTSTRAP_CALLS})
)


def _objects(con: duckdb.DuckDBPyConnection) -> tuple[set[str], set[str], set[str]]:
    database = con.execute("SELECT current_database()").fetchone()[0]
    tables = {
        row[0] for row in con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name=? "
            "AND NOT internal AND NOT temporary AND table_name<>'schema_migrations'",
            [database],
        ).fetchall()
    }
    views = {
        row[0] for row in con.execute(
            "SELECT view_name FROM duckdb_views() WHERE database_name=? "
            "AND NOT internal AND NOT temporary", [database],
        ).fetchall()
    }
    sequences = {
        row[0] for row in con.execute(
            "SELECT sequence_name FROM duckdb_sequences() WHERE database_name=? "
            "AND NOT temporary", [database],
        ).fetchall()
    }
    return tables, views, sequences


def _legacy_core_upgrades(con: duckdb.DuckDBPyConnection) -> None:
    tables, _views, _sequences = _objects(con)
    def columns(table: str) -> set[str]:
        return {
            row[0] for row in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='main' AND table_name=?", [table],
        ).fetchall()
        }
    additions = {
        "prices": (("first_fetched_at", "TIMESTAMP"),),
        "jobs": (("priority", "INTEGER DEFAULT 100"), ("mem_mb", "INTEGER DEFAULT 0"),
                 ("last_error", "VARCHAR")),
        "screen_results": (("universe_policy", "VARCHAR DEFAULT 'all'"),),
    }
    for table, definitions in additions.items():
        if table not in tables:
            continue
        present = columns(table)
        for name, definition in definitions:
            if name not in present:
                con.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')
    if "actions_fetch_log" in tables and "attempted_at" not in columns("actions_fetch_log"):
        con.execute("ALTER TABLE actions_fetch_log RENAME TO actions_fetch_log_v1")
        con.execute(
            "CREATE TABLE actions_fetch_log (ticker VARCHAR NOT NULL, fetched_on DATE NOT NULL, "
            "n_splits INTEGER NOT NULL, n_dividends INTEGER NOT NULL, status VARCHAR NOT NULL "
            "CHECK (status IN ('ok','empty','failed')), source VARCHAR DEFAULT 'yfinance', "
            "attempted_at TIMESTAMP)"
        )
        con.execute(
            "INSERT INTO actions_fetch_log SELECT ticker,fetched_on,COALESCE(n_splits,0),"
            "COALESCE(n_dividends,0),status,'yfinance',NULL FROM actions_fetch_log_v1"
        )
        con.execute("DROP TABLE actions_fetch_log_v1")


def _upgrade_v2_accounts(con: duckdb.DuckDBPyConnection) -> None:
    """Move the deployed v2 portfolio columns into their r15 table."""
    con.execute(
        """CREATE TABLE portfolio_accounts (
        portfolio_id VARCHAR PRIMARY KEY,
        engine VARCHAR NOT NULL DEFAULT 'league',
        cost_profile VARCHAR NOT NULL DEFAULT 'baseline_v1',
        account_type VARCHAR NOT NULL DEFAULT 'cash_legacy',
        visibility VARCHAR NOT NULL DEFAULT 'public',
        status VARCHAR,
        price_source VARCHAR NOT NULL DEFAULT 'prices',
        day_trade_rule VARCHAR NOT NULL DEFAULT 'pdt_25k_legacy',
        allow_short BOOLEAN NOT NULL DEFAULT FALSE,
        updated_at TIMESTAMP)"""
    )
    con.execute(
        """INSERT INTO portfolio_accounts
        SELECT id,COALESCE(engine,'league'),COALESCE(cost_profile,'baseline_v1'),
        COALESCE(account_type,'cash_legacy'),COALESCE(visibility,'public'),status,
        COALESCE(price_source,'prices'),'pdt_25k_legacy',FALSE,NULL FROM portfolios"""
    )
    con.execute(
        """CREATE TABLE portfolios_r16 (
        id VARCHAR PRIMARY KEY, name VARCHAR, strategy VARCHAR, config VARCHAR,
        created DATE, active BOOLEAN DEFAULT TRUE, cash DOUBLE,
        initial_cash DOUBLE, execution_profile VARCHAR)"""
    )
    con.execute(
        "INSERT INTO portfolios_r16 SELECT id,name,strategy,config,created,active,cash,"
        "initial_cash,execution_profile FROM portfolios"
    )
    con.execute("DROP TABLE portfolios")
    con.execute("ALTER TABLE portfolios_r16 RENAME TO portfolios")


def _normalize_v2_fill_fees(con: duckdb.DuckDBPyConnection) -> None:
    """Move the newly added CAT fee into the exact r15 column order."""
    con.execute(
        """CREATE TABLE sim_fill_fees_r16 (
        order_id BIGINT PRIMARY KEY, cost_profile VARCHAR NOT NULL,
        commission DOUBLE, exchange_fee DOUBLE, clearing_fee DOUBLE,
        pass_through DOUBLE, cat_fee DOUBLE, sec_fee DOUBLE, finra_taf DOUBLE,
        occ_fee DOUBLE, orf_fee DOUBLE, total_usd DOUBLE NOT NULL)"""
    )
    con.execute(
        "INSERT INTO sim_fill_fees_r16 SELECT order_id,cost_profile,commission,"
        "exchange_fee,clearing_fee,pass_through,cat_fee,sec_fee,finra_taf,occ_fee,"
        "orf_fee,total_usd FROM sim_fill_fees"
    )
    con.execute("DROP TABLE sim_fill_fees")
    con.execute("ALTER TABLE sim_fill_fees_r16 RENAME TO sim_fill_fees")


def bootstrap(con: duckdb.DuckDBPyConnection) -> None:
    """Create/upgrade the exact post-r15 catalog under migration authority."""
    from engine.lib.snapshots import catalog_sha256

    tables, views, sequences = _objects(con)
    has_objects = bool(tables or views or sequences)
    if not has_objects:
        source_shape = None
    else:
        source_hash = catalog_sha256(con)
        source_shape = next(
            (name for name, digest in SUPPORTED_CATALOG_SHA256.items() if digest == source_hash),
            None,
        )
    if has_objects and source_shape is None:
        raise ValueError("database is not a supported pre-v2, v2, or r15 catalog")
    _legacy_core_upgrades(con)
    if source_shape == "v2":
        _upgrade_v2_accounts(con)
    for module_name, function_name in BOOTSTRAP_CALLS:
        getattr(importlib.import_module(module_name), function_name)(con)
    if source_shape == "v2":
        _normalize_v2_fill_fees(con)
