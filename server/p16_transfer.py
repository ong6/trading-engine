"""Production of active-return transfer coefficients for every P15/P16 book."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import numpy as np

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from farm.p16_statistics import (
    implied_active_weights,
    transfer_coefficient,
    weight_pearson_tc,
)
from sim import nyse, portfolio

BOOK_POLICIES = {
    "p15_ai_ranked": "champion",
    "p15_rule_control": "rule",
    "p15_hybrid_veto": "rule",
    "p16_construct_ai": "champion",
    "p16_construct_rule": "rule",
}


def _cutoff(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("transfer cutoff must be timezone-aware")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _scores(con, signal_date: date, cutoff: datetime) -> tuple[dict[str, dict], str]:
    if not table_exists(con, "agent_evaluation_traces") \
            or not table_exists(con, "agent_evaluation_decisions"):
        return {}, canonical_sha256([])
    rows = con.execute(
        "SELECT d.ticker,d.decision_payload FROM agent_evaluation_decisions d "
        "JOIN agent_evaluation_traces t ON t.id=d.trace_id "
        "WHERE t.policy_id='p15-scoring-v1' AND t.market_date=? "
        "AND t.terminal_status='completed' AND t.completed_at<=? ORDER BY d.ticker",
        [signal_date, cutoff],
    ).fetchall()
    values = {}
    for ticker, raw in rows:
        try:
            payload = json.loads(raw)
            champion = float(payload["expected_excess_bp_5"])
            rule = -float(payload["baseline_rank"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        if np.isfinite(champion) and np.isfinite(rule):
            values[ticker] = {"champion": champion, "rule": rule}
    return values, canonical_sha256([
        {"ticker": ticker, **values[ticker]} for ticker in sorted(values)
    ])


def _active_sigma(con, ticker: str, signal_date: date, cutoff: datetime) -> float | None:
    sessions, cursor = [], signal_date
    while len(sessions) < 61:
        if nyse.is_session(cursor):
            sessions.append(cursor)
        cursor -= timedelta(days=1)
    sessions.reverse()
    placeholders = ",".join("?" for _ in sessions)
    rows = con.execute(
        f"SELECT ticker,date,close FROM prices WHERE ticker IN (?,?) "
        f"AND date IN ({placeholders}) AND fetched_at IS NOT NULL AND fetched_at<=? "
        "AND close>0 AND volume>0 ORDER BY ticker,date",
        [ticker, "SPY", *sessions, cutoff],
    ).fetchall()
    by_ticker: dict[str, dict[date, float]] = {ticker: {}, "SPY": {}}
    for name, market_date, close in rows:
        by_ticker[name][market_date] = float(close)
    if any(set(by_ticker[name]) != set(sessions) for name in by_ticker):
        return None
    stock = np.asarray([by_ticker[ticker][session] for session in sessions])
    spy = np.asarray([by_ticker["SPY"][session] for session in sessions])
    active = stock[1:] / stock[:-1] - spy[1:] / spy[:-1]
    return float(np.std(active, ddof=1)) if np.all(np.isfinite(active)) else None


def _instance(con, book_id: str, registration_sha256: str) -> str | None:
    if book_id.startswith("p15_"):
        return book_id
    if not table_exists(con, "p16_book_contracts"):
        return None
    row = con.execute(
        "SELECT book_instance_id FROM p16_book_contracts "
        "WHERE logical_portfolio_id=? AND registration_sha256=?",
        [book_id, registration_sha256],
    ).fetchone()
    return None if row is None else row[0]


def produce(
    con, *, registration_sha256: str, signal_date: date, holding_date: date,
    information_cutoff_at: datetime, trailing_ic: dict[str, float],
) -> dict:
    """Compute five book rows from one score/risk vintage and next-open holdings."""
    cutoff = _cutoff(information_cutoff_at)
    scores, score_sha = _scores(con, signal_date, cutoff)
    tickers = sorted(scores)
    sigma = {ticker: _active_sigma(con, ticker, signal_date, cutoff) for ticker in tickers}
    risk_sha = canonical_sha256([
        {"ticker": ticker, "active_return_sd60": sigma[ticker]} for ticker in tickers
    ])
    rows = []
    for book_id, policy in BOOK_POLICIES.items():
        instance = _instance(con, book_id, registration_sha256)
        row = {
            "book_id": book_id, "book_instance_id": instance,
            "signal_date": signal_date.isoformat(), "holding_date": holding_date.isoformat(),
            "score_sha256": score_sha, "risk_sha256": risk_sha,
            "sigma_basis": "stock_minus_spy_daily_return_sd60_ddof1",
            "primary_instruments": "stocks_only_spy_and_cash_excluded",
        }
        if instance is None or not table_exists(con, "portfolios"):
            rows.append({**row, "status": "unavailable", "reason": "book_absent",
                         "tc_diagonal": None})
            continue
        portfolio_row = con.execute(
            "SELECT cash FROM portfolios WHERE id=?", [instance],
        ).fetchone()
        if portfolio_row is None or len(tickers) < 2:
            rows.append({**row, "status": "unavailable", "reason": "book_or_scores_unavailable",
                         "tc_diagonal": None})
            continue
        positions = portfolio.get_positions(con, instance)
        holding_marks = {}
        for ticker in positions:
            mark = con.execute(
                "SELECT open FROM prices WHERE ticker=? AND date=? AND open>0 AND volume>0 "
                "AND fetched_at IS NOT NULL AND fetched_at<=?",
                [ticker, holding_date, cutoff],
            ).fetchone()
            if mark is None:
                break
            holding_marks[ticker] = float(mark[0])
        if len(holding_marks) != len(positions):
            rows.append({**row, "status": "unavailable", "reason": "next_open_mark_unavailable",
                         "tc_diagonal": None})
            continue
        equity = float(portfolio_row[0]) + sum(
            float(position["qty"]) * holding_marks[ticker]
            for ticker, position in positions.items()
        )
        if equity <= 0:
            rows.append({**row, "status": "unavailable", "reason": "book_equity_invalid",
                         "tc_diagonal": None})
            continue
        weights, missing_held = [], 0.0
        for ticker in tickers:
            position = positions.get(ticker)
            weights.append(0.0 if position is None else
                           float(position["qty"]) * holding_marks[ticker] / equity)
        for ticker, position in positions.items():
            if ticker not in {"SPY", *tickers}:
                missing_held += float(position["qty"]) * holding_marks[ticker] / equity
        if any(sigma[ticker] is None for ticker in tickers):
            rows.append({**row, "status": "unavailable", "reason": "active_risk_unavailable",
                         "tc_diagonal": None})
            continue
        ic = trailing_ic.get(policy)
        positive_ic = isinstance(ic, (int, float)) and np.isfinite(ic) and ic > 0
        score_vector = [scores[ticker][policy] for ticker in tickers]
        sigma_vector = [sigma[ticker] for ticker in tickers]
        primary = transfer_coefficient(
            score_vector, sigma_vector, weights, positive_ic=positive_ic,
            held_unscored_weight=missing_held,
        )
        spy_position = positions.get("SPY")
        spy_weight = (0.0 if spy_position is None else
                      float(spy_position["qty"]) * holding_marks["SPY"] / equity)
        cash_weight = float(portfolio_row[0]) / equity
        implied = implied_active_weights(score_vector, sigma_vector, positive_ic=positive_ic)
        diagnostic = weight_pearson_tc(
            [*implied, 0.0], [*weights, spy_weight - 1.0, cash_weight],
        )
        rows.append({
            **row, **primary,
            "tc_weight_pearson": None if missing_held > 1e-15 else diagnostic,
            "stock_weight": float(sum(weights)), "spy_weight": spy_weight,
            "cash_weight": cash_weight, "trailing_ic": ic,
        })
    payload = {
        "schema_version": 1, "signal_date": signal_date.isoformat(),
        "holding_date": holding_date.isoformat(),
        "information_cutoff_at": cutoff.replace(tzinfo=timezone.utc).isoformat(),
        "score_sha256": score_sha, "risk_sha256": risk_sha,
        "books": rows, "execution_authority": "none",
    }
    return {**payload, "transfer_sha256": canonical_sha256(payload)}
