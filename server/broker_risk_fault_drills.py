"""Bounded, source-bound fault drills for the inert broker-risk boundary."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path

from engine.lib.provenance import canonical_sha256
from engine.lib.settings import REPO_ROOT

from . import host_command
from .file_utils import read_bytes

SCHEMA_VERSION = 1
SUITE_ID = "broker-risk-boundary-v1"
MAX_OUTPUT_BYTES = 1_048_576
CASE_TIMEOUT_SECONDS = 120.0
DRILL_CASES = (
    {
        "id": "risk_faults_before_submission",
        "target": (
            "tests/test_broker_ledger.py::"
            "test_risk_faults_stop_before_submission_boundary"
        ),
        "property": (
            "stale data, reconciliation, halt, corporate-action, reservation, "
            "loss, and drawdown faults make zero adapter calls"
        ),
    },
    {
        "id": "submission_timeout_restart",
        "target": (
            "tests/test_broker_ledger.py::"
            "test_submit_once_failure_persists_uncertainty_and_never_blind_retries"
        ),
        "property": "timeout remains uncertain across re-entry without duplicate submission",
    },
    {
        "id": "malformed_acknowledgement",
        "target": (
            "tests/test_broker_ledger.py::"
            "test_malformed_adapter_acknowledgement_leaves_uncertain"
        ),
        "property": "malformed acknowledgement cannot become an acknowledged order",
    },
    {
        "id": "conflicting_duplicate_intent",
        "target": (
            "tests/test_broker_ledger.py::"
            "test_submit_once_rejects_conflicting_replay_before_adapter_call"
        ),
        "property": "conflicting duplicate intent makes no second adapter call",
    },
    {
        "id": "expired_decision",
        "target": (
            "tests/test_broker_ledger.py::"
            "test_expired_risk_stops_before_submission_event_or_adapter_call"
        ),
        "property": "expired risk evidence makes no adapter call",
    },
    {
        "id": "default_halted_restart",
        "target": (
            "tests/test_broker_risk_control.py::"
            "test_halt_events_are_append_only_hash_chained_and_survive_reopen"
        ),
        "property": "durable one-way halt evidence remains halted across database reopen",
    },
    {
        "id": "independent_operator_halt_cli",
        "target": (
            "tests/test_broker_risk_control.py::"
            "test_cli_is_an_independent_one_way_halt_path"
        ),
        "property": "local operator CLI can append and inspect a halt but cannot enable",
    },
    {
        "id": "assembled_snapshot_default_halt",
        "target": (
            "tests/test_broker_risk_snapshot.py::"
            "test_assembled_snapshot_is_default_halted_at_risk_gate"
        ),
        "property": (
            "stable adapter and reconciliation evidence still fails at the "
            "default-halted control"
        ),
    },
    {
        "id": "partial_fill_and_expiration",
        "target": (
            "tests/test_broker_reconciliation.py::"
            "test_partial_fill_and_expiration_are_representable_and_compared"
        ),
        "property": "partial-fill and expiration state remains explicit and comparable",
    },
    {
        "id": "rejected_cancel",
        "target": (
            "tests/test_simulator_broker_adapter.py::"
            "test_terminal_filled_order_cannot_be_cancelled"
        ),
        "property": "rejected cancellation cannot mutate a terminal filled order",
    },
    {
        "id": "reconciliation_difference",
        "target": (
            "tests/test_broker_reconciliation.py::"
            "test_reconciliation_classifies_account_position_and_fill_differences"
        ),
        "property": "cash, position, and fill differences are classified and retained",
    },
    {
        "id": "changing_snapshot",
        "target": (
            "tests/test_broker_reconciliation.py::"
            "test_snapshot_rejects_state_that_changes_during_capture"
        ),
        "property": "changing broker state cannot produce a trusted snapshot",
    },
    {
        "id": "changing_snapshot_during_assembly",
        "target": (
            "tests/test_broker_risk_snapshot.py::"
            "test_assembler_rejects_state_change_after_evidence_read"
        ),
        "property": "state changing across risk assembly cannot produce a snapshot",
    },
    {
        "id": "startup_reconciled_halted_restart",
        "target": (
            "tests/test_broker_startup_readiness.py::"
            "test_restart_preserves_halted_startup_assessment"
        ),
        "property": (
            "restart reaches only reconciled-halted state with no submission authority"
        ),
    },
    {
        "id": "emergency_stop_cancel_all",
        "target": (
            "tests/test_broker_emergency_stop.py::"
            "test_success_is_halt_first_durable_and_exactly_replayable"
        ),
        "property": (
            "halt is durable before reads and every planned open order is cancelled "
            "exactly once before completion"
        ),
    },
    {
        "id": "emergency_stop_timeout_restart",
        "target": (
            "tests/test_broker_emergency_stop.py::"
            "test_timeout_leaves_halt_and_uncertainty_and_blocks_blind_retry"
        ),
        "property": (
            "cancel timeout leaves durable halt and uncertainty without blind retry"
        ),
    },
    {
        "id": "paper_lease_fail_closed",
        "target": (
            "tests/test_broker_paper_lease.py::"
            "test_current_bindings_must_match_and_pass_every_gate"
        ),
        "property": (
            "paper lease admission fails closed on identity, budget, release, "
            "readiness, or startup drift without granting submission authority"
        ),
    },
    {
        "id": "paper_intent_fail_closed",
        "target": (
            "tests/test_broker_paper_intent.py::"
            "test_agent_request_and_budget_drift_fail_closed"
        ),
        "property": (
            "paper intent eligibility fails closed on agent binding, exact request, "
            "or cumulative lease-budget drift without consuming authority"
        ),
    },
    {
        "id": "hybrid_paper_intent_fail_closed",
        "target": (
            "tests/test_broker_paper_intent.py::"
            "test_hybrid_vetoed_buy_cannot_enter_the_future_consumption_bridge"
        ),
        "property": (
            "a buy removed by the hybrid veto cannot become eligible for future "
            "lease consumption"
        ),
    },
    {
        "id": "paper_activation_plan_inert",
        "target": (
            "tests/test_broker_paper_activation_plan.py::"
            "test_changed_halt_chain_invalidates_prior_startup_evidence"
        ),
        "property": (
            "the activation plan re-verifies startup, runtime, and halt-chain "
            "evidence without persisting or granting authority"
        ),
    },
    {
        "id": "paper_authority_restart_invalidates",
        "target": (
            "tests/test_broker_paper_authority_transcript.py::"
            "test_restart_halt_and_expiry_close_the_design_epoch"
        ),
        "property": (
            "restart, a later halt, or expiry closes the proposed authority epoch "
            "without granting runtime submission authority"
        ),
    },
    {
        "id": "paper_authority_consumption_fail_closed",
        "target": (
            "tests/test_broker_paper_authority_transcript.py::"
            "test_capacity_and_atomic_pre_call_state_fail_closed"
        ),
        "property": (
            "capacity drift and a consumption not atomically paired with uncertain "
            "pre-call submission state fail closed"
        ),
    },
    {
        "id": "startup_blocks_incomplete_emergency_stop",
        "target": (
            "tests/test_broker_startup_readiness.py::"
            "test_startup_assessment_blocks_uncertain_cancellation_and_incomplete_stop"
        ),
        "property": (
            "startup remains blocked by uncertain cancellation and incomplete "
            "emergency-stop evidence"
        ),
    },
    {
        "id": "uncertain_submission_stable_absence_burned",
        "target": (
            "tests/test_broker_submission_resolution.py::"
            "test_resolved_absence_never_allows_submit_once_retry"
        ),
        "property": (
            "stable venue absence is durably adjudicated but permanently burns "
            "the original idempotency key"
        ),
    },
    {
        "id": "uncertain_submission_resolution_tamper_restart",
        "target": (
            "tests/test_broker_submission_resolution.py::"
            "test_tampering_fails_closed_and_restart_preserves_resolution"
        ),
        "property": (
            "retained stable-snapshot adjudication survives restart and fails "
            "closed after evidence tampering"
        ),
    },
    {
        "id": "agent_only_retained_evidence_tamper",
        "target": (
            "tests/test_agent_paper_evidence.py::"
            "test_loader_fails_closed_on_retained_evidence_tampering"
        ),
        "property": (
            "agent-only paper bindings are derived from complete retained evidence "
            "and fail closed after any covered row is tampered"
        ),
    },
    {
        "id": "hybrid_retained_evidence_tamper",
        "target": (
            "tests/test_agent_paper_evidence.py::"
            "test_hybrid_loader_fails_closed_on_retained_evidence_tampering"
        ),
        "property": (
            "hybrid paper bindings are derived from the exact candidate, model "
            "outcome or fallback, and effective order set and fail closed after "
            "any covered row is tampered"
        ),
    },
    {
        "id": "paper_usage_complete_transcript",
        "target": (
            "tests/test_broker_paper_usage.py::"
            "test_loader_rejects_truncated_or_wrong_head_transcript"
        ),
        "property": (
            "lease usage is derived from a complete head-matched transcript "
            "and cannot be understated by supplying a valid prefix"
        ),
    },
    {
        "id": "paper_runtime_epoch_and_control",
        "target": (
            "tests/test_broker_paper_runtime.py::"
            "test_runtime_epoch_changes_in_a_new_process_and_is_not_environment_driven"
        ),
        "property": (
            "the authority runtime epoch is generated per process and cannot be "
            "restored from caller-controlled environment state"
        ),
    },
    {
        "id": "paper_authority_risk_projection_inert",
        "target": (
            "tests/test_broker_paper_risk_projection.py::"
            "test_projection_preserves_historical_halt_and_remains_non_executable"
        ),
        "property": (
            "authority-aware risk projection preserves the durable historical "
            "halt and cannot enter the current risk evaluator"
        ),
    },
    {
        "id": "paper_authority_startup_scan",
        "target": (
            "tests/test_broker_paper_startup_scan.py::"
            "test_prior_process_open_epoch_is_verified_as_restart_invalidated"
        ),
        "property": (
            "startup re-verifies retained authority epochs and a prior-process "
            "activation cannot remain open after restart"
        ),
    },
    {
        "id": "paper_authority_startup_store_complete",
        "target": (
            "tests/test_broker_paper_startup_store.py::"
            "test_valid_truncated_prefix_and_omitted_rechained_epoch_fail_external_head"
        ),
        "property": (
            "durable startup loading binds the complete global retained row count "
            "and head so a valid prefix or omitted and rechained epoch fails closed"
        ),
    },
    {
        "id": "paper_authority_risk_evaluation_inert",
        "target": (
            "tests/test_broker_paper_risk_evaluation.py::"
            "test_open_epoch_runs_all_twenty_gates_but_cannot_authorize_submission"
        ),
        "property": (
            "a verified open epoch can evaluate all standard risk gates only as "
            "distinct design evidence rejected by the broker submission ledger"
        ),
    },
    {
        "id": "paper_atomic_consumption_plan_inert",
        "target": (
            "tests/test_broker_paper_consumption_plan.py::"
            "test_replay_is_proven_from_complete_usage"
        ),
        "property": (
            "the next consumption plan binds complete retained usage and rejects "
            "replayed identities without persisting or submitting"
        ),
    },
)
SOURCE_FILES = (
    "server/broker_contract.py",
    "server/agent_paper_evidence.py",
    "server/agent_model_client.py",
    "server/broker_emergency_stop.py",
    "server/broker_ledger.py",
    "server/broker_paper_activation_plan.py",
    "server/broker_paper_authority_transcript.py",
    "server/broker_paper_consumption_plan.py",
    "server/broker_paper_intent.py",
    "server/broker_paper_lease.py",
    "server/broker_paper_risk_evaluation.py",
    "server/broker_paper_risk_projection.py",
    "server/broker_paper_runtime.py",
    "server/broker_paper_startup_scan.py",
    "server/broker_paper_startup_store.py",
    "server/broker_paper_usage.py",
    "server/broker_reconciliation.py",
    "server/broker_risk.py",
    "server/broker_risk_control.py",
    "server/broker_risk_fault_drills.py",
    "server/broker_risk_snapshot.py",
    "server/broker_startup_readiness.py",
    "server/broker_submission.py",
    "server/broker_submission_resolution.py",
    "tests/conftest.py",
    "tests/test_agent_paper_evidence.py",
    "tests/test_broker_emergency_stop.py",
    "tests/test_broker_ledger.py",
    "tests/test_broker_paper_activation_plan.py",
    "tests/test_broker_paper_authority_transcript.py",
    "tests/test_broker_paper_consumption_plan.py",
    "tests/test_broker_paper_intent.py",
    "tests/test_broker_paper_lease.py",
    "tests/test_broker_paper_risk_evaluation.py",
    "tests/test_broker_paper_risk_projection.py",
    "tests/test_broker_paper_runtime.py",
    "tests/test_broker_paper_startup_scan.py",
    "tests/test_broker_paper_startup_store.py",
    "tests/test_broker_paper_usage.py",
    "tests/test_broker_reconciliation.py",
    "tests/test_broker_risk.py",
    "tests/test_broker_risk_control.py",
    "tests/test_broker_risk_snapshot.py",
    "tests/test_broker_startup_readiness.py",
    "tests/test_broker_submission_resolution.py",
    "tests/test_simulator_broker_adapter.py",
)


class BrokerRiskDrillError(RuntimeError):
    """The bounded drill suite or its source identity is invalid."""


CaseRunner = Callable[[str], object]


def _source_identity(repo_root: Path) -> dict:
    files = {}
    for relative in SOURCE_FILES:
        try:
            content = read_bytes(
                repo_root / relative,
                max_bytes=MAX_OUTPUT_BYTES,
                label="broker risk fault-drill source",
                allow_symlinked_parents=False,
            )
        except (OSError, ValueError) as exc:
            raise BrokerRiskDrillError(
                "broker risk fault-drill source is unavailable"
            ) from exc
        files[relative] = hashlib.sha256(content).hexdigest()
    return {
        "source_sha256": canonical_sha256(files),
        "source_file_count": len(files),
    }


def suite_identity(repo_root: Path = REPO_ROOT) -> dict:
    source = _source_identity(repo_root)
    body = {
        "schema_version": SCHEMA_VERSION,
        "suite_id": SUITE_ID,
        "cases": list(DRILL_CASES),
        **source,
        "execution_authority": "none",
    }
    return {**body, "suite_sha256": canonical_sha256(body)}


def _default_runner(target: str) -> object:
    return host_command.run_bounded(
        [sys.executable, "-m", "pytest", "-q", "-W", "error", target],
        cwd=REPO_ROOT,
        timeout=CASE_TIMEOUT_SECONDS,
        max_output_bytes=MAX_OUTPUT_BYTES,
    )


def _case_result(case: dict, completed: object) -> dict:
    if completed is None:
        return {
            "id": case["id"],
            "property": case["property"],
            "status": "indeterminate",
            "returncode": None,
            "output_sha256": None,
        }
    returncode = getattr(completed, "returncode", None)
    stdout = getattr(completed, "stdout", None)
    stderr = getattr(completed, "stderr", None)
    if (
        isinstance(returncode, bool)
        or not isinstance(returncode, int)
        or not isinstance(stdout, str)
        or not isinstance(stderr, str)
    ):
        raise BrokerRiskDrillError("broker risk fault-drill result is invalid")
    output = (stdout + stderr).encode()
    if len(output) > MAX_OUTPUT_BYTES:
        raise BrokerRiskDrillError("broker risk fault-drill output exceeds its bound")
    return {
        "id": case["id"],
        "property": case["property"],
        "status": "pass" if returncode == 0 else "fail",
        "returncode": returncode,
        "output_sha256": hashlib.sha256(output).hexdigest(),
    }


def run(
    *,
    repo_root: Path = REPO_ROOT,
    runner: CaseRunner = _default_runner,
) -> dict:
    """Run every isolated case and return hash-bound, non-authorizing evidence."""
    before = suite_identity(repo_root)
    results = [_case_result(case, runner(case["target"])) for case in DRILL_CASES]
    if suite_identity(repo_root) != before:
        raise BrokerRiskDrillError(
            "broker risk fault-drill source changed while the suite ran"
        )
    counts = {
        status: sum(result["status"] == status for result in results)
        for status in ("pass", "fail", "indeterminate")
    }
    status = (
        "pass"
        if counts == {"pass": len(DRILL_CASES), "fail": 0, "indeterminate": 0}
        else "fail"
        if counts["fail"]
        else "indeterminate"
    )
    body = {
        **before,
        "status": status,
        "case_count": len(results),
        "passed_count": counts["pass"],
        "failed_count": counts["fail"],
        "indeterminate_count": counts["indeterminate"],
        "results": results,
    }
    return {**body, "run_sha256": canonical_sha256(body)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "identity"))
    args = parser.parse_args(argv)
    result = run() if args.command == "run" else suite_identity()
    print(json.dumps(result, sort_keys=True))
    return int(result.get("status", "pass") != "pass")


if __name__ == "__main__":
    raise SystemExit(main())
