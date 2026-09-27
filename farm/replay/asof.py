"""Split-aware, explicitly named price projections for historical replay."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, datetime, time, timezone
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

from engine.lib.provenance import canonical_sha256
from farm.replay.registration import (
    EARLIEST_EXACT_SPLIT_OBSERVATION_AT,
    PRICE_SERIES_BY_CONSUMER,
    SPLIT_KNOWLEDGE_PRIMARY,
    SPLIT_KNOWLEDGE_SENSITIVITY,
    SPLIT_OBSERVATION_REGISTRATION_KEY,
    TRUSTED_NOOP_SPLIT_OUTCOMES,
    TRUSTED_SPLIT_OUTCOMES,
)
from farm.replay.store import append_exact, load_record, seal_records, verify_seal
from sim import nyse

_SHA256 = re.compile(r"[0-9a-f]{64}")
_NY = ZoneInfo("America/New_York")
_OBSERVATION_TOKEN = object()
_LABEL_TOKEN = object()


class PriceSeriesError(ValueError):
    """A replay price or action cannot satisfy the registered as-of contract."""


class SplitQuarantineError(PriceSeriesError):
    """A relevant action is not trustworthy enough to apply or ignore."""


class LabelPricePoint:
    __slots__ = (
        "security_id", "session", "available_at", "price_field", "price",
        "reconstruction_factor", "reconstruction_action_ids", "archive_row_sha256",
        "reconstruction_sha256", "point_sha256",
    )

    def __init__(self, *values, _token=None):
        if _token is not _LABEL_TOKEN or len(values) != len(self.__slots__):
            raise PriceSeriesError("unverified_label_price_point")
        for name, value in zip(self.__slots__, values, strict=True):
            object.__setattr__(self, name, value)

    def __setattr__(self, _name, _value):
        raise AttributeError("immutable_label_price_point")


class ExactSplitObservations:
    __slots__ = ("registration_sha256", "seal_sha256", "entries", "entries_sha256")

    def __init__(self, *values, _token=None):
        if _token is not _OBSERVATION_TOKEN or len(values) != len(self.__slots__):
            raise SplitQuarantineError("unverified_split_observations")
        for name, value in zip(self.__slots__, values, strict=True):
            object.__setattr__(self, name, value)

    def __setattr__(self, _name, _value):
        raise AttributeError("immutable_split_observations")

    def get(self, action_sha256: str) -> tuple[datetime, str] | None:
        if self.entries_sha256 != canonical_sha256([
            [key, at.isoformat().replace("+00:00", "Z"), receipt]
            for key, at, receipt in self.entries
        ]):
            raise SplitQuarantineError("split_observations_tampered")
        return next(((at, receipt) for key, at, receipt in self.entries if key == action_sha256), None)


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


def split_observation_identity(action: Mapping) -> str:
    """Bind a first-observation receipt to one exact normalized action version."""
    return canonical_sha256(
        {
            key: action.get(key)
            for key in (
                "action_id", "security_id", "stable_mapping", "kind", "ex_date",
                "outcome", "new_shares_per_old",
            )
        }
    )


def _unique_actions(actions: Sequence[Mapping]) -> tuple[Mapping, ...]:
    selected, natural_keys = set(), set()
    for action in actions:
        action_id = action.get("action_id")
        natural_key = (
            action.get("security_id"), action.get("kind"),
            _date(action.get("ex_date"), "split_ex_date"),
        )
        if not action_id or action_id in selected or natural_key in natural_keys:
            raise SplitQuarantineError("ambiguous_split_action_versions")
        selected.add(action_id)
        natural_keys.add(natural_key)
    return tuple(actions)


def _split_effective_at(action: Mapping) -> datetime:
    return datetime.combine(
        _date(action.get("ex_date"), "split_ex_date"), time(9, 30), _NY
    ).astimezone(timezone.utc)


def _split_fixed_lag_at(action: Mapping) -> datetime:
    return datetime.combine(
        nyse.next_session(_date(action.get("ex_date"), "split_ex_date")),
        time(9, 30),
        _NY,
    ).astimezone(timezone.utc)


def _reconstruction_scale(
    security_id: object, session: date, actions: Sequence[Mapping]
) -> tuple[float, list[str]]:
    factor, action_ids = 1.0, []
    for action in actions:
        if action.get("security_id") != security_id or session >= _date(
            action.get("ex_date"), "split_ex_date"
        ):
            continue
        status = split_outcome(action)
        if status == "quarantined":
            raise SplitQuarantineError(f"quarantined_split:{action.get('action_id')}")
        if status == "trusted":
            factor *= _ratio(action)
            action_ids.append(action.get("action_id"))
    return factor, sorted(action_ids)


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


def record_actions_fetch_log(
    con, *, receipt: Mapping, recorded_at: datetime
) -> str:
    """Append one exact receipt and all normalized split versions it contained."""
    observed = _instant(recorded_at, "actions_fetch_recorded_at")
    if observed < _instant(EARLIEST_EXACT_SPLIT_OBSERVATION_AT, "observation_start"):
        raise SplitQuarantineError("actions_fetch_before_collector_start")
    actions = receipt.get("actions")
    archive_sha = receipt.get("archive_payload_sha256")
    if (not isinstance(actions, list) or not isinstance(receipt.get("source"), str)
            or _SHA256.fullmatch(str(archive_sha)) is None):
        raise SplitQuarantineError("invalid_actions_fetch_receipt")
    identities = sorted({split_observation_identity(action) for action in actions})
    if not identities:
        raise SplitQuarantineError("empty_actions_fetch_log")
    receipt_sha256 = canonical_sha256(receipt)
    append_exact(con, record_type="actions_fetch_receipt", record_key=receipt_sha256,
                 payload=receipt, recorded_at=recorded_at)
    payload = {"receipt_sha256": receipt_sha256, "action_identity_sha256es": identities}
    key = canonical_sha256(payload)
    append_exact(con, record_type="actions_fetch_log", record_key=key,
                 payload=payload, recorded_at=recorded_at)
    return key


def freeze_exact_split_observations(
    con, *, fetch_keys: Sequence[str], frozen_at: datetime
) -> str:
    """Freeze the append-only fetch attempts used by the registered sensitivity."""
    frozen = _instant(frozen_at, "split_observation_frozen_at")
    for key in fetch_keys:
        record = load_record(con, "actions_fetch_log", key)
        if record is None or _instant(record["recorded_at"], "first_seen_at") > frozen:
            raise SplitQuarantineError("actions_fetch_after_registration")
    seal_sha256 = seal_records(
        con, record_type="actions_fetch_log", member_keys=tuple(sorted(set(fetch_keys))),
        sealed_at=frozen_at,
    )
    payload = {
        "policy": SPLIT_KNOWLEDGE_SENSITIVITY,
        "actions_fetch_log_seal_sha256": seal_sha256,
        "frozen_at": frozen.isoformat().replace("+00:00", "Z"),
        "status": "registered", "authority": "historical_research_only",
    }
    return append_exact(
        con, record_type="split_observation_registration",
        record_key=SPLIT_OBSERVATION_REGISTRATION_KEY, payload=payload, recorded_at=frozen_at,
    )


def load_exact_split_observations(con, registration_sha256: str) -> ExactSplitObservations:
    registration = load_record(
        con, "split_observation_registration", SPLIT_OBSERVATION_REGISTRATION_KEY
    )
    if registration is None or registration["payload_sha256"] != registration_sha256:
        raise SplitQuarantineError("split_observation_registration_mismatch")
    registration_payload = registration["payload"]
    if (registration_payload.get("policy") != SPLIT_KNOWLEDGE_SENSITIVITY
            or registration_payload.get("status") != "registered"
            or registration_payload.get("authority") != "historical_research_only"):
        raise SplitQuarantineError("wrong_split_observation_registration")
    seal_sha256 = registration_payload.get("actions_fetch_log_seal_sha256")
    manifest = verify_seal(con, seal_sha256)
    if manifest["record_type"] != "actions_fetch_log":
        raise SplitQuarantineError("wrong_split_observation_seal")
    observations: dict[str, tuple[datetime, str]] = {}
    for member in manifest["members"]:
        record = load_record(con, "actions_fetch_log", member["record_key"])
        payload = record["payload"]
        receipt_sha = payload.get("receipt_sha256")
        identities = payload.get("action_identity_sha256es")
        if not isinstance(identities, list) or identities != sorted(set(identities)) or not isinstance(
            receipt_sha, str
        ) or _SHA256.fullmatch(receipt_sha) is None:
            raise SplitQuarantineError("invalid_split_observation")
        receipt = load_record(con, "actions_fetch_receipt", receipt_sha)
        if receipt is None or canonical_sha256(receipt["payload"]) != receipt_sha or identities != sorted({
            split_observation_identity(action) for action in receipt["payload"].get("actions", [])
        }):
            raise SplitQuarantineError("invalid_split_observation_receipt")
        observed_at = _instant(record["recorded_at"], "first_seen_at")
        for action_sha in identities:
            if _SHA256.fullmatch(action_sha) is None:
                raise SplitQuarantineError("invalid_split_observation")
            prior = observations.get(action_sha)
            if prior is None or (observed_at, receipt_sha) < prior:
                observations[action_sha] = (observed_at, receipt_sha)
    entries = tuple((key, *observations[key]) for key in sorted(observations))
    entries_sha256 = canonical_sha256([
        [key, at.isoformat().replace("+00:00", "Z"), receipt]
        for key, at, receipt in entries
    ])
    return ExactSplitObservations(
        registration_sha256, seal_sha256, entries, entries_sha256,
        _token=_OBSERVATION_TOKEN,
    )


def split_known_at(
    action: Mapping, policy: str, observations: ExactSplitObservations | None = None
) -> datetime:
    if policy == SPLIT_KNOWLEDGE_PRIMARY:
        return _split_effective_at(action)
    if policy == SPLIT_KNOWLEDGE_SENSITIVITY:
        return _split_fixed_lag_at(action)
    raise PriceSeriesError("unknown_split_knowledge_policy")


def reconstruct_unadjusted_bars(
    bars: Sequence[Mapping], actions: Sequence[Mapping]
) -> list[dict]:
    """Undo vendor back-adjustment using resolved actions, not knowledge timestamps."""
    actions = _unique_actions(actions)
    rebuilt = []
    for source in bars:
        if source.get("series") != "source_back_adjusted_v1":
            raise PriceSeriesError("wrong_source_price_series")
        security_id = source.get("security_id")
        session = _date(source.get("session"), "bar_session")
        factor, action_ids = _reconstruction_scale(security_id, session, actions)
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
        archive_row = dict(source)
        row.update(
            series="reconstructed_unadjusted_v1",
            reconstruction_factor=factor,
            reconstruction_action_ids=action_ids,
            archive_row=archive_row,
            archive_row_sha256=canonical_sha256(archive_row),
        )
        row["reconstruction_sha256"] = canonical_sha256(_reconstruction_payload(row))
        rebuilt.append(row)
    return rebuilt


def asof_split_adjusted_bars(
    reconstructed_bars: Sequence[Mapping],
    actions: Sequence[Mapping],
    *,
    as_of: datetime,
    knowledge_policy: str = SPLIT_KNOWLEDGE_PRIMARY,
    observations: ExactSplitObservations | None = None,
) -> list[dict]:
    """Restate raw bars only by splits both effective and known at the cutoff."""
    actions = _unique_actions(actions)
    cutoff = _instant(as_of, "as_of")
    visible = []
    for source in reconstructed_bars:
        _validate_reconstructed_bar(source, actions)
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
            if not session < ex_date or _split_effective_at(action) > cutoff:
                continue
            try:
                known_at = split_known_at(action, knowledge_policy, observations)
            except SplitQuarantineError:
                raise SplitQuarantineError(
                    f"unknown_split_knowledge:{action.get('action_id')}"
                ) from None
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
    entry_point: LabelPricePoint,
    exit_point: LabelPricePoint,
    entry_at: datetime,
    exit_at: datetime,
    visible_at: datetime,
    actions: Sequence[Mapping],
    knowledge_policy: str = SPLIT_KNOWLEDGE_PRIMARY,
    observations: ExactSplitObservations | None = None,
    entry_cost_bps: float = 10.0,
    exit_cost_bps: float = 10.0,
) -> float:
    """Compute one label on a common raw share scale, including SPY labels."""
    entry = _instant(entry_at, "entry_at")
    exit_ = _instant(exit_at, "exit_at")
    visible = _instant(visible_at, "visible_at")
    if not entry < exit_ <= visible:
        raise PriceSeriesError("invalid_label_clock")
    actions = _unique_actions(actions)
    prices = []
    for name, point, at in (("entry", entry_point, entry), ("exit", exit_point, exit_)):
        if not isinstance(point, LabelPricePoint):
            raise PriceSeriesError(f"wrong_{name}_label_price_series")
        local = at.astimezone(_NY)
        expected_field = "open" if local.time() == time(9, 30) else "close" if local.time() == time(16) else None
        if point.security_id != security_id or point.session != local.date():
            raise PriceSeriesError(f"wrong_{name}_label_security")
        if expected_field is None or point.price_field != expected_field:
            raise PriceSeriesError(f"wrong_{name}_label_price_field")
        if point.point_sha256 != canonical_sha256(_label_point_payload(point)):
            raise PriceSeriesError(f"tampered_{name}_label_price")
        factor, action_ids = _reconstruction_scale(security_id, point.session, actions)
        if point.reconstruction_factor != factor or list(point.reconstruction_action_ids) != action_ids:
            raise PriceSeriesError(f"wrong_{name}_label_action_set")
        if point.available_at > visible or _SHA256.fullmatch(point.archive_row_sha256) is None:
            raise PriceSeriesError(f"unavailable_{name}_label_price")
        value = float(point.price)
        if not math.isfinite(value) or value <= 0:
            raise PriceSeriesError("invalid_label_price")
        prices.append(value)
    entry_raw, exit_raw = prices
    factor = 1.0
    for action in actions:
        if action.get("security_id") != security_id:
            continue
        effective_at = _split_effective_at(action)
        if not entry < effective_at <= exit_:
            continue
        if split_known_at(action, knowledge_policy, observations) > visible:
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


def _reconstruction_payload(bar: Mapping) -> dict:
    return {key: bar.get(key) for key in (
        "security_id", "session", "available_at", "open", "high", "low", "close", "volume",
        "reconstruction_factor", "reconstruction_action_ids", "archive_row_sha256",
    )}


def _label_point_payload(point: LabelPricePoint) -> dict:
    payload = {key: getattr(point, key) for key in (
        "security_id", "session", "available_at", "price_field", "price",
        "reconstruction_factor", "reconstruction_action_ids", "archive_row_sha256",
        "reconstruction_sha256",
    )}
    payload["session"] = payload["session"].isoformat()
    payload["available_at"] = payload["available_at"].isoformat().replace("+00:00", "Z")
    payload["reconstruction_action_ids"] = list(payload["reconstruction_action_ids"])
    return payload


def _validate_reconstructed_bar(bar: Mapping, actions: Sequence[Mapping]) -> None:
    if bar.get("series") != "reconstructed_unadjusted_v1":
        raise PriceSeriesError("wrong_reconstructed_price_series")
    if (bar.get("archive_row_sha256") != canonical_sha256(bar.get("archive_row"))
            or bar.get("reconstruction_sha256") != canonical_sha256(_reconstruction_payload(bar))):
        raise PriceSeriesError("tampered_reconstructed_price_series")
    factor, action_ids = _reconstruction_scale(
        bar.get("security_id"), _date(bar.get("session"), "bar_session"), actions
    )
    if float(bar.get("reconstruction_factor")) != factor or bar.get(
        "reconstruction_action_ids"
    ) != action_ids:
        raise PriceSeriesError("wrong_reconstructed_action_set")


def label_price_point(bar: Mapping, price_field: str) -> LabelPricePoint:
    if bar.get("series") != "reconstructed_unadjusted_v1" or price_field not in {"open", "close"}:
        raise PriceSeriesError("wrong_label_price_series")
    action_ids = bar.get("reconstruction_action_ids")
    archive_sha = bar.get("archive_row_sha256")
    reconstruction_sha = bar.get("reconstruction_sha256")
    if (not isinstance(action_ids, list) or not isinstance(archive_sha, str)
            or _SHA256.fullmatch(archive_sha) is None
            or archive_sha != canonical_sha256(bar.get("archive_row"))
            or reconstruction_sha != canonical_sha256(_reconstruction_payload(bar))):
        raise PriceSeriesError("incomplete_label_price_provenance")
    values = (
        str(bar.get("security_id")), _date(bar.get("session"), "bar_session"),
        _instant(bar.get("available_at"), "bar_available_at"), price_field, float(bar[price_field]),
        float(bar.get("reconstruction_factor")), tuple(action_ids), archive_sha, reconstruction_sha,
    )
    point = LabelPricePoint(*values, "", _token=_LABEL_TOKEN)
    return LabelPricePoint(
        *values, canonical_sha256(_label_point_payload(point)), _token=_LABEL_TOKEN
    )


def quarantined_exposure_counts(
    actions: Sequence[Mapping],
    exposures: Iterable[Mapping],
    *,
    registered_windows: Sequence[str],
    knowledge_policy: str = SPLIT_KNOWLEDGE_PRIMARY,
    observations: ExactSplitObservations | None = None,
) -> list[dict]:
    """Estimate held/pending action quarantines for each preregistered window."""
    exposures = tuple(exposures)
    windows = tuple(registered_windows)
    if not windows or windows != tuple(dict.fromkeys(windows)) or any(not item for item in windows):
        raise PriceSeriesError("invalid_registered_windows")
    counts = defaultdict(lambda: {"held": 0, "pending": 0, "action_ids": set()})
    for window in windows:
        counts[window]
    for action in _unique_actions(actions):
        quarantined = split_outcome(action) == "quarantined"
        try:
            known_at = split_known_at(action, knowledge_policy, observations)
        except SplitQuarantineError:
            quarantined = True
        else:
            quarantined = quarantined or known_at > _split_effective_at(action)
        if not quarantined:
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
            window_id = str(exposure.get("window_id"))
            if window_id not in counts:
                raise PriceSeriesError("exposure_outside_registered_windows")
            row = counts[window_id]
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
