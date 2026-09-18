"""Persisted, source-bound fault drills for the shadow decision state machine."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from engine.lib import db as engine_db
from engine.lib.provenance import canonical_sha256
from engine.lib.resources import advisory_file_lock
from engine.lib.settings import DEFAULT_DB, REPO_ROOT

from . import agent_context, agent_policy, host_command
from .file_utils import read_bytes

SCHEMA_VERSION = 1
SUITE_ID = "agent-shadow-state-machine-v1"
COVERAGE_LEVEL = "application_state_machine"
MAX_OUTPUT_BYTES = 1_048_576
CASE_TIMEOUT_SECONDS = 120.0
LOCK_PATH = REPO_ROOT / "store" / ".agent-fault-drill.lock"
DRILL_CASES = (
    {
        "id": "agent_only_duplicate_window_replay",
        "runner": "pytest",
        "target": (
            "tests/test_agent_shadow_runner.py::"
            "test_no_action_is_persisted_and_replayed_without_second_model_call"
        ),
        "mode": "agent_only",
        "property": "one model call and one attempt per decision window",
    },
    {
        "id": "scheduled_duplicate_window_replay",
        "runner": "pytest",
        "target": (
            "tests/test_agent_shadow_runner.py::"
            "test_scheduled_no_action_uses_runner_replay_without_order_mutation"
        ),
        "mode": "agent_only",
        "property": "scheduled replay creates no second model call or order",
    },
    {
        "id": "agent_only_unrecorded_response_restart",
        "runner": "pytest",
        "target": (
            "tests/test_agent_shadow_runner.py::"
            "test_started_attempt_without_response_becomes_uncertain_without_retry"
        ),
        "mode": "agent_only",
        "property": "interrupted unrecorded response becomes uncertain without retry",
    },
    {
        "id": "agent_only_recorded_response_restart",
        "runner": "pytest",
        "target": (
            "tests/test_agent_shadow_runner.py::"
            "test_recorded_response_is_completed_after_restart_without_model_retry"
        ),
        "mode": "agent_only",
        "property": "recorded response resumes without model regeneration",
    },
    {
        "id": "hybrid_unrecorded_response_restart",
        "runner": "pytest",
        "target": (
            "tests/test_agent_shadow_runner.py::"
            "test_interrupted_hybrid_request_falls_back_without_regeneration"
        ),
        "mode": "hybrid",
        "property": "interrupted hybrid request uses the registered fallback without retry",
    },
    {
        "id": "isolated_paper_attribution_tamper",
        "runner": "pytest",
        "target": (
            "tests/test_agent_paper_attribution.py::"
            "test_unattributed_or_cross_book_rows_fail_closed"
        ),
        "mode": "shared_attribution",
        "property": (
            "unattributed orders and cross-book fills cannot become policy returns"
        ),
    },
    {
        "id": "paper_authority_stage_separation",
        "runner": "pytest",
        "target": (
            "tests/test_agent_authority_read_models.py::"
            "test_readiness_is_shadow_only_and_exposes_concrete_blockers"
        ),
        "mode": "shared_authority",
        "property": (
            "human-approved and automatic paper keep separate fail-closed "
            "prerequisites and neither projection grants execution authority"
        ),
    },
    {
        "id": "paper_book_preflight_read_only",
        "runner": "pytest",
        "target": (
            "tests/test_agent_paper_book_preflight.py::"
            "test_complete_preflight_passes_without_mutating_any_table"
        ),
        "mode": "shared_attribution",
        "property": (
            "isolated-book initialization preflight verifies both modes without "
            "mutating simulator or protected control state"
        ),
    },
    {
        "id": "paper_attribution_schema_migration_rollback",
        "runner": "pytest",
        "target": (
            "tests/test_migrate_agent_paper_attribution.py::"
            "test_post_migration_scope_failure_rolls_back"
        ),
        "mode": "shared_attribution",
        "property": (
            "backup-gated attribution schema installation rolls back when its "
            "post-DDL scope proof fails"
        ),
    },
    {
        "id": "inactive_paper_book_initialization_rollback",
        "runner": "pytest",
        "target": (
            "tests/test_initialize_agent_paper_book.py::"
            "test_post_insert_scope_failure_rolls_back"
        ),
        "mode": "shared_attribution",
        "property": (
            "backup-gated inactive-book initialization rolls back all three "
            "records when its exact post-insert scope proof fails"
        ),
    },
    {
        "id": "human_paper_review_non_authorizing",
        "runner": "pytest",
        "target": (
            "tests/test_broker_human_paper_review.py::"
            "test_retained_verifier_rejects_self_consistent_review_fact_forgery"
        ),
        "mode": "shared_authority",
        "property": (
            "self-consistent forged review facts cannot match independently "
            "reloaded evidence or become approval or submission authority"
        ),
    },
    {
        "id": "human_paper_review_cli_read_only",
        "runner": "pytest",
        "target": (
            "tests/test_review_agent_paper_intent.py::"
            "test_build_and_verify_round_trip_without_database_mutation"
        ),
        "mode": "shared_authority",
        "property": (
            "the operator CLI builds and revalidates one exact packet through "
            "read-only database access without mutating decision or simulator state"
        ),
    },
    {
        "id": "human_paper_approval_authentication_non_authorizing",
        "runner": "pytest",
        "target": (
            "tests/test_broker_human_paper_approval.py::"
            "test_retained_composition_rejects_rehashed_forgery_before_authenticator"
        ),
        "mode": "shared_authority",
        "property": (
            "retained evidence is reloaded before detached-authenticator verification "
            "so a self-consistent forged packet cannot reach authentication or authority"
        ),
    },
    {
        "id": "human_paper_approval_replay_protection",
        "runner": "pytest",
        "target": (
            "tests/test_broker_human_paper_approval.py::"
            "test_conflicting_approval_or_request_identity_reuse_fails_closed"
        ),
        "mode": "shared_authority",
        "property": (
            "authenticated evidence is retained once and conflicting approval or "
            "request identity reuse fails without granting authority"
        ),
    },
    {
        "id": "human_paper_approval_complete_history",
        "runner": "pytest",
        "target": (
            "tests/test_broker_human_paper_approval.py::"
            "test_truncated_or_wrong_approval_history_cannot_match_trusted_head"
        ),
        "mode": "shared_authority",
        "property": (
            "a valid but truncated or replaced approval-observation history "
            "cannot match an independently trusted global count and head"
        ),
    },
    {
        "id": "trae_model_catalog_drift",
        "runner": "pytest",
        "target": (
            "tests/test_agent_model_client.py::"
            "test_generation_rejects_catalog_drift_after_model_response"
        ),
        "mode": "shared_model_transport",
        "property": (
            "the selected Trae alias, internal max-routing key, catalog marker, "
            "proxy version, and runtime identity remain unchanged across generation"
        ),
    },
    {
        "id": "data_discrepancy_review_non_authorizing",
        "runner": "pytest",
        "target": (
            "tests/test_agent_data_discrepancy_review.py::"
            "test_retained_verify_rejects_rehashed_forgery_and_cache_change"
        ),
        "mode": "shared_data",
        "property": (
            "a rehashed source/cache discrepancy packet cannot survive independent "
            "retained-evidence reload or mutate data and trading authority"
        ),
    },
    {
        "id": "data_discrepancy_adjudication_non_remediating",
        "runner": "pytest",
        "target": (
            "tests/test_agent_data_discrepancy_adjudication.py::"
            "test_forged_stale_or_changed_evidence_aborts_without_schema_or_event"
        ),
        "mode": "shared_data",
        "property": (
            "operator adjudication requires fresh independently reloaded evidence "
            "and cannot repair cache, quarantine a ticker, or grant authority"
        ),
    },
    {
        "id": "independent_price_evidence_tamper",
        "runner": "pytest",
        "target": (
            "tests/test_agent_independent_price_evidence.py::"
            "test_tampered_raw_response_or_chain_fails_closed"
        ),
        "mode": "shared_data",
        "property": (
            "independent raw responses and derived observation chains are "
            "retained exactly and fail closed on tampering"
        ),
    },
    {
        "id": "release_review_non_authorizing",
        "runner": "pytest",
        "target": (
            "tests/test_agent_release_readiness.py::"
            "test_rehashed_readiness_forgery_and_failed_authenticator_are_rejected"
        ),
        "mode": "shared_authority",
        "property": (
            "release review requires independently trusted release readiness, an "
            "explicit reviewer policy, and a valid detached authenticator while "
            "remaining non-persisting and non-authorizing"
        ),
    },
    {
        "id": "release_review_replay_protection",
        "runner": "pytest",
        "target": (
            "tests/test_agent_release_review_store.py::"
            "test_current_release_drift_fails_before_authentication_or_schema"
        ),
        "mode": "shared_authority",
        "property": (
            "release-review recording re-inspects the current candidate and "
            "rejects trusted-identity drift before authentication or persistence"
        ),
    },
    {
        "id": "release_review_complete_history",
        "runner": "pytest",
        "target": (
            "tests/test_agent_release_review_store.py::"
            "test_truncated_or_wrong_release_review_history_cannot_match_trusted_head"
        ),
        "mode": "shared_authority",
        "property": (
            "a valid but truncated or replaced release-review history cannot "
            "match an independently trusted global count and head"
        ),
    },
    {
        "id": "release_review_schema_migration_rollback",
        "runner": "pytest",
        "target": (
            "tests/test_migrate_agent_release_review.py::"
            "test_post_migration_scope_failure_rolls_back"
        ),
        "mode": "shared_authority",
        "property": (
            "backup-gated release-review schema installation rolls back when "
            "its post-DDL scope proof fails"
        ),
    },
    {
        "id": "human_approval_schema_migration_rollback",
        "runner": "pytest",
        "target": (
            "tests/test_migrate_agent_human_approval.py::"
            "test_post_migration_scope_failure_rolls_back"
        ),
        "mode": "shared_authority",
        "property": (
            "backup-gated human-approval schema installation rolls back when "
            "its post-DDL scope proof fails"
        ),
    },
    {
        "id": "paper_authority_store_schema_migration_rollback",
        "runner": "pytest",
        "target": (
            "tests/test_migrate_agent_paper_authority_store.py::"
            "test_post_migration_scope_failure_rolls_back"
        ),
        "mode": "shared_authority",
        "property": (
            "backup-gated paper-authority evidence schema installation "
            "rolls back when its post-DDL scope proof fails"
        ),
    },
    {
        "id": "paper_authority_activation_append_rollback",
        "runner": "pytest",
        "target": (
            "tests/test_broker_paper_authority_store.py::"
            "test_failed_post_insert_chain_verification_rolls_back"
        ),
        "mode": "shared_authority",
        "property": (
            "a failed complete-chain verification rolls back the automatic-paper "
            "activation append without creating submission authority"
        ),
    },
    {
        "id": "paper_authority_atomic_pre_call_rollback",
        "runner": "pytest",
        "target": (
            "tests/test_broker_paper_consumption_store.py::"
            "test_failed_post_write_verification_rolls_back_all_four_records"
        ),
        "mode": "shared_authority",
        "property": (
            "failed post-write verification atomically rolls back authority "
            "consumption, risk evidence, broker intent, and submission marker"
        ),
    },
    {
        "id": "systemd_process_restart",
        "runner": "systemd_transient",
        "target": "restart_on_failure_once",
        "mode": "shared_supervision",
        "property": "user-systemd restarts one failed process and reaches success",
    },
)
SOURCE_FILES = tuple(
    sorted(
        set(agent_context.BOUNDARY_FILES)
        | {
            "pyproject.toml",
            "uv.lock",
            "server/agent_authority_read_models.py",
            "server/agent_data_discrepancy_adjudication.py",
            "server/agent_data_discrepancy_review.py",
            "server/agent_fault_drills.py",
            "server/agent_independent_price_evidence.py",
            "server/agent_release_readiness.py",
            "server/agent_release_review_store.py",
            "server/broker_human_paper_approval.py",
            "server/broker_human_paper_approval_store.py",
            "server/broker_human_paper_review.py",
            "server/broker_contract.py",
            "server/broker_ledger.py",
            "server/broker_paper_activation_plan.py",
            "server/broker_paper_authority_store.py",
            "server/broker_paper_authority_transcript.py",
            "server/broker_paper_consumption_plan.py",
            "server/broker_paper_consumption_store.py",
            "server/broker_paper_intent.py",
            "server/broker_paper_lease.py",
            "server/broker_paper_risk_evaluation.py",
            "server/broker_paper_risk_projection.py",
            "server/broker_paper_runtime.py",
            "server/broker_paper_startup_store.py",
            "server/broker_paper_usage.py",
            "server/broker_risk.py",
            "server/broker_risk_control.py",
            "server/json_utils.py",
            "server/host_command.py",
            "tests/agent_test_helpers.py",
            "tests/conftest.py",
            "tests/test_backup_database.py",
            "tests/test_adjudicate_agent_data_discrepancy.py",
            "tests/test_agent_data_discrepancy_adjudication.py",
            "tests/test_agent_data_discrepancy_review.py",
            "tests/test_agent_independent_price_evidence.py",
            "tests/test_agent_model_client.py",
            "tests/test_agent_paper_attribution.py",
            "tests/test_agent_paper_book_plan.py",
            "tests/test_agent_paper_book_preflight.py",
            "tests/test_agent_paper_evidence.py",
            "tests/test_agent_release_readiness.py",
            "tests/test_agent_release_review_store.py",
            "tests/test_migrate_agent_human_approval.py",
            "tests/test_migrate_agent_paper_authority_store.py",
            "tests/test_migrate_agent_release_review.py",
            "tests/test_agent_authority_read_models.py",
            "tests/test_agent_shadow_runner.py",
            "tests/test_broker_human_paper_approval.py",
            "tests/test_broker_human_paper_review.py",
            "tests/test_broker_paper_activation_plan.py",
            "tests/test_broker_paper_authority_store.py",
            "tests/test_broker_paper_authority_transcript.py",
            "tests/test_broker_paper_consumption_plan.py",
            "tests/test_broker_paper_consumption_store.py",
            "tests/test_broker_paper_intent.py",
            "tests/test_broker_paper_lease.py",
            "tests/test_broker_paper_risk_evaluation.py",
            "tests/test_broker_paper_risk_projection.py",
            "tests/test_broker_paper_runtime.py",
            "tests/test_broker_paper_startup_store.py",
            "tests/test_broker_paper_usage.py",
            "tests/test_broker_risk_snapshot.py",
            "tests/test_broker_startup_readiness.py",
            "tests/test_initialize_agent_paper_book.py",
            "tests/test_migrate_agent_paper_attribution.py",
            "tests/test_review_agent_paper_intent.py",
            "tools/backup_database.py",
            "tools/adjudicate_agent_data_discrepancy.py",
            "tools/initialize_agent_paper_book.py",
            "tools/migrate_agent_human_approval.py",
            "tools/migrate_agent_paper_attribution.py",
            "tools/migrate_agent_paper_authority_store.py",
            "tools/migrate_agent_release_review.py",
            "tools/review_agent_paper_intent.py",
            "tools/review_agent_data_discrepancy.py",
        }
    )
)


class FaultDrillError(RuntimeError):
    """Fault-drill evidence is unavailable, invalid, or internally inconsistent."""


CaseRunner = Callable[[str], object]


def _timestamp(value: datetime) -> str:
    if type(value) is not datetime:
        raise FaultDrillError("fault drill timestamp is invalid")
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_identity(repo_root: Path) -> dict:
    files = {}
    for relative in SOURCE_FILES:
        try:
            content = read_bytes(
                repo_root / relative,
                max_bytes=MAX_OUTPUT_BYTES,
                label="fault drill source",
                allow_symlinked_parents=False,
            )
        except (OSError, ValueError) as exc:
            raise FaultDrillError("fault drill source is unavailable") from exc
        files[relative] = _sha256(content)
    return {
        "source_sha256": canonical_sha256(files),
        "source_file_count": len(files),
    }


def _suite_identity(repo_root: Path, registration_path: Path) -> dict:
    source = _source_identity(repo_root)
    try:
        registry_sha256 = agent_policy.registry(registration_path)[
            "registry_sha256"
        ]
    except agent_policy.PolicyError as exc:
        raise FaultDrillError(str(exc)) from exc
    suite = {
        "schema_version": SCHEMA_VERSION,
        "suite_id": SUITE_ID,
        "coverage_level": COVERAGE_LEVEL,
        "cases": list(DRILL_CASES),
        "source_sha256": source["source_sha256"],
        "source_file_count": source["source_file_count"],
        "registry_sha256": registry_sha256,
        "execution_authority": "none",
    }
    return {**suite, "suite_sha256": canonical_sha256(suite)}


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_fault_drill_runs (
            id                    BIGINT PRIMARY KEY,
            schema_version        INTEGER NOT NULL,
            suite_id              VARCHAR NOT NULL,
            suite_sha256          VARCHAR NOT NULL,
            coverage_level        VARCHAR NOT NULL,
            source_sha256         VARCHAR NOT NULL,
            source_file_count     INTEGER NOT NULL,
            registry_sha256       VARCHAR NOT NULL,
            started_at            TIMESTAMP NOT NULL,
            completed_at          TIMESTAMP NOT NULL,
            status                VARCHAR NOT NULL,
            case_count            INTEGER NOT NULL,
            passed_count          INTEGER NOT NULL,
            failed_count          INTEGER NOT NULL,
            indeterminate_count   INTEGER NOT NULL,
            results_payload       VARCHAR NOT NULL,
            results_sha256        VARCHAR NOT NULL,
            run_sha256            VARCHAR NOT NULL UNIQUE
        )
        """
    )


