"""Exact post-r15 baseline and fresh/legacy/deployed bootstrap migration.

The baseline catalog is frozen here as data, so this migration's recorded identity is this
file alone: later edits to the runtime initializers cannot change it. CI proves the current
initializers still reproduce the newest migration's catalog (``tests/test_schema_migrations.py``).
"""
from __future__ import annotations

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
# Existing tables each pre-image rebuilds into the baseline DDL (rows copied by column name).
REBUILD_PLAN: dict[str, tuple[str, ...]] = {
    "pre-v2": ("actions_fetch_log", "jobs", "paper_account_intakes", "paper_account_specs"),
    "v2": (
        "actions_fetch_log", "jobs", "paper_account_intakes", "paper_account_specs",
        "sim_fill_fees",
    ),
    "r15": ("actions_fetch_log", "jobs"),
    # Column order or NOT NULL from accumulated ADD COLUMN; the deployed actions_fetch_log
    # and jobs already match the baseline, which declares their nullable stamp and timeout.
    "deployed-2026-10": (
        "agent_evaluation_labels", "agent_proposals", "agent_shadow_attempts",
        "daily_opportunity_execution_quality", "daily_opportunity_runs",
        "fundamentals_fetch_log",
    ),
}
# Legacy pre-images whose portfolios gained these columns in this migration take the values
# the initializer backfilled when the columns were introduced.
LEGACY_PORTFOLIO_DEFAULTS = {"initial_cash": 39_000.0, "execution_profile": "baseline_v1"}

# The runtime initializers that create the baseline in a fresh store. They are not called by
# this migration; CI runs them to prove they still reproduce the frozen catalog below, and
# tests/test_baseline_table_coverage.py proves every table the code creates is owned here.
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

