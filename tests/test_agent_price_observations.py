"""Immutable normalized price observations preserve agent input history."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import agent_context, agent_price_observations
from tests.agent_test_helpers import complete_dual_momentum_history, fixed_etf_market

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def _latest(con, ticker="SPY"):
    return con.execute(
        "SELECT ticker, date, open, high, low, close, volume, source, fetched_at "
        "FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()


def test_capture_is_idempotent_and_records_a_baseline_without_changing_prices(con):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    prices_before = con.execute(
        "SELECT ticker, date, open, high, low, close, volume, source, fetched_at "
        "FROM prices ORDER BY ticker, date"
    ).fetchall()

    first = agent_price_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )
    second = agent_price_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )

    assert first["selected_rows"] == 759
    assert first["inserted_observations"] == 759
    assert first["baseline_snapshots"] == 759
    assert first["unchanged_observations"] == 0
    assert first["value_revisions"] == 0
    assert second["inserted_observations"] == 0
    assert con.execute(
        "SELECT COUNT(*) FROM agent_daily_price_observations"
    ).fetchone() == (759,)
    assert con.execute(
        "SELECT ticker, date, open, high, low, close, volume, source, fetched_at "
        "FROM prices ORDER BY ticker, date"
    ).fetchall() == prices_before


def test_capture_distinguishes_reobservation_from_value_revision(con):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    agent_price_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )

    later_fetch = NOW + timedelta(days=1)
    con.execute(
        "UPDATE prices SET fetched_at = ? WHERE ticker = 'SPY' AND date = ?",
        [later_fetch, market_date],
    )
    unchanged = agent_price_observations.capture_strategy_scope(
        con,
        "dual_momentum",
        market_date,
        observed_at=later_fetch + timedelta(hours=1),
    )

    con.execute(
        "UPDATE prices SET close = close + 1, high = high + 1, fetched_at = ? "
        "WHERE ticker = 'SPY' AND date = ?",
        [later_fetch + timedelta(days=1), market_date],
    )
    changed = agent_price_observations.capture_strategy_scope(
        con,
        "dual_momentum",
        market_date,
        observed_at=later_fetch + timedelta(days=1, hours=1),
    )

    assert unchanged["unchanged_observations"] == 1
    assert unchanged["value_revisions"] == 0
    assert changed["unchanged_observations"] == 0
    assert changed["value_revisions"] == 1
    rows = con.execute(
        "SELECT observation_sequence, value_revision, classification, "
        "previous_observation_sha256, observation_sha256 "
        "FROM agent_daily_price_observations "
        "WHERE ticker = 'SPY' AND market_date = ? ORDER BY observation_sequence",
        [market_date],
    ).fetchall()
    assert [row[:3] for row in rows] == [
        (1, 1, "baseline_snapshot"),
        (2, 1, "unchanged_observation"),
        (3, 2, "value_revision"),
    ]
    assert rows[0][3] is None
    assert rows[1][3] == rows[0][4]
    assert rows[2][3] == rows[1][4]


def test_invalid_batch_is_rejected_before_any_observation_is_inserted(con):
    fixed_etf_market(con)
    agent_price_observations.init_schema(con)
    valid = _latest(con)
    invalid = (*valid[:6], -1, *valid[7:])

    with pytest.raises(agent_price_observations.ObservationError, match="volume"):
        agent_price_observations._capture_rows(
            con, [valid, invalid], observed_at=NOW
        )

    assert con.execute(
        "SELECT COUNT(*) FROM agent_daily_price_observations"
    ).fetchone() == (0,)


def test_capture_rejects_observation_before_source_ingestion(con):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)

    with pytest.raises(
        agent_price_observations.ObservationError,
        match="observation precedes source ingestion",
    ):
        agent_price_observations.capture_strategy_scope(
            con,
            "dual_momentum",
            market_date,
            observed_at=datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc),
        )

    assert con.execute(
        "SELECT COUNT(*) FROM agent_daily_price_observations"
    ).fetchone() == (0,)


def test_context_binds_exact_observation_and_detects_ledger_tampering(con):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    agent_price_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )

    context = agent_context.build(con, "dual_momentum", "SPY")
    fact = context["instrument"]["data_contract"]

    assert fact["schema_version"] == 4
    assert fact["revision"]["policy"] == "append_only_normalized_observation"
    assert fact["revision"]["classification"] == "baseline_snapshot"
    assert fact["revision"]["history_retained"] is True
    assert fact["revision"]["point_in_time_replayable"] is True
    assert fact["record"]["raw_retained"] is False
    assert fact["availability"]["source_published_at"] is None
    assert fact["source"]["provider_version"] is None
    assert fact["revision"]["revision_id"] in {
        row[0]
        for row in con.execute(
            "SELECT observation_sha256 FROM agent_daily_price_observations"
        ).fetchall()
    }

    con.execute(
        "UPDATE agent_daily_price_observations SET observation_sha256 = ? "
        "WHERE ticker = 'SPY' AND market_date = ?",
        [canonical_sha256({"tampered": True}), market_date],
    )
    with pytest.raises(agent_context.ContextError, match="identity is invalid"):
        agent_context.build(con, "dual_momentum", "SPY")


def test_context_uses_legacy_contract_when_no_observation_exists(con):
    fixed_etf_market(con)

    fact = agent_context.build(con, "dual_momentum", "SPY")["instrument"][
        "data_contract"
    ]

    assert fact["schema_version"] == 4
    assert fact["revision"]["policy"] == "mutable_latest_value_upsert"
    assert fact["revision"]["classification"] == "legacy_unobserved"
    assert fact["revision"]["history_retained"] is False
    assert fact["revision"]["point_in_time_replayable"] is False


def test_status_is_bounded_for_missing_and_capturing_ledgers(con):
    fixed_etf_market(con)

    missing = agent_price_observations.status(con)

    assert missing["status"] == "not_initialized"
    assert missing["observation_count"] == 0
    assert missing["raw_retained"] is False
    assert missing["execution_authority"] == "none"

    market_date = complete_dual_momentum_history(con)
    agent_price_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )
    captured = agent_price_observations.status(con)

    assert captured == {
        "schema_version": 1,
        "status": "capturing",
        "observation_count": 759,
        "ticker_count": 3,
        "first_market_date": "2025-09-24",
        "last_market_date": "2026-09-11",
        "first_observed_at": "2026-09-13T12:00:00Z",
        "last_observed_at": "2026-09-13T12:00:00Z",
        "classification_counts": {
            "baseline_snapshot": 759,
            "unchanged_observation": 0,
            "value_revision": 0,
        },
        "raw_retained": False,
        "point_in_time_scope": "normalized_observations_after_capture_only",
        "execution_authority": "none",
    }


def test_status_fails_closed_on_broken_revision_chain(con):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    agent_price_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )
    con.execute(
        "UPDATE agent_daily_price_observations "
        "SET previous_observation_sha256 = ? "
        "WHERE ticker = 'SPY' AND market_date = ?",
        ["f" * 64, market_date],
    )

    with pytest.raises(
        agent_price_observations.ObservationError, match="ledger is invalid"
    ):
        agent_price_observations.status(con)
