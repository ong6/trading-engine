"""Public count-only W4 replay report renderer."""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

from engine.lib.resources import write_text_atomic
from farm.replay.registration import REPLAY_REPORT_PATH


def render_replay_report(snapshot: Mapping) -> str:
    endpoint = snapshot.get("primary_endpoint", {"status": "unavailable"})
    coverage = snapshot.get("coverage", {})
    lines = [
        "# P16 historical replay lab",
        "",
        f"Status: **{snapshot.get('status', 'unavailable')}**",
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
        f"- Lockbox tag: {snapshot.get('lockbox_tag', 'unavailable')}",
    ]
    return "\n".join(lines) + "\n"


def write_replay_report(path: Path, snapshot: Mapping) -> Path:
    if path.as_posix() != REPLAY_REPORT_PATH and path.name != "replay.md":
        raise ValueError("unexpected_replay_report_path")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(path, render_replay_report(snapshot))
    return path
