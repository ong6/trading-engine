"""Inert P16 construction calibration and copied-store dry-run entry point."""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import numpy as np

from engine.lib import db
from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from engine.p16_features import session_dates
from engine.p16_order_planner import plan_mandatory_exit_orders, plan_whole_share_orders
from farm import p16_calibration, p16_eval_inputs, p16_optimizer, p16_risk
from server import p16_book_store, p16_transfer
from sim import execution, p16_books
from tools.backup_database import _copy_database


def _latest_origin(con) -> date | None:
    try:
        return con.execute(
            "SELECT MAX(market_date) FROM agent_evaluation_traces "
            "WHERE policy_id='p15-scoring-v1' AND terminal_status='completed'"
        ).fetchone()[0]
    except Exception:  # noqa: BLE001 - absent preactivation schema is an explicit state
        return None


def _calibration_dates(con, through: date, cutoff: datetime) -> list[date]:
    """Use every retained completed preactivation origin through the requested date."""
    try:
        rows = con.execute(
            "SELECT DISTINCT market_date FROM agent_evaluation_traces "
            "WHERE policy_id='p15-scoring-v1' AND terminal_status='completed' "
            "AND market_date<=? AND completed_at<=? ORDER BY market_date",
            [through, cutoff.replace(tzinfo=None)],
        ).fetchall()
    except duckdb.Error:
        return [through]
    return [row[0] for row in rows] or [through]


def _sector_rows(con, tickers: list[str], market_date: date, cutoff: datetime) -> list[str]:
    placeholders = ",".join("?" for _ in tickers)
    rows = con.execute(
        "SELECT ticker,sector FROM fundamentals "
        f"WHERE ticker IN ({placeholders}) AND as_of<=? AND fetched_at IS NOT NULL "
        "AND fetched_at<=? QUALIFY ROW_NUMBER() OVER (PARTITION BY ticker "
        "ORDER BY as_of DESC,fetched_at DESC)=1",
        [*tickers, market_date, cutoff.replace(tzinfo=None)],
    ).fetchall()
    mapped = {ticker: sector for ticker, sector in rows}
    return [
        mapped[ticker].strip().lower()
        if isinstance(mapped.get(ticker), str) and mapped[ticker].strip() else "unknown"
        for ticker in tickers
    ]


