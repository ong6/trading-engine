"""Isolated paper-book attribution is verified without creating or scheduling it."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import duckdb
import pytest

from engine.lib.provenance import canonical_sha256
from server import (
    agent_attribution_read_models,
    agent_authority_read_models,
    agent_paper_attribution,
    agent_policy,
)
from sim.strategies.configs import config_by_id
from tests.agent_test_helpers import complete_dual_momentum_history, fixed_etf_market

BOOK_START = date(2026, 9, 10)
START = date(2026, 9, 11)
RECORDED = datetime(2026, 9, 11, 20, 0, tzinfo=timezone.utc)


def _tables(con) -> None:
    agent_paper_attribution.init_schema(con)


def test_schema_initialization_is_idempotent_and_creates_no_book_state(con):
    before = {
        table: con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()
        for table in (
            "portfolios",
            "sim_orders",
            "sim_fills",
            "sim_positions",
            "sim_equity",
            "sim_dividends",
        )
    }

    agent_paper_attribution.init_schema(con)
    agent_paper_attribution.init_schema(con)

    schemas = {}
    for table in (
        agent_paper_attribution.BOOK_ATTRIBUTION_TABLE,
        agent_paper_attribution.ORDER_ATTRIBUTION_TABLE,
    ):
        schemas[table] = tuple(
            (name, kind)
            for name, kind in con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? ORDER BY ordinal_position",
                [table],
            ).fetchall()
        )
        assert con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert schemas == {
        agent_paper_attribution.BOOK_ATTRIBUTION_TABLE: (
            agent_paper_attribution.BOOK_ATTRIBUTION_SCHEMA
        ),
        agent_paper_attribution.ORDER_ATTRIBUTION_TABLE: (
            agent_paper_attribution.ORDER_ATTRIBUTION_SCHEMA
        ),
    }
    after = {
        table: con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()
        for table in before
    }
    assert after == before


def test_attribution_schema_enforces_unique_book_and_decision_ownership(con):
    _tables(con)
    book_row = [
        "book-one",
        "policy-one",
        "1" * 64,
        "agent_only",
        "{}",
        "2" * 64,
        RECORDED,
    ]
    con.execute(
        "INSERT INTO agent_paper_book_attribution VALUES (?, ?, ?, ?, ?, ?, ?)",
        book_row,
    )
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO agent_paper_book_attribution VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["book-two", *book_row[1:]],
        )

    order_row = [
        101,
        "book-one",
        "policy-one",
        "1" * 64,
        "agent_only",
        7,
        1,
        "window-one",
        "3" * 64,
        "4" * 64,
        "{}",
        "5" * 64,
        RECORDED,
    ]
    con.execute(
        "INSERT INTO agent_paper_order_attribution VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        order_row,
    )
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO agent_paper_order_attribution VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [102, *order_row[1:]],
        )


def _controls(con) -> None:
    config = config_by_id("spy_benchmark")
    con.execute(
        "INSERT INTO portfolios "
        "(id, name, strategy, config, created, active, cash, initial_cash, "
        "execution_profile) VALUES (?, ?, ?, ?, DATE '2026-09-01', TRUE, "
        "39000, 39000, 'baseline_v1')",
        [
            config["id"],
            config["name"],
            config["strategy"],
            json.dumps(config),
        ],
    )


def _book(con, policy: dict, *, cash: float = 39_000.0) -> dict:
    contract = agent_paper_attribution.expected_book_contract(policy, BOOK_START)
    raw = json.dumps(contract, sort_keys=True, separators=(",", ":"))
    identity = canonical_sha256(contract)
    con.execute(
        "INSERT INTO portfolios "
        "(id, name, strategy, config, created, active, cash, initial_cash, "
        "execution_profile) VALUES (?, ?, ?, ?, ?, FALSE, ?, ?, ?)",
        [
            policy["reserved_portfolio_id"],
            f"{policy['mode']} isolated attribution book",
            contract["book_strategy"],
            raw,
            BOOK_START,
            cash,
            policy["capital_ceiling"],
            policy["execution_profile_id"],
        ],
    )
    con.execute(
        "INSERT INTO agent_paper_book_attribution VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            policy["reserved_portfolio_id"],
            policy["id"],
            policy["registration_sha256"],
            policy["mode"],
            raw,
            identity,
            datetime(2026, 9, 10, 0, 0),
        ],
    )
    return contract


def _equity(con, policy: dict, *, cash: float = 39_000.0) -> None:
    open_positions = con.execute(
        "SELECT COUNT(*) FROM sim_positions "
        "WHERE portfolio_id = ? AND qty != 0",
        [policy["reserved_portfolio_id"]],
    ).fetchone()[0]
    for portfolio_id in (
        policy["reserved_portfolio_id"],
        policy["attribution"]["algorithm_control_id"],
        policy["attribution"]["strategy_control_id"],
    ):
        con.execute(
            "INSERT OR IGNORE INTO sim_equity "
            "(portfolio_id, date, equity, cash, n_positions) "
            "VALUES (?, ?, 39000, 39000, 0)",
            [portfolio_id, BOOK_START],
        )
        con.execute(
            "INSERT OR IGNORE INTO sim_equity "
            "(portfolio_id, date, equity, cash, n_positions) "
            "VALUES (?, ?, 39000, ?, ?)",
            [
                portfolio_id,
                START,
                cash if portfolio_id == policy["reserved_portfolio_id"] else 39_000,
                (
                    open_positions
                    if portfolio_id == policy["reserved_portfolio_id"]
                    else 0
                ),
            ],
        )


def _decision(policy: dict) -> dict:
    return {
        "attempt_id": 7,
        "decision_window": "agent-shadow-v2:" + "1" * 64,
        "policy_id": policy["id"],
        "mode": policy["mode"],
        "completed_at": datetime(2026, 9, 11, 19, 0),
        "_terminal_event_sha256": "2" * 64,
        "_decision_evidence_sha256": "3" * 64,
        "_attributable_orders": [
            {
                "sequence": 1,
                "ticker": "SPY",
                "side": "buy",
                "quantity": 10.0,
                "signal_date": START,
                "quantity_rule": (
                    "maximum" if policy["mode"] == "agent_only" else "exact"
                ),
            }
        ],
    }


def _order(con, policy: dict, decision: dict, *, quantity: float = 10.0) -> None:
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(101, ?, 'SPY', 'buy', ?, ?, 'filled', NULL)",
        [policy["reserved_portfolio_id"], quantity, START],
    )
    con.execute(
        "INSERT INTO sim_fills VALUES "
        "(101, ?, 'SPY', 'buy', ?, ?, 100, 100, 0, 0)",
        [policy["reserved_portfolio_id"], quantity, START],
    )
    con.execute(
        "INSERT INTO sim_positions VALUES (?, 'SPY', ?, 100)",
        [policy["reserved_portfolio_id"], quantity],
    )
    payload = {
        "schema_version": 1,
        "order_id": 101,
        "portfolio_id": policy["reserved_portfolio_id"],
        "policy_id": policy["id"],
        "policy_registration_sha256": policy["registration_sha256"],
        "mode": policy["mode"],
        "attempt_id": decision["attempt_id"],
        "decision_order_sequence": 1,
        "decision_window": decision["decision_window"],
        "terminal_event_sha256": decision["_terminal_event_sha256"],
        "decision_evidence_sha256": decision["_decision_evidence_sha256"],
        "ticker": "SPY",
        "side": "buy",
        "quantity": quantity,
        "signal_date": START.isoformat(),
        "recorded_at": RECORDED.isoformat().replace("+00:00", "Z"),
        "execution_authority": "none",
    }
    con.execute(
        "INSERT INTO agent_paper_order_attribution VALUES "
        "(101, ?, ?, ?, ?, 7, 1, ?, ?, ?, ?, ?, ?)",
        [
            policy["reserved_portfolio_id"],
            policy["id"],
            policy["registration_sha256"],
            policy["mode"],
            decision["decision_window"],
            decision["_terminal_event_sha256"],
            decision["_decision_evidence_sha256"],
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            canonical_sha256(payload),
            RECORDED.replace(tzinfo=None),
        ],
    )


def test_absent_book_and_uncontracted_book_remain_unavailable(con):
    fixed_etf_market(con)
    _controls(con)
    policy = agent_policy.get("dual_momentum_agent_shadow_v1")

    absent = agent_paper_attribution.assess_policy(
        con, policy, decision_records=[]
    )
    assert absent["status"] == "unavailable_no_isolated_paper_portfolio"
    assert absent["portfolio_created"] is False

    contract = agent_paper_attribution.expected_book_contract(policy, BOOK_START)
    con.execute(
        "INSERT INTO portfolios "
        "(id, name, strategy, config, created, active, cash, initial_cash, "
        "execution_profile) VALUES (?, 'reserved', ?, ?, ?, FALSE, 39000, "
        "39000, 'baseline_v1')",
        [
            policy["reserved_portfolio_id"],
            contract["book_strategy"],
            json.dumps(contract),
            BOOK_START,
        ],
    )
    unavailable = agent_paper_attribution.assess_policy(
        con, policy, decision_records=[]
    )
    assert unavailable["status"] == "unavailable_no_persisted_attribution_contract"
    assert unavailable["portfolio_created"] is True


def test_complete_empty_isolated_book_has_separate_aligned_return_path(con):
    fixed_etf_market(con)
    _controls(con)
    policy = agent_policy.get("dual_momentum_agent_shadow_v1")
    _tables(con)
    _book(con, policy)
    _equity(con, policy)
    before = {
        table: con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()
        for table in (
            "portfolios",
            "sim_orders",
            "sim_fills",
            "sim_positions",
            "sim_equity",
            "agent_paper_book_attribution",
            "agent_paper_order_attribution",
        )
    }

    result = agent_paper_attribution.assess_policy(
        con, policy, decision_records=[]
    )

    assert result["status"] == "available"
    assert result["portfolio_created"] is True
    assert result["persisted_contract_present"] is True
    assert result["attribution_start_date"] == BOOK_START
    assert result["equity_start_date"] == BOOK_START
    assert result["equity_end_date"] == START
    assert result["equity_observation_count"] == 2
    assert result["order_count"] == 0
    assert result["attributed_order_count"] == 0
    assert result["evidence_pooling"] == "prohibited"
    assert result["execution_authority"] == "none"
    after = {
        table: con.execute(f"SELECT * FROM {table} ORDER BY ALL").fetchall()
        for table in before
    }
    assert after == before


def test_read_models_recognize_both_books_without_granting_authority(con):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    _controls(con)
    _tables(con)
    policies = [
        agent_policy.get("dual_momentum_agent_shadow_v1"),
        agent_policy.get("dual_momentum_hybrid_veto_shadow_v1"),
    ]
    for policy in policies:
        _book(con, policy)
        _equity(con, policy)

    attribution = agent_attribution_read_models.attribution(con)
    readiness = agent_authority_read_models.readiness(con)

    assert attribution["return_attribution_status"] == "available"
    assert {
        summary["return_attribution_status"]
        for summary in attribution["policy_summaries"]
    } == {"available"}
    for policy in readiness["policies"]:
        gates = {gate["name"]: gate for gate in policy["gates"]}
        assert gates["isolated_paper_portfolio"]["status"] == "pass"
        assert gates["return_attribution"]["status"] == "pass"
        assert policy["human_approved_paper_eligible"] is False
        assert policy["automatic_paper_eligible"] is False
        assert policy["paper_order_route"] == "absent"
        assert policy["execution_authority"] == "none"


@pytest.mark.parametrize(
    ("policy_id", "quantity"),
    [
        ("dual_momentum_agent_shadow_v1", 5.0),
        ("dual_momentum_hybrid_veto_shadow_v1", 10.0),
    ],
)
def test_every_order_fill_and_position_is_bound_to_one_policy_decision(
    con, policy_id, quantity
):
    fixed_etf_market(con)
    _controls(con)
    policy = agent_policy.get(policy_id)
    decision = _decision(policy)
    _tables(con)
    expected_cash = 39_000 - quantity * 100
    _book(con, policy, cash=expected_cash)
    _order(con, policy, decision, quantity=quantity)
    _equity(con, policy, cash=expected_cash)

    result = agent_paper_attribution.assess_policy(
        con, policy, decision_records=[decision]
    )

    assert result["status"] == "available"
    assert result["order_count"] == 1
    assert result["attributed_order_count"] == 1
    assert result["fill_count"] == 1
    assert result["position_count"] == 1


def test_hybrid_quantity_cannot_drift_from_deterministic_candidate(con):
    fixed_etf_market(con)
    _controls(con)
    policy = agent_policy.get("dual_momentum_hybrid_veto_shadow_v1")
    decision = _decision(policy)
    _tables(con)
    _book(con, policy, cash=38_500)
    _order(con, policy, decision, quantity=5.0)
    _equity(con, policy, cash=38_500)

    with pytest.raises(
        agent_paper_attribution.PaperAttributionError,
        match="ownership is inconsistent",
    ):
        agent_paper_attribution.assess_policy(
            con, policy, decision_records=[decision]
        )


def test_unattributed_or_cross_book_rows_fail_closed(con):
    fixed_etf_market(con)
    _controls(con)
    policy = agent_policy.get("dual_momentum_agent_shadow_v1")
    decision = _decision(policy)
    _tables(con)
    _book(con, policy, cash=38_000)
    _order(con, policy, decision)
    _equity(con, policy, cash=38_000)
    con.execute("DELETE FROM agent_paper_order_attribution")

    with pytest.raises(
        agent_paper_attribution.PaperAttributionError,
        match="unattributed simulator orders",
    ):
        agent_paper_attribution.assess_policy(
            con, policy, decision_records=[decision]
        )

    _order_attribution_only(con, policy, decision)
    con.execute(
        "UPDATE sim_fills SET portfolio_id = 'dual_momentum' WHERE order_id = 101"
    )
    with pytest.raises(
        agent_paper_attribution.PaperAttributionError,
        match="cross-book fill",
    ):
        agent_paper_attribution.assess_policy(
            con, policy, decision_records=[decision]
        )


def test_position_or_cash_not_reconciled_to_attributed_fills_fails_closed(con):
    fixed_etf_market(con)
    _controls(con)
    policy = agent_policy.get("dual_momentum_agent_shadow_v1")
    decision = _decision(policy)
    _tables(con)
    _book(con, policy, cash=38_000)
    _order(con, policy, decision)
    _equity(con, policy, cash=38_000)
    con.execute(
        "UPDATE sim_positions SET qty = 11 WHERE portfolio_id = ?",
        [policy["reserved_portfolio_id"]],
    )

    with pytest.raises(
        agent_paper_attribution.PaperAttributionError,
        match="positions do not reconcile",
    ):
        agent_paper_attribution.assess_policy(
            con, policy, decision_records=[decision]
        )

    con.execute(
        "UPDATE sim_positions SET qty = 10 WHERE portfolio_id = ?",
        [policy["reserved_portfolio_id"]],
    )
    con.execute(
        "UPDATE portfolios SET cash = 38001 WHERE id = ?",
        [policy["reserved_portfolio_id"]],
    )
    with pytest.raises(
        agent_paper_attribution.PaperAttributionError,
        match="cash does not reconcile",
    ):
        agent_paper_attribution.assess_policy(
            con, policy, decision_records=[decision]
        )


def _order_attribution_only(con, policy: dict, decision: dict) -> None:
    payload = {
        "schema_version": 1,
        "order_id": 101,
        "portfolio_id": policy["reserved_portfolio_id"],
        "policy_id": policy["id"],
        "policy_registration_sha256": policy["registration_sha256"],
        "mode": policy["mode"],
        "attempt_id": 7,
        "decision_order_sequence": 1,
        "decision_window": decision["decision_window"],
        "terminal_event_sha256": decision["_terminal_event_sha256"],
        "decision_evidence_sha256": decision["_decision_evidence_sha256"],
        "ticker": "SPY",
        "side": "buy",
        "quantity": 10.0,
        "signal_date": START.isoformat(),
        "recorded_at": RECORDED.isoformat().replace("+00:00", "Z"),
        "execution_authority": "none",
    }
    con.execute(
        "INSERT INTO agent_paper_order_attribution VALUES "
        "(101, ?, ?, ?, ?, 7, 1, ?, ?, ?, ?, ?, ?)",
        [
            policy["reserved_portfolio_id"],
            policy["id"],
            policy["registration_sha256"],
            policy["mode"],
            decision["decision_window"],
            decision["_terminal_event_sha256"],
            decision["_decision_evidence_sha256"],
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            canonical_sha256(payload),
            RECORDED.replace(tzinfo=None),
        ],
    )


def test_contract_tampering_and_control_date_misalignment_fail_closed(con):
    fixed_etf_market(con)
    _controls(con)
    policy = agent_policy.get("dual_momentum_agent_shadow_v1")
    _tables(con)
    _book(con, policy)
    _equity(con, policy)
    con.execute(
        "UPDATE agent_paper_book_attribution SET mode = 'hybrid' "
        "WHERE policy_id = ?",
        [policy["id"]],
    )

    with pytest.raises(
        agent_paper_attribution.PaperAttributionError,
        match="does not match its contract",
    ):
        agent_paper_attribution.assess_policy(con, policy, decision_records=[])

    con.execute(
        "UPDATE agent_paper_book_attribution SET mode = ? WHERE policy_id = ?",
        [policy["mode"], policy["id"]],
    )
    con.execute(
        "DELETE FROM sim_equity WHERE portfolio_id = 'spy_benchmark'"
    )
    with pytest.raises(
        agent_paper_attribution.PaperAttributionError,
        match="dates do not align",
    ):
        agent_paper_attribution.assess_policy(con, policy, decision_records=[])
