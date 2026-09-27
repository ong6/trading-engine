"""Pure P16 challenger treatments over one retained P15 request.

Treatment metadata and inverse identifiers remain outside the model payload.  No
source fetch, mutable-history lookup, model call, or execution operation occurs
here; callers must supply snapshots that were visible at the decision cutoff.
"""
from __future__ import annotations

import copy
import math
import re
from datetime import datetime, timezone

from engine.lib.provenance import canonical_sha256

META_FIELDS = {
    "schema_version", "policy_id", "market_date", "information_cutoff_at",
    "chunk_index", "sample_index", "permutation_seed",
}
PRICE_FIELDS = {
    "ticker", "market_date", "sector", "close", "daily_return", "overnight_gap",
    "return_5d", "relative_volume_20d", "median_dollar_volume_20d", "atr_14",
    "rs_rank", "template_score", "passes_template", "new_screen_pass", "earnings",
    "held", "tradeable", "reason", "standout_score", "stratum", "selection_ordinal",
    "baseline_rank", "baseline_score", "baseline_version", "evidence_id",
}
TEXT_FIELDS = {
    "ticker", "company_name", "sector", "earnings", "headlines", "evidence_id",
}
EARNINGS_FIELDS = {"status", "next_date", "is_estimate", "snapshot_date"}
MEMORY_LIMIT = 20


