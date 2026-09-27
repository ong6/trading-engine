"""Pre-entry evaluation-origin decisions for the fixed P16 challenger family.

This adapter owns no registered values.  Its caller supplies the committed
family identity, epoch, members, and already-retained challenger score
artifacts.  It records every family decision atomically before the next open;
it never manufactures a decision for a session whose forward entry passed.
"""
from __future__ import annotations

import math
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from engine import p15_event_sources, p16_features
from engine.lib.provenance import canonical_sha256
from engine.lib.util import table_exists
from farm import p16_eval_inputs, p16_factors
from server import p16_store
from sim import nyse

MIN_CANDIDATES = 20
ET = ZoneInfo("America/New_York")


class PreentryError(ValueError):
    """The registered family cannot record an honest pre-entry decision."""


def _aware(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise PreentryError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _member_rows(members: list[dict]) -> list[dict]:
    fields = {"comparison_id", "trial_id", "control_trial_id"}
    if not isinstance(members, list) or not members:
        raise PreentryError("P16 family members are absent")
    rows = []
    for member in members:
        if not isinstance(member, dict) or set(member) != fields:
            raise PreentryError("P16 family member identity is invalid")
        if any(not isinstance(member[field], str) or not member[field] for field in fields):
            raise PreentryError("P16 family member identity is invalid")
        rows.append(dict(member))
    if len({row["comparison_id"] for row in rows}) != len(rows) \
            or len({row["trial_id"] for row in rows}) != len(rows):
        raise PreentryError("P16 family members are duplicated")
    return rows


def session_index(epoch_session: date, market_date: date) -> int:
    """Return the fixed NYSE-grid index without observing retained rows."""
    if (not isinstance(epoch_session, date) or isinstance(epoch_session, datetime)
            or not isinstance(market_date, date) or isinstance(market_date, datetime)
            or not nyse.is_session(epoch_session) or not nyse.is_session(market_date)
            or market_date < epoch_session):
        raise PreentryError("P16 origin is outside the registered session grid")
    index, current = 0, epoch_session
    while current < market_date:
        current = nyse.next_session(current)
        index += 1
    if current != market_date:
        raise PreentryError("P16 origin is outside the registered session grid")
    return index


def _session_at(epoch_session: date, index: int) -> date:
    current = epoch_session
    for _ in range(index):
        current = nyse.next_session(current)
    return current


def _next_open(market_date: date) -> datetime:
    return datetime.combine(nyse.next_session(market_date), time(9, 30), ET).astimezone(
        timezone.utc)


def _session_close(market_date: date) -> datetime:
    return datetime.combine(
        market_date, p15_event_sources.session_close(market_date), ET,
    ).astimezone(timezone.utc)


def _due_endpoint(epoch_session: date, generated_at: datetime) -> int:
    if not nyse.is_session(epoch_session):
        raise PreentryError("P16 sequential epoch is invalid")
    cutoff, index, current = _aware(generated_at, "report time"), -1, epoch_session
    while _next_open(current) <= cutoff:
        index += 1
        current = nyse.next_session(current)
    return index


def grid_report(
    con, *, registration_sha256: str, family_id: str, epoch_session: date,
    members: list[dict], generated_at: datetime,
) -> dict:
    """Report permanent missed decisions on the literal exchange-session grid."""
    rows = _member_rows(members)
    cutoff = _aware(generated_at, "report time")
    endpoint = _due_endpoint(epoch_session, cutoff)
    expected = list(range(endpoint + 1))
    comparisons = []
    for member in rows:
        retained = []
        if table_exists(con, "p16_sequential_origin_events"):
            raw = con.execute(
                "SELECT * FROM p16_sequential_origin_events "
                "WHERE registration_sha256=? AND family_id=? AND comparison_id=? "
                "AND trial_id=? AND control_trial_id=? AND event_kind='decision' "
                "AND recorded_at<=? ORDER BY session_index",
                [registration_sha256, family_id, member["comparison_id"],
                 member["trial_id"], member["control_trial_id"],
                 cutoff.replace(tzinfo=None)],
            ).fetchall()
            retained = [p16_store._sequential_row(row) for row in raw]
        indices = [row["session_index"] for row in retained]
        missing = [index for index in expected if index not in indices]
        comparisons.append({
            "comparison_id": member["comparison_id"],
            "retained_decision_indices": indices,
            "missing_session_indices": missing,
            "missing_market_dates": [
                _session_at(epoch_session, index).isoformat() for index in missing
            ],
        })
    missing_dates = sorted({day for row in comparisons
                            for day in row["missing_market_dates"]})
    missing_indices = sorted({index for row in comparisons
                              for index in row["missing_session_indices"]})
    body = {
        "schema_version": 1, "registration_sha256": registration_sha256,
        "family_id": family_id, "epoch_session": epoch_session.isoformat(),
        "report_at": cutoff.isoformat(), "expected_through_session_index": endpoint,
        "status": "blocked_missing_origin_decision" if missing_dates else "on_schedule",
        "first_permanently_missing_session_index": (
            missing_indices[0] if missing_indices else None),
        "first_permanently_missing_origin": missing_dates[0] if missing_dates else None,
        "comparisons": comparisons, "execution_authority": "none",
    }
    return {**body, "grid_report_sha256": canonical_sha256(body)}


def _score_artifacts(
    con, *, registration_sha256: str, market_date: date,
    information_cutoff_at: str, members: list[dict],
    score_artifact_sha256s: list[str], visible_at: datetime,
) -> dict[str, tuple[str, dict]]:
    if (not isinstance(score_artifact_sha256s, list)
            or score_artifact_sha256s != sorted(set(score_artifact_sha256s))):
        raise PreentryError("P16 score artifact identities are invalid")
    expected = {row["comparison_id"] for row in members}
    expected_cutoff = _aware(
        datetime.fromisoformat(information_cutoff_at.replace("Z", "+00:00")),
        "scoring information cutoff",
    )
    result = {}
    for artifact_id in score_artifact_sha256s:
        artifact = p16_store._artifact_by_id(con, artifact_id, visible_at=visible_at)
        policy_id = artifact["artifact_key"]
        if (artifact["artifact_kind"] != "policy_scores"
                or artifact["registration_sha256"] != registration_sha256
                or artifact["market_date"] != market_date or policy_id not in expected
                or _aware(datetime.fromisoformat(
                    artifact["payload"].get("information_cutoff_at", "").replace(
                        "Z", "+00:00")), "score information cutoff") != expected_cutoff
                or policy_id in result):
            raise PreentryError("P16 score artifact differs from the registered origin")
        result[policy_id] = (artifact_id, artifact["payload"])
    if set(result) != expected:
        raise PreentryError("P16 score artifacts do not cover the registered family")
    return result


def _decision_status(decision_rows: list[dict], scores: dict) -> tuple[str, str | None]:
    champion = {row.get("ticker"): row.get("champion_score") for row in decision_rows}
    if (len(champion) != len(decision_rows) or None in champion
            or set(scores) != set(champion)):
        raise PreentryError("P16 pre-entry candidate set differs")
    paired = [(challenger, champion[ticker]) for ticker, challenger in scores.items()
              if all(isinstance(value, (int, float)) and not isinstance(value, bool)
                     and math.isfinite(float(value))
                     for value in (challenger, champion[ticker]))]
    if len(paired) < MIN_CANDIDATES:
        return "decision_unavailable", "fewer_than_20_candidates"
    challenger_values, champion_values = zip(*paired, strict=True)
    if len(set(challenger_values)) == 1 or len(set(champion_values)) == 1:
        return "decision_unavailable", "constant_scores"
    return "eligible", None


def record_preentry(
    con, *, registration_sha256: str, family_id: str, epoch_session: date,
    members: list[dict], market_date: date, score_artifact_sha256s: list[str],
    recorded_at: datetime,
) -> dict:
    """Record one complete family origin before its forward entry."""
    rows = _member_rows(members)
    now = _aware(recorded_at, "recorded at")
    index = session_index(epoch_session, market_date)
    close_at, forward_entry_at = _session_close(market_date), _next_open(market_date)
    if not close_at < now < forward_entry_at:
        raise PreentryError("P16 origin must be recorded after close and before next open")
    origin = p16_eval_inputs.load_origin(
        con, market_date=market_date, report_cutoff=now,
    )
    decision_rows = origin.get("decision_rows")
    if not isinstance(decision_rows, list) or not decision_rows:
        raise PreentryError("P16 origin lacks pre-entry decision rows")
    tickers = [row.get("ticker") for row in decision_rows]
    if len(tickers) != len(set(tickers)) or any(not isinstance(item, str) or not item
                                                for item in tickers):
        raise PreentryError("P16 origin pre-entry candidates are invalid")
    exposure = p16_features.exposure_snapshot(
        con, tickers, market_date,
        information_cutoff_at=datetime.fromisoformat(
            origin["scoring_information_cutoff_at"].replace("Z", "+00:00")),
    )
    score_rows = _score_artifacts(
        con, registration_sha256=registration_sha256, market_date=market_date,
        information_cutoff_at=origin["scoring_information_cutoff_at"], members=rows,
        score_artifact_sha256s=score_artifact_sha256s, visible_at=now,
    )
    challenger_scores = {key: value[1] for key, value in score_rows.items()}
    probe = p16_factors.evaluate_origin(
        origin, exposure, challenger_scores=challenger_scores,
    )
    if probe.get("status") != "pending" or probe.get("reason") != "origin_labels_unresolved":
        raise PreentryError("P16 pre-entry factor probe unexpectedly became terminal")
    origin_id = p16_store.record_evaluation_input(
        con, registration_sha256=registration_sha256, payload=origin, recorded_at=now,
    )
    exposure_id = p16_store.record_exposure_snapshot(
        con, registration_sha256=registration_sha256, payload=exposure, recorded_at=now,
    )
    decisions = []
    for member in rows:
        source_id, score = score_rows[member["comparison_id"]]
        status, reason = _decision_status(decision_rows, score["scores"])
        event_id = p16_store.record_origin_decision(
            con, registration_sha256=registration_sha256, family_id=family_id,
            comparison_id=member["comparison_id"], trial_id=member["trial_id"],
            control_trial_id=member["control_trial_id"], epoch_session=epoch_session,
            session_index=index, market_date=market_date, status=status, reason=reason,
            decided_at=now, forward_entry_at=forward_entry_at,
            source_artifact_sha256=source_id, recorded_at=now,
        )
        decisions.append({
            "comparison_id": member["comparison_id"], "status": status,
            "reason": reason, "event_sha256": event_id,
        })
    body = {
        "status": "recorded", "family_id": family_id,
        "market_date": market_date.isoformat(), "session_index": index,
        "forward_entry_at": forward_entry_at.isoformat(),
        "evaluation_input_sha256": origin_id, "exposure_artifact_sha256": exposure_id,
        "factor_probe_sha256": probe["factor_report_sha256"],
        "decisions": decisions, "execution_authority": "none",
    }
    return {**body, "preentry_sha256": canonical_sha256(body)}
