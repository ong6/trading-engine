"""Machine-enforced P15 frozen registration contract."""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

from engine import daily_opportunities, p15_evaluation, p15_event_sources
from engine.lib.provenance import canonical_sha256
from farm import p15_event_runner
from server import (
    agent_evaluation,
    agent_model_client,
    p15_incremental_collect,
    p15_preopen,
    p15_scoring_runner,
)
from sim import p15_books

ROOT = Path(__file__).resolve().parents[1]
REGISTRATION_PATH = ROOT / "server" / "p15-registration.json"
REGISTERED_PATHS = {
    "engine/__init__.py",
    "engine/actions.py",
    "engine/bitemporal_facts.py",
    "engine/collect.py",
    "engine/daily_opportunities.py",
    "engine/earnings.py",
    "engine/forward_review.py",
    "engine/fundamentals.py",
    "engine/intraday.py",
    "engine/lib/__init__.py",
    "engine/lib/data_quality.py",
    "engine/lib/db.py",
    "engine/lib/driver.sh",
    "engine/lib/log.py",
    "engine/lib/leverage.py",
    "engine/lib/provenance.py",
    "engine/lib/resources.py",
    "engine/lib/settings.py",
    "engine/lib/snapshots.py",
    "engine/lib/util.py",
    "engine/market_date.py",
    "engine/p15_evaluation.py",
    "engine/p15_event_sources.py",
    "engine/queue_runner.py",
    "engine/run_daily.sh",
    "engine/screen.py",
    "engine/signals.py",
    "engine/sync.py",
    "engine/tradingview_history_archive.py",
    "engine/universe.py",
    "engine/verify_prices.py",
    "engine/xs_forward_review.py",
    "farm/__init__.py",
    "farm/agent_evaluation_analysis.py",
    "farm/backtest/__init__.py",
    "farm/backtest/hist_screen.py",
    "farm/backtest/replay.py",
    "farm/backtest/report.py",
    "farm/backtest/stats.py",
    "farm/capital_sensitivity.py",
    "farm/experiment.py",
    "farm/experiment_runner.py",
    "farm/p15_event_runner.py",
    "farm/stats/__init__.py",
    "farm/stats/equity.py",
    "farm/stats/inference.py",
    "farm/sweep/__init__.py",
    "farm/sweep/sweep.py",
    "farm/walkforward/__init__.py",
    "farm/walkforward/controls.py",
    "farm/walkforward/monthly.py",
    "farm/walkforward/protocol.py",
    "farm/walkforward/report.py",
    "farm/walkforward/runner.py",
    "server/__init__.py",
    "server/agent-cadence-registration.json",
    "server/agent_evaluation.py",
    "server/agent_evaluation_reporting.py",
    "server/agent_model_client.py",
    "server/daily_opportunity_news.py",
    "server/daily_opportunity_execution.py",
    "server/daily_opportunity_runner.py",
    "server/daily_opportunity_store.py",
    "server/daily_opportunity_tools.py",
    "server/driver_log.py",
    "server/driver_monitor.py",
    "server/file_utils.py",
    "server/hourly_opportunity_observer.py",
    "server/intraday_source.py",
    "server/json_utils.py",
    "server/market_data_sources.py",
    "server/nightly_monitor.py",
    "server/nightly_reports.py",
    "server/official_quote_source.py",
    "server/run_p15_scoring.sh",
    "server/p15_incremental_collect.py",
    "server/p15_preopen.py",
    "server/p15_price_fetch_attempts.py",
    "server/p15_scoring_runner.py",
    "server/p15_scoring_store.py",
    "server/status_validation.py",
    "server/trading-engine-p15-events.service",
    "server/trading-engine-p15-events.timer",
    "server/trading-engine-p15-preopen.service",
    "server/trading-engine-p15-preopen.timer",
    "server/trading-engine-p15-scoring.service",
    "server/trading-engine-p15-scoring.timer",
    "server/tradingview_source.py",
    "sim/__init__.py",
    "sim/calendar.py",
    "sim/execution.py",
    "sim/fills.py",
    "sim/league.py",
    "sim/nyse.py",
    "sim/p15_books.py",
    "sim/p15_fills.py",
    "sim/portfolio.py",
    "sim/schema.py",
    "sim/settle.py",
    "sim/strategies/__init__.py",
    "sim/strategies/agent_only_policy.py",
    "sim/strategies/base.py",
    "sim/strategies/configs.py",
    "sim/strategies/discretionary.py",
    "sim/strategies/dual_momentum.py",
    "sim/strategies/ew_benchmark.py",
    "sim/strategies/ew_dd_throttle.py",
    "sim/strategies/ew_gross_voltarget.py",
    "sim/strategies/ew_sector_capped.py",
    "sim/strategies/ew_static_exposure.py",
    "sim/strategies/ew_trend_gated.py",
    "sim/strategies/ew_voltarget.py",
    "sim/strategies/high_52wk.py",
    "sim/strategies/low_vol.py",
    "sim/strategies/macro_composite.py",
    "sim/strategies/momo_stopped.py",
    "sim/strategies/mr_overlay.py",
    "sim/strategies/multi_asset_trend.py",
    "sim/strategies/pead_ear.py",
    "sim/strategies/sector_momentum.py",
    "sim/strategies/sleeve_alloc.py",
    "sim/strategies/spy_benchmark.py",
    "sim/strategies/template_top10_banded.py",
    "sim/strategies/template_top5.py",
    "sim/strategies/turtle_breakout.py",
    "sim/strategies/xs_common.py",
    "sim/strategies/xs_momentum_12_1.py",
    "sim/strategies/xs_reversal_1m.py",
    "tools/__init__.py",
    "tools/agent_trial_register.py",
    "tools/backup_database.py",
    "tools/p15_evidence_validation.py",
    "tools/publish_snapshot.py",
    "tools/release_manifest.py",
    "tools/sec_edgar_capture.py",
}


