"""Discretionary ticket writes are atomic and preserve paper-order invariants."""

from datetime import date, datetime, timezone

import pytest

from server import read_model_utils, ticket_contract, tickets
from tests.conftest import insert_bars
from tests.ticket_test_helpers import buy_body, liquid_universe, passing_risk


def test_create_rejects_oversized_text_before_any_write(con):
    with pytest.raises(
        ticket_contract.TicketError,
        match="notes must be at most 4096 characters",
    ) as exc_info:
        tickets.create(
            con,
            buy_body(notes="x" * (ticket_contract.NOTES_MAX_CHARS + 1)),
        )

    assert exc_info.value.status_code == 400
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM disc_tickets").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


def test_create_reports_the_signal_date_stored_on_order(con, monkeypatch):
    observed_now = []
    gates = [{"name": "test_gate", "status": "pass", "detail": "ok"}]
    monkeypatch.setattr(
        tickets.risk,
        "evaluate_gates",
        lambda actual, ticket, *, now: observed_now.append(now) or gates,
    )
    monkeypatch.setattr(tickets.risk, "is_allowed", lambda actual, ticket: (True, []))
    liquid_universe(con, "AAA")
    as_of = date(2026, 9, 1)
    submitted_at = datetime(2026, 9, 2, 15, 0, tzinfo=timezone.utc)
    insert_bars(con, "AAA", [as_of], close=10)
    # An unrelated dead quote dated after submission must not advance market
    # time or produce a future-dated order.
    insert_bars(con, "DEAD", [date(2026, 9, 3)], open_=50, high=50, low=50, close=50, volume=0)

    result = tickets.create(con, buy_body(), now=submitted_at)

    assert result["allowed"] is True
    assert result["status"] == "submitted"
    assert result["signal_date"] == date(2026, 9, 2)
    assert con.execute("SELECT signal_date FROM sim_orders").fetchone() == (date(2026, 9, 2),)
    assert con.execute("SELECT ticker, side, qty FROM disc_tickets").fetchone() == (
        "AAA",
        "buy",
        2.0,
    )
    assert con.execute("SELECT action FROM audit_log").fetchone() == ("ticket_submit",)
    assert observed_now == [submitted_at]
    stored_at = submitted_at.replace(tzinfo=None)  # DuckDB TIMESTAMP stores UTC wall time.
    assert con.execute("SELECT created_at FROM disc_tickets").fetchone() == (stored_at,)
    assert con.execute("SELECT ts FROM audit_log").fetchone() == (stored_at,)


def test_risk_rejected_buy_records_ticket_and_audit_without_creating_order(con, monkeypatch):
    gates = [{"name": "test_gate", "status": "fail", "detail": "blocked"}]
    reasons = ["test_gate: blocked"]
    monkeypatch.setattr(tickets.risk, "evaluate_gates", lambda con, ticket, **kwargs: gates)
    monkeypatch.setattr(tickets.risk, "is_allowed", lambda actual, ticket: (False, reasons))
    liquid_universe(con, "AAA")
    as_of = date(2026, 9, 1)
    insert_bars(con, "AAA", [as_of], close=10)

    result = tickets.create(
        con,
        buy_body(),
        now=datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc),
    )

    assert result == {
        "ticket_id": 1,
        "allowed": False,
        "status": "rejected",
        "order_id": None,
        "signal_date": as_of,
        "gates": gates,
        "reasons": reasons,
    }
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert con.execute("SELECT status, order_id FROM disc_tickets").fetchone() == (
        "rejected",
        None,
    )
    action, payload = con.execute("SELECT action, payload FROM audit_log").fetchone()
    assert action == "ticket_submit"
    assert '"allowed": false' in payload


