"""Versioned provenance envelope for facts admitted to an agent context."""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version

from engine.lib.provenance import canonical_sha256

from .read_model_utils import require_public_ticker
from .status_validation import iso_date, iso_timestamp

DATA_CONTRACT_SCHEMA_VERSION = 1
DAILY_PRICE_SCHEMA_VERSION = 4
CASH_DIVIDEND_SCHEMA_VERSION = 4
SOURCE_NAME = "yfinance"
SOURCE_ADAPTER = "yfinance.download"
SOURCE_ADAPTER_VERSION = "auto_adjust_false_v1"
ADJUSTMENT_POLICY = "provider_current_history"
LEGACY_REVISION_POLICY = "mutable_latest_value_upsert"
IMMUTABLE_REVISION_POLICY = "append_only_normalized_observation"
REVISION_POLICY = LEGACY_REVISION_POLICY
AVAILABILITY_POLICY = "usable_no_earlier_than_latest_ingestion"
IMMUTABLE_AVAILABILITY_POLICY = "usable_no_earlier_than_immutable_observation"
QUALITY_STATUS = "limited"
USAGE_AUTHORITY = "shadow_context_only"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
PROVIDER_EVIDENCE_RELATIONSHIP = "later_exact_value_corroboration"
SOURCE_OBSERVATION_RELATIONSHIP = "exact_response_source_observation"
PROVIDER_ENDPOINT_API_VERSION = "yahoo_finance_chart_v8"
SOURCE_OBSERVATION_ADAPTER = "yahoo_finance.chart_v8"
SOURCE_OBSERVATION_ADAPTER_VERSION = "exact_response_v1"
OBSERVATION_CLASSIFICATIONS = frozenset(
    {
        "baseline_snapshot",
        "unchanged_observation",
        "value_revision",
        "baseline_source_observation",
        "source_value_revision",
    }
)


class DataContractError(ValueError):
    """A stored fact cannot satisfy the agent-visible data contract."""


def _timestamp(value: datetime) -> str:
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _positive_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DataContractError(f"price {field} is invalid")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise DataContractError(f"price {field} is not positive and finite")
    return number


