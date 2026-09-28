"""Pure selection and measurement contracts for P16 execution realism."""
from __future__ import annotations

import hashlib
import math
import statistics
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from engine.lib.provenance import canonical_sha256
from sim import nyse

POLICY_ID = "p16-fills-v1"
SAMPLE_ID = "p16-fills-v1:sample:1"
SAMPLE_SIZE = 20
BAR_MINUTES = (0, 5, 10)
QUOTE_WINDOWS = ((time(9, 31), time(9, 31, 15)),
                 (time(9, 34), time(9, 34, 15)))
_NEW_YORK = ZoneInfo("America/New_York")


def _aware(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _number(value: object, field: str, *, zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0 or (not zero and result == 0):
        raise ValueError(f"{field} is invalid")
    return result


def expected_bar_starts(session_date: date) -> list[datetime]:
    if not isinstance(session_date, date) or not nyse.is_session(session_date):
        raise ValueError("fill capture date is not an exchange session")
    return [datetime.combine(session_date, time(9, 30 + minute), _NEW_YORK)
            .astimezone(timezone.utc) for minute in BAR_MINUTES]


def selection_cutoff(session_date: date) -> datetime:
    if not nyse.is_session(session_date):
        raise ValueError("fill selection date is not an exchange session")
    return datetime.combine(session_date, time(9, 20), _NEW_YORK).astimezone(timezone.utc)


def select_sample(session_date: date, candidates: list[dict]) -> dict:
    """Hash-rank security identities without observing opening data or score success."""
    if not isinstance(candidates, list):
        raise ValueError("fill candidate snapshot is invalid")
    identities = []
    for row in candidates:
        if not isinstance(row, dict):
            raise ValueError("fill candidate row is invalid")
        security_id = row.get("security_id") or row.get("ticker")
        if not isinstance(security_id, str) or not security_id.strip():
            raise ValueError("fill candidate security identity is invalid")
        identities.append(security_id.strip())
    if len(identities) != len(set(identities)):
        raise ValueError("fill candidate security identities are duplicated")
    ranked = sorted(
        identities,
        key=lambda item: (
            hashlib.sha256(
                f"{SAMPLE_ID}|{session_date.isoformat()}|{item}".encode(),
            ).hexdigest(), item,
        ),
    )
    selected = ranked[:SAMPLE_SIZE]
    population = len(ranked)
    body = {
        "sample_id": SAMPLE_ID, "session_date": session_date.isoformat(),
        "population_count": population, "sample_size": len(selected),
        "sample_shortfall": max(0, SAMPLE_SIZE - population),
        "inclusion_probability": 0.0 if population == 0
        else min(SAMPLE_SIZE, population) / population,
        "selected_security_ids": selected,
    }
    return {**body, "selection_sha256": canonical_sha256(body)}


def liquidity_tier(median_dollar_volume: float | None) -> str:
    if median_dollar_volume is None:
        return "unknown"
    value = _number(median_dollar_volume, "median dollar volume")
    if value < 5_000_000:
        return "lt_5m"
    if value < 20_000_000:
        return "5m_20m"
    if value < 50_000_000:
        return "20m_50m"
    return "gte_50m"


def normalize_bars(session_date: date, source_payload: dict) -> dict:
    """Validate exact first-three-bar slots and derive proxy-only diagnostics."""
    required = {"source", "source_version", "venue", "provider", "currency",
                "adjustment", "resolution", "regular_session", "bars"}
    if not isinstance(source_payload, dict) or not required <= set(source_payload):
        raise ValueError("fill bar source payload is invalid")
    if (source_payload["resolution"] not in {"5", "5m"}
            or source_payload["regular_session"] is not True
            or source_payload["currency"] != "USD"):
        raise ValueError("fill bar source contract differs")
    expected = expected_bar_starts(session_date)
    normalized, seen = [], set()
    for raw in source_payload["bars"]:
        if not isinstance(raw, dict):
            raise ValueError("fill bar is invalid")
        started = _aware(raw.get("start_at"), "fill bar start")
        if started not in expected or started in seen:
            raise ValueError("fill bar start is invalid or duplicated")
        seen.add(started)
        o = _number(raw.get("open"), "fill bar open")
        high = _number(raw.get("high"), "fill bar high")
        low = _number(raw.get("low"), "fill bar low")
        close = _number(raw.get("close"), "fill bar close")
        volume = _number(raw.get("volume"), "fill bar volume", zero=True)
        if low > min(o, high, close) or high < max(o, low, close):
            raise ValueError("fill bar OHLC range is invalid")
        vwap = raw.get("vwap_value")
        vwap_kind = raw.get("vwap_kind")
        if vwap is not None:
            vwap = _number(vwap, "first-bar VWAP")
            if vwap_kind not in {"reported_provider", "trade_derived"}:
                raise ValueError("first-bar VWAP kind is not independently verified")
        elif vwap_kind is not None:
            raise ValueError("first-bar VWAP kind exists without a value")
        normalized.append({
            "start_at": started.isoformat(), "open": o, "high": high,
            "low": low, "close": close, "volume": volume,
            "vwap_value": vwap, "vwap_kind": vwap_kind,
            "volume_scope": raw.get("volume_scope"),
        })
    normalized.sort(key=lambda row: row["start_at"])
    missing = [item.isoformat() for item in expected if item not in seen]
    first = next((row for row in normalized if row["start_at"] == expected[0].isoformat()), None)
    metrics = None
    if first is not None:
        first_hlc3 = (first["high"] + first["low"] + first["close"]) / 3
        metrics = {
            "first_open": first["open"],
            "reported_vwap": first["vwap_value"],
            "vwap_kind": first["vwap_kind"],
            "vwap_gap_bp": None if first["vwap_value"] is None else
                10_000 * (first["vwap_value"] / first["open"] - 1),
            "hlc3_gap_bp": 10_000 * (first_hlc3 / first["open"] - 1),
        }
    if not missing:
        hlc3 = [(row["high"] + row["low"] + row["close"]) / 3
                for row in normalized]
        weights = [row["volume"] for row in normalized]
        metrics.update({
            "half_range_proxy_bp": statistics.median(
                10_000 * (row["high"] - row["low"]) /
                (row["high"] + row["low"]) for row in normalized),
            "weighted_hlc3_proxy": None if sum(weights) == 0 else
                sum(price * weight for price, weight in zip(hlc3, weights, strict=True)) /
                sum(weights),
        })
    body = {
        "status": "complete" if not missing else "missing_slots",
        "missing_starts": missing, "bars": normalized, "metrics": metrics,
        **{key: source_payload[key] for key in required - {"bars"}},
    }
    return {**body, "bar_set_sha256": canonical_sha256(body)}


def normalize_quote(session_date: date, window_index: int, quote: dict) -> dict:
    """Validate one quote target; absent native side clocks stay unverified."""
    if window_index not in (0, 1) or not isinstance(quote, dict):
        raise ValueError("fill quote target is invalid")
    received = _aware(quote.get("received_at"), "quote receipt")
    local = received.astimezone(_NEW_YORK)
    lower, upper = QUOTE_WINDOWS[window_index]
    if local.date() != session_date or not lower <= local.time().replace(tzinfo=None) <= upper:
        return {"status": "outside_window", "window_index": window_index}
    bid = _number(quote.get("bid"), "quote bid")
    ask = _number(quote.get("ask"), "quote ask")
    if bid > ask:
        return {"status": "crossed", "window_index": window_index}
    bid_at, ask_at = quote.get("bid_at"), quote.get("ask_at")
    if bid_at is None or ask_at is None or quote.get("venue") is None:
        return {"status": "quote_target_unverified", "window_index": window_index,
                "bid": bid, "ask": ask}
    bid_at = _aware(bid_at, "bid timestamp")
    ask_at = _aware(ask_at, "ask timestamp")
    if (abs((bid_at - ask_at).total_seconds()) > 1
            or max((received - bid_at).total_seconds(),
                   (received - ask_at).total_seconds()) > 5
            or min(bid_at, ask_at) > received):
        return {"status": "stale_or_unsynchronized", "window_index": window_index}
    body = {
        "status": "valid", "window_index": window_index, "bid": bid, "ask": ask,
        "bid_at": bid_at.isoformat(), "ask_at": ask_at.isoformat(),
        "received_at": received.isoformat(), "venue": quote["venue"],
        "currency": quote.get("currency"), "source": quote.get("source"),
        "receipt_sha256": quote.get("receipt_sha256"), "locked": bid == ask,
        "half_quote_spread_bp": 10_000 * (ask - bid) / (ask + bid),
    }
    if body["currency"] != "USD":
        return {"status": "currency_mismatch", "window_index": window_index}
    return body


def measure_symbol_day(
    *, bar_set: dict, quote_rows: list[dict], operational_open: float | None = None,
    simulated_fill: float | None = None, side: str | None = None,
) -> dict:
    """Compose separate bar, quote, operational-open and simulator comparisons."""
    if bar_set.get("bar_set_sha256") != canonical_sha256({
            key: value for key, value in bar_set.items() if key != "bar_set_sha256"}):
        raise ValueError("fill bar set identity differs")
    valid = {row.get("window_index"): row for row in quote_rows
             if row.get("status") == "valid"}
    quote_target = None
    if set(valid) == {0, 1}:
        quote_target = statistics.mean(
            valid[index]["half_quote_spread_bp"] for index in (0, 1))
    metrics = bar_set.get("metrics")
    first_open = None if metrics is None else metrics["first_open"]
    open_gap = None
    if first_open is not None and operational_open is not None:
        open_gap = 10_000 * (first_open / _number(operational_open, "operational open") - 1)
    sim_gap = None
    if metrics is not None and metrics.get("reported_vwap") is not None \
            and simulated_fill is not None:
        if side not in {"buy", "sell"}:
            raise ValueError("fill side is invalid")
        sign = 1 if side == "buy" else -1
        sim_gap = sign * 10_000 * (
            _number(simulated_fill, "simulated fill") / metrics["reported_vwap"] - 1)
    body = {
        "bar_status": bar_set["status"], "quote_target_bp": quote_target,
        "quote_statuses": [row.get("status") for row in quote_rows],
        "vwap_gap_bp": None if metrics is None else metrics.get("vwap_gap_bp"),
        "hlc3_gap_bp": None if metrics is None else metrics.get("hlc3_gap_bp"),
        "half_range_proxy_bp": None if metrics is None else
            metrics.get("half_range_proxy_bp"),
        "open_source_gap_bp": open_gap, "sim_vs_vwap_bp": sim_gap,
        "execution_basis_verified": False, "v5_activation_eligible": False,
    }
    return {**body, "measurement_sha256": canonical_sha256(body)}