def test_sell_reserves_quantity_already_in_pending_exits(con):
    as_of = date(2026, 9, 1)
    liquid_universe(con, "AAA")
    insert_bars(con, "AAA", [as_of], close=10)
    con.execute(
        "INSERT INTO portfolios "
        "(id, name, strategy, config, created, active, cash, initial_cash, execution_profile) "
        "VALUES ('discretionary', 'Discretionary', 'discretionary', '{}', ?, TRUE, "
        "39000, 39000, 'baseline_v1')",
        [as_of],
    )
    con.execute("INSERT INTO sim_positions VALUES ('discretionary', 'AAA', 10, 8)")
    con.execute(
        "INSERT INTO sim_orders VALUES (1, 'discretionary', 'AAA', 'sell', 7, ?, 'pending', NULL)",
        [as_of],
    )

    with pytest.raises(ticket_contract.TicketError, match="after pending exits") as exc_info:
        tickets.create(con, buy_body(side="sell", qty=4))

    assert exc_info.value.status_code == 400
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone()[0] == 1
    action, payload = con.execute("SELECT action, payload FROM audit_log").fetchone()
    assert action == "ticket_reject_short"
    assert '"available_to_sell": 3.0' in payload


def test_create_rolls_back_portfolio_order_and_ticket_when_audit_fails(con, monkeypatch):
    passing_risk(monkeypatch)
    liquid_universe(con, "AAA")
    insert_bars(con, "AAA", [date(2026, 9, 1)], close=10)
    monkeypatch.setattr(
        tickets,
        "_audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        tickets.create(con, buy_body())

    assert con.execute("SELECT COUNT(*) FROM portfolios").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM disc_tickets").fetchone()[0] == 0


def test_create_rolls_back_when_write_is_interrupted(con, monkeypatch):
    passing_risk(monkeypatch)
    liquid_universe(con, "AAA")
    insert_bars(con, "AAA", [date(2026, 9, 1)], close=10)
    monkeypatch.setattr(
        tickets,
        "_audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        tickets.create(con, buy_body())

    assert con.execute("SELECT COUNT(*) FROM portfolios").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM disc_tickets").fetchone()[0] == 0
    con.execute("BEGIN TRANSACTION")
    con.execute("ROLLBACK")


@pytest.mark.parametrize(
    "gates",
    [
        [],
        [None],
        [{"name": "", "status": "pass", "detail": "ok"}],
        [{"name": "test_gate", "status": "passed", "detail": "ok"}],
        [{"name": "test_gate", "status": "pass", "detail": None}],
    ],
)
def test_create_rolls_back_malformed_success_gate_projection(con, monkeypatch, gates):
    liquid_universe(con, "AAA")
    insert_bars(con, "AAA", [date(2026, 9, 1)], close=10)
    monkeypatch.setattr(tickets.risk, "evaluate_gates", lambda *_args, **_kwargs: gates)
    monkeypatch.setattr(tickets.risk, "is_allowed", lambda *_args: (True, []))

    with pytest.raises(ValueError, match="public ticket gate"):
        tickets.create(con, buy_body())

    assert con.execute("SELECT COUNT(*) FROM portfolios").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM disc_tickets").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


def test_submission_result_rejects_unreviewed_fields():
    result = {
        "ticket_id": 1,
        "allowed": True,
        "status": "submitted",
        "order_id": 2,
        "signal_date": date(2026, 9, 1),
        "gates": [{"name": "test_gate", "status": "pass", "detail": "ok"}],
        "reasons": [],
        "internal": True,
    }

    with pytest.raises(ValueError, match="submission shape"):
        tickets._validate_submission_result(result)

    result.pop("internal")
    result["gates"][0]["internal"] = True
    with pytest.raises(ValueError, match="public ticket gate"):
        tickets._validate_submission_result(result)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("name", "x" * (tickets.MAX_GATE_NAME_CHARS + 1), "gate name"),
        ("detail", "x" * (tickets.MAX_GATE_DETAIL_CHARS + 1), "gate detail"),
    ],
)
def test_submission_result_bounds_public_gate_text(field, value, message):
    gate = {"name": "test_gate", "status": "pass", "detail": "ok"}
    gate[field] = value
    result = {
        "ticket_id": 1,
        "allowed": True,
        "status": "submitted",
        "order_id": 2,
        "signal_date": date(2026, 9, 1),
        "gates": [gate],
        "reasons": [],
    }

    with pytest.raises(ValueError, match=message):
        tickets._validate_submission_result(result)