def _default_runner(node_id: str) -> object:
    return host_command.run_bounded(
        [sys.executable, "-m", "pytest", "-W", "error", "-q", node_id],
        cwd=REPO_ROOT,
        timeout=CASE_TIMEOUT_SECONDS,
        max_output_bytes=MAX_OUTPUT_BYTES,
    )


def _systemd_restart_runner(_target: str) -> object:
    """Exercise the actual user-systemd restart policy without project state access."""
    with tempfile.TemporaryDirectory(
        prefix="trading-engine-agent-fault-drill."
    ) as directory:
        counter = Path(directory) / "starts"
        unit = (
            f"trading-engine-agent-fault-drill-{os.getpid()}-"
            f"{time.monotonic_ns()}"
        )
        result = host_command.run_bounded(
            [
                "systemd-run",
                "--user",
                "--wait",
                "--collect",
                f"--unit={unit}",
                "--property=Restart=on-failure",
                "--property=RestartSec=100ms",
                "--property=StartLimitBurst=2",
                "--property=StartLimitIntervalSec=30s",
                "--property=NoNewPrivileges=yes",
                "--property=ProtectSystem=strict",
                sys.executable,
                "-c",
                (
                    "import pathlib,sys; p=pathlib.Path(sys.argv[1]); "
                    "n=int(p.read_text())+1 if p.exists() else 1; "
                    "p.write_text(str(n)); "
                    "raise SystemExit(17 if n == 1 else 0)"
                ),
                str(counter),
            ],
            cwd=REPO_ROOT,
            timeout=30,
            max_output_bytes=MAX_OUTPUT_BYTES,
        )
        if result is None or result.returncode != 0:
            return result
        try:
            starts = read_bytes(
                counter,
                max_bytes=16,
                label="fault drill restart counter",
                allow_symlinked_parents=False,
            )
        except (OSError, ValueError):
            starts = b""
        return subprocess.CompletedProcess(
            result.args,
            0 if starts == b"2" else 1,
            result.stdout + f"\nrestart_count={starts.decode(errors='replace')}\n",
            result.stderr,
        )


