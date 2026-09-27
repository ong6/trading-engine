"""Frozen W4 implementation-gate values; no producer authority lives here."""

SPLIT_KNOWLEDGE_PRIMARY = "registered_ex_date_open_v1"
SPLIT_KNOWLEDGE_SENSITIVITY = "registered_one_session_after_ex_date_v1"
INDEPENDENT_UNADJUSTED_PRICE_SOURCE = "alpha_vantage_time_series_daily_raw_v1"
PROBE_CATEGORIES = ("earnings_outcome", "headline")
PROBE_MONTH_MINIMUM = 300
PROBE_BASELINE_MINIMUM = 350
PROBE_EQUIVALENCE_DELTA = 0.08

TRUSTED_SPLIT_OUTCOMES = frozenset({"applied", "noop_restated"})
TRUSTED_NOOP_SPLIT_OUTCOMES = frozenset({"noop_pre_history"})

PRICE_SERIES_BY_CONSUMER = {
    "archive_validation": "reconstructed_unadjusted_v1",
    "atr14": "asof_split_adjusted_v1",
    "daily_return": "asof_split_adjusted_v1",
    "relative_strength": "asof_split_adjusted_v1",
    "screen_253": "asof_split_adjusted_v1",
    "absolute_return_guard": "asof_split_adjusted_v1",
    "median_dollar_volume": "asof_split_adjusted_v1",
    "p15_universe": "asof_split_adjusted_v1",
    "position_sizing": "asof_split_adjusted_v1",
    "open_execution": "asof_split_adjusted_v1",
    "close_stops_and_marks": "asof_split_adjusted_v1",
    "asset_label": "label_split_normalized_v1",
    "spy_label": "label_split_normalized_v1",
    "source_provenance": "source_back_adjusted_v1",
}


def mandatory_acceptance_contract() -> dict:
    return {
        "schema_version": 1,
        "status": "implementation_inert",
        "split_knowledge": {
            "primary": SPLIT_KNOWLEDGE_PRIMARY,
            "sensitivity": SPLIT_KNOWLEDGE_SENSITIVITY,
            "primary_is_measured_history": False,
            "sensitivity_lag_sessions": 1,
        },
        "split_outcomes": {
            "trusted": sorted(TRUSTED_SPLIT_OUTCOMES),
            "trusted_noop": sorted(TRUSTED_NOOP_SPLIT_OUTCOMES),
            "all_other_or_missing": "quarantine",
        },
        "held_split_quarantine_estimate": {
            "unit": "held_or_pending_action_exposures_per_registered_window",
            "method": "potential_exposure_intersection_then_actual_replay_counts_v1",
            "zero_count_windows_required": True,
            "status": "blocked_until_frozen_archive_preflight",
        },
        "price_series_by_consumer": dict(PRICE_SERIES_BY_CONSUMER),
        "independent_unadjusted_price_validation": {
            "source": INDEPENDENT_UNADJUSTED_PRICE_SOURCE,
            "status": "required_before_archive_admission",
        },
        "contamination_probe": {
            "categories": list(PROBE_CATEGORIES),
            "historical_month_minimum": PROBE_MONTH_MINIMUM,
            "unseen_baseline_minimum": PROBE_BASELINE_MINIMUM,
            "equivalence_delta": PROBE_EQUIVALENCE_DELTA,
            "category_minimum": 0,
            "seed": 1604,
        },
        "authority": "historical_research_only",
    }
