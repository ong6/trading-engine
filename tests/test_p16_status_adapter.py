"""P16 status failures and primary-kill projection stay outside frozen P15 code."""
from datetime import datetime, timezone

from server import p16_status_adapter

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)


def test_primary_kill_ends_ineligible_comparisons_without_mutating_input():
    original = {"p15": {
        "status": "kill", "primary": {"status": "kill"},
        "books": {"status": "collecting", "comparisons": [{
            "eligible": False, "status": "collecting", "promotion_status": "collecting",
        }]},
    }}

    result = p16_status_adapter.with_primary_kill(original)

    assert result["p15"]["books"]["status"] == "killed"
    assert result["p15"]["books"]["comparisons"][0]["status"] == "killed"
    assert result["p15"]["books"]["comparisons"][0]["promotion_status"] == "killed"
    assert original["p15"]["books"]["comparisons"][0]["status"] == "collecting"


def test_p16_projection_failure_returns_unavailable_without_raising(monkeypatch):
    monkeypatch.setattr(
        p16_status_adapter.p16_reporting,
        "project",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad P16 report")),
    )

    result = p16_status_adapter.project(object(), generated_at=NOW)

    assert result["status"] == "unavailable"
    assert result["reason"] == "p16_status_projection_failed"
    assert result["execution_authority"] == "none"
