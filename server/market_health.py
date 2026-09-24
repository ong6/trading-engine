"""Read-only market freshness and independent-price evidence projections."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sim import nyse

from .read_model_utils import (
    require_public_nonnegative_integer,
    require_public_nonnegative_number,
    require_public_positive_number,
    require_public_ticker,
)
from .status_validation import iso_date, iso_timestamp, metadata_timestamp, nonnegative_int

log = logging.getLogger(__name__)

_PRICE_COUNT_FIELDS = (
    "names_selected",
    "names_checked",
    "names_agreeing",
    "names_disagreeing",
    "names_not_checked",
    "n_disagreements",
    "n_material",
    "n_parse_errors",
)
PRICE_DISAGREEMENT_LIMIT = 20
PRICE_DIFF_BP_ROUNDING_TOLERANCE = 0.005_2
_PRICE_FIELDS = frozenset({"open", "high", "low", "close"})
_PRICE_DISAGREEMENT_FIELDS = frozenset(
    {"ticker", "date", "field", "store", "source", "diff_bp"}
)


def _utc_today() -> date:
    """Return the operational calendar date used by UTC cron and reports."""
    return datetime.now(timezone.utc).date()


def _freshness_payload(
    *,
    status: str,
    as_of: date,
    latest: date | None,
    calendar_days: int | None,
    missing: list[date] | None,
    next_session: date | None,
) -> dict:
    return {
        "status": status,
        "as_of": as_of,
        "latest_date": latest,
        "calendar_days": calendar_days,
        "missing_completed_sessions": len(missing) if missing is not None else None,
        "first_missing_session": missing[0] if missing else None,
        "last_missing_session": missing[-1] if missing else None,
        "next_session": next_session,
    }


def _missing_sessions(latest: date, as_of: date) -> list[date]:
    missing = []
    cursor = latest + timedelta(days=1)
    while cursor < as_of:
        if nyse.is_session(cursor):
            missing.append(cursor)
        cursor += timedelta(days=1)
    return missing


def _known_freshness(latest: date, as_of: date) -> dict:
    calendar_days = (as_of - latest).days
    if calendar_days < 0:
        return _freshness_payload(
            status="future",
            as_of=as_of,
            latest=latest,
            calendar_days=calendar_days,
            missing=[],
            next_session=None,
        )
    missing = _missing_sessions(latest, as_of)
    return _freshness_payload(
        status="stale" if missing else "ok",
        as_of=as_of,
        latest=latest,
        calendar_days=calendar_days,
        missing=missing,
        next_session=nyse.next_session(latest),
    )


def freshness(latest: date | None, as_of: date | None = None) -> dict:
    """Describe data age in scheduled sessions, not just calendar days.

    Only sessions strictly before ``as_of`` are expected. This gives the current
    trading day and the 22:30 UTC collector its normal completion window while
    still identifying a missed prior session on the following calendar day.
    """
    as_of = as_of or _utc_today()
    if latest is None:
        return _freshness_payload(
            status="unknown",
            as_of=as_of,
            latest=None,
            calendar_days=None,
            missing=None,
            next_session=None,
        )

    return _known_freshness(latest, as_of)


def _price_diff_bp(item: dict, store: int | float, source: int | float) -> int | float:
    """Require the producer's rounded gap to match its six-decimal published prices."""
    diff_bp = require_public_nonnegative_number(
        item["diff_bp"], "price disagreement basis-point difference"
    )
    calculated_diff_bp = abs(store - source) / max(store, source) * 10_000.0
    if abs(diff_bp - calculated_diff_bp) > PRICE_DIFF_BP_ROUNDING_TOLERANCE:
        raise ValueError("price disagreement basis-point difference does not reconcile")
    return diff_bp


def _price_disagreements(
    raw: dict,
    as_of: date,
    count: int,
    names_disagreeing: int,
    material_count: int,
    material_bp: int | float,
    tolerance_bp: int | float,
    tolerance_abs_usd: int | float,
) -> list[dict]:
    details = raw["disagreements"]
    if not isinstance(details, list) or len(details) != min(count, PRICE_DISAGREEMENT_LIMIT):
        raise ValueError("price disagreement details do not reconcile")

    projected: list[dict] = []
    identities: set[tuple[str, date, str]] = set()
    tickers: set[str] = set()
    previous_diff: int | float | None = None
    for item in details:
        if not isinstance(item, dict) or set(item) != _PRICE_DISAGREEMENT_FIELDS:
            raise ValueError("price disagreement detail is malformed")
        ticker = require_public_ticker(item["ticker"])
        disagreement_date = iso_date(item["date"], "price disagreement date is invalid")
        field = item["field"]
        if disagreement_date > as_of or field not in _PRICE_FIELDS:
            raise ValueError("price disagreement identity is invalid")
        identity = (ticker, disagreement_date, field)
        if identity in identities:
            raise ValueError("price disagreement detail is duplicated")
        identities.add(identity)
        tickers.add(ticker)
        store = require_public_positive_number(item["store"], "price disagreement store value")
        source = require_public_positive_number(item["source"], "price disagreement source value")
        diff_bp = _price_diff_bp(item, store, source)
        if diff_bp <= tolerance_bp or abs(store - source) < tolerance_abs_usd:
            raise ValueError("price disagreement does not exceed both tolerances")
        if previous_diff is not None and diff_bp > previous_diff:
            raise ValueError("price disagreement details are not worst-first")
        previous_diff = diff_bp
        projected.append(
            {
                "ticker": ticker,
                "date": disagreement_date,
                "field": field,
                "store": store,
                "source": source,
                "diff_bp": diff_bp,
            }
        )
    if len(tickers) > names_disagreeing or (
        count <= PRICE_DISAGREEMENT_LIMIT and len(tickers) != names_disagreeing
    ):
        raise ValueError("price disagreement ticker count does not reconcile")
    listed_material = sum(item["diff_bp"] > material_bp for item in projected)
    if listed_material != min(material_count, PRICE_DISAGREEMENT_LIMIT):
        raise ValueError("material price disagreement details do not reconcile")
    return projected


