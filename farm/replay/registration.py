"""Frozen W4 implementation-gate values; no producer authority lives here."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sim import nyse

SPLIT_KNOWLEDGE_PRIMARY = "registered_ex_date_open_v1"
SPLIT_KNOWLEDGE_SENSITIVITY = "registered_one_session_after_ex_date_v1"
INDEPENDENT_UNADJUSTED_PRICE_SOURCE = "alpha_vantage_time_series_daily_raw_v1"
PROBE_CATEGORIES = ("earnings_outcome", "headline")
PROBE_MONTH_MINIMUM = 300
PROBE_BASELINE_MINIMUM = 350
PROBE_EQUIVALENCE_DELTA = 0.08
MODEL_CUTOFFS = {
    "GPT-5.6-Sol": "2026-02-16",
    "GPT-6-Astra": "2026-04-30",
}
FUTURE_SPLIT_QUARANTINE = {
    "GPT-5.6-Sol": {
        "window_start": "2026-04-17",
        "quarantined_rows": 59,
        "excluded_securities": 57,
    },
    "GPT-6-Astra": {
        "window_start": "2026-06-29",
        "quarantined_rows": 20,
        "excluded_securities": 20,
    },
}
REPLAY_POLICY_IDS = (
    "replay-champion-sol-v1",
    "replay-notes-sol-v1",
    "replay-blind-sol-v1",
    "replay-model-astra-v1",
)
TEXTLAB_POLICY_ID = "text-chrono-reduced-ridge-v1"
REPLAY_REPORT_PATH = "data/reports/research/replay.md"
TEXTLAB_REPORT_PATH = "data/reports/research/textlab.md"

TRUSTED_SPLIT_OUTCOMES = frozenset({"applied", "noop_restated"})
TRUSTED_NOOP_SPLIT_OUTCOMES = frozenset({"noop_pre_history"})


def _cutoff_date(value: date | datetime | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_model_cutoff") from exc


def admitted_grid(
    cutoff: date | datetime | str | None, activation: datetime
) -> dict:
    """Build the complete C+60-to-activation NYSE grid and its fixed 2/3 split."""
    if not isinstance(activation, datetime) or activation.tzinfo is None:
        raise ValueError("invalid_activation_clock")
    cutoff_day = _cutoff_date(cutoff)
    if cutoff_day is None:
        return {
            "status": "unknown_cutoff",
            "cutoff": None,
            "activation": activation.astimezone(timezone.utc).isoformat(),
            "sessions": [],
            "development": [],
            "lockbox": [],
        }
    floor = cutoff_day + timedelta(days=60)
    cursor = floor
    sessions = []
    activation_utc = activation.astimezone(timezone.utc)
    while cursor <= activation_utc.date():
        decision_at = datetime.combine(cursor + timedelta(days=1), time(2), timezone.utc)
        if nyse.is_session(cursor) and decision_at < activation_utc:
            sessions.append(cursor.isoformat())
        cursor += timedelta(days=1)
    split = (2 * len(sessions)) // 3
    return {
        "status": "planned" if sessions else "empty_window",
        "cutoff": cutoff_day.isoformat(),
        "c_plus_60_floor": floor.isoformat(),
        "activation": activation_utc.isoformat(),
        "sessions": sessions,
        "development": sessions[:split],
        "lockbox": sessions[split:],
        "split_index": split,
        "first_lockbox_session": sessions[split] if split < len(sessions) else None,
    }

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


def w4_registration(
    code_sha256: dict[str, str],
    *,
    plan_sha256: str,
    notes_filter_spec_sha256: str,
    lesson_corpus_sha256: str,
    activation_at: datetime,
    price_archive_listing_date: str,
) -> dict:
    """Build the inert W4 registration body before any real-data producer run."""
    required = {"collectors", "probes", "replay", "textlab", "reports"}
    if set(code_sha256) != required or any(
        len(value) != 64 or any(char not in "0123456789abcdef" for char in value)
        for value in code_sha256.values()
    ):
        raise ValueError("w4_code_identity_incomplete")
    for value in (plan_sha256, notes_filter_spec_sha256, lesson_corpus_sha256):
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("w4_registration_digest_invalid")
    try:
        listing_date = date.fromisoformat(price_archive_listing_date).isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_price_archive_listing_date") from exc
    grids = {
        model: admitted_grid(cutoff, activation_at)
        for model, cutoff in MODEL_CUTOFFS.items()
    }
    body = {
        "schema_version": 1,
        "registration_id": "p16-w4-historical-labs-v1",
        "status": "registered_inactive",
        "replay_policies": list(REPLAY_POLICY_IDS),
        "textlab_policy": TEXTLAB_POLICY_ID,
        "mandatory_acceptance_contract": mandatory_acceptance_contract(),
        "notes": {
            "filter_spec_sha256": notes_filter_spec_sha256,
            "lesson_corpus_sha256": lesson_corpus_sha256,
            "maximum_lessons": 12,
            "prompt": "prompts/notes-v1.txt",
            "postmortem_schema": "schemas/postmortem-v1.json",
        },
        "plan_sha256": plan_sha256,
        # Ticker list capture date: names delisted earlier may be absent (survivorship).
        "price_archive_listing_date": listing_date,
        "model_cutoffs": dict(MODEL_CUTOFFS),
        "replay_grids": grids,
        "development_lockbox_split": "floor(2*T/3)_exchange_sessions_v1",
        "future_split_quarantine": {
            "security_key": "ticker_proxy_no_stable_security_table",
            "windows": FUTURE_SPLIT_QUARANTINE,
        },
        "primary_endpoint": {
            "id": "notes_minus_no_notes_factor_neutral_h5_ic",
            "alternative": "greater_than_zero",
            "bootstrap_block_sessions": 5,
            "bootstrap_resamples": 10_000,
            "seed": 1604,
        },
        "reports": [REPLAY_REPORT_PATH, TEXTLAB_REPORT_PATH],
        "edgar_without_contact": "unconfigured",
        "text_inference": "unconfigured_without_research_text_approval",
        "real_data_producer_allowed": False,
        "code_sha256": dict(sorted(code_sha256.items())),
        "authority": "historical_research_only",
    }
    from engine.lib.provenance import canonical_sha256

    return {**body, "registration_sha256": canonical_sha256(body)}
