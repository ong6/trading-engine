from __future__ import annotations

from pathlib import Path

import pytest

from engine import job_contract
from server import scheduler_monitor

ROOT = Path(__file__).resolve().parents[1]


def _job_block(job_id: str = "test-job") -> str:
    return f"""
[[jobs]]
job_id = "{job_id}"
owner = "test"
repository = "fixture"
version = 1
argv = ["python", "-m", "fixture"]
parameters = {{}}
authority = "data"
enabled = true
runner_enabled = true
runner_mode = "synthetic"
schedules = []
calendar = "always"
locks = [{{ name = "job:{job_id}", mode = "exclusive", wait_seconds = 0, timeout_status = "superseded" }}]
idempotency = {{ template = "{{job_id}}:{{version}}:{{scheduled_for}}", completion_probe = {{ kind = "command", argv = ["python", "-m", "fixture_probe"], timeout_seconds = 1 }} }}
run_record = {{ retention_days = 180 }}
timeout = {{ attempt_seconds = 10, term_grace_seconds = 1, overall_seconds = 10 }}
retry = {{ max_attempts = 1, exit_codes = [], backoff_seconds = [], deadline_seconds = 10 }}
alert = {{ severity = "FAIL", grace_seconds = 0 }}
catch_up = {{ mode = "none", max_age_seconds = 0, max_count = 0 }}
approval = {{ kind = "synthetic_fixture" }}
resources = {{ nice = 0, io_scheduling_class = "best-effort", cpu_quota_percent = 50, memory_high_bytes = 1048576, memory_max_bytes = 2097152, minimum_available_memory_bytes = 0, tasks_max = 8, scratch_bytes = 0, output_bytes = 0, min_free_bytes = 0, unlimited_reason = "synthetic fixture" }}
"""


def _manifest(*blocks: str) -> str:
    return "schema_version = 1\nmaximum_receipt_retention_days = 180\n" + "".join(blocks)


def _load(tmp_path: Path, text: str):
    path = tmp_path / "jobs.toml"
    path.write_text(text)
    return job_contract.load_registry(tmp_path, paths=[path])


def test_public_registry_has_every_current_schedule_and_disabled_p16():
    registry = job_contract.load_registry(ROOT)

    assert len(registry.jobs) == 20
    assert sum(bool(job.schedules) for job in registry.jobs) == 19
    assert sum(job.timer_unit is not None for job in registry.jobs) == 13
    assert sum(isinstance(job.legacy.get("cron"), dict) for job in registry.jobs) == 6
    assert registry.get("trading-engine-p16-challengers").enabled is False
    assert all(not job.runner_enabled for job in registry.jobs if job.schedules)
    assert registry.get("registry-audit").runner_enabled is True
    assert registry.get("registry-audit").runner_mode == "read_only"
    assert not registry.get("registry-audit").schedules
    assert all(len(job.spec_sha256) == 64 for job in registry.jobs)


def test_rendered_units_and_crontab_are_exact_legacy_goldens():
    registry = job_contract.load_registry(ROOT)
    rendered = job_contract.render_units(registry)
    sources = {
        path.name: path.read_text()
        for path in (ROOT / "server").glob("*.service")
        if path.name in rendered
    } | {
        path.name: path.read_text()
        for path in (ROOT / "server").glob("*.timer")
        if path.name in rendered
    }

    assert rendered == sources
    assert job_contract.render_cron_entries(registry, ROOT) == {
        **scheduler_monitor.expected_cron_entries(ROOT),
        **scheduler_monitor.expected_auxiliary_cron_entries(ROOT),
    }


