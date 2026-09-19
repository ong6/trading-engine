"""Read-only review packets for exact provider-source/cache discrepancies.

Each packet binds one newest verified source observation to the corresponding
current operational-cache row. It is diagnostic evidence only: it cannot
change a cache row, activate a quarantine, select a resolution, or grant
trading authority.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone

import duckdb

from engine import verify_prices
from engine.lib.provenance import canonical_sha256

from . import agent_independent_price_evidence, agent_provider_responses
from .read_model_utils import require_public_ticker
from .status_validation import iso_date, iso_timestamp

REVIEW_SCHEMA_VERSION = 2
REVIEW_SCOPE = "one_exact_provider_source_cache_discrepancy"
REVIEW_TTL_SECONDS = 3600
STATUS = "awaiting_operator_adjudication"
DISCREPANCY_LIST_LIMIT = 100
DATASETS = frozenset({"daily_price", "corporate_action"})
ACTION_KINDS = frozenset({"dividend", "split"})
OPERATOR_DECISIONS = (
    "accept_source_revision_via_separate_guarded_repair",
    "retain_current_cache_with_justification",
    "quarantine_ticker",
    "defer_pending_more_evidence",
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class DataDiscrepancyReviewError(ValueError):
    """One discrepancy cannot be safely represented or revalidated."""


def _utc(value: object, label: str) -> datetime:
    if (
        type(value) is not datetime
        or value.utcoffset() is None
        or value.utcoffset().total_seconds() != 0
    ):
        raise DataDiscrepancyReviewError(f"{label} must be UTC")
    return value.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return _utc(value, "review timestamp").isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise DataDiscrepancyReviewError(f"{label} is invalid")
    try:
        parsed = iso_timestamp(value, f"{label} is invalid")
    except ValueError as exc:
        raise DataDiscrepancyReviewError(f"{label} is invalid") from exc
    if _timestamp(parsed) != value:
        raise DataDiscrepancyReviewError(f"{label} is invalid")
    return parsed


def _key(dataset: object, ticker: object, fact_date: object, kind: object) -> tuple:
    if (
        not isinstance(dataset, str)
        or dataset not in DATASETS
        or type(fact_date) is not date
        or not isinstance(kind, str)
    ):
        raise DataDiscrepancyReviewError("discrepancy fact identity is invalid")
    try:
        ticker = require_public_ticker(ticker)
    except ValueError as exc:
        raise DataDiscrepancyReviewError("discrepancy fact identity is invalid") from exc
    if ticker != ticker.upper():
        raise DataDiscrepancyReviewError("discrepancy fact identity is invalid")
    if (
        dataset == "daily_price"
        and kind != "daily_price"
        or dataset == "corporate_action"
        and kind not in ACTION_KINDS
    ):
        raise DataDiscrepancyReviewError("discrepancy fact identity is invalid")
    return dataset, ticker, fact_date, kind


def _finite_positive(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise DataDiscrepancyReviewError(f"{label} is invalid")
    return float(value)


def _cache_fact(
    con: duckdb.DuckDBPyConnection,
    dataset: str,
    ticker: str,
    fact_date: date,
    kind: str,
) -> dict | None:
    if dataset == "daily_price":
        rows = con.execute(
            "SELECT ticker, date, open, high, low, close, volume, source, fetched_at "
            "FROM prices WHERE ticker = ? AND date = ?",
            [ticker, fact_date],
        ).fetchall()
        if len(rows) > 1:
            raise DataDiscrepancyReviewError("current cache fact is ambiguous")
        if not rows:
            return None
        row = rows[0]
        open_value = _finite_positive(row[2], "cache open")
        high_value = _finite_positive(row[3], "cache high")
        low_value = _finite_positive(row[4], "cache low")
        close_value = _finite_positive(row[5], "cache close")
        if (
            isinstance(row[6], bool)
            or not isinstance(row[6], int)
            or row[6] < 0
            or low_value > min(open_value, high_value, close_value)
            or high_value < max(open_value, low_value, close_value)
        ):
            raise DataDiscrepancyReviewError("current cache daily price is invalid")
        value = {
            "ticker": row[0],
            "market_date": row[1].isoformat(),
            "open": open_value,
            "high": high_value,
            "low": low_value,
            "close": close_value,
            "volume": row[6],
            "source": row[7],
        }
        fetched_at = row[8]
    else:
        rows = con.execute(
            "SELECT ticker, ex_date, kind, value, source, fetched_at "
            "FROM corporate_actions "
            "WHERE ticker = ? AND ex_date = ? AND kind = ?",
            [ticker, fact_date, kind],
        ).fetchall()
        if len(rows) > 1:
            raise DataDiscrepancyReviewError("current cache fact is ambiguous")
        if not rows:
            return None
        row = rows[0]
        value = {
            "ticker": row[0],
            "ex_date": row[1].isoformat(),
            "kind": row[2],
            "value": _finite_positive(row[3], "cache corporate-action value"),
            "source": row[4],
        }
        fetched_at = row[5]
    if value["source"] != agent_provider_responses.SOURCE_NAME:
        raise DataDiscrepancyReviewError("current cache source is invalid")
    try:
        fetched = agent_provider_responses._timestamp(fetched_at)
    except (TypeError, ValueError) as exc:
        raise DataDiscrepancyReviewError(
            "current cache ingestion time is invalid"
        ) from exc
    return {
        "value": value,
        "value_sha256": canonical_sha256(value),
        "latest_ingested_at": fetched,
    }


def _source_fact(
    con: duckdb.DuckDBPyConnection,
    dataset: str,
    ticker: str,
    fact_date: date,
    kind: str,
) -> dict:
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_provider_source_observations'"
    ).fetchone()
    if exists is None:
        raise DataDiscrepancyReviewError("source observation ledger is unavailable")
    row = con.execute(
        "SELECT * FROM agent_provider_source_observations "
        "WHERE dataset = ? AND ticker = ? AND fact_date = ? AND kind = ? "
        "ORDER BY observation_sequence DESC LIMIT 1",
        [dataset, ticker, fact_date, kind],
    ).fetchone()
    if row is None:
        raise DataDiscrepancyReviewError("source observation is unavailable")
    try:
        source = agent_provider_responses._stored_source_observation(con, row)
    except agent_provider_responses.ProviderResponseError as exc:
        raise DataDiscrepancyReviewError(str(exc)) from exc
    normalized = source["normalized"]
    value = {
        key: normalized[key]
        for key in (
            (
                "ticker",
                "market_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "source",
            )
            if dataset == "daily_price"
            else ("ticker", "ex_date", "kind", "value", "source")
        )
    }
    return {
        "value": value,
        "value_sha256": source["value_sha256"],
        "observation_sha256": source["observation_sha256"],
        "observation_sequence": source["observation_sequence"],
        "value_revision": source["value_revision"],
        "classification": source["classification"],
        "source_fetched_at": source["source_fetched_at"],
        "observed_at": source["observed_at"],
        "receipt_sha256": source["receipt_sha256"],
        "response_sha256": source["response_sha256"],
        "source_adapter": source["source_adapter"],
        "source_adapter_version": source["source_adapter_version"],
        "source_library_version": source["source_library_version"],
    }


def _source_confirmations(
    con: duckdb.DuckDBPyConnection,
    *,
    dataset: str,
    ticker: str,
    fact_date: date,
    kind: str,
    value_sha256: str,
) -> dict:
    matches = []
    for row in con.execute(
        "SELECT provider_ticker, received_at, response_sha256, "
        "receipt_sha256, response_body FROM agent_provider_responses "
        "WHERE ticker = ? ORDER BY received_at, id",
        [ticker],
    ).fetchall():
        for fact in agent_provider_responses._facts(
            bytes(row[4]), ticker, row[0]
        ):
            if (
                fact["dataset"],
                fact["ticker"],
                fact["fact_date"],
                fact["kind"],
                fact["value_sha256"],
            ) == (dataset, ticker, fact_date, kind, value_sha256):
                matches.append(row)
    if not matches:
        raise DataDiscrepancyReviewError(
            "source observation has no confirming retained response"
        )
    latest = matches[-1]
    return {
        "matching_response_count": len(matches),
        "latest_received_at": agent_provider_responses._timestamp(latest[1]),
        "latest_response_sha256": latest[2],
        "latest_receipt_sha256": latest[3],
    }


def discrepancies(con: duckdb.DuckDBPyConnection) -> dict:
    """List bounded discrepancy identities and hashes, never market values."""
    try:
        agent_provider_responses._verify(con)
    except agent_provider_responses.ProviderResponseError as exc:
        raise DataDiscrepancyReviewError(str(exc)) from exc
    source_table = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_provider_source_observations'"
    ).fetchone()
    latest = (
        []
        if source_table is None
        else con.execute(
            "SELECT dataset, ticker, fact_date, kind, value_sha256, "
            "observation_sha256, source_fetched_at FROM ("
            "SELECT dataset, ticker, fact_date, kind, value_sha256, "
            "observation_sha256, source_fetched_at, ROW_NUMBER() OVER ("
            "PARTITION BY dataset, ticker, fact_date, kind "
            "ORDER BY observation_sequence DESC"
            ") AS newest FROM agent_provider_source_observations"
            ") WHERE newest = 1 ORDER BY dataset, ticker, fact_date, kind"
        ).fetchall()
    )
    available_tables = {
        row[0]
        for row in con.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name IN ('prices', 'corporate_actions')"
        ).fetchall()
    }
    items = []
    for (
        dataset,
        ticker,
        fact_date,
        kind,
        source_value_sha256,
        source_observation_sha256,
        source_fetched_at,
    ) in latest:
        try:
            cache_value_sha256 = agent_provider_responses._cache_value_sha256(
                con,
                dataset=dataset,
                ticker=ticker,
                fact_date=fact_date,
                kind=kind,
                available_tables=available_tables,
            )
        except agent_provider_responses.ProviderResponseError as exc:
            raise DataDiscrepancyReviewError(str(exc)) from exc
        if cache_value_sha256 == source_value_sha256:
            continue
        item = {
            "dataset": dataset,
            "ticker": ticker,
            "fact_date": fact_date.isoformat(),
            "kind": kind,
            "classification": (
                "missing_current_cache_row"
                if cache_value_sha256 is None
                else "current_cache_value_drift"
            ),
            "source_value_sha256": source_value_sha256,
            "cache_value_sha256": cache_value_sha256,
            "source_observation_sha256": source_observation_sha256,
            "source_fetched_at": agent_provider_responses._timestamp(
                source_fetched_at
            ),
        }
        items.append({**item, "discrepancy_sha256": canonical_sha256(item)})
    matching_count = len(items)
    return {
        "schema_version": 1,
        "status": (
            "discrepancies_detected"
            if matching_count
            else "no_discrepancies_detected"
        ),
        "matching_count": matching_count,
        "limit": DISCREPANCY_LIST_LIMIT,
        "truncated": matching_count > DISCREPANCY_LIST_LIMIT,
        "items": items[:DISCREPANCY_LIST_LIMIT],
        "market_values_exposed": False,
        "automatic_recommendation": None,
        "cache_mutation_implemented": False,
        "quarantine_mutation_implemented": False,
        "execution_authority": "none",
    }


def _differences(source_value: dict, cache_value: dict | None) -> list[dict]:
    fields = sorted(source_value)
    if cache_value is None:
        return [
            {
                "field": field,
                "cache_value": None,
                "source_value": source_value[field],
            }
            for field in fields
        ]
    if set(cache_value) != set(source_value):
        raise DataDiscrepancyReviewError("source and cache fact shapes differ")
    return [
        {
            "field": field,
            "cache_value": cache_value[field],
            "source_value": source_value[field],
        }
        for field in fields
        if cache_value[field] != source_value[field]
    ]


def _price_value_without_source(value: dict) -> dict:
    fields = {
        "ticker",
        "market_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    if not isinstance(value, dict) or not fields.issubset(value):
        raise DataDiscrepancyReviewError(
            "independent price comparison shape is invalid"
        )
    return {field: value[field] for field in sorted(fields)}


def _named_differences(
    first: dict,
    second: dict | None,
    *,
    first_label: str,
    second_label: str,
) -> list[dict]:
    if second is None:
        return [
            {
                "field": field,
                first_label: first[field],
                second_label: None,
            }
            for field in sorted(first)
        ]
    if set(first) != set(second):
        raise DataDiscrepancyReviewError(
            "independent price comparison shape is invalid"
        )
    return [
        {
            "field": field,
            first_label: first[field],
            second_label: second[field],
        }
        for field in sorted(first)
        if first[field] != second[field]
    ]


def _price_comparison(first: dict, second: dict | None) -> dict:
    """Apply the verifier's registered OHLC tolerance; report volume separately."""
    if second is None:
        return {
            "comparable": False,
            "ohlc_agree_within_registered_tolerance": False,
            "tolerance_bp": verify_prices.TOLERANCE_BP,
            "tolerance_abs_usd": verify_prices.TOLERANCE_ABS_USD,
            "maximum_ohlc_difference_bp": None,
            "volume_difference_pct": None,
        }
    differences = []
    for field in ("open", "high", "low", "close"):
        first_value = float(first[field])
        second_value = float(second[field])
        differences.append(
            {
                "bp": verify_prices._diff_bp(first_value, second_value),
                "absolute": abs(first_value - second_value),
            }
        )
    first_volume = float(first["volume"])
    second_volume = float(second["volume"])
    volume_denominator = max(first_volume, second_volume)
    volume_difference_pct = (
        0.0
        if volume_denominator == 0
        else abs(first_volume - second_volume) / volume_denominator * 100.0
    )
    return {
        "comparable": True,
        "ohlc_agree_within_registered_tolerance": not any(
            item["bp"] > verify_prices.TOLERANCE_BP
            and item["absolute"] >= verify_prices.TOLERANCE_ABS_USD
            for item in differences
        ),
        "tolerance_bp": verify_prices.TOLERANCE_BP,
        "tolerance_abs_usd": verify_prices.TOLERANCE_ABS_USD,
        "maximum_ohlc_difference_bp": round(
            max(item["bp"] for item in differences), 6
        ),
        "volume_difference_pct": round(volume_difference_pct, 6),
    }