def _case_result(case: dict, completed: object) -> dict:
    if completed is None:
        return {
            "id": case["id"],
            "mode": case["mode"],
            "property": case["property"],
            "status": "indeterminate",
            "returncode": None,
            "output_size_bytes": None,
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
        raise FaultDrillError("fault drill runner result is invalid")
    output = (stdout + stderr).encode()
    if len(output) > MAX_OUTPUT_BYTES:
        raise FaultDrillError("fault drill output exceeds its bound")
    return {
        "id": case["id"],
        "mode": case["mode"],
        "property": case["property"],
        "status": "pass" if returncode == 0 else "fail",
        "returncode": returncode,
        "output_size_bytes": len(output),
        "output_sha256": _sha256(output),
    }


def _persist(
    con: duckdb.DuckDBPyConnection,
    suite: dict,
    results: list[dict],
    *,
    started_at: datetime,
    completed_at: datetime,
) -> dict:
    init_schema(con)
    counts = {
        name: sum(item["status"] == name for item in results)
        for name in ("pass", "fail", "indeterminate")
    }
    status = (
        "pass"
        if counts == {"pass": len(DRILL_CASES), "fail": 0, "indeterminate": 0}
        else "fail"
        if counts["fail"]
        else "indeterminate"
    )
    result_payload = {
        "schema_version": SCHEMA_VERSION,
        "suite_sha256": suite["suite_sha256"],
        "results": results,
    }
    results_sha256 = canonical_sha256(result_payload)
    identity = {
        "schema_version": SCHEMA_VERSION,
        "suite_id": SUITE_ID,
        "suite_sha256": suite["suite_sha256"],
        "coverage_level": COVERAGE_LEVEL,
        "source_sha256": suite["source_sha256"],
        "source_file_count": suite["source_file_count"],
        "registry_sha256": suite["registry_sha256"],
        "started_at": _timestamp(started_at),
        "completed_at": _timestamp(completed_at),
        "status": status,
        "case_count": len(results),
        "passed_count": counts["pass"],
        "failed_count": counts["fail"],
        "indeterminate_count": counts["indeterminate"],
        "results_sha256": results_sha256,
        "execution_authority": "none",
    }
    run_sha256 = canonical_sha256(identity)
    next_id = int(
        con.execute(
            "SELECT COALESCE(MAX(id), 0) + 1 FROM agent_fault_drill_runs"
        ).fetchone()[0]
    )
    with engine_db.transaction(con):
        con.execute(
            "INSERT INTO agent_fault_drill_runs VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                next_id,
                SCHEMA_VERSION,
                SUITE_ID,
                suite["suite_sha256"],
                COVERAGE_LEVEL,
                suite["source_sha256"],
                suite["source_file_count"],
                suite["registry_sha256"],
                started_at,
                completed_at,
                status,
                len(results),
                counts["pass"],
                counts["fail"],
                counts["indeterminate"],
                json.dumps(
                    result_payload, sort_keys=True, separators=(",", ":")
                ),
                results_sha256,
                run_sha256,
            ],
        )
    return {**identity, "run_sha256": run_sha256}