def test_submission_result_bounds_and_requires_nonblank_reasons():
    result = {
        "ticket_id": 1,
        "allowed": False,
        "status": "rejected",
        "order_id": None,
        "signal_date": date(2026, 9, 1),
        "gates": [{"name": "test_gate", "status": "fail", "detail": "blocked"}],
        "reasons": [" "],
    }

    with pytest.raises(ValueError, match="ticket reasons"):
        tickets._validate_submission_result(result)
    result["reasons"] = ["x" * (tickets.MAX_REASON_CHARS + 1)]
    with pytest.raises(ValueError, match="ticket reasons"):
        tickets._validate_submission_result(result)


@pytest.mark.parametrize(
    ("allowed", "reasons", "message"),
    [
        (True, ["unexpected"], "submitted ticket result"),
        (False, [], "rejected ticket result"),
        (False, [None], "ticket reasons"),
    ],
)
def test_create_rolls_back_incoherent_decision_projection(
    con, monkeypatch, allowed, reasons, message
):
    gates = [{"name": "test_gate", "status": "fail", "detail": "blocked"}]
    liquid_universe(con, "AAA")
    insert_bars(con, "AAA", [date(2026, 9, 1)], close=10)
    monkeypatch.setattr(tickets.risk, "evaluate_gates", lambda *_args, **_kwargs: gates)
    monkeypatch.setattr(tickets.risk, "is_allowed", lambda *_args: (allowed, reasons))

    with pytest.raises(ValueError, match=message):
        tickets.create(con, buy_body())

    assert con.execute("SELECT COUNT(*) FROM portfolios").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM disc_tickets").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


def test_create_rolls_back_non_date_signal_projection(con, monkeypatch):
    passing_risk(monkeypatch)
    liquid_universe(con, "AAA")
    insert_bars(con, "AAA", [date(2026, 9, 1)], close=10)
    monkeypatch.setattr(tickets, "signal_date", lambda *_args: datetime(2026, 9, 1))

    with pytest.raises(ValueError, match="ticket signal date"):
        tickets.create(con, buy_body())

    assert con.execute("SELECT COUNT(*) FROM portfolios").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM disc_tickets").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


def test_create_allocates_exact_public_safe_order_identifier(con, monkeypatch):
    maximum = read_model_utils.PUBLIC_SAFE_INTEGER_MAX
    passing_risk(monkeypatch)
    liquid_universe(con, "AAA")
    insert_bars(con, "AAA", [date(2026, 9, 1)], close=10)
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(?, 'seed', 'OLD', 'buy', 1, DATE '2026-08-31', 'filled', NULL)",
        [maximum - 1],
    )

    result = tickets.create(con, buy_body())

    assert result["order_id"] == maximum
    assert con.execute("SELECT MAX(id) FROM sim_orders").fetchone() == (maximum,)


def test_create_reports_order_identifier_exhaustion_after_atomic_rollback(con, monkeypatch):
    maximum = read_model_utils.PUBLIC_SAFE_INTEGER_MAX
    passing_risk(monkeypatch)
    liquid_universe(con, "AAA")
    insert_bars(con, "AAA", [date(2026, 9, 1)], close=10)
    con.execute(
        "INSERT INTO sim_orders VALUES "
        "(?, 'seed', 'OLD', 'buy', 1, DATE '2026-08-31', 'filled', NULL)",
        [maximum],
    )

    with pytest.raises(ticket_contract.TicketError, match="identifier space exhausted") as exc:
        tickets.create(con, buy_body())

    assert exc.value.status_code == 503
    assert con.execute("SELECT COUNT(*) FROM portfolios").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM disc_tickets").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