def _independent_evidence(
    con: duckdb.DuckDBPyConnection,
    *,
    dataset: str,
    ticker: str,
    fact_date: date,
    source_value: dict,
    cache_value: dict | None,
) -> dict:
    """Load one exact Nasdaq fact and compare values without source labels."""
    if dataset != "daily_price":
        return {
            "status": "not_supported_for_dataset",
            "source": agent_independent_price_evidence.SOURCE_NAME,
            "raw_response_body_retained": False,
            "execution_authority": "none",
        }
    try:
        evidence = agent_independent_price_evidence.evidence_for_fact(
            con,
            ticker=ticker,
            market_date=fact_date,
        )
    except agent_independent_price_evidence.IndependentPriceEvidenceError as exc:
        raise DataDiscrepancyReviewError(str(exc)) from exc
    if evidence is None:
        return {
            "status": "unavailable",
            "source": agent_independent_price_evidence.SOURCE_NAME,
            "raw_response_body_retained": False,
            "execution_authority": "none",
        }
    independent_value = evidence["value"]
    comparable_independent = _price_value_without_source(independent_value)
    comparable_source = _price_value_without_source(source_value)
    comparable_cache = (
        None
        if cache_value is None
        else _price_value_without_source(cache_value)
    )
    source_differences = _named_differences(
        comparable_independent,
        comparable_source,
        first_label="independent_value",
        second_label="yahoo_source_value",
    )
    cache_differences = _named_differences(
        comparable_independent,
        comparable_cache,
        first_label="independent_value",
        second_label="current_cache_value",
    )
    return {
        "status": "exact_raw_response_fact",
        "source": agent_independent_price_evidence.SOURCE_NAME,
        "value": independent_value,
        "value_sha256": evidence["value_sha256"],
        "observation_sha256": evidence["observation_sha256"],
        "receipt_sha256": evidence["receipt_sha256"],
        "response_sha256": evidence["response_sha256"],
        "received_at": evidence["source_fetched_at"],
        "observation_sequence": evidence["observation_sequence"],
        "value_revision": evidence["value_revision"],
        "classification": evidence["classification"],
        "matching_response_count": evidence["matching_response_count"],
        "source_value_matches": not source_differences,
        "cache_value_matches": comparable_cache is not None and not cache_differences,
        "source_value_comparison": _price_comparison(
            comparable_independent,
            comparable_source,
        ),
        "cache_value_comparison": _price_comparison(
            comparable_independent,
            comparable_cache,
        ),
        "source_differences": source_differences,
        "cache_differences": cache_differences,
        "raw_response_body_retained": True,
        "source_publication_time_available": False,
        "provider_dataset_version": None,
        "operational_price_mutation": False,
        "quarantine_mutation": False,
        "execution_authority": "none",
    }


