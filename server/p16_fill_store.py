"""Append-only manifests and observations for inert P16 fill measurement."""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from engine import p16_fill_capture
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from sim import nyse

_NEW_YORK = ZoneInfo("America/New_York")
_SHA = re.compile(r"[0-9a-f]{64}")


def _timestamp(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def init_schema(con) -> None:
    con.execute("""CREATE TABLE IF NOT EXISTS p16_fill_manifests (
        session_date DATE PRIMARY KEY, policy_id VARCHAR NOT NULL,
        selected_at TIMESTAMP NOT NULL, order_cutoff_at TIMESTAMP NOT NULL,
        universe_sha256 VARCHAR NOT NULL, population_count INTEGER NOT NULL,
        sample_json VARCHAR NOT NULL, sample_sha256 VARCHAR NOT NULL UNIQUE,
        orders_json VARCHAR NOT NULL, orders_sha256 VARCHAR NOT NULL,
        targets_json VARCHAR NOT NULL, targets_sha256 VARCHAR NOT NULL,
        manifest_sha256 VARCHAR NOT NULL UNIQUE)""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_fill_source_captures (
        capture_sha256 VARCHAR PRIMARY KEY, session_date DATE NOT NULL,
        security_id VARCHAR NOT NULL, source VARCHAR NOT NULL,
        source_version VARCHAR NOT NULL, receipt_sha256 VARCHAR NOT NULL,
        attempted_at TIMESTAMP NOT NULL, status VARCHAR NOT NULL,
        reason VARCHAR, payload_json VARCHAR NOT NULL, payload_sha256 VARCHAR NOT NULL,
        UNIQUE(session_date,security_id,source,receipt_sha256))""")
    con.execute("""CREATE TABLE IF NOT EXISTS p16_fill_measurements (
        measurement_sha256 VARCHAR PRIMARY KEY, session_date DATE NOT NULL,
        security_id VARCHAR NOT NULL, source VARCHAR NOT NULL,
        liquidity_tier VARCHAR NOT NULL, median_dollar_volume DOUBLE,
        bar_set_sha256 VARCHAR NOT NULL, measured_at TIMESTAMP NOT NULL,
        payload_json VARCHAR NOT NULL,
        UNIQUE(session_date,security_id,source,bar_set_sha256))""")


def candidate_snapshot_as_of(con, session_date: date, *, selected_at: datetime) -> dict:
    """Read the latest completed P15 universe that was actually known by 09:20 ET."""
    cutoff = _timestamp(selected_at, "fill selection time")
    expected = p16_fill_capture.selection_cutoff(session_date).replace(tzinfo=None)
    if cutoff != expected or not table_exists(con, "p15_scoring_runs"):
        return {"status": "unavailable", "reason": "candidate_snapshot_unavailable"}
    row = con.execute(
        "SELECT market_date,universe_payload,universe_sha256,completed_at "
        "FROM p15_scoring_runs WHERE status='completed' AND market_date<? "
        "AND completed_at IS NOT NULL AND completed_at<=? "
        "ORDER BY market_date DESC,completed_at DESC,id DESC LIMIT 1",
        [session_date, cutoff],
    ).fetchone()
    if row is None:
        return {"status": "unavailable", "reason": "candidate_snapshot_unavailable"}
    try:
        universe = json.loads(row[1])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("retained P15 universe is invalid") from exc
    if canonical_sha256(universe) != row[2] or not isinstance(universe.get("candidates"), list):
        raise ValueError("retained P15 universe identity differs")
    return {
        "status": "available", "market_date": row[0].isoformat(),
        "known_at": row[3].replace(tzinfo=timezone.utc).isoformat(),
        "universe_sha256": row[2], "candidates": universe["candidates"],
    }


def targeted_orders(con, session_date: date, *, known_at: datetime) -> list[dict]:
    """Snapshot every P15 intent targeting this open, including non-fill states."""
    cutoff = _timestamp(known_at, "order cutoff")
    if not table_exists(con, "p15_order_intents"):
        return []
    cursor = con.execute(
        "SELECT id,decision_id,portfolio_id,ticker,side,qty,signal_date,order_role,"
        "priority,signal_close,entry_atr,limit_px,status,reason,sim_order_id,created_at "
        "FROM p15_order_intents WHERE created_at<=? ORDER BY id", [cutoff],
    )
    fields = [item[0] for item in cursor.description]
    rows = []
    for values in cursor.fetchall():
        row = dict(zip(fields, values, strict=True))
        if nyse.next_session(row["signal_date"]) != session_date:
            continue
        rows.append({
            key: value.isoformat() if isinstance(value, (date, datetime)) else value
            for key, value in row.items()
        })
    return rows


def build_manifest(con, session_date: date) -> dict:
    """Freeze sample at 09:20 and order union at 09:30 New York time."""
    selected_at = p16_fill_capture.selection_cutoff(session_date)
    order_cutoff = datetime.combine(session_date, time(9, 30), _NEW_YORK).astimezone(timezone.utc)
    snapshot = candidate_snapshot_as_of(con, session_date, selected_at=selected_at)
    if snapshot["status"] != "available":
        body = {
            "policy_id": p16_fill_capture.POLICY_ID,
            "session_date": session_date.isoformat(), "status": "unavailable",
            "reason": snapshot["reason"], "selected_at": selected_at.isoformat(),
            "order_cutoff_at": order_cutoff.isoformat(),
        }
        return {**body, "manifest_sha256": canonical_sha256(body)}
    sample = p16_fill_capture.select_sample(session_date, snapshot["candidates"])
    orders = targeted_orders(con, session_date, known_at=order_cutoff)
    order_ids = [f"p15:{row['id']}" for row in orders]
    targets = sorted(set(sample["selected_security_ids"]) | {"SPY"}
                     | {row["ticker"] for row in orders})
    body = {
        "policy_id": p16_fill_capture.POLICY_ID,
        "session_date": session_date.isoformat(), "status": "ready",
        "selected_at": selected_at.isoformat(), "order_cutoff_at": order_cutoff.isoformat(),
        "universe_sha256": snapshot["universe_sha256"], "sample": sample,
        "order_ids": order_ids, "orders": orders, "targets": targets,
    }
    return {**body, "manifest_sha256": canonical_sha256(body)}


def record_manifest(con, manifest: dict) -> str:
    expected = canonical_sha256({
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    })
    if manifest.get("status") != "ready" or manifest.get("manifest_sha256") != expected:
        raise ValueError("fill manifest is unavailable or invalid")
    sample, orders, targets = manifest["sample"], manifest["orders"], manifest["targets"]
    sample_sha, orders_sha, targets_sha = (
        canonical_sha256(sample), canonical_sha256(orders), canonical_sha256(targets))
    day = date.fromisoformat(manifest["session_date"])
    row = con.execute(
        "SELECT manifest_sha256 FROM p16_fill_manifests WHERE session_date=?", [day],
    ).fetchone()
    if row is not None:
        if row[0] != expected:
            raise ValueError("fill manifest replay differs")
        return expected
    con.execute("INSERT INTO p16_fill_manifests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", [
        day, manifest["policy_id"], _timestamp(
            datetime.fromisoformat(manifest["selected_at"]), "fill selection time"),
        _timestamp(datetime.fromisoformat(manifest["order_cutoff_at"]), "order cutoff"),
        manifest["universe_sha256"], sample["population_count"], _json(sample),
        sample_sha, _json(orders), orders_sha, _json(targets), targets_sha, expected,
    ])
    return expected


def record_source_capture(
    con, *, session_date: date, security_id: str, receipt_sha256: str,
    attempted_at: datetime, payload: dict, reason: str | None = None,
) -> str:
    """Retain one exact-source normalized attempt; later retries are new receipts."""
    if _SHA.fullmatch(receipt_sha256 or "") is None or not isinstance(payload, dict):
        raise ValueError("fill source capture identity is invalid")
    source, version = payload.get("source"), payload.get("source_version")
    status = payload.get("status")
    if not all(isinstance(value, str) and value for value in (security_id, source, version, status)):
        raise ValueError("fill source capture contract is invalid")
    payload_sha = canonical_sha256(payload)
    identity = {
        "session_date": session_date.isoformat(), "security_id": security_id,
        "source": source, "source_version": version, "receipt_sha256": receipt_sha256,
        "attempted_at": _timestamp(attempted_at, "capture attempt").isoformat(),
        "status": status, "reason": reason, "payload_sha256": payload_sha,
    }
    capture_sha = canonical_sha256(identity)
    row = con.execute(
        "SELECT payload_sha256 FROM p16_fill_source_captures WHERE capture_sha256=?",
        [capture_sha],
    ).fetchone()
    if row is not None:
        if row[0] != payload_sha:
            raise ValueError("fill source capture replay differs")
        return capture_sha
    con.execute("INSERT INTO p16_fill_source_captures VALUES (?,?,?,?,?,?,?,?,?,?,?)", [
        capture_sha, session_date, security_id, source, version, receipt_sha256,
        _timestamp(attempted_at, "capture attempt"), status, reason,
        _json(payload), payload_sha,
    ])
    return capture_sha


def record_measurement(
    con, *, session_date: date, security_id: str, source: str,
    median_dollar_volume: float | None, bar_set_sha256: str,
    measured_at: datetime, measurement: dict,
) -> str:
    if measurement.get("measurement_sha256") != canonical_sha256({
            key: value for key, value in measurement.items()
            if key != "measurement_sha256"}):
        raise ValueError("fill measurement identity differs")
    if _SHA.fullmatch(bar_set_sha256 or "") is None:
        raise ValueError("fill bar-set identity is invalid")
    mdv = None if median_dollar_volume is None else float(median_dollar_volume)
    if mdv is not None and (not math.isfinite(mdv) or mdv <= 0):
        raise ValueError("fill liquidity is invalid")
    digest = measurement["measurement_sha256"]
    row = con.execute(
        "SELECT payload_json FROM p16_fill_measurements WHERE measurement_sha256=?", [digest],
    ).fetchone()
    encoded = _json(measurement)
    if row is not None:
        if row[0] != encoded:
            raise ValueError("fill measurement replay differs")
        return digest
    con.execute("INSERT INTO p16_fill_measurements VALUES (?,?,?,?,?,?,?,?,?)", [
        digest, session_date, security_id, source,
        p16_fill_capture.liquidity_tier(mdv), mdv, bar_set_sha256,
        _timestamp(measured_at, "measurement time"), encoded,
    ])
    return digest
