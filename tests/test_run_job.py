from __future__ import annotations

import fcntl
import json
import os
import sqlite3
import sys
import time
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from engine import job_contract
from tools import run_job

ROOT = Path(__file__).resolve().parents[1]
SLOT = datetime(2026, 10, 18, 12, tzinfo=UTC)


def _spec(
    tmp_path: Path,
    code: str,
    *,
    job_id: str = "synthetic-job",
    parameters: str = "{}",
    locks: str | None = None,
    attempt_seconds: float = 5,
    term_grace_seconds: float = 1,
    max_attempts: int = 1,
    retry_codes: tuple[int, ...] = (),
    backoffs: tuple[float, ...] = (),
    catch_up: tuple[str, int, int] = ("none", 0, 0),
    memory_required: int = 0,
    min_free_bytes: int = 0,
    completion_probe_code: str | None = "raise SystemExit(1)\n",
    runner_enabled: bool = True,
    retention_days: int = 180,
) -> tuple[job_contract.JobSpec, Path]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    script = repo / "synthetic_job.py"
    script.write_text(code)
    completion_probe = '{ kind = "receipt" }'
    if completion_probe_code is not None:
        (repo / "completion_probe.py").write_text(completion_probe_code)
        completion_probe = (
            f'{{ kind = "command", argv = ["{sys.executable}", '
            '"{repo}/completion_probe.py"], timeout_seconds = 1 }'
        )
    manifest = repo / "ops" / "jobs.toml"
    manifest.parent.mkdir()
    lock_text = locks or (
        f'[{{ name = "job:{job_id}", mode = "exclusive", wait_seconds = 0, '
        'timeout_status = "superseded" }]'
    )
    manifest.write_text(
        f"""schema_version = 1
maximum_receipt_retention_days = 180
[[jobs]]
job_id = "{job_id}"
owner = "test"
repository = "fixture"
version = 1
argv = ["{sys.executable}", "{{repo}}/synthetic_job.py"]
parameters = {parameters}
authority = "data"
enabled = true
runner_enabled = {str(runner_enabled).lower()}
runner_mode = "{'synthetic' if runner_enabled else 'blocked'}"
schedules = []
calendar = "always"
locks = {lock_text}
idempotency = {{ template = "{{job_id}}:{{version}}:{{scheduled_for}}", completion_probe = {completion_probe} }}
run_record = {{ retention_days = {retention_days} }}
timeout = {{ attempt_seconds = {attempt_seconds}, term_grace_seconds = {term_grace_seconds}, overall_seconds = 20 }}
retry = {{ max_attempts = {max_attempts}, exit_codes = {list(retry_codes)}, backoff_seconds = {list(backoffs)}, deadline_seconds = 20 }}
alert = {{ severity = "FAIL", grace_seconds = 0 }}
catch_up = {{ mode = "{catch_up[0]}", max_age_seconds = {catch_up[1]}, max_count = {catch_up[2]} }}
[jobs.resources]
nice = 0
io_scheduling_class = "best-effort"
cpu_quota_percent = 50
memory_high_bytes = 1048576
memory_max_bytes = 2097152
minimum_available_memory_bytes = {memory_required}
tasks_max = 8
scratch_bytes = 0
output_bytes = 0
min_free_bytes = {min_free_bytes}
unlimited_reason = "synthetic fixture"
"""
    )
    registry = job_contract.load_registry(repo, paths=[manifest])
    return registry.get(job_id), repo


def _execute(spec, repo, tmp_path, **kwargs):
    return run_job.execute_job(
        spec,
        scheduled_for=SLOT,
        repo_root=repo,
        logs_dir=tmp_path / "logs",
        projector=kwargs.pop("projector", lambda receipt, ops: None),
        executor_verified=True,
        **kwargs,
    )


def _destination(logs_dir, spec, parameters=None, explicit_key=None):
    clean = run_job.validate_parameters(spec, parameters or {})
    parameter_hash = run_job._hash_json(clean)
    operator_key, canonical_key, scope = run_job._invocation_keys(
        spec, SLOT, parameter_hash, explicit_key
    )
    return (
        run_job._receipt_directory(logs_dir, spec, SLOT, canonical_key),
        operator_key,
        canonical_key,
        scope,
    )