def _verify_independent_evidence(
    evidence: object,
    *,
    dataset: str,
    ticker: str,
    fact_date: date,
    source_value: dict,
    cache_value: dict | None,
) -> None:
    unavailable_fields = {
        "status",
        "source",
        "raw_response_body_retained",
        "execution_authority",
    }
    if dataset != "daily_price":
        if evidence != {
            "status": "not_supported_for_dataset",
            "source": agent_independent_price_evidence.SOURCE_NAME,
            "raw_response_body_retained": False,
            "execution_authority": "none",
        }:
            raise DataDiscrepancyReviewError(
                "independent price evidence is invalid"
            )
        return
    if isinstance(evidence, dict) and set(evidence) == unavailable_fields:
        if evidence != {
            "status": "unavailable",
            "source": agent_independent_price_evidence.SOURCE_NAME,
            "raw_response_body_retained": False,
            "execution_authority": "none",
        }:
            raise DataDiscrepancyReviewError(
                "independent price evidence is invalid"
            )
        return
    expected = {
        "status",
        "source",
        "value",
        "value_sha256",
        "observation_sha256",
        "receipt_sha256",
        "response_sha256",
        "received_at",
        "observation_sequence",
        "value_revision",
        "classification",
        "matching_response_count",
        "source_value_matches",
        "cache_value_matches",
        "source_value_comparison",
        "cache_value_comparison",
        "source_differences",
        "cache_differences",
        "raw_response_body_retained",
        "source_publication_time_available",
        "provider_dataset_version",
        "operational_price_mutation",
        "quarantine_mutation",
        "execution_authority",
    }
    if not isinstance(evidence, dict) or set(evidence) != expected:
        raise DataDiscrepancyReviewError("independent price evidence is invalid")
    value = evidence["value"]
    comparable_independent = _price_value_without_source(value)
    comparable_source = _price_value_without_source(source_value)
    comparable_cache = (
        None
        if cache_value is None
        else _price_value_without_source(cache_value)
    )
    source_differences = _named_differences(
        comparable_independent,
        comparable_source,
        first_label="independent_value",
        second_label="yahoo_source_value",
    )
    cache_differences = _named_differences(
        comparable_independent,
        comparable_cache,
        first_label="independent_value",
        second_label="current_cache_value",
    )
    source_comparison = _price_comparison(
        comparable_independent,
        comparable_source,
    )
    cache_comparison = _price_comparison(
        comparable_independent,
        comparable_cache,
    )
    try:
        received_at = _parse_timestamp(
            evidence["received_at"],
            "independent response time",
        )
        independent_open = _finite_positive(
            value.get("open"), "independent open"
        )
        independent_high = _finite_positive(
            value.get("high"), "independent high"
        )
        independent_low = _finite_positive(
            value.get("low"), "independent low"
        )
        independent_close = _finite_positive(
            value.get("close"), "independent close"
        )
    except (TypeError, ValueError, DataDiscrepancyReviewError) as exc:
        raise DataDiscrepancyReviewError(
            "independent price evidence is invalid"
        ) from exc
    if (
        evidence["status"] != "exact_raw_response_fact"
        or evidence["source"] != agent_independent_price_evidence.SOURCE_NAME
        or value.get("ticker") != ticker
        or value.get("market_date") != fact_date.isoformat()
        or value.get("source") != agent_independent_price_evidence.SOURCE_NAME
        or independent_low
        > min(independent_open, independent_high, independent_close)
        or independent_high
        < max(independent_open, independent_low, independent_close)
        or isinstance(value.get("volume"), bool)
        or not isinstance(value.get("volume"), int)
        or value["volume"] < 0
        or evidence["value_sha256"] != canonical_sha256(value)
        or any(
            not isinstance(evidence[field], str)
            or _SHA256.fullmatch(evidence[field]) is None
            for field in (
                "value_sha256",
                "observation_sha256",
                "receipt_sha256",
                "response_sha256",
            )
        )
        or any(
            isinstance(evidence[field], bool)
            or not isinstance(evidence[field], int)
            or evidence[field] < 1
            for field in (
                "observation_sequence",
                "value_revision",
                "matching_response_count",
            )
        )
        or evidence["classification"]
        not in agent_independent_price_evidence.CLASSIFICATIONS
        or evidence["source_value_matches"] is not (not source_differences)
        or evidence["cache_value_matches"]
        is not (comparable_cache is not None and not cache_differences)
        or evidence["source_value_comparison"] != source_comparison
        or evidence["cache_value_comparison"] != cache_comparison
        or evidence["source_differences"] != source_differences
        or evidence["cache_differences"] != cache_differences
        or received_at.utcoffset() is None
        or received_at.utcoffset().total_seconds() != 0
        or evidence["raw_response_body_retained"] is not True
        or evidence["source_publication_time_available"] is not False
        or evidence["provider_dataset_version"] is not None
        or evidence["operational_price_mutation"] is not False
        or evidence["quarantine_mutation"] is not False
        or evidence["execution_authority"] != "none"
    ):
        raise DataDiscrepancyReviewError("independent price evidence is invalid")


