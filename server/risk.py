"""Discretionary ticket risk gates — execution-design §4 enforced server-side.

Every gate returns {name, status, detail} where status is 'pass' | 'fail' |
'unknown'. Submission is allowed iff no gate is 'fail' and every 'unknown' gate
is explicitly acknowledged (only earnings has an ack flag today — we never
silently pass what we can't verify).

The discretionary book is portfolio id 'discretionary'. Market reads use the
latest actually traded bar rather than zero-volume flat quotes. This module
reads only; the caller opens the connection.
"""

from __future__ import annotations

from datetime import date, datetime

import duckdb

from engine.lib.data_quality import quarantine_reason

from . import risk_book, risk_history, risk_market, risk_ticket_gates

EXPERIMENT_MAX = 0.0025  # 'experiment' playbook capped at 0.25% equity
MAX_OPEN_R = 4.0  # portfolio heat cap in R (× 1% equity)
ENTRY_ANCHOR_MAX = 0.10  # entry_ref may sit at most 10% from the latest close

# Public contract shared by API consumers, tests, and current documentation.
# evaluate_gates() asserts this exact order before returning so adding, removing,
# or reordering a control requires an intentional contract update.
RISK_CONTROL_NAMES: tuple[str, ...] = (
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

# The known-playbook library: setups the book has vetted and sizes at the full
# 1% risk. A setup NOT in this set is treated as an experiment and capped at
# EXPERIMENT_MAX (0.25%). Empty for now — until it is populated, every named
# setup is unknown and therefore capped (only 'experiment' is intentionally so).
KNOWN_PLAYBOOKS: frozenset[str] = frozenset()


# --------------------------------------------------------------------------- #
# gate evaluation
# --------------------------------------------------------------------------- #
def _g(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def _data_quarantine_gate(con: duckdb.DuckDBPyConnection, ticket: dict) -> dict:
    quarantine = (
        quarantine_reason(con, ticket.get("ticker", ""))
        if ticket.get("side", "buy") == "buy"
        else None
    )
    return _g(
        "data_quarantine",
        "fail" if quarantine else "pass",
        f"confirmed primary-data defect: {quarantine}"
        if quarantine
        else "no active primary-data quarantine",
    )


def _market_risk_inputs(
    con: duckdb.DuckDBPyConnection,
    ticket: dict,
    market_date: date | None,
) -> tuple[date | None, float | None, float | None, bool, float | None, float | None]:
    entry = ticket.get("entry_ref")
    stop = ticket.get("stop")
    qty = float(ticket.get("qty") or 0)
    quote = (
        risk_book.latest_real_quote(con, ticket.get("ticker"), as_of=market_date)
        if ticket.get("ticker") and market_date is not None
        else None
    )
    quote_date = None if quote is None else quote[0]
    close = None if quote is None else quote[1]
    ref = None if entry is None else (entry if close is None else max(float(entry), close))
    long_ok = (
        ref is not None and stop is not None and ref > stop and (close is None or stop < close)
    )
    r_per_share = (ref - stop) if long_ok else None
    ticket_risk = qty * r_per_share if long_ok else None
    return quote_date, close, ref, long_ok, r_per_share, ticket_risk


def _open_risk_gate(
    con: duckdb.DuckDBPyConnection,
    state: dict,
    ticket_risk: float | None,
    equity: float,
) -> dict:
    if ticket_risk is None:
        return _g(
            "max_open_risk_4r",
            "fail",
            "cannot compute ticket risk without valid stop",
        )
    open_risk = risk_book.open_disc_risk(con, state)
    budget = MAX_OPEN_R * risk_book.RISK_PCT * equity
    total = open_risk + ticket_risk
    return _g(
        "max_open_risk_4r",
        "pass" if total <= budget else "fail",
        f"open ${open_risk:,.0f} + ticket ${ticket_risk:,.0f} = "
        f"${total:,.0f} vs 4R budget ${budget:,.0f}",
    )


def _regime_gate(con: duckdb.DuckDBPyConnection, ticket: dict, market_date: date | None) -> dict:
    label, detail = risk_market.spy_regime_for_date(con, market_date)
    if label == "unknown":
        return _g("regime_gate", "unknown", detail)
    if label == "risk-on":
        return _g("regime_gate", "pass", detail)
    if ticket.get("override_regime") and (ticket.get("override_reason") or "").strip():
        return _g(
            "regime_gate",
            "pass",
            f"{detail}; OVERRIDDEN: {ticket['override_reason']}",
        )
    return _g(
        "regime_gate",
        "fail",
        f"{detail}; set override_regime + override_reason to proceed",
    )


def _circuit_breaker_gate(con: duckdb.DuckDBPyConnection) -> dict:
    result = risk_history.circuit_breaker(con)
    return _g("circuit_breaker", result["status"], result["detail"])


def _require_risk_control_contract(gates: list[dict]) -> None:
    emitted = tuple(gate["name"] for gate in gates)
    if emitted != RISK_CONTROL_NAMES:
        raise RuntimeError(
            f"risk-control contract mismatch: expected {RISK_CONTROL_NAMES!r}, emitted {emitted!r}"
        )


def _risk_context(
    con: duckdb.DuckDBPyConnection, ticket: dict
) -> risk_ticket_gates.TicketRiskContext:
    entry = ticket.get("entry_ref")
    stop = ticket.get("stop")
    target = ticket.get("target")
    qty = float(ticket.get("qty") or 0)
    playbook = (ticket.get("playbook") or "").strip()
    market_date = risk_book.latest_prices_date(con)
    state = risk_book.disc_state(con, as_of=market_date)
    equity = state["equity"]

    # The next open is unknown, so risk/share uses the worse of the owner's
    # entry reference and the latest eligible close.
    quote_date, close, ref, long_ok, r_per_share, ticket_risk = _market_risk_inputs(
        con, ticket, market_date
    )
    return risk_ticket_gates.TicketRiskContext(
        entry,
        stop,
        target,
        qty,
        playbook,
        market_date,
        state,
        equity,
        quote_date,
        close,
        ref,
        long_ok,
        r_per_share,
        ticket_risk,
    )


def _ticket_gates(
    con: duckdb.DuckDBPyConnection,
    ticket: dict,
    context: risk_ticket_gates.TicketRiskContext,
) -> list[dict]:
    local_gates = risk_ticket_gates.evaluate(
        context,
        entry_anchor_max=ENTRY_ANCHOR_MAX,
        experiment_max=EXPERIMENT_MAX,
        known_playbooks=KNOWN_PLAYBOOKS,
        risk_pct=risk_book.RISK_PCT,
    )
    return [_data_quarantine_gate(con, ticket), *local_gates]


def _portfolio_gates(
    con: duckdb.DuckDBPyConnection,
    ticket: dict,
    context: risk_ticket_gates.TicketRiskContext,
    now: datetime | None,
) -> list[dict]:
    return [
        _open_risk_gate(con, context.state, context.ticket_risk, context.equity),
        risk_market.earnings_window(
            con,
            ticket.get("ticker"),
            bool(ticket.get("acknowledge_earnings")),
            now=now,
        ),
        _regime_gate(con, ticket, context.market_date),
        _circuit_breaker_gate(con),
    ]


def _ordered_gates(
    con: duckdb.DuckDBPyConnection,
    ticket: dict,
    context: risk_ticket_gates.TicketRiskContext,
    now: datetime | None,
) -> list[dict]:
    return _ticket_gates(con, ticket, context) + _portfolio_gates(con, ticket, context, now)


def evaluate_gates(
    con: duckdb.DuckDBPyConnection,
    t: dict,
    *,
    now: datetime | None = None,
) -> list[dict]:
    """Run all gates for ticket dict `t`. Fields: ticker, side, qty, entry_ref,
    stop, target, playbook, acknowledge_earnings, override_regime,
    override_reason. Returns the list of gate results."""
    gates = _ordered_gates(con, t, _risk_context(con, t), now)
    _require_risk_control_contract(gates)
    return gates


def is_allowed(gates: list[dict], t: dict) -> tuple[bool, list[str]]:
    """(allowed, reasons). Allowed iff no gate 'fail' and every 'unknown' gate is
    acknowledged. Only earnings_window has an ack (acknowledge_earnings)."""
    reasons: list[str] = []
    for g in gates:
        # The earnings ack clears earnings_window whether it fails (earnings in
        # the window) or is unknown (no data) — an explicit "I checked" override.
        acked_earnings = g["name"] == "earnings_window" and t.get("acknowledge_earnings")
        if g["status"] == "fail":
            if acked_earnings:
                continue
            reasons.append(f"{g['name']}: {g['detail']}")
        elif g["status"] == "unknown":
            if acked_earnings:
                continue
            reasons.append(f"{g['name']} unacknowledged: {g['detail']}")
    return (len(reasons) == 0), reasons
