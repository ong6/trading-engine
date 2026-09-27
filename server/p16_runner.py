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
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import DEFAULT_DB, REPO_ROOT
from engine.p16_features import session_dates
from farm import p16_calibration, p16_eval_inputs, p16_optimizer, p16_risk
from server import p16_book_store
from sim import execution
from tools.backup_database import _copy_database


def _latest_origin(con) -> date | None:
    try:
        return con.execute(
            "SELECT MAX(market_date) FROM agent_evaluation_traces "
            "WHERE policy_id='p15-scoring-v1' AND terminal_status='completed'"
        ).fetchone()[0]
    except Exception:  # noqa: BLE001 - absent preactivation schema is an explicit state
        return None


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


def _snapshot(con, origin: dict, cutoff: datetime) -> dict:
    decisions = [row for row in origin["decision_rows"]
                 if row.get("champion_score_available") is True]
    tickers = sorted(row["ticker"] for row in decisions)
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
        "AND fetched_at IS NOT NULL AND fetched_at<=? AND close>0 AND volume>0 "
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
    costs = [execution.cost_components(
        "baseline_v1", side="buy", qty=1_000 / history[ticker][sessions[-1]][0],
        open_px=history[ticker][sessions[-1]][0], median_dollar_volume=median,
    )["total_bps"] / 10_000 for ticker, median in zip(tickers, medians, strict=True)]
    spy_median = float(np.median([
        history["SPY"][session][0] * history["SPY"][session][1]
        for session in sessions[-60:]
    ]))
    costs.append(execution.cost_components(
        "baseline_v1", side="buy", qty=10_000 / history["SPY"][sessions[-1]][0],
        open_px=history["SPY"][sessions[-1]][0], median_dollar_volume=spy_median,
    )["total_bps"] / 10_000)
    cost = max(costs)
    risk_sha = canonical_sha256({
        "market_date": market_date.isoformat(), "tickers": tickers,
        "sessions": [value.isoformat() for value in sessions],
        "covariance_h5": risk["champion"]["covariance_h5"].tolist(),
        "beta": risk["champion"]["beta"].tolist(), "sectors": sectors,
    })
    score_sha = canonical_sha256({"champion": champion, "rule": rule, "tickers": tickers})
    return {
        "market_date": market_date, "tickers": tickers, "sectors": sectors,
        "risk": risk, "risk_sha256": risk_sha, "score_sha256": score_sha,
        "cost_per_turnover": cost,
    }


def calibrate(con, *, market_date: date, generated_at: datetime) -> dict:
    """Calibrate from one retained real snapshot or explain why it is unavailable."""
    try:
        origin = p16_eval_inputs.load_origin(
            con, market_date=market_date, report_cutoff=generated_at,
        )
        scoring_cutoff = datetime.fromisoformat(
            origin["scoring_information_cutoff_at"].replace("Z", "+00:00"),
        )
        snapshot = _snapshot(con, origin, scoring_cutoff)
    except (ValueError, p16_eval_inputs.EvaluationInputError, duckdb.Error) as exc:
        return {
            "status": "calibration_unavailable", "reason": str(exc),
            "selected_lambda": None, "books": [
                {"book_id": book_id, "status": "core_collecting"}
                for book_id in p16_book_store.LOGICAL_BOOK_IDS
            ],
        }
    cases = []
    for book_id, policy in zip(
        p16_book_store.LOGICAL_BOOK_IDS, ("champion", "rule"), strict=True,
    ):
        values = snapshot["risk"][policy]
        cases.append({
            "book_id": book_id, "alpha": values["alpha_h5"],
            "covariance": values["covariance_h5"], "beta": values["beta"],
            "sectors": snapshot["sectors"],
            "previous": np.r_[np.zeros(len(snapshot["tickers"])), 1.0],
            "cost": snapshot["cost_per_turnover"], "band": 0.005,
            "horizon_sessions": 5,
        })
    result = p16_calibration.calibrate_lambda(cases)
    books = []
    if result["selected_lambda"] is not None:
        for case in cases:
            solve_args = {key: value for key, value in case.items() if key != "book_id"}
            solved = p16_optimizer.solve(
                **solve_args, risk_aversion=result["selected_lambda"],
            )
            books.append({
                "book_id": case["book_id"], "status": solved["status"],
                "tracking_error": solved["tracking_error"],
                "sector_status": solved["sector_status"],
                "sector_coverage": solved["sector_coverage"],
                "weights": solved["weights"].tolist(),
            })
    else:
        books = [{"book_id": case["book_id"], "status": "core_collecting"}
                 for case in cases]
    return {
        **result, "books": books, "risk_sha256": snapshot["risk_sha256"],
        "score_sha256": snapshot["score_sha256"],
        "cost_per_turnover": snapshot["cost_per_turnover"],
        "ic_source": "registered_assumption", "assumed_ic": p16_risk.CALIBRATION_IC,
    }


def dry_run(
    database: Path = DEFAULT_DB, *, market_date: date | None = None,
    generated_at: datetime | None = None,
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
        finally:
            con.close()
    body = {
        "schema_version": 1, "status": "completed", "dry_run": True,
        "source_database_modified": False,
        "market_date": None if market_date is None and selected_date is None
        else selected_date.isoformat(),
        "generated_at": generated.astimezone(timezone.utc).isoformat(),
        "calibration": result, "execution_authority": "none",
    }
    return {**body, "dry_run_sha256": canonical_sha256(body)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", required=True)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--market-date", type=date.fromisoformat)
    args = parser.parse_args()
    print(json.dumps(dry_run(args.database, market_date=args.market_date), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