def _price_evidence(
    raw: dict,
) -> tuple[
    datetime,
    date,
    dict[str, int],
    list[dict],
    int | float,
    int | float,
    int | float,
]:
    verified_at = metadata_timestamp(raw)
    as_of = iso_date(raw["as_of"], "price verification as_of must be YYYY-MM-DD")
    counts = {
        field: require_public_nonnegative_integer(nonnegative_int(raw, field))
        for field in _PRICE_COUNT_FIELDS
    }
    if counts["names_checked"] + counts["names_not_checked"] != counts["names_selected"]:
        raise ValueError("selected-name accounting does not reconcile")
    if counts["names_agreeing"] + counts["names_disagreeing"] != counts["names_checked"]:
        raise ValueError("checked-name accounting does not reconcile")
    if counts["n_material"] > counts["n_disagreements"]:
        raise ValueError("material disagreements exceed total disagreements")
    if counts["names_disagreeing"] > counts["n_disagreements"]:
        raise ValueError("disagreeing names exceed disagreement rows")
    tolerance_bp = require_public_positive_number(
        raw["tolerance_bp"], "price verification relative tolerance"
    )
    tolerance_abs_usd = require_public_positive_number(
        raw["tolerance_abs_usd"], "price verification absolute tolerance"
    )
    material_bp = require_public_positive_number(
        raw["material_bp"], "price verification material threshold"
    )
    if material_bp < tolerance_bp:
        raise ValueError("material threshold is below the disagreement tolerance")
    disagreements = _price_disagreements(
        raw,
        as_of,
        counts["n_disagreements"],
        counts["names_disagreeing"],
        counts["n_material"],
        material_bp,
        tolerance_bp,
        tolerance_abs_usd,
    )
    return (
        verified_at,
        as_of,
        counts,
        disagreements,
        material_bp,
        tolerance_bp,
        tolerance_abs_usd,
    )


def _successful_driver_start(driver: dict | None) -> datetime | None:
    if not driver or driver.get("status") != "ok":
        return None
    return iso_timestamp(
        driver["started_at"], "driver started_at must be a canonical ISO timestamp"
    ).astimezone(timezone.utc)


def _price_evidence_state(
    verified_at: datetime,
    as_of: date,
    counts: dict[str, int],
    latest: date | None,
    nightly_started: datetime | None,
    checked_at: datetime,
) -> tuple[str, str | None]:
    if verified_at > checked_at:
        return "invalid", "future-verification"
    if latest is None:
        return "unknown", "market-date-unavailable"
    if as_of > latest:
        return "invalid", "future-market-date"
    if as_of < latest:
        return "stale", "market-date-behind"
    if nightly_started is not None and verified_at < nightly_started:
        return "stale", "not-refreshed-by-latest-nightly"
    if counts["names_checked"] == 0:
        return "incomplete", "no-names-checked"
    if counts["n_disagreements"] or counts["n_parse_errors"]:
        return "issues", "disagreements-or-parse-errors"
    if counts["names_not_checked"]:
        return "partial", "selected-names-not-checked"
    return "current", None


def _checked_at(now: datetime | None) -> datetime:
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        return checked_at.replace(tzinfo=timezone.utc)
    return checked_at.astimezone(timezone.utc)


def _price_verification_result(
    status: str,
    reason: str | None,
    as_of: date,
    verified_at: datetime,
    counts: dict[str, int],
    disagreements: list[dict],
    material_bp: int | float,
    tolerance_bp: int | float,
    tolerance_abs_usd: int | float,
) -> dict:
    result = {
        "status": status,
        "as_of": as_of,
        "verified_at": verified_at.isoformat(),
        **counts,
        "material_bp": material_bp,
        "tolerance_bp": tolerance_bp,
        "tolerance_abs_usd": tolerance_abs_usd,
        "disagreements": disagreements,
        "disagreements_limit": PRICE_DISAGREEMENT_LIMIT,
        "disagreements_matching_count": counts["n_disagreements"],
        "disagreements_truncated": counts["n_disagreements"] > len(disagreements),
    }
    if reason is not None:
        result["reason"] = reason
    return result


def price_verification(
    meta: dict,
    latest: date | None,
    nightly: dict | None,
    *,
    now: datetime | None = None,
) -> dict:
    """Validate the latest independent-price evidence, not just its shell run."""
    raw = meta.get("price_verify")
    if raw is None:
        return {"status": "missing"}
    if not isinstance(raw, dict):
        return {"status": "invalid", "reason": "not-an-object"}

    try:
        (
            verified_at,
            as_of,
            counts,
            disagreements,
            material_bp,
            tolerance_bp,
            tolerance_abs_usd,
        ) = _price_evidence(raw)
        nightly_started = _successful_driver_start(nightly)
    except (KeyError, TypeError, ValueError) as exc:
        log.warning("price-verification evidence validation failed", exc_info=exc)
        return {"status": "invalid", "reason": "malformed-evidence"}

    status, reason = _price_evidence_state(
        verified_at, as_of, counts, latest, nightly_started, _checked_at(now)
    )
    return _price_verification_result(
        status,
        reason,
        as_of,
        verified_at,
        counts,
        disagreements,
        material_bp,
        tolerance_bp,
        tolerance_abs_usd,
    )
