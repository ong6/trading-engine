"""Exact post-r15 baseline and fresh/legacy/deployed bootstrap migration."""
from __future__ import annotations

import importlib

import duckdb

MIGRATION_ID = 0
DESCRIPTION = "post-r15 operational catalog baseline"
STATEMENTS: tuple[str, ...] = ()
EXPECTED_CATALOG_SHA256 = "7286ea9b55c05d1bb16af2f2faeeb6aa69b1d5f711e1219efb2d5c27709a2e5d"
SUPPORTED_CATALOG_SHA256 = {
    "pre-v2": "3ea2d60e7c575d4e4e249f3d13ae3ede031a9c5eabf8e7d8b56c6b6205ef6fba",
    "v2": "62bf42557342666325c3b7ee19bf0fb15c564df4c6516be93eb0cf974cbb6034",
    "r15": "dcd1a8ea73f4136bc935f37d506b16b0d65f7928c88788c96a0f2bde809165b7",
    # The deployed store as published 2026-10-21..22: r15 plus the lazily created
    # experiment_results/job_resolutions/sim_settlements, without the three agent-paper
    # tables, and eight tables whose DDL accumulated runtime ALTERs.
    "deployed-2026-10": "865f64aad4529c6f2cde3d0fb72d7b70dd968b85f49905681db1aef825d59a65",
    "baseline": EXPECTED_CATALOG_SHA256,  # re-running bootstrap is an assertion
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
    # Baseline-owned since revision 18: first-use tables (B2).
    "agent_data_discrepancy_decisions", "agent_release_review_observations",
    "broker_cancellation_events", "broker_emergency_stop_events", "broker_executions",
    "broker_human_paper_approval_observations", "broker_intents", "broker_order_observations",
    "broker_paper_authority_retained_events", "broker_paper_authority_risk_evaluations",
    "broker_reconciliation_differences", "broker_reconciliations",
    "broker_risk_control_events", "broker_risk_decisions", "broker_snapshots",
    "broker_submission_events", "broker_submission_resolutions", "experiment_results",
    "job_resolutions", "p16_book_contracts", "p16_book_fills", "p16_book_state",
    "p16_book_windows", "p16_calibrations", "p16_challenger_attempts",
    "p16_challenger_outputs", "p16_challenger_receipts", "p16_challenger_runs",
    "p16_construct_targets", "p16_evaluation_artifacts", "p16_filing_acceptance",
    "p16_filing_accessions", "p16_filing_bundles", "p16_filing_cik_responses",
    "p16_filing_decisions", "p16_filing_labels", "p16_filing_scans",
    "p16_filing_score_attempts", "p16_filing_work_events", "p16_fill_manifests",
    "p16_fill_measurements", "p16_fill_source_captures", "p16_limit_attempts",
    "p16_limit_labels", "p16_order_intents", "p16_position_rules", "p16_screen_versions",
    "p16_sec_request_events", "p16_sequential_origin_events", "p16_trial_register_v4",
    "sim_settlements", "simulator_broker_order_keys",
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
    # Tables that producers, tools and inactive stores create on first use: on a
    # versioned store a first-use CREATE is refused, so the baseline owns them.
    ("engine.job_resolutions", "init_schema"),
    ("engine.p16_screen_inputs", "init_schema"),
    ("farm.experiment", "ensure_results_table"),
    ("farm.experiment_runner", "ensure_forward_columns"),
    ("server.agent_data_discrepancy_adjudication", "init_schema"),
    ("server.agent_release_review_store", "init_schema"),
    ("server.broker_human_paper_approval_store", "init_schema"),
    ("server.broker_ledger", "init_broker_ledger_schema"),
    ("server.broker_risk_control", "init_schema"),
    ("server.p16_book_store", "init_schema"),
    ("server.p16_challenger_store", "init_schema"),
    ("server.p16_filing_store", "init_schema"),
    ("server.p16_fill_store", "init_schema"),
    ("server.p16_store", "init_schema"),
    ("server.simulator_broker_adapter", "init_schema"),
    ("sim.settle", "ensure_table"),
    ("tools.migrate_agent_paper_authority_store", "_create_empty_schema"),
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


def _initialized(con: duckdb.DuckDBPyConnection) -> None:
    for module_name, function_name in BOOTSTRAP_CALLS:
        getattr(importlib.import_module(module_name), function_name)(con)


def _columns_of(con: duckdb.DuckDBPyConnection, table: str) -> list[tuple[str, str]]:
    return [
        (str(name), str(kind)) for name, kind in con.execute(
            "SELECT column_name, data_type FROM duckdb_columns() "
            "WHERE database_name=current_database() AND schema_name='main' "
            "AND table_name=? ORDER BY column_index", [table],
        ).fetchall()
    ]


def _normalize_drifted_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Rebuild every existing table whose DDL differs from the baseline, keeping each row.

    Runtime ``ALTER ... ADD COLUMN`` on a long-lived store appends columns in history order
    and keeps whatever constraints the column was added with, so the deployed DDL can differ
    from a fresh initializer's in column order and NOT NULL. A table is rebuilt only when
    every stored column exists in the baseline with the same type; its rows are copied by
    column name (a baseline-only column takes its declared default, exactly as the runtime
    ``ADD COLUMN`` would) and the copy is proven equal before the original is released.
    """
    reference = duckdb.connect()
    try:
        _initialized(reference)
        canonical = {
            name: sql for name, sql in reference.execute(
                "SELECT table_name, sql FROM duckdb_tables() "
                "WHERE schema_name='main' AND NOT internal AND NOT temporary"
            ).fetchall()
        }
        canonical_columns = {name: _columns_of(reference, name) for name in canonical}
    finally:
        reference.close()
    rebuilt = []
    stored = con.execute(
        "SELECT table_name, sql FROM duckdb_tables() WHERE database_name=current_database() "
        "AND schema_name='main' AND NOT internal AND NOT temporary "
        "AND table_name<>'schema_migrations' ORDER BY table_name"
    ).fetchall()
    for table, sql in stored:
        if table not in canonical or sql == canonical[table]:
            continue
        columns = _columns_of(con, table)
        target = dict(canonical_columns[table])
        lost = [name for name, kind in columns if target.get(name) != kind]
        if lost:
            raise ValueError(f"{table} cannot be normalized without changing columns: {lost}")
        names = ", ".join('"' + name.replace('"', '""') + '"' for name, _kind in columns)
        quoted = '"' + table.replace('"', '""') + '"'
        holding = f'"__baseline_rebuild_{table}"'
        count = con.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        con.execute(f"CREATE TEMP TABLE {holding} AS SELECT {names} FROM {quoted}")
        con.execute(f"DROP TABLE {quoted}")
        con.execute(canonical[table])
        con.execute(f"INSERT INTO {quoted} ({names}) SELECT {names} FROM {holding}")
        differences = con.execute(
            f"SELECT (SELECT COUNT(*) FROM (SELECT {names} FROM {holding} EXCEPT ALL "
            f"SELECT {names} FROM {quoted})) + (SELECT COUNT(*) FROM (SELECT {names} "
            f"FROM {quoted} EXCEPT ALL SELECT {names} FROM {holding})), "
            f"(SELECT COUNT(*) FROM {quoted})"
        ).fetchone()
        if differences != (0, count):
            raise ValueError(f"{table} rows changed while normalizing its DDL")
        con.execute(f"DROP TABLE {holding}")
        rebuilt.append(table)
    return rebuilt


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
        raise ValueError(
            "database is not a supported pre-v2, v2, r15, or deployed-2026-10 catalog"
        )
    _legacy_core_upgrades(con)
    if source_shape == "v2":
        _upgrade_v2_accounts(con)
    _initialized(con)
    if source_shape == "v2":
        _normalize_v2_fill_fees(con)
    if has_objects and _normalize_drifted_tables(con):
        _initialized(con)  # recreate the indexes dropped with a rebuilt table