def _exited_process_identity():
    process = run_job.subprocess.Popen([sys.executable, "-c", "pass"])
    identity = run_job._process_identity(process.pid)
    process.wait()
    assert identity is not None
    return process.pid, identity


def _wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for synthetic process state")


def test_success_receipt_environment_and_completed_key_noop(tmp_path):
    state = tmp_path / "state.json"
    parameters = ('{ state = { type = "string", option = "--state", required = true } }')
    spec, repo = _spec(
        tmp_path,
        """import argparse, json, os
p=argparse.ArgumentParser(); p.add_argument('--state'); a=p.parse_args()
path=__import__('pathlib').Path(a.state)
count=int(path.read_text())+1 if path.exists() else 1
path.write_text(str(count))
path.with_suffix('.env').write_text(json.dumps({k: os.environ[k] for k in (
 'ENGINE_JOB_RUN_ID','ENGINE_JOB_SCHEDULED_FOR','ENGINE_JOB_IDEMPOTENCY_KEY',
 'ENGINE_JOB_RECEIPT_PATH','ENGINE_JOB_PARAMETERS_SHA256','PYTHONPATH')}))
""",
        parameters=parameters,
    )

    first = _execute(spec, repo, tmp_path, parameters={"state": str(state)})
    second = _execute(spec, repo, tmp_path, parameters={"state": str(state)})

    assert first.exit_code == 0 and first.final["work_status"] == "success"
    assert second.exit_code == 0 and second.final["work_status"] == "noop"
    assert second.final["reason"] == "completed-idempotency-key"
    assert state.read_text() == "1"
    environment = json.loads(state.with_suffix(".env").read_text())
    assert environment["ENGINE_JOB_SCHEDULED_FOR"] == "2026-10-18T12:00:00Z"
    assert environment["PYTHONPATH"] == str(repo)
    assert Path(environment["ENGINE_JOB_RECEIPT_PATH"]) == first.receipts[-1]
    assert len(first.final["parameter_sha256"]) == 64
    assert str(state) not in json.dumps(first.final)


def test_committed_production_jobs_are_audit_only_runner_refusals(tmp_path):
    registry = job_contract.load_registry(ROOT)
    launched = False

    def forbidden_popen(*args, **kwargs):
        nonlocal launched
        launched = True
        raise AssertionError("audit-only job launched")

    for job_id in ("run-daily", "trading-engine-p15-scoring",
                   "trading-engine-accounts-settle"):
        with pytest.raises(run_job.JobRunError, match="audit-only"):
            run_job.execute_job(
                registry.get(job_id), scheduled_for=SLOT, repo_root=ROOT,
                logs_dir=tmp_path / "logs", popen=forbidden_popen, executor_verified=True,
            )
    assert launched is False


def test_live_idempotency_key_refuses_a_concurrent_child(tmp_path):
    spec, repo = _spec(tmp_path, "pass\n")
    key = "same-key"
    lock = run_job._lock_path(
        tmp_path / "logs", "idempotency", f"{spec.job_id}:{key}"
    )
    lock.parent.mkdir(parents=True)
    with lock.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(run_job.JobRunError, match="live run"):
            _execute(spec, repo, tmp_path, idempotency_key=key)


def test_explicit_key_is_bound_to_parameter_and_spec_scope(tmp_path):
    parameters = '{ state = { type = "string", option = "--state", required = true } }'
    first_state = tmp_path / "scope-a"
    second_state = tmp_path / "scope-b"
    spec, repo = _spec(
        tmp_path,
        """import argparse
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--state'); a=p.parse_args()
Path(a.state).write_text('ran')
""",
        parameters=parameters,
    )
    first = _execute(
        spec, repo, tmp_path, parameters={"state": str(first_state)},
        idempotency_key="operator-key",
    )
    second = _execute(
        spec, repo, tmp_path, parameters={"state": str(second_state)},
        idempotency_key="operator-key",
    )

    assert first.final["work_status"] == "success"
    assert second.exit_code == 1
    assert second.final["work_status"] == "terminal_failure"
    assert second.final["reason"] == "idempotency-scope-mismatch"
    assert first.final["idempotency_key"] != second.final["idempotency_key"]
    assert first_state.read_text() == "ran" and not second_state.exists()