def _snapshot(
    con, origin: dict, cutoff: datetime, *, held_tickers: set[str] | None = None,
) -> dict:
    held = held_tickers or set()
    all_decisions = [*origin["decision_rows"], *origin.get("held_decision_rows", [])]
    decisions = [
        row for row in all_decisions
        if row.get("champion_score_available") is True
        and (row.get("tradeable") is not False or row["ticker"] in held)
    ]
    tickers = sorted(row["ticker"] for row in decisions)
    if not held <= set(tickers):
        raise ValueError("held_name_missing_score")
    if len(tickers) < 2:
        raise ValueError("fewer_than_two_common_scores")
    by_ticker = {row["ticker"]: row for row in decisions}
    market_date = date.fromisoformat(origin["market_date"])
    sessions = session_dates(market_date, 121)
    names = [*tickers, "SPY"]
    placeholders = ",".join("?" for _ in names)
    rows = con.execute(
        "SELECT ticker,date,close,volume FROM prices "
        f"WHERE ticker IN ({placeholders}) AND date BETWEEN ? AND ? "
        f"AND fetched_at IS NOT NULL AND fetched_at<=? AND close>0 AND {REAL_BAR_SQL} "
        "ORDER BY ticker,date",
        [*names, sessions[0], sessions[-1], cutoff.replace(tzinfo=None)],
    ).fetchall()
    history = {ticker: {} for ticker in names}
    for ticker, session, close, volume in rows:
        if session in set(sessions):
            history[ticker][session] = (float(close), float(volume))
    if any(set(history[ticker]) != set(sessions) for ticker in names):
        raise ValueError("complete_120_session_risk_history_unavailable")
    spy_closes = np.asarray([history["SPY"][session][0] for session in sessions])
    spy_returns = spy_closes[1:] / spy_closes[:-1] - 1
    stock_returns = np.column_stack([
        np.asarray([history[ticker][session][0] for session in sessions])[1:]
        / np.asarray([history[ticker][session][0] for session in sessions])[:-1] - 1
        for ticker in tickers
    ])
    sectors = _sector_rows(con, tickers, market_date, cutoff)
    champion = [by_ticker[ticker]["champion_score"] for ticker in tickers]
    rule = [by_ticker[ticker]["rule_score"] for ticker in tickers]
    risk = {
        "champion": p16_risk.calibration_risk_and_alpha(
            stock_returns, spy_returns, champion,
        ),
        "rule": p16_risk.calibration_risk_and_alpha(stock_returns, spy_returns, rule),
    }
    medians = [float(np.median([
        history[ticker][session][0] * history[ticker][session][1]
        for session in sessions[-60:]
    ])) for ticker in tickers]
    cost_rows = []
    for ticker, median in zip(tickers, medians, strict=True):
        reference_px = history[ticker][sessions[-1]][0]
        for side in ("buy", "sell"):
            components = execution.cost_components(
                "baseline_v1", side=side, qty=1_000 / reference_px,
                open_px=reference_px, median_dollar_volume=median,
            )
            cost_rows.append({
                "market_date": market_date.isoformat(), "ticker": ticker,
                "role": "stock", "side": side, "reference_notional": 1_000.0,
                "qty": 1_000 / reference_px, "open_px": reference_px,
                "median_dollar_volume": median, "execution_profile": "baseline_v1",
                **components,
            })
    spy_median = float(np.median([
        history["SPY"][session][0] * history["SPY"][session][1]
        for session in sessions[-60:]
    ]))
    spy_reference_px = history["SPY"][sessions[-1]][0]
    for side in ("buy", "sell"):
        components = execution.cost_components(
            "baseline_v1", side=side, qty=10_000 / spy_reference_px,
            open_px=spy_reference_px, median_dollar_volume=spy_median,
        )
        cost_rows.append({
            "market_date": market_date.isoformat(), "ticker": "SPY",
            "role": "core_financing", "side": side,
            "reference_notional": 10_000.0, "qty": 10_000 / spy_reference_px,
            "open_px": spy_reference_px, "median_dollar_volume": spy_median,
            "execution_profile": "baseline_v1", **components,
        })
    cost = max(row["total_bps"] for row in cost_rows) / 10_000
    risk_sha = canonical_sha256({
        "market_date": market_date.isoformat(), "tickers": tickers,
        "sessions": [value.isoformat() for value in sessions],
        "covariance_h5": risk["champion"]["covariance_h5"].tolist(),
        "beta": risk["champion"]["beta"].tolist(), "sectors": sectors,
    })
    score_sha = canonical_sha256({"champion": champion, "rule": rule, "tickers": tickers})
    manifest_body = {
        "market_date": market_date.isoformat(),
        "scoring_information_cutoff_at": cutoff.astimezone(timezone.utc).isoformat(),
        "sessions": [value.isoformat() for value in sessions],
        "tickers": tickers, "sectors": sectors,
        "scores": {"champion": champion, "rule": rule},
        "solver_inputs": {
            policy: {
                "alpha_h5": values["alpha_h5"].tolist(),
                "covariance_h5": values["covariance_h5"].tolist(),
                "beta": values["beta"].tolist(),
            } for policy, values in risk.items()
        },
        "risk_snapshot_sha256": risk_sha, "score_snapshot_sha256": score_sha,
        "previous_weights": [*([0.0] * len(tickers)), 1.0],
        "previous_weight_source": "initial_all_spy", "cost_rows": cost_rows,
    }
    return {
        "market_date": market_date, "tickers": tickers, "sectors": sectors,
        "risk": risk, "risk_sha256": risk_sha, "score_sha256": score_sha,
        "cost_per_turnover": cost, "cost_rows": cost_rows,
        "stock_returns": stock_returns, "spy_returns": spy_returns,
        "calibration_manifest": {
            **manifest_body, "snapshot_sha256": canonical_sha256(manifest_body),
        },
    }


