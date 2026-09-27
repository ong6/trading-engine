"""Production of active-return transfer coefficients for every P15/P16 book."""
from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np

from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from engine.p15_evaluation import spearman
from engine.p16_features import session_dates
from farm import p16_eval_inputs, p16_risk
from farm.p16_statistics import (
    implied_active_weights,
    transfer_coefficient,
    validate_transfer_rows,
    weight_pearson_tc,
)
from sim import nyse

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


def _score_snapshot(con, signal_date: date, cutoff: datetime) -> dict:
    origin = p16_eval_inputs.load_origin(
        con, market_date=signal_date, report_cutoff=cutoff.replace(tzinfo=timezone.utc),
    )
    values = {
        row["ticker"]: {"champion": float(row["champion_score"]),
                        "rule": float(row["rule_score"])}
        for row in origin["decision_rows"] if row["champion_score_available"] is True
    }
    scoring_cutoff = datetime.fromisoformat(
        origin["scoring_information_cutoff_at"].replace("Z", "+00:00"),
    ).astimezone(timezone.utc).replace(tzinfo=None)
    return {
        "scores": values, "score_sha256": canonical_sha256([
            {"ticker": ticker, **values[ticker]} for ticker in sorted(values)
        ]),
        "input_snapshot_sha256": origin["input_snapshot_sha256"],
        "scoring_cutoff": scoring_cutoff,
    }


def _active_risk(con, tickers: list[str], signal_date: date, cutoff: datetime) -> dict | None:
    sessions = session_dates(signal_date, 121)
    names = [*tickers, "SPY"]
    placeholders = ",".join("?" for _ in sessions)
    name_marks = ",".join("?" for _ in names)
    rows = con.execute(
        f"SELECT ticker,date,close,fetched_at FROM prices WHERE ticker IN ({name_marks}) "
        f"AND date IN ({placeholders}) AND fetched_at IS NOT NULL AND fetched_at<=? "
        "AND close>0 AND volume>0 ORDER BY ticker,date",
        [*names, *sessions, cutoff],
    ).fetchall()
    history: dict[str, dict[date, float]] = {ticker: {} for ticker in names}
    for ticker, market_date, close, _fetched_at in rows:
        history[ticker][market_date] = float(close)
    if any(set(history[ticker]) != set(sessions) for ticker in names):
        return None
    closes = np.column_stack([
        np.asarray([history[ticker][session] for session in sessions]) for ticker in names
    ])
    returns = closes[1:] / closes[:-1] - 1
    active = returns[:, :-1] - returns[:, -1, None]
    if not np.all(np.isfinite(active)):
        return None
    estimate = p16_risk.ledoit_wolf(active)
    return {
        "sigma": np.std(active[-60:], axis=0, ddof=1),
        "covariance": estimate["covariance"],
        "risk_sha256": canonical_sha256({
            "sessions": [value.isoformat() for value in sessions],
            "tickers": tickers, "closes": closes.tolist(),
            "scoring_cutoff": cutoff.isoformat(),
        }),
    }


def _trailing_ics(con, signal_date: date, cutoff: datetime) -> dict:
    """Derive both policies' ICs from exactly 60 consecutive mature P15 origins."""
    if not table_exists(con, "agent_evaluation_traces"):
        return {"status": "unavailable", "reason": "mature_ic_origins_absent",
                "values": {}, "source_sha256": canonical_sha256([])}
    candidates = [row[0] for row in con.execute(
        "SELECT DISTINCT market_date FROM agent_evaluation_traces "
        "WHERE policy_id='p15-scoring-v1' AND terminal_status='completed' "
        "AND market_date<? AND completed_at<=? ORDER BY market_date DESC LIMIT 20",
        [signal_date, cutoff],
    ).fetchall()]
    latest, latest_origin = None, None
    aware_cutoff = cutoff.replace(tzinfo=timezone.utc)
    for market_date in candidates:
        try:
            origin = p16_eval_inputs.load_origin(
                con, market_date=market_date, report_cutoff=aware_cutoff,
            )
        except p16_eval_inputs.EvaluationInputError:
            continue
        if origin.get("status") == "available":
            latest, latest_origin = market_date, origin
            break
    if latest is None:
        return {"status": "unavailable", "reason": "fewer_than_60_mature_origins",
                "values": {}, "source_sha256": canonical_sha256([])}
    origins, source = [], []
    for market_date in session_dates(latest, 60):
        try:
            origin = latest_origin if market_date == latest else p16_eval_inputs.load_origin(
                con, market_date=market_date, report_cutoff=aware_cutoff,
            )
        except p16_eval_inputs.EvaluationInputError:
            origin = None
        if origin is None or origin.get("status") != "available":
            return {"status": "unavailable", "reason": "nonconsecutive_mature_ic_origins",
                    "values": {}, "source_sha256": canonical_sha256(source)}
        usable = [row for row in origin["rows"] if row["champion_score_available"] is True]
        champion = spearman([float(row["champion_score"]) for row in usable],
                            [float(row["net_excess_return"]) for row in usable])
        rule = spearman([float(row["rule_score"]) for row in usable],
                        [float(row["net_excess_return"]) for row in usable])
        if len(usable) < 20 or champion is None or rule is None:
            return {"status": "unavailable", "reason": "mature_origin_ic_unavailable",
                    "values": {}, "source_sha256": canonical_sha256(source)}
        origins.append((float(champion), float(rule)))
        source.append({
            "market_date": market_date.isoformat(),
            "input_snapshot_sha256": origin["input_snapshot_sha256"],
            "label_sha256s": sorted(row["label_sha256"] for row in usable),
            "champion_ic": float(champion), "rule_ic": float(rule),
        })
    return {
        "status": "available", "reason": None,
        "values": {
            "champion": max(0.0, float(np.mean([row[0] for row in origins]))),
            "rule": max(0.0, float(np.mean([row[1] for row in origins]))),
        },
        "origin_dates": [row["market_date"] for row in source],
        "source_sha256": canonical_sha256(source),
    }