def test_distinct_keys_in_one_slot_reserve_distinct_terminal_paths(tmp_path):
    effects = tmp_path / "effects"
    spec, repo = _spec(
        tmp_path,
        """import os
from pathlib import Path
path=Path(""" + repr(str(effects)) + ")\n"
        "with path.open('a') as handle: handle.write(os.environ['ENGINE_JOB_IDEMPOTENCY_KEY']+'\\n')\n",
    )

    first = _execute(spec, repo, tmp_path, idempotency_key="key-a")
    second = _execute(spec, repo, tmp_path, idempotency_key="key-b")

    assert first.final["work_status"] == second.final["work_status"] == "success"
    assert first.receipts[-1] != second.receipts[-1]
    assert first.receipts[-1].name == second.receipts[-1].name == "1.json"
    assert len(effects.read_text().splitlines()) == 2


def test_stale_running_attempt_is_interrupted_then_resumed(tmp_path):
    state = tmp_path / "side-effect"
    parameters = ('{ state = { type = "string", option = "--state", required = true } }')
    spec, repo = _spec(
        tmp_path,
        """import argparse
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--state'); a=p.parse_args()
path=Path(a.state); path.write_text(str(int(path.read_text())+1 if path.exists() else 1))
""",
        parameters=parameters,
    )
    destination, operator_key, canonical_key, scope = _destination(
        tmp_path / "logs", spec, {"state": str(state)}, "resume-key"
    )
    child_pid, child_identity = _exited_process_identity()
    stale = {
        "schema_version": 1,
        "run_id": "old",
        "job_id": spec.job_id,
        "spec_version": 1,
        "spec_sha256": spec.spec_sha256,
        "idempotency_key": canonical_key,
        "operator_idempotency_key": operator_key,
        "idempotency_scope_sha256": scope,
        "scheduled_for": "2026-10-18T12:00:00Z",
        "started_at": "2026-10-18T11:59:00Z",
        "attempt": 1,
        "argv": list(spec.argv),
        "parameter_sha256": "0" * 64,
        "source_sha": "unknown",
        "child_pid": child_pid,
        "child_process_identity": child_identity,
        "state": "running",
    }
    run_job._atomic_json(destination / "1.running.json", stale)

    result = _execute(
        spec, repo, tmp_path, idempotency_key="resume-key", parameters={"state": str(state)}
    )

    assert [json.loads(path.read_text())["work_status"] for path in result.receipts] == [
        "interrupted", "success"
    ]
    assert result.final["attempt"] == 2 and state.read_text() == "1"
    assert not list(destination.glob("*.running.json"))


def test_task_completion_probe_prevents_duplicate_stale_side_effect(tmp_path):
    state = tmp_path / "completed"
    launched = tmp_path / "launched"
    state.write_text("done")
    spec, repo = _spec(
        tmp_path,
        f"from pathlib import Path\nPath({str(launched)!r}).touch()\n",
        completion_probe_code=(
            "from pathlib import Path\n"
            f"raise SystemExit(0 if Path({str(state)!r}).exists() else 1)\n"
        ),
    )
    destination, operator_key, canonical_key, scope = _destination(
        tmp_path / "logs", spec, explicit_key="probe-key"
    )
    child_pid, child_identity = _exited_process_identity()
    stale = {
        "schema_version": 1, "run_id": "old", "job_id": spec.job_id,
        "spec_version": 1, "spec_sha256": spec.spec_sha256,
        "idempotency_key": canonical_key, "operator_idempotency_key": operator_key,
        "idempotency_scope_sha256": scope, "scheduled_for": "2026-10-18T12:00:00Z",
        "started_at": "2026-10-18T11:59:00Z", "attempt": 1,
        "argv": list(spec.argv), "parameter_sha256": "0" * 64, "source_sha": "unknown",
        "state": "running",
        "child_pid": child_pid, "child_process_identity": child_identity,
    }
    run_job._atomic_json(destination / "1.running.json", stale)

    result = _execute(spec, repo, tmp_path, idempotency_key="probe-key")

    assert [json.loads(path.read_text())["work_status"] for path in result.receipts] == [
        "interrupted", "noop"
    ]
    assert result.final["reason"] == "task-completion-probe"
    assert not launched.exists()


