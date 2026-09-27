"""Split-aware, explicitly named price projections for historical replay."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import pandas as pd

from engine import p15_event_sources
from engine.lib import db
from farm.replay.registration import (
    INDEPENDENT_UNADJUSTED_PRICE_SOURCE,
    PRICE_SERIES_BY_CONSUMER,
    SPLIT_KNOWLEDGE_PRIMARY,
    SPLIT_KNOWLEDGE_SENSITIVITY,
    TRUSTED_NOOP_SPLIT_OUTCOMES,
    TRUSTED_SPLIT_OUTCOMES,
)
from sim import nyse

_NY = ZoneInfo("America/New_York")


class PriceSeriesError(ValueError):
    """A replay price or action cannot satisfy the registered as-of contract."""


class SplitQuarantineError(PriceSeriesError):
    """A relevant action is not trustworthy enough to apply or ignore."""


@dataclass(frozen=True)
class LabelPricePoint:
    security_id: str
    session: date
    available_at: datetime
    price_field: str
    price: float
    reconstruction_factor: float
    reconstruction_action_ids: tuple[str, ...]


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


def _unique_actions(actions: Sequence[Mapping]) -> tuple[Mapping, ...]:
    selected, natural_keys, unique = set(), set(), []
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
        unique.append(action)
    return tuple(unique)


def _actions_by_security(actions: Sequence[Mapping]) -> dict[object, tuple[Mapping, ...]]:
    indexed: dict[object, list[Mapping]] = defaultdict(list)
    for action in _unique_actions(actions):
        indexed[action.get("security_id")].append(action)
    return {security_id: tuple(rows) for security_id, rows in indexed.items()}


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


def split_adjustment_actions(
    rows: Sequence[Mapping],
    *,
    security_ids_by_ticker: Mapping[str, str],
    ticker_reuse_quarantine: set[str] | frozenset[str],
) -> list[dict]:
    """Map split-adjustment rows into replay actions using the ticker-reuse rule."""
    actions = []
    for row in rows:
        ticker = str(row.get("ticker", "")).upper()
        ex_date = _date(row.get("ex_date"), "split_ex_date")
        security_id = security_ids_by_ticker.get(ticker)
        actions.append(
            {
                "action_id": f"{ticker}:{ex_date.isoformat()}",
                "security_id": security_id,
                "stable_mapping": security_id is not None
                and ticker not in ticker_reuse_quarantine,
                "kind": "split",
                "ex_date": ex_date,
                "outcome": row.get("outcome"),
                "new_shares_per_old": row.get("ratio"),
            }
        )
    return actions


def split_known_at(
    action: Mapping, policy: str
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
    actions_by_security = _actions_by_security(actions)
    rebuilt = []
    for source in bars:
        if source.get("series") != "source_back_adjusted_v1":
            raise PriceSeriesError("wrong_source_price_series")
        security_id = source.get("security_id")
        session = _date(source.get("session"), "bar_session")
        factor, action_ids = _reconstruction_scale(
            security_id, session, actions_by_security.get(security_id, ())
        )
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
            reconstruction_action_ids=action_ids,
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
    actions_by_security = _actions_by_security(actions)
    cutoff = _instant(as_of, "as_of")
    visible = []
    for source in reconstructed_bars:
        security_id = source.get("security_id")
        security_actions = actions_by_security.get(security_id, ())
        _validate_reconstructed_bar(source, security_actions)
        if _instant(source.get("available_at"), "bar_available_at") > cutoff:
            continue
        session = _date(source.get("session"), "bar_session")
        factor = 1.0
        action_ids = []
        for action in security_actions:
            ex_date = _date(action.get("ex_date"), "split_ex_date")
            if not session < ex_date or _split_effective_at(action) > cutoff:
                continue
            try:
                known_at = split_known_at(action, knowledge_policy)
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


def _price_frame(rows: Sequence[Mapping]) -> pd.DataFrame:
    return pd.DataFrame.from_records(
        [
            {
                "ticker": str(row.get("ticker") or row.get("security_id")),
                "date": _date(row.get("session"), "bar_session"),
                "open": float(row["open"]),
                "high": None if row.get("high") is None else float(row["high"]),
                "low": None if row.get("low") is None else float(row["low"]),
                "close": None if row.get("close") is None else float(row["close"]),
                "volume": None if row.get("volume") is None else int(row["volume"]),
                "source": "historical_backfill",
                "fetched_at": _instant(row.get("visible_at"), "bar_visible_at").replace(
                    tzinfo=None
                ),
            }
            for row in rows
        ],
        columns=(
            "ticker", "date", "open", "high", "low", "close", "volume", "source",
            "fetched_at",
        ),
    )


def _phase_visible_bars(
    reconstructed_bars: Sequence[Mapping],
    actions: Sequence[Mapping],
    *,
    as_of: datetime,
    phase: str,
    knowledge_policy: str,
) -> list[dict]:
    """Project the archive into the fields available at one replay phase."""
    cutoff = _instant(as_of, "as_of")
    phase = phase.upper()
    if phase not in {"PREOPEN", "OPEN", "CLOSE", "SCORE", "POSTMORTEM"}:
        raise PriceSeriesError("invalid_price_phase")
    full = asof_split_adjusted_bars(
        reconstructed_bars, actions, as_of=cutoff, knowledge_policy=knowledge_policy
    )
    visible = {
        (row.get("security_id"), _date(row.get("session"), "bar_session")): {
            **row,
            "visible_at": row["available_at"],
        }
        for row in full
    }
    if phase != "OPEN":
        return list(visible.values())

    current_session = cutoff.astimezone(_NY).date()
    actions_by_security = _actions_by_security(actions)
    for source in reconstructed_bars:
        session = _date(source.get("session"), "bar_session")
        if session != current_session:
            continue
        security_id = source.get("security_id")
        security_actions = actions_by_security.get(security_id, ())
        _validate_reconstructed_bar(source, security_actions)
        factor = 1.0
        action_ids = []
        for action in security_actions:
            if session >= _date(action.get("ex_date"), "split_ex_date"):
                continue
            if split_known_at(action, knowledge_policy) > cutoff:
                continue
            status = split_outcome(action)
            if status == "quarantined":
                raise SplitQuarantineError(f"quarantined_split:{action.get('action_id')}")
            if status == "trusted":
                factor *= _ratio(action)
                action_ids.append(action.get("action_id"))
        visible[(security_id, session)] = {
            **source,
            "open": float(source["open"]) / factor,
            "high": None,
            "low": None,
            "close": None,
            # P15's frozen fill model uses realised daily volume as explicitly
            # labelled execution-model hindsight; policy code sees no SQL tools.
            "volume": None if source.get("volume") is None else float(source["volume"]) * factor,
            "series": "asof_split_adjusted_v1",
            "as_of": cutoff.isoformat().replace("+00:00", "Z"),
            "asof_split_factor": factor,
            "asof_action_ids": sorted(action_ids),
            "visible_at": cutoff,
        }
    return list(visible.values())


def _known_split_ids(
    actions: Sequence[Mapping], cutoff: datetime, knowledge_policy: str
) -> dict[object, tuple[str, ...]]:
    known: dict[object, list[str]] = defaultdict(list)
    for action in _unique_actions(actions):
        if (
            split_outcome(action) == "trusted"
            and split_known_at(action, knowledge_policy) <= cutoff
        ):
            known[action.get("security_id")].append(str(action.get("action_id")))
    return {key: tuple(sorted(values)) for key, values in known.items()}


def rewrite_private_prices(
    con,
    reconstructed_bars: Sequence[Mapping],
    actions: Sequence[Mapping],
    *,
    as_of: datetime,
    phase: str = "CLOSE",
    knowledge_policy: str = SPLIT_KNOWLEDGE_PRIMARY,
) -> dict:
    """Incrementally materialize one phase's visible prices.

    Ordinary phase advances insert or enrich only newly visible sessions.  A
    newly known split changes the historical scale, so only that security's
    prefix is deleted and bulk reinserted.
    """
    cutoff = _instant(as_of, "as_of")
    visible = _phase_visible_bars(
        reconstructed_bars, actions, as_of=cutoff, phase=phase,
        knowledge_policy=knowledge_policy,
    )
    con.execute(
        """CREATE TABLE IF NOT EXISTS replay_price_scale_state (
            security_id VARCHAR PRIMARY KEY,
            ticker VARCHAR NOT NULL,
            known_action_ids VARCHAR NOT NULL)"""
    )
    by_security: dict[str, list[dict]] = defaultdict(list)
    for row in visible:
        by_security[str(row.get("security_id"))].append(row)
    current = {
        row[0]: (row[1], tuple(json.loads(row[2])))
        for row in con.execute(
            "SELECT security_id,ticker,known_action_ids FROM replay_price_scale_state"
        ).fetchall()
    }
    known = _known_split_ids(actions, cutoff, knowledge_policy)
    rewrite_ids = {
        security_id
        for security_id, rows in by_security.items()
        if security_id in current
        and current[security_id][1] != known.get(security_id, ())
    }
    rewrite_tickers = sorted({
        str(by_security[security_id][0].get("ticker") or security_id)
        for security_id in rewrite_ids
    })
    if rewrite_tickers:
        ticker_frame = pd.DataFrame({"ticker": rewrite_tickers})
        with db.registered_frame(con, "_replay_rewrite_tickers", ticker_frame):
            con.execute(
                "DELETE FROM prices USING _replay_rewrite_tickers r "
                "WHERE prices.ticker=r.ticker"
            )

    frame = _price_frame(visible)
    changed = 0
    if not frame.empty:
        with db.registered_frame(con, "_replay_price_batch", frame):
            changed = int(con.execute(
                "SELECT COUNT(*) FROM _replay_price_batch b LEFT JOIN prices p "
                "ON p.ticker=b.ticker AND p.date=b.date WHERE p.ticker IS NULL "
                "OR p.open IS DISTINCT FROM b.open OR p.high IS DISTINCT FROM b.high "
                "OR p.low IS DISTINCT FROM b.low OR p.close IS DISTINCT FROM b.close "
                "OR p.volume IS DISTINCT FROM b.volume OR p.source IS DISTINCT FROM b.source "
                "OR p.fetched_at IS DISTINCT FROM b.fetched_at"
            ).fetchone()[0])
            con.execute(
                "INSERT OR REPLACE INTO prices "
                "SELECT ticker,date,open,high,low,close,volume,source,fetched_at "
                "FROM _replay_price_batch b WHERE NOT EXISTS ("
                "SELECT 1 FROM prices p WHERE p.ticker=b.ticker AND p.date=b.date "
                "AND p.open IS NOT DISTINCT FROM b.open "
                "AND p.high IS NOT DISTINCT FROM b.high "
                "AND p.low IS NOT DISTINCT FROM b.low "
                "AND p.close IS NOT DISTINCT FROM b.close "
                "AND p.volume IS NOT DISTINCT FROM b.volume "
                "AND p.source IS NOT DISTINCT FROM b.source "
                "AND p.fetched_at IS NOT DISTINCT FROM b.fetched_at)"
            )

    state_rows = []
    for security_id, rows in sorted(by_security.items()):
        ticker = str(rows[0].get("ticker") or security_id)
        state_rows.append({
            "security_id": security_id,
            "ticker": ticker,
            "known_action_ids": json.dumps(known.get(security_id, ()), separators=(",", ":")),
        })
    if state_rows:
        state_frame = pd.DataFrame.from_records(state_rows)
        with db.registered_frame(con, "_replay_price_state_batch", state_frame):
            con.execute(
                "INSERT OR REPLACE INTO replay_price_scale_state "
                "SELECT security_id,ticker,known_action_ids FROM _replay_price_state_batch"
            )
    return {
        "visible_rows": len(visible),
        "changed_rows": changed,
        "rewritten_security_ids": sorted(rewrite_ids),
    }


def rewrite_known_split_adjustments(
    con,
    actions: Sequence[Mapping],
    *,
    known_at: datetime,
    knowledge_policy: str = SPLIT_KNOWLEDGE_PRIMARY,
) -> int:
    """Expose only trusted split decisions known by this replay open."""
    cutoff = _instant(known_at, "split_cutoff")
    rows = []
    for action in _unique_actions(actions):
        status = split_outcome(action)
        if status == "quarantined" or split_known_at(action, knowledge_policy) > cutoff:
            continue
        ticker = str(action.get("ticker", ""))
        if not ticker:
            raise SplitQuarantineError("split_ticker_missing")
        rows.append(
            (
                ticker,
                _date(action.get("ex_date"), "split_ex_date"),
                _ratio(action),
                action.get("outcome"),
                None,
                None,
                0,
                cutoff,
            )
        )
    if rows:
        frame = pd.DataFrame.from_records(rows, columns=(
            "ticker", "ex_date", "ratio", "outcome", "observed_price_ratio",
            "break_date", "rows_restated", "applied_at",
        ))
        with db.registered_frame(con, "_replay_split_batch", frame):
            con.execute(
                "INSERT OR REPLACE INTO split_adjustments "
                "SELECT ticker,ex_date,ratio,outcome,observed_price_ratio,break_date,"
                "rows_restated,applied_at FROM _replay_split_batch"
            )
    return len(rows)


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
        expected_field = (
            "open"
            if local.time() == time(9, 30)
            else "close"
            if local.time() == p15_event_sources.session_close(point.session)
            else None
        )
        if point.security_id != security_id or point.session != local.date():
            raise PriceSeriesError(f"wrong_{name}_label_security")
        if expected_field is None or point.price_field != expected_field:
            raise PriceSeriesError(f"wrong_{name}_label_price_field")
        factor, action_ids = _reconstruction_scale(security_id, point.session, actions)
        if point.reconstruction_factor != factor or list(point.reconstruction_action_ids) != action_ids:
            raise PriceSeriesError(f"wrong_{name}_label_action_set")
        if point.available_at > visible:
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


def _validate_reconstructed_bar(bar: Mapping, actions: Sequence[Mapping]) -> None:
    if bar.get("series") != "reconstructed_unadjusted_v1":
        raise PriceSeriesError("wrong_reconstructed_price_series")
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
    if not isinstance(action_ids, list):
        raise PriceSeriesError("incomplete_label_price")
    return LabelPricePoint(
        str(bar.get("security_id")), _date(bar.get("session"), "bar_session"),
        _instant(bar.get("available_at"), "bar_available_at"), price_field, float(bar[price_field]),
        float(bar.get("reconstruction_factor")), tuple(action_ids),
    )


def quarantined_exposure_counts(
    actions: Sequence[Mapping],
    exposures: Iterable[Mapping],
    *,
    registered_windows: Sequence[str],
    knowledge_policy: str = SPLIT_KNOWLEDGE_PRIMARY,
) -> list[dict]:
    """Estimate held/pending action quarantines for each preregistered window."""
    exposures = tuple(exposures)
    windows = tuple(registered_windows)
    if not windows or windows != tuple(dict.fromkeys(windows)) or any(not item for item in windows):
        raise PriceSeriesError("invalid_registered_windows")
    counts = defaultdict(
        lambda: {"held": 0, "pending": 0, "action_ids": set(), "security_ids": set()}
    )
    for window in windows:
        counts[window]
    for action in _unique_actions(actions):
        quarantined = split_outcome(action) == "quarantined"
        try:
            known_at = split_known_at(action, knowledge_policy)
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
            row["security_ids"].add(action.get("security_id"))
    return [
        {
            "window_id": window_id,
            "held": row["held"],
            "pending": row["pending"],
            "affected_actions": len(row["action_ids"]),
            "excluded_securities": len(row["security_ids"]),
        }
        for window_id, row in sorted(counts.items())
    ]


def raw_price_spot_check(
    reconstructed_bars: Sequence[Mapping],
    reference_rows: Sequence[Mapping],
) -> dict:
    """Compare a small registered sample with independent contemporaneous prints."""
    if not reference_rows:
        raise PriceSeriesError("raw_price_reference_missing")
    bars = {
        (str(row.get("security_id")), _date(row.get("session"), "bar_session")): row
        for row in reconstructed_bars
    }
    failures, volume_checks, strata = [], [], defaultdict(lambda: {"checked": 0, "failed": 0})
    for reference in reference_rows:
        if reference.get("source") != INDEPENDENT_UNADJUSTED_PRICE_SOURCE:
            raise PriceSeriesError("raw_price_reference_source_unregistered")
        key = (
            str(reference.get("security_id")),
            _date(reference.get("session"), "reference_session"),
        )
        bar = bars.get(key)
        stratum = str(reference.get("stratum", "unclassified"))
        strata[stratum]["checked"] += 1
        failed_fields = []
        if bar is None or bar.get("series") != "reconstructed_unadjusted_v1":
            failed_fields.append("missing_reconstructed_bar")
        else:
            for field in ("open", "high", "low", "close"):
                if reference.get(field) is None:
                    continue
                observed, expected = float(bar[field]), float(reference[field])
                tolerance = max(0.005, 5e-4 * abs(expected))
                if not math.isfinite(observed) or abs(observed - expected) > tolerance:
                    failed_fields.append(field)
            if reference.get("volume") is not None:
                volume_checks.append({
                    "security_id": key[0], "session": key[1].isoformat(),
                    "observed": bar.get("volume"), "reference": reference["volume"],
                })
        if failed_fields:
            strata[stratum]["failed"] += 1
            failures.append({
                "security_id": key[0],
                "session": key[1].isoformat(),
                "fields": failed_fields,
            })
    return {
        "status": "pass" if not failures else "quarantine",
        "source": INDEPENDENT_UNADJUSTED_PRICE_SOURCE,
        "checked": len(reference_rows),
        "failures": failures,
        "volume_informational": volume_checks,
        "strata": dict(sorted(strata.items())),
    }
