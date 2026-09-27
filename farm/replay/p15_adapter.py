"""Narrow, inert boundary for feeding registered replay prices to P15 helpers."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping, Sequence

from farm.replay.asof import (
    SplitQuarantineError,
    asof_split_adjusted_bars,
    quarantined_exposure_counts,
)
from farm.replay.registration import SPLIT_KNOWLEDGE_PRIMARY


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
