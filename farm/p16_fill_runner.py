"""Explicit, unscheduled runner for inert P16 fill-measurement captures."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

from engine import p16_fill_capture
from farm import p16_fill_calibration
from server import p16_fill_store, p16_quote_capture

_NEW_YORK = ZoneInfo("America/New_York")
BarFetch = Callable[[str, date, datetime], dict]


def capture_attempts(session_date: date) -> list[datetime]:
    return [datetime.combine(session_date, value, _NEW_YORK).astimezone(timezone.utc)
            for value in (time(9, 46), time(10), time(12))]


def quote_times(session_date: date) -> list[datetime]:
    return [datetime.combine(session_date, value, _NEW_YORK).astimezone(timezone.utc)
            for value in (time(9, 31, 5), time(9, 34, 5))]


def _jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _receipt(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        _jsonable(payload), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _failed_bar_set(
    session_date: date, source: str, source_version: str,
) -> dict:
    body = {
        "source": source, "source_version": source_version,
        "venue": None, "provider": None, "currency": "USD",
        "adjustment": None, "resolution": "5m", "regular_session": True,
        "status": "capture_failed",
        "missing_starts": [value.isoformat()
                           for value in p16_fill_capture.expected_bar_starts(session_date)],
        "missing_reasons": ["bar_capture_failed"], "bars": [], "metrics": None,
    }
    return {**body, "bar_set_sha256": _receipt(body)}


def _bar_quality(payload: dict) -> tuple[bool, bool, int]:
    return (payload.get("status") == "complete", payload.get("metrics") is not None,
            len(payload.get("bars") or []))


def _capture_bars(
    con, session_date: date, security_id: str, source: str, source_version: str,
    fetch: BarFetch, attempts: list[datetime],
) -> dict:
    """Persist every attempt and return the first complete or best incomplete set."""
    best = _failed_bar_set(session_date, source, source_version)
    for attempted_at in attempts:
        try:
            captured = fetch(security_id, session_date, attempted_at)
            raw = captured.get("payload", captured)
            if raw.get("source") != source or raw.get("source_version") != source_version:
                raise ValueError("fill bar source identity differs")
            payload = p16_fill_capture.normalize_bars(session_date, raw)
            receipt = captured.get("receipt_sha256") or _receipt(raw)
            reason = None if payload["status"] == "complete" else payload["status"]
        except (OSError, RuntimeError, ValueError, TypeError):
            payload = _failed_bar_set(session_date, source, source_version)
            receipt = hashlib.sha256(
                f"{session_date}|{security_id}|{source}|{attempted_at.isoformat()}|failed"
                .encode()).hexdigest()
            reason = "bar_capture_failed"
        p16_fill_store.record_source_capture(
            con, session_date=session_date, security_id=security_id,
            receipt_sha256=receipt, attempted_at=attempted_at,
            payload=payload, reason=reason)
        if payload["status"] == "complete":
            return payload
        if _bar_quality(payload) > _bar_quality(best):
            best = payload
    return best


def run_capture(
    con, session_date: date, *, bar_sources: dict[str, tuple[str, BarFetch]],
    quote_fetch: p16_quote_capture.Fetch, quote_source: str, quote_source_version: str,
    primary_source: str, generated_at: datetime, registration: dict | None = None,
    report_dir: Path | None = None, attempts: list[datetime] | None = None,
) -> dict:
    """Run selection through report writing. Callers supply every transport and clock."""
    p16_fill_store.init_schema(con)
    manifest = p16_fill_store.build_manifest(con, session_date)
    if manifest["status"] != "ready":
        return {"status": "unavailable", "reason": manifest["reason"], "observations": []}
    p16_fill_store.record_manifest(con, manifest)
    selected = manifest["sample"]["selected_security_ids"]
    quote_rows: dict[str, list[dict]] = {security_id: [] for security_id in selected}
    for window_index, observed_at in enumerate(quote_times(session_date)):
        rows = p16_quote_capture.collect_window(
            session_date, selected, window_index, observed_at=observed_at,
            fetch=quote_fetch, source=quote_source, source_version=quote_source_version)
        for row in rows:
            p16_fill_store.record_source_capture(
                con, session_date=session_date, security_id=row["security_id"],
                receipt_sha256=row["receipt_sha256"], attempted_at=observed_at,
                payload=row["payload"], reason=row["reason"])
            quote_rows[row["security_id"]].append(row["payload"]["quote"])
    cutoff = p16_fill_capture.selection_cutoff(session_date)
    liquidity = {security_id: p16_fill_store.liquidity_as_of(
        con, security_id, session_date, information_cutoff_at=cutoff)
        for security_id in manifest["targets"]}
    captured: dict[str, dict[str, dict]] = {}
    for security_id in manifest["targets"]:
        for source, (source_version, fetch) in bar_sources.items():
            payload = _capture_bars(
                con, session_date, security_id, source, source_version, fetch,
                attempts or capture_attempts(session_date))
            captured.setdefault(security_id, {})[source] = payload
    for security_id, sources in captured.items():
        for source, bar_set in sources.items():
            secondary = next((item["metrics"]["first_open"]
                              for other, item in sources.items() if other != source
                              and item.get("metrics") is not None), None)
            measurement = p16_fill_capture.measure_symbol_day(
                session_date=session_date, security_id=security_id, source=source,
                bar_set=bar_set, quote_rows=quote_rows.get(security_id, []),
                secondary_open=secondary)
            mdv = liquidity[security_id]["median_dollar_volume_60d"]
            p16_fill_store.record_measurement(
                con, session_date=session_date, security_id=security_id, source=source,
                median_dollar_volume=mdv, bar_set_sha256=bar_set["bar_set_sha256"],
                measured_at=generated_at, measurement=measurement)
    observations = p16_fill_store.observations_for_session(
        con, session_date, primary_source=primary_source)
    result = {"status": "complete", "manifest_sha256": manifest["manifest_sha256"],
              "selected_count": len(selected), "observation_count": len(observations),
              "observations": observations,
              "order_outcomes": p16_fill_store.order_outcomes(con, session_date)}
    if registration is not None and report_dir is not None:
        days = [row[0] for row in con.execute(
            "SELECT session_date FROM p16_fill_manifests ORDER BY session_date").fetchall()]
        all_observations = [row for day in days for row in
                            p16_fill_store.observations_for_session(
                                con, day, primary_source=primary_source)]
        report = p16_fill_calibration.build_report(
            registration, all_observations, generated_at=generated_at.isoformat())
        paths = p16_fill_calibration.write_report(report, report_dir)
        result.update({"report": report, "report_paths": [str(path) for path in paths]})
    return result