# Generated from the fresh initializers (BOOTSTRAP_CALLS) and frozen with this migration:
# tests/test_schema_migrations.py proves the current initializers still reproduce it.
BASELINE_SEQUENCES: dict[str, str] = {
    'sim_order_id_seq': 'CREATE SEQUENCE sim_order_id_seq INCREMENT BY 1 MINVALUE 1 MAXVALUE 9223372036854775807 START 1 NO CYCLE;',
}
BASELINE_TABLES: dict[str, str] = {
    'account_events': 'CREATE TABLE account_events(id BIGINT PRIMARY KEY, portfolio_id VARCHAR, kind VARCHAR, payload VARCHAR, created_at TIMESTAMP);',
    'account_reconciliations': 'CREATE TABLE account_reconciliations(portfolio_id VARCHAR, session_date DATE, expected_sha256 VARCHAR, observed_sha256 VARCHAR, status VARCHAR, detail VARCHAR, created_at TIMESTAMP, PRIMARY KEY(portfolio_id, session_date));',
    'account_state': 'CREATE TABLE account_state(portfolio_id VARCHAR PRIMARY KEY, peak_equity DOUBLE NOT NULL, prior_close_equity DOUBLE, drawdown_anchor_equity DOUBLE, halted_at TIMESTAMP, halt_reason VARCHAR, resumed_at TIMESTAMP, resumed_by VARCHAR, pdt_flagged_at TIMESTAMP, pdt_restricted_until DATE, retired_at TIMESTAMP, updated_at TIMESTAMP NOT NULL);',
    'account_watch': 'CREATE TABLE account_watch(portfolio_id VARCHAR, ticker VARCHAR, created_at TIMESTAMP NOT NULL, PRIMARY KEY(portfolio_id, ticker));',
    'actions_fetch_log': 'CREATE TABLE actions_fetch_log(ticker VARCHAR NOT NULL, fetched_on DATE NOT NULL, n_splits INTEGER NOT NULL, n_dividends INTEGER NOT NULL, status VARCHAR NOT NULL, "source" VARCHAR DEFAULT(\'yfinance\'), attempted_at TIMESTAMP, CHECK((status IN (\'ok\', \'empty\', \'failed\'))));',
    'agent_corporate_action_observations': 'CREATE TABLE agent_corporate_action_observations(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, ticker VARCHAR NOT NULL, ex_date DATE NOT NULL, kind VARCHAR NOT NULL, "value" DOUBLE NOT NULL, "source" VARCHAR NOT NULL, source_fetched_at TIMESTAMP NOT NULL, observed_at TIMESTAMP NOT NULL, source_adapter VARCHAR NOT NULL, source_adapter_version VARCHAR NOT NULL, source_library_version VARCHAR NOT NULL, normalized_sha256 VARCHAR NOT NULL, value_sha256 VARCHAR NOT NULL, observation_sequence INTEGER NOT NULL, value_revision INTEGER NOT NULL, classification VARCHAR NOT NULL, previous_observation_sha256 VARCHAR, observation_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(ticker, ex_date, kind, observation_sequence));',
    'agent_daily_price_observations': 'CREATE TABLE agent_daily_price_observations(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, ticker VARCHAR NOT NULL, market_date DATE NOT NULL, open DOUBLE NOT NULL, high DOUBLE NOT NULL, low DOUBLE NOT NULL, "close" DOUBLE NOT NULL, volume BIGINT NOT NULL, "source" VARCHAR NOT NULL, source_fetched_at TIMESTAMP NOT NULL, observed_at TIMESTAMP NOT NULL, source_adapter VARCHAR NOT NULL, source_adapter_version VARCHAR NOT NULL, source_library_version VARCHAR NOT NULL, normalized_sha256 VARCHAR NOT NULL, value_sha256 VARCHAR NOT NULL, observation_sequence INTEGER NOT NULL, value_revision INTEGER NOT NULL, classification VARCHAR NOT NULL, previous_observation_sha256 VARCHAR, observation_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(ticker, market_date, observation_sequence));',
    'agent_data_discrepancy_decisions': 'CREATE TABLE agent_data_discrepancy_decisions(decision_sequence BIGINT PRIMARY KEY, decision_id VARCHAR NOT NULL UNIQUE, discrepancy_state_sha256 VARCHAR NOT NULL UNIQUE, review_packet_sha256 VARCHAR NOT NULL, dataset VARCHAR NOT NULL, ticker VARCHAR NOT NULL, fact_date VARCHAR NOT NULL, kind VARCHAR NOT NULL, discrepancy_classification VARCHAR NOT NULL, source_observation_sha256 VARCHAR NOT NULL, source_value_sha256 VARCHAR NOT NULL, cache_value_sha256 VARCHAR, disposition VARCHAR NOT NULL, operator_id VARCHAR NOT NULL, justification VARCHAR NOT NULL, decided_at VARCHAR NOT NULL, prior_decision_sha256 VARCHAR, decision_payload VARCHAR NOT NULL, decision_sha256 VARCHAR NOT NULL);',
    'agent_evaluation_decisions': 'CREATE TABLE agent_evaluation_decisions(id BIGINT PRIMARY KEY, trace_id BIGINT NOT NULL, ticker VARCHAR NOT NULL, decision VARCHAR NOT NULL, "action" VARCHAR NOT NULL, horizon_sessions INTEGER NOT NULL, confidence DOUBLE NOT NULL, assessment_sha256 VARCHAR NOT NULL, source_assessment_id BIGINT, decision_payload VARCHAR NOT NULL, decision_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(trace_id, ticker));',
    'agent_evaluation_execution_links': 'CREATE TABLE agent_evaluation_execution_links(id BIGINT PRIMARY KEY, decision_id BIGINT NOT NULL UNIQUE, tool_attempt_id BIGINT NOT NULL, order_id BIGINT, linked_at TIMESTAMP NOT NULL, link_sha256 VARCHAR NOT NULL UNIQUE);',
    'agent_evaluation_labels': 'CREATE TABLE agent_evaluation_labels(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, decision_id BIGINT NOT NULL, horizon_sessions INTEGER NOT NULL, entry_date DATE NOT NULL, exit_date DATE NOT NULL, entry_open DOUBLE NOT NULL, exit_close DOUBLE NOT NULL, asset_return DOUBLE NOT NULL, spy_return DOUBLE NOT NULL, excess_return DOUBLE NOT NULL, maximum_adverse_excursion DOUBLE NOT NULL, maximum_favorable_excursion DOUBLE NOT NULL, price_prefix_sha256 VARCHAR NOT NULL, labeled_at TIMESTAMP NOT NULL, label_sha256 VARCHAR NOT NULL UNIQUE, round_trip_cost_bps DOUBLE DEFAULT(20) NOT NULL, net_return DOUBLE DEFAULT(0) NOT NULL, net_excess_return DOUBLE DEFAULT(0) NOT NULL, UNIQUE(decision_id, horizon_sessions));',
    'agent_evaluation_labels_v2': 'CREATE TABLE agent_evaluation_labels_v2(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, decision_id BIGINT NOT NULL, horizon_sessions INTEGER NOT NULL, label_basis VARCHAR NOT NULL, entry_date DATE NOT NULL, exit_date DATE NOT NULL, entry_open DOUBLE NOT NULL, exit_close DOUBLE NOT NULL, asset_return DOUBLE NOT NULL, spy_return DOUBLE NOT NULL, excess_return DOUBLE NOT NULL, maximum_adverse_excursion DOUBLE NOT NULL, maximum_favorable_excursion DOUBLE NOT NULL, price_prefix_sha256 VARCHAR NOT NULL, missing_bar_status VARCHAR NOT NULL, labeled_at TIMESTAMP NOT NULL, label_sha256 VARCHAR NOT NULL UNIQUE, round_trip_cost_bps DOUBLE NOT NULL, net_return DOUBLE NOT NULL, net_excess_return DOUBLE NOT NULL, spy_net_return DOUBLE, UNIQUE(decision_id, horizon_sessions, label_basis));',
    'agent_evaluation_traces': 'CREATE TABLE agent_evaluation_traces(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, window_id VARCHAR NOT NULL UNIQUE, policy_id VARCHAR NOT NULL, cadence VARCHAR NOT NULL, prompt_role VARCHAR NOT NULL, market_date DATE NOT NULL, observed_at TIMESTAMP NOT NULL, completed_at TIMESTAMP NOT NULL, information_cutoff_at TIMESTAMP NOT NULL, source_kind VARCHAR NOT NULL, source_identifier VARCHAR NOT NULL, source_refs VARCHAR NOT NULL, input_payload VARCHAR NOT NULL, input_sha256 VARCHAR NOT NULL, output_payload VARCHAR NOT NULL, output_sha256 VARCHAR NOT NULL, request_sha256 VARCHAR NOT NULL, response_id VARCHAR NOT NULL, model VARCHAR NOT NULL, model_version VARCHAR NOT NULL, instructions_sha256 VARCHAR NOT NULL, toolset_sha256 VARCHAR NOT NULL, model_catalog_entry_sha256 VARCHAR NOT NULL, proxy_source_sha256 VARCHAR NOT NULL, traecli_runtime VARCHAR NOT NULL, upstream_model_family VARCHAR NOT NULL, upstream_request_id VARCHAR NOT NULL, latency_ms DOUBLE NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL, terminal_status VARCHAR NOT NULL, execution_authority VARCHAR NOT NULL, trace_sha256 VARCHAR NOT NULL UNIQUE);',
    'agent_fault_drill_runs': 'CREATE TABLE agent_fault_drill_runs(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, suite_id VARCHAR NOT NULL, suite_sha256 VARCHAR NOT NULL, coverage_level VARCHAR NOT NULL, source_sha256 VARCHAR NOT NULL, source_file_count INTEGER NOT NULL, registry_sha256 VARCHAR NOT NULL, started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP NOT NULL, status VARCHAR NOT NULL, case_count INTEGER NOT NULL, passed_count INTEGER NOT NULL, failed_count INTEGER NOT NULL, indeterminate_count INTEGER NOT NULL, results_payload VARCHAR NOT NULL, results_sha256 VARCHAR NOT NULL, run_sha256 VARCHAR NOT NULL UNIQUE);',
    'agent_independent_price_observations': 'CREATE TABLE agent_independent_price_observations(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, ticker VARCHAR NOT NULL, market_date DATE NOT NULL, normalized_payload VARCHAR NOT NULL, normalized_sha256 VARCHAR NOT NULL, value_sha256 VARCHAR NOT NULL, source_fetched_at TIMESTAMP NOT NULL, observed_at TIMESTAMP NOT NULL, source_adapter VARCHAR NOT NULL, source_adapter_version VARCHAR NOT NULL, source_library_version VARCHAR NOT NULL, observation_sequence INTEGER NOT NULL, value_revision INTEGER NOT NULL, classification VARCHAR NOT NULL, previous_observation_sha256 VARCHAR, receipt_sha256 VARCHAR NOT NULL, response_sha256 VARCHAR NOT NULL, observation_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(ticker, market_date, observation_sequence), UNIQUE(receipt_sha256, ticker, market_date));',
    'agent_independent_price_responses': 'CREATE TABLE agent_independent_price_responses(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, "source" VARCHAR NOT NULL, endpoint VARCHAR NOT NULL, endpoint_api_version VARCHAR NOT NULL, ticker VARCHAR NOT NULL, asset_class VARCHAR NOT NULL, period_start DATE NOT NULL, period_end_inclusive DATE NOT NULL, request_sha256 VARCHAR NOT NULL, requested_at TIMESTAMP NOT NULL, received_at TIMESTAMP NOT NULL, http_status INTEGER NOT NULL, content_type VARCHAR NOT NULL, source_library_version VARCHAR NOT NULL, response_size_bytes BIGINT NOT NULL, response_sha256 VARCHAR NOT NULL, response_body BLOB NOT NULL, source_row_count INTEGER NOT NULL, parse_error_count INTEGER NOT NULL, incomplete_row_count INTEGER NOT NULL, receipt_sha256 VARCHAR NOT NULL UNIQUE);',
    'agent_paper_book_attribution': 'CREATE TABLE agent_paper_book_attribution(portfolio_id VARCHAR PRIMARY KEY, policy_id VARCHAR NOT NULL UNIQUE, policy_registration_sha256 VARCHAR NOT NULL, "mode" VARCHAR NOT NULL, contract_payload VARCHAR NOT NULL, contract_sha256 VARCHAR NOT NULL, recorded_at TIMESTAMP NOT NULL);',
    'agent_paper_decision_receipts': 'CREATE TABLE agent_paper_decision_receipts(decision_window VARCHAR PRIMARY KEY, policy_id VARCHAR NOT NULL, attempt_id BIGINT NOT NULL UNIQUE, outcome VARCHAR NOT NULL, order_id BIGINT UNIQUE, receipt_payload VARCHAR NOT NULL, receipt_sha256 VARCHAR NOT NULL, consumed_at TIMESTAMP NOT NULL);',
    'agent_paper_order_attribution': 'CREATE TABLE agent_paper_order_attribution(order_id BIGINT PRIMARY KEY, portfolio_id VARCHAR NOT NULL, policy_id VARCHAR NOT NULL, policy_registration_sha256 VARCHAR NOT NULL, "mode" VARCHAR NOT NULL, attempt_id BIGINT NOT NULL, decision_order_sequence INTEGER NOT NULL, decision_window VARCHAR NOT NULL, terminal_event_sha256 VARCHAR NOT NULL, decision_evidence_sha256 VARCHAR NOT NULL, attribution_payload VARCHAR NOT NULL, attribution_sha256 VARCHAR NOT NULL, recorded_at TIMESTAMP NOT NULL, UNIQUE(policy_id, attempt_id, decision_order_sequence));',
    'agent_proposals': 'CREATE TABLE agent_proposals(id BIGINT PRIMARY KEY, proposal_id VARCHAR UNIQUE, idempotency_key VARCHAR UNIQUE, proposal_sha256 VARCHAR, schema_version INTEGER, "mode" VARCHAR, policy_id VARCHAR, policy_registration_sha256 VARCHAR, agent_id VARCHAR, model VARCHAR, model_version VARCHAR, prompt_sha256 VARCHAR, toolset_sha256 VARCHAR, strategy_id VARCHAR, strategy_config_sha256 VARCHAR, agent_boundary_sha256 VARCHAR, runtime_source_sha256 VARCHAR, data_snapshot_sha256 VARCHAR, context_sha256 VARCHAR, validated_context_sha256 VARCHAR, validated_context VARCHAR, validation_sha256 VARCHAR, validation_payload VARCHAR, ticker VARCHAR, side VARCHAR, max_notional DOUBLE, stop DOUBLE, confidence DOUBLE, signal_at TIMESTAMP, expires_at TIMESTAMP, thesis VARCHAR, invalidation VARCHAR, evidence_ids VARCHAR, normalized_proposal VARCHAR, status VARCHAR, reasons VARCHAR, received_at TIMESTAMP);',
    'agent_provider_response_links': 'CREATE TABLE agent_provider_response_links(schema_version INTEGER NOT NULL, receipt_sha256 VARCHAR NOT NULL, response_sha256 VARCHAR NOT NULL, dataset VARCHAR NOT NULL, ticker VARCHAR NOT NULL, fact_date DATE NOT NULL, kind VARCHAR NOT NULL, value_sha256 VARCHAR NOT NULL, observation_sha256 VARCHAR NOT NULL, linked_at TIMESTAMP NOT NULL, link_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(receipt_sha256, observation_sha256));',
    'agent_provider_responses': 'CREATE TABLE agent_provider_responses(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, "source" VARCHAR NOT NULL, endpoint VARCHAR NOT NULL, endpoint_api_version VARCHAR NOT NULL, ticker VARCHAR NOT NULL, provider_ticker VARCHAR NOT NULL, period_start DATE NOT NULL, period_end_exclusive DATE NOT NULL, "interval" VARCHAR NOT NULL, events VARCHAR NOT NULL, request_sha256 VARCHAR NOT NULL, requested_at TIMESTAMP NOT NULL, received_at TIMESTAMP NOT NULL, http_status INTEGER NOT NULL, content_type VARCHAR NOT NULL, source_library_version VARCHAR NOT NULL, response_size_bytes BIGINT NOT NULL, response_sha256 VARCHAR NOT NULL, response_body BLOB NOT NULL, receipt_sha256 VARCHAR NOT NULL UNIQUE);',
    'agent_provider_source_observations': 'CREATE TABLE agent_provider_source_observations(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, dataset VARCHAR NOT NULL, ticker VARCHAR NOT NULL, fact_date DATE NOT NULL, kind VARCHAR NOT NULL, normalized_payload VARCHAR NOT NULL, normalized_sha256 VARCHAR NOT NULL, value_sha256 VARCHAR NOT NULL, source_fetched_at TIMESTAMP NOT NULL, observed_at TIMESTAMP NOT NULL, source_adapter VARCHAR NOT NULL, source_adapter_version VARCHAR NOT NULL, source_library_version VARCHAR NOT NULL, observation_sequence INTEGER NOT NULL, value_revision INTEGER NOT NULL, classification VARCHAR NOT NULL, previous_observation_sha256 VARCHAR, receipt_sha256 VARCHAR NOT NULL, response_sha256 VARCHAR NOT NULL, observation_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(dataset, ticker, fact_date, kind, observation_sequence));',
    'agent_release_review_observations': 'CREATE TABLE agent_release_review_observations(observation_sequence BIGINT PRIMARY KEY, review_id VARCHAR NOT NULL UNIQUE, envelope_sha256 VARCHAR NOT NULL UNIQUE, manifest_sha256 VARCHAR NOT NULL UNIQUE, release_readiness_sha256 VARCHAR NOT NULL UNIQUE, decision VARCHAR NOT NULL, review_source_id VARCHAR NOT NULL, reviewer_policy_id VARCHAR NOT NULL, reviewer_policy_version VARCHAR NOT NULL, reviewer_identity VARCHAR NOT NULL, authenticator_algorithm VARCHAR NOT NULL, selected_policy_sha256 VARCHAR NOT NULL, signing_payload_sha256 VARCHAR NOT NULL, authenticated_at VARCHAR NOT NULL, recorded_at VARCHAR NOT NULL, prior_observation_sha256 VARCHAR, policy_payload VARCHAR NOT NULL, envelope_payload VARCHAR NOT NULL, release_readiness_payload VARCHAR NOT NULL, verification_payload VARCHAR NOT NULL, verification_sha256 VARCHAR NOT NULL, observation_payload VARCHAR NOT NULL, observation_sha256 VARCHAR NOT NULL UNIQUE);',
    'agent_shadow_attempts': 'CREATE TABLE agent_shadow_attempts(id BIGINT PRIMARY KEY, decision_window VARCHAR UNIQUE, schema_version INTEGER, "mode" VARCHAR, policy_id VARCHAR, policy_registration_sha256 VARCHAR, agent_id VARCHAR, strategy_id VARCHAR, ticker VARCHAR, market_date DATE, context_sha256 VARCHAR, context_payload VARCHAR, model_input VARCHAR, model_request VARCHAR, request_sha256 VARCHAR, model VARCHAR, model_version VARCHAR, prompt_sha256 VARCHAR, toolset_sha256 VARCHAR, required_proxy_version VARCHAR, execution_authority VARCHAR, started_at TIMESTAMP);',
    'agent_shadow_events': 'CREATE TABLE agent_shadow_events(id BIGINT PRIMARY KEY, attempt_id BIGINT, event_type VARCHAR, payload VARCHAR, occurred_at TIMESTAMP);',
    'audit_log': 'CREATE TABLE audit_log(ts TIMESTAMP, actor VARCHAR, "action" VARCHAR, payload VARCHAR);',
    'bitemporal_facts': 'CREATE TABLE bitemporal_facts(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, entity_id VARCHAR NOT NULL, security_id VARCHAR, fact_type VARCHAR NOT NULL, event_at TIMESTAMP NOT NULL, published_at TIMESTAMP, available_at TIMESTAMP NOT NULL, ingested_at TIMESTAMP NOT NULL, revision INTEGER NOT NULL, normalized_payload VARCHAR NOT NULL, normalized_sha256 VARCHAR NOT NULL, "source" VARCHAR NOT NULL, source_version VARCHAR NOT NULL, receipt_sha256 VARCHAR NOT NULL, previous_fact_sha256 VARCHAR, fact_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(entity_id, fact_type, event_at, revision));',
    'broker_cancellation_events': 'CREATE TABLE broker_cancellation_events(cancellation_key VARCHAR, event_sequence INTEGER, account_id VARCHAR NOT NULL, broker_order_id VARCHAR NOT NULL, event_type VARCHAR NOT NULL, order_sha256 VARCHAR, order_payload VARCHAR, occurred_at TIMESTAMP NOT NULL, PRIMARY KEY(cancellation_key, event_sequence));',
    'broker_emergency_stop_events': 'CREATE TABLE broker_emergency_stop_events(halt_key VARCHAR, event_sequence INTEGER, account_id VARCHAR NOT NULL, event_type VARCHAR NOT NULL, event_sha256 VARCHAR NOT NULL, event_payload VARCHAR NOT NULL, occurred_at VARCHAR NOT NULL, PRIMARY KEY(halt_key, event_sequence));',
    'broker_executions': 'CREATE TABLE broker_executions(execution_id VARCHAR PRIMARY KEY, account_id VARCHAR NOT NULL, broker_order_id VARCHAR NOT NULL, execution_sha256 VARCHAR NOT NULL, execution_payload VARCHAR NOT NULL, observed_at TIMESTAMP NOT NULL);',
    'broker_human_paper_approval_observations': 'CREATE TABLE broker_human_paper_approval_observations(observation_sequence BIGINT PRIMARY KEY, approval_id VARCHAR NOT NULL UNIQUE, envelope_sha256 VARCHAR NOT NULL UNIQUE, review_request_sha256 VARCHAR NOT NULL UNIQUE, request_sha256 VARCHAR NOT NULL UNIQUE, decision VARCHAR NOT NULL, approval_source_id VARCHAR NOT NULL, signer_policy_id VARCHAR NOT NULL, signer_policy_version VARCHAR NOT NULL, signer_identity VARCHAR NOT NULL, authenticator_algorithm VARCHAR NOT NULL, selected_policy_sha256 VARCHAR NOT NULL, signing_payload_sha256 VARCHAR NOT NULL, authenticated_at VARCHAR NOT NULL, recorded_at VARCHAR NOT NULL, prior_observation_sha256 VARCHAR, policy_payload VARCHAR NOT NULL, envelope_payload VARCHAR NOT NULL, review_packet_payload VARCHAR NOT NULL, verification_payload VARCHAR NOT NULL, verification_sha256 VARCHAR NOT NULL, observation_payload VARCHAR NOT NULL, observation_sha256 VARCHAR NOT NULL UNIQUE);',
    'broker_intents': 'CREATE TABLE broker_intents(idempotency_key VARCHAR PRIMARY KEY, account_id VARCHAR NOT NULL, intent_sha256 VARCHAR NOT NULL, intent_payload VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL);',
    'broker_order_observations': 'CREATE TABLE broker_order_observations(observation_key VARCHAR PRIMARY KEY, account_id VARCHAR NOT NULL, broker_order_id VARCHAR NOT NULL, order_sha256 VARCHAR NOT NULL, order_payload VARCHAR NOT NULL, observed_at TIMESTAMP NOT NULL);',
    'broker_paper_authority_retained_events': 'CREATE TABLE broker_paper_authority_retained_events(global_sequence BIGINT NOT NULL, account_id VARCHAR NOT NULL, "mode" VARCHAR NOT NULL, lease_id VARCHAR NOT NULL, lease_sha256 VARCHAR NOT NULL, lease_payload VARCHAR NOT NULL, event_sequence INTEGER NOT NULL, event_type VARCHAR NOT NULL, event_payload VARCHAR NOT NULL, event_sha256 VARCHAR NOT NULL, trusted_activation_event_sha256 VARCHAR NOT NULL, candidate_assessment_sha256 VARCHAR NOT NULL, startup_assessment_sha256 VARCHAR NOT NULL, activation_runtime_epoch_sha256 VARCHAR NOT NULL, prior_global_row_sha256 VARCHAR, row_sha256 VARCHAR NOT NULL);',
    'broker_paper_authority_risk_evaluations': 'CREATE TABLE broker_paper_authority_risk_evaluations(idempotency_key VARCHAR PRIMARY KEY, account_id VARCHAR NOT NULL, lease_id VARCHAR NOT NULL, evaluation_sha256 VARCHAR NOT NULL UNIQUE, evaluation_payload VARCHAR NOT NULL, eligibility_sha256 VARCHAR NOT NULL, eligibility_payload VARCHAR NOT NULL, atomic_bundle_sha256 VARCHAR NOT NULL, atomic_bundle_payload VARCHAR NOT NULL, recorded_at VARCHAR NOT NULL, record_sha256 VARCHAR NOT NULL);',
    'broker_reconciliation_differences': 'CREATE TABLE broker_reconciliation_differences(reconciliation_key VARCHAR, difference_sequence INTEGER, difference_sha256 VARCHAR NOT NULL, difference_payload VARCHAR NOT NULL, recorded_at TIMESTAMP NOT NULL, PRIMARY KEY(reconciliation_key, difference_sequence));',
    'broker_reconciliations': 'CREATE TABLE broker_reconciliations(reconciliation_key VARCHAR PRIMARY KEY, account_id VARCHAR NOT NULL, status VARCHAR NOT NULL, expected_sha256 VARCHAR, observed_sha256 VARCHAR, expected_payload VARCHAR, observed_payload VARCHAR, detail VARCHAR NOT NULL, observed_at TIMESTAMP NOT NULL);',
    'broker_risk_control_events': 'CREATE TABLE broker_risk_control_events(halt_key VARCHAR PRIMARY KEY, account_id VARCHAR NOT NULL, event_sequence INTEGER NOT NULL, event_type VARCHAR NOT NULL, reason VARCHAR NOT NULL, occurred_at VARCHAR NOT NULL, prior_event_sha256 VARCHAR, event_sha256 VARCHAR NOT NULL, UNIQUE(account_id, event_sequence));',
    'broker_risk_decisions': 'CREATE TABLE broker_risk_decisions(idempotency_key VARCHAR PRIMARY KEY, account_id VARCHAR NOT NULL, decision_sha256 VARCHAR NOT NULL, decision_payload VARCHAR NOT NULL, decided_at TIMESTAMP NOT NULL);',
    'broker_snapshots': 'CREATE TABLE broker_snapshots(snapshot_key VARCHAR PRIMARY KEY, reconciliation_key VARCHAR NOT NULL, "role" VARCHAR NOT NULL, account_id VARCHAR NOT NULL, snapshot_sha256 VARCHAR NOT NULL, snapshot_payload VARCHAR NOT NULL, observed_at TIMESTAMP NOT NULL);',
    'broker_submission_events': 'CREATE TABLE broker_submission_events(idempotency_key VARCHAR, event_sequence INTEGER, account_id VARCHAR NOT NULL, intent_sha256 VARCHAR NOT NULL, event_type VARCHAR NOT NULL, broker_order_id VARCHAR, order_sha256 VARCHAR, order_payload VARCHAR, occurred_at TIMESTAMP NOT NULL, PRIMARY KEY(idempotency_key, event_sequence));',
    'broker_submission_resolutions': 'CREATE TABLE broker_submission_resolutions(idempotency_key VARCHAR PRIMARY KEY, resolution_key VARCHAR NOT NULL UNIQUE, account_id VARCHAR NOT NULL, intent_sha256 VARCHAR NOT NULL, outcome VARCHAR NOT NULL, control_sha256 VARCHAR NOT NULL, evidence_sha256 VARCHAR NOT NULL, evidence_payload VARCHAR NOT NULL, resolution_sha256 VARCHAR NOT NULL, resolution_payload VARCHAR NOT NULL, observed_at VARCHAR NOT NULL);',
    'corporate_actions': 'CREATE TABLE corporate_actions(ticker VARCHAR, ex_date DATE, kind VARCHAR, "value" DOUBLE NOT NULL, "source" VARCHAR DEFAULT(\'yfinance\'), fetched_at TIMESTAMP, PRIMARY KEY(ticker, ex_date, kind));',
    'daily_opportunity_alert_events': 'CREATE TABLE daily_opportunity_alert_events(id BIGINT PRIMARY KEY, alert_id BIGINT NOT NULL, event_type VARCHAR NOT NULL, market_date DATE NOT NULL, detail VARCHAR NOT NULL, event_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(alert_id, event_type));',
    'daily_opportunity_alerts': 'CREATE TABLE daily_opportunity_alerts(id BIGINT PRIMARY KEY, assessment_id BIGINT NOT NULL UNIQUE, ticker VARCHAR NOT NULL, direction VARCHAR NOT NULL, trigger_price DOUBLE NOT NULL, created_market_date DATE NOT NULL, expires_sessions INTEGER NOT NULL, alert_sha256 VARCHAR NOT NULL UNIQUE);',
    'daily_opportunity_assessments': 'CREATE TABLE daily_opportunity_assessments(id BIGINT PRIMARY KEY, run_id BIGINT NOT NULL, ticker VARCHAR NOT NULL, decision VARCHAR NOT NULL, "action" VARCHAR NOT NULL, horizon_sessions INTEGER NOT NULL, confidence DOUBLE NOT NULL, thesis VARCHAR NOT NULL, invalidation VARCHAR NOT NULL, evidence_ids VARCHAR NOT NULL, assessment_payload VARCHAR NOT NULL, assessment_sha256 VARCHAR NOT NULL UNIQUE, created_at TIMESTAMP NOT NULL, UNIQUE(run_id, ticker));',
    'daily_opportunity_execution_quality': 'CREATE TABLE daily_opportunity_execution_quality(order_id BIGINT PRIMARY KEY, assessment_id BIGINT NOT NULL, side VARCHAR NOT NULL, decision_at TIMESTAMP NOT NULL, tool_started_at TIMESTAMP, tool_completed_at TIMESTAMP, order_recorded_at TIMESTAMP NOT NULL, fill_date DATE NOT NULL, fill_time_precision VARCHAR NOT NULL, decision_to_tool_ms DOUBLE, tool_latency_ms DOUBLE, tool_to_order_ms DOUBLE, order_to_fill_sessions INTEGER NOT NULL, arrival_price DOUBLE NOT NULL, open_price DOUBLE NOT NULL, fill_price DOUBLE NOT NULL, gap_shortfall_bps DOUBLE NOT NULL, total_shortfall_bps DOUBLE NOT NULL, cost_bps DOUBLE NOT NULL, captured_at TIMESTAMP NOT NULL, quality_sha256 VARCHAR NOT NULL UNIQUE, post_fill_position_qty DOUBLE NOT NULL, post_fill_cash DOUBLE NOT NULL, post_fill_equity DOUBLE, equity_as_of DATE);',
    'daily_opportunity_exit_events': 'CREATE TABLE daily_opportunity_exit_events(id BIGINT PRIMARY KEY, rule_sha256 VARCHAR NOT NULL, attempt INTEGER NOT NULL, signal_date DATE NOT NULL, reason VARCHAR NOT NULL, observed_close DOUBLE NOT NULL, exit_order_id BIGINT NOT NULL UNIQUE, created_at TIMESTAMP NOT NULL, event_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(rule_sha256, attempt));',
    'daily_opportunity_exit_rules': 'CREATE TABLE daily_opportunity_exit_rules(entry_order_id BIGINT PRIMARY KEY, assessment_id BIGINT NOT NULL UNIQUE, ticker VARCHAR NOT NULL, max_hold_sessions INTEGER NOT NULL, invalidation_kind VARCHAR NOT NULL, invalidation_price DOUBLE NOT NULL, signal_reference_price DOUBLE NOT NULL, created_at TIMESTAMP NOT NULL, rule_sha256 VARCHAR NOT NULL UNIQUE);',
    'daily_opportunity_news_responses': 'CREATE TABLE daily_opportunity_news_responses(run_id BIGINT NOT NULL, ticker VARCHAR NOT NULL, endpoint VARCHAR NOT NULL, requested_at TIMESTAMP NOT NULL, received_at TIMESTAMP NOT NULL, http_status INTEGER NOT NULL, content_type VARCHAR NOT NULL, response_sha256 VARCHAR NOT NULL, response_body BLOB NOT NULL, receipt_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(run_id, ticker));',
    'daily_opportunity_order_attribution': 'CREATE TABLE daily_opportunity_order_attribution(order_id BIGINT PRIMARY KEY, assessment_id BIGINT NOT NULL UNIQUE, run_id BIGINT NOT NULL, portfolio_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL, side VARCHAR NOT NULL, quantity DOUBLE NOT NULL, signal_date DATE NOT NULL, assessment_sha256 VARCHAR NOT NULL, attribution_sha256 VARCHAR NOT NULL UNIQUE, recorded_at TIMESTAMP NOT NULL);',
    'daily_opportunity_runs': 'CREATE TABLE daily_opportunity_runs(id BIGINT PRIMARY KEY, market_date DATE UNIQUE, bundle_payload VARCHAR NOT NULL, bundle_sha256 VARCHAR NOT NULL UNIQUE, news_status VARCHAR NOT NULL, model_input_payload VARCHAR, information_cutoff_at TIMESTAMP, model_latency_ms DOUBLE, model_request_sha256 VARCHAR, model_response_id VARCHAR, model_response_payload VARCHAR, status VARCHAR NOT NULL, reason VARCHAR, started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP);',
    'daily_opportunity_tool_attempts': 'CREATE TABLE daily_opportunity_tool_attempts(id BIGINT PRIMARY KEY, assessment_id BIGINT NOT NULL UNIQUE, run_id BIGINT NOT NULL, idempotency_key VARCHAR NOT NULL UNIQUE, request_payload VARCHAR NOT NULL, request_sha256 VARCHAR NOT NULL, status VARCHAR NOT NULL, response_id VARCHAR, call_id VARCHAR, arguments_payload VARCHAR, response_payload VARCHAR, started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP);',
    'disc_tickets': 'CREATE TABLE disc_tickets(id BIGINT PRIMARY KEY, ticker VARCHAR, side VARCHAR, qty DOUBLE, entry_ref DOUBLE, stop DOUBLE, "target" DOUBLE, playbook VARCHAR, emotion VARCHAR, notes VARCHAR, gates VARCHAR, status VARCHAR, order_id BIGINT, created_at TIMESTAMP);',
    'earnings_calendar': 'CREATE TABLE earnings_calendar(ticker VARCHAR, earnings_date DATE, as_of DATE, is_estimate BOOLEAN, "source" VARCHAR DEFAULT(\'yfinance\'), fetched_at TIMESTAMP, PRIMARY KEY(ticker, earnings_date, as_of));',
    'earnings_fetch_log': 'CREATE TABLE earnings_fetch_log(ticker VARCHAR NOT NULL, as_of DATE NOT NULL, status VARCHAR NOT NULL, n_dates INTEGER NOT NULL, "source" VARCHAR DEFAULT(\'yfinance\'), attempted_at TIMESTAMP NOT NULL, CHECK((status IN (\'ok\', \'empty\', \'failed\'))));',
    'experiment_results': 'CREATE TABLE experiment_results(experiment_id VARCHAR, config_hash VARCHAR, run_at TIMESTAMP, "partition" VARCHAR, n_trades INTEGER, mean_ret DOUBLE, std_ret DOUBLE, t_stat DOUBLE, gross_cagr DOUBLE, net_cagr DOUBLE, ann_mean_net DOUBLE, sharpe_annual DOUBLE, deflated_sharpe DOUBLE, sr0_benchmark DOUBLE, max_drawdown DOUBLE, skew DOUBLE, kurtosis DOUBLE, cost_roundtrip_bps DOUBLE, variants_tried INTEGER, hypothesis VARCHAR, verdict VARCHAR, meta_json VARCHAR, trade_date DATE, gross_ret DOUBLE, net_ret DOUBLE, PRIMARY KEY(experiment_id, config_hash, "partition", run_at));',
    'fundamentals': 'CREATE TABLE fundamentals(ticker VARCHAR, as_of DATE, market_cap DOUBLE, trailing_pe DOUBLE, forward_pe DOUBLE, price_to_book DOUBLE, price_to_sales DOUBLE, enterprise_value DOUBLE, ev_to_ebitda DOUBLE, ev_to_revenue DOUBLE, ebitda DOUBLE, trailing_eps DOUBLE, forward_eps DOUBLE, profit_margins DOUBLE, dividend_yield DOUBLE, beta DOUBLE, shares_outstanding DOUBLE, sector VARCHAR, industry VARCHAR, quote_type VARCHAR, currency VARCHAR, "source" VARCHAR DEFAULT(\'yfinance\'), fetched_at TIMESTAMP, PRIMARY KEY(ticker, as_of));',
    'fundamentals_fetch_log': 'CREATE TABLE fundamentals_fetch_log(ticker VARCHAR NOT NULL, as_of DATE NOT NULL, status VARCHAR NOT NULL, n_fields INTEGER NOT NULL, "source" VARCHAR DEFAULT(\'yfinance\'), attempted_at TIMESTAMP, CHECK((status IN (\'ok\', \'failed\'))));',
    'instruments': 'CREATE TABLE instruments(instrument_id VARCHAR PRIMARY KEY, kind VARCHAR NOT NULL, underlying VARCHAR, multiplier DOUBLE NOT NULL, expiry DATE, strike DOUBLE, "right" VARCHAR, exercise_style VARCHAR, settlement VARCHAR, deliverable VARCHAR, currency VARCHAR DEFAULT(\'USD\'), "source" VARCHAR, first_seen DATE, last_seen DATE);',
    'intraday_prices': 'CREATE TABLE intraday_prices(ticker VARCHAR, ts TIMESTAMP, "interval" VARCHAR, open DOUBLE, high DOUBLE, low DOUBLE, "close" DOUBLE, volume BIGINT, "source" VARCHAR DEFAULT(\'yfinance\'), as_of DATE, PRIMARY KEY(ticker, ts, "interval"));',
    'job_resolutions': 'CREATE TABLE job_resolutions(job_id BIGINT PRIMARY KEY, payload VARCHAR NOT NULL, sha256 VARCHAR NOT NULL, recorded_at TIMESTAMP NOT NULL);',
    'jobs': "CREATE TABLE jobs(id INTEGER PRIMARY KEY, kind VARCHAR, params VARCHAR, state VARCHAR DEFAULT('queued'), progress VARCHAR, created_at TIMESTAMP, updated_at TIMESTAMP, priority INTEGER DEFAULT(100), mem_mb INTEGER DEFAULT(0), last_error VARCHAR, timeout_s INTEGER);",
    'macro_signals': 'CREATE TABLE macro_signals(series VARCHAR, obs_date DATE, "value" DOUBLE NOT NULL, fetch_as_of DATE NOT NULL, PRIMARY KEY(series, obs_date));',
    'p15_book_contracts': 'CREATE TABLE p15_book_contracts(portfolio_id VARCHAR PRIMARY KEY, mechanics_version VARCHAR NOT NULL, config_sha256 VARCHAR NOT NULL UNIQUE, initialized_at TIMESTAMP NOT NULL);',
    'p15_book_fills': 'CREATE TABLE p15_book_fills(intent_id BIGINT PRIMARY KEY, order_id BIGINT NOT NULL UNIQUE, portfolio_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL, side VARCHAR NOT NULL, qty DOUBLE NOT NULL, fill_date DATE NOT NULL, open_px DOUBLE NOT NULL, fill_px DOUBLE NOT NULL, slippage_bps DOUBLE NOT NULL, cost_bps DOUBLE NOT NULL, execution_profile VARCHAR NOT NULL, median_dollar_vol DOUBLE, participation DOUBLE, impact_bps DOUBLE NOT NULL, fee_bps DOUBLE NOT NULL);',
    'p15_book_state': 'CREATE TABLE p15_book_state(portfolio_id VARCHAR PRIMARY KEY, peak_equity DOUBLE NOT NULL, entry_halted BOOLEAN NOT NULL, updated_at TIMESTAMP NOT NULL);',
    'p15_book_windows': 'CREATE TABLE p15_book_windows(portfolio_id VARCHAR, market_date DATE, equity DOUBLE NOT NULL, cash DOUBLE NOT NULL, n_positions INTEGER NOT NULL, carried VARCHAR NOT NULL, completed_at TIMESTAMP NOT NULL, PRIMARY KEY(portfolio_id, market_date));',
    'p15_evaluation_look_anchors': 'CREATE TABLE p15_evaluation_look_anchors(policy_id VARCHAR, registration_sha256 VARCHAR, look_sessions INTEGER, look_sha256 VARCHAR NOT NULL UNIQUE, external_anchor_sha256 VARCHAR, PRIMARY KEY(policy_id, registration_sha256, look_sessions));',
    'p15_evaluation_looks': 'CREATE TABLE p15_evaluation_looks(schema_version INTEGER NOT NULL, policy_id VARCHAR NOT NULL, registration_sha256 VARCHAR NOT NULL, look_sessions INTEGER NOT NULL, through_market_date DATE NOT NULL, evaluated_at TIMESTAMP NOT NULL, source_prefix_sha256 VARCHAR NOT NULL, previous_look_sha256 VARCHAR, result_payload VARCHAR NOT NULL, look_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(policy_id, registration_sha256, look_sessions));',
    'p15_evaluation_origin_grid': 'CREATE TABLE p15_evaluation_origin_grid(policy_id VARCHAR, registration_sha256 VARCHAR, origin_index INTEGER, market_date DATE NOT NULL, eligibility VARCHAR NOT NULL, skip_reason VARCHAR, decided_at TIMESTAMP NOT NULL, forward_entry_at TIMESTAMP NOT NULL, source_sha256 VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE, PRIMARY KEY(policy_id, registration_sha256, origin_index));',
    'p15_event_calls': 'CREATE TABLE p15_event_calls(id BIGINT PRIMARY KEY, window_id VARCHAR NOT NULL, chunk_index INTEGER NOT NULL, request_payload VARCHAR NOT NULL, request_sha256 VARCHAR NOT NULL UNIQUE, response_payload VARCHAR, response_sha256 VARCHAR, status VARCHAR NOT NULL, "error" VARCHAR, started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP, call_sha256 VARCHAR UNIQUE, UNIQUE(window_id, chunk_index));',
    'p15_event_decisions': 'CREATE TABLE p15_event_decisions(id BIGINT PRIMARY KEY, window_id VARCHAR NOT NULL, trigger_id BIGINT NOT NULL UNIQUE, ticker VARCHAR NOT NULL, event_type VARCHAR NOT NULL, scoring_status VARCHAR NOT NULL, decision_payload VARCHAR NOT NULL, decision_sha256 VARCHAR NOT NULL UNIQUE, triggered_at TIMESTAMP NOT NULL, decision_at TIMESTAMP NOT NULL, latency_ms DOUBLE NOT NULL);',
    'p15_event_labels': 'CREATE TABLE p15_event_labels(id BIGINT PRIMARY KEY, decision_id BIGINT NOT NULL, horizon_sessions INTEGER NOT NULL, label_basis VARCHAR NOT NULL, entry_at TIMESTAMP NOT NULL, exit_date DATE NOT NULL, entry_px DOUBLE NOT NULL, exit_close DOUBLE NOT NULL, asset_return DOUBLE NOT NULL, spy_return DOUBLE NOT NULL, net_return DOUBLE NOT NULL, net_excess_return DOUBLE NOT NULL, missing_bar_status VARCHAR NOT NULL, price_prefix_sha256 VARCHAR NOT NULL, labeled_at TIMESTAMP NOT NULL, label_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(decision_id, horizon_sessions, label_basis));',
    'p15_event_source_state': 'CREATE TABLE p15_event_source_state(policy_id VARCHAR PRIMARY KEY, evidence_started_at TIMESTAMP NOT NULL, scanned_through_at TIMESTAMP NOT NULL, start_sha256 VARCHAR NOT NULL UNIQUE);',
    'p15_event_triggers': 'CREATE TABLE p15_event_triggers(id BIGINT PRIMARY KEY, session_date DATE NOT NULL, ticker VARCHAR NOT NULL, "source" VARCHAR NOT NULL, event_type VARCHAR NOT NULL, event_at TIMESTAMP NOT NULL, available_at TIMESTAMP NOT NULL, triggered_at TIMESTAMP NOT NULL, fact_sha256 VARCHAR NOT NULL, status VARCHAR NOT NULL, reason VARCHAR, trigger_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(session_date, ticker, "source"));',
    'p15_event_windows': 'CREATE TABLE p15_event_windows(id BIGINT PRIMARY KEY, window_id VARCHAR NOT NULL UNIQUE, session_date DATE NOT NULL, observed_at TIMESTAMP NOT NULL, information_cutoff_at TIMESTAMP NOT NULL, completed_at TIMESTAMP, status VARCHAR NOT NULL, reason VARCHAR, source_summary VARCHAR NOT NULL, trigger_count INTEGER NOT NULL, decision_count INTEGER NOT NULL, skipped_count INTEGER NOT NULL, window_sha256 VARCHAR UNIQUE);',
    'p15_execution_quality': 'CREATE TABLE p15_execution_quality(intent_id BIGINT PRIMARY KEY, sim_order_id BIGINT UNIQUE, decision_id BIGINT, portfolio_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL, side VARCHAR NOT NULL, order_role VARCHAR NOT NULL, decision_at TIMESTAMP, order_at TIMESTAMP NOT NULL, attempt_date DATE NOT NULL, status VARCHAR NOT NULL, decision_to_order_ms DOUBLE, order_to_attempt_sessions INTEGER NOT NULL, arrival_price DOUBLE NOT NULL, open_px DOUBLE, fill_px DOUBLE, gap_shortfall_bps DOUBLE, total_shortfall_bps DOUBLE, cost_bps DOUBLE, captured_at TIMESTAMP NOT NULL, quality_sha256 VARCHAR NOT NULL UNIQUE);',
    'p15_limit_attempts': 'CREATE TABLE p15_limit_attempts(intent_id BIGINT, attempt_date DATE, limit_px DOUBLE NOT NULL, open_px DOUBLE, counterfactual_fill_px DOUBLE, outcome VARCHAR NOT NULL, reject_reason VARCHAR, PRIMARY KEY(intent_id, attempt_date));',
    'p15_limit_labels': 'CREATE TABLE p15_limit_labels(intent_id BIGINT PRIMARY KEY, attempt_date DATE NOT NULL, horizon_sessions INTEGER NOT NULL, entry_px DOUBLE NOT NULL, exit_date DATE NOT NULL, exit_close DOUBLE NOT NULL, net_return DOUBLE NOT NULL, spy_net_return DOUBLE NOT NULL, net_excess_return DOUBLE NOT NULL, price_prefix_sha256 VARCHAR NOT NULL, labeled_at TIMESTAMP NOT NULL, label_sha256 VARCHAR NOT NULL UNIQUE);',
    'p15_open_label_fetch_receipts': 'CREATE TABLE p15_open_label_fetch_receipts(id BIGINT PRIMARY KEY, ticker VARCHAR NOT NULL, provider_ticker VARCHAR NOT NULL, market_date DATE NOT NULL, requested_at TIMESTAMP NOT NULL, completed_at TIMESTAMP NOT NULL, "source" VARCHAR NOT NULL, status VARCHAR NOT NULL, outcome_reason VARCHAR, request_sha256 VARCHAR NOT NULL, response_sha256 VARCHAR NOT NULL, receipt_sha256 VARCHAR NOT NULL UNIQUE);',
    'p15_order_intents': 'CREATE TABLE p15_order_intents(id BIGINT PRIMARY KEY, decision_id BIGINT, portfolio_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL, side VARCHAR NOT NULL, qty DOUBLE NOT NULL, signal_date DATE NOT NULL, order_role VARCHAR NOT NULL, priority INTEGER NOT NULL, signal_close DOUBLE NOT NULL, entry_atr DOUBLE, limit_px DOUBLE, status VARCHAR NOT NULL, reason VARCHAR, sim_order_id BIGINT UNIQUE, created_at TIMESTAMP NOT NULL, UNIQUE(decision_id, portfolio_id, order_role), UNIQUE(portfolio_id, ticker, side, signal_date, order_role));',
    'p15_position_rules': 'CREATE TABLE p15_position_rules(portfolio_id VARCHAR, ticker VARCHAR, entry_intent_id BIGINT NOT NULL UNIQUE, entry_order_id BIGINT NOT NULL UNIQUE, entry_date DATE NOT NULL, entry_atr DOUBLE NOT NULL, stop_px DOUBLE NOT NULL, status VARCHAR NOT NULL, PRIMARY KEY(portfolio_id, ticker));',
    'p15_preopen_decisions': 'CREATE TABLE p15_preopen_decisions(id BIGINT PRIMARY KEY, run_id BIGINT NOT NULL, intent_id BIGINT NOT NULL, portfolio_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL, decision VARCHAR NOT NULL, reason VARCHAR NOT NULL, evidence_ids VARCHAR NOT NULL, decision_sha256 VARCHAR NOT NULL UNIQUE, applied_at TIMESTAMP NOT NULL, UNIQUE(run_id, intent_id));',
    'p15_preopen_news_responses': 'CREATE TABLE p15_preopen_news_responses(run_id BIGINT, ticker VARCHAR, endpoint VARCHAR NOT NULL, requested_at TIMESTAMP NOT NULL, received_at TIMESTAMP NOT NULL, http_status INTEGER NOT NULL, content_type VARCHAR NOT NULL, response_sha256 VARCHAR NOT NULL, response_body BLOB NOT NULL, receipt_sha256 VARCHAR NOT NULL, PRIMARY KEY(run_id, ticker));',
    'p15_preopen_runs': 'CREATE TABLE p15_preopen_runs(id BIGINT PRIMARY KEY, policy_id VARCHAR NOT NULL, session_date DATE NOT NULL, status VARCHAR NOT NULL, reason VARCHAR, input_payload VARCHAR NOT NULL, input_sha256 VARCHAR NOT NULL UNIQUE, response_payload VARCHAR, response_sha256 VARCHAR, started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP, run_sha256 VARCHAR UNIQUE, UNIQUE(policy_id, session_date));',
    'p15_price_fetch_batches': 'CREATE TABLE p15_price_fetch_batches(id BIGINT PRIMARY KEY, market_date DATE NOT NULL, attempted_at TIMESTAMP NOT NULL, "source" VARCHAR NOT NULL, requested_count INTEGER NOT NULL, failed_count INTEGER NOT NULL, present_count INTEGER NOT NULL, missing_count INTEGER NOT NULL, batch_sha256 VARCHAR NOT NULL UNIQUE);',
    'p15_rss_checkpoints': 'CREATE TABLE p15_rss_checkpoints(source_id VARCHAR PRIMARY KEY, byte_offset BIGINT NOT NULL, line_count BIGINT NOT NULL, file_identity VARCHAR NOT NULL, updated_at TIMESTAMP NOT NULL);',
    'p15_rss_failures': 'CREATE TABLE p15_rss_failures(id BIGINT PRIMARY KEY, source_id VARCHAR NOT NULL, byte_offset BIGINT NOT NULL, byte_count BIGINT NOT NULL, receipt_sha256 VARCHAR NOT NULL, response_sha256 VARCHAR NOT NULL, invalid_lines INTEGER NOT NULL, failure_payload VARCHAR NOT NULL, detected_at TIMESTAMP NOT NULL, failure_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(source_id, byte_offset, response_sha256));',
    'p15_scoring_news_responses': 'CREATE TABLE p15_scoring_news_responses(run_id BIGINT NOT NULL, ticker VARCHAR NOT NULL, endpoint VARCHAR NOT NULL, requested_at TIMESTAMP NOT NULL, received_at TIMESTAMP NOT NULL, http_status INTEGER NOT NULL, content_type VARCHAR NOT NULL, response_sha256 VARCHAR NOT NULL, response_body BLOB NOT NULL, receipt_sha256 VARCHAR NOT NULL, UNIQUE(run_id, ticker), UNIQUE(receipt_sha256));',
    'p15_scoring_runs': 'CREATE TABLE p15_scoring_runs(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, policy_id VARCHAR NOT NULL, market_date DATE NOT NULL, universe_payload VARCHAR NOT NULL, universe_sha256 VARCHAR NOT NULL, context_payload VARCHAR NOT NULL, context_sha256 VARCHAR NOT NULL, status VARCHAR NOT NULL, reason VARCHAR, information_cutoff_at TIMESTAMP NOT NULL, started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP, aggregate_trace_sha256 VARCHAR, UNIQUE(policy_id, market_date), UNIQUE(universe_sha256));',
    'p15_scoring_samples': 'CREATE TABLE p15_scoring_samples(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, run_id BIGINT NOT NULL, chunk_index INTEGER NOT NULL, sample_index INTEGER NOT NULL, permutation_seed BIGINT NOT NULL, ticker_order VARCHAR NOT NULL, request_payload VARCHAR NOT NULL, request_sha256 VARCHAR NOT NULL, status VARCHAR NOT NULL, response_id VARCHAR, response_payload VARCHAR, response_sha256 VARCHAR, model VARCHAR, model_version VARCHAR, proxy_version VARCHAR, proxy_source_sha256 VARCHAR, traecli_runtime VARCHAR, upstream_model_family VARCHAR, upstream_request_id VARCHAR, model_catalog_entry_sha256 VARCHAR, input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, "error" VARCHAR, started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP, UNIQUE(run_id, chunk_index, sample_index), UNIQUE(request_sha256));',
    'p16_book_contracts': 'CREATE TABLE p16_book_contracts(book_instance_id VARCHAR PRIMARY KEY, logical_portfolio_id VARCHAR NOT NULL, registration_sha256 VARCHAR NOT NULL, portfolio_id VARCHAR NOT NULL UNIQUE, mechanics_version VARCHAR NOT NULL, calibration_sha256 VARCHAR NOT NULL, activation_date DATE, initial_capital DOUBLE NOT NULL, risk_aversion DOUBLE NOT NULL, cost_per_turnover DOUBLE NOT NULL, no_trade_band DOUBLE NOT NULL, config_json VARCHAR NOT NULL, contract_sha256 VARCHAR NOT NULL UNIQUE, created_at TIMESTAMP NOT NULL, UNIQUE(logical_portfolio_id, registration_sha256));',
    'p16_book_fills': 'CREATE TABLE p16_book_fills(intent_id VARCHAR PRIMARY KEY, order_id BIGINT NOT NULL UNIQUE, book_instance_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL, side VARCHAR NOT NULL, qty DOUBLE NOT NULL, fill_date DATE NOT NULL, open_px DOUBLE NOT NULL, fill_px DOUBLE NOT NULL, slippage_bps DOUBLE NOT NULL, cost_bps DOUBLE NOT NULL, execution_profile VARCHAR NOT NULL, median_dollar_vol DOUBLE, participation DOUBLE, impact_bps DOUBLE NOT NULL, fee_bps DOUBLE NOT NULL, source_sha256 VARCHAR NOT NULL, fill_sha256 VARCHAR NOT NULL UNIQUE);',
    'p16_book_state': 'CREATE TABLE p16_book_state(book_instance_id VARCHAR, market_date DATE, peak_equity DOUBLE NOT NULL, entry_halted BOOLEAN NOT NULL, equity DOUBLE NOT NULL, cash DOUBLE NOT NULL, spy_mark DOUBLE, stock_marks_json VARCHAR NOT NULL, position_state_sha256 VARCHAR NOT NULL, previous_state_sha256 VARCHAR, state_sha256 VARCHAR NOT NULL UNIQUE, recorded_at TIMESTAMP NOT NULL, PRIMARY KEY(book_instance_id, market_date));',
    'p16_book_windows': 'CREATE TABLE p16_book_windows(book_instance_id VARCHAR, market_date DATE, information_cutoff_at TIMESTAMP NOT NULL, risk_sha256 VARCHAR NOT NULL, score_sha256 VARCHAR NOT NULL, previous_state_sha256 VARCHAR, target_sha256 VARCHAR NOT NULL, status VARCHAR NOT NULL, reason VARCHAR, started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP, window_sha256 VARCHAR NOT NULL UNIQUE, PRIMARY KEY(book_instance_id, market_date));',
    'p16_calibrations': 'CREATE TABLE p16_calibrations(calibration_sha256 VARCHAR PRIMARY KEY, registration_sha256 VARCHAR NOT NULL, selected_lambda DOUBLE NOT NULL, cost_per_turnover DOUBLE NOT NULL, snapshot_count INTEGER NOT NULL, payload_json VARCHAR NOT NULL, recorded_at TIMESTAMP NOT NULL);',
    'p16_challenger_attempts': 'CREATE TABLE p16_challenger_attempts(record_id VARCHAR PRIMARY KEY, parent_id VARCHAR NOT NULL, recorded_at TIMESTAMP NOT NULL, payload VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE);',
    'p16_challenger_outputs': 'CREATE TABLE p16_challenger_outputs(record_id VARCHAR PRIMARY KEY, parent_id VARCHAR NOT NULL, recorded_at TIMESTAMP NOT NULL, payload VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE);',
    'p16_challenger_receipts': 'CREATE TABLE p16_challenger_receipts(record_id VARCHAR PRIMARY KEY, parent_id VARCHAR NOT NULL, recorded_at TIMESTAMP NOT NULL, payload VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE);',
    'p16_challenger_runs': 'CREATE TABLE p16_challenger_runs(record_id VARCHAR PRIMARY KEY, parent_id VARCHAR NOT NULL, recorded_at TIMESTAMP NOT NULL, payload VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE);',
    'p16_construct_targets': 'CREATE TABLE p16_construct_targets(book_instance_id VARCHAR, signal_date DATE, risk_snapshot_sha256 VARCHAR NOT NULL, score_sha256 VARCHAR NOT NULL, ic_source_sha256 VARCHAR NOT NULL, risk_aversion DOUBLE NOT NULL, cost_per_turnover DOUBLE NOT NULL, solver_status VARCHAR NOT NULL, residuals_json VARCHAR NOT NULL, sector_coverage DOUBLE, sector_status VARCHAR, continuous_json VARCHAR, banded_json VARCHAR, rounded_json VARCHAR, target_sha256 VARCHAR NOT NULL UNIQUE, recorded_at TIMESTAMP NOT NULL, PRIMARY KEY(book_instance_id, signal_date));',
    'p16_evaluation_artifacts': 'CREATE TABLE p16_evaluation_artifacts(artifact_sha256 VARCHAR PRIMARY KEY, registration_sha256 VARCHAR NOT NULL, artifact_kind VARCHAR NOT NULL, artifact_key VARCHAR NOT NULL, market_date DATE NOT NULL, information_cutoff_at TIMESTAMP NOT NULL, recorded_at TIMESTAMP NOT NULL, source_sha256 VARCHAR NOT NULL, payload_json VARCHAR NOT NULL, payload_sha256 VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL, UNIQUE(registration_sha256, artifact_kind, artifact_key, market_date, information_cutoff_at));',
    'p16_filing_acceptance': 'CREATE TABLE p16_filing_acceptance(resolution_sha256 VARCHAR PRIMARY KEY, policy_id VARCHAR NOT NULL, accession VARCHAR NOT NULL, accepted_at TIMESTAMP NOT NULL, resolved_at TIMESTAMP NOT NULL, reference VARCHAR NOT NULL, json_crosscheck VARCHAR NOT NULL, input_json VARCHAR NOT NULL, input_sha256 VARCHAR NOT NULL, UNIQUE(policy_id, accession));',
    'p16_filing_accessions': 'CREATE TABLE p16_filing_accessions(policy_id VARCHAR, accession VARCHAR, cik VARCHAR NOT NULL, first_response_id VARCHAR NOT NULL, previous_response_id VARCHAR, previous_accessions_sha256 VARCHAR NOT NULL, discovered_at TIMESTAMP NOT NULL, activation_at TIMESTAMP NOT NULL, cik_entered_at TIMESTAMP NOT NULL, securities_json VARCHAR NOT NULL, primary_security_id VARCHAR NOT NULL, metadata_json VARCHAR NOT NULL, metadata_sha256 VARCHAR NOT NULL, discovery_status VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE, PRIMARY KEY(policy_id, accession));',
    'p16_filing_bundles': 'CREATE TABLE p16_filing_bundles(bundle_sha256 VARCHAR PRIMARY KEY, policy_id VARCHAR NOT NULL, accession VARCHAR NOT NULL, revision INTEGER NOT NULL, accepted_at TIMESTAMP NOT NULL, available_at TIMESTAMP NOT NULL, ingested_at TIMESTAMP NOT NULL, status VARCHAR NOT NULL, eligibility_status VARCHAR NOT NULL, exhibit_status VARCHAR NOT NULL, byte_count BIGINT NOT NULL, components_json VARCHAR NOT NULL, components_sha256 VARCHAR NOT NULL, normalized_json VARCHAR NOT NULL, normalized_sha256 VARCHAR NOT NULL, fact_sha256 VARCHAR, row_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(policy_id, accession, revision));',
    'p16_filing_cik_responses': 'CREATE TABLE p16_filing_cik_responses(response_id VARCHAR PRIMARY KEY, policy_id VARCHAR NOT NULL, scan_id VARCHAR NOT NULL, cik VARCHAR NOT NULL, received_at TIMESTAMP NOT NULL, ingested_at TIMESTAMP NOT NULL, accessions_json VARCHAR NOT NULL, accessions_sha256 VARCHAR NOT NULL, previous_response_id VARCHAR, receipt_sha256 VARCHAR NOT NULL, reused_response_id VARCHAR, source_body_sha256 VARCHAR NOT NULL, source_status VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(scan_id, cik));',
    'p16_filing_decisions': 'CREATE TABLE p16_filing_decisions(decision_sha256 VARCHAR PRIMARY KEY, work_id VARCHAR NOT NULL UNIQUE, attempt_sha256 VARCHAR NOT NULL UNIQUE, policy_id VARCHAR NOT NULL, accession VARCHAR NOT NULL, security_id VARCHAR NOT NULL, status VARCHAR NOT NULL, decided_at TIMESTAMP NOT NULL, response_json VARCHAR, response_sha256 VARCHAR, runtime_sha256 VARCHAR NOT NULL, model_latency_ms BIGINT NOT NULL, retrieval_latency_ms BIGINT NOT NULL, reason VARCHAR, UNIQUE(policy_id, accession, security_id));',
    'p16_filing_labels': 'CREATE TABLE p16_filing_labels(label_sha256 VARCHAR PRIMARY KEY, decision_sha256 VARCHAR NOT NULL, horizon INTEGER NOT NULL, entry_basis VARCHAR NOT NULL, labelled_at TIMESTAMP NOT NULL, payload_json VARCHAR NOT NULL, payload_sha256 VARCHAR NOT NULL, UNIQUE(decision_sha256, horizon, entry_basis));',
    'p16_filing_scans': 'CREATE TABLE p16_filing_scans(scan_id VARCHAR PRIMARY KEY, policy_id VARCHAR NOT NULL, session_date DATE NOT NULL, activation_at TIMESTAMP NOT NULL, started_at TIMESTAMP NOT NULL, universe_json VARCHAR NOT NULL, universe_sha256 VARCHAR NOT NULL, map_sha256 VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE);',
    'p16_filing_score_attempts': 'CREATE TABLE p16_filing_score_attempts(attempt_sha256 VARCHAR PRIMARY KEY, work_id VARCHAR NOT NULL, attempt_number INTEGER NOT NULL, started_at TIMESTAMP NOT NULL, request_json VARCHAR NOT NULL, request_sha256 VARCHAR NOT NULL, runtime_json VARCHAR NOT NULL, runtime_sha256 VARCHAR NOT NULL, UNIQUE(work_id, attempt_number));',
    'p16_filing_work_events': 'CREATE TABLE p16_filing_work_events(event_sha256 VARCHAR PRIMARY KEY, work_id VARCHAR NOT NULL, policy_id VARCHAR NOT NULL, work_kind VARCHAR NOT NULL, accession VARCHAR NOT NULL, security_id VARCHAR NOT NULL, session_date DATE NOT NULL, "sequence" INTEGER NOT NULL, status VARCHAR NOT NULL, event_at TIMESTAMP NOT NULL, not_before TIMESTAMP NOT NULL, input_json VARCHAR NOT NULL, input_sha256 VARCHAR NOT NULL, reason VARCHAR, UNIQUE(work_id, "sequence"));',
    'p16_fill_manifests': 'CREATE TABLE p16_fill_manifests(session_date DATE PRIMARY KEY, policy_id VARCHAR NOT NULL, selected_at TIMESTAMP NOT NULL, order_cutoff_at TIMESTAMP NOT NULL, universe_sha256 VARCHAR NOT NULL, population_count INTEGER NOT NULL, sample_json VARCHAR NOT NULL, sample_sha256 VARCHAR NOT NULL UNIQUE, orders_json VARCHAR NOT NULL, orders_sha256 VARCHAR NOT NULL, targets_json VARCHAR NOT NULL, targets_sha256 VARCHAR NOT NULL, manifest_sha256 VARCHAR NOT NULL UNIQUE);',
    'p16_fill_measurements': 'CREATE TABLE p16_fill_measurements(measurement_sha256 VARCHAR PRIMARY KEY, session_date DATE NOT NULL, security_id VARCHAR NOT NULL, "source" VARCHAR NOT NULL, liquidity_tier VARCHAR NOT NULL, median_dollar_volume DOUBLE, bar_set_sha256 VARCHAR NOT NULL, measured_at TIMESTAMP NOT NULL, payload_json VARCHAR NOT NULL, UNIQUE(session_date, security_id, "source", bar_set_sha256));',
    'p16_fill_source_captures': 'CREATE TABLE p16_fill_source_captures(capture_sha256 VARCHAR PRIMARY KEY, session_date DATE NOT NULL, security_id VARCHAR NOT NULL, "source" VARCHAR NOT NULL, source_version VARCHAR NOT NULL, receipt_sha256 VARCHAR NOT NULL, attempted_at TIMESTAMP NOT NULL, status VARCHAR NOT NULL, reason VARCHAR, payload_json VARCHAR NOT NULL, payload_sha256 VARCHAR NOT NULL, UNIQUE(session_date, security_id, "source", receipt_sha256));',
    'p16_limit_attempts': 'CREATE TABLE p16_limit_attempts(intent_id VARCHAR, attempt_date DATE, limit_px DOUBLE NOT NULL, open_px DOUBLE, counterfactual_fill_px DOUBLE, outcome VARCHAR NOT NULL, reject_reason VARCHAR, PRIMARY KEY(intent_id, attempt_date));',
    'p16_limit_labels': 'CREATE TABLE p16_limit_labels(intent_id VARCHAR PRIMARY KEY, attempt_date DATE NOT NULL, horizon_sessions INTEGER NOT NULL, entry_px DOUBLE NOT NULL, exit_date DATE NOT NULL, exit_close DOUBLE NOT NULL, net_return DOUBLE NOT NULL, spy_net_return DOUBLE NOT NULL, net_excess_return DOUBLE NOT NULL, price_prefix_sha256 VARCHAR NOT NULL, labeled_at TIMESTAMP NOT NULL, label_sha256 VARCHAR NOT NULL UNIQUE);',
    'p16_order_intents': 'CREATE TABLE p16_order_intents(intent_id VARCHAR PRIMARY KEY, book_instance_id VARCHAR NOT NULL, signal_date DATE NOT NULL, ticker VARCHAR NOT NULL, side VARCHAR NOT NULL, order_role VARCHAR NOT NULL, target_weight DOUBLE NOT NULL, rounded_qty DOUBLE NOT NULL, source_sha256 VARCHAR NOT NULL, limit_px DOUBLE, entry_atr DOUBLE, expected_session DATE NOT NULL, status VARCHAR NOT NULL, reason VARCHAR, sim_order_id BIGINT UNIQUE, created_at TIMESTAMP NOT NULL, intent_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(book_instance_id, signal_date, ticker, side, order_role));',
    'p16_position_rules': 'CREATE TABLE p16_position_rules(book_instance_id VARCHAR, ticker VARCHAR, entry_intent_id VARCHAR, entry_order_id BIGINT NOT NULL, entry_date DATE NOT NULL, entry_atr DOUBLE NOT NULL, stop_px DOUBLE NOT NULL, status VARCHAR NOT NULL, exit_intent_id VARCHAR, PRIMARY KEY(book_instance_id, ticker, entry_intent_id));',
    'p16_screen_versions': 'CREATE TABLE p16_screen_versions(screen_date DATE, computed_at TIMESTAMP, rows_payload VARCHAR NOT NULL, content_sha256 VARCHAR NOT NULL, snapshot_sha256 VARCHAR NOT NULL UNIQUE, PRIMARY KEY(screen_date, computed_at));',
    'p16_sec_request_events': 'CREATE TABLE p16_sec_request_events(event_sha256 VARCHAR PRIMARY KEY, request_id VARCHAR NOT NULL, scan_id VARCHAR NOT NULL, consumer VARCHAR NOT NULL, request_kind VARCHAR NOT NULL, attempt INTEGER NOT NULL, event_kind VARCHAR NOT NULL, event_at TIMESTAMP NOT NULL, status_code INTEGER, pause_until TIMESTAMP, blocked BOOLEAN, payload_json VARCHAR NOT NULL, payload_sha256 VARCHAR NOT NULL, UNIQUE(request_id, attempt, event_kind));',
    'p16_sequential_origin_events': 'CREATE TABLE p16_sequential_origin_events(registration_sha256 VARCHAR NOT NULL, family_id VARCHAR NOT NULL, comparison_id VARCHAR NOT NULL, trial_id VARCHAR NOT NULL, control_trial_id VARCHAR NOT NULL, epoch_session DATE NOT NULL, session_index INTEGER NOT NULL, market_date DATE NOT NULL, event_kind VARCHAR NOT NULL, status VARCHAR NOT NULL, reason VARCHAR, decided_at TIMESTAMP NOT NULL, forward_entry_at TIMESTAMP NOT NULL, labels_available_at TIMESTAMP, delta_ic DOUBLE, source_sha256 VARCHAR NOT NULL, recorded_at TIMESTAMP NOT NULL, event_sha256 VARCHAR PRIMARY KEY, row_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(registration_sha256, family_id, comparison_id, session_index, event_kind), UNIQUE(registration_sha256, family_id, comparison_id, market_date, event_kind));',
    'p16_trial_register_v4': 'CREATE TABLE p16_trial_register_v4(record_sha256 VARCHAR PRIMARY KEY, record_kind VARCHAR NOT NULL, trial_id VARCHAR, event_at TIMESTAMP NOT NULL, recorded_at TIMESTAMP NOT NULL, source_sha256 VARCHAR, payload VARCHAR NOT NULL, append_sequence BIGINT NOT NULL UNIQUE, row_sha256 VARCHAR NOT NULL UNIQUE);',
    'paper_account_intakes': 'CREATE TABLE paper_account_intakes(intent_id VARCHAR PRIMARY KEY, account_id VARCHAR NOT NULL, order_id BIGINT NOT NULL UNIQUE, payload VARCHAR NOT NULL, sha256 VARCHAR NOT NULL, received_at TIMESTAMP NOT NULL, receipt VARCHAR);',
    'paper_account_specs': 'CREATE TABLE paper_account_specs(account_id VARCHAR PRIMARY KEY, payload VARCHAR NOT NULL, sha256 VARCHAR NOT NULL, created_at TIMESTAMP NOT NULL, schema_version INTEGER DEFAULT(1));',
    'pit_import_batches': 'CREATE TABLE pit_import_batches(batch_sha256 VARCHAR PRIMARY KEY, schema_version INTEGER NOT NULL, dataset_id VARCHAR NOT NULL, vendor VARCHAR NOT NULL, source_version VARCHAR NOT NULL, license_id VARCHAR NOT NULL, license_accepted_at TIMESTAMP NOT NULL, redistribution_allowed BOOLEAN NOT NULL, manifest_payload VARCHAR NOT NULL, file_sha256 VARCHAR NOT NULL, row_count BIGINT NOT NULL, imported_at TIMESTAMP NOT NULL);',
    'pit_import_rows': 'CREATE TABLE pit_import_rows(batch_sha256 VARCHAR, row_number BIGINT, dataset_kind VARCHAR NOT NULL, entity_id VARCHAR NOT NULL, security_id VARCHAR NOT NULL, event_at TIMESTAMP NOT NULL, published_at TIMESTAMP, available_at TIMESTAMP NOT NULL, payload VARCHAR NOT NULL, payload_sha256 VARCHAR NOT NULL, row_sha256 VARCHAR NOT NULL UNIQUE, PRIMARY KEY(batch_sha256, row_number));',
    'portfolio_accounts': "CREATE TABLE portfolio_accounts(portfolio_id VARCHAR PRIMARY KEY, engine VARCHAR DEFAULT('league') NOT NULL, cost_profile VARCHAR DEFAULT('baseline_v1') NOT NULL, account_type VARCHAR DEFAULT('cash_legacy') NOT NULL, visibility VARCHAR DEFAULT('public') NOT NULL, status VARCHAR, price_source VARCHAR DEFAULT('prices') NOT NULL, day_trade_rule VARCHAR DEFAULT('pdt_25k_legacy') NOT NULL, allow_short BOOLEAN DEFAULT(CAST('f' AS BOOLEAN)) NOT NULL, updated_at TIMESTAMP);",
    'portfolios': 'CREATE TABLE portfolios(id VARCHAR PRIMARY KEY, "name" VARCHAR, strategy VARCHAR, config VARCHAR, created DATE, active BOOLEAN DEFAULT(CAST(\'t\' AS BOOLEAN)), cash DOUBLE, initial_cash DOUBLE, execution_profile VARCHAR);',
    'price_fetch_attempts': 'CREATE TABLE price_fetch_attempts(id BIGINT PRIMARY KEY, ticker VARCHAR NOT NULL, market_date DATE NOT NULL, attempted_at TIMESTAMP NOT NULL, "source" VARCHAR NOT NULL, status VARCHAR NOT NULL, batch_sha256 VARCHAR NOT NULL, attempt_sha256 VARCHAR NOT NULL UNIQUE, UNIQUE(batch_sha256, ticker));',
    'price_observation_rejects': 'CREATE TABLE price_observation_rejects(observation_id VARCHAR PRIMARY KEY, batch_id VARCHAR NOT NULL, ticker VARCHAR, date DATE, ts TIMESTAMP, "interval" VARCHAR NOT NULL, open DOUBLE, high DOUBLE, low DOUBLE, "close" DOUBLE, volume VARCHAR, "source" VARCHAR, fetched_at TIMESTAMP, first_fetched_at TIMESTAMP, recorded_at TIMESTAMP NOT NULL, reason VARCHAR NOT NULL, validator_version VARCHAR NOT NULL, observation_json VARCHAR NOT NULL);',
    'price_quarantine': 'CREATE TABLE price_quarantine(ticker VARCHAR PRIMARY KEY, status VARCHAR, reason VARCHAR, evidence VARCHAR, confirmed_at TIMESTAMP, resolved_at TIMESTAMP, resolution VARCHAR);',
    'prices': 'CREATE TABLE prices(ticker VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, "close" DOUBLE, volume BIGINT, "source" VARCHAR DEFAULT(\'yfinance\'), fetched_at TIMESTAMP, first_fetched_at TIMESTAMP, PRIMARY KEY(ticker, date));',
    'review_markers': 'CREATE TABLE review_markers(ts TIMESTAMP, kind VARCHAR);',
    'screen_results': 'CREATE TABLE screen_results(run_date DATE, ticker VARCHAR, "close" DOUBLE, rs_rank INTEGER, template_score INTEGER, passes_template BOOLEAN, dist_50d DOUBLE, dist_200d DOUBLE, off_52w_low DOUBLE, off_52w_high DOUBLE, base_tight BOOLEAN, vol_dryup BOOLEAN, new_today BOOLEAN, universe_policy VARCHAR DEFAULT(\'all\'), PRIMARY KEY(run_date, ticker));',
    'sim_book_breaks': 'CREATE TABLE sim_book_breaks(portfolio_id VARCHAR, break_date DATE, kind VARCHAR, from_value VARCHAR, to_value VARCHAR, registration_revision INTEGER, note VARCHAR, created_at TIMESTAMP, PRIMARY KEY(portfolio_id, break_date, kind));',
    'sim_cash_events': 'CREATE TABLE sim_cash_events(portfolio_id VARCHAR, event_date DATE, seq INTEGER, kind VARCHAR NOT NULL, amount DOUBLE NOT NULL, instrument_id VARCHAR, ref_order_id BIGINT, note VARCHAR, created_at TIMESTAMP NOT NULL, PRIMARY KEY(portfolio_id, event_date, seq));',
    'sim_day_trades': 'CREATE TABLE sim_day_trades(portfolio_id VARCHAR, session_date DATE, instrument_id VARCHAR, open_order_id BIGINT, close_order_id BIGINT, PRIMARY KEY(portfolio_id, close_order_id));',
    'sim_dividends': 'CREATE TABLE sim_dividends(portfolio_id VARCHAR, ticker VARCHAR, ex_date DATE, qty DOUBLE, dps DOUBLE, amount DOUBLE, PRIMARY KEY(portfolio_id, ticker, ex_date));',
    'sim_equity': 'CREATE TABLE sim_equity(portfolio_id VARCHAR, date DATE, equity DOUBLE, cash DOUBLE, n_positions INTEGER, PRIMARY KEY(portfolio_id, date));',
    'sim_execution_attempts': 'CREATE TABLE sim_execution_attempts(order_id BIGINT, attempt_date DATE, execution_profile VARCHAR, raw_notional DOUBLE, median_dollar_vol DOUBLE, participation DOUBLE, outcome VARCHAR, reject_reason VARCHAR, PRIMARY KEY(order_id, attempt_date));',
    'sim_fill_costs': 'CREATE TABLE sim_fill_costs(order_id BIGINT PRIMARY KEY, execution_profile VARCHAR, participation DOUBLE, market_bps DOUBLE, impact_bps DOUBLE, fee_bps DOUBLE, total_bps DOUBLE);',
    'sim_fill_details': "CREATE TABLE sim_fill_details(order_id BIGINT PRIMARY KEY, fill_ts TIMESTAMP, fill_kind VARCHAR, price_source VARCHAR, bar_ref VARCHAR, reference_px DOUBLE, multiplier DOUBLE DEFAULT(1), late_settled BOOLEAN DEFAULT(CAST('f' AS BOOLEAN)), settled_at TIMESTAMP);",
    'sim_fill_fees': 'CREATE TABLE sim_fill_fees(order_id BIGINT PRIMARY KEY, cost_profile VARCHAR NOT NULL, commission DOUBLE, exchange_fee DOUBLE, clearing_fee DOUBLE, pass_through DOUBLE, cat_fee DOUBLE, sec_fee DOUBLE, finra_taf DOUBLE, occ_fee DOUBLE, orf_fee DOUBLE, total_usd DOUBLE NOT NULL);',
    'sim_fills': 'CREATE TABLE sim_fills(order_id BIGINT, portfolio_id VARCHAR, ticker VARCHAR, side VARCHAR, qty DOUBLE, fill_date DATE, open_px DOUBLE, fill_px DOUBLE, slippage_bps DOUBLE, cost_bps DOUBLE);',
    'sim_order_details': "CREATE TABLE sim_order_details(order_id BIGINT PRIMARY KEY, instrument_id VARCHAR NOT NULL, instrument_kind VARCHAR NOT NULL, order_type VARCHAR NOT NULL, side VARCHAR NOT NULL, tif VARCHAR DEFAULT('day') NOT NULL, limit_px DOUBLE, session_date DATE NOT NULL, received_at TIMESTAMP NOT NULL, created_at TIMESTAMP, parent_order_id BIGINT, leg_no INTEGER, leg_ratio INTEGER, contingent_on BIGINT, state VARCHAR NOT NULL, state_reason VARCHAR, state_at TIMESTAMP, source_sha256 VARCHAR);",
    'sim_orders': 'CREATE TABLE sim_orders(id BIGINT PRIMARY KEY, portfolio_id VARCHAR, ticker VARCHAR, side VARCHAR, qty DOUBLE, signal_date DATE, status VARCHAR, reject_reason VARCHAR);',
    'sim_position_lots': 'CREATE TABLE sim_position_lots(portfolio_id VARCHAR, instrument_id VARCHAR, opened_session DATE, open_order_id BIGINT, qty DOUBLE, avg_px DOUBLE, PRIMARY KEY(portfolio_id, instrument_id, open_order_id));',
    'sim_positions': 'CREATE TABLE sim_positions(portfolio_id VARCHAR, ticker VARCHAR, qty DOUBLE, avg_cost DOUBLE, PRIMARY KEY(portfolio_id, ticker));',
    'sim_settlements': 'CREATE TABLE sim_settlements(portfolio_id VARCHAR, ticker VARCHAR, kind VARCHAR, qty DOUBLE, price DOUBLE, into_ticker VARCHAR, ratio DOUBLE, effective DATE, "source" VARCHAR, note VARCHAR, created_at TIMESTAMP, PRIMARY KEY(portfolio_id, ticker, effective));',
    'simulator_broker_order_keys': 'CREATE TABLE simulator_broker_order_keys(idempotency_key VARCHAR PRIMARY KEY, order_id BIGINT NOT NULL UNIQUE);',
    'source_response_receipts': 'CREATE TABLE source_response_receipts(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, "source" VARCHAR NOT NULL, dataset VARCHAR NOT NULL, endpoint VARCHAR NOT NULL, request_payload VARCHAR NOT NULL, request_sha256 VARCHAR NOT NULL, requested_at TIMESTAMP NOT NULL, received_at TIMESTAMP NOT NULL, http_status INTEGER NOT NULL, content_type VARCHAR NOT NULL, response_size_bytes BIGINT NOT NULL, response_sha256 VARCHAR NOT NULL, response_body BLOB NOT NULL, license_class VARCHAR NOT NULL, receipt_sha256 VARCHAR NOT NULL UNIQUE);',
    'split_adjustments': 'CREATE TABLE split_adjustments(ticker VARCHAR, ex_date DATE, ratio DOUBLE, outcome VARCHAR, observed DOUBLE, break_date DATE, rows_restated BIGINT, applied_at TIMESTAMP, PRIMARY KEY(ticker, ex_date));',
    'tradingview_history_attempts': 'CREATE TABLE tradingview_history_attempts(id BIGINT PRIMARY KEY, schema_version INTEGER NOT NULL, cohort_id VARCHAR NOT NULL, ticker VARCHAR NOT NULL, provider_symbol VARCHAR NOT NULL, start_date DATE NOT NULL, end_date DATE NOT NULL, status VARCHAR NOT NULL, fact_count INTEGER NOT NULL, receipt_sha256 VARCHAR, "error" VARCHAR, started_at TIMESTAMP NOT NULL, completed_at TIMESTAMP NOT NULL, attempt_sha256 VARCHAR NOT NULL UNIQUE);',
    'tradingview_history_cohorts': 'CREATE TABLE tradingview_history_cohorts(cohort_id VARCHAR PRIMARY KEY, schema_version INTEGER NOT NULL, selected_at TIMESTAMP NOT NULL, start_date DATE NOT NULL, selection_rule VARCHAR NOT NULL, selection_sha256 VARCHAR NOT NULL, symbol_count INTEGER NOT NULL, limitation VARCHAR NOT NULL);',
    'tradingview_history_symbols': 'CREATE TABLE tradingview_history_symbols(cohort_id VARCHAR, ordinal INTEGER NOT NULL, ticker VARCHAR, provider_symbol VARCHAR NOT NULL, exchange_code VARCHAR NOT NULL, PRIMARY KEY(cohort_id, ticker), UNIQUE(cohort_id, ordinal));',
    'universe': 'CREATE TABLE universe(ticker VARCHAR PRIMARY KEY, yf_ticker VARCHAR, "name" VARCHAR, exchange VARCHAR, etf BOOLEAN, member VARCHAR, added DATE, active BOOLEAN DEFAULT(CAST(\'t\' AS BOOLEAN)), liquid BOOLEAN DEFAULT(CAST(\'f\' AS BOOLEAN)), backfill_done BOOLEAN DEFAULT(CAST(\'f\' AS BOOLEAN)));',
    'universe_snapshot': 'CREATE TABLE universe_snapshot(snapshot_date DATE, ticker VARCHAR, "name" VARCHAR, exchange VARCHAR, etf BOOLEAN, member VARCHAR, active BOOLEAN, liquid BOOLEAN, PRIMARY KEY(snapshot_date, ticker));',
}
BASELINE_INDEXES: dict[str, str] = {
    'actions_fetch_log_resume_idx': 'CREATE INDEX actions_fetch_log_resume_idx ON actions_fetch_log(fetched_on, ticker, status);',
    'earnings_fetch_log_resume_idx': 'CREATE INDEX earnings_fetch_log_resume_idx ON earnings_fetch_log(as_of, ticker, status);',
    'fundamentals_fetch_log_resume_idx': 'CREATE INDEX fundamentals_fetch_log_resume_idx ON fundamentals_fetch_log(as_of, ticker, status);',
}
BASELINE_VIEWS: dict[str, str] = {
    'portfolio_accounts_v': "CREATE VIEW portfolio_accounts_v AS SELECT p.portfolio_id, COALESCE(pa.engine, 'league') AS pa_engine, COALESCE(pa.cost_profile, 'baseline_v1') AS pa_cost_profile, COALESCE(pa.account_type, 'cash_legacy') AS pa_account_type, COALESCE(pa.visibility, 'public') AS pa_visibility, COALESCE(pa.status, CASE  WHEN (p.active) THEN ('active') ELSE 'inactive' END) AS pa_status, COALESCE(pa.price_source, 'prices') AS pa_price_source, COALESCE(pa.day_trade_rule, 'pdt_25k_legacy') AS pa_day_trade_rule, COALESCE(pa.allow_short, CAST('f' AS BOOLEAN)) AS pa_allow_short, pa.updated_at AS pa_updated_at FROM (SELECT id AS portfolio_id, active FROM portfolios) AS p LEFT JOIN portfolio_accounts AS pa USING (portfolio_id);",
}

