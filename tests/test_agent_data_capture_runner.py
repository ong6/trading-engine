"""The aggregate agent data-capture runner isolates stage failures."""

from __future__ import annotations

from server import agent_data_capture_runner


def _step(name, calls, *, fail=False):
    def capture(argv):
        assert argv == ["capture"]
        calls.append(name)
        if fail:
            raise RuntimeError("injected capture failure")
        return 0

    return name, capture


def test_runner_runs_fourth_step_after_third_fails_and_exits_one(capsys):
    calls = []
    result = agent_data_capture_runner.run(
        (
            _step("price_observations", calls),
            _step("corporate_action_observations", calls),
            _step("provider_responses", calls, fail=True),
            _step("independent_price_evidence", calls),
        )
    )

    assert result == 1
    assert calls == [
        "price_observations",
        "corporate_action_observations",
        "provider_responses",
        "independent_price_evidence",
    ]
    output = capsys.readouterr().out
    assert "step=provider_responses status=failed" in output
    assert "step=independent_price_evidence status=completed" in output
    assert "status=failed failed_steps=provider_responses" in output