def test_create_reports_ticket_identifier_exhaustion_after_atomic_rollback(con, monkeypatch):
    maximum = read_model_utils.PUBLIC_SAFE_INTEGER_MAX
    passing_risk(monkeypatch)
    liquid_universe(con, "AAA")
    insert_bars(con, "AAA", [date(2026, 9, 1)], close=10)
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, status, created_at) "
        "VALUES (?, 'OLD', 'buy', 1, 'rejected', now())",
        [maximum],
    )

    with pytest.raises(ticket_contract.TicketError, match="identifier space exhausted") as exc:
        tickets.create(con, buy_body())

    assert exc.value.status_code == 503
    assert con.execute("SELECT COUNT(*) FROM portfolios").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM disc_tickets").fetchone() == (1,)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


def test_create_refuses_to_append_to_retired_discretionary_book(con, monkeypatch):
    passing_risk(monkeypatch)
    liquid_universe(con, "AAA")
    as_of = date(2026, 9, 1)
    insert_bars(con, "AAA", [as_of], close=10)
    con.execute(
        "INSERT INTO portfolios "
        "(id, name, strategy, config, created, active, cash) VALUES "
        "('discretionary', 'Retired discretionary', 'discretionary', '{}', ?, FALSE, 39000)",
        [as_of],
    )

    with pytest.raises(
        ticket_contract.TicketError, match="discretionary portfolio is inactive"
    ) as exc:
        tickets.create(con, buy_body())

    assert exc.value.status_code == 409
    assert con.execute("SELECT active FROM portfolios").fetchone() == (False,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM disc_tickets").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_create_treats_null_portfolio_active_flag_as_inactive(con, monkeypatch):
    passing_risk(monkeypatch)
    liquid_universe(con, "AAA")
    as_of = date(2026, 9, 1)
    insert_bars(con, "AAA", [as_of], close=10)
    con.execute(
        "INSERT INTO portfolios "
        "(id, name, strategy, config, created, active, cash) VALUES "
        "('discretionary', 'Invalid discretionary', 'discretionary', '{}', ?, NULL, 39000)",
        [as_of],
    )

    with pytest.raises(
        ticket_contract.TicketError, match="discretionary portfolio is inactive"
    ) as exc_info:
        tickets.create(con, buy_body())

    assert exc_info.value.status_code == 409
    assert con.execute("SELECT active FROM portfolios").fetchone() == (None,)
    assert con.execute("SELECT COUNT(*) FROM sim_orders").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM disc_tickets").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_cancel_rolls_back_order_and_ticket_when_audit_fails(con, monkeypatch):
    as_of = date(2026, 9, 1)
    con.execute(
        "INSERT INTO sim_orders VALUES (1, 'discretionary', 'AAA', 'buy', 2, ?, 'pending', NULL)",
        [as_of],
    )
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, status, order_id, created_at) "
        "VALUES (1, 'AAA', 'buy', 2, 'submitted', 1, now())"
    )
    monkeypatch.setattr(
        tickets,
        "_audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        tickets.cancel(con, 1)

    assert con.execute("SELECT status, reject_reason FROM sim_orders").fetchone() == (
        "pending",
        None,
    )
    assert con.execute("SELECT status FROM disc_tickets").fetchone() == ("submitted",)


@pytest.mark.parametrize(
    "ticket_id", [0, -1, True, 1.0, read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1]
)
def test_cancel_rejects_non_public_ticket_identifier_without_writes(con, ticket_id):
    with pytest.raises(ticket_contract.TicketError, match="ticket identifier is invalid") as exc:
        tickets.cancel(con, ticket_id)

    assert exc.value.status_code == 422
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


def test_cancel_rejects_unsafe_linked_order_identifier_without_writes(con):
    unsafe = read_model_utils.PUBLIC_SAFE_INTEGER_MAX + 1
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, status, order_id, created_at) "
        "VALUES (1, 'AAA', 'buy', 2, 'submitted', ?, now())",
        [unsafe],
    )

    with pytest.raises(ticket_contract.TicketError, match="invalid linked order") as exc:
        tickets.cancel(con, 1)

    assert exc.value.status_code == 409
    assert con.execute("SELECT status, order_id FROM disc_tickets").fetchone() == (
        "submitted",
        unsafe,
    )
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