def _utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("challenger availability time is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("challenger availability requires an explicit timezone")
    return parsed.astimezone(timezone.utc)


def _finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _treatment(original: dict, payload: dict, kind: str, details: dict) -> dict:
    body = {
        "treatment": kind,
        "original_sha256": canonical_sha256(original),
        "payload_sha256": canonical_sha256(payload),
        "payload": payload,
        **details,
    }
    return {**body, "treatment_sha256": canonical_sha256(body)}


def blind(original: dict, aliases: dict, *, decision_at: str) -> dict:
    """Replace symbols and known issuer names with stable per-session IDs."""
    cutoff = _utc(decision_at)
    if _utc(aliases.get("available_at")) > cutoff \
            or _utc(original.get("information_cutoff_at")) > cutoff:
        raise ValueError("company aliases were unavailable at the decision")
    candidates = original.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("challenger candidates are empty")
    tickers = {row.get("ticker") for row in candidates if isinstance(row, dict)}
    names = aliases.get("names")
    if None in tickers or not isinstance(names, dict) or not tickers <= set(names):
        raise ValueError("candidate company aliases are incomplete")

    parents = {ticker: ticker for ticker in names}

    def root(ticker: str) -> str:
        while parents[ticker] != ticker:
            ticker = parents[ticker]
        return ticker

    owners: dict[str, str] = {}
    for ticker, values in names.items():
        if not isinstance(values, list) or not values or any(
            not isinstance(name, str) or len(name.strip()) < 1 for name in values
        ):
            raise ValueError("company aliases are empty or invalid")
        for name in values:
            key = name.strip().casefold()
            if key in owners:
                parents[root(ticker)] = root(owners[key])
            owners[key] = ticker
    groups: dict[str, list[str]] = {}
    for ticker in parents:
        groups.setdefault(root(ticker), []).append(ticker)
    epoch = original.get("market_date")
    assets = {
        ticker: "asset_" + canonical_sha256([epoch, ticker])[:16]
        for ticker in parents
    }
    issuers = {
        ticker: "issuer_" + canonical_sha256([epoch, sorted(groups[root(ticker)])])[:16]
        for ticker in parents
    }
    replacements = {name: issuers[ticker] for name, ticker in owners.items()}
    tokens = sorted(replacements, key=lambda value: (-len(value), value))
    name_pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(name) for name in tokens) + r")(?!\w)",
        re.IGNORECASE,
    )
    ticker_pattern = re.compile(
        r"(?<![A-Za-z0-9_])(?:"
        + "|".join(re.escape(ticker) for ticker in sorted(
            assets, key=lambda value: (-len(value), value)))
        + r")(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )

    def transform(value: object, *, key: str | None = None) -> object:
        if key == "sector":
            return copy.deepcopy(value)
        if isinstance(value, str):
            if key == "ticker" and value.upper() in assets:
                return assets[value.upper()]
            value = name_pattern.sub(
                lambda match: replacements[match.group().casefold()], value)
            return ticker_pattern.sub(
                lambda match: assets[match.group().upper()], value)
        if isinstance(value, list):
            return [transform(item) for item in value]
        if isinstance(value, dict):
            return {name: transform(item, key=name) for name, item in value.items()}
        return value

    payload = transform(original)
    return _treatment(original, payload, "blind", {
        "asset_ids": assets,
        "issuer_ids": issuers,
        "alias_snapshot_sha256": canonical_sha256(aliases),
    })


def _evidence_ids(value: object) -> set[str]:
    if isinstance(value, dict):
        own = {value["evidence_id"]} if isinstance(value.get("evidence_id"), str) else set()
        return own.union(*(_evidence_ids(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_evidence_ids(item) for item in value)
                           ) if value else set()
    return set()


def ablate(original: dict, kind: str) -> dict:
    """Keep only registered price or text/sector/earnings inputs."""
    if kind not in {"price_only", "text_only"}:
        raise ValueError("unknown challenger input ablation")
    payload = {
        key: copy.deepcopy(value) for key, value in original.items() if key in META_FIELDS
    }
    fields = PRICE_FIELDS if kind == "price_only" else TEXT_FIELDS
    if kind == "price_only":
        payload["market"] = {
            key: copy.deepcopy(value) for key, value in original["market"].items()
            if key in {"market_date", "spy_close", "spy_daily_return", "regime", "evidence_id"}
        }
        payload["event_facts"] = [
            copy.deepcopy(row) for row in original.get("event_facts", [])
            if row.get("fact_type") == "p15.event.intraday_mover"
        ]
    else:
        payload["market_headlines"] = copy.deepcopy(original.get("market_headlines", []))
        payload["event_facts"] = [
            copy.deepcopy(row) for row in original.get("event_facts", [])
            if row.get("fact_type") != "p15.event.intraday_mover"
        ]
    payload["candidates"] = []
    global_ids = _evidence_ids(payload)
    for candidate in original["candidates"]:
        row = {
            key: copy.deepcopy(value) for key, value in candidate.items() if key in fields
        }
        if "earnings" in row:
            row["earnings"] = {
                key: value for key, value in row["earnings"].items()
                if key in EARNINGS_FIELDS
            }
        visible = global_ids | _evidence_ids(row)
        row["allowed_evidence_ids"] = sorted(
            set(candidate["allowed_evidence_ids"]) & visible)
        payload["candidates"].append(row)
    return _treatment(original, payload, kind, {})


def memory_examples(
    candidates: list[dict], history: list[dict], *, champion_policy_sha256: str,
    decision_at: str,
) -> dict:
    """Select at most twenty known champion outcomes without outcome-based retrieval."""
    cutoff = _utc(decision_at)
    if (
        not re.fullmatch(r"[0-9a-f]{64}", champion_policy_sha256)
        or not candidates
        or any(not _finite(row.get("standout_score")) for row in candidates)
    ):
        raise ValueError("memory candidates require finite standout scores")
    eligible, seen = [], set()
    for row in history:
        if (
            row.get("policy_sha256") != champion_policy_sha256
            or row.get("horizon_sessions") != 5
            or row.get("evidence_class") != "prospective_forward"
            or _utc(row.get("label_mature_at")) >= cutoff
            or _utc(row.get("label_available_at")) >= cutoff
        ):
            continue
        if (
            _utc(row.get("decision_at")) >= _utc(row.get("label_mature_at"))
            or _utc(row.get("label_mature_at")) > _utc(row.get("label_available_at"))
            or row.get("decision_id") in seen
            or not _finite(row.get("standout_score"))
            or not _finite(row.get("net_excess_return"))
            or not isinstance(row.get("thesis"), str)
            or not row["thesis"].strip()
        ):
            raise ValueError("invalid matured memory evidence")
        seen.add(row["decision_id"])
        nearest = min(
            (
                row.get("stratum") != item.get("stratum"),
                row.get("sector", "unknown") != item.get("sector", "unknown"),
                abs(float(row["standout_score"]) - float(item["standout_score"])),
            )
            for item in candidates
        )
        key = (*nearest, -_utc(row["decision_at"]).timestamp(), str(row["decision_id"]))
        eligible.append((key, row))
    selected = [copy.deepcopy(row) for _, row in sorted(eligible)[:MEMORY_LIMIT]]
    body = {
        "champion_policy_sha256": champion_policy_sha256,
        "decision_at": cutoff.isoformat(),
        "eligible_count": len(eligible),
        "examples": selected,
        "rule": "best_chunk_stratum_sector_standout_recency_id",
        "limit": MEMORY_LIMIT,
    }
    return {**body, "memory_sha256": canonical_sha256(body)}
