"""Fail-closed API projection for the frozen E1 prospective experiment."""

from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb

from engine.lib.util import table_exists
from farm import experiment_runner as e1_monitor

from .forward_contracts import invalid_status
from .json_utils import load_object
from .status_validation import iso_date


def _validated_evidence(
    con: duckdb.DuckDBPyConnection,
    latest_date: date | None,
    now: datetime,
) -> tuple[dict, list[dict], int, date, dict]:
    if latest_date is None or not table_exists(con, "experiment_results"):
        raise ValueError("E1 evidence source is unavailable")
    cfg, _path = e1_monitor.load_forward_config("e1-spy-monday", None)
    phash = e1_monitor.params_hash_for(cfg)
    oos = e1_monitor.load_oos_series(con, cfg, phash)
    load_object(e1_monitor.checkpoint_path(cfg))
    e1_monitor._validate_checkpoint(cfg, phash, oos, require_current=True)
    start = iso_date(cfg["oos_start"], "E1 oos_start must be YYYY-MM-DD")
    weekday = e1_monitor.WEEKDAY[str(cfg["params"]["weekday"]).lower()]
    ticker = cfg["params"]["ticker"]
    sample_end = e1_monitor.frozen_sample_end(cfg)
    coverage_end = min(latest_date, sample_end)
    bars = e1_monitor._mondays(con, ticker, weekday, start, coverage_end)
    e1_monitor._validate_trade_date_coverage(
        con, ticker, weekday, start, bars, through=coverage_end
    )
    target = int(cfg["kill_criterion"]["n_oos_mondays"])
    expected_dates = e1_monitor.validate_oos_schedule(cfg, oos, bars, now)
    if [row["date"] for row in oos] != expected_dates:
        raise ValueError("E1 forward record is stale or has unexpected dates")
    stats = e1_monitor.series_stats([row["net"] for row in oos])
    return cfg, oos, target, sample_end, stats


def _result_status(stats: dict, target: int) -> str:
    verdict = e1_monitor.frozen_verdict(stats, target)
    if verdict is None:
        return "ACCUMULATING"
    return "KILLED" if verdict == "KILL" else "SURVIVED"


def _project(con: duckdb.DuckDBPyConnection, latest_date: date | None, now: datetime) -> dict:
    _cfg, oos, target, sample_end, stats = _validated_evidence(con, latest_date, now)
    return {
        "status": _result_status(stats, target),
        "paper_only": True,
        "automatic_action": "none",
        "checkpoint_schema_version": e1_monitor.CHECKPOINT_SCHEMA_VERSION,
        "runtime_contract_version": e1_monitor.RUNTIME_CONTRACT_VERSION,
        "runtime_contract_sha256": e1_monitor.EXPECTED_RUNTIME_CONTRACT_SHA256,
        "observations": stats["n"],
        "target_observations": target,
        "remaining_observations": target - stats["n"],
        "sample_end": sample_end.isoformat(),
        "latest_trade_date": oos[-1]["date"].isoformat() if oos else None,
        "mean_net_return": stats["mean"],
        "t_stat": stats["t"],
    }


def status(
    con: duckdb.DuckDBPyConnection,
    latest_date: date | None,
    now: datetime | None = None,
) -> dict:
    """Project the frozen E1 out-of-sample experiment or fail closed."""
    try:
        return _project(con, latest_date, now or datetime.now(timezone.utc))
    except (
        OSError,
        KeyError,
        TypeError,
        ValueError,
        RuntimeError,
        SystemExit,
        duckdb.Error,
    ):
        return invalid_status()