def test_cancel_reports_null_order_status_without_calling_it_missing(con):
    as_of = date(2026, 9, 1)
    con.execute(
        "INSERT INTO sim_orders VALUES (1, 'discretionary', 'AAA', 'buy', 2, ?, NULL, NULL)",
        [as_of],
    )
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, status, order_id, created_at) "
        "VALUES (1, 'AAA', 'buy', 2, 'submitted', 1, now())"
    )

    with pytest.raises(ticket_contract.TicketError, match=r"status None") as exc_info:
        tickets.cancel(con, 1)

    assert exc_info.value.status_code == 409
    assert con.execute("SELECT status FROM disc_tickets").fetchone() == ("submitted",)


def test_cancel_refuses_rejected_ticket_without_order(con):
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, status, order_id, created_at) "
        "VALUES (1, 'AAA', 'buy', 2, 'rejected', NULL, now())"
    )

    with pytest.raises(ticket_contract.TicketError, match="has no order") as exc_info:
        tickets.cancel(con, 1)

    assert exc_info.value.status_code == 409
    assert con.execute("SELECT status FROM disc_tickets").fetchone() == ("rejected",)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


def test_cancel_reports_unknown_ticket_without_writing_audit(con):
    with pytest.raises(ticket_contract.TicketError, match="no ticket 99") as exc_info:
        tickets.cancel(con, 99)

    assert exc_info.value.status_code == 404
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


def test_cancel_reports_missing_linked_order_without_mutating_ticket(con):
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, status, order_id, created_at) "
        "VALUES (1, 'AAA', 'buy', 2, 'submitted', 99, now())"
    )

    with pytest.raises(ticket_contract.TicketError, match="status missing") as exc_info:
        tickets.cancel(con, 1)

    assert exc_info.value.status_code == 409
    assert con.execute("SELECT status FROM disc_tickets").fetchone() == ("submitted",)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


@pytest.mark.parametrize("order_status", ["filled", "rejected", "cancelled"])
def test_cancel_refuses_order_that_is_no_longer_pending(con, order_status):
    as_of = date(2026, 9, 1)
    con.execute(
        "INSERT INTO sim_orders VALUES (1, 'discretionary', 'AAA', 'buy', 2, ?, ?, NULL)",
        [as_of, order_status],
    )
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, status, order_id, created_at) "
        "VALUES (1, 'AAA', 'buy', 2, 'submitted', 1, now())"
    )

    with pytest.raises(ticket_contract.TicketError, match=rf"status {order_status}") as exc_info:
        tickets.cancel(con, 1)

    assert exc_info.value.status_code == 409
    assert con.execute("SELECT status FROM sim_orders").fetchone() == (order_status,)
    assert con.execute("SELECT status FROM disc_tickets").fetchone() == ("submitted",)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


def test_cancel_commits_order_ticket_and_audit_together(con):
    as_of = date(2026, 9, 1)
    con.execute(
        "INSERT INTO sim_orders VALUES (1, 'discretionary', 'AAA', 'buy', 2, ?, 'pending', NULL)",
        [as_of],
    )
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, status, order_id, created_at) "
        "VALUES (1, 'AAA', 'buy', 2, 'submitted', 1, now())"
    )

    assert tickets.cancel(con, 1) == {
        "ticket_id": 1,
        "order_id": 1,
        "status": "cancelled",
    }
    assert con.execute("SELECT status, reject_reason FROM sim_orders").fetchone() == (
        "cancelled",
        "cancelled by user",
    )
    assert con.execute("SELECT status FROM disc_tickets").fetchone() == ("cancelled",)
    assert con.execute("SELECT action FROM audit_log").fetchone() == ("ticket_cancel",)


