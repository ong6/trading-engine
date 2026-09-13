"""Compose the read-only operational and prospective-evidence `/meta` payload."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

import duckdb

from engine.lib.util import table_exists

from . import (
    driver_monitor,
    e1_forward_status,
    exposure_monitor,
    forward_contracts,
    friday_postflight,
    liquidity_monitor,
    market_health,
    market_read_models,
    meta_snapshot,
    miner_monitor,
    nightly_monitor,
    queue_monitor,
    scheduler_monitor,
    sector_forward_status,
    source_control,
    sweep_monitor,
    walkforward_evidence,
    walkforward_recovery,
    xs_forward_status,
)
from .read_model_utils import (
    require_public_nonempty_string,
    require_public_nonnegative_integer,
    require_public_ticker,
)

log = logging.getLogger(__name__)
T = TypeVar("T")
PRICE_QUARANTINE_LIMIT = 100
PRICE_QUARANTINE_DETAIL_MAX_CHARS = 1_024
PUBLIC_META_FIELDS = (
    "meta",
    "meta_file",
    "latest_prices_date",
    "freshness_days",
    "market_freshness",
    "price_verification",
    "queue",
    "nightly_evidence",
    "miner_evidence",
    "sweep_evidence",
    "liquidity_evidence",
    "stale_exposure",
    "price_quarantines",
    "price_quarantines_limit",
    "price_quarantines_matching_count",
    "price_quarantines_truncated",
    "scheduler",
    "friday_postflight",
    "source_control",
    "nightly",
    "weekly_verify",
    "weekly_sweeps",
    "weekly_liquidity",
    "weekly_walkforward",
    "walkforward_evidence",
    "forward_review",
    "xs_forward_review",
    "e1_forward",
)
PUBLIC_DRIVER_FIELDS = (
    "status",
    "name",
    "started_at",
    "finished_at",
    "exit_code",
    "stage",
    "reason",
    "lock_held",
    "expected_at",
    "expected_name",
    "previous_status",
    "refresh_job_count",
    "refresh_job_counts",
    "refresh_started_at",
    "refreshed_at",
    "recovery_job_count",
    "recovery_job_counts",
    "recovery_started_at",
    "recovered_at",
)


def _optional(name: str, project: Callable[[], T], fallback: T) -> T:
    """Keep one optional monitor defect from hiding all operational status."""
    try:
        return project()
    except Exception:  # Optional monitors must fail closed in isolation.
        log.exception("optional /meta projection failed: %s", name)
        return fallback


def _public_snapshot(meta_json: dict, meta_file: dict) -> tuple[dict, dict]:
    """Hide producer bookkeeping and local paths from the public projection."""
    status = {"status": meta_file["status"]}
    if "reason" in meta_file:
        status["reason"] = meta_file["reason"]
    if status["status"] != "ok":
        return {}, status
    try:
        return meta_snapshot.public_summary(meta_json), status
    except (TypeError, ValueError) as exc:
        log.warning("metadata snapshot summary validation failed", exc_info=exc)
        return {}, {"status": "invalid", "reason": "malformed-summary"}


def _public_driver(status: dict | None) -> dict | None:
    """Allowlist reviewed driver fields after internal reconciliation."""
    if status is None:
        return None
    return {field: status[field] for field in PUBLIC_DRIVER_FIELDS if field in status}


def _public_meta(payload: dict) -> dict:
    """Allowlist reviewed top-level fields after composing internal projections."""
    return {field: payload[field] for field in PUBLIC_META_FIELDS}


def _public_walkforward_status(status: dict) -> dict:
    """Sanitize the driver member while preserving sparse failure isolation."""
    public = dict(status)
    if "weekly_walkforward" in public:
        public["weekly_walkforward"] = _public_driver(public["weekly_walkforward"])
    return public


def _validate_price_quarantine_row(row: dict) -> None:
    require_public_ticker(row["ticker"])
    reason = require_public_nonempty_string(row["reason"], "price quarantine reason")
    evidence = require_public_nonempty_string(row["evidence"], "price quarantine evidence")
    if len(reason) > PRICE_QUARANTINE_DETAIL_MAX_CHARS:
        raise ValueError("public price quarantine reason is oversized")
    if len(evidence) > PRICE_QUARANTINE_DETAIL_MAX_CHARS:
        raise ValueError("public price quarantine evidence is oversized")
    if type(row["confirmed_at"]) is not datetime:
        raise ValueError("public price quarantine confirmation time is invalid")
    if type(row["detail_truncated"]) is not bool:
        raise ValueError("public price quarantine truncation state is invalid")
    if row["detail_truncated"] and not (
        len(reason) == PRICE_QUARANTINE_DETAIL_MAX_CHARS
        or len(evidence) == PRICE_QUARANTINE_DETAIL_MAX_CHARS
    ):
        raise ValueError("public price quarantine truncation state does not reconcile")


def _price_quarantines(con: duckdb.DuckDBPyConnection) -> dict:
    """Return bounded active-quarantine details with an exact complete count."""
    if not table_exists(con, "price_quarantine"):
        quarantine_rows = []
        matching_count = 0
    else:
        cursor = con.execute(
            "WITH matching AS ("
            "SELECT CAST(ticker AS VARCHAR) AS ticker, "
            "LEFT(CAST(reason AS VARCHAR), ?) AS reason, "
            "LEFT(CAST(evidence AS VARCHAR), ?) AS evidence, confirmed_at, "
            "LENGTH(CAST(reason AS VARCHAR)) > ? "
            "OR LENGTH(CAST(evidence AS VARCHAR)) > ? AS detail_truncated, "
            "COUNT(*) OVER () AS _matching_count FROM price_quarantine "
            "WHERE status = 'active'"
            ") SELECT * FROM matching ORDER BY ticker LIMIT ?",
            [
                PRICE_QUARANTINE_DETAIL_MAX_CHARS,
                PRICE_QUARANTINE_DETAIL_MAX_CHARS,
                PRICE_QUARANTINE_DETAIL_MAX_CHARS,
                PRICE_QUARANTINE_DETAIL_MAX_CHARS,
                PRICE_QUARANTINE_LIMIT,
            ],
        )
        columns = [column[0] for column in cursor.description]
        quarantine_rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        matching_count = (
            require_public_nonnegative_integer(quarantine_rows[0].pop("_matching_count"))
            if quarantine_rows
            else 0
        )
        for row in quarantine_rows[1:]:
            row.pop("_matching_count")
        for row in quarantine_rows:
            _validate_price_quarantine_row(row)
            confirmed_at = row["confirmed_at"]
            row["confirmed_at"] = confirmed_at.replace(tzinfo=timezone.utc).isoformat()
    return {
        "price_quarantines": quarantine_rows,
        "price_quarantines_limit": PRICE_QUARANTINE_LIMIT,
        "price_quarantines_matching_count": matching_count,
        "price_quarantines_truncated": matching_count > PRICE_QUARANTINE_LIMIT,
    }


def _host_status(data_dir: Path) -> dict:
    return {
        "scheduler": _optional(
            "scheduler",
            scheduler_monitor.status,
            scheduler_monitor.invalid_status("projection-error"),
        ),
        "friday_postflight": _optional(
            "friday_postflight",
            lambda: friday_postflight.status(data_dir.parent / "logs" / "friday-postflight.json"),
            friday_postflight.invalid_status("projection-error"),
        ),
        "source_control": _optional(
            "source_control",
            source_control.status,
            source_control.invalid_status(),
        ),
    }


def _nightly_evidence(
    con: duckdb.DuckDBPyConnection,
    meta_json: dict,
    drivers: dict,
    latest,
) -> dict:
    invalid = {"status": "invalid", "reason": "projection-error"}

    def nightly_status() -> dict:
        status = nightly_monitor.evidence_status(meta_json, drivers["nightly"], con, latest)
        for field in (
            "screened",
            "passing",
            "new_today",
            "active_portfolios",
            "portfolios_with_equity",
        ):
            if field in status:
                require_public_nonnegative_integer(status[field])
        return status

    return {
        "nightly_evidence": _optional(
            "nightly_evidence",
            nightly_status,
            invalid,
        ),
        "miner_evidence": _optional(
            "miner_evidence",
            lambda: miner_monitor.evidence_status(meta_json, con),
            invalid,
        ),
        "sweep_evidence": _optional(
            "sweep_evidence",
            lambda: sweep_monitor.evidence_status(con),
            invalid,
        ),
        "liquidity_evidence": _optional(
            "liquidity_evidence",
            lambda: liquidity_monitor.evidence_status(
                meta_json, drivers["weekly_liquidity"], con, latest
            ),
            invalid,
        ),
    }


def _walkforward_status(con: duckdb.DuckDBPyConnection, drivers: dict) -> dict:
    weekly = _optional(
        "weekly_walkforward",
        lambda: walkforward_recovery.reconcile_driver_status(drivers["weekly_walkforward"], con),
        drivers["weekly_walkforward"],
    )
    evidence = _optional(
        "walkforward_evidence",
        lambda: walkforward_evidence.evidence_status(con, recovery_status=weekly),
        {"status": "invalid", "reason": "projection-error"},
    )
    return {"weekly_walkforward": weekly, "walkforward_evidence": evidence}


def _forward_status(con: duckdb.DuckDBPyConnection, data_dir: Path, latest) -> dict:
    invalid = forward_contracts.invalid_status()
    forward_dir = data_dir / "reports" / "forward"
    return {
        "forward_review": _optional(
            "forward_review",
            lambda: sector_forward_status.status(forward_dir / "sector_momentum.json", latest, con),
            invalid,
        ),
        "xs_forward_review": _optional(
            "xs_forward_review",
            lambda: xs_forward_status.status(forward_dir / "xs_momentum_12_1.json", latest, con),
            invalid,
        ),
        "e1_forward": _optional(
            "e1_forward",
            lambda: e1_forward_status.status(con, latest),
            invalid,
        ),
    }


def project(con: duckdb.DuckDBPyConnection, *, meta_path: Path, data_dir: Path) -> dict:
    """Build one coherent `/meta` response from read-only monitor projections."""
    meta_json, meta_file = meta_snapshot.load(meta_path)
    public_meta, public_meta_file = _public_snapshot(meta_json, meta_file)
    drivers = driver_monitor.driver_statuses()
    latest = market_read_models.latest_prices_date(con)
    market_freshness = market_health.freshness(latest)
    internal = {
        "meta": public_meta,
        "meta_file": public_meta_file,
        "latest_prices_date": latest,
        # Compatibility field for existing consumers; market_freshness is the
        # authoritative health signal because calendar days include closures.
        "freshness_days": market_freshness["calendar_days"],
        "market_freshness": market_freshness,
        "price_verification": market_health.price_verification(
            meta_json, latest, drivers["nightly"]
        ),
        "queue": queue_monitor.status(con),
        **_nightly_evidence(con, meta_json, drivers, latest),
        "stale_exposure": exposure_monitor.status(con, latest),
        **_price_quarantines(con),
        **_host_status(data_dir),
        "nightly": _public_driver(drivers["nightly"]),
        "weekly_verify": _public_driver(drivers["weekly_verify"]),
        "weekly_sweeps": _public_driver(drivers["weekly_sweeps"]),
        "weekly_liquidity": _public_driver(drivers["weekly_liquidity"]),
        **_public_walkforward_status(_walkforward_status(con, drivers)),
        **_forward_status(con, data_dir, latest),
    }
    return _public_meta(internal)