def _current_book(con, book_instance_id: str, signal_date: date, tickers: list[str],
                  cutoff: datetime) -> dict:
    state = p16_transfer._state_as_of(con, book_instance_id, signal_date)
    if state is None:
        raise ValueError("book_state_unavailable")
    names = [*tickers, "SPY"]
    marks = {}
    for ticker in names:
        row = con.execute(
            f"SELECT close FROM prices WHERE ticker=? AND date=? AND fetched_at IS NOT NULL "
            f"AND fetched_at<=? AND close>0 AND {REAL_BAR_SQL}",
            [ticker, signal_date, cutoff.replace(tzinfo=None)],
        ).fetchone()
        if row is None:
            raise ValueError("decision_close_unavailable")
        marks[ticker] = float(row[0])
    positions = state["positions"]
    equity = float(state["cash"]) + sum(
        float(quantity) * marks[ticker] for ticker, quantity in positions.items()
    )
    if equity <= 0 or any(ticker not in names for ticker in positions):
        raise ValueError("book_state_unavailable")
    quantities = {ticker: float(positions.get(ticker, 0.0)) for ticker in names}
    if not positions:
        previous = np.r_[np.zeros(len(tickers)), 1.0]
    else:
        previous = np.asarray([
            quantities[ticker] * marks[ticker] / equity for ticker in names
        ])
        previous[-1] += max(0.0, float(state["cash"]) / equity)
    halted = con.execute(
        "SELECT entry_halted FROM p16_book_state WHERE book_instance_id=? "
        "AND market_date<=? AND recorded_at<=? ORDER BY market_date DESC LIMIT 1",
        [book_instance_id, signal_date, cutoff.replace(tzinfo=None)],
    ).fetchone()
    return {
        "quantities": quantities, "marks": marks, "cash": float(state["cash"]),
        "equity": equity, "previous": previous, "state_sha256": state["state_sha256"],
        "entry_halted": bool(halted and halted[0]),
    }


def _unavailable_sha(kind: str, signal_date: date, reason: str) -> str:
    return canonical_sha256({
        "kind": kind, "signal_date": signal_date.isoformat(),
        "status": "unavailable", "reason": reason,
    })