def test_cancellation_result_rejects_unreviewed_fields():
    result = {"ticket_id": 1, "order_id": 2, "status": "cancelled", "internal": True}

    with pytest.raises(ValueError, match="cancellation shape"):
        tickets._validate_cancellation_result(result, 1)


def test_cancel_rolls_back_when_success_projection_is_invalid(con, monkeypatch):
    as_of = date(2026, 9, 1)
    con.execute(
        "INSERT INTO sim_orders VALUES (1, 'discretionary', 'AAA', 'buy', 2, ?, 'pending', NULL)",
        [as_of],
    )
    con.execute(
        "INSERT INTO disc_tickets "
        "(id, ticker, side, qty, status, order_id, created_at) "
        "VALUES (1, 'AAA', 'buy', 2, 'submitted', 1, now())"
    )
    monkeypatch.setattr(
        tickets,
        "_validate_cancellation_result",
        lambda *_args: (_ for _ in ()).throw(ValueError("invalid cancellation")),
    )

    with pytest.raises(ValueError, match="invalid cancellation"):
        tickets.cancel(con, 1)

    assert con.execute("SELECT status, reject_reason FROM sim_orders").fetchone() == (
        "pending",
        None,
    )
    assert con.execute("SELECT status FROM disc_tickets").fetchone() == ("submitted",)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


def test_review_marker_rolls_back_when_audit_fails(con, monkeypatch):
    monkeypatch.setattr(
        tickets,
        "_audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(RuntimeError, match="audit failed"):
        tickets.mark_review_done(con)

    assert con.execute("SELECT COUNT(*) FROM review_markers").fetchone()[0] == 0


def test_review_marker_and_audit_commit_together_at_one_timestamp(con, monkeypatch):
    timestamp = datetime(2026, 9, 9, 14, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(tickets, "_now", lambda: timestamp)

    result = tickets.mark_review_done(con)

    assert result["ok"] is True
    assert result["kind"] == "circuit_breaker"
    stored_at = timestamp.replace(tzinfo=None)  # DuckDB TIMESTAMP stores UTC wall time.
    assert con.execute("SELECT ts, kind FROM review_markers").fetchone() == (
        stored_at,
        "circuit_breaker",
    )
    audit_at, action, payload = con.execute("SELECT ts, action, payload FROM audit_log").fetchone()
    assert audit_at == stored_at
    assert action == "review_done"
    assert str(timestamp) in payload


def test_review_result_rejects_unreviewed_fields():
    result = {
        "ok": True,
        "kind": "circuit_breaker",
        "ts": datetime(2026, 9, 9, 14, 30, tzinfo=timezone.utc),
        "detail": "circuit breaker cleared",
        "internal": True,
    }

    with pytest.raises(ValueError, match="review result shape"):
        tickets._validate_review_result(result)


def test_review_marker_rolls_back_when_success_projection_is_invalid(con, monkeypatch):
    monkeypatch.setattr(
        tickets,
        "_validate_review_result",
        lambda *_args: (_ for _ in ()).throw(ValueError("invalid review result")),
    )

    with pytest.raises(ValueError, match="invalid review result"):
        tickets.mark_review_done(con)

    assert con.execute("SELECT COUNT(*) FROM review_markers").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)


def test_review_marker_rolls_back_for_naive_success_timestamp(con, monkeypatch):
    monkeypatch.setattr(tickets, "_now", lambda: datetime(2026, 9, 9, 14, 30))

    with pytest.raises(ValueError, match="review timestamp"):
        tickets.mark_review_done(con)

    assert con.execute("SELECT COUNT(*) FROM review_markers").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM audit_log").fetchone() == (0,)
