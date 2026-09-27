"""Narrow, inert boundary for feeding registered replay prices to P15 helpers."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping, Sequence

from engine.daily_opportunities import p15_universe
from farm.replay.asof import (
    SplitQuarantineError,
    asof_split_adjusted_bars,
    quarantined_exposure_counts,
)
from farm.replay.registration import SPLIT_KNOWLEDGE_PRIMARY
from server import p15_scoring_runner
from sim import p15_books, p15_fills


def prepare_p15_price_inputs(
    reconstructed_bars: Sequence[Mapping], actions: Sequence[Mapping],
    exposures: Iterable[Mapping], *, as_of: datetime, registered_windows: Sequence[str],
    knowledge_policy: str = SPLIT_KNOWLEDGE_PRIMARY,
) -> tuple[list[dict], list[dict]]:
    """Reject held/pending split uncertainty before exposing any replay price input."""
    counts = quarantined_exposure_counts(
        actions, exposures, registered_windows=registered_windows,
        knowledge_policy=knowledge_policy,
    )
    if any(row["held"] or row["pending"] for row in counts):
        raise SplitQuarantineError("p15_replay_exposure_quarantined")
    bars = asof_split_adjusted_bars(
        reconstructed_bars, actions, as_of=as_of,
        knowledge_policy=knowledge_policy,
    )
    return bars, counts


def gate_candidates(bundle: dict) -> dict:
    return p15_scoring_runner._gate_candidates(bundle)


def build_context(
    bundle: dict, news: dict, cutoff: datetime, event_facts: list[dict] | None = None
) -> tuple[dict, dict[str, set[str]]]:
    return p15_scoring_runner._context(bundle, news, cutoff, event_facts)


def request_input(
    bundle: dict,
    context: dict,
    candidates: list[dict],
    *,
    chunk_index: int,
    sample_index: int,
    seed: int,
    cutoff: datetime,
    used_orders: set[tuple[str, ...]],
) -> dict:
    return p15_scoring_runner._request_input(
        bundle,
        context,
        candidates,
        chunk_index=chunk_index,
        sample_index=sample_index,
        seed=seed,
        cutoff=cutoff,
        used_orders=used_orders,
    )


def validate_output(
    output: object, candidates: list[dict], allowed: dict[str, set[str]]
) -> dict[str, dict]:
    return p15_scoring_runner._validate_output(output, candidates, allowed)


def aggregate(candidates: list[dict], samples: list[dict[str, dict]]) -> list[dict]:
    return p15_scoring_runner._aggregate(candidates, samples)


def unavailable(candidates: list[dict], reason: str) -> list[dict]:
    return p15_scoring_runner._unavailable(candidates, reason)


def pinned_dependencies() -> dict:
    """Expose the exact modules/functions the replay registration must hash."""
    return {
        "universe": p15_universe,
        "books": p15_books,
        "fills": p15_fills,
        "scoring": p15_scoring_runner,
    }