def test_wrapper_sigkill_cannot_duplicate_a_surviving_child(tmp_path):
    started = tmp_path / "started"
    completed = tmp_path / "completed"
    effects = tmp_path / "effects"
    spec, repo = _spec(
        tmp_path,
        """import time
from pathlib import Path
Path(""" + repr(str(started)) + ").touch()\n"
        "time.sleep(1)\n"
        "with Path(" + repr(str(effects)) + ").open('a') as handle: handle.write('once\\n')\n"
        "Path(" + repr(str(completed)) + ").touch()\n",
        completion_probe_code=(
            "from pathlib import Path\n"
            f"raise SystemExit(0 if Path({str(completed)!r}).exists() else 1)\n"
        ),
    )
    wrapper_script = tmp_path / "wrapper.py"
    wrapper_script.write_text(
        """import sys
from datetime import datetime
from pathlib import Path
from engine.job_contract import load_registry
from tools.run_job import execute_job
repo=Path(sys.argv[1]); logs=Path(sys.argv[2])
spec=load_registry(repo).get('synthetic-job')
result=execute_job(spec, scheduled_for=datetime.fromisoformat(sys.argv[3]),
                   idempotency_key='crash-key', repo_root=repo, logs_dir=logs,
                   executor_verified=True, projector=lambda receipt, ops: None)
raise SystemExit(result.exit_code)
"""
    )
    wrapper = run_job.subprocess.Popen(
        [
            sys.executable, str(wrapper_script), str(repo), str(tmp_path / "logs"),
            SLOT.isoformat(),
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTHONPATH": str(ROOT),
        },
        stdout=run_job.subprocess.DEVNULL,
        stderr=run_job.subprocess.DEVNULL,
    )
    _wait_for(started.exists)
    wrapper.kill()
    wrapper.wait()

    with pytest.raises(run_job.JobRunError, match="live run"):
        _execute(spec, repo, tmp_path, idempotency_key="crash-key")

    running = next((tmp_path / "logs/job-runs" / spec.job_id).glob("**/*.running.json"))
    running_row = json.loads(running.read_text())
    child_pid = running_row["child_pid"]
    child_identity = running_row["child_process_identity"]
    _wait_for(completed.exists)
    _wait_for(lambda: run_job._process_identity(child_pid) != child_identity)
    resumed = _execute(spec, repo, tmp_path, idempotency_key="crash-key")

    assert [json.loads(path.read_text())["work_status"] for path in resumed.receipts] == [
        "interrupted", "noop"
    ]
    assert resumed.final["reason"] == "task-completion-probe"
    assert effects.read_text().splitlines() == ["once"]


@pytest.mark.parametrize(("fail_until", "statuses"), [(1, ["retryable_failure", "success"]),
                                                        (9, ["retryable_failure"] * 3)])
def test_bounded_retry_then_success_or_exhaustion(tmp_path, fail_until, statuses):
    state = tmp_path / "attempts"
    parameters = (
        '{ state = { type = "string", option = "--state", required = true }, '
        'fail_until = { type = "integer", option = "--fail-until", required = true } }'
    )
    spec, repo = _spec(
        tmp_path,
        """import argparse, sys
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--state'); p.add_argument('--fail-until', type=int)
a=p.parse_args(); path=Path(a.state); n=int(path.read_text())+1 if path.exists() else 1
path.write_text(str(n)); sys.exit(9 if n <= a.fail_until else 0)
""",
        parameters=parameters,
        max_attempts=3,
        retry_codes=(9,),
        backoffs=(0, 0),
    )
    result = _execute(
        spec, repo, tmp_path, parameters={"state": str(state), "fail_until": fail_until}
    )

    assert [json.loads(path.read_text())["work_status"] for path in result.receipts] == statuses
    assert int(state.read_text()) == len(statuses)
    assert result.exit_code == (0 if fail_until == 1 else 1)
    assert result.final["retry_disposition"] == ("none" if fail_until == 1 else "exhausted")


@pytest.mark.parametrize(("ignore_term", "termination"), [(False, "TERM"), (True, "KILL")])
def test_attempt_timeout_escalates_from_term_to_kill(tmp_path, ignore_term, termination):
    setup = "signal.signal(signal.SIGTERM, signal.SIG_IGN)" if ignore_term else ""
    spec, repo = _spec(
        tmp_path,
        f"import signal, time\n{setup}\ntime.sleep(10)\n",
        attempt_seconds=0.05,
        term_grace_seconds=0.05,
    )

    result = _execute(spec, repo, tmp_path)

    assert result.exit_code == 1
    assert result.final["work_status"] == "retryable_failure"
    assert result.final["termination"] == termination
    assert not list((tmp_path / "logs").glob("job-runs/*/*/*.running.json"))


