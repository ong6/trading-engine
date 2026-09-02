"""Discretionary ticket risk gates — the server-side enforcement of rules.md.

Every gate returns {name, status, detail} where status is 'pass' | 'fail' |
'unknown'. Submission is allowed iff no gate is 'fail' and every 'unknown' gate
is explicitly acknowledged (only earnings has an ack flag today — we never
silently pass what we can't verify).

The discretionary book is portfolio id 'discretionary'. All reads are as of the
latest bar in `prices`. This module reads only; the caller opens the connection.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import duckdb
import numpy as np

from sim.schema import INITIAL_CASH

from .sizing import size_position

DISC_ID = "discretionary"
RISK_PCT = 0.01          # 1% of equity per trade
EXPERIMENT_MAX = 0.0025  # 'experiment' playbook capped at 0.25% equity
MAX_OPEN_R = 4.0         # portfolio heat cap in R (× 1% equity)
CB_CONSEC_LOSERS = 3     # circuit breaker: 3 straight losing round-trips
CB_R_WINDOW_DAYS = 5     # ...or realized R ≤ -5 within trailing 5 trading days
CB_R_FLOOR = -5.0
EARNINGS_WINDOW_DAYS = 7  # fail if earnings fall within [today, today+7d]
ENTRY_ANCHOR_MAX = 0.10   # entry_ref may sit at most 10% from the latest close

# The known-playbook library: setups the book has vetted and sizes at the full
# 1% risk. A setup NOT in this set is treated as an experiment and capped at
# EXPERIMENT_MAX (0.25%). Empty for now — until it is populated, every named
# setup is unknown and therefore capped (only 'experiment' is intentionally so).
KNOWN_PLAYBOOKS: frozenset[str] = frozenset()


def _is_experiment(playbook: str) -> bool:
    """True when this setup carries the experiment risk cap (0.25%): the literal
    'experiment', or any setup absent from the known-playbook library."""
    pb = playbook.strip().lower()
    return pb == "experiment" or pb not in KNOWN_PLAYBOOKS


# --------------------------------------------------------------------------- #
# discretionary book state
# --------------------------------------------------------------------------- #
def latest_prices_date(con: duckdb.DuckDBPyConnection) -> date | None:
    return con.execute("SELECT MAX(date) FROM prices").fetchone()[0]


def _latest_close(con: duckdb.DuckDBPyConnection, ticker: str) -> float | None:
    row = con.execute(
        "SELECT close FROM prices WHERE ticker = ? AND date <= "
        "(SELECT MAX(date) FROM prices) ORDER BY date DESC LIMIT 1",
        [ticker],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def latest_stop_for(con: duckdb.DuckDBPyConnection, ticker: str) -> float | None:
    """Stop from the most recent submitted/filled disc ticket for this ticker."""
    if not _table_exists(con, "disc_tickets"):
        return None
    row = con.execute(
        "SELECT stop FROM disc_tickets WHERE ticker = ? AND stop IS NOT NULL "
        "AND status IN ('submitted', 'filled') ORDER BY created_at DESC, id DESC "
        "LIMIT 1",
        [ticker],
    ).fetchone()
    return None if row is None or row[0] is None else float(row[0])


def disc_state(con: duckdb.DuckDBPyConnection) -> dict:
    """Current discretionary book: {exists, cash, equity, positions[...] }.

    equity = cash + Σ qty*latest_close. Before the book's first ticket the
    portfolio row is absent → equity defaults to INITIAL_CASH, no positions.
    """
    row = con.execute(
        "SELECT cash FROM portfolios WHERE id = ?", [DISC_ID]
    ).fetchone()
    if row is None:
        return {"exists": False, "cash": INITIAL_CASH,
                "equity": INITIAL_CASH, "positions": []}
    cash = float(row[0])
    positions = []
    mkt = 0.0
    for tk, qty, avg in con.execute(
        "SELECT ticker, qty, avg_cost FROM sim_positions "
        "WHERE portfolio_id = ? AND qty > 0",
        [DISC_ID],
    ).fetchall():
        close = _latest_close(con, tk)
        stop = latest_stop_for(con, tk)
        if close is not None:
            mkt += qty * close
        positions.append({"ticker": tk, "qty": float(qty),
                          "avg_cost": float(avg), "stop": stop, "close": close})
    return {"exists": True, "cash": cash, "equity": cash + mkt,
            "positions": positions}


def pending_disc_risk(con: duckdb.DuckDBPyConnection) -> float:
    """Σ risk of already-accepted-but-unfilled discretionary buy orders, in
    dollars. Each pending sim_orders row joins back to its disc_ticket for the
    stop/entry_ref; risk = qty*(entry_ref-stop), floored at 0 (the stop-side gate
    guarantees entry_ref > stop for accepted tickets). A pending order missing any
    of qty/entry_ref/stop contributes nothing (never fabricate a stop)."""
    if not _table_exists(con, "sim_orders") or not _table_exists(con, "disc_tickets"):
        return 0.0
    rows = con.execute(
        "SELECT o.qty, t.entry_ref, t.stop FROM sim_orders o "
        "JOIN disc_tickets t ON t.order_id = o.id "
        "WHERE o.portfolio_id = ? AND o.status = 'pending' AND o.side = 'buy'",
        [DISC_ID],
    ).fetchall()
    total = 0.0
    for qty, entry, stop in rows:
        if qty is None or entry is None or stop is None:
            continue
        total += max(0.0, float(qty) * (float(entry) - float(stop)))
    return total


def open_disc_risk(con: duckdb.DuckDBPyConnection, state: dict) -> float:
    """Σ open discretionary risk in dollars. Position with a stored stop risks
    qty*(avg_cost-stop) (floored at 0); a position with no stored stop counts as
    1R = 1% of equity (conservative). Pending (accepted-but-unfilled) buy orders
    add their own committed risk so same-day tickets can't stack past the heat
    cap before any of them fills."""
    one_r = RISK_PCT * state["equity"]
    total = 0.0
    for p in state["positions"]:
        if p["stop"] is not None:
            total += max(0.0, p["qty"] * (p["avg_cost"] - p["stop"]))
        else:
            total += one_r
    return total + pending_disc_risk(con)


# --------------------------------------------------------------------------- #
# regime
# --------------------------------------------------------------------------- #
def spy_regime(con: duckdb.DuckDBPyConnection) -> tuple[str, str]:
    """('risk-on'|'risk-off'|'unknown', detail). risk-off = SPY < 200d SMA."""
    d = latest_prices_date(con)
    spy = con.execute(
        "SELECT close FROM prices WHERE ticker = 'SPY' AND date <= ? "
        "ORDER BY date DESC LIMIT 200",
        [d],
    ).fetchall()
    if len(spy) < 200:
        return "unknown", f"SPY has {len(spy)} bars (<200) — regime unknown"
    closes = np.array([r[0] for r in spy], dtype=float)
    sma = float(closes.mean())
    last = float(closes[0])
    label = "risk-off" if last < sma else "risk-on"
    return label, f"SPY {last:.2f} vs 200d SMA {sma:.2f} → {label}"


# --------------------------------------------------------------------------- #
# closed round-trips / circuit breaker
# --------------------------------------------------------------------------- #
def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [name]
    ).fetchone() is not None


def closed_round_trips(con: duckdb.DuckDBPyConnection) -> list[dict]:
    """FIFO-match discretionary buy→sell fills into closed round-trips.

    realized_r uses the entry ticket's stop (entry_ref-stop per share) when known;
    if the entry has no stored stop, magnitude falls back to ±1R by P&L sign
    (conservative). Returns oldest→newest by exit fill_date."""
    if not _table_exists(con, "disc_tickets"):
        return []
    fills = con.execute(
        "SELECT order_id, ticker, side, qty, fill_date, fill_px FROM sim_fills "
        "WHERE portfolio_id = ? ORDER BY fill_date, order_id",
        [DISC_ID],
    ).fetchall()
    # entry context per order_id (buy tickets carry entry_ref/stop).
    tickets = {
        oid: (er, st)
        for oid, er, st in con.execute(
            "SELECT order_id, entry_ref, stop FROM disc_tickets "
            "WHERE order_id IS NOT NULL"
        ).fetchall()
    }
    lots: dict[str, list[dict]] = {}
    trips: list[dict] = []
    for oid, tk, side, qty, fdate, fpx in fills:
        if side == "buy":
            er, st = tickets.get(oid, (None, None))
            rps = (er - st) if (er is not None and st is not None and er > st) else None
            lots.setdefault(tk, []).append(
                {"qty": float(qty), "px": float(fpx), "rps": rps})
        else:  # sell — close against oldest open lots
            remaining = float(qty)
            while remaining > 1e-9 and lots.get(tk):
                lot = lots[tk][0]
                take = min(remaining, lot["qty"])
                pnl_ps = float(fpx) - lot["px"]
                if lot["rps"]:
                    realized_r = pnl_ps / lot["rps"]
                else:
                    realized_r = 1.0 if pnl_ps > 0 else (-1.0 if pnl_ps < 0 else 0.0)
                trips.append({
                    "ticker": tk, "qty": take, "entry_px": lot["px"],
                    "exit_px": float(fpx), "exit_date": fdate,
                    "realized_r": realized_r,
                })
                lot["qty"] -= take
                remaining -= take
                if lot["qty"] <= 1e-9:
                    lots[tk].pop(0)
    return trips


def circuit_breaker(con: duckdb.DuckDBPyConnection) -> dict:
    """{status, detail}. Fires on 3 consecutive losing round-trips OR realized R
    ≤ -5 within the trailing 5 trading days. Cleared by the latest review marker:
    only round-trips closed strictly after it are considered."""
    marker = con.execute(
        "SELECT MAX(ts) FROM review_markers WHERE kind = 'circuit_breaker'"
    ).fetchone()[0] if _table_exists(con, "review_markers") else None
    trips = closed_round_trips(con)
    if marker is not None:
        trips = [t for t in trips if t["exit_date"] > marker.date()]
    if not trips:
        return {"status": "pass", "detail": "no closed discretionary round-trips"}

    # 3 consecutive losers (most recent trips).
    last3 = trips[-CB_CONSEC_LOSERS:]
    if len(last3) == CB_CONSEC_LOSERS and all(t["realized_r"] < 0 for t in last3):
        return {"status": "fail",
                "detail": f"{CB_CONSEC_LOSERS} consecutive losing round-trips"}

    # Realized R within trailing 5 trading days.
    cutoff = con.execute(
        "SELECT MIN(date) FROM (SELECT DISTINCT date FROM prices "
        "ORDER BY date DESC LIMIT ?)",
        [CB_R_WINDOW_DAYS],
    ).fetchone()[0]
    r_window = sum(t["realized_r"] for t in trips if t["exit_date"] >= cutoff)
    if r_window <= CB_R_FLOOR:
        return {"status": "fail",
                "detail": f"realized {r_window:.1f}R in trailing "
                          f"{CB_R_WINDOW_DAYS}d (≤ {CB_R_FLOOR:.0f}R)"}
    return {"status": "pass",
            "detail": f"ok — {r_window:.1f}R in trailing {CB_R_WINDOW_DAYS}d, "
                      f"last {len(last3)} not all losers"}


# --------------------------------------------------------------------------- #
# gate evaluation
# --------------------------------------------------------------------------- #
def _g(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def earnings_window(con: duckdb.DuckDBPyConnection, ticker: str,
                    acked: bool) -> dict:
    """earnings_window gate result. Reads the LATEST as_of snapshot per ticker
    from the append-only earnings_calendar. Fails if that snapshot has an
    earnings_date within [today, today+EARNINGS_WINDOW_DAYS]. No rows for the
    ticker (or the table absent / any DB error) → 'unknown, check manually', which
    the earnings ack clears. Past earnings dates never fail."""
    ack_suffix = " (acknowledged)" if acked else ""
    unknown = _g("earnings_window", "unknown",
                 "no earnings data — check manually" + ack_suffix)
    try:
        if not _table_exists(con, "earnings_calendar"):
            return unknown
        rows = con.execute(
            "SELECT earnings_date, is_estimate FROM earnings_calendar "
            "WHERE ticker = ? AND as_of = "
            "(SELECT MAX(as_of) FROM earnings_calendar WHERE ticker = ?)",
            [ticker, ticker],
        ).fetchall()
    except Exception:
        return unknown
    if not rows:
        return unknown
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=EARNINGS_WINDOW_DAYS)
    upcoming = [(d, est) for d, est in rows if d is not None and today <= d <= horizon]
    if not upcoming:
        return _g("earnings_window", "pass",
                  f"no earnings within {EARNINGS_WINDOW_DAYS}d")
    d, est = min(upcoming, key=lambda x: x[0])
    kind = "estimate" if est else "confirmed"
    return _g("earnings_window", "fail",
              f"earnings {d} ({kind}) within {EARNINGS_WINDOW_DAYS}d window")


def evaluate_gates(con: duckdb.DuckDBPyConnection, t: dict) -> list[dict]:
    """Run all gates for ticket dict `t`. Fields: ticker, side, qty, entry_ref,
    stop, target, playbook, acknowledge_earnings, override_regime,
    override_reason. Returns the list of gate results."""
    entry = t.get("entry_ref")
    stop = t.get("stop")
    target = t.get("target")
    qty = float(t.get("qty") or 0)
    playbook = (t.get("playbook") or "").strip()
    state = disc_state(con)
    equity = state["equity"]
    gates: list[dict] = []

    # Anchor to the market. entry_ref and stop are typed by the owner; sizing
    # from them alone let `entry_ref=1000, stop=999.99` on a $100 stock size a
    # 25x-the-book position through every gate (r/share 0.01). The order fills
    # at the NEXT open, which is unknown, so the honest risk per share is
    # measured from the worse of the typed entry and the latest close.
    close = _latest_close(con, t.get("ticker")) if t.get("ticker") else None
    ref = None
    if entry is not None:
        ref = entry if close is None else max(float(entry), close)
    long_ok = (ref is not None and stop is not None and ref > stop
               and (close is None or stop < close))
    r_per_share = (ref - stop) if long_ok else None
    ticket_risk = qty * r_per_share if long_ok else None

    # 1. stop_present — and the stop must be below the LIVE price too: a stop
    # above the latest close is already breached, not protection.
    if stop is None:
        gates.append(_g("stop_present", "fail", "no stop price given"))
    elif entry is None:
        gates.append(_g("stop_present", "fail", "no entry_ref to compare stop to"))
    elif stop >= entry:
        gates.append(_g("stop_present", "fail",
                        f"stop {stop} not below entry {entry} (long)"))
    elif close is not None and stop >= close:
        gates.append(_g("stop_present", "fail",
                        f"stop {stop} not below latest close {close:.2f} "
                        f"(already breached)"))
    else:
        gates.append(_g("stop_present", "pass",
                        f"stop {stop} < entry {entry}"
                        + (f" (risk/share from close {close:.2f})"
                           if close is not None and close > entry else "")))

    # 1b. entry_anchored — the typed entry must be near the market, or every
    # downstream number is fiction. ±10% covers a gap; beyond that the ticket
    # is stale or mistyped.
    if entry is None or close is None:
        gates.append(_g("entry_anchored", "unknown" if entry is not None else "fail",
                        "no latest close for ticker" if entry is not None
                        else "no entry_ref given"))
    else:
        dev = abs(float(entry) / close - 1.0)
        gates.append(_g("entry_anchored", "pass" if dev <= ENTRY_ANCHOR_MAX else "fail",
                        f"entry {entry} vs latest close {close:.2f} "
                        f"({dev * 100:.1f}% away, max {ENTRY_ANCHOR_MAX * 100:.0f}%)"))

    # 1c. notional_cap — paper book, no margin: qty × price may not exceed equity.
    # apply_fill would clamp the buy to cash anyway, but a clamp is a surprise,
    # not a gate.
    if ref is None:
        gates.append(_g("notional_cap", "fail", "cannot price the order"))
    else:
        notional = qty * ref
        gates.append(_g("notional_cap", "pass" if notional <= equity else "fail",
                        f"notional ${notional:,.0f} vs equity ${equity:,.0f}"))

    # 2. sizing_1pct
    if not long_ok:
        gates.append(_g("sizing_1pct", "fail",
                        "cannot size without entry > stop"))
    else:
        max_qty = size_position(equity, ref, stop, RISK_PCT)["qty"]
        status = "pass" if qty <= max_qty else "fail"
        gates.append(_g("sizing_1pct", status,
                        f"qty {qty:g} vs 1%-risk max {max_qty} "
                        f"(equity ${equity:,.0f})"))

    # 3. playbook_named
    if not playbook:
        gates.append(_g("playbook_named", "fail", "no playbook named"))
    elif _is_experiment(playbook):
        cap = EXPERIMENT_MAX * equity
        if ticket_risk is None:
            gates.append(_g("playbook_named", "fail",
                            "experiment: cannot verify size without valid stop"))
        elif ticket_risk <= cap:
            gates.append(_g("playbook_named", "pass",
                            f"experiment within ${cap:,.0f} (0.25%) cap "
                            f"(risk ${ticket_risk:,.0f})"))
        else:
            gates.append(_g("playbook_named", "fail",
                            f"experiment risk ${ticket_risk:,.0f} > 0.25% cap "
                            f"${cap:,.0f}"))
    else:
        gates.append(_g("playbook_named", "pass", f"playbook '{playbook}'"))

    # 4. rr_at_least_2
    if target is None:
        gates.append(_g("rr_at_least_2", "fail", "no target given"))
    elif not long_ok:
        gates.append(_g("rr_at_least_2", "fail",
                        "cannot compute R:R without entry > stop"))
    else:
        rr = (target - ref) / r_per_share
        status = "pass" if rr >= 2.0 else "fail"
        gates.append(_g("rr_at_least_2", status, f"R:R {rr:.2f} (need ≥ 2.0)"))

    # 5. max_open_risk_4r
    if ticket_risk is None:
        gates.append(_g("max_open_risk_4r", "fail",
                        "cannot compute ticket risk without valid stop"))
    else:
        open_risk = open_disc_risk(con, state)
        budget = MAX_OPEN_R * RISK_PCT * equity
        total = open_risk + ticket_risk
        status = "pass" if total <= budget else "fail"
        gates.append(_g("max_open_risk_4r", status,
                        f"open ${open_risk:,.0f} + ticket ${ticket_risk:,.0f} = "
                        f"${total:,.0f} vs 4R budget ${budget:,.0f}"))

    # 6. earnings_window — latest earnings_calendar snapshot; fail inside the
    # window, unknown when there's no data. Ack clears fail/unknown (is_allowed).
    acked = bool(t.get("acknowledge_earnings"))
    gates.append(earnings_window(con, t.get("ticker"), acked))

    # 7. regime_gate
    label, detail = spy_regime(con)
    if label == "unknown":
        gates.append(_g("regime_gate", "unknown", detail))
    elif label == "risk-on":
        gates.append(_g("regime_gate", "pass", detail))
    else:  # risk-off
        if t.get("override_regime") and (t.get("override_reason") or "").strip():
            gates.append(_g("regime_gate", "pass",
                            f"{detail}; OVERRIDDEN: {t['override_reason']}"))
        else:
            gates.append(_g("regime_gate", "fail",
                            f"{detail}; set override_regime + override_reason "
                            "to proceed"))

    # 8. circuit_breaker
    cb = circuit_breaker(con)
    gates.append(_g("circuit_breaker", cb["status"], cb["detail"]))

    return gates


def is_allowed(gates: list[dict], t: dict) -> tuple[bool, list[str]]:
    """(allowed, reasons). Allowed iff no gate 'fail' and every 'unknown' gate is
    acknowledged. Only earnings_window has an ack (acknowledge_earnings)."""
    reasons: list[str] = []
    for g in gates:
        # The earnings ack clears earnings_window whether it fails (earnings in
        # the window) or is unknown (no data) — an explicit "I checked" override.
        acked_earnings = (g["name"] == "earnings_window"
                          and t.get("acknowledge_earnings"))
        if g["status"] == "fail":
            if acked_earnings:
                continue
            reasons.append(f"{g['name']}: {g['detail']}")
        elif g["status"] == "unknown":
            if acked_earnings:
                continue
            reasons.append(f"{g['name']} unacknowledged: {g['detail']}")
    return (len(reasons) == 0), reasons