def _positive_volume(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise DataContractError("price volume is not a positive integer")
    return value


def _nonnegative_number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DataContractError(f"{field} is invalid")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise DataContractError(f"{field} is not nonnegative and finite")
    return number


def _source_version() -> str:
    try:
        value = version("yfinance")
    except PackageNotFoundError as exc:  # pragma: no cover - deployment dependency
        raise DataContractError("price source library version is unavailable") from exc
    if not value or len(value) > 64 or not value.isprintable():
        raise DataContractError("price source library version is invalid")
    return value


def _provider_evidence(
    evidence: object,
    *,
    observation_sha256: str | None,
    value_sha256: str | None,
    observed_at: str | None,
) -> dict | None:
    if evidence is None:
        return None
    fields = {
        "schema_version",
        "relationship",
        "receipt_sha256",
        "response_sha256",
        "response_size_bytes",
        "received_at",
        "endpoint_api_version",
        "source_library_version",
        "observation_sha256",
        "value_sha256",
        "raw_response_body_retained",
    }
    if (
        not isinstance(evidence, dict)
        or set(evidence) != fields
        or evidence["schema_version"] != 1
        or evidence["relationship"]
        not in {
            PROVIDER_EVIDENCE_RELATIONSHIP,
            SOURCE_OBSERVATION_RELATIONSHIP,
        }
        or not isinstance(evidence["receipt_sha256"], str)
        or _SHA256.fullmatch(evidence["receipt_sha256"]) is None
        or not isinstance(evidence["response_sha256"], str)
        or _SHA256.fullmatch(evidence["response_sha256"]) is None
        or isinstance(evidence["response_size_bytes"], bool)
        or not isinstance(evidence["response_size_bytes"], int)
        or evidence["response_size_bytes"] < 1
        or evidence["endpoint_api_version"] != PROVIDER_ENDPOINT_API_VERSION
        or not isinstance(evidence["source_library_version"], str)
        or not evidence["source_library_version"]
        or len(evidence["source_library_version"]) > 64
        or not evidence["source_library_version"].isprintable()
        or evidence["observation_sha256"] != observation_sha256
        or evidence["value_sha256"] != value_sha256
        or evidence["raw_response_body_retained"] is not True
        or observed_at is None
    ):
        raise DataContractError("provider corroboration evidence is invalid")
    try:
        received_at = iso_timestamp(
            evidence["received_at"], "provider evidence receipt time is invalid"
        )
        observed = iso_timestamp(
            observed_at, "immutable observation time is invalid"
        )
    except (TypeError, ValueError) as exc:
        raise DataContractError("provider corroboration evidence is invalid") from exc
    if (
        evidence["relationship"] == PROVIDER_EVIDENCE_RELATIONSHIP
        and received_at < observed
    ) or (
        evidence["relationship"] == SOURCE_OBSERVATION_RELATIONSHIP
        and received_at > observed
    ):
        raise DataContractError("provider corroboration evidence is invalid")
    return dict(evidence)


def daily_price_fact(
    *,
    ticker: str,
    market_date: date,
    open_price: object,
    high: object,
    low: object,
    close: object,
    volume: object,
    source: object,
    fetched_at: object,
    immutable_observation: object = None,
    provider_evidence: object = None,
) -> dict:
    """Return an honest immutable envelope around one selected daily bar.

    The existing price table remains a mutable provider-current cache. When a
    matching append-only observation is supplied, the envelope binds that
    retained normalized state and its revision chain. Raw transport bytes and
    provider publication/version metadata remain unavailable.
    """
    if type(market_date) is not date:
        raise DataContractError("price observation date is invalid")
    try:
        ticker = require_public_ticker(ticker)
    except ValueError as exc:
        raise DataContractError("price ticker is invalid") from exc
    if (
        not isinstance(source, str)
        or not source.strip()
        or source != source.strip()
        or len(source) > 128
        or not source.isprintable()
    ):
        raise DataContractError("price source is invalid")
    if source != SOURCE_NAME:
        raise DataContractError("price source is not admitted for this data contract")
    if type(fetched_at) is not datetime:
        raise DataContractError("price has no ingestion timestamp")
    ingested_at = _timestamp(fetched_at)
    if fetched_at.date() < market_date:
        raise DataContractError("price ingestion precedes its observation date")

    normalized_record = {
        "ticker": ticker,
        "market_date": market_date.isoformat(),
        "open": _positive_number(open_price, "open"),
        "high": _positive_number(high, "high"),
        "low": _positive_number(low, "low"),
        "close": _positive_number(close, "close"),
        "volume": _positive_volume(volume),
        "source": source,
        "latest_ingested_at": ingested_at,
    }
    if (
        normalized_record["low"]
        > min(
            normalized_record["open"],
            normalized_record["close"],
            normalized_record["high"],
        )
        or normalized_record["high"]
        < max(
            normalized_record["open"],
            normalized_record["close"],
            normalized_record["low"],
        )
    ):
        raise DataContractError("price OHLC values are inconsistent")
    immutable = immutable_observation is not None
    if immutable:
        source_library_version = (
            immutable_observation.get("source_library_version")
            if isinstance(immutable_observation, dict)
            else None
        )
        if (
            not isinstance(immutable_observation, dict)
            or immutable_observation.get("normalized") != normalized_record
            or immutable_observation.get("schema_version") != 1
            or not isinstance(
                immutable_observation.get("observation_sha256"), str
            )
            or _SHA256.fullmatch(
                immutable_observation["observation_sha256"]
            )
            is None
            or immutable_observation.get("classification")
            not in OBSERVATION_CLASSIFICATIONS
            or isinstance(
                immutable_observation.get("observation_sequence"), bool
            )
            or not isinstance(
                immutable_observation.get("observation_sequence"), int
            )
            or immutable_observation["observation_sequence"] < 1
            or isinstance(immutable_observation.get("value_revision"), bool)
            or not isinstance(immutable_observation.get("value_revision"), int)
            or immutable_observation["value_revision"] < 1
            or not isinstance(source_library_version, str)
            or not source_library_version
            or len(source_library_version) > 64
            or not source_library_version.isprintable()
        ):
            raise DataContractError("immutable price observation is invalid")
        observed_at = immutable_observation.get("observed_at")
        try:
            iso_timestamp(
                observed_at, "immutable price observation time is invalid"
            )
        except (TypeError, ValueError) as exc:
            raise DataContractError(
                "immutable price observation is invalid"
            ) from exc
        revision = {
            "policy": IMMUTABLE_REVISION_POLICY,
            "revision_id": immutable_observation["observation_sha256"],
            "observation_schema_version": immutable_observation[
                "schema_version"
            ],
            "observation_sequence": immutable_observation[
                "observation_sequence"
            ],
            "value_revision": immutable_observation["value_revision"],
            "classification": immutable_observation["classification"],
            "value_sha256": immutable_observation["value_sha256"],
            "previous_revision_id": immutable_observation[
                "previous_observation_sha256"
            ],
            "observed_at": observed_at,
            "history_retained": True,
            "point_in_time_replayable": True,
        }
        usable_at = observed_at
        availability_policy = IMMUTABLE_AVAILABILITY_POLICY
    else:
        source_library_version = _source_version()
        observed_at = None
        revision = {
            "policy": LEGACY_REVISION_POLICY,
            "revision_id": None,
            "observation_schema_version": None,
            "observation_sequence": None,
            "value_revision": None,
            "classification": "legacy_unobserved",
            "value_sha256": None,
            "previous_revision_id": None,
            "observed_at": None,
            "history_retained": False,
            "point_in_time_replayable": False,
        }
        limitations = [
            "source publication time is unavailable",
            "provider API version is unavailable",
            "raw provider payload is not retained",
            "provider revisions overwrite the same ticker/date key",
        ]
        usable_at = ingested_at
        availability_policy = AVAILABILITY_POLICY
    corroboration = _provider_evidence(
        provider_evidence,
        observation_sha256=revision["revision_id"],
        value_sha256=revision["value_sha256"],
        observed_at=revision["observed_at"],
    )
    source_observation = (
        corroboration is not None
        and corroboration["relationship"] == SOURCE_OBSERVATION_RELATIONSHIP
    )
    if immutable:
        limitations = [
            "source publication time is unavailable",
            "provider dataset revision is unavailable",
        ]
        if not source_observation:
            limitations.append("raw provider payload is not retained at observation time")
    source_adapter = (
        immutable_observation["source_adapter"]
        if immutable
        else SOURCE_ADAPTER
    )
    source_adapter_version = (
        immutable_observation["source_adapter_version"]
        if immutable
        else SOURCE_ADAPTER_VERSION
    )

    result = {
        "schema_version": DAILY_PRICE_SCHEMA_VERSION,
        "dataset": "daily_price",
        "quality_status": QUALITY_STATUS,
        "usage_authority": USAGE_AUTHORITY,
        "observation": {
            "market_date": market_date.isoformat(),
            "event_time": None,
            "event_time_status": "daily_session_date_only",
        },
        "availability": {
            "source_published_at": None,
            "usable_at": usable_at,
            "policy": availability_policy,
        },
        "ingestion": {
            "latest_ingested_at": ingested_at,
            "immutable_observed_at": observed_at,
        },
        "source": {
            "name": source,
            "provider_version": None,
            "adapter": source_adapter,
            "adapter_version": source_adapter_version,
            "library_version": source_library_version,
        },
        "revision": revision,
        "provider_evidence": corroboration,
        "record": {
            "normalized": normalized_record,
            "normalized_sha256": canonical_sha256(normalized_record),
            "raw_sha256": (
                corroboration["response_sha256"] if source_observation else None
            ),
            "raw_retained": source_observation,
        },
        "adjustment": {
            "request_auto_adjust": False,
            "storage_policy": ADJUSTMENT_POLICY,
            "point_in_time_revision_safe": False,
        },
        "quarantine": {
            "status": "clear",
            "reason": None,
        },
        "limitations": limitations,
    }
    validate_daily_price_fact(result)
    return result


def dividend_fact(
    *,
    ticker: str,
    ex_date: date,
    value: object,
    source: object,
    fetched_at: object,
    immutable_observation: object = None,
    provider_evidence: object = None,
) -> dict:
    """Return one hash-bound dividend record used by total-return features."""
    if type(ex_date) is not date:
        raise DataContractError("dividend ex-date is invalid")
    try:
        ticker = require_public_ticker(ticker)
    except ValueError as exc:
        raise DataContractError("dividend ticker is invalid") from exc
    if source != SOURCE_NAME:
        raise DataContractError("dividend source is not admitted")
    if type(fetched_at) is not datetime:
        raise DataContractError("dividend has no ingestion timestamp")
    ingested_at = _timestamp(fetched_at)
    if fetched_at.date() < ex_date:
        raise DataContractError("dividend ingestion precedes its ex-date")
    normalized = {
        "ticker": ticker,
        "ex_date": ex_date.isoformat(),
        "cash_per_share": _nonnegative_number(value, "dividend value"),
        "source": source,
        "latest_ingested_at": ingested_at,
    }
    immutable = immutable_observation is not None
    if immutable:
        source_library_version = (
            immutable_observation.get("source_library_version")
            if isinstance(immutable_observation, dict)
            else None
        )
        expected_observation = {
            "ticker": ticker,
            "ex_date": ex_date.isoformat(),
            "kind": "dividend",
            "value": normalized["cash_per_share"],
            "source": source,
            "latest_ingested_at": ingested_at,
        }
        if (
            not isinstance(immutable_observation, dict)
            or immutable_observation.get("normalized") != expected_observation
            or immutable_observation.get("schema_version") != 1
            or not isinstance(
                immutable_observation.get("observation_sha256"), str
            )
            or _SHA256.fullmatch(immutable_observation["observation_sha256"])
            is None
            or immutable_observation.get("classification")
            not in OBSERVATION_CLASSIFICATIONS
            or isinstance(
                immutable_observation.get("observation_sequence"), bool
            )
            or not isinstance(
                immutable_observation.get("observation_sequence"), int
            )
            or immutable_observation["observation_sequence"] < 1
            or isinstance(immutable_observation.get("value_revision"), bool)
            or not isinstance(immutable_observation.get("value_revision"), int)
            or immutable_observation["value_revision"] < 1
            or not isinstance(source_library_version, str)
            or not source_library_version
            or len(source_library_version) > 64
            or not source_library_version.isprintable()
        ):
            raise DataContractError("immutable dividend observation is invalid")
        observed_at = immutable_observation.get("observed_at")
        try:
            iso_timestamp(
                observed_at, "immutable dividend observation time is invalid"
            )
        except (TypeError, ValueError) as exc:
            raise DataContractError(
                "immutable dividend observation is invalid"
            ) from exc
        revision = {
            "policy": IMMUTABLE_REVISION_POLICY,
            "revision_id": immutable_observation["observation_sha256"],
            "observation_schema_version": immutable_observation[
                "schema_version"
            ],
            "observation_sequence": immutable_observation[
                "observation_sequence"
            ],
            "value_revision": immutable_observation["value_revision"],
            "classification": immutable_observation["classification"],
            "observation_normalized_sha256": immutable_observation[
                "normalized_sha256"
            ],
            "value_sha256": immutable_observation["value_sha256"],
            "previous_revision_id": immutable_observation[
                "previous_observation_sha256"
            ],
            "observed_at": observed_at,
            "history_retained": True,
            "point_in_time_replayable": True,
        }
        usable_at = observed_at
        availability_policy = IMMUTABLE_AVAILABILITY_POLICY
    else:
        source_library_version = _source_version()
        observed_at = None
        revision = {
            "policy": LEGACY_REVISION_POLICY,
            "revision_id": None,
            "observation_schema_version": None,
            "observation_sequence": None,
            "value_revision": None,
            "classification": "legacy_unobserved",
            "observation_normalized_sha256": None,
            "value_sha256": None,
            "previous_revision_id": None,
            "observed_at": None,
            "history_retained": False,
            "point_in_time_replayable": False,
        }
        usable_at = ingested_at
        availability_policy = AVAILABILITY_POLICY
    corroboration = _provider_evidence(
        provider_evidence,
        observation_sha256=revision["revision_id"],
        value_sha256=revision["value_sha256"],
        observed_at=revision["observed_at"],
    )
    source_observation = (
        corroboration is not None
        and corroboration["relationship"] == SOURCE_OBSERVATION_RELATIONSHIP
    )
    source_adapter = (
        immutable_observation["source_adapter"]
        if immutable
        else "yfinance.actions"
    )
    source_adapter_version = (
        immutable_observation["source_adapter_version"]
        if immutable
        else "corporate_actions_v1"
    )
    result = {
        "schema_version": CASH_DIVIDEND_SCHEMA_VERSION,
        "dataset": "cash_dividend",
        "quality_status": QUALITY_STATUS,
        "usage_authority": USAGE_AUTHORITY,
        "availability": {
            "source_published_at": None,
            "usable_at": usable_at,
            "policy": availability_policy,
        },
        "ingestion": {
            "latest_ingested_at": ingested_at,
            "immutable_observed_at": observed_at,
        },
        "source": {
            "name": source,
            "provider_version": None,
            "adapter": source_adapter,
            "adapter_version": source_adapter_version,
            "library_version": source_library_version,
        },
        "revision": revision,
        "provider_evidence": corroboration,
        "record": {
            "normalized": normalized,
            "normalized_sha256": canonical_sha256(normalized),
            "raw_sha256": (
                corroboration["response_sha256"] if source_observation else None
            ),
            "raw_retained": source_observation,
        },
    }
    validate_dividend_fact(result)
    return result


def _valid_optional_sha256(value: object) -> bool:
    return value is None or (isinstance(value, str) and _SHA256.fullmatch(value) is not None)


def _validate_dividend_revision(
    revision: dict, ingestion: dict, availability: dict
) -> bool:
    immutable = revision["policy"] == IMMUTABLE_REVISION_POLICY
    if immutable:
        valid = all(
            (
                isinstance(revision["revision_id"], str)
                and _SHA256.fullmatch(revision["revision_id"]) is not None,
                revision["observation_schema_version"] == 1,
                isinstance(revision["observation_sequence"], int)
                and not isinstance(revision["observation_sequence"], bool)
                and revision["observation_sequence"] >= 1,
                isinstance(revision["value_revision"], int)
                and not isinstance(revision["value_revision"], bool)
                and revision["value_revision"] >= 1,
                revision["classification"] in OBSERVATION_CLASSIFICATIONS,
                isinstance(revision["observation_normalized_sha256"], str)
                and _SHA256.fullmatch(revision["observation_normalized_sha256"]) is not None,
                isinstance(revision["value_sha256"], str)
                and _SHA256.fullmatch(revision["value_sha256"]) is not None,
                _valid_optional_sha256(revision["previous_revision_id"]),
                revision["observed_at"] == ingestion["immutable_observed_at"],
                availability["policy"] == IMMUTABLE_AVAILABILITY_POLICY,
                availability["usable_at"] == ingestion["immutable_observed_at"],
                revision["history_retained"] is True,
                revision["point_in_time_replayable"] is True,
                isinstance(ingestion["immutable_observed_at"], str),
            )
        )
    else:
        valid = (
            revision
            == {
                "policy": LEGACY_REVISION_POLICY,
                "revision_id": None,
                "observation_schema_version": None,
                "observation_sequence": None,
                "value_revision": None,
                "classification": "legacy_unobserved",
                "observation_normalized_sha256": None,
                "value_sha256": None,
                "previous_revision_id": None,
                "observed_at": None,
                "history_retained": False,
                "point_in_time_replayable": False,
            }
            and ingestion["immutable_observed_at"] is None
            and availability["policy"] == AVAILABILITY_POLICY
            and availability["usable_at"] == ingestion["latest_ingested_at"]
        )
    if not valid:
        raise DataContractError("dividend data contract is invalid")
    return immutable


def _dividend_source_observation(
    provider_evidence: dict | None, source: dict, record: dict
) -> bool:
    source_observation = (
        provider_evidence is not None
        and provider_evidence["relationship"] == SOURCE_OBSERVATION_RELATIONSHIP
    )
    if source_observation:
        valid = (
            source["adapter"] == SOURCE_OBSERVATION_ADAPTER
            and source["adapter_version"] == SOURCE_OBSERVATION_ADAPTER_VERSION
            and record["raw_retained"] is True
            and record["raw_sha256"] == provider_evidence["response_sha256"]
        )
    else:
        valid = record["raw_retained"] is False and record["raw_sha256"] is None
    if not valid:
        raise DataContractError("dividend data contract is invalid")
    return source_observation


def validate_dividend_fact(value: object) -> None:
    """Fail closed if a published dividend fact drifts from its reviewed shape."""
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "dataset",
        "quality_status",
        "usage_authority",
        "availability",
        "ingestion",
        "source",
        "revision",
        "provider_evidence",
        "record",
    }:
        raise DataContractError("dividend data contract shape is invalid")
    availability = value["availability"]
    ingestion = value["ingestion"]
    source = value["source"]
    revision = value["revision"]
    provider_evidence = value["provider_evidence"]
    record = value["record"]
    if (
        value["schema_version"] != CASH_DIVIDEND_SCHEMA_VERSION
        or value["dataset"] != "cash_dividend"
        or value["quality_status"] != QUALITY_STATUS
        or value["usage_authority"] != USAGE_AUTHORITY
        or not isinstance(availability, dict)
        or set(availability) != {"source_published_at", "usable_at", "policy"}
        or availability["source_published_at"] is not None
        or not isinstance(ingestion, dict)
        or set(ingestion)
        != {"latest_ingested_at", "immutable_observed_at"}
        or not isinstance(source, dict)
        or set(source)
        != {
            "name",
            "provider_version",
            "adapter",
            "adapter_version",
            "library_version",
        }
        or source["name"] != SOURCE_NAME
        or source["provider_version"] is not None
        or (
            source["adapter"],
            source["adapter_version"],
        )
        not in {
            ("yfinance.actions", "corporate_actions_v1"),
            (
                SOURCE_OBSERVATION_ADAPTER,
                SOURCE_OBSERVATION_ADAPTER_VERSION,
            ),
        }
        or not isinstance(source["library_version"], str)
        or not source["library_version"]
        or not isinstance(revision, dict)
        or set(revision)
        != {
            "policy",
            "revision_id",
            "observation_schema_version",
            "observation_sequence",
            "value_revision",
            "classification",
            "observation_normalized_sha256",
            "value_sha256",
            "previous_revision_id",
            "observed_at",
            "history_retained",
            "point_in_time_replayable",
        }
        or not isinstance(record, dict)
        or set(record)
        != {"normalized", "normalized_sha256", "raw_sha256", "raw_retained"}
        or not isinstance(record["normalized"], dict)
        or set(record["normalized"])
        != {
            "ticker",
            "ex_date",
            "cash_per_share",
            "source",
            "latest_ingested_at",
        }
        or not isinstance(record["normalized_sha256"], str)
        or _SHA256.fullmatch(record["normalized_sha256"]) is None
        or canonical_sha256(record["normalized"]) != record["normalized_sha256"]
    ):
        raise DataContractError("dividend data contract is invalid")
    immutable = _validate_dividend_revision(revision, ingestion, availability)
    _provider_evidence(
        provider_evidence,
        observation_sha256=revision["revision_id"],
        value_sha256=revision["value_sha256"],
        observed_at=revision["observed_at"],
    )
    source_observation = _dividend_source_observation(
        provider_evidence, source, record
    )
    try:
        normalized = record["normalized"]
        require_public_ticker(normalized["ticker"])
        ex_date = iso_date(normalized["ex_date"], "dividend ex-date is invalid")
        usable_at = iso_timestamp(
            availability["usable_at"], "dividend availability time is invalid"
        ).astimezone(timezone.utc)
        ingested_at = iso_timestamp(
            normalized["latest_ingested_at"], "dividend ingestion time is invalid"
        ).astimezone(timezone.utc)
        immutable_observed_at = (
            iso_timestamp(
                ingestion["immutable_observed_at"],
                "immutable dividend observation time is invalid",
            ).astimezone(timezone.utc)
            if immutable
            else None
        )
        _nonnegative_number(normalized["cash_per_share"], "dividend value")
    except (KeyError, TypeError, ValueError) as exc:
        raise DataContractError("dividend data contract is invalid") from exc
    if (
        normalized["source"] != SOURCE_NAME
        or ingestion["latest_ingested_at"]
        != normalized["latest_ingested_at"]
        or usable_at
        != (immutable_observed_at if immutable else ingested_at)
        or ingested_at.date() < ex_date
        or (
            immutable_observed_at is not None
            and immutable_observed_at < ingested_at
        )
    ):
        raise DataContractError("dividend data contract is invalid")
    if immutable:
        observation_normalized = {
            "ticker": normalized["ticker"],
            "ex_date": normalized["ex_date"],
            "kind": "dividend",
            "value": normalized["cash_per_share"],
            "source": normalized["source"],
            "latest_ingested_at": normalized["latest_ingested_at"],
        }
        observation_value = {
            key: observation_normalized[key]
            for key in ("ticker", "ex_date", "kind", "value", "source")
        }
        observation_identity = {
            "schema_version": revision["observation_schema_version"],
            "ticker": normalized["ticker"],
            "ex_date": normalized["ex_date"],
            "kind": "dividend",
            "normalized_sha256": revision[
                "observation_normalized_sha256"
            ],
            "value_sha256": revision["value_sha256"],
            "source_fetched_at": normalized["latest_ingested_at"],
            "observed_at": revision["observed_at"],
            "source_adapter": source["adapter"],
            "source_adapter_version": source["adapter_version"],
            "source_library_version": source["library_version"],
            "observation_sequence": revision["observation_sequence"],
            "value_revision": revision["value_revision"],
            "classification": revision["classification"],
            "previous_observation_sha256": revision["previous_revision_id"],
        }
        if source_observation:
            observation_identity = {
                "schema_version": revision["observation_schema_version"],
                "dataset": "corporate_action",
                "ticker": normalized["ticker"],
                "fact_date": normalized["ex_date"],
                "kind": "dividend",
                "normalized_sha256": revision[
                    "observation_normalized_sha256"
                ],
                "value_sha256": revision["value_sha256"],
                "source_fetched_at": normalized["latest_ingested_at"],
                "observed_at": revision["observed_at"],
                "source_adapter": source["adapter"],
                "source_adapter_version": source["adapter_version"],
                "source_library_version": source["library_version"],
                "observation_sequence": revision["observation_sequence"],
                "value_revision": revision["value_revision"],
                "classification": revision["classification"],
                "previous_observation_sha256": revision[
                    "previous_revision_id"
                ],
                "receipt_sha256": provider_evidence["receipt_sha256"],
                "response_sha256": provider_evidence["response_sha256"],
            }
        if (
            canonical_sha256(observation_normalized)
            != revision["observation_normalized_sha256"]
            or canonical_sha256(observation_value)
            != revision["value_sha256"]
            or canonical_sha256(observation_identity)
            != revision["revision_id"]
        ):
            raise DataContractError("dividend data contract is invalid")


