"""Discretionary ticket gate-policy tests."""

from datetime import datetime, timedelta, timezone

import pytest

from server import risk, risk_book, risk_market
from sim.schema import INITIAL_CASH
from tests.conftest import insert_bars
from tests.risk_test_helpers import (
    gate,
    good_ticket,
    open_book,
    populate_risk_con,
    spy_days,
)

EQ = INITIAL_CASH
TODAY = datetime.now(timezone.utc).date()


@pytest.fixture
def risk_con(con):
    return populate_risk_con(con)


def test_good_ticket_passes_every_gate(risk_con):
    t = good_ticket()
    gates = risk.evaluate_gates(risk_con, t)
    assert risk.RISK_CONTROL_NAMES == (
        "data_quarantine",
        "stop_present",
        "entry_anchored",
        "notional_cap",
        "sizing_1pct",
        "playbook_named",
        "rr_at_least_2",
        "max_open_risk_4r",
        "earnings_window",
        "regime_gate",
        "circuit_breaker",
    )
    assert tuple(g["name"] for g in gates) == risk.RISK_CONTROL_NAMES
    statuses = {g["name"]: g["status"] for g in gates}
    assert statuses["earnings_window"] == "unknown"  # no table; acked
    assert all(v == "pass" for k, v in statuses.items() if k != "earnings_window")
    ok, reasons = risk.is_allowed(gates, t)
    assert ok and reasons == []


def test_market_anchor_and_regime_ignore_later_phantom_quotes(risk_con):
    real_date = spy_days()[-1]
    phantom_date = real_date + timedelta(days=1)
    insert_bars(
        risk_con,
        "AAA",
        [phantom_date],
        open_=500.0,
        high=500.0,
        low=500.0,
        close=500.0,
        volume=0,
    )
    insert_bars(
        risk_con,
        "SPY",
        [phantom_date],
        open_=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        volume=0,
    )

    assert risk_book.latest_prices_date(risk_con) == real_date
    assert risk_book.latest_close(risk_con, "AAA") == 100.0
    assert risk_market.spy_regime(risk_con)[0] == "risk-on"
    assert gate(risk.evaluate_gates(risk_con, good_ticket()), "entry_anchored")["status"] == "pass"


def test_operational_quotes_ignore_a_real_bar_from_a_partial_batch(risk_con):
    market_date = spy_days()[-1]
    partial_date = market_date + timedelta(days=1)
    risk_con.execute("UPDATE universe SET liquid = TRUE WHERE ticker = 'AAA'")
    insert_bars(
        risk_con,
        "AAA",
        [partial_date],
        open_=499.0,
        high=501.0,
        low=498.0,
        close=500.0,
    )
    open_book(risk_con, 10_000.0, [("AAA", 100.0, 100.0)])

    assert risk_book.latest_prices_date(risk_con) == market_date
    assert risk_book.latest_real_quote(risk_con, "AAA") == (partial_date, 500.0)
    assert risk_book.latest_real_quote(risk_con, "AAA", as_of=market_date) == (
        market_date,
        100.0,
    )
    assert risk_book.disc_state(risk_con)["equity"] == pytest.approx(20_000.0)
    assert gate(risk.evaluate_gates(risk_con, good_ticket()), "entry_anchored")["status"] == "pass"


def test_operational_quotes_fail_closed_without_a_qualified_date(risk_con):
    risk_con.execute("DELETE FROM universe")
    risk_con.execute(
        "INSERT INTO universe (ticker, active, liquid) VALUES "
        "('AAA', TRUE, TRUE), ('MISSING', TRUE, TRUE)"
    )
    open_book(risk_con, 10_000.0, [("AAA", 100.0, 100.0)])

    assert risk_book.latest_prices_date(risk_con) is None
    state = risk_book.disc_state(risk_con)
    assert state["positions"][0]["close"] is None
    assert state["equity"] == pytest.approx(10_000.0)
    assert (
        gate(risk.evaluate_gates(risk_con, good_ticket()), "entry_anchored")["status"] == "unknown"
    )


