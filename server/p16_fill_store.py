"""Append-only manifests and observations for inert P16 fill measurement."""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from engine import p16_fill_capture
from engine.lib import db
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
    """Snapshot immutable intent inputs; mutable outcomes are joined after capture."""
    cutoff = _timestamp(known_at, "order cutoff")
    if not table_exists(con, "p15_order_intents"):
        return []
    cursor = con.execute(
        "SELECT id,decision_id,portfolio_id,ticker,side,qty,signal_date,order_role,"
        "priority,signal_close,entry_atr,limit_px,created_at "
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


def order_outcomes(con, session_date: date) -> list[dict]:
    """Join mutable order outcomes to a frozen manifest without changing its identity."""
    if not table_exists(con, "p16_fill_manifests"):
        return []
    retained = con.execute(
        "SELECT orders_json FROM p16_fill_manifests WHERE session_date=?", [session_date],
    ).fetchone()
    if retained is None or not table_exists(con, "p15_order_intents"):
        return []
    ids = [row["id"] for row in json.loads(retained[0])]
    if not ids:
        return []
    cursor = con.execute(
        "SELECT id,status,reason,sim_order_id FROM p15_order_intents "
        f"WHERE id IN ({','.join('?' for _ in ids)}) ORDER BY id", ids,
    )
    fields = [item[0] for item in cursor.description]
    return [dict(zip(fields, values, strict=True)) for values in cursor.fetchall()]


def liquidity_as_of(
    con, security_id: str, session_date: date, *, information_cutoff_at: datetime,
) -> dict:
    """Compute 60-session median dollar volume using only rows known by selection."""
    cutoff = _timestamp(information_cutoff_at, "liquidity cutoff")
    if cutoff > p16_fill_capture.selection_cutoff(session_date).replace(tzinfo=None):
        raise ValueError("fill liquidity cutoff is after selection")
    if not table_exists(con, "prices"):
        return {"status": "unavailable", "reason": "liquidity_history_unavailable",
                "valid_sessions": 0, "median_dollar_volume_60d": None}
    rows = con.execute(
        "SELECT date,close,volume,source,fetched_at FROM prices WHERE ticker=? AND date<? "
        f"AND fetched_at IS NOT NULL AND fetched_at<=? AND {db.REAL_BAR_SQL} "
        "ORDER BY date DESC LIMIT 60", [security_id, session_date, cutoff],
    ).fetchall()
    evidence = [{"date": row[0].isoformat(), "close": row[1], "volume": row[2],
                 "source": row[3], "fetched_at": row[4].replace(
                     tzinfo=timezone.utc).isoformat()} for row in rows]
    values = [float(row[1]) * int(row[2]) for row in rows]
    if len(values) < 20 or any(not math.isfinite(value) or value <= 0 for value in values):
        return {"status": "unavailable", "reason": "liquidity_history_insufficient",
                "valid_sessions": len(values), "median_dollar_volume_60d": None,
                "price_rows_sha256": canonical_sha256(evidence)}
    values.sort()
    middle = len(values) // 2
    median = values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2
    return {"status": "available", "valid_sessions": len(values),
            "median_dollar_volume_60d": median,
            "price_rows_sha256": canonical_sha256(evidence)}


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
    if (measurement.get("session_date") != session_date.isoformat()
            or measurement.get("security_id") != security_id
            or measurement.get("source") != source):
        raise ValueError("fill measurement row identity differs")
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


def observations_for_session(
    con, session_date: date, *, primary_source: str,
) -> list[dict]:
    """Project one row per sampled name; the first valid source capture wins."""
    retained = con.execute(
        "SELECT sample_json FROM p16_fill_manifests WHERE session_date=?", [session_date],
    ).fetchone()
    if retained is None:
        return []
    sample = json.loads(retained[0])
    cursor = con.execute(
        "SELECT security_id,source,liquidity_tier,median_dollar_volume,measured_at,payload_json "
        "FROM p16_fill_measurements WHERE session_date=? "
        "ORDER BY measured_at,measurement_sha256", [session_date],
    )
    grouped: dict[str, dict[str, list[tuple]]] = {}
    for security_id, source, tier, mdv, measured_at, payload in cursor.fetchall():
        grouped.setdefault(security_id, {}).setdefault(source, []).append(
            (tier, mdv, measured_at, json.loads(payload)))
    observations = []
    for security_id in sample["selected_security_ids"]:
        sources = grouped.get(security_id, {})
        chosen = {}
        for source, rows in sources.items():
            chosen[source] = next(
                (row for row in rows if row[3].get("bar_status") == "complete"), rows[0])
        primary = chosen.get(primary_source)
        missing = []
        if primary is None:
            missing.append("primary_measurement_unavailable")
            payload, tier, mdv = {}, "unknown", None
        else:
            tier, mdv, _, payload = primary
            if payload.get("bar_status") != "complete":
                missing.append(f"bar_{payload.get('bar_status', 'unavailable')}")
            if payload.get("quote_target_bp") is None:
                statuses = payload.get("quote_statuses") or ["unavailable"]
                missing.extend(f"quote_{status}" for status in statuses)
        secondary = next((row for source, row in chosen.items()
                          if source != primary_source and row[3].get("first_open") is not None), None)
        first_open = payload.get("first_open")
        cross_gap = None if first_open is None or secondary is None else \
            10_000 * (first_open / secondary[3]["first_open"] - 1)
        if cross_gap is None:
            missing.append("cross_source_open_unavailable")
        if tier == "unknown":
            missing.append("liquidity_unknown")
        observations.append({
            "sample_id": sample["sample_id"], "session_date": session_date.isoformat(),
            "security_id": security_id, "source": primary_source,
            "liquidity_tier": tier, "median_dollar_volume": mdv,
            "quote_target_bp": payload.get("quote_target_bp"),
            "half_range_proxy_bp": payload.get("half_range_proxy_bp"),
            "hlc3_gap_bp": payload.get("hlc3_gap_bp"),
            "cross_source_open_gap_bp": cross_gap,
            "missing_reasons": sorted(set(missing)),
        })
    return observations