def run(
    database: Path = DEFAULT_DB,
    *,
    repo_root: Path = REPO_ROOT,
    registration_path: Path = agent_policy.REGISTRATION_PATH,
    lock_path: Path = LOCK_PATH,
    runner: CaseRunner = _default_runner,
    systemd_runner: CaseRunner = _systemd_restart_runner,
    now: Callable[[], datetime] | None = None,
) -> dict:
    """Run the frozen isolated suite and append one bounded attestation."""
    with advisory_file_lock(lock_path):
        clock = now or (lambda: datetime.now(timezone.utc))
        started_at = clock()
        suite = _suite_identity(repo_root, registration_path)
        results = [
            _case_result(
                case,
                (
                    runner(case["target"])
                    if case["runner"] == "pytest"
                    else systemd_runner(case["target"])
                ),
            )
            for case in DRILL_CASES
        ]
        completed_at = clock()
        if _timestamp(completed_at) < _timestamp(started_at):
            raise FaultDrillError("fault drill completion precedes its start")
        if _suite_identity(repo_root, registration_path) != suite:
            raise FaultDrillError("fault drill source changed while the suite ran")
        con = engine_db.connect(database)
        try:
            return _persist(
                con,
                suite,
                results,
                started_at=started_at,
                completed_at=completed_at,
            )
        finally:
            con.close()