def test_lock_timeout_and_resource_refusal_never_launch_child(tmp_path, monkeypatch):
    marker = tmp_path / "launched"
    locks = (
        '[{ name = "job:synthetic-job", mode = "exclusive", wait_seconds = 0, '
        'timeout_status = "superseded" }, { name = "market-writer", mode = "exclusive", '
        'wait_seconds = 0, timeout_status = "terminal_failure" }]'
    )
    spec, repo = _spec(tmp_path, f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
                       locks=locks)
    held = run_job._lock_path(tmp_path / "logs", "domains", "market-writer")
    held.parent.mkdir(parents=True)
    with held.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        locked = _execute(spec, repo, tmp_path)
    assert locked.final["reason"] == "lock-timeout:market-writer"
    assert locked.final["work_status"] == "terminal_failure" and not marker.exists()

    spec2, repo2 = _spec(tmp_path / "memory", "raise AssertionError('launched')\n",
                         memory_required=1024)
    monkeypatch.setattr(run_job, "_available_memory_bytes", lambda: 0)
    refused = _execute(spec2, repo2, tmp_path / "memory")
    assert refused.final["reason"] == "resource-refusal:memory-reserve"

    spec3, repo3 = _spec(tmp_path / "disk", "raise AssertionError('launched')\n",
                         min_free_bytes=1)
    monkeypatch.setattr(run_job.shutil, "disk_usage", lambda root: SimpleNamespace(free=0))
    refused = _execute(spec3, repo3, tmp_path / "disk")
    assert refused.final["reason"] == "resource-refusal:disk-reserve"


def test_retryable_lock_refusal_uses_bounded_attempt_policy(tmp_path):
    marker = tmp_path / "launched"
    locks = (
        '[{ name = "job:synthetic-job", mode = "exclusive", wait_seconds = 0, '
        'timeout_status = "superseded" }, { name = "market-writer", mode = "exclusive", '
        'wait_seconds = 0, timeout_status = "retryable_failure" }]'
    )
    spec, repo = _spec(
        tmp_path, f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
        locks=locks, max_attempts=3, retry_codes=(9,), backoffs=(0, 0),
    )
    held = run_job._lock_path(tmp_path / "logs", "domains", "market-writer")
    held.parent.mkdir(parents=True)
    with held.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        released = False

        def release_after_first(_delay):
            nonlocal released
            if not released:
                fcntl.flock(handle, fcntl.LOCK_UN)
                released = True

        result = _execute(spec, repo, tmp_path, sleep=release_after_first)

    assert [json.loads(path.read_text())["work_status"] for path in result.receipts] == [
        "retryable_failure", "success"
    ]
    assert json.loads(result.receipts[0].read_text())["retry_disposition"] == "retry"
    assert marker.exists()

    exhausted_root = tmp_path / "exhausted"
    exhausted_spec, exhausted_repo = _spec(
        exhausted_root, "raise AssertionError('must not launch')\n", locks=locks,
        max_attempts=3, retry_codes=(9,), backoffs=(0, 0),
    )
    exhausted_lock = run_job._lock_path(
        exhausted_root / "logs", "domains", "market-writer"
    )
    exhausted_lock.parent.mkdir(parents=True)
    with exhausted_lock.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        exhausted = _execute(
            exhausted_spec, exhausted_repo, exhausted_root, sleep=lambda _delay: None
        )
    assert [json.loads(path.read_text())["work_status"] for path in exhausted.receipts] == [
        "retryable_failure", "retryable_failure", "retryable_failure"
    ]
    assert exhausted.final["retry_disposition"] == "exhausted"


@pytest.mark.parametrize(("code", "status", "runner_exit"),
                         [(0, "success", 0), (75, "degraded", 75), (2, "terminal_failure", 1)])
def test_status_and_process_exit_are_distinct(tmp_path, code, status, runner_exit):
    spec, repo = _spec(tmp_path, f"raise SystemExit({code})\n")
    result = _execute(spec, repo, tmp_path)
    assert (result.final["process_exit"], result.final["work_status"], result.exit_code) == (
        code, status, runner_exit
    )


