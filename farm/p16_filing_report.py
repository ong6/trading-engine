"""Point-in-time labels and descriptive reporting for the W3 filing reader."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

import numpy as np

from engine.lib.db import REAL_BAR_SQL
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from engine.p15_evaluation import spearman
from engine.p15_event_sources import session_close
from server import p15_price_fetch_attempts, p16_filing_store
from sim import nyse

ET = ZoneInfo("America/New_York")
HORIZONS = (1, 5, 10, 20)
BASES = ("next_session_open", "next_bar")
ROUND_TRIP_COST_BPS = 20
BOOTSTRAP_DRAWS = 2_000
BOOTSTRAP_SEED = 1603
SLA_SECONDS = 300
STATE_NAMES = (
    "queued", "parsed", "scored", "unavailable", "mapped", "unmapped",
    "duplicate", "pre_activation", "truncated", "labelled", "label_pending",
    "label_unavailable", "label_last_available", "capacity_unavailable", "sla_miss",
    "timeout",
)


def _utc(value: datetime | str, field: str) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    if parsed.utcoffset() is None:
        raise ValueError(f"{field} requires a timezone")
    return parsed.astimezone(timezone.utc)


def _day(value: date | str) -> date:
    try:
        if isinstance(value, datetime):
            raise ValueError
        return value if isinstance(value, date) else date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("price session date is invalid") from exc


def _session_open(day: date) -> datetime:
    return datetime.combine(day, time(9, 30), ET).astimezone(timezone.utc)


def entry_target(decided_at: datetime, basis: str) -> datetime:
    """Return the exact registered entry timestamp strictly after completion."""
    if basis not in BASES:
        raise ValueError("filing label basis is invalid")
    local = _utc(decided_at, "decided_at").astimezone(ET)
    if basis == "next_session_open":
        return _session_open(nyse.next_session(local.date()))
    day = local.date()
    if not nyse.is_session(day) or local.time() >= session_close(day):
        return _session_open(nyse.next_session(day))
    opening = datetime.combine(day, time(9, 30), ET)
    if local < opening:
        return opening.astimezone(timezone.utc)
    elapsed = int((local - opening).total_seconds() // 60)
    target = opening + timedelta(minutes=(elapsed // 5 + 1) * 5)
    if target.time() >= session_close(day):
        return _session_open(nyse.next_session(day))
    return target.astimezone(timezone.utc)


def _sessions(start: date, horizon: int) -> list[date]:
    if horizon not in HORIZONS or not nyse.is_session(start):
        raise ValueError("filing label horizon or entry session is invalid")
    sessions = [start]
    while len(sessions) < horizon:
        sessions.append(nyse.next_session(sessions[-1]))
    return sessions


def _price_rows(rows: Iterable[dict], *, cutoff: datetime, intraday: bool) -> list[dict]:
    required = ({"security_id", "event_at", "open", "interval", "fact_type"} if intraday else
                {"security_id", "session_date", "session_close_at", "open", "close"}) | {
                    "source", "price_basis", "corporate_action_status", "available_at",
                    "ingested_at", "source_sha256", "row_sha256"}
    normalized = []
    for source in rows:
        if not isinstance(source, dict) or not required <= set(source):
            raise ValueError("filing price row is invalid")
        row = dict(source)
        available = _utc(row["available_at"], "price available_at")
        ingested = _utc(row["ingested_at"], "price ingested_at")
        row["available_at"], row["ingested_at"] = available.isoformat(), ingested.isoformat()
        if max(available, ingested) > cutoff:
            continue
        if (not row["security_id"] or not row["source"] or
                row["price_basis"] not in {"raw", "split_adjusted", "total_return_adjusted"} or
                row["corporate_action_status"] not in {"none", "adjusted"} or
                (row["price_basis"] == "raw" and row["corporate_action_status"] != "none") or
                not isinstance(row["source_sha256"], str) or
                re.fullmatch(r"[0-9a-f]{64}", row["source_sha256"]) is None):
            raise ValueError("filing price identity is invalid")
        fields = ("open",) if intraday else ("open", "close")
        if any(isinstance(row[key], bool) or not isinstance(row[key], (int, float)) or
               not math.isfinite(row[key]) or row[key] <= 0 for key in fields):
            raise ValueError("filing price value is invalid")
        if intraday:
            event_at = _utc(row["event_at"], "price event_at")
            if (row["interval"] != "5m" or row["fact_type"] != "intraday.ohlcv.5m"
                    or available < event_at or ingested < available):
                raise ValueError("filing intraday provenance is invalid")
            row["event_at"] = event_at.isoformat()
        else:
            day = _day(row["session_date"])
            closed = datetime.combine(day, session_close(day), ET).astimezone(timezone.utc)
            if (_utc(row["session_close_at"], "session_close_at") != closed
                    or available < closed or ingested < available):
                raise ValueError("filing daily close is not mature")
            row["session_date"], row["session_close_at"] = day.isoformat(), closed.isoformat()
        stored_sha = row.pop("row_sha256")
        if canonical_sha256(row) != stored_sha:
            raise ValueError("filing price row identity differs")
        row["row_sha256"] = stored_sha
        normalized.append(row)
    return normalized


def _unique(rows: list[dict], key) -> dict:
    selected = {key(row): row for row in rows}
    if len(selected) != len(rows):
        raise ValueError("filing price rows are duplicated")
    return selected


def _confirmed(con, value: dict | None, *, missing: list[tuple[str, str]], through: date,
               cutoff: datetime, intraday_after: datetime | None = None) -> str | None:
    if value is None:
        return None
    if (con is None or not isinstance(value, dict) or set(value) != {
            "method", "observed_through"}
            or value["method"] not in {"recorded_fetch_attempt", "later_ticker_bar"}):
        raise ValueError("filing missing-price confirmation is invalid")
    observed = _day(value["observed_through"])
    grace = through
    for _ in range(3):
        grace = nyse.next_session(grace)
    grace_close = datetime.combine(grace, session_close(grace), ET).astimezone(timezone.utc)
    if observed < grace or observed > cutoff.astimezone(ET).date() or cutoff < grace_close:
        return None
    evidence = []
    if value["method"] == "recorded_fetch_attempt":
        if not all(table_exists(con, name) for name in (
                "price_fetch_attempts", "p15_price_fetch_batches")):
            return None
        p15_price_fetch_attempts.validate(con, ValueError)
        for security_id, day in missing:
            missing_day = _day(day)
            evidence_after = datetime.combine(
                missing_day, session_close(missing_day), ET
            ).astimezone(timezone.utc)
            row = con.execute(
                "SELECT a.attempt_sha256 FROM price_fetch_attempts a "
                "JOIN p15_price_fetch_batches b ON b.batch_sha256=a.batch_sha256 "
                "WHERE a.ticker=? AND a.market_date=? AND a.status='missing' "
                "AND a.attempted_at>=? AND a.attempted_at<=? AND b.failed_count=0 "
                "AND b.requested_count=b.present_count+b.missing_count",
                [security_id, missing_day, evidence_after.replace(tzinfo=None),
                 cutoff.replace(tzinfo=None)]).fetchone()
            if row is None:
                return None
            evidence.append(row[0])
    else:
        for security_id, day in missing:
            if intraday_after is not None:
                if not table_exists(con, "bitemporal_facts"):
                    return None
                row = con.execute(
                    "SELECT fact_sha256 FROM bitemporal_facts WHERE security_id=? "
                    "AND fact_type='intraday.ohlcv.5m' AND event_at>? AND available_at<=? "
                    "AND ingested_at<=? ORDER BY event_at LIMIT 1",
                    [security_id, intraday_after.replace(tzinfo=None),
                     cutoff.replace(tzinfo=None), cutoff.replace(tzinfo=None)]).fetchone()
            else:
                if not table_exists(con, "prices"):
                    return None
                row = con.execute(
                    f"SELECT date,fetched_at FROM prices WHERE ticker=? AND date>? AND date<=? "
                    f"AND fetched_at<=? AND {REAL_BAR_SQL} ORDER BY date LIMIT 1",
                    [security_id, _day(day), observed, cutoff.replace(tzinfo=None)]).fetchone()
            if row is None:
                return None
            evidence.append([item.isoformat() if isinstance(item, (date, datetime)) else item
                             for item in row])
    return canonical_sha256({"method": value["method"], "observed_through": observed.isoformat(),
                             "missing": sorted(missing), "evidence": evidence})


def make_label(
    *, decided_at: datetime, labelled_at: datetime, security_id: str, horizon: int,
    entry_basis: str, daily_rows: Iterable[dict], intraday_rows: Iterable[dict] = (),
    missing_confirmation: dict | None = None, verification_con=None,
) -> dict:
    """Build one label without shifting an absent entry to a later or prior bar."""
    decided, cutoff = _utc(decided_at, "decided_at"), _utc(labelled_at, "labelled_at")
    if cutoff < decided or not security_id:
        raise ValueError("filing label chronology is invalid")
    target = entry_target(decided, entry_basis)
    sessions = _sessions(target.astimezone(ET).date(), horizon)
    base = {"status": "pending", "label_market_date": decided.astimezone(ET).date().isoformat(),
            "entry_session": sessions[0].isoformat(), "entry_at": target.isoformat(),
            "expected_sessions": [item.isoformat() for item in sessions],
            "horizon": horizon, "entry_basis": entry_basis, "labelled_at": cutoff.isoformat()}
    daily = _price_rows(daily_rows, cutoff=cutoff, intraday=False)
    indexed = _unique(daily, lambda row: (row["security_id"], row["session_date"]))
    expected = [item.isoformat() for item in sessions]
    asset = [indexed.get((security_id, day)) for day in expected]
    spy = [indexed.get(("SPY", day)) for day in expected]
    entry_rows = None
    if entry_basis == "next_bar":
        intraday = _price_rows(intraday_rows, cutoff=cutoff, intraday=True)
        by_event = _unique(intraday, lambda row: (row["security_id"], row["event_at"]))
        key = target.isoformat()
        entry_rows = [by_event.get((security_id, key)), by_event.get(("SPY", key))]
    else:
        entry_rows = [asset[0], spy[0]]
    if any(row is None for row in entry_rows):
        missing_entry = [(security, sessions[0].isoformat()) for security, row in zip(
            (security_id, "SPY"), entry_rows, strict=True) if row is None]
        confirmation_sha = _confirmed(
            verification_con, missing_confirmation, missing=missing_entry,
            through=sessions[-1], cutoff=cutoff,
            intraday_after=target if entry_basis == "next_bar" else None)
        return ({**base, "status": "unavailable", "reason": "missing_exact_entry",
                 "missing_confirmation_sha256": confirmation_sha} if confirmation_sha else base)
    available_pairs = [(day, left, right) for day, left, right in zip(
        expected, asset, spy, strict=True) if left is not None and right is not None]
    missing = len(available_pairs) != len(expected)
    missing_rows = [(security, day) for day, left, right in zip(expected, asset, spy, strict=True)
                    for security, row in ((security_id, left), ("SPY", right)) if row is None]
    confirmation_sha = (_confirmed(
        verification_con, missing_confirmation, missing=missing_rows,
        through=sessions[-1], cutoff=cutoff) if missing else None)
    if missing and confirmation_sha is None:
        return base
    if not available_pairs:
        return {**base, "status": "unavailable", "reason": "missing_exit_reference"}
    exit_day, asset_exit, spy_exit = available_pairs[-1]
    used_rows = [row for pair in available_pairs for row in pair[1:]]
    if entry_basis == "next_bar" and any(
            entry_rows[leg][field] != entry_rows[0][field]
            for leg in (0, 1) for field in ("source", "price_basis")):
        return {**base, "status": "unavailable", "reason": "incompatible_price_basis"}
    if any(
            row[field] != entry_rows[leg][field]
            for _day_value, asset_row, spy_row in available_pairs
            for leg, row in enumerate((asset_row, spy_row))
            for field in ("source", "price_basis")
    ):
        return {**base, "status": "unavailable", "reason": "incompatible_price_basis"}
    asset_entry, spy_entry = float(entry_rows[0]["open"]), float(entry_rows[1]["open"])
    asset_return = float(asset_exit["close"]) / asset_entry - 1
    spy_return = float(spy_exit["close"]) / spy_entry - 1
    asset_net = float(asset_exit["close"]) * .999 / (asset_entry * 1.001) - 1
    spy_net = float(spy_exit["close"]) * .999 / (spy_entry * 1.001) - 1
    evidence = {"entry": entry_rows, "daily": used_rows,
                "missing_confirmation": missing_confirmation}
    return {**base, "status": "available", "exit_date": exit_day,
            "asset_return": asset_return, "spy_return": spy_return,
            "asset_net_return": asset_net, "spy_net_return": spy_net,
            "net_excess_return": asset_net - spy_net,
            "round_trip_cost_bps_each_leg": ROUND_TRIP_COST_BPS,
            "missing_bar_status": "last_available_close" if missing else "complete",
            "missing_confirmation_sha256": confirmation_sha,
            "next_session_bar": (entry_basis == "next_bar" and (
                target.astimezone(ET).date() > decided.astimezone(ET).date()
                or decided.astimezone(ET).time() < time(9, 30))),
            "source": entry_rows[0]["source"], "price_basis": entry_rows[0]["price_basis"],
            "price_series_sha256": canonical_sha256(evidence)}


def append_labels(con, rows: Iterable[dict], *, labelled_at: datetime) -> int:
    """Persist terminal labels; pending rows remain eligible for a later pass."""
    inserted = 0
    for row in rows:
        payload = make_label(
            decided_at=row["decided_at"], labelled_at=labelled_at,
            security_id=row["security_id"], horizon=row["horizon"],
            entry_basis=row["entry_basis"], daily_rows=row["daily_rows"],
            intraday_rows=row.get("intraday_rows", ()),
            missing_confirmation=row.get("missing_confirmation"),
            verification_con=con,
        )
        if payload["status"] == "pending":
            continue
        before = con.execute(
            "SELECT 1 FROM p16_filing_labels WHERE decision_sha256=? AND horizon=? "
            "AND entry_basis=?", [row["decision_sha256"], row["horizon"], row["entry_basis"]],
        ).fetchone()
        p16_filing_store.record_label(
            con, decision_sha256=row["decision_sha256"], horizon=row["horizon"],
            entry_basis=row["entry_basis"], labelled_at=labelled_at, payload=payload,
        )
        inserted += before is None
    return inserted


def circular_session_ci(values: list[float | None], *, horizon: int) -> dict:
    """Registered circular moving-block percentile interval over session positions."""
    if horizon not in HORIZONS:
        raise ValueError("filing report horizon is invalid")
    if any(value is not None and not math.isfinite(float(value)) for value in values):
        raise ValueError("filing bootstrap value is nonfinite")
    valid = [float(value) for value in values if value is not None]
    minimum, block = max(30, 6 * horizon), max(5, horizon)
    if len(valid) < minimum:
        return {"status": "descriptive_only", "valid_sessions": len(valid),
                "required_sessions": minimum, "lower": None, "upper": None}
    rng, size, draws = np.random.Generator(np.random.PCG64(BOOTSTRAP_SEED)), len(values), []
    for _ in range(BOOTSTRAP_DRAWS):
        indices = []
        while len(indices) < size:
            start = int(rng.integers(0, size))
            indices.extend((start + offset) % size for offset in range(block))
        sample = [values[index] for index in indices[:size] if values[index] is not None]
        if not sample:
            return {"status": "invalid_replicate", "valid_sessions": len(valid),
                    "required_sessions": minimum, "lower": None, "upper": None}
        draws.append(float(np.mean(sample)))
    lower, upper = np.quantile(draws, [0.025, 0.975], method="linear")
    return {"status": "available", "valid_sessions": len(valid),
            "required_sessions": minimum, "lower": float(lower), "upper": float(upper)}


def _primary(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    chosen, supplemental, seen = {}, [], set()
    for row in sorted(rows, key=lambda item: (
            item["issuer_id"], item["label"]["entry_session"],
            item["label"]["entry_basis"], _utc(item["eligible_at"], "eligible_at"),
            item["accession"], item["security_id"])):
        if (row["issuer_id"] != f"sec-cik:{row['cik']}" or
                _utc(row["eligible_at"], "eligible_at") > _utc(row["decided_at"], "decided_at")):
            raise ValueError("filing report identity or chronology differs")
        identity = (row["issuer_id"], row["accession"], row["security_id"],
                    row["label"]["entry_session"], row["label"]["entry_basis"],
                    row["label"]["horizon"])
        if identity in seen:
            raise ValueError("duplicate filing report observation")
        seen.add(identity)
        if row["security_id"] != row["primary_security_id"]:
            supplemental.append(row)
            continue
        key = (row["issuer_id"], row["label"]["entry_session"], row["label"]["entry_basis"])
        if key in chosen:
            supplemental.append(row)
        else:
            chosen[key] = row
    return list(chosen.values()), supplemental


def _ic(rows: list[dict], score_key: str) -> dict:
    if len({row["issuer_id"] for row in rows}) < 5:
        return {"value": None, "reason": "fewer_than_5_issuers"}
    scores = [float(row[score_key]) for row in rows]
    labels = [float(row["label"]["net_excess_return"]) for row in rows]
    if len(set(scores)) < 2:
        return {"value": None, "reason": "constant_score"}
    if len(set(labels)) < 2:
        return {"value": None, "reason": "constant_label"}
    return {"value": spearman(scores, labels), "reason": None}


def _state_counts(rows: Iterable[dict], *, cutoff: datetime,
                  label_rows: Iterable[dict] = ()) -> dict:
    states = Counter(state for row in rows for state in row.get("states", ()))
    for row in rows:
        reason = str(row.get("reason") or "").lower()
        if "timeout" in reason and "timeout" not in row.get("states", ()):
            states["timeout"] += 1
        deadline = row.get("deadline_at")
        if (deadline is not None and _utc(deadline, "deadline_at") <= cutoff
                and not {"complete", "scored", "unavailable"}.intersection(
                    row.get("states", ()))
                and "sla_miss" not in row.get("states", ())):
            states["sla_miss"] += 1
    states.update(
        "labelled" if row["label"].get("status") == "available" and
        _utc(row["label"]["labelled_at"], "labelled_at") <= cutoff else
        "label_unavailable" if row["label"].get("status") == "unavailable" and
        _utc(row["label"]["labelled_at"], "labelled_at") <= cutoff else "label_pending"
        for row in label_rows)
    states.update("label_last_available" for row in label_rows
                  if row["label"].get("missing_bar_status") == "last_available_close"
                  and _utc(row["label"]["labelled_at"], "labelled_at") <= cutoff)
    return {key: states[key] for key in STATE_NAMES}


def _daily(rows: list[dict], *, horizon: int, basis: str, cutoff: datetime,
           session_index: Iterable[str] = ()) -> list[dict]:
    sessions = defaultdict(list)
    for session in session_index:
        sessions[session]
    for row in rows:
        label = row["label"]
        if label.get("horizon") == horizon and label.get("entry_basis") == basis:
            sessions[label["entry_session"]].append(row)
    output = []
    score_key = "expected_excess_bp_10" if horizon == 10 else "expected_excess_bp_5"
    for session, members in sorted(sessions.items()):
        all_rows = [row for row in members if row["label"].get("status") == "available"
                    and _utc(row["label"]["labelled_at"], "labelled_at") <= cutoff
                    and row.get(score_key) is not None]
        if any(not math.isfinite(float(row[score_key])) or
               not math.isfinite(float(row["label"]["net_excess_return"])) for row in all_rows):
            raise ValueError("filing report value is nonfinite")
        paired = [row for row in all_rows if row.get("eps_yoy_sign") is not None and _known(row)]
        if any(row["eps_yoy_sign"] not in {-1, 0, 1} for row in paired):
            raise ValueError("filing EPS baseline is invalid")
        model_all, model_paired, eps_paired = (_ic(all_rows, score_key),
                                               _ic(paired, score_key), _ic(paired, "eps_yoy_sign"))
        tone_rows = [row for row in all_rows if row.get("tone") is not None]
        tone = _ic(tone_rows, "tone")
        output.append({"entry_session": session, "model_all_ic": model_all["value"],
                       "model_all_reason": model_all["reason"],
                       "model_paired_ic": model_paired["value"],
                       "model_paired_reason": model_paired["reason"],
                       "eps_paired_ic": eps_paired["value"],
                       "eps_paired_reason": eps_paired["reason"],
                       "tone_ic": tone["value"], "tone_reason": tone["reason"],
                       "paired_difference": (None if model_paired["value"] is None or
                                              eps_paired["value"] is None else
                                              model_paired["value"] - eps_paired["value"]),
                       "model_count": len(all_rows),
                       "paired_count": len(paired), "paired_excluded": len(all_rows) - len(paired),
                       "counts": _state_counts(members, cutoff=cutoff, label_rows=members)})
    return output


def _aggregate(daily: list[dict], key: str, horizon: int) -> dict:
    values = [row[key] for row in daily]
    valid = [value for value in values if value is not None]
    return {"mean": None if not valid else float(np.mean(valid)),
            "daily": values, "ci": circular_session_ci(values, horizon=horizon)}


def _known(row: dict) -> bool:
    known = row.get("counterpart_known_at")
    return known is not None and _utc(known, "counterpart_known_at") <= _utc(
        row["decided_at"], "decided_at"
    )


def _latency(rows: Iterable[dict], field: str) -> dict:
    values = []
    for row in rows:
        value = row.get(field)
        if value is None:
            continue
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise ValueError(f"filing {field} is invalid")
        values.append(float(value) / 1_000)
    values.sort()
    return {"seconds": values, "count": len(values),
            "p95_seconds": (float(np.quantile(values, .95, method="linear"))
                            if values else None)}


def _terminal_sla_failure(row: dict, cutoff: datetime) -> bool:
    states = set(row.get("states", ()))
    reason = str(row.get("reason") or "").lower()
    if states.intersection({"capacity_unavailable", "timeout", "sla_miss"}):
        return True
    if "capacity_unavailable" in reason or "timeout" in reason:
        return True
    deadline = row.get("deadline_at")
    return (deadline is not None and _utc(deadline, "deadline_at") <= cutoff
            and not states.intersection({"complete", "scored", "unavailable"}))


def _completeness_status(row: dict) -> str:
    explicit = row.get("source_status") or row.get("reason")
    if explicit:
        return str(explicit)
    states = set(row.get("states", ()))
    return next((name for name in ("capacity_unavailable", "timeout", "unavailable")
                 if name in states), "unknown")


def _category(rows: list[dict], field: str, *, horizon: int, cutoff: datetime,
              session_index: list[str]) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[str(row.get(field, "unknown"))].append(row)
    result = {}
    for key, members in sorted(groups.items()):
        sessions = defaultdict(list, {session: [] for session in session_index})
        missing = 0
        for row in members:
            label = row["label"]
            if (label.get("status") == "available" and
                    _utc(label["labelled_at"], "labelled_at") <= cutoff):
                sessions[label["entry_session"]].append(float(label["net_excess_return"]))
            else:
                sessions[label["entry_session"]]
                missing += 1
        daily = [float(np.mean(values)) if values else None
                 for _session, values in sorted(sessions.items())]
        valid = [value for value in daily if value is not None]
        result[key] = {"count": sum(len(values) for values in sessions.values()),
                       "missing": missing, "daily": daily,
                       "mean": None if not valid else float(np.mean(valid)),
                       "ci": circular_session_ci(daily, horizon=horizon)}
    return result


def filing_report(rows: Iterable[dict], *, horizon: int, basis: str,
                  generated_at: datetime, sec_status: str,
                  factor_neutral: dict | None = None,
                  lifecycle_rows: Iterable[dict] = ()) -> dict:
    """Build the registered primary and paired filing-IC report."""
    cutoff = _utc(generated_at, "generated_at")
    if horizon not in HORIZONS or basis not in BASES:
        raise ValueError("filing report horizon or basis is invalid")
    materialized = [dict(row) for row in rows if _utc(row["decided_at"], "decided_at") <= cutoff]
    for row in materialized:
        latency = row.get("retrieval_latency_ms")
        row["latency_bucket"] = ("unknown" if latency is None else "<=60" if latency <= 60_000
                                 else "61-300" if latency <= 300_000 else ">300")
        known = _known(row)
        row["counterpart_cross"] = (
            f"{row.get('headline_surprise', 'unknown')}|{row.get('consensus_surprise')}"
            if known else "unavailable_at_decision")
        row["guidance_cross"] = (f"{row.get('guidance_change', 'unknown')}|"
                                  f"{row.get('deterministic_guidance_change')}"
                                  if known else "unavailable_at_decision")
        if not known:
            row["eps_yoy_sign"] = row["consensus_surprise"] = None
            row["deterministic_guidance_change"] = None
        row["eps_baseline_category"] = (str(row["eps_yoy_sign"]) if known
                                         else "unavailable_at_decision")
    relevant = [row for row in materialized if row["label"].get("horizon") == horizon
                and row["label"].get("entry_basis") == basis]
    primary, supplemental = _primary(relevant)
    observed_sessions = sorted({_day(row["label"]["entry_session"]) for row in primary})
    if any(not nyse.is_session(day) for day in observed_sessions):
        raise ValueError("filing report entry session is invalid")
    session_days = observed_sessions[:1]
    while session_days and session_days[-1] < observed_sessions[-1]:
        session_days.append(nyse.next_session(session_days[-1]))
    session_index = [day.isoformat() for day in session_days]
    daily = _daily(primary, horizon=horizon, basis=basis, cutoff=cutoff,
                   session_index=session_index)
    lifecycle = [dict(row) for row in lifecycle_rows
                 if _utc(row["event_at"], "lifecycle event_at") <= cutoff
                 and row.get("horizon", horizon) == horizon
                 and row.get("entry_basis", basis) == basis]
    counts = _state_counts([*relevant, *lifecycle], cutoff=cutoff, label_rows=primary)
    latency_rows = [*relevant, *lifecycle]
    latencies = {
        "acceptance_to_discovery": _latency(latency_rows, "acceptance_to_discovery_ms"),
        "discovery_to_bundle": _latency(latency_rows, "discovery_to_bundle_ms"),
        "acceptance_to_retrieval": _latency(latency_rows, "acceptance_to_retrieval_ms"),
        "queue_delay": _latency(latency_rows, "queue_delay_ms"),
        "model": _latency(latency_rows, "model_latency_ms"),
        "retrieval_to_decision": _latency(relevant, "retrieval_latency_ms"),
    }
    acceptance_lag = latencies["acceptance_to_retrieval"]["seconds"]
    decision_lag = latencies["retrieval_to_decision"]["seconds"]
    terminal_failures = sum(_terminal_sla_failure(row, cutoff) for row in lifecycle)
    slow_decisions = sum(value > SLA_SECONDS for value in decision_lag)
    sla_misses = terminal_failures + slow_decisions
    counts["sla_miss"] = sla_misses
    secondary = {}
    for field in ("deterministic_event_kind", "model_event_kind", "item", "exhibit_status",
                  "company_reported_consensus", "size_tier", "liquidity_tier", "truncated",
                  "latency_bucket", "guidance_change", "headline_surprise",
                  "eps_baseline_category",
                  "counterpart_cross", "guidance_cross"):
        secondary[field] = _category(
            primary, field, horizon=horizon, cutoff=cutoff, session_index=session_index)
    score_key = "expected_excess_bp_10" if horizon == 10 else "expected_excess_bp_5"
    pooled = [row for row in primary if row["label"].get("status") == "available"
              and _utc(row["label"]["labelled_at"], "labelled_at") <= cutoff
              and row.get(score_key) is not None]
    paired = [row for row in pooled if row.get("eps_yoy_sign") is not None and _known(row)]
    pooled_model, pooled_paired, pooled_eps = (_ic(pooled, score_key),
                                               _ic(paired, score_key),
                                               _ic(paired, "eps_yoy_sign"))
    event_kinds = {kind: _daily(
        [row for row in primary if row.get("deterministic_event_kind") == kind],
        horizon=horizon, basis=basis, cutoff=cutoff, session_index=session_index,
    ) for kind in sorted({row.get("deterministic_event_kind", "unknown") for row in primary})}
    sensitivity_rows = [{**row, "label": ({**row["label"], "status": "unavailable"}
                        if row["label"].get("missing_bar_status") != "complete" else row["label"])}
                        for row in primary]
    complete_daily = _daily(sensitivity_rows, horizon=horizon, basis=basis, cutoff=cutoff,
                            session_index=session_index)
    successful_p95 = latencies["retrieval_to_decision"]["p95_seconds"]
    sla_denominator = len(decision_lag) + terminal_failures
    result = {"status": "available" if any(row["model_all_ic"] is not None for row in daily)
              else "insufficient", "horizon": horizon, "entry_basis": basis,
              "generated_at": cutoff.isoformat(), "sec_status": sec_status,
              "primary_count": len(primary), "supplemental_count": len(supplemental),
              "counts": counts, "acceptance_to_retrieval_seconds": acceptance_lag,
              "retrieval_to_decision_seconds": decision_lag, "daily": daily,
              "latencies": latencies,
              "retrieval_sla": {"target_seconds": SLA_SECONDS,
                                "status": ("censored_failures" if terminal_failures else
                                           "available" if decision_lag else "unavailable"),
                                "p95_seconds": (None if terminal_failures else successful_p95),
                                "conditional_success_p95_seconds": successful_p95,
                                "observed_decision_count": len(decision_lag),
                                "failure_count": terminal_failures,
                                "denominator": sla_denominator,
                                "miss_count": sla_misses,
                                "miss_rate": (sla_misses / sla_denominator
                                              if sla_denominator else None)},
              "source_completeness": dict(sorted(Counter(
                  _completeness_status(row) for row in latency_rows).items())),
              "pooled_event": {"model_all": pooled_model, "model_paired": pooled_paired,
                               "eps_paired": pooled_eps},
              "model_all": _aggregate(daily, "model_all_ic", horizon),
              "model_paired": _aggregate(daily, "model_paired_ic", horizon),
              "eps_paired": _aggregate(daily, "eps_paired_ic", horizon),
              "tone": _aggregate(daily, "tone_ic", horizon),
              "paired_difference": _aggregate(daily, "paired_difference", horizon),
              "complete_bar_sensitivity": _aggregate(
                  complete_daily, "model_all_ic", horizon),
              "by_deterministic_event_kind": {kind: {
                  "daily": values, "model_all": _aggregate(values, "model_all_ic", horizon),
                  "model_paired": _aggregate(values, "model_paired_ic", horizon),
                  "eps_paired": _aggregate(values, "eps_paired_ic", horizon),
                  "paired_difference": _aggregate(values, "paired_difference", horizon),
                  "tone": _aggregate(values, "tone_ic", horizon)}
                  for kind, values in event_kinds.items()},
              "factor_neutral": factor_neutral or {"status": "unavailable"},
              "secondary": secondary,
              "bootstrap": {"unit": "entry_session", "method": "circular_moving_block",
                            "block_length": max(5, horizon), "draws": BOOTSTRAP_DRAWS,
                            "bit_generator": "PCG64", "seed": BOOTSTRAP_SEED}}
    return {**result, "report_sha256": canonical_sha256(result)}
