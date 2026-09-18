"""Tests for the honest agent-visible daily-price fact contract."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import agent_data_contract

OBSERVATION_DATE = date(2026, 9, 11)
FETCHED_AT = datetime(2026, 9, 12, tzinfo=timezone.utc)


def _fact(**overrides):
    values = {
        "ticker": "SPY",
        "market_date": OBSERVATION_DATE,
        "open_price": 99.0,
        "high": 101.0,
        "low": 98.0,
        "close": 100.0,
        "volume": 1_000_000,
        "source": "yfinance",
        "fetched_at": FETCHED_AT,
    }
    values.update(overrides)
    return agent_data_contract.daily_price_fact(**values)


def test_daily_price_fact_is_deterministic_and_explicit_about_missing_provenance():
    first = _fact()
    second = _fact()

    assert first == second
    assert first["observation"] == {
        "market_date": "2026-09-11",
        "event_time": None,
        "event_time_status": "daily_session_date_only",
    }
    assert first["availability"]["source_published_at"] is None
    assert first["availability"]["usable_at"] == "2026-09-12T00:00:00Z"
    assert first["source"]["name"] == "yfinance"
    assert first["source"]["provider_version"] is None
    assert first["source"]["adapter"] == "yfinance.download"
    assert first["source"]["adapter_version"] == "auto_adjust_false_v1"
    assert first["source"]["library_version"]
    assert first["schema_version"] == 4
    assert first["provider_evidence"] is None
    assert first["revision"] == {
        "policy": "mutable_latest_value_upsert",
        "revision_id": None,
        "observation_schema_version": None,
        "observation_sequence": None,
        "value_revision": None,
        "classification": "legacy_unobserved",
        "value_sha256": None,
        "previous_revision_id": None,
        "observed_at": None,
        "history_retained": False,
        "point_in_time_replayable": False,
    }
    assert first["record"]["raw_sha256"] is None
    assert first["record"]["raw_retained"] is False
    assert first["ingestion"]["immutable_observed_at"] is None
    assert first["record"]["normalized"] == {
        "ticker": "SPY",
        "market_date": "2026-09-11",
        "open": 99.0,
        "high": 101.0,
        "low": 98.0,
        "close": 100.0,
        "volume": 1_000_000,
        "source": "yfinance",
        "latest_ingested_at": "2026-09-12T00:00:00Z",
    }
    assert len(first["record"]["normalized_sha256"]) == 64
    assert first["adjustment"] == {
        "request_auto_adjust": False,
        "storage_policy": "provider_current_history",
        "point_in_time_revision_safe": False,
    }


def test_normalized_record_identity_changes_with_selected_value():
    first = _fact()
    second = _fact(close=100.5)

    assert first["record"]["normalized_sha256"] != second["record"]["normalized_sha256"]


def test_daily_price_fact_binds_and_validates_immutable_observation():
    legacy = _fact()
    normalized = legacy["record"]["normalized"]
    value = {
        key: normalized[key]
        for key in (
            "ticker",
            "market_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
        )
    }
    observation = {
        "schema_version": 1,
        "ticker": "SPY",
        "market_date": "2026-09-11",
        "normalized_sha256": canonical_sha256(normalized),
        "value_sha256": canonical_sha256(value),
        "source_fetched_at": "2026-09-12T00:00:00Z",
        "observed_at": "2026-09-13T12:00:00Z",
        "source_adapter": "yfinance.download",
        "source_adapter_version": "auto_adjust_false_v1",
        "source_library_version": legacy["source"]["library_version"],
        "observation_sequence": 1,
        "value_revision": 1,
        "classification": "baseline_snapshot",
        "previous_observation_sha256": None,
    }
    observation["observation_sha256"] = canonical_sha256(observation)

    fact = _fact(immutable_observation={**observation, "normalized": normalized})

    assert fact["revision"]["revision_id"] == observation["observation_sha256"]
    assert fact["revision"]["history_retained"] is True
    assert fact["revision"]["point_in_time_replayable"] is True
    assert fact["ingestion"]["immutable_observed_at"] == "2026-09-13T12:00:00Z"
    assert fact["availability"] == {
        "source_published_at": None,
        "usable_at": "2026-09-13T12:00:00Z",
        "policy": "usable_no_earlier_than_immutable_observation",
    }
    assert fact["record"]["raw_retained"] is False
    agent_data_contract.validate_daily_price_fact(fact)


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"source": "other"}, "not admitted"),
        ({"fetched_at": None}, "ingestion timestamp"),
        (
            {"fetched_at": datetime(2026, 9, 10, tzinfo=timezone.utc)},
            "precedes",
        ),
        ({"volume": 0}, "volume"),
        ({"open_price": float("nan")}, "open"),
        ({"high": 97.0}, "OHLC"),
    ],
)
def test_daily_price_fact_rejects_unsupported_or_inconsistent_input(overrides, detail):
    with pytest.raises(agent_data_contract.DataContractError, match=detail):
        _fact(**overrides)


def test_validator_rejects_contract_claiming_unretained_raw_data():
    fact = _fact()
    fact["record"]["raw_retained"] = True

    with pytest.raises(agent_data_contract.DataContractError, match="contract is invalid"):
        agent_data_contract.validate_daily_price_fact(fact)


def test_validator_rejects_normalized_record_hash_mismatch():
    fact = _fact()
    fact["record"]["normalized"]["close"] = 90.0

    with pytest.raises(agent_data_contract.DataContractError, match="contract is invalid"):
        agent_data_contract.validate_daily_price_fact(fact)


def test_dividend_fact_retains_recomputable_normalized_identity():
    fact = agent_data_contract.dividend_fact(
        ticker="BIL",
        ex_date=date(2026, 9, 1),
        value=0.28,
        source="yfinance",
        fetched_at=FETCHED_AT,
    )

    assert fact["dataset"] == "cash_dividend"
    assert fact["schema_version"] == 4
    assert fact["provider_evidence"] is None
    assert fact["quality_status"] == "limited"
    assert fact["usage_authority"] == "shadow_context_only"
    assert fact["revision"]["point_in_time_replayable"] is False
    assert fact["revision"]["classification"] == "legacy_unobserved"
    assert fact["ingestion"] == {
        "latest_ingested_at": "2026-09-12T00:00:00Z",
        "immutable_observed_at": None,
    }
    assert fact["record"]["normalized"] == {
        "ticker": "BIL",
        "ex_date": "2026-09-01",
        "cash_per_share": 0.28,
        "source": "yfinance",
        "latest_ingested_at": "2026-09-12T00:00:00Z",
    }
    assert len(fact["record"]["normalized_sha256"]) == 64


def test_dividend_fact_binds_and_validates_immutable_observation():
    legacy = agent_data_contract.dividend_fact(
        ticker="BIL",
        ex_date=date(2026, 9, 1),
        value=0.28,
        source="yfinance",
        fetched_at=FETCHED_AT,
    )
    observation_normalized = {
        "ticker": "BIL",
        "ex_date": "2026-09-01",
        "kind": "dividend",
        "value": 0.28,
        "source": "yfinance",
        "latest_ingested_at": "2026-09-12T00:00:00Z",
    }
    observation_value = {
        key: observation_normalized[key]
        for key in ("ticker", "ex_date", "kind", "value", "source")
    }
    observation = {
        "schema_version": 1,
        "ticker": "BIL",
        "ex_date": "2026-09-01",
        "kind": "dividend",
        "normalized_sha256": canonical_sha256(observation_normalized),
        "value_sha256": canonical_sha256(observation_value),
        "source_fetched_at": "2026-09-12T00:00:00Z",
        "observed_at": "2026-09-13T12:00:00Z",
        "source_adapter": "yfinance.actions",
        "source_adapter_version": "corporate_actions_v1",
        "source_library_version": legacy["source"]["library_version"],
        "observation_sequence": 1,
        "value_revision": 1,
        "classification": "baseline_snapshot",
        "previous_observation_sha256": None,
    }
    observation["observation_sha256"] = canonical_sha256(observation)

    fact = agent_data_contract.dividend_fact(
        ticker="BIL",
        ex_date=date(2026, 9, 1),
        value=0.28,
        source="yfinance",
        fetched_at=FETCHED_AT,
        immutable_observation={
            **observation,
            "normalized": observation_normalized,
        },
    )

    assert fact["revision"]["revision_id"] == observation["observation_sha256"]
    assert fact["revision"]["history_retained"] is True
    assert fact["revision"]["point_in_time_replayable"] is True
    assert fact["availability"] == {
        "source_published_at": None,
        "usable_at": "2026-09-13T12:00:00Z",
        "policy": "usable_no_earlier_than_immutable_observation",
    }
    assert fact["ingestion"]["immutable_observed_at"] == "2026-09-13T12:00:00Z"
    assert fact["record"]["raw_retained"] is False
    agent_data_contract.validate_dividend_fact(fact)


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"source": "other"}, "not admitted"),
        ({"fetched_at": None}, "ingestion timestamp"),
        ({"value": -0.01}, "nonnegative"),
    ],
)
def test_dividend_fact_rejects_invalid_source_time_or_value(overrides, detail):
    values = {
        "ticker": "BIL",
        "ex_date": date(2026, 9, 1),
        "value": 0.28,
        "source": "yfinance",
        "fetched_at": FETCHED_AT,
    }
    values.update(overrides)

    with pytest.raises(agent_data_contract.DataContractError, match=detail):
        agent_data_contract.dividend_fact(**values)
