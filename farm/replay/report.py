"""Public count-only W4 replay report renderer."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from engine.lib.resources import write_text_atomic


def render_replay_report(snapshot: Mapping) -> str:
    endpoint = snapshot.get("primary_endpoint", {"status": "unavailable"})
    coverage = snapshot.get("coverage", {})
    lockbox_tag = snapshot.get("lockbox_tag", "unavailable")
    result_status = snapshot.get("status", "unavailable")
    if lockbox_tag != "confirmatory":
        result_status = "exploratory"
    lines = [
        "# P16 historical replay lab",
        "",
        f"Status: **{result_status}**",
        "",
        "Research-only evidence; it cannot promote a policy or authorize orders.",
        "",
        "## Coverage",
        "",
        f"- Candidate sessions: {int(coverage.get('candidate_sessions', 0))}",
        f"- Unavailable chunks: {int(coverage.get('unavailable_chunks', 0))}",
        f"- Capture-confirmed items: {int(coverage.get('capture_confirmed', 0))}",
        f"- Publish-only headlines: {int(coverage.get('publish_only_headlines', 0))}",
        "",
        "## Registered primary endpoint",
        "",
        f"- Result: {endpoint.get('status', 'unavailable')}",
        f"- Eligible sessions: {int(endpoint.get('eligible_sessions', 0))}",
        f"- Notes minus no-notes mean: {endpoint.get('estimate', 'unavailable')}",
        f"- One-sided 95% lower bound: {endpoint.get('one_sided_lower_95', 'unavailable')}",
        "",
        "## Mechanics",
        "",
        f"- Book status: {snapshot.get('book_status', 'unavailable')}",
        f"- Raw-price spot check: {snapshot.get('raw_price_status', 'unavailable')}",
        f"- Lockbox tag: {lockbox_tag}",
    ]
    return "\n".join(lines) + "\n"


def write_replay_report(path: Path, snapshot: Mapping) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, render_replay_report(snapshot))
    return path