def _verified_row(
    row: tuple,
    *,
    current_cases: tuple[dict, ...] | None = None,
) -> dict:
    try:
        payload = json.loads(row[15])
    except (TypeError, ValueError) as exc:
        raise FaultDrillError("stored fault drill result is invalid") from exc
    identity = {
        "schema_version": row[1],
        "suite_id": row[2],
        "suite_sha256": row[3],
        "coverage_level": row[4],
        "source_sha256": row[5],
        "source_file_count": row[6],
        "registry_sha256": row[7],
        "started_at": _timestamp(row[8]),
        "completed_at": _timestamp(row[9]),
        "status": row[10],
        "case_count": row[11],
        "passed_count": row[12],
        "failed_count": row[13],
        "indeterminate_count": row[14],
        "results_sha256": row[16],
        "execution_authority": "none",
    }
    results = payload.get("results") if isinstance(payload, dict) else None
    expected_cases = (
        None
        if current_cases is None
        else {
            case["id"]: {
                "mode": case["mode"],
                "property": case["property"],
            }
            for case in current_cases
        }
    )
    actual_counts = {"pass": 0, "fail": 0, "indeterminate": 0}
    valid_results = (
        isinstance(results, list)
        and len(results) == row[11]
        and row[11] > 0
        and (expected_cases is None or len(results) == len(expected_cases))
    )
    seen = set()
    if valid_results:
        for result in results:
            if not isinstance(result, dict) or set(result) != {
                "id",
                "mode",
                "property",
                "status",
                "returncode",
                "output_size_bytes",
                "output_sha256",
            }:
                valid_results = False
                break
            result_id = result["id"]
            result_mode = result["mode"]
            result_property = result["property"]
            expected = (
                None if expected_cases is None else expected_cases.get(result_id)
            )
            status = result["status"]
            if (
                not isinstance(result_id, str)
                or not result_id
                or not isinstance(result_mode, str)
                or not result_mode
                or not isinstance(result_property, str)
                or not result_property
                or result_id in seen
                or status not in actual_counts
                or (
                    expected_cases is not None
                    and (
                        expected is None
                        or result_mode != expected["mode"]
                        or result_property != expected["property"]
                    )
                )
            ):
                valid_results = False
                break
            seen.add(result_id)
            actual_counts[status] += 1
            if status == "indeterminate":
                valid_metadata = (
                    result["returncode"] is None
                    and result["output_size_bytes"] is None
                    and result["output_sha256"] is None
                )
            else:
                valid_metadata = (
                    isinstance(result["returncode"], int)
                    and not isinstance(result["returncode"], bool)
                    and (result["returncode"] == 0) is (status == "pass")
                    and isinstance(result["output_size_bytes"], int)
                    and not isinstance(result["output_size_bytes"], bool)
                    and 0 <= result["output_size_bytes"] <= MAX_OUTPUT_BYTES
                    and isinstance(result["output_sha256"], str)
                    and len(result["output_sha256"]) == 64
                    and all(
                        character in "0123456789abcdef"
                        for character in result["output_sha256"]
                    )
                )
            if not valid_metadata:
                valid_results = False
                break
    if (
        row[1] != SCHEMA_VERSION
        or row[2] != SUITE_ID
        or row[4] != COVERAGE_LEVEL
        or not isinstance(payload, dict)
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("suite_sha256") != row[3]
        or not valid_results
        or (
            expected_cases is not None
            and seen != set(expected_cases)
        )
        or len(results) != row[11]
        or (
            expected_cases is not None
            and row[11] != len(expected_cases)
        )
        or row[12] + row[13] + row[14] != row[11]
        or actual_counts
        != {"pass": row[12], "fail": row[13], "indeterminate": row[14]}
        or row[10] not in {"pass", "fail", "indeterminate"}
        or row[10]
        != (
            "pass"
            if actual_counts
            == {"pass": row[11], "fail": 0, "indeterminate": 0}
            else "fail"
            if actual_counts["fail"]
            else "indeterminate"
        )
        or row[9] < row[8]
        or canonical_sha256(payload) != row[16]
        or canonical_sha256(identity) != row[17]
    ):
        raise FaultDrillError("stored fault drill result is invalid")
    return {**identity, "run_sha256": row[17]}


