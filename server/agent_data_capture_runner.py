"""Run every agent data-capture stage and report aggregate failure."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from engine.lib.log import get_logger

from . import (
    agent_corporate_action_observations,
    agent_independent_price_evidence,
    agent_price_observations,
    agent_provider_responses,
)

CaptureMain = Callable[[list[str] | None], int]
CaptureStep = tuple[str, CaptureMain]
CAPTURE_STEPS: tuple[CaptureStep, ...] = (
    ("price_observations", agent_price_observations.main),
    ("corporate_action_observations", agent_corporate_action_observations.main),
    ("provider_responses", agent_provider_responses.main),
    ("independent_price_evidence", agent_independent_price_evidence.main),
)
log = get_logger("agent_data_capture")


def run(steps: Iterable[CaptureStep] = CAPTURE_STEPS) -> int:
    failures = []
    for name, capture_main in steps:
        log.info("[agent-data-capture] step=%s status=started", name)
        try:
            exit_code = capture_main(["capture"])
        except Exception:
            failures.append(name)
            log.exception("[agent-data-capture] step=%s status=failed", name)
            continue
        if exit_code:
            failures.append(name)
            log.error(
                "[agent-data-capture] step=%s status=failed exit_code=%d",
                name,
                exit_code,
            )
            continue
        log.info("[agent-data-capture] step=%s status=completed", name)
    if failures:
        log.error(
            "[agent-data-capture] status=failed failed_steps=%s",
            ",".join(failures),
        )
        return 1
    log.info("[agent-data-capture] status=completed")
    return 0


def main() -> int:
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