def _split_factor(con, ticker: str, after: date, through: date) -> float:
    if not table_exists(con, "split_adjustments"):
        return 1.0
    return float(np.prod([float(row[0]) for row in con.execute(
        "SELECT ratio FROM split_adjustments WHERE ticker=? AND outcome='applied' "
        "AND ex_date>? AND ex_date<=? ORDER BY ex_date", [ticker, after, through],
    ).fetchall()]))


def _state_as_of(con, instance: str, holding_date: date) -> dict | None:
    portfolio_row = con.execute(
        "SELECT initial_cash FROM portfolios WHERE id=?", [instance],
    ).fetchone()
    if portfolio_row is None:
        return None
    if table_exists(con, "sim_settlements") and con.execute(
        "SELECT 1 FROM sim_settlements WHERE portfolio_id=? AND effective<=? LIMIT 1",
        [instance, holding_date],
    ).fetchone() is not None:
        return None
    fills = con.execute(
        "SELECT order_id,ticker,side,qty,fill_date,fill_px FROM sim_fills "
        "WHERE portfolio_id=? AND fill_date<=? ORDER BY fill_date,order_id",
        [instance, holding_date],
    ).fetchall()
    cash = float(portfolio_row[0])
    quantities: dict[str, float] = {}
    for order_id, ticker, side, quantity, fill_date, fill_px in fills:
        del order_id
        signed = float(quantity) * _split_factor(con, ticker, fill_date, holding_date)
        quantities[ticker] = quantities.get(ticker, 0.0) + (signed if side == "buy" else -signed)
        cash += (-1 if side == "buy" else 1) * float(quantity) * float(fill_px)
    dividends = []
    if table_exists(con, "sim_dividends"):
        dividends = con.execute(
            "SELECT ticker,ex_date,amount FROM sim_dividends "
            "WHERE portfolio_id=? AND ex_date<=? ORDER BY ex_date,ticker",
            [instance, holding_date],
        ).fetchall()
        cash += sum(float(row[2]) for row in dividends)
    if cash < -1e-8 or any(quantity < -1e-8 for quantity in quantities.values()):
        return None
    positions = {ticker: quantity for ticker, quantity in quantities.items()
                 if quantity > 1e-12}
    body = {
        "book_instance_id": instance, "holding_date": holding_date.isoformat(),
        "initial_cash": float(portfolio_row[0]), "fills": [
            [int(row[0]), row[1], row[2], float(row[3]), row[4].isoformat(), float(row[5])]
            for row in fills
        ],
        "dividends": [[row[0], row[1].isoformat(), float(row[2])] for row in dividends],
        "positions": positions, "cash": cash,
    }
    return {**body, "state_sha256": canonical_sha256(body)}


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
    information_cutoff_at: datetime,
) -> dict:
    """Compute five book rows from one score/risk vintage and next-open holdings."""
    if holding_date != nyse.next_session(signal_date):
        raise ValueError("transfer holding date is not the next session")
    cutoff = _cutoff(information_cutoff_at)
    score_snapshot = _score_snapshot(con, signal_date, cutoff)
    scores, score_sha = score_snapshot["scores"], score_snapshot["score_sha256"]
    tickers = sorted(scores)
    risk = _active_risk(con, tickers, signal_date, score_snapshot["scoring_cutoff"])
    sigma = None if risk is None else dict(zip(tickers, risk["sigma"], strict=True))
    risk_sha = canonical_sha256([]) if risk is None else risk["risk_sha256"]
    trailing = _trailing_ics(con, signal_date, cutoff)
    rows = []
    for book_id, policy in BOOK_POLICIES.items():
        instance = _instance(con, book_id, registration_sha256)
        row = {
            "book_id": book_id, "book_instance_id": instance,
            "signal_date": signal_date.isoformat(), "holding_date": holding_date.isoformat(),
            "score_sha256": score_sha, "risk_sha256": risk_sha,
            "ic_source_sha256": trailing["source_sha256"],
            "sigma_basis": "stock_minus_spy_daily_return_sd60_ddof1",
            "primary_instruments": "stocks_only_spy_and_cash_excluded",
        }
        if instance is None or not table_exists(con, "portfolios"):
            rows.append({**row, "status": "unavailable", "reason": "book_absent",
                         "tc_diagonal": None})
            continue
        state = _state_as_of(con, instance, holding_date)
        if state is None or len(tickers) < 2:
            rows.append({**row, "status": "unavailable", "reason": "book_or_scores_unavailable",
                         "tc_diagonal": None})
            continue
        positions = state["positions"]
        row["holding_state_sha256"] = state["state_sha256"]
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
        equity = float(state["cash"]) + sum(
            float(quantity) * holding_marks[ticker]
            for ticker, quantity in positions.items()
        )
        if equity <= 0:
            rows.append({**row, "status": "unavailable", "reason": "book_equity_invalid",
                         "tc_diagonal": None})
            continue
        weights, missing_held = [], 0.0
        for ticker in tickers:
            quantity = positions.get(ticker)
            weights.append(0.0 if quantity is None else
                           float(quantity) * holding_marks[ticker] / equity)
        for ticker, quantity in positions.items():
            if ticker not in {"SPY", *tickers}:
                missing_held += float(quantity) * holding_marks[ticker] / equity
        if sigma is None:
            rows.append({**row, "status": "unavailable", "reason": "active_risk_unavailable",
                         "tc_diagonal": None})
            continue
        ic = trailing["values"].get(policy)
        positive_ic = isinstance(ic, (int, float)) and np.isfinite(ic) and ic > 0
        score_vector = [scores[ticker][policy] for ticker in tickers]
        sigma_vector = [sigma[ticker] for ticker in tickers]
        primary = transfer_coefficient(
            score_vector, sigma_vector, weights, positive_ic=positive_ic,
            held_unscored_weight=missing_held,
        )
        spy_position = positions.get("SPY")
        spy_weight = (0.0 if spy_position is None else
                      float(spy_position) * holding_marks["SPY"] / equity)
        cash_weight = float(state["cash"]) / equity
        implied = implied_active_weights(score_vector, sigma_vector, positive_ic=positive_ic)
        diagnostic = weight_pearson_tc(
            [*implied, 0.0], [*weights, spy_weight - 1.0, cash_weight],
        )
        rows.append({
            **row, **primary,
            "tc_weight_pearson": None if missing_held > 1e-15 else diagnostic,
            "stock_weight": float(sum(weights)), "spy_weight": spy_weight,
            "cash_weight": cash_weight, "trailing_ic": ic,
            "ex_ante_tracking_error": float(np.sqrt(
                max(0.0, 252 * np.asarray(weights) @ risk["covariance"]
                    @ np.asarray(weights)),
            )),
        })
    payload = {
        "schema_version": 1, "signal_date": signal_date.isoformat(),
        "holding_date": holding_date.isoformat(),
        "information_cutoff_at": cutoff.replace(tzinfo=timezone.utc).isoformat(),
        "score_sha256": score_sha, "risk_sha256": risk_sha,
        "score_input_sha256": score_snapshot["input_snapshot_sha256"],
        "ic_status": trailing["status"], "ic_reason": trailing["reason"],
        "ic_source_sha256": trailing["source_sha256"],
        "ic_origin_dates": trailing.get("origin_dates", []),
        "books": rows, "execution_authority": "none",
    }
    return {**payload, "transfer_sha256": canonical_sha256(payload)}


def validate_payload(payload: dict) -> dict:
    """Verify a production TC artifact before persistence or report use."""
    if not isinstance(payload, dict) or payload.get("transfer_sha256") != canonical_sha256({
            key: value for key, value in payload.items() if key != "transfer_sha256"}):
        raise ValueError("P16 transfer hash differs")
    try:
        cutoff = datetime.fromisoformat(payload["information_cutoff_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("P16 transfer cutoff is invalid") from exc
    if (payload.get("schema_version") != 1 or cutoff.tzinfo is None
            or payload.get("execution_authority") != "none"
            or any(not isinstance(payload.get(field), str)
                   or len(payload[field]) != 64 for field in (
                       "score_sha256", "risk_sha256", "score_input_sha256",
                       "ic_source_sha256"))
            or payload.get("ic_status") not in {"available", "unavailable"}
            or (payload.get("ic_status") == "available"
                and len(payload.get("ic_origin_dates", [])) != 60)):
        raise ValueError("P16 transfer artifact provenance differs")
    validate_transfer_rows(payload.get("books"), list(BOOK_POLICIES))
    return payload