def test_malformed_and_immutable_receipts_fail_closed(tmp_path):
    spec, repo = _spec(tmp_path, "pass\n")
    destination, _operator, _canonical, _scope = _destination(tmp_path / "logs", spec)
    broken = destination / "1.json"
    broken.parent.mkdir(parents=True)
    broken.write_text("not json")
    with pytest.raises(run_job.JobRunError, match="malformed"):
        _execute(spec, repo, tmp_path)

    target = tmp_path / "receipt.json"
    run_job._atomic_json(target, {"schema_version": 1, "value": 1})
    with pytest.raises(run_job.JobRunError, match="already exists"):
        run_job._atomic_json(target, {"schema_version": 1, "value": 2})
    assert json.loads(target.read_text())["value"] == 1


def test_projection_outage_is_fail_soft_and_receipts_prune_at_180_days(tmp_path, capsys):
    spec, repo = _spec(tmp_path, "pass\n")
    result = _execute(
        spec, repo, tmp_path,
        projector=lambda receipt, ops: (_ for _ in ()).throw(OSError("down")),
    )
    assert result.exit_code == 0
    assert "projection unavailable: OSError" in capsys.readouterr().err
    old = dict(result.final)
    old["ended_at"] = "2026-04-20T11:59:59Z"
    receipt_root = tmp_path / "old" / "job-runs" / spec.job_id
    old_path = receipt_root / "slot" / "key" / "1.json"
    run_job._atomic_json(old_path, old)
    boundary = dict(old)
    boundary["ended_at"] = "2026-04-21T12:00:00Z"
    keep = old_path.with_name("2.json")
    run_job._atomic_json(keep, boundary)
    assert run_job.prune_receipts(receipt_root, 180, SLOT) == 1
    assert not old_path.exists() and keep.exists()


def test_short_retention_job_cannot_prune_another_jobs_evidence(tmp_path):
    spec, repo = _spec(tmp_path, "pass\n", retention_days=7)
    other = tmp_path / "logs/job-runs/long-retention/slot/1.json"
    old = {
        "schema_version": 1,
        "ended_at": (SLOT - timedelta(days=8)).isoformat().replace("+00:00", "Z"),
    }
    run_job._atomic_json(other, old)

    result = _execute(spec, repo, tmp_path, now=lambda: SLOT)

    assert result.exit_code == 0
    assert other.exists()


def test_terminal_receipt_projects_into_existing_ops_database(tmp_path):
    spec, repo = _spec(tmp_path, "pass\n")
    logs = tmp_path / "logs"
    result = run_job.execute_job(
        spec, scheduled_for=SLOT, repo_root=repo, logs_dir=logs, ops_dir=logs / "ops",
        executor_verified=True,
    )

    with closing(sqlite3.connect(logs / "ops/ops.sqlite")) as db:
        projected = db.execute(
            "SELECT run_id, attempt, job_id, work_status, process_exit FROM job_runs"
        ).fetchall()
    assert projected == [
        (result.final["run_id"], 1, "synthetic-job", "success", 0)
    ]


@pytest.mark.parametrize(
    ("policy", "expected"),
    [(('none', 0, 0), []), (('latest', 86400, 1), [3]), (('all_bounded', 86400, 2), [2, 3])],
)
def test_catch_up_is_age_and_count_bounded(tmp_path, policy, expected):
    spec, _repo = _spec(
        tmp_path, "pass\n", catch_up=policy, runner_enabled=policy[0] == "none"
    )
    slots = [SLOT - timedelta(hours=value) for value in (30, 3, 2, 1)]
    plan = run_job.plan_catch_up(spec, slots, SLOT)
    assert list(plan.execute) == [slots[index] for index in expected]
    assert set(plan.execute).isdisjoint(plan.skipped)


