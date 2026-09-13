"""Versioned comparison declarations for new walk-forward artifacts.

These mappings are reporting assumptions, not proof that the choices were made
before historical returns were observed. The runner stamps both the version
and selected control into each result so later report-code edits cannot silently
change an existing artifact's relative verdict.
"""
from __future__ import annotations

EW = "ew_benchmark"
SPY = "spy_benchmark"
CONTROLS = frozenset({EW, SPY})
CONTROL_PROTOCOL = "wf-controls-2026-09-07-v1"

# ETF and sleeve-allocation rules are measured against the investable market
# alternative. Screen-driven single-name rules use the same-universe EW book so
# survivorship and screen-selection bias are more nearly shared.
SPY_BOOKS = frozenset({
    "agentic_alloc",
    "agentic_alloc_frozen",
    "dual_momentum",
    "dual_momentum_gated",
    "macro_composite",
    "multi_asset_trend",
    "sector_momentum",
})


def declared_control(config_id: str) -> str | None:
    """Return the v1 report control; benchmarks are reference series."""
    if config_id in CONTROLS:
        return None
    return SPY if config_id in SPY_BOOKS else EW


def declaration(config_id: str) -> dict:
    """Serializable declaration captured when a result begins running."""
    return {
        "protocol": CONTROL_PROTOCOL,
        "control_id": declared_control(config_id),
        "evidence_role": "exploratory_historical_comparison",
    }
