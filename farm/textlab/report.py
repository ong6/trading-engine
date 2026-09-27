"""Count-only report for the reduced text lab when inference is unconfigured."""
from __future__ import annotations

from typing import Mapping


def render_textlab_report(inventory: Mapping, readiness: Mapping) -> str:
    counts = inventory.get("year_counts", {})
    lines = [
        "# P16 time-locked text lab",
        "",
        f"Status: **{readiness.get('status', 'unconfigured')}**",
        "",
        "The full 2015-2025 8-K item 2.02 inventory is retained before price-label filtering.",
        "The registered reduced variant selects issuers by SHA-256 CIK modulo 4 equals zero.",
        "No later checkpoint substitutes for a missing time-locked checkpoint.",
        "",
        "## Corpus years",
        "",
    ]
    lines.extend(f"- {year}: {int(counts.get(str(year), 0))}" for year in range(2015, 2026))
    lines.extend([
        "",
        "## Inference",
        "",
        f"- Variant: {readiness.get('variant', 'text-chrono-reduced-ridge-v1')}",
        f"- Reason: {readiness.get('reason', 'unconfigured')}",
        "- Matched 2024 look-ahead control: unavailable until the same reduced inference runs.",
    ])
    return "\n".join(lines) + "\n"
