"""Shared setup for walk-forward recovery and evidence tests."""

import json
from datetime import date, datetime

from engine.lib.data_quality import quality_class
from engine.lib.provenance import canonical_sha256
from farm.walkforward import controls as walkforward_controls
from farm.walkforward import protocol as walkforward_protocol_definition
from farm.walkforward.runner import summarize as summarize_folds
from sim import execution


def walkforward_snapshot(tables=None):
    tables = {"prices": {"rows": 1}} if tables is None else tables
    return {"sha256": canonical_sha256(tables), "tables": tables}


def walkforward_protocol(anchor="2026-09-04", *, train_months=24):
    anchor_date = date.fromisoformat(anchor)
    folds = walkforward_protocol_definition.make_folds(
        anchor_date,
        train_months=train_months,
        n_folds=walkforward_protocol_definition.N_FOLDS,
    )
    return walkforward_protocol_definition.protocol_dict(
        anchor_date,
        folds,
        train_months=train_months,
    )


def walkforward_fold(geometry, *, initial_cash=39_000.0, clamped=False):
    first_session = date.fromisoformat(geometry["train_start"])
    split_session = date.fromisoformat(geometry["split_date"])
    last_session = date.fromisoformat(geometry["validate_end"])
    train_years = (split_session - first_session).days / 365.25
    validate_years = (last_session - split_session).days / 365.25
    train_start_equity = float(initial_cash)
    train_end_equity = train_start_equity * 1.1
    validate_end_equity = train_end_equity * 1.1
    return {
        **geometry,
        "status": "ok",
        "train_start_clamped_to_data_floor": clamped,
        "sessions": 3,
        "first_session": first_session.isoformat(),
        "split_session": split_session.isoformat(),
        "last_session": last_session.isoformat(),
        "n_fills": 2,
        "n_validate_fills": 1,
        "train": {
            "n_sessions": 2,
            "start_date": first_session.isoformat(),
            "end_date": split_session.isoformat(),
            "equity_start": train_start_equity,
            "equity_end": train_end_equity,
            "return_base": train_start_equity,
            "total_return": train_end_equity / train_start_equity - 1.0,
            "years": train_years,
            "cagr": (train_end_equity / train_start_equity) ** (1.0 / train_years) - 1.0,
            "vol_ann": 0.1,
            "sharpe": 1.0,
            "sharpe_ex_bil": 0.9,
            "bil_coverage": 1.0,
            "max_dd": -0.05,
            "worst_month": -0.02,
        },
        "validate": {
            "n_sessions": 2,
            "start_date": split_session.isoformat(),
            "end_date": last_session.isoformat(),
            "equity_start": train_end_equity,
            "equity_end": validate_end_equity,
            "return_base": train_end_equity,
            "total_return": validate_end_equity / train_end_equity - 1.0,
            "years": validate_years,
            "cagr": (validate_end_equity / train_end_equity) ** (1.0 / validate_years) - 1.0,
            "vol_ann": 0.1,
            "sharpe": 1.0,
            "sharpe_ex_bil": 0.9,
            "bil_coverage": 1.0,
            "max_dd": -0.05,
            "worst_month": -0.02,
        },
        "validate_monthly_equity": [
            [geometry["split_date"][:7], train_end_equity],
            [geometry["validate_end"][:7], validate_end_equity],
        ],
    }


def failed_weekly_status():
    return {
        "name": "run_weekly_walkforward",
        "started_at": "2026-09-06T06:00:01Z",
        "status": "failed",
        "log": "walkforward.log",
        "finished_at": "2026-09-06T06:00:02Z",
        "stage": "enqueue",
        "exit_code": 1,
    }


def setup_walkforward_recovery(con, states=("done", "done")):
    required_tickers = ("SPY", "XLK", "XLF", "XLE", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE")
    con.execute(
        "INSERT INTO prices (ticker, date, open, high, low, close, volume) "
        "SELECT ticker, DATE '1993-05-20' + i::INTEGER, 100, 100, 100, 100, 1000000 "
        "FROM UNNEST(?) AS required(ticker), range(253) AS sessions(i)",
        [list(required_tickers)],
    )
    for portfolio_id, strategy in (("spy", "spy_benchmark"), ("sector", "sector_momentum")):
        con.execute(
            "INSERT INTO portfolios "
            "(id,name,strategy,config,created,active,cash,initial_cash,execution_profile) "
            "VALUES (?,?,?,?,DATE '2026-09-01',TRUE,39000,39000,'baseline_v1')",
            [portfolio_id, portfolio_id, strategy, "{}"],
        )
    con.execute(
        "CREATE TABLE jobs (id INTEGER, kind VARCHAR, params VARCHAR, state VARCHAR, "
        "progress VARCHAR, last_error VARCHAR, created_at TIMESTAMP, updated_at TIMESTAMP)"
    )
    for i, (portfolio_id, state) in enumerate(zip(("spy", "sector"), states, strict=False)):
        con.execute(
            "INSERT INTO jobs VALUES (?, 'walkforward', ?, ?, ?, NULL, ?, ?)",
            [
                i + 1,
                json.dumps({"config_id": portfolio_id}),
                state,
                "complete" if state == "done" else "started",
                datetime(2026, 9, 7, 7, 0, i),
                datetime(2026, 9, 7, 8, 0, i),
            ],
        )


def write_walkforward_result(
    path,
    config_id,
    source="a" * 64,
    anchor="2026-09-04",
    **override,
):
    strategy = {"spy": "spy_benchmark", "sector": "sector_momentum"}.get(
        config_id, config_id
    )
    protocol = override.get("protocol", walkforward_protocol(anchor))
    initial_cash = float(override.get("initial_cash", 39_000.0))
    folds = [walkforward_fold(fold, initial_cash=initial_cash) for fold in protocol["folds"]]
    payload = {
        "config_id": config_id,
        "strategy": strategy,
        "config": {},
        "config_sha256": canonical_sha256({}),
        "source_sha256": source,
        "protocol": protocol,
        "fill_model": "v4",
        "data_quality_class": quality_class(strategy),
        "data_floor": "1994-01-27",
        "universe_policy": "all",
        "initial_cash": initial_cash,
        "execution_profile": execution.resolve_profile("baseline_v1").as_dict(),
        "data_snapshot": walkforward_snapshot(),
        "comparison": walkforward_controls.declaration(config_id),
        "dropped_folds": [],
        "folds": folds,
        "summary": summarize_folds(folds),
    }
    payload.update(override)
    path.write_text(json.dumps(payload))