def _registration() -> dict:
    return json.loads(REGISTRATION_PATH.read_text())


_RELATIVE_SOURCE = re.compile(
    r'^source "\$\(dirname "\$\{BASH_SOURCE\[0\]\}"\)/([^"\n]+)"$',
    re.MULTILINE,
)
_PYTHON_MODULE = re.compile(
    r"(?:^|\s)-m\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)",
    re.MULTILINE,
)


def _local_dependency_closure(paths: set[str]) -> set[str]:
    closure = set(paths)
    pending = list(closure)
    roots = {"engine", "farm", "server", "sim", "tools"}

    def include(target: Path) -> None:
        candidates = [target]
        candidates.extend(
            parent / "__init__.py"
            for parent in target.parents
            if parent != ROOT and ROOT in parent.parents
        )
        for candidate in candidates:
            if not candidate.is_file():
                continue
            found = candidate.relative_to(ROOT).as_posix()
            if found not in closure:
                closure.add(found)
                pending.append(found)

    def include_module(module: str) -> None:
        parts = module.split(".")
        if not parts or parts[0] not in roots:
            return
        options = [ROOT.joinpath(*parts).with_suffix(".py"), ROOT.joinpath(*parts, "__init__.py")]
        target = next((item for item in options if item.is_file()), None)
        if target is not None:
            include(target)

    while pending:
        relative = pending.pop()
        if relative.endswith((".sh", ".service")):
            script = ROOT / relative
            content = script.read_text()
            if relative.endswith(".sh"):
                for sourced in _RELATIVE_SOURCE.findall(content):
                    include(script.parent / sourced)
            for module in _PYTHON_MODULE.findall(content):
                include_module(module)
            continue
        if not relative.endswith(".py"):
            continue
        module_parts = list(Path(relative).with_suffix("").parts)
        package = module_parts[:-1]
        tree = ast.parse((ROOT / relative).read_text())
        candidates = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                candidates.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    prefix = package[:len(package) - node.level + 1]
                    base = [*prefix, *([] if node.module is None else node.module.split("."))]
                else:
                    base = [] if node.module is None else node.module.split(".")
                if base:
                    candidates.add(".".join(base))
                candidates.update(
                    ".".join([*base, alias.name]) for alias in node.names
                    if alias.name != "*"
                )
        for module in candidates:
            include_module(module)
    return closure