def _verified_source_observation(
    packet: dict, fact_date: date, value_fields: set[str]
) -> dict:
    source = packet["source_observation"]
    source_fields = {
        "value",
        "value_sha256",
        "observation_sha256",
        "observation_sequence",
        "value_revision",
        "classification",
        "source_fetched_at",
        "observed_at",
        "receipt_sha256",
        "response_sha256",
        "source_adapter",
        "source_adapter_version",
        "source_library_version",
    }
    if (
        not isinstance(source, dict)
        or set(source) != source_fields
        or not isinstance(source.get("value"), dict)
        or set(source["value"]) != value_fields
        or source["value"]["ticker"] != packet["ticker"]
        or source["value"].get("market_date", source["value"].get("ex_date"))
        != fact_date.isoformat()
        or source["value"].get("kind", packet["kind"]) != packet["kind"]
        or source["value"].get("source") != agent_provider_responses.SOURCE_NAME
        or source.get("value_sha256") != canonical_sha256(source["value"])
        or any(
            not isinstance(source.get(field), str)
            or _SHA256.fullmatch(source[field]) is None
            for field in (
                "value_sha256",
                "observation_sha256",
                "receipt_sha256",
                "response_sha256",
            )
        )
        or any(
            isinstance(source.get(field), bool)
            or not isinstance(source.get(field), int)
            or source[field] < 1
            for field in ("observation_sequence", "value_revision")
        )
        or source.get("classification")
        not in {"baseline_source_observation", "source_value_revision"}
        or any(
            not isinstance(source.get(field), str)
            or not source[field]
            or len(source[field]) > 64
            or not source[field].isprintable()
            for field in (
                "source_adapter",
                "source_adapter_version",
                "source_library_version",
            )
        )
    ):
        raise DataDiscrepancyReviewError("source observation evidence is invalid")
    source_value = source["value"]
    try:
        if packet["dataset"] == "daily_price":
            source_open = _finite_positive(source_value["open"], "source open")
            source_high = _finite_positive(source_value["high"], "source high")
            source_low = _finite_positive(source_value["low"], "source low")
            source_close = _finite_positive(source_value["close"], "source close")
            if (
                isinstance(source_value["volume"], bool)
                or not isinstance(source_value["volume"], int)
                or source_value["volume"] < 0
                or source_low
                > min(source_open, source_high, source_close)
                or source_high
                < max(source_open, source_low, source_close)
            ):
                raise DataDiscrepancyReviewError(
                    "source observation evidence is invalid"
                )
        else:
            _finite_positive(
                source_value["value"], "source corporate-action value"
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise DataDiscrepancyReviewError(
            "source observation evidence is invalid"
        ) from exc
    try:
        source_fetched_at = _parse_timestamp(
            source["source_fetched_at"],
            "source observation receipt time",
        )
        source_observed_at = _parse_timestamp(
            source["observed_at"],
            "source observation time",
        )
    except (TypeError, ValueError, DataDiscrepancyReviewError) as exc:
        raise DataDiscrepancyReviewError(
            "source observation evidence is invalid"
        ) from exc
    if source_observed_at < source_fetched_at:
        raise DataDiscrepancyReviewError("source observation evidence is invalid")
    return source


def _verified_cache(
    packet: dict, fact_date: date, value_fields: set[str]
) -> dict | None:
    cache = packet["current_cache"]
    if cache is None:
        return None
    if (
        not isinstance(cache, dict)
        or set(cache) != {"value", "value_sha256", "latest_ingested_at"}
        or not isinstance(cache["value"], dict)
        or set(cache["value"]) != value_fields
        or cache["value"]["ticker"] != packet["ticker"]
        or cache["value"].get("market_date", cache["value"].get("ex_date"))
        != fact_date.isoformat()
        or cache["value"].get("kind", packet["kind"]) != packet["kind"]
        or cache["value"].get("source") != agent_provider_responses.SOURCE_NAME
        or cache["value_sha256"] != canonical_sha256(cache["value"])
    ):
        raise DataDiscrepancyReviewError("current cache evidence is invalid")
    cache_value = cache["value"]
    try:
        if packet["dataset"] == "daily_price":
            cache_open = _finite_positive(cache_value["open"], "cache open")
            cache_high = _finite_positive(cache_value["high"], "cache high")
            cache_low = _finite_positive(cache_value["low"], "cache low")
            cache_close = _finite_positive(cache_value["close"], "cache close")
            if (
                isinstance(cache_value["volume"], bool)
                or not isinstance(cache_value["volume"], int)
                or cache_value["volume"] < 0
                or cache_low > min(cache_open, cache_high, cache_close)
                or cache_high < max(cache_open, cache_low, cache_close)
            ):
                raise DataDiscrepancyReviewError(
                    "current cache evidence is invalid"
                )
        else:
            _finite_positive(cache_value["value"], "cache corporate-action value")
    except (KeyError, TypeError, ValueError) as exc:
        raise DataDiscrepancyReviewError("current cache evidence is invalid") from exc
    try:
        _parse_timestamp(cache["latest_ingested_at"], "cache ingestion time")
    except (TypeError, ValueError, DataDiscrepancyReviewError) as exc:
        raise DataDiscrepancyReviewError("current cache evidence is invalid") from exc
    return cache


def _verified_contents(packet: dict, fact_date: date) -> tuple[dict, dict | None]:
    value_fields = (
        {
            "ticker",
            "market_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
        }
        if packet["dataset"] == "daily_price"
        else {"ticker", "ex_date", "kind", "value", "source"}
    )
    source = _verified_source_observation(packet, fact_date, value_fields)
    cache = _verified_cache(packet, fact_date, value_fields)
    return source, cache


def build(
    con: duckdb.DuckDBPyConnection,
    *,
    dataset: str,
    ticker: str,
    fact_date: date,
    kind: str,
    generated_at: datetime,
) -> dict:
    """Build one short-lived packet after verifying the complete source ledger."""
    dataset, ticker, fact_date, kind = _key(dataset, ticker, fact_date, kind)
    generated_at = _utc(generated_at, "review generation time")
    try:
        agent_provider_responses._verify(con)
    except agent_provider_responses.ProviderResponseError as exc:
        raise DataDiscrepancyReviewError(str(exc)) from exc
    source = _source_fact(con, dataset, ticker, fact_date, kind)
    source_confirmations = _source_confirmations(
        con,
        dataset=dataset,
        ticker=ticker,
        fact_date=fact_date,
        kind=kind,
        value_sha256=source["value_sha256"],
    )
    cache = _cache_fact(con, dataset, ticker, fact_date, kind)
    source_observed_at = _parse_timestamp(
        source["observed_at"], "source observation time"
    ).astimezone(
        timezone.utc
    )
    if generated_at < source_observed_at:
        raise DataDiscrepancyReviewError(
            "review generation precedes source observation"
        )
    differences = _differences(
        source["value"],
        None if cache is None else cache["value"],
    )
    if not differences:
        raise DataDiscrepancyReviewError(
            "newest source observation matches the current cache"
        )
    independent = _independent_evidence(
        con,
        dataset=dataset,
        ticker=ticker,
        fact_date=fact_date,
        source_value=source["value"],
        cache_value=None if cache is None else cache["value"],
    )
    if (
        independent["status"] == "exact_raw_response_fact"
        and generated_at
        < _parse_timestamp(
            independent["received_at"],
            "independent response time",
        )
    ):
        raise DataDiscrepancyReviewError(
            "review generation precedes independent evidence"
        )
    body = {
        "schema_version": REVIEW_SCHEMA_VERSION,
        "status": STATUS,
        "review_scope": REVIEW_SCOPE,
        "dataset": dataset,
        "ticker": ticker,
        "fact_date": fact_date.isoformat(),
        "kind": kind,
        "discrepancy_classification": (
            "missing_current_cache_row"
            if cache is None
            else "current_cache_value_drift"
        ),
        "source_observation": source,
        "source_confirmations": source_confirmations,
        "current_cache": cache,
        "differences": differences,
        "independent_evidence": independent,
        "generated_at": _timestamp(generated_at),
        "expires_at": _timestamp(
            generated_at + timedelta(seconds=REVIEW_TTL_SECONDS)
        ),
        "required_operator_decision": list(OPERATOR_DECISIONS),
        "automatic_recommendation": None,
        "source_publication_time_available": False,
        "provider_dataset_version": None,
        "decision_present": False,
        "cache_mutation_implemented": False,
        "quarantine_mutation_implemented": False,
        "execution_authority": "none",
    }
    return {**body, "review_packet_sha256": canonical_sha256(body)}


def verify(packet: object) -> dict:
    """Validate one closed packet without consulting mutable retained state."""
    expected = {
        "schema_version",
        "status",
        "review_scope",
        "dataset",
        "ticker",
        "fact_date",
        "kind",
        "discrepancy_classification",
        "source_observation",
        "source_confirmations",
        "current_cache",
        "differences",
        "independent_evidence",
        "generated_at",
        "expires_at",
        "required_operator_decision",
        "automatic_recommendation",
        "source_publication_time_available",
        "provider_dataset_version",
        "decision_present",
        "cache_mutation_implemented",
        "quarantine_mutation_implemented",
        "execution_authority",
        "review_packet_sha256",
    }
    if not isinstance(packet, dict) or set(packet) != expected:
        raise DataDiscrepancyReviewError("discrepancy review packet shape is invalid")
    try:
        fact_date = iso_date(
            packet["fact_date"], "discrepancy fact date is invalid"
        )
        generated_at = _parse_timestamp(
            packet["generated_at"], "review generation time"
        )
        expires_at = _parse_timestamp(
            packet["expires_at"], "review expiry time"
        )
    except (KeyError, TypeError, ValueError, DataDiscrepancyReviewError) as exc:
        raise DataDiscrepancyReviewError(
            "discrepancy review packet identity is invalid"
        ) from exc
    _key(packet["dataset"], packet["ticker"], fact_date, packet["kind"])
    source, cache = _verified_contents(packet, fact_date)
    confirmations = packet["source_confirmations"]
    differences = _differences(
        source["value"],
        None if cache is None else cache["value"],
    )
    _verify_independent_evidence(
        packet["independent_evidence"],
        dataset=packet["dataset"],
        ticker=packet["ticker"],
        fact_date=fact_date,
        source_value=source["value"],
        cache_value=None if cache is None else cache["value"],
    )
    body = {
        key: value
        for key, value in packet.items()
        if key != "review_packet_sha256"
    }
    if (
        packet["schema_version"] != REVIEW_SCHEMA_VERSION
        or packet["status"] != STATUS
        or packet["review_scope"] != REVIEW_SCOPE
        or packet["discrepancy_classification"]
        not in {"current_cache_value_drift", "missing_current_cache_row"}
        or packet["discrepancy_classification"]
        != (
            "missing_current_cache_row"
            if cache is None
            else "current_cache_value_drift"
        )
        or not isinstance(confirmations, dict)
        or set(confirmations)
        != {
            "matching_response_count",
            "latest_received_at",
            "latest_response_sha256",
            "latest_receipt_sha256",
        }
        or isinstance(confirmations["matching_response_count"], bool)
        or not isinstance(confirmations["matching_response_count"], int)
        or confirmations["matching_response_count"] < 1
        or any(
            not isinstance(confirmations[field], str)
            or _SHA256.fullmatch(confirmations[field]) is None
            for field in ("latest_response_sha256", "latest_receipt_sha256")
        )
        or packet["differences"] != differences
        or (
            packet["independent_evidence"]["status"]
            == "exact_raw_response_fact"
            and _parse_timestamp(
                packet["independent_evidence"]["received_at"],
                "independent response time",
            )
            > generated_at
        )
        or generated_at.utcoffset() is None
        or generated_at.utcoffset().total_seconds() != 0
        or expires_at - generated_at
        != timedelta(seconds=REVIEW_TTL_SECONDS)
        or packet["required_operator_decision"] != list(OPERATOR_DECISIONS)
        or packet["automatic_recommendation"] is not None
        or packet["source_publication_time_available"] is not False
        or packet["provider_dataset_version"] is not None
        or packet["decision_present"] is not False
        or packet["cache_mutation_implemented"] is not False
        or packet["quarantine_mutation_implemented"] is not False
        or packet["execution_authority"] != "none"
        or not isinstance(packet["review_packet_sha256"], str)
        or _SHA256.fullmatch(packet["review_packet_sha256"]) is None
        or packet["review_packet_sha256"] != canonical_sha256(body)
    ):
        raise DataDiscrepancyReviewError("discrepancy review packet is invalid")
    try:
        latest_received_at = _parse_timestamp(
            confirmations["latest_received_at"],
            "latest source confirmation time",
        )
        if latest_received_at < _parse_timestamp(
            source["source_fetched_at"], "source observation receipt time"
        ):
            raise DataDiscrepancyReviewError(
                "latest source confirmation precedes source observation"
            )
    except (TypeError, ValueError, DataDiscrepancyReviewError) as exc:
        raise DataDiscrepancyReviewError(
            "discrepancy review packet is invalid"
        ) from exc
    return dict(packet)


def verify_retained(
    con: duckdb.DuckDBPyConnection,
    packet: object,
    *,
    reviewed_at: datetime,
) -> dict:
    """Rebuild against current retained evidence and reject stale or forged packets."""
    verified = verify(packet)
    reviewed_at = _utc(reviewed_at, "review time")
    expires_at = _parse_timestamp(
        verified["expires_at"], "review expiry time"
    ).astimezone(timezone.utc)
    generated_at = _parse_timestamp(
        verified["generated_at"], "review generation time"
    ).astimezone(timezone.utc)
    if reviewed_at < generated_at:
        raise DataDiscrepancyReviewError("review precedes packet generation")
    if reviewed_at >= expires_at:
        raise DataDiscrepancyReviewError("discrepancy review packet expired")
    rebuilt = build(
        con,
        dataset=verified["dataset"],
        ticker=verified["ticker"],
        fact_date=iso_date(verified["fact_date"]),
        kind=verified["kind"],
        generated_at=generated_at,
    )
    if rebuilt != verified:
        raise DataDiscrepancyReviewError(
            "discrepancy review packet does not match retained evidence"
        )
    return verified