def _queue_mandatory_only(
    con, *, book_instance_id: str, logical_book_id: str, signal_date: date,
    information_cutoff_at: datetime, recorded_at: datetime, reason: str,
    risk_sha256: str, score_sha256: str, state: dict | None = None,
    exits: dict[str, str] | None = None, ic_source_sha256: str | None = None,
    risk_aversion: float, cost_per_turnover: float,
    solver_result: dict | None = None,
) -> dict:
    """Queue independent exits without manufacturing a discretionary target."""
    retained_state = state or p16_transfer._state_as_of(
        con, book_instance_id, signal_date,
    )
    if retained_state is None:
        return {
            "book_id": logical_book_id, "status": reason, "queued": 0,
            "reason": "book_state_unavailable", "mandatory_exits": {},
        }
    held = {
        ticker for ticker, quantity in retained_state["positions"].items()
        if ticker != "SPY" and float(quantity) > 0
    }
    exit_reasons = exits if exits is not None else p16_books.mandatory_exits(
        con, book_instance_id=book_instance_id, market_date=signal_date,
        information_cutoff_at=information_cutoff_at, held_tickers=held,
    )
    plan = plan_mandatory_exit_orders(retained_state["positions"], exit_reasons)
    result = solver_result or {
        "status": "input_unavailable", "reason": reason,
        "sector_coverage": None, "sector_status": None,
    }
    ic_source = ic_source_sha256 or _unavailable_sha("ic", signal_date, reason)
    with db.transaction(con):
        source_sha = p16_book_store.record_target(
            con, book_instance_id=book_instance_id, signal_date=signal_date,
            risk_snapshot_sha256=risk_sha256, score_sha256=score_sha256,
            ic_source_sha256=ic_source, risk_aversion=risk_aversion,
            cost_per_turnover=cost_per_turnover, solver_result=result,
            continuous_weights=None, banded_weights=None, rounded_plan=plan,
            recorded_at=recorded_at,
        )
        previous = con.execute(
            "SELECT state_sha256 FROM p16_book_state WHERE book_instance_id=? "
            "AND market_date<=? AND recorded_at<=? ORDER BY market_date DESC LIMIT 1",
            [book_instance_id, signal_date,
             information_cutoff_at.astimezone(timezone.utc).replace(tzinfo=None)],
        ).fetchone()
        p16_book_store.claim_window(
            con, book_instance_id=book_instance_id, market_date=signal_date,
            information_cutoff_at=information_cutoff_at,
            risk_sha256=risk_sha256, score_sha256=score_sha256,
            previous_state_sha256=None if previous is None else previous[0],
            target_sha256=source_sha, started_at=recorded_at,
        )
        queued = p16_books.queue_plan(
            con, book_instance_id=book_instance_id, signal_date=signal_date,
            plan=plan, limit_prices={}, source_sha256=source_sha,
            created_at=recorded_at, transactional=False,
        )
        p16_book_store.complete_window(
            con, book_instance_id=book_instance_id, market_date=signal_date,
            status="completed", reason=f"mandatory_exits_only:{reason}",
            completed_at=recorded_at,
        )
    return {
        "book_id": logical_book_id, "status": reason, "queued": queued,
        "source_sha256": source_sha, "mandatory_exits": exit_reasons,
    }