def test_p15_registration_revision_and_self_hash():
    registration = _registration()
    recorded = registration.pop("registration_sha256")

    assert registration["schema_version"] == 1
    assert registration["registration_revision"] == 9
    assert registration["revision_reason"] == (
        "infrastructure only: per-stage timing; nightly sync autostash and single rebase retry; "
        "read-only snapshots with throttled publication and lock-only API fallback; fail-soft "
        "evidence reporting after league rendering; cached evaluation and readiness projections; "
        "single-connection observers; concurrent verify/farm; intraday unchanged-payload dedupe "
        "with batch writes; rolling queue pool and walk-forward scratch hygiene; paced parallel "
        "price verification, bounded nightly earnings and multi-session TradingView requests. No "
        "scoring, book, gate, label or written-row semantics change."
    )
    assert registration["status"] == "registered_inactive"
    assert registration["activated_at"] == p15_evaluation.ACTIVATED_AT.isoformat()
    assert recorded == canonical_sha256(registration)


def test_p15_registered_constants_match_runtime():
    registration = _registration()
    assert registration["authority"] == {
        "asset_side": "long_only", "broker_access": False,
        "event_execution": False, "leverage": False, "real_capital": False,
        "scope": "local_simulator_only",
    }
    assert registration["universe"] == {
        "version": "p15-universe-v1",
        "minimum_close": daily_opportunities.MIN_CLOSE,
        "minimum_history_sessions": daily_opportunities.MIN_HISTORY,
        "maximum_absolute_daily_return": daily_opportunities.MAX_ABS_DAILY_RETURN,
        "minimum_median_dollar_volume_20d": (
            daily_opportunities.P15_MIN_MEDIAN_DOLLAR_VOLUME
        ),
        "mover_limit": daily_opportunities.P15_MOVER_LIMIT,
        "trend_limit": daily_opportunities.P15_TREND_LIMIT,
        "held_names_included": True,
        "held_names_excluded_from_primary_ic": True,
    }
    scoring_identity = agent_model_client.identity(role="p15_scoring")
    assert registration["scoring"] == {
        "policy_id": p15_scoring_runner.POLICY_ID,
        "chunk_size": p15_scoring_runner.CHUNK_SIZE,
        "samples_per_chunk": p15_scoring_runner.SAMPLE_COUNT,
        "aggregation": p15_scoring_runner.AGGREGATION_RULE,
        "deadline_utc": "12:00:00",
        "actions": ["ignore", "watch", "buy_candidate", "exit"],
        "exit_requires_held": True,
        "ai_entry_minimum_probability": 0.55,
        "ai_entry_minimum_expected_excess_bp_5": 50.0,
        "hybrid_veto_below_expected_excess_bp_5": 0.0,
        "model": scoring_identity["model"],
        "model_version": scoring_identity["model_version"],
        "provider_revision_available": scoring_identity["provider_model_revision_available"],
        "model_identity_sha256": canonical_sha256(scoring_identity),
        "instructions_sha256": scoring_identity["instructions_sha256"],
        "toolset_sha256": scoring_identity["toolset_sha256"],
        "database_wait_seconds": p15_scoring_runner.DB_WAIT_S,
        "maximum_event_facts": p15_event_sources.MAX_SCORING_EVENT_FACTS,
        "admissible_window": "after_market_close_before_next_session_open",
        "deadline_start_refusal": "persist_failed_run_without_external_calls",
    }
    assert registration["baseline"] == {
        "version": "p15-baseline-v1",
        "ranking": ["rs_rank_desc", "standout_score_desc", "ticker_asc"],
        "missing_rs_rank": "last",
    }
    assert registration["labels"] == {
        "schema_version": agent_evaluation.LABEL_V2_SCHEMA_VERSION,
        "round_trip_cost_bps": agent_evaluation.ROUND_TRIP_COST_BPS,
        "horizons_sessions": list(agent_evaluation.HORIZONS),
        "primary_horizon_sessions": 5,
        "nightly_basis": agent_evaluation.NEXT_SESSION_OPEN_BASIS,
        "event_bases": ["next_bar", "next_session_open"],
        "missing_bars": "last_available_close_after_confirmation",
        "missing_bar_grace_sessions": agent_evaluation.MISSING_BAR_GRACE_SESSIONS,
        "missing_bar_confirmation": "later_ticker_bar_or_completed_exact_date_fetch",
        "fetch_attempt_evidence": (
            "batch_bound_liquid_and_exact_open_label_missing_receipts"
        ),
        "spy_net_return_stored": True,
    }
    books = registration["books"]
    assert books["mechanics_version"] == p15_books.MECHANICS_VERSION
    assert books["portfolio_ids"] == list(p15_books.BOOK_IDS)
    assert books["initial_cash_usd_each"] == p15_books.INITIAL_CASH
    assert books["risk_fraction"] == p15_books.COMMON_CONFIG["risk_fraction"]
    assert books["atr_period"] == p15_books.COMMON_CONFIG["atr_period"]
    assert books["atr_stop_multiple"] == p15_books.COMMON_CONFIG["atr_multiple"]
    assert books["maximum_name_fraction"] == p15_books.COMMON_CONFIG["max_name_fraction"]
    assert books["maximum_new_entries_per_session"] == p15_books.COMMON_CONFIG["max_new_entries"]
    assert books["maximum_positions"] == p15_books.COMMON_CONFIG["max_positions"]
    assert books["drawdown_halt"] == p15_books.COMMON_CONFIG["drawdown_halt"]
    assert books["time_exit_sessions"] == p15_books.COMMON_CONFIG["time_exit_sessions"]
    assert books["stale_entry_sessions"] == 1
    assert set(books) == {
        "mechanics_version", "portfolio_ids", "initial_cash_usd_each",
        "execution_profile", "risk_fraction", "atr_period", "atr_stop_multiple",
        "maximum_name_fraction", "maximum_new_entries_per_session", "maximum_positions",
        "maximum_gross_exposure", "drawdown_halt", "time_exit_sessions", "spy_sleeve",
        "entry_order", "entry_limit", "hybrid_vetoed_slot_replacement",
        "stale_entry_sessions", "config_sha256",
    }
    preopen_identity = agent_model_client.identity(role="p15_preopen")
    assert registration["preopen"] == {
        "policy_id": p15_preopen.POLICY_ID,
        "schedule": "09:05 America/New_York weekdays",
        "deadline": "09:25:00 America/New_York", "authority": "cancel_only",
        "model_identity_sha256": canonical_sha256(preopen_identity),
        "instructions_sha256": preopen_identity["instructions_sha256"],
        "session_only": True,
    }
    event_identity = agent_model_client.identity(role="p15_event")
    assert registration["events"] == {
        "policy_id": p15_event_runner.POLICY_ID,
        "schedule": "09:35,09:50,10:05-15:50 at :05/:20/:35/:50 America/New_York",
        "sources": ["local_rss", "sec_edgar_8k", "intraday_mover"],
        "maximum_universe": p15_event_sources.MAX_TRIGGER_UNIVERSE,
        "maximum_workers": p15_event_sources.MAX_INTRADAY_WORKERS,
        "maximum_decisions_per_session": p15_event_runner.MAX_DECISIONS_PER_SESSION,
        "chunk_size": p15_event_runner.CHUNK_SIZE,
        "mover_minimum_absolute_return": 0.04,
        "mover_atr_threshold_multiple": 2.0,
        "mover_minimum_relative_volume": 2.0,
        "execution_authority": "none", "latency_target_p95_ms": 600000,
        "model_identity_sha256": canonical_sha256(event_identity),
        "instructions_sha256": event_identity["instructions_sha256"],
        "database_released_during_model_calls": True,
        "first_availability_only": True,
        "sec_acceptance_after_previous_cik_scan": True,
    }
    assert registration["evaluation"] == {
        "primary_statistic": "paired_daily_spearman_champion_minus_rule",
        "minimum_pairs_per_session": 20,
        "score_and_label_basis": {
            "champion_score": (
                "registered champion score on the common P15-eligible candidate set"
            ),
            "rule_score": "-agent_evaluation_decisions.decision_payload.baseline_rank",
            "label": (
                "registered h5 net excess with the same next-open/fifth-close and cost "
                "version for both scores"
            ),
            "mean_champion_ic": (
                "arithmetic mean of raw Spearman(champion_score,label) on exactly the "
                "retained origins used by the look"
            ),
        },
        "primary_sampling": {
            "calendar": "NYSE_exchange_sessions",
            "origin_epoch_rule": (
                "first NYSE signal session whose registered scoring cutoff is strictly after "
                "activated_at; persist its literal session as index 0 even if predictably skipped"
            ),
            "origin_epoch": p15_evaluation.ORIGIN_EPOCH.isoformat(),
            "stride": p15_evaluation.PRIMARY_STRIDE,
            "offset": p15_evaluation.PRIMARY_OFFSET,
            "nominal_look_labels": list(p15_evaluation.LOOKS),
            "retained_observations_at_looks": [12, 18, 24],
            "skip_decided_before_forward_outcome": [
                "fewer_than_20_candidates", "constant_scores"
            ],
            "constant_scores_definition": (
                "either champion score or rule score is constant on the common eligible "
                "candidate set"
            ),
            "skip_effect": (
                "stay_on_original_offset0_grid_and_delay_until_target_retained_count"
            ),
            "unresolved_or_outcome_dependent_missing": "block_prefix_no_replacement",
            "other_offsets": "diagnostic_only",
        },
        "primary_interval": {
            "standard_error": "sample_sd_ddof1_divided_by_sqrt_retained_n",
            "one_sided_alpha_per_look": p15_evaluation.ALPHA,
            "degrees_of_freedom": [11, 17, 23],
            "critical_values": [
                p15_evaluation.PRIMARY_T_CRITICAL[look] for look in p15_evaluation.LOOKS
            ],
            "zero_variance": "no_interval_no_pass_and_kill_at_completed_final_look",
        },
        "primary_pass": (
            "lower_bound_gt_0_and_mean_champion_IC_on_same_retained_origins_gt_0"
        ),
        "primary_kill": (
            "upper_bound_lt_0_at_any_look_or_no_pass_at_final_24_observation_look"
        ),
        "look_persistence": (
            "immutable_first_evaluation_of_registered_retained_origin_prefix"
        ),
        "lag4_hansen_hodrick": (
            "diagnostic_only_with_nonpositive_Bartlett_lag8_fallback"
        ),
        "retained_lag1_autocorrelation": {
            "formula": "sum((d[1:]-mean_d)*(d[:-1]-mean_d))/sum((d-mean_d)^2)",
            "zero_denominator": "unavailable",
            "role": "diagnostic_only_never_changes_pass_or_kill",
            "ar1_rho_0_5_seeded_any_crossing": 0.06253,
        },
        "null_contract": (
            "retained_offset0_d_are_iid_Gaussian_with_nonpositive_mean; eligibility_is_"
            "decided_before_and_independent_of_forward_return_innovations"
        ),
        "family_error_argument": (
            "three_fixed_sample_count_looks_each_at_0.05/3; Bonferroni_at_most_0.05"
        ),
        "outside_guarantee": (
            "persistent_AR_dependence_heterogeneous_selected_distributions_or_"
            "outcome_dependent_skips"
        ),
        "primary_simulation_validation": {
            "bit_generator": "PCG64", "draws": 10000, "iid_null_seed": 20260927,
            "iid_null_pass_count": 353, "maximum_iid_null_false_pass_rate": 0.05,
        },
        "missing_label_grace_sessions": p15_evaluation.MISSING_LABEL_GRACE_SESSIONS,
        "book_newey_west_lag": p15_evaluation.NW_LAG,
        "book_minimum_calendar_days": 90, "book_minimum_closed_trades_each": 30,
        "book_promotion": (
            "primary_pass_and_challenger_lower_bound_gt_0_and_all_drawdowns_gte_minus_0.20"
        ),
        "p8_review": (
            "90_calendar_days_and_60_completed_sessions; expectancy_after_20_round_trips; "
            "confidence_bound_not_a_gate"
        ),
    }
    assert registration["delivery"] == {
        "scoring_timer_persistent": True, "preopen_timer_persistent": False,
        "events_timer_persistent": False,
        "report_json": "data/reports/agent-evaluation.json",
        "report_markdown": "data/reports/agent-eval/p15.md",
        "scoring_service_restart": "on-failure_after_5min_burst_3_per_30min",
        "model_call_count": "attempted_calls_including_connector_failures",
        "dry_run_lock_scope": "production_lock_only_during_source_snapshot",
        "price_fetch_attempts": (
            "zero_failed_liquid_batch_plus_exact_open_label_receipts"
        ),
        "maximum_open_label_fetches_per_run": (
            p15_incremental_collect.MAX_OPEN_LABEL_FETCHES
        ),
        "price_fetch_availability": "after_collection_completion",
    }


