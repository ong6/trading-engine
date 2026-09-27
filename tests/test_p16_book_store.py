"""Persistence contracts for versioned P16 construction books."""
from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import pytest

from server import p16_book_store

NOW = datetime(2026, 9, 27, 16, tzinfo=timezone.utc)
REGISTRATION = "a" * 64


def test_contracts_use_full_registration_digest_and_remain_inactive():
    con = duckdb.connect(":memory:")
    instances = p16_book_store.initialize_contracts(
        con, registration_sha256=REGISTRATION, activation_date=date(2026, 10, 5),
        risk_aversion=5, cost_per_turnover=0.0005, created_at=NOW,
    )
    assert instances == [
        f"p16_construct_ai@sha256:{REGISTRATION}",
        f"p16_construct_rule@sha256:{REGISTRATION}",
    ]
    assert con.execute(
        "SELECT logical_portfolio_id,active,cash FROM p16_book_contracts c "
        "JOIN portfolios p ON p.id=c.portfolio_id ORDER BY logical_portfolio_id"
    ).fetchall() == [
        ("p16_construct_ai", False, 10_000.0),
        ("p16_construct_rule", False, 10_000.0),
    ]
    assert p16_book_store.initialize_contracts(
        con, registration_sha256=REGISTRATION, activation_date=date(2026, 10, 5),
        risk_aversion=5, cost_per_turnover=0.0005, created_at=NOW,
    ) == instances


def test_attempts_and_horizon_labels_are_separate_tables_with_p15_parity_columns():
    con = duckdb.connect(":memory:")
    p16_book_store.init_schema(con)
    attempts = [
        row[1] for row in con.execute("PRAGMA table_info('p16_limit_attempts')").fetchall()
    ]
    labels = [
        row[1] for row in con.execute("PRAGMA table_info('p16_limit_labels')").fetchall()
    ]
    assert attempts == [
        "intent_id", "attempt_date", "limit_px", "open_px",
        "counterfactual_fill_px", "outcome", "reject_reason",
    ]
    assert labels == [
        "intent_id", "attempt_date", "horizon_sessions", "entry_px", "exit_date",
        "exit_close", "net_return", "spy_net_return", "net_excess_return",
        "price_prefix_sha256", "labeled_at", "label_sha256",
    ]


def test_intent_and_attempt_exact_retries_are_idempotent_but_drift_is_rejected():
    con = duckdb.connect(":memory:")
    [instance, _] = p16_book_store.initialize_contracts(
        con, registration_sha256=REGISTRATION, activation_date=None,
        risk_aversion=5, cost_per_turnover=0.0005, created_at=NOW,
    )
    arguments = dict(
        book_instance_id=instance, signal_date=date(2026, 9, 25), ticker="AAA",
        side="buy", order_role="rebalance", target_weight=0.1, rounded_qty=10,
        source_sha256="b" * 64, limit_px=9.95,
        expected_session=date(2026, 9, 28), created_at=NOW,
    )
    intent_id, created = p16_book_store.add_intent(con, **arguments)
    assert created is True
    assert p16_book_store.add_intent(con, **arguments) == (intent_id, False)
    with pytest.raises(p16_book_store.P16BookError, match="replay differs"):
        p16_book_store.add_intent(con, **(arguments | {"rounded_qty": 11}))
    attempt = dict(
        intent_id=intent_id, attempt_date=date(2026, 9, 28), limit_px=9.95,
        open_px=10.0, counterfactual_fill_px=10.01,
        outcome="limit_not_reached", reject_reason="limit_not_reached",
    )
    assert p16_book_store.record_limit_attempt(con, **attempt) is True
    assert p16_book_store.record_limit_attempt(con, **attempt) is False
    with pytest.raises(p16_book_store.P16BookError, match="replay differs"):
        p16_book_store.record_limit_attempt(
            con, **(attempt | {"counterfactual_fill_px": 10.02}),
        )