def construct_targets(
    con, *, registration_sha256: str, signal_date: date,
    information_cutoff_at: datetime, recorded_at: datetime,
) -> dict:
    """Compose retained live inputs into inert, next-open construction intents."""
    cutoff = information_cutoff_at.astimezone(timezone.utc)
    contracts = con.execute(
        "SELECT book_instance_id,logical_portfolio_id,risk_aversion,cost_per_turnover "
        "FROM p16_book_contracts WHERE registration_sha256=? "
        "ORDER BY logical_portfolio_id", [registration_sha256],
    ).fetchall()
    if len(contracts) != len(p16_book_store.LOGICAL_BOOK_IDS):
        raise p16_book_store.P16BookError("P16 construction contracts are incomplete")
    try:
        origin = p16_eval_inputs.load_origin(
            con, market_date=signal_date, report_cutoff=cutoff,
        )
        scoring_cutoff = datetime.fromisoformat(
            origin["scoring_information_cutoff_at"].replace("Z", "+00:00"),
        )
    except (ValueError, p16_eval_inputs.EvaluationInputError, duckdb.Error) as exc:
        reason = str(exc)
        results = [
            _queue_mandatory_only(
                con, book_instance_id=instance, logical_book_id=logical,
                signal_date=signal_date, information_cutoff_at=cutoff,
                recorded_at=recorded_at, reason=reason,
                risk_sha256=_unavailable_sha("risk", signal_date, reason),
                score_sha256=_unavailable_sha("score", signal_date, reason),
                risk_aversion=float(risk_aversion), cost_per_turnover=float(cost),
            ) for instance, logical, risk_aversion, cost in contracts
        ]
        return {
            "status": "input_unavailable", "reason": reason,
            "books": results, "execution_authority": "none",
        }
    held = {
        row[0] for row in con.execute(
            "SELECT DISTINCT ticker FROM sim_positions WHERE portfolio_id IN ("
            "SELECT book_instance_id FROM p16_book_contracts WHERE registration_sha256=?) "
            "AND ticker!='SPY' AND qty>0", [registration_sha256],
        ).fetchall()
    }
    trailing = p16_transfer._trailing_ics(
        con, signal_date, scoring_cutoff.astimezone(timezone.utc).replace(tzinfo=None),
    )
    if trailing["status"] != "available":
        reason = trailing["reason"]
        risk_sha = _unavailable_sha("risk_not_required", signal_date, reason)
        score_sha = origin.get("input_snapshot_sha256")
        if not isinstance(score_sha, str) or len(score_sha) != 64:
            score_sha = canonical_sha256(origin.get("decision_rows", []))
        results = [
            _queue_mandatory_only(
                con, book_instance_id=instance, logical_book_id=logical,
                signal_date=signal_date, information_cutoff_at=scoring_cutoff,
                recorded_at=recorded_at, reason=reason,
                risk_sha256=risk_sha, score_sha256=score_sha,
                ic_source_sha256=trailing["source_sha256"],
                risk_aversion=float(risk_aversion), cost_per_turnover=float(cost),
                solver_result={
                    "status": "core_collecting", "reason": reason,
                    "sector_coverage": None, "sector_status": None,
                },
            ) for instance, logical, risk_aversion, cost in contracts
        ]
        return {
            "status": "core_collecting", "reason": reason,
            "books": results, "execution_authority": "none",
        }
    try:
        snapshot = _snapshot(con, origin, scoring_cutoff, held_tickers=held)
    except (ValueError, duckdb.Error) as exc:
        reason = str(exc)
        risk_sha = _unavailable_sha("risk", signal_date, reason)
        score_sha = origin.get("input_snapshot_sha256")
        if not isinstance(score_sha, str) or len(score_sha) != 64:
            score_sha = canonical_sha256(origin.get("decision_rows", []))
        results = [
            _queue_mandatory_only(
                con, book_instance_id=instance, logical_book_id=logical,
                signal_date=signal_date, information_cutoff_at=scoring_cutoff,
                recorded_at=recorded_at, reason=reason,
                risk_sha256=risk_sha, score_sha256=score_sha,
                ic_source_sha256=trailing["source_sha256"],
                risk_aversion=float(risk_aversion), cost_per_turnover=float(cost),
            ) for instance, logical, risk_aversion, cost in contracts
        ]
        return {
            "status": "risk_unavailable", "reason": reason,
            "books": results, "execution_authority": "none",
        }
    decisions = {
        row["ticker"]: row
        for row in [*origin["decision_rows"], *origin.get("held_decision_rows", [])]
    }
    results = []
    for instance, logical, risk_aversion, cost in contracts:
        book = _current_book(con, instance, signal_date, snapshot["tickers"], scoring_cutoff)
        exits = p16_books.mandatory_exits(
            con, book_instance_id=instance, market_date=signal_date,
            information_cutoff_at=scoring_cutoff,
            held_tickers={
                ticker for ticker, quantity in book["quantities"].items()
                if ticker != "SPY" and quantity > 0
            },
        )
        policy = "champion" if logical == "p16_construct_ai" else "rule"
        scores = [float(decisions[ticker][f"{policy}_score"])
                  for ticker in snapshot["tickers"]]
        try:
            risk = p16_risk.risk_and_alpha(
                snapshot["stock_returns"], snapshot["spy_returns"], scores,
                trailing["vectors"][policy],
            )
        except (ValueError, RuntimeError) as exc:
            results.append(_queue_mandatory_only(
                con, book_instance_id=instance, logical_book_id=logical,
                signal_date=signal_date, information_cutoff_at=scoring_cutoff,
                recorded_at=recorded_at, reason=str(exc),
                risk_sha256=snapshot["risk_sha256"],
                score_sha256=snapshot["score_sha256"],
                ic_source_sha256=trailing["source_sha256"],
                risk_aversion=float(risk_aversion), cost_per_turnover=float(cost),
                state={"positions": {
                    ticker: quantity for ticker, quantity in book["quantities"].items()
                    if quantity > 0
                }, "state_sha256": book["state_sha256"]}, exits=exits,
            ))
            continue
        gates = {
            ticker: ("eligible" if decisions[ticker].get("tradeable") is True
                     else decisions[ticker].get("entry_gate_reason") or "unavailable")
            for ticker in snapshot["tickers"]
        }
        upper_limits = []
        for index, ticker in enumerate(snapshot["tickers"]):
            if ticker in exits:
                upper_limits.append(0.0)
            elif gates[ticker] == "eligible" and not book["entry_halted"]:
                upper_limits.append(0.1)
            else:
                upper_limits.append(min(0.1, float(book["previous"][index])))
        try:
            solved = p16_optimizer.solve(
                risk["alpha_h5"], risk["covariance_h5"], risk["beta"],
                snapshot["sectors"], book["previous"],
                risk_aversion=float(risk_aversion), cost=float(cost),
                upper_limits=upper_limits,
                fixed_weights={snapshot["tickers"].index(ticker): 0.0 for ticker in exits},
            )
        except (ValueError, RuntimeError) as exc:
            solved = {
                "status": "input_unavailable" if isinstance(exc, ValueError)
                else "not_converged",
                "reason": str(exc), "sector_coverage": None, "sector_status": None,
            }
        target_weights = solved.get("weights")
        if target_weights is None:
            results.append(_queue_mandatory_only(
                con, book_instance_id=instance, logical_book_id=logical,
                signal_date=signal_date, information_cutoff_at=scoring_cutoff,
                recorded_at=recorded_at, reason=solved["status"],
                risk_sha256=snapshot["risk_sha256"],
                score_sha256=snapshot["score_sha256"],
                ic_source_sha256=trailing["source_sha256"],
                risk_aversion=float(risk_aversion), cost_per_turnover=float(cost),
                solver_result=solved, state={
                    "positions": {
                        ticker: quantity for ticker, quantity in book["quantities"].items()
                        if quantity > 0
                    },
                    "state_sha256": book["state_sha256"],
                }, exits=exits,
            ))
            continue
        entry_atr = {
            ticker: float(decisions[ticker]["atr_14"])
            for ticker in snapshot["tickers"]
            if isinstance(decisions[ticker].get("atr_14"), (int, float))
            and decisions[ticker]["atr_14"] > 0
        }
        if set(entry_atr) != set(snapshot["tickers"]):
            results.append(_queue_mandatory_only(
                con, book_instance_id=instance, logical_book_id=logical,
                signal_date=signal_date, information_cutoff_at=scoring_cutoff,
                recorded_at=recorded_at, reason="entry_atr_unavailable",
                risk_sha256=snapshot["risk_sha256"],
                score_sha256=snapshot["score_sha256"],
                ic_source_sha256=trailing["source_sha256"],
                risk_aversion=float(risk_aversion), cost_per_turnover=float(cost),
                state={"positions": {
                    ticker: quantity for ticker, quantity in book["quantities"].items()
                    if quantity > 0
                }, "state_sha256": book["state_sha256"]}, exits=exits,
            ))
            continue
        limits = {
            ticker: book["marks"][ticker] * (
                1 + max(0.015, 0.5 * entry_atr[ticker] / book["marks"][ticker])
            ) for ticker in snapshot["tickers"]
        }
        plan = plan_whole_share_orders(
            tickers=snapshot["tickers"], target_weights=target_weights,
            current_quantities=book["quantities"],
            operational_prices={**limits, "SPY": book["marks"]["SPY"]},
            cash=book["cash"], equity=book["equity"], beta=risk["beta"],
            sectors=snapshot["sectors"], alpha=risk["alpha_h5"],
            entry_atr=entry_atr, mandatory_exits=exits,
        )
        with db.transaction(con):
            target_sha = p16_book_store.record_target(
                con, book_instance_id=instance, signal_date=signal_date,
                risk_snapshot_sha256=snapshot["risk_sha256"],
                score_sha256=snapshot["score_sha256"],
                ic_source_sha256=trailing["source_sha256"],
                risk_aversion=float(risk_aversion), cost_per_turnover=float(cost),
                solver_result=solved,
                continuous_weights=solved["continuous_weights"].tolist(),
                banded_weights=target_weights.tolist(), rounded_plan=plan,
                recorded_at=recorded_at,
            )
            previous_state = con.execute(
                "SELECT state_sha256 FROM p16_book_state WHERE book_instance_id=? "
                "AND market_date<=? AND recorded_at<=? ORDER BY market_date DESC LIMIT 1",
                [instance, signal_date, scoring_cutoff.replace(tzinfo=None)],
            ).fetchone()
            p16_book_store.claim_window(
                con, book_instance_id=instance, market_date=signal_date,
                information_cutoff_at=scoring_cutoff,
                risk_sha256=snapshot["risk_sha256"], score_sha256=snapshot["score_sha256"],
                previous_state_sha256=None if previous_state is None else previous_state[0],
                target_sha256=target_sha, started_at=recorded_at,
            )
            queued = p16_books.queue_plan(
                con, book_instance_id=instance, signal_date=signal_date, plan=plan,
                limit_prices=limits, source_sha256=target_sha, created_at=recorded_at,
                entry_gates=gates, transactional=False,
            )
            p16_book_store.complete_window(
                con, book_instance_id=instance, market_date=signal_date,
                status="completed", reason=None, completed_at=recorded_at,
            )
        results.append({
            "book_id": logical, "status": plan["status"], "queued": queued,
            "target_sha256": target_sha, "mandatory_exits": exits,
        })
    return {
        "status": "completed", "books": results,
        "risk_sha256": snapshot["risk_sha256"],
        "score_sha256": snapshot["score_sha256"],
        "ic_source_sha256": trailing["source_sha256"], "execution_authority": "none",
    }