def test_entry_anchor_rejects_a_stale_real_quote(risk_con):
    market_date = spy_days()[-1]
    risk_con.execute("DELETE FROM prices WHERE ticker = 'AAA' AND date = ?", [market_date])
    assert risk_book.latest_prices_date(risk_con) == market_date
    stale_quote = risk_book.latest_real_quote(risk_con, "AAA")
    assert stale_quote is not None and stale_quote[0] < market_date

    anchored = gate(risk.evaluate_gates(risk_con, good_ticket()), "entry_anchored")
    assert anchored["status"] == "fail"
    assert (
        f"latest real quote {stale_quote[0]} trails market date {market_date}" == anchored["detail"]
    )


def test_unacked_unknown_earnings_blocks(risk_con):
    t = good_ticket(acknowledge_earnings=False)
    ok, reasons = risk.is_allowed(risk.evaluate_gates(risk_con, t), t)
    assert not ok and reasons == [
        pytest.approx("earnings_window unacknowledged: no earnings data — check manually")
    ]


def test_missing_stop_fails_dependent_gates(risk_con):
    gates = risk.evaluate_gates(risk_con, good_ticket(stop=None))
    for n in ("stop_present", "sizing_1pct", "rr_at_least_2", "max_open_risk_4r", "playbook_named"):
        assert gate(gates, n)["status"] == "fail", n


def test_stop_at_or_above_entry_fails(risk_con):
    assert (
        gate(risk.evaluate_gates(risk_con, good_ticket(stop=100.0)), "stop_present")["status"]
        == "fail"
    )
    assert (
        gate(risk.evaluate_gates(risk_con, good_ticket(stop=101.0)), "stop_present")["status"]
        == "fail"
    )


def test_sizing_gate_boundary(risk_con):
    # 1% of 39k = $390 / $1 per share = 390 shares max.
    assert (
        gate(risk.evaluate_gates(risk_con, good_ticket(qty=390)), "sizing_1pct")["status"] == "pass"
    )
    assert (
        gate(risk.evaluate_gates(risk_con, good_ticket(qty=391)), "sizing_1pct")["status"] == "fail"
    )


def test_experiment_cap_quarter_pct(risk_con):
    assert (
        gate(risk.evaluate_gates(risk_con, good_ticket(qty=97)), "playbook_named")["status"]
        == "pass"
    )
    g = gate(risk.evaluate_gates(risk_con, good_ticket(qty=98)), "playbook_named")
    assert g["status"] == "fail" and "0.25% cap" in g["detail"]
    assert (
        gate(risk.evaluate_gates(risk_con, good_ticket(playbook="  ")), "playbook_named")["status"]
        == "fail"
    )


def test_known_playbook_gets_full_size(risk_con, monkeypatch):
    monkeypatch.setattr(risk, "KNOWN_PLAYBOOKS", frozenset({"vcp"}))
    gates = risk.evaluate_gates(risk_con, good_ticket(qty=300))
    assert gate(gates, "playbook_named") == {
        "name": "playbook_named",
        "status": "pass",
        "detail": "playbook 'vcp'",
    }
    assert gate(gates, "sizing_1pct")["status"] == "pass"
    # the literal 'experiment' stays capped even when in the library
    monkeypatch.setattr(risk, "KNOWN_PLAYBOOKS", frozenset({"experiment"}))
    assert (
        gate(
            risk.evaluate_gates(risk_con, good_ticket(qty=300, playbook="experiment")),
            "playbook_named",
        )["status"]
        == "fail"
    )


def test_rr_gate_boundary(risk_con):
    assert (
        gate(risk.evaluate_gates(risk_con, good_ticket(target=102.0)), "rr_at_least_2")["status"]
        == "pass"
    )
    assert (
        gate(risk.evaluate_gates(risk_con, good_ticket(target=101.99)), "rr_at_least_2")["status"]
        == "fail"
    )
    assert (
        gate(risk.evaluate_gates(risk_con, good_ticket(target=None)), "rr_at_least_2")["status"]
        == "fail"
    )


