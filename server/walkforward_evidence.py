"""Validate published walk-forward evidence against live registrations."""

from __future__ import annotations

import math
from pathlib import Path

import duckdb

from engine.lib import leverage
from engine.lib.data_quality import quality_class
from engine.lib.provenance import canonical_sha256, runtime_source_hash
from engine.lib.settings import DATA_DIR
from engine.lib.util import table_exists
from farm.backtest.replay import DEFAULT_REQUIRED, REQUIRED, REQUIRED_LOOKBACK
from farm.walkforward import controls as walkforward_controls
from farm.walkforward import protocol as walkforward_protocol
from server import walkforward_cohort
from server.json_utils import loads_object
from sim import execution, portfolio


def _required_data_floors(
    con: duckdb.DuckDBPyConnection, strategies: set[str]
) -> dict[str, object] | None:
    """Resolve every required ticker's 253rd bar once for this projection."""
    tickers = sorted(
        {ticker for strategy in strategies for ticker in REQUIRED.get(strategy, DEFAULT_REQUIRED)}
    )
    if not tickers:
        return {}
    try:
        return dict(
            con.execute(
                "SELECT ticker, date FROM ("
                "  SELECT ticker, date, ROW_NUMBER() OVER ("
                "    PARTITION BY ticker ORDER BY date"
                "  ) AS row_number FROM prices WHERE ticker = ANY(?)"
                ") WHERE row_number = ?",
                [tickers, REQUIRED_LOOKBACK + 1],
            ).fetchall()
        )
    except duckdb.Error:
        return None


def _data_floor(strategy: str, floors_by_ticker: dict[str, object] | None) -> str:
    required = REQUIRED.get(strategy, DEFAULT_REQUIRED)
    if floors_by_ticker is None:
        raise ValueError("required price history is unavailable")
    missing = next((ticker for ticker in required if ticker not in floors_by_ticker), None)
    if missing is not None:
        raise ValueError(f"insufficient required price history for {missing}")
    return max(floors_by_ticker[ticker] for ticker in required).isoformat()


def _universe_policy() -> str:
    try:
        return leverage.resolve_policy(None)
    except SystemExit as exc:
        raise ValueError("invalid universe policy") from exc


def _registration(row: tuple, floors_by_ticker: dict[str, object] | None) -> dict:
    portfolio_id, strategy, raw_config, initial_cash, profile_id = row
    config = loads_object(raw_config)
    if (
        isinstance(initial_cash, bool)
        or not isinstance(initial_cash, (int, float))
        or not math.isfinite(initial_cash)
        or initial_cash <= 0
    ):
        raise ValueError("invalid initial cash")
    profile = execution.resolve_profile(profile_id).as_dict()
    return {
        "strategy": strategy,
        "fill_model": portfolio.FILL_MODEL_VERSION,
        "universe_policy": _universe_policy(),
        "data_quality_class": quality_class(strategy),
        "config_sha256": canonical_sha256(config),
        "initial_cash": float(initial_cash),
        "execution_profile_sha256": canonical_sha256(profile),
        "comparison": walkforward_controls.declaration(portfolio_id),
        "planned_fold_count": walkforward_protocol.N_FOLDS,
        "protocol_windows": {
            "train_months": walkforward_protocol.TRAIN_MONTHS,
            "validate_months": walkforward_protocol.VALIDATE_MONTHS,
            "step_months": walkforward_protocol.STEP_MONTHS,
        },
        "data_floor": _data_floor(strategy, floors_by_ticker),
    }


def _eligible_walkforward_configs(
    con: duckdb.DuckDBPyConnection,
) -> tuple[dict[str, dict], list[str]]:
    """Return the live identity of each active, historically replayable book."""
    if not table_exists(con, "portfolios"):
        return {}, []
    rows = con.execute(
        "SELECT id, strategy, config, initial_cash, execution_profile "
        "FROM portfolios WHERE active ORDER BY id"
    ).fetchall()
    eligible = [row for row in rows if walkforward_protocol.excluded_reason(row[0], row[1]) is None]
    floors_by_ticker = _required_data_floors(con, {row[1] for row in eligible})
    registrations: dict[str, dict] = {}
    invalid: list[str] = []
    for row in eligible:
        portfolio_id = row[0]
        try:
            registrations[portfolio_id] = _registration(row, floors_by_ticker)
        except (duckdb.Error, TypeError, ValueError):
            invalid.append(str(portfolio_id))
    return registrations, invalid


def _overlay_recovery(result: dict, recovery_status: dict | None) -> None:
    if (
        recovery_status is None
        or recovery_status.get("status") != "updating"
        or result["status"] not in {"stale-source", "incomplete", "mixed-cohort"}
    ):
        return
    artifact_status = result["status"]
    result.update(
        status="updating",
        artifact_status=artifact_status,
        refresh_job_count=recovery_status.get(
            "refresh_job_count", recovery_status.get("recovery_job_count")
        ),
        refresh_job_counts=recovery_status.get(
            "refresh_job_counts", recovery_status.get("recovery_job_counts")
        ),
    )


def _source_identity() -> tuple[str, int] | None:
    try:
        return runtime_source_hash()
    except OSError:
        return None


def _invalid_source_result(expected: set[str], invalid_registrations: list[str]) -> dict:
    return walkforward_cohort.result_payload(
        status="invalid",
        current_sha256=None,
        current_file_count=None,
        cohort=None,
        signature_count=0,
        expected=expected,
        scan=walkforward_cohort.empty_scan(),
        invalid_registrations=invalid_registrations,
    )


def _cohort_state(scan: dict) -> tuple[dict, dict | None]:
    signatures = {key: signature for signature, key in scan["rows"].values()}
    cohort = next(iter(signatures.values())) if len(signatures) == 1 else None
    return signatures, cohort


def _evidence_result(
    *,
    scan: dict,
    expected: set[str],
    invalid_registrations: list[str],
    current_sha256: str,
    current_file_count: int,
) -> dict:
    signatures, cohort = _cohort_state(scan)
    status = walkforward_cohort.status(
        scan=scan,
        invalid_registrations=invalid_registrations,
        missing=sorted(expected - scan["rows"].keys()),
        signatures=signatures,
        cohort=cohort,
        current_sha256=current_sha256,
    )
    return walkforward_cohort.result_payload(
        status=status,
        current_sha256=current_sha256,
        current_file_count=current_file_count,
        cohort=cohort,
        signature_count=len(signatures),
        expected=expected,
        scan=scan,
        invalid_registrations=invalid_registrations,
    )


def evidence_status(
    con: duckdb.DuckDBPyConnection,
    results_dir: Path | None = None,
    *,
    recovery_status: dict | None = None,
) -> dict:
    """Compare the complete active result cohort with the current source tree.

    Driver success says the queue ran; this says whether its published evidence
    was produced by the code currently deployed. Historical files remain
    immutable and visible, but stale or mixed cohorts cannot masquerade as
    current research evidence.
    """
    registrations, invalid_registrations = _eligible_walkforward_configs(con)
    expected = set(registrations) | set(invalid_registrations)
    source_identity = _source_identity()
    if source_identity is None:
        return _invalid_source_result(expected, invalid_registrations)
    current_sha256, current_file_count = source_identity
    root = results_dir or DATA_DIR / "reports" / "walkforward" / "results"
    scan = walkforward_cohort.scan_results(root, registrations)
    result = _evidence_result(
        scan=scan,
        expected=expected,
        invalid_registrations=invalid_registrations,
        current_sha256=current_sha256,
        current_file_count=current_file_count,
    )
    _overlay_recovery(result, recovery_status)
    return result
