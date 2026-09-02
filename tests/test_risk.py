"""server/risk.py gates on an in-memory book. Regime needs 200 SPY bars."""
from datetime import date, datetime, timedelta, timezone

import pytest

from server import risk
from sim.schema import INITIAL_CASH
from tests.conftest import insert_bars

EQ = INITIAL_CASH                # 39_000: 1R = $390, experiment cap = $97.50, 4R = $1_560
TODAY = datetime.now(timezone.utc).date()


def _spy_days(n=200, start=date(2023, 1, 2)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


@pytest.fixture
def risk_con(con):
    """200 SPY bars, rising -> risk-on. No discretionary book yet."""
    days = _spy_days()
    insert_bars(con, "SPY", days, close=[400.0 + i for i in range(200)])
    insert_bars(con, "AAA", days[-5:-1], close=100.0)  # the ticket's ticker, at $100
    return con


def good_ticket(**over):
    # risk/share $1 * 90 sh = $90 <= $97.50 experiment cap; qty 90 <= 390 (1%);
    # R:R = (104-100)/1 = 4.
    t = dict(ticker="AAA", side="buy", qty=90, entry_ref=100.0, stop=99.0,
             target=104.0, playbook="vcp", acknowledge_earnings=True)
    t.update(over)
    return t


def gate(gates, name):
    return next(g for g in gates if g["name"] == name)


def test_good_ticket_passes_every_gate(risk_con):
    t = good_ticket()
    gates = risk.evaluate_gates(risk_con, t)
    assert [g["name"] for g in gates] == [
        "stop_present", "entry_anchored", "notional_cap", "sizing_1pct",
        "playbook_named", "rr_at_least_2", "max_open_risk_4r", "earnings_window",
        "regime_gate", "circuit_breaker"]
    statuses = {g["name"]: g["status"] for g in gates}
    assert statuses["earnings_window"] == "unknown"        # no table; acked
    assert all(v == "pass" for k, v in statuses.items() if k != "earnings_window")
    ok, reasons = risk.is_allowed(gates, t)
    assert ok and reasons == []


def test_unacked_unknown_earnings_blocks(risk_con):
    t = good_ticket(acknowledge_earnings=False)
    ok, reasons = risk.is_allowed(risk.evaluate_gates(risk_con, t), t)
    assert not ok and reasons == [pytest.approx("earnings_window unacknowledged: no earnings data — check manually")]


def test_missing_stop_fails_dependent_gates(risk_con):
    gates = risk.evaluate_gates(risk_con, good_ticket(stop=None))
    for n in ("stop_present", "sizing_1pct", "rr_at_least_2", "max_open_risk_4r", "playbook_named"):
        assert gate(gates, n)["status"] == "fail", n


def test_stop_at_or_above_entry_fails(risk_con):
    assert gate(risk.evaluate_gates(risk_con, good_ticket(stop=100.0)), "stop_present")["status"] == "fail"
    assert gate(risk.evaluate_gates(risk_con, good_ticket(stop=101.0)), "stop_present")["status"] == "fail"


def test_sizing_gate_boundary(risk_con):
    # 1% of 39k = $390 / $1 per share = 390 shares max.
    assert gate(risk.evaluate_gates(risk_con, good_ticket(qty=390)), "sizing_1pct")["status"] == "pass"
    assert gate(risk.evaluate_gates(risk_con, good_ticket(qty=391)), "sizing_1pct")["status"] == "fail"


def test_experiment_cap_quarter_pct(risk_con):
    assert gate(risk.evaluate_gates(risk_con, good_ticket(qty=97)), "playbook_named")["status"] == "pass"
    g = gate(risk.evaluate_gates(risk_con, good_ticket(qty=98)), "playbook_named")
    assert g["status"] == "fail" and "0.25% cap" in g["detail"]
    assert gate(risk.evaluate_gates(risk_con, good_ticket(playbook="  ")), "playbook_named")["status"] == "fail"


def test_known_playbook_gets_full_size(risk_con, monkeypatch):
    monkeypatch.setattr(risk, "KNOWN_PLAYBOOKS", frozenset({"vcp"}))
    gates = risk.evaluate_gates(risk_con, good_ticket(qty=300))
    assert gate(gates, "playbook_named") == {"name": "playbook_named", "status": "pass",
                                             "detail": "playbook 'vcp'"}
    assert gate(gates, "sizing_1pct")["status"] == "pass"
    # the literal 'experiment' stays capped even when in the library
    monkeypatch.setattr(risk, "KNOWN_PLAYBOOKS", frozenset({"experiment"}))
    assert gate(risk.evaluate_gates(risk_con, good_ticket(qty=300, playbook="experiment")),
                "playbook_named")["status"] == "fail"


def test_rr_gate_boundary(risk_con):
    assert gate(risk.evaluate_gates(risk_con, good_ticket(target=102.0)), "rr_at_least_2")["status"] == "pass"
    assert gate(risk.evaluate_gates(risk_con, good_ticket(target=101.99)), "rr_at_least_2")["status"] == "fail"
    assert gate(risk.evaluate_gates(risk_con, good_ticket(target=None)), "rr_at_least_2")["status"] == "fail"


def _open_book(con, cash, positions):
    con.execute("INSERT INTO portfolios (id, name, cash, active) VALUES ('discretionary', 'd', ?, TRUE)", [cash])
    for tk, qty, avg in positions:
        con.execute("INSERT INTO sim_positions VALUES ('discretionary', ?, ?, ?)", [tk, qty, avg])


def test_disc_state_equity_and_default(risk_con):
    assert risk.disc_state(risk_con)["equity"] == INITIAL_CASH
    insert_bars(risk_con, "AAA", [_spy_days()[-1]], close=120.0)
    _open_book(risk_con, 10_000.0, [("AAA", 100.0, 100.0)])
    st = risk.disc_state(risk_con)
    assert st["exists"] and st["equity"] == pytest.approx(10_000 + 12_000)
    assert st["positions"][0]["stop"] is None


def test_heat_cap_counts_open_pending_and_ticket(risk_con):
    # Equity 39k -> 4R budget $1,560. Three stop-less positions = 3 x $390 = $1,170
    # (conservative 1R each). Ticket risk $90 -> $1,260 pass; add a pending
    # $400 order -> $1,660 fail.
    _open_book(risk_con, EQ, [])
    for tk in ("P1", "P2", "P3"):
        risk_con.execute("INSERT INTO sim_positions VALUES ('discretionary', ?, 1, 1)", [tk])
    # positions valued via _latest_close -> no bars -> 0 market value; equity stays 39k
    gates = risk.evaluate_gates(risk_con, good_ticket())
    assert gate(gates, "max_open_risk_4r")["status"] == "pass"
    risk_con.execute("INSERT INTO sim_orders VALUES (7, 'discretionary', 'PND', 'buy', 100, ?, 'pending', NULL)",
                     [TODAY])
    risk_con.execute("INSERT INTO disc_tickets (id, ticker, entry_ref, stop, status, order_id) "
                     "VALUES (1, 'PND', 50, 46, 'submitted', 7)")
    assert risk.pending_disc_risk(risk_con) == pytest.approx(400.0)
    gates = risk.evaluate_gates(risk_con, good_ticket())
    assert gate(gates, "max_open_risk_4r")["status"] == "fail"


def test_open_risk_uses_stored_stop(risk_con):
    _open_book(risk_con, EQ, [("AAA", 10.0, 100.0)])
    risk_con.execute("INSERT INTO disc_tickets (id, ticker, stop, status, created_at) "
                     "VALUES (1, 'AAA', 95, 'filled', now())")
    st = risk.disc_state(risk_con)
    assert st["positions"][0]["stop"] == 95.0
    assert risk.open_disc_risk(risk_con, st) == pytest.approx(50.0)     # 10 x (100-95)
    risk_con.execute("UPDATE disc_tickets SET stop = 120")               # stop above cost -> floor 0
    assert risk.open_disc_risk(risk_con, risk.disc_state(risk_con)) == 0.0


def test_regime_gate_risk_off_needs_override(con):
    days = _spy_days()
    insert_bars(con, "SPY", days, close=[600.0 - i for i in range(200)])   # falling: last < SMA
    label, _ = risk.spy_regime(con)
    assert label == "risk-off"
    assert gate(risk.evaluate_gates(con, good_ticket()), "regime_gate")["status"] == "fail"
    assert gate(risk.evaluate_gates(con, good_ticket(override_regime=True)), "regime_gate")["status"] == "fail"
    g = gate(risk.evaluate_gates(con, good_ticket(override_regime=True, override_reason="thesis")), "regime_gate")
    assert g["status"] == "pass" and "OVERRIDDEN" in g["detail"]


def test_regime_unknown_under_200_bars_blocks(con):
    insert_bars(con, "SPY", _spy_days(50))
    insert_bars(con, "AAA", _spy_days(50)[-3:], close=100.0)
    t = good_ticket()
    gates = risk.evaluate_gates(con, t)
    assert gate(gates, "regime_gate")["status"] == "unknown"
    ok, reasons = risk.is_allowed(gates, t)
    assert not ok and reasons[0].startswith("regime_gate unacknowledged")


def _earn(con, ticker, when, as_of, est=False):
    con.execute("INSERT INTO earnings_calendar VALUES (?, ?, ?, ?)", [ticker, when, as_of, est])


@pytest.fixture
def earn_con(con):
    con.execute("CREATE TABLE earnings_calendar (ticker VARCHAR, earnings_date DATE, "
                "as_of DATE, is_estimate BOOLEAN)")
    return con


def test_earnings_window_fail_inside_pass_outside(earn_con):
    _earn(earn_con, "AAA", TODAY + timedelta(days=7), TODAY, est=True)
    g = risk.earnings_window(earn_con, "AAA", acked=False)
    assert g["status"] == "fail" and "estimate" in g["detail"]
    _earn(earn_con, "BBB", TODAY + timedelta(days=8), TODAY)
    assert risk.earnings_window(earn_con, "BBB", acked=False)["status"] == "pass"
    _earn(earn_con, "CCC", TODAY - timedelta(days=1), TODAY)
    assert risk.earnings_window(earn_con, "CCC", acked=False)["status"] == "pass"
    assert risk.earnings_window(earn_con, "ZZZ", acked=True)["status"] == "unknown"


def test_earnings_window_uses_latest_snapshot_only(earn_con):
    _earn(earn_con, "AAA", TODAY + timedelta(days=2), TODAY - timedelta(days=30))   # stale: inside
    _earn(earn_con, "AAA", TODAY + timedelta(days=40), TODAY)                       # latest: outside
    assert risk.earnings_window(earn_con, "AAA", acked=False)["status"] == "pass"


def test_ack_clears_earnings_fail_but_nothing_else():
    gates = [{"name": "earnings_window", "status": "fail", "detail": "x"},
             {"name": "regime_gate", "status": "unknown", "detail": "y"}]
    ok, reasons = risk.is_allowed(gates, {"acknowledge_earnings": True})
    assert not ok and reasons == ["regime_gate unacknowledged: y"]
    ok, reasons = risk.is_allowed(gates[:1], {"acknowledge_earnings": True})
    assert ok
    ok, reasons = risk.is_allowed(gates[:1], {})
    assert not ok and reasons == ["earnings_window: x"]


# ------------------------------------------------------ circuit breaker ---- #
def _trip(con, oid, tk, side, qty, d, px, entry=None, stop=None):
    con.execute("INSERT INTO sim_fills VALUES (?, 'discretionary', ?, ?, ?, ?, ?, ?, 10, 10)",
                [oid, tk, side, qty, d, px, px])
    if side == "buy":
        con.execute("INSERT INTO disc_tickets (id, ticker, entry_ref, stop, status, order_id) "
                    "VALUES (?, ?, ?, ?, 'filled', ?)", [oid, tk, entry, stop, oid])


def test_closed_round_trips_fifo_and_realized_r(risk_con):
    days = _spy_days()
    _trip(risk_con, 1, "AAA", "buy", 10, days[-10], 100.0, entry=100.0, stop=95.0)
    _trip(risk_con, 2, "AAA", "buy", 10, days[-9], 110.0, entry=110.0, stop=100.0)
    _trip(risk_con, 3, "AAA", "sell", 15, days[-8], 90.0)
    trips = risk.closed_round_trips(risk_con)
    assert [(t["qty"], t["entry_px"], t["realized_r"]) for t in trips] == [
        (10.0, 100.0, pytest.approx(-2.0)), (5.0, 110.0, pytest.approx(-2.0))]


def test_round_trip_without_stop_falls_back_to_unit_r(risk_con):
    days = _spy_days()
    _trip(risk_con, 1, "AAA", "buy", 10, days[-10], 100.0)
    _trip(risk_con, 2, "AAA", "sell", 10, days[-9], 130.0)
    assert risk.closed_round_trips(risk_con)[0]["realized_r"] == 1.0


def test_circuit_breaker_three_losers(risk_con):
    days = _spy_days()
    assert risk.circuit_breaker(risk_con)["status"] == "pass"
    for i, tk in enumerate(("A", "B", "C")):
        _trip(risk_con, 10 + i, tk, "buy", 1, days[-40 + i], 100.0, entry=100.0, stop=90.0)
        _trip(risk_con, 20 + i, tk, "sell", 1, days[-30 + i], 99.0)          # -0.1R each
    cb = risk.circuit_breaker(risk_con)
    assert cb["status"] == "fail" and "consecutive" in cb["detail"]
    # a review marker after the last exit clears it
    risk_con.execute("INSERT INTO review_markers VALUES (?, 'circuit_breaker')",
                     [datetime.combine(days[-20], datetime.min.time())])
    assert risk.circuit_breaker(risk_con)["status"] == "pass"


def test_circuit_breaker_minus_five_r_in_window(risk_con):
    days = _spy_days()
    _trip(risk_con, 1, "A", "buy", 10, days[-10], 100.0, entry=100.0, stop=99.0)
    _trip(risk_con, 2, "A", "sell", 10, days[-2], 94.0)                       # -6R, in last 5 sessions
    _trip(risk_con, 3, "B", "buy", 1, days[-10], 100.0, entry=100.0, stop=99.0)
    _trip(risk_con, 4, "B", "sell", 1, days[-1], 101.0)                       # +1R -> not 3 losers
    cb = risk.circuit_breaker(risk_con)
    assert cb["status"] == "fail" and "-5.0R" in cb["detail"]


def test_circuit_breaker_old_loss_outside_window_passes(risk_con):
    days = _spy_days()
    _trip(risk_con, 1, "A", "buy", 10, days[-30], 100.0, entry=100.0, stop=99.0)
    _trip(risk_con, 2, "A", "sell", 10, days[-20], 90.0)                      # -10R but stale
    assert risk.circuit_breaker(risk_con)["status"] == "pass"