def test_heat_cap_counts_open_pending_and_ticket(risk_con):
    # Equity 39k -> 4R budget $1,560. Three stop-less positions = 3 x $390 = $1,170
    # (conservative 1R each). Ticket risk $90 -> $1,260 pass; add a pending
    # $400 order -> $1,660 fail.
    open_book(risk_con, EQ, [])
    for tk in ("P1", "P2", "P3"):
        risk_con.execute("INSERT INTO sim_positions VALUES ('discretionary', ?, 1, 1)", [tk])
    # positions valued via _latest_close -> no bars -> 0 market value; equity stays 39k
    gates = risk.evaluate_gates(risk_con, good_ticket())
    assert gate(gates, "max_open_risk_4r")["status"] == "pass"
    risk_con.execute(
        "INSERT INTO sim_orders VALUES (7, 'discretionary', 'PND', 'buy', 100, ?, 'pending', NULL)",
        [TODAY],
    )
    risk_con.execute(
        "INSERT INTO disc_tickets (id, ticker, entry_ref, stop, status, order_id) "
        "VALUES (1, 'PND', 50, 46, 'submitted', 7)"
    )
    assert risk_book.pending_disc_risk(risk_con) == pytest.approx(400.0)
    gates = risk.evaluate_gates(risk_con, good_ticket())
    assert gate(gates, "max_open_risk_4r")["status"] == "fail"


def test_regime_gate_risk_off_needs_override(con):
    days = spy_days()
    con.execute(
        "CREATE TABLE universe (ticker VARCHAR PRIMARY KEY, active BOOLEAN, liquid BOOLEAN)"
    )
    con.execute("INSERT INTO universe VALUES ('SPY', TRUE, TRUE)")
    insert_bars(con, "SPY", days, close=[600.0 - i for i in range(200)])  # falling: last < SMA
    label, _ = risk_market.spy_regime(con)
    assert label == "risk-off"
    assert gate(risk.evaluate_gates(con, good_ticket()), "regime_gate")["status"] == "fail"
    assert (
        gate(risk.evaluate_gates(con, good_ticket(override_regime=True)), "regime_gate")["status"]
        == "fail"
    )
    g = gate(
        risk.evaluate_gates(con, good_ticket(override_regime=True, override_reason="thesis")),
        "regime_gate",
    )
    assert g["status"] == "pass" and "OVERRIDDEN" in g["detail"]


def test_regime_unknown_under_200_bars_blocks(con):
    con.execute(
        "CREATE TABLE universe (ticker VARCHAR PRIMARY KEY, active BOOLEAN, liquid BOOLEAN)"
    )
    con.execute("INSERT INTO universe VALUES ('SPY', TRUE, TRUE), ('AAA', TRUE, TRUE)")
    insert_bars(con, "SPY", spy_days(50), high=101.0, low=99.0)
    insert_bars(con, "AAA", spy_days(50)[-3:], open_=100.0, high=101.0, low=99.0, close=100.0)
    t = good_ticket()
    gates = risk.evaluate_gates(con, t)
    assert gate(gates, "regime_gate")["status"] == "unknown"
    ok, reasons = risk.is_allowed(gates, t)
    assert not ok and reasons[0].startswith("regime_gate unacknowledged")


def test_ack_clears_earnings_fail_but_nothing_else():
    gates = [
        {"name": "earnings_window", "status": "fail", "detail": "x"},
        {"name": "regime_gate", "status": "unknown", "detail": "y"},
    ]
    ok, reasons = risk.is_allowed(gates, {"acknowledge_earnings": True})
    assert not ok and reasons == ["regime_gate unacknowledged: y"]
    ok, reasons = risk.is_allowed(gates[:1], {"acknowledge_earnings": True})
    assert ok
    ok, reasons = risk.is_allowed(gates[:1], {})
    assert not ok and reasons == ["earnings_window: x"]