def calibrate(con, *, market_date: date, generated_at: datetime) -> dict:
    """Calibrate across all retained real snapshots or explain why unavailable."""
    snapshots = []
    try:
        for origin_date in _calibration_dates(con, market_date, generated_at):
            origin = p16_eval_inputs.load_origin(
                con, market_date=origin_date, report_cutoff=generated_at,
            )
            scoring_cutoff = datetime.fromisoformat(
                origin["scoring_information_cutoff_at"].replace("Z", "+00:00"),
            )
            snapshots.append(_snapshot(con, origin, scoring_cutoff))
    except (ValueError, p16_eval_inputs.EvaluationInputError, duckdb.Error) as exc:
        return {
            "status": "calibration_unavailable", "reason": str(exc),
            "selected_lambda": None, "books": [
                {"book_id": book_id, "status": "core_collecting"}
                for book_id in p16_book_store.LOGICAL_BOOK_IDS
            ],
        }
    frozen_cost = max(row["cost_per_turnover"] for row in snapshots)
    cases = []
    for snapshot in snapshots:
        for book_id, policy in zip(
            p16_book_store.LOGICAL_BOOK_IDS, ("champion", "rule"), strict=True,
        ):
            values = snapshot["risk"][policy]
            cases.append({
                "book_id": book_id, "alpha": values["alpha_h5"],
                "covariance": values["covariance_h5"], "beta": values["beta"],
                "sectors": snapshot["sectors"],
                "previous": np.r_[np.zeros(len(snapshot["tickers"])), 1.0],
                "cost": frozen_cost, "band": 0.005,
                "horizon_sessions": 5,
                "snapshot_sha256": snapshot["calibration_manifest"]["snapshot_sha256"],
                "snapshot_date": snapshot["market_date"].isoformat(),
                "risk_snapshot_sha256": snapshot["risk_sha256"],
                "score_snapshot_sha256": snapshot["score_sha256"],
            })
    result = p16_calibration.calibrate_lambda(cases)
    books = []
    if result["selected_lambda"] is not None:
        for book_id in p16_book_store.LOGICAL_BOOK_IDS:
            solves = []
            for case in (row for row in cases if row["book_id"] == book_id):
                solve_args = {
                    key: value for key, value in case.items()
                    if key not in p16_calibration.CASE_METADATA
                }
                solves.append(p16_optimizer.solve(
                    **solve_args, risk_aversion=result["selected_lambda"],
                ))
            books.append({
                "book_id": book_id, "status": "calibrated",
                "snapshot_count": len(solves),
                "median_tracking_error": float(np.median([
                    row["tracking_error"] for row in solves
                ])),
            })
    else:
        books = [{"book_id": book_id, "status": "core_collecting"}
                 for book_id in p16_book_store.LOGICAL_BOOK_IDS]
    body = {
        "schema_version": 1, **result, "books": books,
        "snapshot_dates": [row["market_date"].isoformat() for row in snapshots],
        "risk_snapshot_sha256s": [row["risk_sha256"] for row in snapshots],
        "score_snapshot_sha256s": [row["score_sha256"] for row in snapshots],
        "snapshots": [row["calibration_manifest"] for row in snapshots],
        "cost_per_turnover": frozen_cost,
        "ic_source": "registered_assumption", "assumed_ic": p16_risk.CALIBRATION_IC,
        "observed_ic_count": 0,
        "solver_failure_policy": "drop_lambda_on_any_case_failure",
        "execution_authority": "none",
    }
    return {**body, "calibration_sha256": canonical_sha256(body)}


