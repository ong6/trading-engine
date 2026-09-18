"""Immutable normalized corporate actions preserve agent input history."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    agent_context,
    agent_corporate_action_observations,
)
from tests.agent_test_helpers import complete_dual_momentum_history, fixed_etf_market

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)


def test_capture_is_idempotent_and_does_not_change_corporate_actions(con):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    actions_before = con.execute(
        "SELECT ticker, ex_date, kind, value, source, fetched_at "
        "FROM corporate_actions ORDER BY ticker, ex_date, kind"
    ).fetchall()

    first = agent_corporate_action_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )
    second = agent_corporate_action_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )

    assert first["selected_rows"] == 1
    assert first["inserted_observations"] == 1
    assert first["baseline_snapshots"] == 1
    assert first["unchanged_observations"] == 0
    assert first["value_revisions"] == 0
    assert second["inserted_observations"] == 0
    assert con.execute(
        "SELECT COUNT(*) FROM agent_corporate_action_observations"
    ).fetchone() == (1,)
    assert con.execute(
        "SELECT ticker, ex_date, kind, value, source, fetched_at "
        "FROM corporate_actions ORDER BY ticker, ex_date, kind"
    ).fetchall() == actions_before


def test_capture_distinguishes_reobservation_from_value_revision(con):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    agent_corporate_action_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )

    later_fetch = NOW + timedelta(days=1)
    con.execute(
        "UPDATE corporate_actions SET fetched_at = ? "
        "WHERE ticker = 'BIL' AND ex_date = DATE '2026-06-01'",
        [later_fetch],
    )
    unchanged = agent_corporate_action_observations.capture_strategy_scope(
        con,
        "dual_momentum",
        market_date,
        observed_at=later_fetch + timedelta(hours=1),
    )

    con.execute(
        "UPDATE corporate_actions SET value = 4.1, fetched_at = ? "
        "WHERE ticker = 'BIL' AND ex_date = DATE '2026-06-01'",
        [later_fetch + timedelta(days=1)],
    )
    changed = agent_corporate_action_observations.capture_strategy_scope(
        con,
        "dual_momentum",
        market_date,
        observed_at=later_fetch + timedelta(days=1, hours=1),
    )

    assert unchanged["unchanged_observations"] == 1
    assert changed["value_revisions"] == 1
    rows = con.execute(
        "SELECT observation_sequence, value_revision, classification, "
        "previous_observation_sha256, observation_sha256 "
        "FROM agent_corporate_action_observations "
        "WHERE ticker = 'BIL' ORDER BY observation_sequence"
    ).fetchall()
    assert [row[:3] for row in rows] == [
        (1, 1, "baseline_snapshot"),
        (2, 1, "unchanged_observation"),
        (3, 2, "value_revision"),
    ]
    assert rows[0][3] is None
    assert rows[1][3] == rows[0][4]
    assert rows[2][3] == rows[1][4]


def test_context_binds_dividend_to_exact_immutable_observation(con):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    agent_corporate_action_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )

    context = agent_context.build(con, "dual_momentum", "SPY")
    bil = next(
        item
        for item in context["decision_features"]["assets"]
        if item["ticker"] == "BIL"
    )
    fact = bil["lookbacks"][0]["dividends"][0]

    assert fact["schema_version"] == 4
    assert fact["revision"]["policy"] == "append_only_normalized_observation"
    assert fact["revision"]["classification"] == "baseline_snapshot"
    assert fact["revision"]["history_retained"] is True
    assert fact["revision"]["point_in_time_replayable"] is True
    assert fact["availability"]["usable_at"] == "2026-09-13T12:00:00Z"
    assert fact["ingestion"]["immutable_observed_at"] == "2026-09-13T12:00:00Z"
    assert fact["record"]["raw_retained"] is False


def test_context_detects_corporate_action_ledger_tampering(con):
    fixed_etf_market(con)
    market_date = complete_dual_momentum_history(con)
    agent_corporate_action_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )
    con.execute(
        "UPDATE agent_corporate_action_observations "
        "SET observation_sha256 = ? WHERE ticker = 'BIL'",
        [canonical_sha256({"tampered": True})],
    )

    with pytest.raises(agent_context.ContextError, match="identity is invalid"):
        agent_context.build(con, "dual_momentum", "SPY")


def test_status_is_bounded_and_fails_closed_on_broken_chain(con):
    fixed_etf_market(con)
    missing = agent_corporate_action_observations.status(con)
    assert missing["status"] == "not_initialized"
    assert missing["raw_retained"] is False

    market_date = complete_dual_momentum_history(con)
    agent_corporate_action_observations.capture_strategy_scope(
        con, "dual_momentum", market_date, observed_at=NOW
    )
    captured = agent_corporate_action_observations.status(con)
    assert captured == {
        "schema_version": 1,
        "status": "capturing",
        "observation_count": 1,
        "ticker_count": 1,
        "first_ex_date": "2026-06-01",
        "last_ex_date": "2026-06-01",
        "first_observed_at": "2026-09-13T12:00:00Z",
        "last_observed_at": "2026-09-13T12:00:00Z",
        "kind_counts": {"dividend": 1, "split": 0},
        "classification_counts": {
            "baseline_snapshot": 1,
            "unchanged_observation": 0,
            "value_revision": 0,
        },
        "raw_retained": False,
        "point_in_time_scope": "normalized_observations_after_capture_only",
        "execution_authority": "none",
    }

    con.execute(
        "UPDATE agent_corporate_action_observations "
        "SET previous_observation_sha256 = ? WHERE ticker = 'BIL'",
        ["f" * 64],
    )
    with pytest.raises(
        agent_corporate_action_observations.ObservationError,
        match="ledger is invalid",
    ):
        agent_corporate_action_observations.status(con)


def test_capture_rejects_invalid_action_before_any_insert(con):
    agent_corporate_action_observations.init_schema(con)
    invalid = (
        "BIL",
        date(2026, 6, 1),
        "dividend",
        -1.0,
        "yfinance",
        datetime(2026, 9, 12),
    )

    with pytest.raises(
        agent_corporate_action_observations.ObservationError,
        match="observation is invalid",
    ):
        agent_corporate_action_observations._capture_rows(
            con, [invalid], observed_at=NOW
        )

    assert con.execute(
        "SELECT COUNT(*) FROM agent_corporate_action_observations"
    ).fetchone() == (0,)
