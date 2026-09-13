"""Pure ticket-local discretionary risk gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .sizing import size_position


@dataclass(frozen=True, slots=True)
class TicketRiskContext:
    entry: object
    stop: object
    target: object
    qty: float
    playbook: str
    market_date: date | None
    state: dict
    equity: float
    quote_date: date | None
    close: float | None
    ref: float | None
    long_ok: bool
    r_per_share: float | None
    ticket_risk: float | None


def _gate(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def _stop_present(entry: object, stop: object, close: float | None) -> dict:
    if stop is None:
        return _gate("stop_present", "fail", "no stop price given")
    if entry is None:
        return _gate("stop_present", "fail", "no entry_ref to compare stop to")
    if stop >= entry:
        return _gate("stop_present", "fail", f"stop {stop} not below entry {entry} (long)")
    if close is not None and stop >= close:
        return _gate(
            "stop_present",
            "fail",
            f"stop {stop} not below latest close {close:.2f} (already breached)",
        )
    detail = f"stop {stop} < entry {entry}"
    if close is not None and close > entry:
        detail += f" (risk/share from close {close:.2f})"
    return _gate("stop_present", "pass", detail)


def _entry_anchored(
    entry: object,
    quote_date: date | None,
    close: float | None,
    market_date: date | None,
    entry_anchor_max: float,
) -> dict:
    if entry is None:
        return _gate("entry_anchored", "fail", "no entry_ref given")
    if close is None or quote_date is None or market_date is None:
        return _gate("entry_anchored", "unknown", "no latest real close for ticker")
    if quote_date != market_date:
        return _gate(
            "entry_anchored",
            "fail",
            f"latest real quote {quote_date} trails market date {market_date}",
        )
    deviation = abs(float(entry) / close - 1.0)
    return _gate(
        "entry_anchored",
        "pass" if deviation <= entry_anchor_max else "fail",
        f"entry {entry} vs latest close {close:.2f} "
        f"({deviation * 100:.1f}% away, max {entry_anchor_max * 100:.0f}%)",
    )


def _notional_cap(qty: float, ref: float | None, equity: float) -> dict:
    if ref is None:
        return _gate("notional_cap", "fail", "cannot price the order")
    notional = qty * ref
    return _gate(
        "notional_cap",
        "pass" if notional <= equity else "fail",
        f"notional ${notional:,.0f} vs equity ${equity:,.0f}",
    )


def _sizing(
    qty: float,
    ref: float | None,
    stop: object,
    long_ok: bool,
    equity: float,
    risk_pct: float,
) -> dict:
    if not long_ok:
        return _gate("sizing_1pct", "fail", "cannot size without entry > stop")
    max_qty = size_position(equity, ref, stop, risk_pct)["qty"]
    return _gate(
        "sizing_1pct",
        "pass" if qty <= max_qty else "fail",
        f"qty {qty:g} vs 1%-risk max {max_qty} (equity ${equity:,.0f})",
    )


def _is_experiment(playbook: str, known_playbooks: frozenset[str]) -> bool:
    normalized = playbook.strip().lower()
    return normalized == "experiment" or normalized not in known_playbooks


def _playbook(
    playbook: str,
    ticket_risk: float | None,
    equity: float,
    experiment_max: float,
    known_playbooks: frozenset[str],
) -> dict:
    if not playbook:
        return _gate("playbook_named", "fail", "no playbook named")
    if not _is_experiment(playbook, known_playbooks):
        return _gate("playbook_named", "pass", f"playbook '{playbook}'")
    cap = experiment_max * equity
    if ticket_risk is None:
        return _gate(
            "playbook_named",
            "fail",
            "experiment: cannot verify size without valid stop",
        )
    if ticket_risk <= cap:
        return _gate(
            "playbook_named",
            "pass",
            f"experiment within ${cap:,.0f} (0.25%) cap (risk ${ticket_risk:,.0f})",
        )
    return _gate(
        "playbook_named",
        "fail",
        f"experiment risk ${ticket_risk:,.0f} > 0.25% cap ${cap:,.0f}",
    )


def _reward_risk(
    target: object,
    ref: float | None,
    r_per_share: float | None,
    long_ok: bool,
) -> dict:
    if target is None:
        return _gate("rr_at_least_2", "fail", "no target given")
    if not long_ok:
        return _gate("rr_at_least_2", "fail", "cannot compute R:R without entry > stop")
    ratio = (target - ref) / r_per_share
    return _gate(
        "rr_at_least_2",
        "pass" if ratio >= 2.0 else "fail",
        f"R:R {ratio:.2f} (need ≥ 2.0)",
    )


def evaluate(
    context: TicketRiskContext,
    *,
    entry_anchor_max: float,
    experiment_max: float,
    known_playbooks: frozenset[str],
    risk_pct: float,
) -> list[dict]:
    """Return the six deterministic ticket-local gates in contract order."""
    return [
        _stop_present(context.entry, context.stop, context.close),
        _entry_anchored(
            context.entry,
            context.quote_date,
            context.close,
            context.market_date,
            entry_anchor_max,
        ),
        _notional_cap(context.qty, context.ref, context.equity),
        _sizing(
            context.qty,
            context.ref,
            context.stop,
            context.long_ok,
            context.equity,
            risk_pct,
        ),
        _playbook(
            context.playbook,
            context.ticket_risk,
            context.equity,
            experiment_max,
            known_playbooks,
        ),
        _reward_risk(
            context.target,
            context.ref,
            context.r_per_share,
            context.long_ok,
        ),
    ]