def dry_run(
    database: Path = DEFAULT_DB, *, market_date: date | None = None,
    generated_at: datetime | None = None,
    registration_sha256: str | None = None,
    lock_path: Path = REPO_ROOT / ".nightly.lock",
) -> dict:
    """Run only against a transactional copy; no contract or evidence is activated."""
    generated = generated_at or datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="trading-engine-p16-construction-") as directory:
        copied = Path(directory) / "market.duckdb"
        with advisory_file_lock(lock_path):
            _copy_database(database, copied)
        con = db.connect(copied, wait_s=0)
        try:
            selected_date = market_date or _latest_origin(con)
            if selected_date is None:
                result = {
                    "status": "calibration_unavailable", "reason": "no_valid_p15_origin",
                    "selected_lambda": None, "books": [
                        {"book_id": book_id, "status": "core_collecting"}
                        for book_id in p16_book_store.LOGICAL_BOOK_IDS
                    ],
                }
            else:
                result = calibrate(con, market_date=selected_date, generated_at=generated)
            retained_calibration = None
            book_instances = []
            construction = None
            if registration_sha256 is not None and result["status"] == "calibrated":
                retained_calibration = p16_book_store.record_calibration(
                    con, registration_sha256=registration_sha256,
                    payload=result, recorded_at=generated,
                )
                book_instances = p16_book_store.initialize_contracts(
                    con, registration_sha256=registration_sha256,
                    activation_date=None, calibration_sha256=retained_calibration,
                    created_at=generated,
                )
                construction = construct_targets(
                    con, registration_sha256=registration_sha256,
                    signal_date=selected_date, information_cutoff_at=generated,
                    recorded_at=generated,
                )
        finally:
            con.close()
    body = {
        "schema_version": 1, "status": "completed", "dry_run": True,
        "source_database_modified": False,
        "market_date": None if market_date is None and selected_date is None
        else selected_date.isoformat(),
        "generated_at": generated.astimezone(timezone.utc).isoformat(),
        "calibration": result,
        "retained_calibration_sha256": retained_calibration,
        "book_instances": book_instances, "construction": construction,
        "execution_authority": "none",
    }
    return {**body, "dry_run_sha256": canonical_sha256(body)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--market-date", type=date.fromisoformat)
    parser.add_argument("--registration-sha256")
    args = parser.parse_args()
    print(json.dumps(dry_run(
        args.database, market_date=args.market_date,
        registration_sha256=args.registration_sha256,
    ), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