def test_every_on_calendar_round_trips_in_source_order():
    registry = job_contract.load_registry(ROOT)
    for job in registry.jobs:
        if not job.timer_unit:
            continue
        source = ROOT / "server" / job.timer_unit
        calendars = tuple(
            line.split("=", 1)[1]
            for line in source.read_text().splitlines()
            if line.startswith("OnCalendar=")
        )
        assert calendars == job.schedules


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('argv = ["python", "-m", "fixture"]', 'argv = ["sh", "-c", "echo bad"]',
         "command shell"),
        ('idempotency = { template = "{job_id}:{version}:{scheduled_for}", completion_probe = { kind = "command", argv = ["python", "-m", "fixture_probe"], timeout_seconds = 1 } }', "", "idempotency"),
        ("timeout = { attempt_seconds = 10, term_grace_seconds = 1, overall_seconds = 10 }",
         "", "timeout"),
        ("retention_days = 180", "retention_days = 181", "retention"),
        ('locks = [{ name = "job:test-job", mode = "exclusive", wait_seconds = 0, '
         'timeout_status = "superseded" }]',
         'locks = [{ name = "job:test-job", mode = "exclusive", wait_seconds = 0, '
         'timeout_status = "superseded" }, { name = "alpha", mode = "shared", '
         'wait_seconds = 0, timeout_status = "terminal_failure" }]', "ordered"),
    ],
)
def test_registry_rejects_unsafe_or_unbounded_contracts(tmp_path, old, new, message):
    text = _manifest(_job_block()).replace(old, new)
    with pytest.raises(job_contract.JobContractError, match=message):
        _load(tmp_path, text)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("memory_high_bytes = 1048576", "memory_high_bytes = 1048576.5", "nonnegative integer"),
        ("tasks_max = 8", "tasks_max = 8.5", "nonnegative integer"),
        ("cpu_quota_percent = 50", "cpu_quota_percent = nan", "nonnegative"),
        ("cpu_quota_percent = 50", "cpu_quota_percent = inf", "nonnegative"),
        ("memory_high_bytes = 1048576", "memory_high_bytes = 3000000", "exceeds"),
        ("nice = 0", "nice = 20", "nice"),
        ('io_scheduling_class = "best-effort"', 'io_scheduling_class = "invalid"',
         "io_scheduling_class"),
    ],
)
def test_registry_rejects_lossy_or_invalid_resource_limits(tmp_path, old, new, message):
    with pytest.raises(job_contract.JobContractError, match=message):
        _load(tmp_path, _manifest(_job_block()).replace(old, new))


def test_registry_accepts_supported_fractional_cpu_quota(tmp_path):
    registry = _load(
        tmp_path,
        _manifest(_job_block()).replace("cpu_quota_percent = 50", "cpu_quota_percent = 0.5"),
    )
    assert registry.get("test-job").resources["cpu_quota_percent"] == 0.5


@pytest.mark.parametrize("authority", ["paper", "shadow"])
def test_schema_v1_refuses_self_declared_paper_or_shadow_one_off(tmp_path, authority):
    manifest = _manifest(_job_block()).replace('authority = "data"', f'authority = "{authority}"')
    with pytest.raises(job_contract.JobContractError, match="synthetic runner"):
        _load(tmp_path, manifest)


def test_alert_grace_cannot_outlive_immutable_receipt_retention(tmp_path):
    manifest = _manifest(_job_block()).replace("grace_seconds = 0", "grace_seconds = 15552001")
    with pytest.raises(job_contract.JobContractError, match="grace exceeds"):
        _load(tmp_path, manifest)


def test_registry_rejects_duplicate_ids_across_manifests(tmp_path):
    first = tmp_path / "first.toml"
    second = tmp_path / "second.toml"
    first.write_text(_manifest(_job_block()))
    second.write_text(_manifest(_job_block()))

    with pytest.raises(job_contract.JobContractError, match="duplicate job id"):
        job_contract.load_registry(tmp_path, paths=[first, second])


def test_registry_refuses_runner_admission_for_scheduled_or_catch_up_work(tmp_path):
    scheduled = _job_block().replace(
        "schedules = []", 'schedules = ["Mon *-*-* 00:00:00 UTC"]'
    )
    with pytest.raises(job_contract.JobContractError, match="later migration"):
        _load(tmp_path, _manifest(scheduled))

    catch_up = _job_block().replace(
        'catch_up = { mode = "none", max_age_seconds = 0, max_count = 0 }',
        'catch_up = { mode = "latest", max_age_seconds = 60, max_count = 1 }',
    )
    with pytest.raises(job_contract.JobContractError, match="later migration"):
        _load(tmp_path, _manifest(catch_up))


def test_host_manifest_discovery_keeps_public_manifest_first(tmp_path):
    private = tmp_path / "private.toml"
    private.write_text(_manifest(_job_block("private-job")))

    assert job_contract.manifest_paths(ROOT, {job_contract.MANIFEST_ENV: str(private)}) == (
        ROOT / "ops/jobs.toml",
        private,
    )


def test_audit_cli_is_a_read_only_registered_one_off(capsys):
    assert job_contract.main(["audit", "--repo-root", str(ROOT)]) == 0
    assert '"status": "ok"' in capsys.readouterr().out
