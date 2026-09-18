"""One verified model decision can control only its isolated paper book."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from server import (
    agent_paper_attribution,
    agent_paper_decisions,
    agent_policy,
    agent_shadow_runner,
    main,
)
from sim import league
from sim.strategies import get_strategy
from tests.agent_test_helpers import complete_dual_momentum_history, fixed_etf_market
from tests.test_agent_paper_attribution import _book, _controls, _equity
from tests.test_agent_paper_evidence import NOW, _accepted
from tests.test_agent_shadow_runner import connector_result

CONFIRMATION = agent_paper_decisions.CONFIRMATION


def _isolated_book(con):
    policy = agent_policy.get("dual_momentum_agent_shadow_v1")
    agent_paper_attribution.init_schema(con)
    _controls(con)
    _book(con, policy)
    _equity(con, policy)
    return policy


def test_accepted_proposal_creates_one_attributed_pending_order(con, monkeypatch):
    result = _accepted(con, monkeypatch)
    policy = _isolated_book(con)
    consumed_at = NOW + timedelta(minutes=1)

    first = agent_paper_decisions.consume(
        con,
        result["decision_window"],
        confirmation=CONFIRMATION,
        now=consumed_at,
    )
    second = agent_paper_decisions.consume(
        con,
        result["decision_window"],
        confirmation=CONFIRMATION,
        now=consumed_at + timedelta(minutes=1),
    )

    assert first["outcome"] == "order_pending"
    assert first["paper_execution_authority"] == "local_simulator_only"
    assert first["broker_submission_authority"] == "none"
    assert first["live_capital_authority"] == "none"
    assert second == {**first, "replayed": True}
    assert con.execute(
        "SELECT portfolio_id, ticker, side, qty, signal_date, status "
        "FROM sim_orders WHERE id = ?",
        [first["order_id"]],
    ).fetchone() == (
        policy["reserved_portfolio_id"],
        "SPY",
        "buy",
        pytest.approx(1_000.0 / 120.0),
        date(2026, 9, 11),
        "pending",
    )
    assert con.execute(
        "SELECT COUNT(*) FROM agent_paper_order_attribution WHERE order_id = ?",
        [first["order_id"]],
    ).fetchone() == (1,)
    assert con.execute(
        "SELECT active FROM portfolios WHERE id = ?",
        [policy["reserved_portfolio_id"]],
    ).fetchone() == (True,)


@contextmanager
def _no_lock(_path):
    yield


@contextmanager
def _borrowed_connection(factory):
    yield factory()


def _no_action(con, monkeypatch):
    fixed_etf_market(con)
    complete_dual_momentum_history(con)
    monkeypatch.setattr(agent_shadow_runner, "advisory_file_lock", _no_lock)
    monkeypatch.setattr(agent_shadow_runner, "_connection", _borrowed_connection)
    monkeypatch.setattr(agent_shadow_runner, "is_month_signal", lambda *_args: True)

    def generate(model_input):
        return connector_result(
            model_input,
            {
                "schema_version": 1,
                "decision": "no_action",
                "reason": "No bounded paper action is justified.",
            },
        )

    return agent_shadow_runner.run(
        "dual_momentum",
        "SPY",
        mode="agent_only",
        generate=generate,
        connection_factory=lambda: con,
        now=NOW,
    )


def test_model_no_action_is_consumed_without_order(con, monkeypatch):
    result = _no_action(con, monkeypatch)
    _isolated_book(con)

    receipt = agent_paper_decisions.consume(
        con,
        result["decision_window"],
        confirmation=CONFIRMATION,
        now=NOW + timedelta(minutes=1),
    )

    assert receipt["outcome"] == "no_action"
    assert receipt["order_id"] is None
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert con.execute(
        "SELECT active FROM portfolios WHERE id = ?",
        ["agent_dual_momentum_shadow_v1"],
    ).fetchone() == (True,)
    assert get_strategy("agent_only_policy").generate_orders(
        con, object(), date(2026, 9, 14)
    ) == []


def test_first_consumption_synchronizes_only_cash_only_control_dates(con, monkeypatch):
    result = _no_action(con, monkeypatch)
    policy = _isolated_book(con)
    missing_date = date(2026, 9, 11)
    for control_id in (
        policy["attribution"]["algorithm_control_id"],
        policy["attribution"]["strategy_control_id"],
    ):
        con.execute(
            "INSERT OR REPLACE INTO sim_equity VALUES (?, ?, 39000, 39000, 0)",
            [control_id, missing_date],
        )

    agent_paper_decisions.consume(
        con,
        result["decision_window"],
        confirmation=CONFIRMATION,
        now=NOW + timedelta(minutes=1),
    )

    assert con.execute(
        "SELECT equity, cash, n_positions FROM sim_equity "
        "WHERE portfolio_id = ? AND date = ?",
        [policy["reserved_portfolio_id"], missing_date],
    ).fetchone() == (39_000.0, 39_000.0, 0)
    assert con.execute(
        "SELECT COUNT(*) FROM sim_equity WHERE portfolio_id = ? AND date < ?",
        [policy["reserved_portfolio_id"], date(2026, 9, 10)],
    ).fetchone() == (0,)


def test_requires_confirmation_initialized_book_and_untampered_evidence(
    con, monkeypatch
):
    result = _accepted(con, monkeypatch)
    with pytest.raises(agent_paper_decisions.PaperDecisionError, match="confirmation"):
        agent_paper_decisions.consume(
            con,
            result["decision_window"],
            confirmation="wrong",
            now=NOW + timedelta(minutes=1),
        )
    with pytest.raises(agent_paper_decisions.PaperDecisionError, match="book"):
        agent_paper_decisions.consume(
            con,
            result["decision_window"],
            confirmation=CONFIRMATION,
            now=NOW + timedelta(minutes=1),
        )

    _isolated_book(con)
    con.execute("UPDATE agent_proposals SET proposal_sha256 = repeat('f', 64)")
    with pytest.raises(agent_paper_decisions.PaperDecisionError):
        agent_paper_decisions.consume(
            con,
            result["decision_window"],
            confirmation=CONFIRMATION,
            now=NOW + timedelta(minutes=1),
        )
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_expired_proposal_fails_closed(con, monkeypatch):
    result = _accepted(con, monkeypatch)
    _isolated_book(con)

    with pytest.raises(agent_paper_decisions.PaperDecisionError, match="window"):
        agent_paper_decisions.consume(
            con,
            result["decision_window"],
            confirmation=CONFIRMATION,
            now=NOW + timedelta(days=2),
        )

    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)


def test_inactive_agent_book_fills_and_marks_without_algorithm_generation(
    con, monkeypatch
):
    result = _accepted(con, monkeypatch)
    policy = _isolated_book(con)
    receipt = agent_paper_decisions.consume(
        con,
        result["decision_window"],
        confirmation=CONFIRMATION,
        now=NOW + timedelta(minutes=1),
    )
    next_session = date(2026, 9, 14)
    con.execute(
        "INSERT INTO prices "
        "(ticker,date,open,high,low,close,volume,source,fetched_at) "
        "VALUES ('SPY', ?, 121, 123, 120, 122, 1000000, 'yfinance', ?)",
        [next_session, NOW.replace(tzinfo=None)],
    )

    fills = league.fill_pending(con, next_session)
    marks = league.mtm_all(con, next_session, verbose=False)
    league.generate_all(con, next_session)

    assert fills == {"filled": 1, "rejected": 0, "pending": 0}
    assert marks == {"carried": {}}
    assert con.execute(
        "SELECT status FROM sim_orders WHERE id = ?", [receipt["order_id"]]
    ).fetchone() == ("filled",)
    assert con.execute(
        "SELECT COUNT(*) FROM sim_equity WHERE portfolio_id = ? AND date = ?",
        [policy["reserved_portfolio_id"], next_session],
    ).fetchone() == (1,)
    assert con.execute(
        "SELECT COUNT(*) FROM sim_orders WHERE portfolio_id = ?",
        [policy["reserved_portfolio_id"]],
    ).fetchone() == (1,)


def test_route_delegates_and_closes_connection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    expected = {"outcome": "no_action"}
    monkeypatch.setattr(main, "write_con", lambda: con)
    monkeypatch.setenv(agent_paper_decisions.AUTH_TOKEN_ENV, "x" * 32)
    monkeypatch.setattr(
        main.agent_paper_decisions,
        "consume",
        lambda actual, window, *, confirmation: (
            expected
            if (actual, window, confirmation) == (con, "window-1", CONFIRMATION)
            else pytest.fail("wrong route inputs")
        ),
    )

    request = agent_paper_decisions.PaperDecisionRequest(
        decision_window="window-1",
        confirmation=CONFIRMATION,
    )
    assert main.consume_agent_paper_decision(request, "x" * 32) == expected
    assert con.closed is True


def test_route_maps_domain_error(monkeypatch):
    class Connection:
        def close(self):
            pass

    monkeypatch.setattr(main, "write_con", Connection)
    monkeypatch.setenv(agent_paper_decisions.AUTH_TOKEN_ENV, "x" * 32)
    monkeypatch.setattr(
        main.agent_paper_decisions,
        "consume",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            agent_paper_decisions.PaperDecisionError(409, "blocked")
        ),
    )

    with pytest.raises(HTTPException, match="blocked") as error:
        main.consume_agent_paper_decision(
            agent_paper_decisions.PaperDecisionRequest(
                decision_window="window-1", confirmation=CONFIRMATION
            ),
            "x" * 32,
        )
    assert error.value.status_code == 409


def test_route_requires_server_side_secret(monkeypatch):
    monkeypatch.delenv(agent_paper_decisions.AUTH_TOKEN_ENV, raising=False)
    request = agent_paper_decisions.PaperDecisionRequest(
        decision_window="window-1", confirmation=CONFIRMATION
    )
    with pytest.raises(HTTPException, match="authentication") as error:
        main.consume_agent_paper_decision(request, None)
    assert error.value.status_code == 403


def test_route_maps_duckdb_contention_to_bounded_retry(monkeypatch):
    import duckdb

    class Connection:
        def close(self):
            pass

    monkeypatch.setenv(agent_paper_decisions.AUTH_TOKEN_ENV, "x" * 32)
    monkeypatch.setattr(main, "write_con", Connection)
    monkeypatch.setattr(
        main.agent_paper_decisions,
        "consume",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            duckdb.TransactionException("conflict")
        ),
    )
    monkeypatch.setattr(
        main.agent_paper_decisions, "replay_after_contention", lambda *_args: None
    )
    with pytest.raises(HTTPException, match="contention") as error:
        main.consume_agent_paper_decision(
            agent_paper_decisions.PaperDecisionRequest(
                decision_window="window-1", confirmation=CONFIRMATION
            ),
            "x" * 32,
        )
    assert error.value.status_code == 503


def test_route_returns_winner_receipt_after_concurrent_conflict(monkeypatch):
    import duckdb

    class Connection:
        def close(self):
            pass

    replay = {"outcome": "no_action", "replayed": True}
    monkeypatch.setenv(agent_paper_decisions.AUTH_TOKEN_ENV, "x" * 32)
    monkeypatch.setattr(main, "write_con", Connection)
    monkeypatch.setattr(
        main.agent_paper_decisions,
        "consume",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            duckdb.TransactionException("conflict")
        ),
    )
    monkeypatch.setattr(
        main.agent_paper_decisions,
        "replay_after_contention",
        lambda *_args: replay,
    )
    assert main.consume_agent_paper_decision(
        agent_paper_decisions.PaperDecisionRequest(
            decision_window="window-1", confirmation=CONFIRMATION
        ),
        "x" * 32,
    ) == replay


def test_receipt_tampering_fails_closed(con, monkeypatch):
    result = _no_action(con, monkeypatch)
    _isolated_book(con)
    receipt = agent_paper_decisions.consume(
        con, result["decision_window"], confirmation=CONFIRMATION,
        now=NOW + timedelta(minutes=1),
    )
    forged = {
        **receipt,
        "outcome": "order_pending",
        "order_id": 999999,
        "broker_submission_authority": "forged",
    }
    con.execute(
        "UPDATE agent_paper_decision_receipts SET receipt_payload = ?, "
        "receipt_sha256 = ? WHERE decision_window = ?",
        [
            __import__("json").dumps(forged, sort_keys=True, separators=(",", ":")),
            __import__("engine.lib.provenance", fromlist=["canonical_sha256"]).canonical_sha256(forged),
            result["decision_window"],
        ],
    )
    with pytest.raises(agent_paper_decisions.PaperDecisionError, match="identity"):
        agent_paper_decisions.consume(
            con, result["decision_window"], confirmation=CONFIRMATION,
            now=NOW + timedelta(minutes=2),
        )


def test_coherent_receipt_outcome_rewrite_fails_against_retained_decision(
    con, monkeypatch
):
    result = _accepted(con, monkeypatch)
    _isolated_book(con)
    receipt = agent_paper_decisions.consume(
        con, result["decision_window"], confirmation=CONFIRMATION,
        now=NOW + timedelta(minutes=1),
    )
    forged = {**receipt, "outcome": "no_action", "order_id": None}
    forged.pop("replayed", None)
    forged["replayed"] = False
    encoded = __import__("json").dumps(forged, sort_keys=True, separators=(",", ":"))
    digest = __import__("engine.lib.provenance", fromlist=["canonical_sha256"]).canonical_sha256(forged)
    con.execute(
        "UPDATE agent_paper_decision_receipts SET outcome = 'no_action', "
        "order_id = NULL, receipt_payload = ?, receipt_sha256 = ? "
        "WHERE decision_window = ?",
        [encoded, digest, result["decision_window"]],
    )
    with pytest.raises(agent_paper_decisions.PaperDecisionError, match="binding"):
        agent_paper_decisions.consume(
            con, result["decision_window"], confirmation=CONFIRMATION,
            now=NOW + timedelta(minutes=2),
        )


def test_receipts_are_exposed_through_existing_attribution_read_model(con, monkeypatch):
    result = _no_action(con, monkeypatch)
    _isolated_book(con)
    agent_paper_decisions.consume(
        con, result["decision_window"], confirmation=CONFIRMATION,
        now=NOW + timedelta(minutes=1),
    )
    projection = main.agent_decision_attribution.__wrapped__() if hasattr(
        main.agent_decision_attribution, "__wrapped__"
    ) else None
    # Call the domain read model directly; route delegation is covered elsewhere.
    from server import agent_attribution_read_models

    projected = agent_attribution_read_models.attribution(con)
    assert projection is None
    assert projected["paper_decision_consumption"]["matching_count"] == 1
    assert projected["paper_decision_consumption"]["receipts"][0]["outcome"] == "no_action"


def test_partial_write_rolls_back_and_control_portfolios_remain_separate(
    con, monkeypatch
):
    result = _accepted(con, monkeypatch)
    policy = _isolated_book(con)
    controls_before = {
        control_id: con.execute(
            "SELECT * FROM portfolios WHERE id = ?", [control_id]
        ).fetchone()
        for control_id in policy["attribution"].values()
    }
    original = agent_paper_decisions._persist
    monkeypatch.setattr(
        agent_paper_decisions,
        "_persist",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("injected")),
    )
    with pytest.raises(RuntimeError, match="injected"):
        agent_paper_decisions.consume(
            con, result["decision_window"], confirmation=CONFIRMATION,
            now=NOW + timedelta(minutes=1),
        )
    monkeypatch.setattr(agent_paper_decisions, "_persist", original)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM agent_paper_order_attribution").fetchone() == (0,)
    assert con.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_name = 'agent_paper_decision_receipts'"
    ).fetchone() == (0,)
    for control_id, row in controls_before.items():
        assert con.execute(
            "SELECT * FROM portfolios WHERE id = ?", [control_id]
        ).fetchone() == row


def test_rerun_preserves_attributed_agent_order_and_receipt(con, monkeypatch):
    result = _accepted(con, monkeypatch)
    _isolated_book(con)
    receipt = agent_paper_decisions.consume(
        con,
        result["decision_window"],
        confirmation=CONFIRMATION,
        now=NOW + timedelta(minutes=1),
    )

    league.rerun_cleanup(con, date(2026, 9, 11))

    assert con.execute(
        "SELECT COUNT(*) FROM sim_orders WHERE id = ?", [receipt["order_id"]]
    ).fetchone() == (1,)
    assert agent_paper_decisions.consume(
        con,
        result["decision_window"],
        confirmation=CONFIRMATION,
        now=NOW + timedelta(minutes=2),
    ) == {**receipt, "replayed": True}


def test_no_broker_or_live_adapter_is_imported():
    source = __import__("pathlib").Path(
        agent_paper_decisions.__file__
    ).read_text()
    assert "simulator_broker_adapter" not in source
    assert "disabled_live_broker_adapter" not in source
    assert "from . import broker_submission" not in source
    assert "import broker_submission" not in source