def test_p15_registered_derived_identities_match_code():
    registration = _registration()
    for section, role in (
        ("scoring", "p15_scoring"),
        ("preopen", "p15_preopen"),
        ("events", "p15_event"),
    ):
        identity = agent_model_client.identity(role=role)
        assert registration[section]["model_identity_sha256"] == canonical_sha256(identity)
        assert registration[section]["instructions_sha256"] == identity["instructions_sha256"]
    assert registration["scoring"]["toolset_sha256"] == (
        agent_model_client.identity(role="p15_scoring")["toolset_sha256"]
    )
    assert registration["books"]["config_sha256"] == {
        book: canonical_sha256(p15_books._config(book)) for book in sorted(p15_books.BOOK_IDS)
    }


def test_p15_registered_file_hashes_match_checkout():
    registration = _registration()
    files = registration["code_identity"]["files"]
    assert set(files) == REGISTERED_PATHS
    assert _local_dependency_closure(REGISTERED_PATHS) <= REGISTERED_PATHS
    drift = {}
    for relative, recorded in files.items():
        path = ROOT / relative
        assert not Path(relative).is_absolute() and ".." not in Path(relative).parts
        assert path.is_file() and not path.is_symlink()
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if recorded != actual:
            drift[relative] = {"registered": recorded, "actual": actual}
    assert drift == {}
    latest_registered_change = subprocess.run(
        ["git", "rev-list", "-1", "HEAD", "--", *sorted(files)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert registration["code_identity"]["source_commit"] == latest_registered_change


def test_p15_entrypoints_are_discovered_without_manual_seeds():
    discoverable = {
        "engine/universe.py",
        "server/p15_incremental_collect.py",
        "server/p15_scoring_runner.py",
        "server/agent_evaluation_reporting.py",
        "farm/p15_event_runner.py",
    }
    for relative in discoverable:
        assert relative in _local_dependency_closure(REGISTERED_PATHS - {relative})