def status(
    con: duckdb.DuckDBPyConnection,
    *,
    repo_root: Path = REPO_ROOT,
    registration_path: Path = agent_policy.REGISTRATION_PATH,
) -> dict:
    """Return the latest verified drill and whether it matches current sources."""
    suite = _suite_identity(repo_root, registration_path)
    exists = con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_name = 'agent_fault_drill_runs'"
    ).fetchone()
    if exists is None:
        return {
            **suite,
            "status": "not_run",
            "current": False,
            "run_count": 0,
            "latest_run": None,
            "missing_coverage": [],
            "execution_authority": "none",
        }
    rows = con.execute(
        "SELECT * FROM agent_fault_drill_runs ORDER BY id"
    ).fetchall()
    verified = [
        _verified_row(
            row,
            current_cases=DRILL_CASES
            if row[3] == suite["suite_sha256"]
            else None,
        )
        for row in rows
    ]
    latest = None if not verified else verified[-1]
    current = bool(
        latest is not None
        and latest["status"] == "pass"
        and latest["suite_sha256"] == suite["suite_sha256"]
        and latest["registry_sha256"] == suite["registry_sha256"]
    )
    return {
        **suite,
        "status": (
            "current_pass"
            if current
            else "initialized_empty"
            if latest is None
            else "stale"
            if latest["status"] == "pass"
            else latest["status"]
        ),
        "current": current,
        "run_count": len(verified),
        "latest_run": latest,
        "missing_coverage": [],
        "execution_authority": "none",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "status"))
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args(argv)
    if args.command == "run":
        result = run(args.db)
    else:
        con = engine_db.connect(args.db, read_only=True)
        try:
            result = status(con)
        finally:
            con.close()
    print(json.dumps(result, sort_keys=True))
    return int(result["status"] not in {"pass", "current_pass"})


if __name__ == "__main__":
    raise SystemExit(main())