EXPECTED_TABLES = frozenset(BASELINE_TABLES)
EXPECTED_VIEWS = frozenset(BASELINE_VIEWS)
EXPECTED_SEQUENCES = frozenset(BASELINE_SEQUENCES)


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




def _columns_of(con: duckdb.DuckDBPyConnection, table: str) -> list[tuple[str, str]]:
    return [
        (str(name), str(kind)) for name, kind in con.execute(
            "SELECT column_name, data_type FROM duckdb_columns() "
            "WHERE database_name=current_database() AND schema_name='main' "
            "AND table_name=? ORDER BY column_index", [table],
        ).fetchall()
    ]


def _stored_sql(con: duckdb.DuckDBPyConnection, function: str, column: str) -> dict[str, str]:
    return dict(con.execute(
        f"SELECT {column}, sql FROM {function} WHERE database_name=current_database() "
        "AND schema_name='main' AND sql IS NOT NULL"
        + ("" if function == "duckdb_indexes()" else " AND NOT temporary")
        + ("" if function in {"duckdb_indexes()", "duckdb_sequences()"} else " AND NOT internal")
    ).fetchall())


def drifted_tables(con: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    """Existing baseline tables whose DDL differs from the frozen baseline."""
    stored = _stored_sql(con, "duckdb_tables()", "table_name")
    return tuple(sorted(
        name for name, sql in stored.items()
        if name in BASELINE_TABLES and sql != BASELINE_TABLES[name]
    ))


def _rebuild(con: duckdb.DuckDBPyConnection, tables: tuple[str, ...]) -> None:
    """Rebuild tables into the baseline DDL, keeping each row.

    Runtime ``ALTER ... ADD COLUMN`` on a long-lived store appends columns in history order
    and keeps whatever constraints the column was added with, so deployed DDL can differ from
    the baseline in column order and NOT NULL. A table is rebuilt only when every stored
    column exists in the baseline with the same type; rows are copied by column name (a
    baseline-only column takes its declared default, exactly as ``ADD COLUMN`` would) and the
    copy is proven equal before the original is released.
    """
    from engine.lib import db as engine_db  # runtime import: engine.lib.db loads migrations

    reference = engine_db.connect(":memory:", wait_s=0)
    try:
        for table in tables:
            reference.execute(BASELINE_TABLES[table])
        canonical_columns = {table: dict(_columns_of(reference, table)) for table in tables}
    finally:
        reference.close()
    for table in tables:
        columns = _columns_of(con, table)
        lost = [name for name, kind in columns if canonical_columns[table].get(name) != kind]
        if lost:
            raise ValueError(f"{table} cannot be normalized without changing columns: {lost}")
        names = ", ".join('"' + name.replace('"', '""') + '"' for name, _kind in columns)
        quoted = '"' + table.replace('"', '""') + '"'
        holding = f'"__baseline_rebuild_{table}"'
        count = con.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
        con.execute(f"CREATE TEMP TABLE {holding} AS SELECT {names} FROM {quoted}")
        con.execute(f"DROP TABLE {quoted}")
        con.execute(BASELINE_TABLES[table])
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


def _create_missing(con: duckdb.DuckDBPyConnection) -> None:
    """Create every baseline object the store lacks; replace a differing index or view."""
    stored = _stored_sql(con, "duckdb_sequences()", "sequence_name")
    for name, sql in BASELINE_SEQUENCES.items():
        if name not in stored:
            con.execute(sql)
    stored = _stored_sql(con, "duckdb_tables()", "table_name")
    for name, sql in BASELINE_TABLES.items():
        if name not in stored:
            con.execute(sql)
    stored = _stored_sql(con, "duckdb_indexes()", "index_name")
    for name, sql in BASELINE_INDEXES.items():
        if stored.get(name) != sql:
            if name in stored:
                con.execute(f'DROP INDEX "{name}"')
            con.execute(sql)
    stored = _stored_sql(con, "duckdb_views()", "view_name")
    for name, sql in BASELINE_VIEWS.items():
        if stored.get(name) != sql:
            if name in stored:
                con.execute(f'DROP VIEW "{name}"')
            con.execute(sql)


def bootstrap(con: duckdb.DuckDBPyConnection) -> None:
    """Create/upgrade the exact baseline catalog under migration authority."""
    from engine.lib.snapshots import catalog_sha256

    tables, views, sequences = _objects(con)
    has_objects = bool(tables or views or sequences)
    source_shape = None
    if has_objects:
        source_hash = catalog_sha256(con)
        source_shape = next(
            (name for name, digest in SUPPORTED_CATALOG_SHA256.items() if digest == source_hash),
            None,
        )
        if source_shape is None:
            raise ValueError(
                "database is not a supported pre-v2, v2, r15, or deployed-2026-10 catalog"
            )
    if source_shape == "baseline":
        return
    if source_shape is not None:
        _legacy_core_upgrades(con)
        if source_shape == "v2":
            _upgrade_v2_accounts(con)
        missing_columns = {
            name for name in LEGACY_PORTFOLIO_DEFAULTS
            if name not in dict(_columns_of(con, "portfolios"))
        }
        drifted = drifted_tables(con)
        if drifted != REBUILD_PLAN[source_shape]:
            raise ValueError(
                f"{source_shape} catalog would rebuild {list(drifted)}, "
                f"not its plan {list(REBUILD_PLAN[source_shape])}"
            )
        _rebuild(con, drifted)
        for name in sorted(missing_columns):
            con.execute(
                f'UPDATE portfolios SET "{name}"=? WHERE "{name}" IS NULL',
                [LEGACY_PORTFOLIO_DEFAULTS[name]],
            )
    _create_missing(con)