def validate_daily_price_fact(value: object) -> None:
    """Fail closed if the published contract drifts from its reviewed shape."""
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "dataset",
        "quality_status",
        "usage_authority",
        "observation",
        "availability",
        "ingestion",
        "source",
        "revision",
        "provider_evidence",
        "record",
        "adjustment",
        "quarantine",
        "limitations",
    }:
        raise DataContractError("daily price data contract shape is invalid")
    if (
        value["schema_version"] != DAILY_PRICE_SCHEMA_VERSION
        or value["dataset"] != "daily_price"
        or value["quality_status"] != QUALITY_STATUS
        or value["usage_authority"] != USAGE_AUTHORITY
    ):
        raise DataContractError("daily price data contract identity is invalid")
    observation = value["observation"]
    availability = value["availability"]
    ingestion = value["ingestion"]
    source = value["source"]
    revision = value["revision"]
    provider_evidence = value["provider_evidence"]
    record = value["record"]
    adjustment = value["adjustment"]
    quarantine = value["quarantine"]
    if (
        not isinstance(observation, dict)
        or set(observation) != {"market_date", "event_time", "event_time_status"}
        or observation["event_time"] is not None
        or observation["event_time_status"] != "daily_session_date_only"
        or not isinstance(availability, dict)
        or set(availability) != {"source_published_at", "usable_at", "policy"}
        or availability["source_published_at"] is not None
        or not isinstance(ingestion, dict)
        or set(ingestion)
        != {"latest_ingested_at", "immutable_observed_at"}
        or not isinstance(source, dict)
        or set(source)
        != {
            "name",
            "provider_version",
            "adapter",
            "adapter_version",
            "library_version",
        }
        or source["name"] != SOURCE_NAME
        or source["provider_version"] is not None
        or (
            source["adapter"],
            source["adapter_version"],
        )
        not in {
            (SOURCE_ADAPTER, SOURCE_ADAPTER_VERSION),
            (
                SOURCE_OBSERVATION_ADAPTER,
                SOURCE_OBSERVATION_ADAPTER_VERSION,
            ),
        }
        or not isinstance(source["library_version"], str)
        or not source["library_version"]
        or not isinstance(revision, dict)
        or set(revision)
        != {
            "policy",
            "revision_id",
            "observation_schema_version",
            "observation_sequence",
            "value_revision",
            "classification",
            "value_sha256",
            "previous_revision_id",
            "observed_at",
            "history_retained",
            "point_in_time_replayable",
        }
        or not isinstance(record, dict)
        or set(record)
        != {"normalized", "normalized_sha256", "raw_sha256", "raw_retained"}
        or not isinstance(record["normalized"], dict)
        or set(record["normalized"])
        != {
            "ticker",
            "market_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "source",
            "latest_ingested_at",
        }
        or not isinstance(record["normalized_sha256"], str)
        or _SHA256.fullmatch(record["normalized_sha256"]) is None
        or canonical_sha256(record["normalized"]) != record["normalized_sha256"]
        or not isinstance(adjustment, dict)
        or set(adjustment)
        != {"request_auto_adjust", "storage_policy", "point_in_time_revision_safe"}
        or adjustment["request_auto_adjust"] is not False
        or adjustment["storage_policy"] != ADJUSTMENT_POLICY
        or adjustment["point_in_time_revision_safe"] is not False
        or quarantine != {"status": "clear", "reason": None}
    ):
        raise DataContractError("daily price data contract is invalid")
    immutable = revision["policy"] == IMMUTABLE_REVISION_POLICY
    if immutable:
        if (
            not isinstance(revision["revision_id"], str)
            or _SHA256.fullmatch(revision["revision_id"]) is None
            or revision["observation_schema_version"] != 1
            or isinstance(revision["observation_sequence"], bool)
            or not isinstance(revision["observation_sequence"], int)
            or revision["observation_sequence"] < 1
            or isinstance(revision["value_revision"], bool)
            or not isinstance(revision["value_revision"], int)
            or revision["value_revision"] < 1
            or revision["classification"] not in OBSERVATION_CLASSIFICATIONS
            or not isinstance(revision["value_sha256"], str)
            or _SHA256.fullmatch(revision["value_sha256"]) is None
            or (
                revision["previous_revision_id"] is not None
                and (
                    not isinstance(revision["previous_revision_id"], str)
                    or _SHA256.fullmatch(revision["previous_revision_id"])
                    is None
                )
            )
            or revision["observed_at"]
            != ingestion["immutable_observed_at"]
            or availability["policy"] != IMMUTABLE_AVAILABILITY_POLICY
            or availability["usable_at"] != ingestion["immutable_observed_at"]
            or revision["history_retained"] is not True
            or revision["point_in_time_replayable"] is not True
            or not isinstance(ingestion["immutable_observed_at"], str)
        ):
            raise DataContractError("daily price data contract is invalid")
    elif (
        revision
        != {
            "policy": LEGACY_REVISION_POLICY,
            "revision_id": None,
            "observation_schema_version": None,
            "observation_sequence": None,
            "value_revision": None,
            "classification": "legacy_unobserved",
            "value_sha256": None,
            "previous_revision_id": None,
            "observed_at": None,
            "history_retained": False,
            "point_in_time_replayable": False,
        }
        or ingestion["immutable_observed_at"] is not None
        or availability["policy"] != AVAILABILITY_POLICY
        or availability["usable_at"] != ingestion["latest_ingested_at"]
        or value["limitations"]
        != [
            "source publication time is unavailable",
            "provider API version is unavailable",
            "raw provider payload is not retained",
            "provider revisions overwrite the same ticker/date key",
        ]
    ):
        raise DataContractError("daily price data contract is invalid")
    _provider_evidence(
        provider_evidence,
        observation_sha256=revision["revision_id"],
        value_sha256=revision["value_sha256"],
        observed_at=revision["observed_at"],
    )
    source_observation = (
        provider_evidence is not None
        and provider_evidence["relationship"]
        == SOURCE_OBSERVATION_RELATIONSHIP
    )
    expected_limitations = [
        "source publication time is unavailable",
        "provider dataset revision is unavailable",
    ]
    if immutable and not source_observation:
        expected_limitations.append(
            "raw provider payload is not retained at observation time"
        )
    if (
        immutable
        and value["limitations"] != expected_limitations
    ) or (
        source_observation
        and (
            source["adapter"] != SOURCE_OBSERVATION_ADAPTER
            or source["adapter_version"]
            != SOURCE_OBSERVATION_ADAPTER_VERSION
            or record["raw_retained"] is not True
            or record["raw_sha256"] != provider_evidence["response_sha256"]
        )
    ) or (
        not source_observation
        and (
            record["raw_retained"] is not False
            or record["raw_sha256"] is not None
        )
    ):
        raise DataContractError("daily price data contract is invalid")
    try:
        observation_date = iso_date(
            observation["market_date"], "daily price observation date is invalid"
        )
        usable_at = iso_timestamp(
            availability["usable_at"], "daily price availability time is invalid"
        ).astimezone(timezone.utc)
        ingested_at = iso_timestamp(
            ingestion["latest_ingested_at"], "daily price ingestion time is invalid"
        ).astimezone(timezone.utc)
        normalized = record["normalized"]
        require_public_ticker(normalized["ticker"])
        normalized_date = iso_date(
            normalized["market_date"], "normalized price date is invalid"
        )
        normalized_ingestion = iso_timestamp(
            normalized["latest_ingested_at"],
            "normalized price ingestion time is invalid",
        ).astimezone(timezone.utc)
        immutable_observed_at = (
            iso_timestamp(
                ingestion["immutable_observed_at"],
                "immutable price observation time is invalid",
            ).astimezone(timezone.utc)
            if immutable
            else None
        )
        _positive_number(normalized["open"], "open")
        _positive_number(normalized["high"], "high")
        _positive_number(normalized["low"], "low")
        _positive_number(normalized["close"], "close")
        _positive_volume(normalized["volume"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DataContractError("daily price data contract is invalid") from exc
    if (
        normalized["source"] != SOURCE_NAME
        or normalized_date != observation_date
        or normalized_ingestion != ingested_at
        or usable_at
        != (immutable_observed_at if immutable else ingested_at)
        or ingested_at.date() < observation_date
        or (
            immutable_observed_at is not None
            and immutable_observed_at < ingested_at
        )
        or normalized["low"]
        > min(normalized["open"], normalized["close"], normalized["high"])
        or normalized["high"]
        < max(normalized["open"], normalized["close"], normalized["low"])
    ):
        raise DataContractError("daily price data contract is invalid")
    if immutable:
        normalized_value = {
            key: normalized[key]
            for key in (
                "ticker",
                "market_date",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "source",
            )
        }
        observation_identity = {
            "schema_version": revision["observation_schema_version"],
            "ticker": normalized["ticker"],
            "market_date": normalized["market_date"],
            "normalized_sha256": record["normalized_sha256"],
            "value_sha256": revision["value_sha256"],
            "source_fetched_at": normalized["latest_ingested_at"],
            "observed_at": revision["observed_at"],
            "source_adapter": source["adapter"],
            "source_adapter_version": source["adapter_version"],
            "source_library_version": source["library_version"],
            "observation_sequence": revision["observation_sequence"],
            "value_revision": revision["value_revision"],
            "classification": revision["classification"],
            "previous_observation_sha256": revision["previous_revision_id"],
        }
        if source_observation:
            observation_identity = {
                "schema_version": revision["observation_schema_version"],
                "dataset": "daily_price",
                "ticker": normalized["ticker"],
                "fact_date": normalized["market_date"],
                "kind": "daily_price",
                "normalized_sha256": record["normalized_sha256"],
                "value_sha256": revision["value_sha256"],
                "source_fetched_at": normalized["latest_ingested_at"],
                "observed_at": revision["observed_at"],
                "source_adapter": source["adapter"],
                "source_adapter_version": source["adapter_version"],
                "source_library_version": source["library_version"],
                "observation_sequence": revision["observation_sequence"],
                "value_revision": revision["value_revision"],
                "classification": revision["classification"],
                "previous_observation_sha256": revision[
                    "previous_revision_id"
                ],
                "receipt_sha256": provider_evidence["receipt_sha256"],
                "response_sha256": provider_evidence["response_sha256"],
            }
        if (
            canonical_sha256(normalized_value) != revision["value_sha256"]
            or canonical_sha256(observation_identity)
            != revision["revision_id"]
        ):
            raise DataContractError("daily price data contract is invalid")