def test_backfill_validates_parameters_and_builds_a_bounded_transient_unit(tmp_path):
    parameters = (
        '{ from = { type = "date", option = "--from", required = true }, '
        'through = { type = "date", option = "--through", required = true }, '
        'reason = { type = "string", option = "--reason", required = true } }'
    )
    spec, repo = _spec(tmp_path, "pass\n", parameters=parameters)
    values = run_job.validate_backfill_parameters(
        spec, "2026-10-01", "2026-10-02", "incident-1"
    )
    command = run_job._backfill_command(
        spec, repo_root=repo, logs_dir=tmp_path / "logs", scheduled_for=SLOT,
        idempotency_key="backfill-1", parameters=values,
    )

    assert command[:5] == ["systemd-run", "--user", "--wait", "--collect", "--quiet"]
    assert f"--working-directory={repo}" in command
    assert f"--setenv=PYTHONPATH={repo}" in command
    assert "--property=TimeoutStartSec=20s" in command
    assert "--property=KillMode=control-group" in command
    assert "--property=CPUQuota=50%" in command
    assert "--property=MemoryMax=2097152" in command
    assert json.dumps(values, sort_keys=True, separators=(",", ":")) in command
    with pytest.raises(run_job.JobRunError, match="missing required"):
        run_job.validate_parameters(spec, {"from": "2026-10-01"})
    with pytest.raises(run_job.JobRunError, match="must not be after"):
        run_job.validate_backfill_parameters(spec, "2026-10-03", "2026-10-02", "incident-1")
    with pytest.raises(run_job.JobRunError, match="must not be empty"):
        run_job.validate_backfill_parameters(spec, "2026-10-01", "2026-10-02", " ")


def test_run_uses_transient_resources_and_internal_executor_is_not_public(tmp_path, monkeypatch):
    spec = job_contract.load_registry(ROOT).get("registry-audit")
    command = run_job._transient_command(
        spec, repo_root=ROOT, logs_dir=tmp_path / "logs", scheduled_for=SLOT,
        idempotency_key=None, parameters={},
    )
    assert command[0:2] == ["systemd-run", "--user"]
    assert "--property=KillMode=control-group" in command
    assert "--property=MemoryHigh=0" not in command
    assert f"--setenv={run_job.TRANSIENT_SPEC_ENV}={spec.spec_sha256}" in command
    with pytest.raises(run_job.JobRunError, match="resource boundary"):
        run_job.execute_job(
            spec, scheduled_for=SLOT, repo_root=ROOT, logs_dir=tmp_path / "direct"
        )
    monkeypatch.setenv(run_job.TRANSIENT_SPEC_ENV, spec.spec_sha256)
    monkeypatch.setenv("INVOCATION_ID", "spoofed")
    with pytest.raises(run_job.JobRunError, match="transient cgroup"):
        run_job.verify_transient_executor(spec)

    monkeypatch.delenv(run_job.TRANSIENT_SPEC_ENV, raising=False)
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    assert run_job.main([
        "_execute", "registry-audit", "--repo-root", str(ROOT),
        "--logs-dir", str(tmp_path / "logs"), "--scheduled-for", _iso_for_cli(SLOT),
    ]) == 2


def _iso_for_cli(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def test_completed_synthetic_backfill_is_an_evidenced_noop(tmp_path):
    state = tmp_path / "backfill-count"
    parameters = (
        '{ from = { type = "date", option = "--from", required = true }, '
        'through = { type = "date", option = "--through", required = true }, '
        'reason = { type = "string", option = "--reason", required = true } }'
    )
    spec, repo = _spec(
        tmp_path,
        """import argparse
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--from'); p.add_argument('--through'); p.add_argument('--reason')
p.parse_args()
path=Path(""" + repr(str(state)) + ")\npath.write_text(str(int(path.read_text())+1 if path.exists() else 1))\n",
        parameters=parameters,
    )
    values = run_job.validate_backfill_parameters(
        spec, "2026-10-01", "2026-10-02", "incident-1"
    )

    first = _execute(
        spec, repo, tmp_path, parameters=values, idempotency_key="backfill-scope-1"
    )
    second = _execute(
        spec, repo, tmp_path, parameters=values, idempotency_key="backfill-scope-1"
    )

    assert first.final["work_status"] == "success"
    assert second.final["work_status"] == "noop"
    assert second.final["business_receipts"] == [str(first.receipts[-1])]
    assert state.read_text() == "1"


def test_public_read_only_registry_audit_runs_through_common_runner(tmp_path):
    spec = job_contract.load_registry(ROOT).get("registry-audit")
    result = run_job.execute_job(
        spec,
        scheduled_for=SLOT,
        repo_root=ROOT,
        logs_dir=tmp_path / "logs",
        projector=lambda receipt, ops: None,
        executor_verified=True,
    )
    assert result.exit_code == 0 and result.final["work_status"] == "success"
    assert json.loads(result.receipts[-1].read_text())["job_id"] == "registry-audit"
