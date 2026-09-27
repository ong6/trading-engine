"""Split-aware, explicitly named price projections for historical replay."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, datetime, time, timezone
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from farm.replay.registration import (
    PRICE_SERIES_BY_CONSUMER,
    SPLIT_KNOWLEDGE_PRIMARY,
    SPLIT_KNOWLEDGE_SENSITIVITY,
    TRUSTED_NOOP_SPLIT_OUTCOMES,
    TRUSTED_SPLIT_OUTCOMES,
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_NY = ZoneInfo("America/New_York")


class PriceSeriesError(ValueError):
    """A replay price or action cannot satisfy the registered as-of contract."""


class SplitQuarantineError(PriceSeriesError):
    """A relevant action is not trustworthy enough to apply or ignore."""


def _date(value: object, field: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise PriceSeriesError(f"invalid_{field}") from exc


def _instant(value: object, field: str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise PriceSeriesError(f"invalid_{field}")
    return value.astimezone(timezone.utc)


def _ratio(action: Mapping) -> float:
    value = action.get("new_shares_per_old")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SplitQuarantineError("invalid_split_ratio")
    ratio = float(value)
    if not math.isfinite(ratio) or ratio <= 0:
        raise SplitQuarantineError("invalid_split_ratio")
    return ratio


def split_outcome(action: Mapping) -> str:
    if action.get("kind") != "split" or action.get("stable_mapping") is not True:
        return "quarantined"
    try:
        _ratio(action)
        _date(action.get("ex_date"), "split_ex_date")
    except PriceSeriesError:
        return "quarantined"
    outcome = action.get("outcome")
    if outcome in TRUSTED_SPLIT_OUTCOMES:
        return "trusted"
    if outcome in TRUSTED_NOOP_SPLIT_OUTCOMES:
        return "trusted_noop"
    return "quarantined"


def split_known_at(action: Mapping, policy: str) -> datetime:
    if policy == SPLIT_KNOWLEDGE_PRIMARY:
        ex_date = _date(action.get("ex_date"), "split_ex_date")
        return datetime.combine(ex_date, time(9, 30), _NY).astimezone(timezone.utc)
    if policy == SPLIT_KNOWLEDGE_SENSITIVITY:
        observed_at = action.get("first_seen_at")
        receipt = action.get("observation_sha256")
        if observed_at is None or not isinstance(receipt, str) or _SHA256.fullmatch(receipt) is None:
            raise SplitQuarantineError("exact_action_first_seen_unavailable")
        return _instant(observed_at, "first_seen_at")
    raise PriceSeriesError("unknown_split_knowledge_policy")


def reconstruct_unadjusted_bars(
    bars: Sequence[Mapping], actions: Sequence[Mapping]
) -> list[dict]:
    """Undo vendor back-adjustment using resolved actions, not knowledge timestamps."""
    rebuilt = []
    for source in bars:
        if source.get("series") != "source_back_adjusted_v1":
            raise PriceSeriesError("wrong_source_price_series")
        security_id = source.get("security_id")
        session = _date(source.get("session"), "bar_session")
        factor = 1.0
        action_ids = []
        for action in actions:
            if action.get("security_id") != security_id:
                continue
            ex_date = _date(action.get("ex_date"), "split_ex_date")
            if session >= ex_date:
                continue
            status = split_outcome(action)
            if status == "quarantined":
                raise SplitQuarantineError(f"quarantined_split:{action.get('action_id')}")
            if status == "trusted_noop":
                continue
            factor *= _ratio(action)
            action_ids.append(action.get("action_id"))
        row = dict(source)
        for field in ("open", "high", "low", "close"):
            value = float(source[field])
            if not math.isfinite(value) or value <= 0:
                raise PriceSeriesError("invalid_source_price")
            row[field] = value * factor
        volume = source.get("volume")
        if volume is not None:
            volume = float(volume)
            if not math.isfinite(volume) or volume < 0:
                raise PriceSeriesError("invalid_source_volume")
            row["volume"] = volume / factor
        row.update(
            series="reconstructed_unadjusted_v1",
            reconstruction_factor=factor,
            reconstruction_action_ids=sorted(action_ids),
        )
        rebuilt.append(row)
    return rebuilt


def asof_split_adjusted_bars(
    reconstructed_bars: Sequence[Mapping],
    actions: Sequence[Mapping],
    *,
    as_of: datetime,
    knowledge_policy: str = SPLIT_KNOWLEDGE_PRIMARY,
) -> list[dict]:
    """Restate raw bars only by splits both effective and known at the cutoff."""
    cutoff = _instant(as_of, "as_of")
    visible = []
    for source in reconstructed_bars:
        if source.get("series") != "reconstructed_unadjusted_v1":
            raise PriceSeriesError("wrong_reconstructed_price_series")
        if _instant(source.get("available_at"), "bar_available_at") > cutoff:
            continue
        security_id = source.get("security_id")
        session = _date(source.get("session"), "bar_session")
        factor = 1.0
        action_ids = []
        for action in actions:
            if action.get("security_id") != security_id:
                continue
            ex_date = _date(action.get("ex_date"), "split_ex_date")
            if not session < ex_date <= cutoff.date():
                continue
            try:
                known_at = split_known_at(action, knowledge_policy)
            except SplitQuarantineError:
                raise SplitQuarantineError(f"unknown_split_knowledge:{action.get('action_id')}")
            if known_at > cutoff:
                continue
            status = split_outcome(action)
            if status == "quarantined":
                raise SplitQuarantineError(f"quarantined_split:{action.get('action_id')}")
            if status == "trusted_noop":
                continue
            factor *= _ratio(action)
            action_ids.append(action.get("action_id"))
        row = dict(source)
        for field in ("open", "high", "low", "close"):
            row[field] = float(source[field]) / factor
        if source.get("volume") is not None:
            row["volume"] = float(source["volume"]) * factor
        row.update(
            series="asof_split_adjusted_v1",
            as_of=cutoff.isoformat().replace("+00:00", "Z"),
            asof_split_factor=factor,
            asof_action_ids=sorted(action_ids),
        )
        visible.append(row)
    return visible


def label_split_normalized_return(
    *,
    security_id: str,
    entry_raw: float,
    exit_raw: float,
    entry_at: datetime,
    exit_at: datetime,
    visible_at: datetime,
    actions: Sequence[Mapping],
    knowledge_policy: str = SPLIT_KNOWLEDGE_PRIMARY,
    entry_cost_bps: float = 10.0,
    exit_cost_bps: float = 10.0,
) -> float:
    """Compute one label on a common raw share scale, including SPY labels."""
    entry = _instant(entry_at, "entry_at")
    exit_ = _instant(exit_at, "exit_at")
    visible = _instant(visible_at, "visible_at")
    if not entry < exit_ <= visible:
        raise PriceSeriesError("invalid_label_clock")
    if not all(math.isfinite(float(value)) and float(value) > 0 for value in (entry_raw, exit_raw)):
        raise PriceSeriesError("invalid_label_price")
    factor = 1.0
    for action in actions:
        if action.get("security_id") != security_id:
            continue
        ex_date = _date(action.get("ex_date"), "split_ex_date")
        if not entry.date() < ex_date <= exit_.date():
            continue
        if split_known_at(action, knowledge_policy) > visible:
            raise SplitQuarantineError(f"late_split_knowledge:{action.get('action_id')}")
        if split_outcome(action) != "trusted":
            raise SplitQuarantineError(f"quarantined_label_split:{action.get('action_id')}")
        factor *= _ratio(action)
    entry_multiplier = 1.0 + float(entry_cost_bps) / 10_000.0
    exit_multiplier = 1.0 - float(exit_cost_bps) / 10_000.0
    return float(exit_raw) * factor * exit_multiplier / (float(entry_raw) * entry_multiplier) - 1.0


def consumer_price_series(consumer: str) -> str:
    try:
        return PRICE_SERIES_BY_CONSUMER[consumer]
    except KeyError as exc:
        raise PriceSeriesError("unregistered_price_consumer") from exc


def quarantined_exposure_counts(
    actions: Sequence[Mapping], exposures: Iterable[Mapping]
) -> list[dict]:
    """Estimate held/pending action quarantines for each preregistered window."""
    counts = defaultdict(lambda: {"held": 0, "pending": 0, "action_ids": set()})
    for action in actions:
        if split_outcome(action) != "quarantined":
            continue
        ex_date = _date(action.get("ex_date"), "split_ex_date")
        for exposure in exposures:
            if exposure.get("security_id") != action.get("security_id"):
                continue
            if not _date(exposure.get("start"), "exposure_start") <= ex_date <= _date(
                exposure.get("end"), "exposure_end"
            ):
                continue
            state = exposure.get("state")
            if state not in {"held", "pending"}:
                raise PriceSeriesError("invalid_exposure_state")
            row = counts[str(exposure.get("window_id"))]
            row[state] += 1
            row["action_ids"].add(action.get("action_id"))
    return [
        {
            "window_id": window_id,
            "held": row["held"],
            "pending": row["pending"],
            "affected_actions": len(row["action_ids"]),
        }
        for window_id, row in sorted(counts.items())
    ]
