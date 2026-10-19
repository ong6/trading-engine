from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest

from tools import release_deploy

OLD_SHA = "1" * 40
NEW_SHA = "2" * 40


class FakeOperations:
    def __init__(self, store: release_deploy.StateStore):
        self.store = store
        self.head = OLD_SHA
        self.branch = "main"
        self.upstream = "origin/main"
        self.calls: list[str] = []
        self.releases: list[bool] = []
        self.migrations: list[str] = []
        self.plan = {"invalid_rows": 2, "moved": 0}
        self.optional_failures: list[str] = []
        self.reconciled_migrations: set[str] = set()
        self.fail_quiesce = False

    def preflight_prepare(self, **kwargs):
        self.calls.append("preflight")
        return {
            "original_sha": OLD_SHA,
            "approved_sha": kwargs["approved_sha"],
            "source_branch": self.branch,
            "source_upstream": self.upstream,
            "lock_sha256": {"uv.lock": "a" * 64, "ui/package-lock.json": "b" * 64},
            "adapter_set": kwargs["adapter_set"],
            "migrations": [
                release_deploy.asdict(item)
                for item in release_deploy.ADAPTERS[kwargs["adapter_set"]]
            ],
            "workspace": {"free_bytes": 100, "required_bytes": 10, "database_bytes": 1},
            "audit_sha256": "c" * 64,
        }

    def prepare_release(self, state, preflight):
        self.calls.append("prepare-release")
        prepared = self.store.directory / "prepared"
        for relative in ("source", "python/bin", "node/node_modules", "node/.next"):
            (prepared / relative).mkdir(parents=True, exist_ok=True)
        python = prepared / "python/bin/python"
        python.write_text("#!/bin/sh\n")
        python.chmod(0o755)
        return {
            "source": str(prepared / "source"),
            "python_environment": str(prepared / "python"),
            "node_environment": str(prepared / "node"),
            "node_modules": str(prepared / "node/node_modules"),
            "ui_build": str(prepared / "node/.next"),
            "lock_sha256": preflight["lock_sha256"],
            "tools": {},
            "unit_policy": {
                name: "optional" if name in release_deploy.OPTIONAL_UNITS else "required"
                for name in release_deploy.install_automation.UNIT_SOURCES
            },
            "semantic": {
                "registration_revision": 15,
                "registration_source_commit": OLD_SHA,
                "registration_sha256": "8" * 64,
                "runtime_versions": {
                    "forward_review": 12,
                    "xs_forward_review": 23,
                    "e1_forward": 8,
                },
            },
            "release_manifest_sha256": "d" * 64,
            "release_tool_sha256": "9" * 64,
            "versions": {"python": "Python test", "node": "v-test"},
            "migrations": preflight["migrations"],
        }

    def validate_state_source(self, state, expected):
        self.calls.append(f"validate:{expected}")
        if self.head != expected:
            raise release_deploy.DeployError("release checkout source changed")
        expected_migrations = [
            release_deploy.asdict(item)
            for item in release_deploy.ADAPTERS.get(state.adapter_set, ())
        ]
        if state.prepared["migrations"] != expected_migrations:
            raise release_deploy.DeployError("unknown or changed migration registry")

    def validate_prepared(self, _state):
        self.calls.append("validate-prepared")

    def validate_recovery_tools(self, _state):
        self.calls.append("validate-recovery-tools")

    def validate_reconciled_source(self, state, reconciled_sha):
        if self.head != reconciled_sha:
            raise release_deploy.DeployError("current source does not match the reconciled SHA")
        if self.branch != state.source_branch:
            raise release_deploy.DeployError("reconciled source is not on the saved release branch")
        if self.upstream != state.source_upstream:
            raise release_deploy.DeployError("reconciled source does not track the saved upstream")

    def capture_inventory(self, _state):
        self.calls.append("capture-inventory")
        return {
            "units": {
                "trading-engine-api.service": {
                    "LoadState": "loaded",
                    "ActiveState": "active",
                    "UnitFileState": "enabled",
                },
                "te-autopush.timer": {
                    "LoadState": "loaded",
                    "ActiveState": "active",
                    "UnitFileState": "enabled",
                },
            },
            "unit_files": {},
            "crontab": {"present": True, "content": "fixture cron\n"},
            "predeploy_meta": {},
            "artifacts": str(self.store.directory / "inventory/artifacts"),
        }

    def quiesce(self, _state):
        self.calls.append("quiesce")
        if self.fail_quiesce:
            raise release_deploy.DeployError("failed after cron removal")
        return {"held": True}

    @contextmanager
    def producer_locks(self, _state):
        self.calls.append("locks")
        yield frozenset({"fixture.lock"})

    def predeploy_adapter_check(self, state):
        self.calls.append("predeploy-adapter-check")
        return {"adapter_set": state.adapter_set}

    def create_backup(self, _state):
        self.calls.append("create-backup")
        return {"manifest_sha256": "e" * 64}

    def capture_artifacts(self, _state):
        self.calls.append("capture-artifacts")
        return {"schema_version": 1, "entries": {}, "sha256": "0" * 64}

    def reconcile_artifacts(self, _state):
        return None

    def switch_source(self, state):
        self.calls.append("source-switch")
        self.head = state.approved_sha
        return {"git_sha": self.head}

    def reconcile_source_switch(self, state):
        return (
            {"git_sha": state.approved_sha, "reconciled": True}
            if self.head == state.approved_sha
            else None
        )

    def switch_runtimes(self, _state):
        self.calls.append("runtime-switch")
        return {
            ".venv": {"kind": "symlink", "target": "/prior/python"},
            "ui/node_modules": {"kind": "absent"},
            "ui/.next": {"kind": "absent"},
        }

    def reconcile_runtime_switch(self, _state):
        return None

    def plan_migration(self, _state, migration):
        self.calls.append(f"plan:{migration.migration_id}")
        return self.plan

    def apply_migration(self, _state, migration, _plan):
        self.calls.append(f"migration:{migration.migration_id}")
        self.migrations.append(migration.migration_id)
        return {"migration": migration.migration_id}

    def migration_intent(self, _state, migration, _plan):
        return {"migration": migration.migration_id, "before": "old"}

    def reconcile_migration(self, _state, migration, _plan, _intent):
        if migration.migration_id in self.reconciled_migrations:
            return {"migration": migration.migration_id, "reconciled": True}
        return None

    def install_automation(self, _state):
        self.calls.append("install-automation")
        return {
            "status": "optional-failures" if self.optional_failures else "ok",
            "installed_unit_files": [],
            "enablement_units": [],
            "optional_failures": self.optional_failures,
        }

    def reconcile_automation(self, _state):
        return None

    def publish_snapshot(self, _state, _held_locks, *, purpose):
        self.calls.append("publish-snapshot")
        return {"sha256": "f" * 64, "purpose": purpose}

    def reconcile_snapshot(self, _state, *, purpose):
        return None

    def semantic_verify(self, _state, *, rolled_back):
        self.calls.append("rollback-semantic-verify" if rolled_back else "semantic-verify")
        return {"status": "ok", "rolled_back": rolled_back}

    def release_producers(self, _state, *, include_autopush):
        self.calls.append(f"release:{include_autopush}")
        self.releases.append(include_autopush)
        return {"autopush": include_autopush}

    def capture_incident(self, _state):
        self.calls.append("capture-incident")
        return {"path": str(self.store.directory / "incident")}

    def reconcile_incident(self, _state):
        return None

    def restore_source(self, state):
        self.calls.append("restore-source")
        self.head = state.original_sha
        self.branch = None
        return {"git_sha": self.head}

    def restore_artifacts(self, _state):
        self.calls.append("restore-artifacts")
        return {"restored": True}

    def restore_runtimes(self, _state):
        self.calls.append("restore-runtimes")
        return {"restored": True}

    def restore_database(self, _state):
        self.calls.append("restore-database")
        return {"restored": True}

    def verify_artifacts(self, _state):
        self.calls.append("verify-artifacts")
        return {"verified": True}

    def restore_units(self, _state):
        self.calls.append("restore-units")
        return {"restored": True}

    def _head(self, _root):
        return self.head

    def _branch(self, _root):
        return self.branch

    def _upstream(self, _root):
        return self.upstream

    def _source_status(self, _root):
        return []


@pytest.fixture
def transaction(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    database = repo / "store/market.duckdb"
    database.parent.mkdir()
    database.write_bytes(b"fixture")
    store = release_deploy.StateStore(tmp_path / "state")
    operations = FakeOperations(store)
    deployment = release_deploy.ReleaseDeployment(store, operations)
    return deployment, operations, repo, database


def prepare(transaction, *, adapter_set="none"):
    deployment, _operations, repo, database = transaction
    return deployment.prepare(
        repo_root=repo,
        database=database,
        approved_sha=NEW_SHA,
        adapter_set=adapter_set,
        d0="2026-10-19" if adapter_set == "revision-15" else None,
        execute=True,
    )


def running_receipt(store, step, inputs):
    transaction_id = store.load().transaction_id
    release_deploy._atomic_json(
        store.directory / "receipts" / f"{step}.json",
        {
            "schema_version": release_deploy.RECEIPT_SCHEMA_VERSION,
            "step": step,
            "transaction_id": transaction_id,
            "input_sha256": release_deploy._digest(
                {"transaction_id": transaction_id, "inputs": inputs}
            ),
            "status": "running",
            "started_at": "2026-10-19T00:00:00+00:00",
            "completed_at": None,
            "result": {},
            "error": None,
        },
    )


def test_prepare_is_dry_by_default_and_execute_creates_private_typed_state(transaction):
    deployment, operations, repo, database = transaction
    planned = deployment.prepare(
        repo_root=repo,
        database=database,
        approved_sha=NEW_SHA,
        adapter_set="none",
        d0=None,
        execute=False,
    )
    assert planned["status"] == "planned"
    assert not deployment.store.directory.exists()
    assert operations.calls == ["preflight"]

    result = prepare(transaction)
    assert result["status"] == "prepared"
    mode = stat.S_IMODE(deployment.store.directory.stat().st_mode)
    assert mode == 0o700
    state = deployment.store.load()
    assert state.phase == "prepared"
    assert state.approved_sha == NEW_SHA
    assert release_deploy.ReceiptJournal(deployment.store).completed("prepare-release")


def test_prepare_refuses_to_overwrite_existing_state(transaction):
    prepare(transaction)
    deployment, _operations, repo, database = transaction
    with pytest.raises(release_deploy.DeployError, match="already exists"):
        deployment.prepare(
            repo_root=repo,
            database=database,
            approved_sha=NEW_SHA,
            adapter_set="none",
            d0=None,
            execute=True,
        )


def test_activation_only_abort_restores_inventory_when_quiesce_fails_before_backup(transaction):
    prepare(transaction)
    deployment, operations, _repo, _database = transaction
    operations.fail_quiesce = True
    with pytest.raises(release_deploy.DeployError, match="after cron removal"):
        deployment.apply(execute=True, approve_plan=None)
    assert release_deploy.ReceiptJournal(deployment.store).read("create-backup") is None

    operations.fail_quiesce = False
    fresh_shell = release_deploy.ReleaseDeployment(deployment.store, operations)
    result = fresh_shell.abort(execute=True)
    assert result["status"] == "aborted"
    assert operations.releases == [True]


def test_apply_and_verify_are_idempotent_after_receipted_fault(transaction):
    prepare(transaction)
    deployment, operations, _repo, _database = transaction
    deployment.fail_after = "publish-snapshot"
    with pytest.raises(release_deploy.DeployError, match="injected failure"):
        deployment.apply(execute=True, approve_plan=None)
    assert deployment.store.load().phase == "applying"
    assert operations.calls.count("publish-snapshot") == 1

    deployment.fail_after = None
    assert deployment.apply(execute=True, approve_plan=None)["status"] == "applied"
    assert operations.calls.count("source-switch") == 1
    assert operations.calls.count("publish-snapshot") == 1

    deployment.fail_after = "semantic-verify"
    with pytest.raises(release_deploy.DeployError, match="injected failure"):
        deployment.verify(execute=True)
    deployment.fail_after = None
    assert deployment.verify(execute=True)["status"] == "verified"
    assert operations.calls.count("semantic-verify") == 1
    assert operations.releases == [True]


def test_revision_15_requires_exact_cleanup_plan_before_continuing(transaction):
    prepare(transaction, adapter_set="revision-15")
    deployment, operations, _repo, _database = transaction
    with pytest.raises(release_deploy.ApprovalRequired) as pause:
        deployment.apply(execute=True, approve_plan=None)
    state = deployment.store.load()
    assert state.phase == "awaiting-migration-approval"
    assert pause.value.plan == operations.plan
    assert operations.migrations == [
        "r15-e1-runtime-contract",
        "r15-forward-runtime-contract",
        "r15-xs-runtime-contract",
    ]

    with pytest.raises(release_deploy.ApprovalRequired):
        deployment.apply(execute=True, approve_plan="0" * 64)
    assert deployment.apply(execute=True, approve_plan=pause.value.digest)["status"] == "applied"
    assert operations.migrations == [
        item.migration_id for item in release_deploy.ADAPTERS["revision-15"]
    ]
    assert operations.calls.count("plan:r15-price-cleanup") == 1


@pytest.mark.parametrize(
    "fault",
    [
        "source-switch",
        "runtime-switch",
        "install-automation",
        "publish-snapshot",
        "semantic-verify",
    ],
)
def test_faults_leave_recovery_authority_and_rollback_holds_autopush(transaction, fault):
    prepare(transaction)
    deployment, operations, _repo, _database = transaction
    deployment.fail_after = fault
    if fault == "semantic-verify":
        deployment.apply(execute=True, approve_plan=None)
        with pytest.raises(release_deploy.DeployError, match="injected failure"):
            deployment.verify(execute=True)
    else:
        with pytest.raises(release_deploy.DeployError, match="injected failure"):
            deployment.apply(execute=True, approve_plan=None)

    deployment.fail_after = None
    fresh_shell = release_deploy.ReleaseDeployment(deployment.store, operations)
    assert fresh_shell.rollback(execute=True)["status"] == "rolled-back"
    assert operations.head == OLD_SHA
    assert operations.releases[-1] is False
    assert fresh_shell.rollback(execute=True)["idempotent"] is True


def test_every_revision_15_migration_has_a_fault_boundary(transaction):
    for migration in release_deploy.ADAPTERS["revision-15"]:
        fresh_root = transaction[2].parent / migration.migration_id
        fresh_root.mkdir()
        repo = fresh_root / "repo"
        repo.mkdir()
        database = repo / "market.duckdb"
        database.write_bytes(b"db")
        store = release_deploy.StateStore(fresh_root / "state")
        operations = FakeOperations(store)
        deployment = release_deploy.ReleaseDeployment(store, operations)
        deployment.prepare(
            repo_root=repo,
            database=database,
            approved_sha=NEW_SHA,
            adapter_set="revision-15",
            d0="2026-10-19",
            execute=True,
        )
        approval = release_deploy._digest(
            {
                "migration": release_deploy.asdict(
                    next(
                        item
                        for item in release_deploy.ADAPTERS["revision-15"]
                        if item.migration_id == "r15-price-cleanup"
                    )
                ),
                "plan": operations.plan,
            }
        )
        deployment.fail_after = f"migration-{migration.migration_id}"
        with pytest.raises(release_deploy.DeployError, match="injected failure"):
            deployment.apply(execute=True, approve_plan=approval)
        receipt = release_deploy.ReceiptJournal(store).completed(
            f"migration-{migration.migration_id}"
        )
        assert receipt is not None


def test_rollback_then_resume_requires_current_reconciled_sha(transaction):
    prepare(transaction)
    deployment, operations, _repo, _database = transaction
    deployment.fail_after = "source-switch"
    with pytest.raises(release_deploy.DeployError):
        deployment.apply(execute=True, approve_plan=None)
    deployment.fail_after = None
    deployment.rollback(execute=True)

    with pytest.raises(release_deploy.DeployError, match="does not match"):
        deployment.resume(reconciled_sha=NEW_SHA, execute=True)
    with pytest.raises(release_deploy.DeployError, match="saved release branch"):
        deployment.resume(reconciled_sha=OLD_SHA, execute=True)
    operations.branch = "main"
    result = deployment.resume(reconciled_sha=OLD_SHA, execute=True)
    assert result["status"] == "resumed"
    assert operations.releases[-1] is True


def test_reconciled_source_refuses_detached_head_in_real_repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "symbolic-ref", "HEAD", "refs/heads/main"], check=True)
    (repo / "tracked").write_text("value\n")
    subprocess.run(["git", "-C", repo, "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            repo,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    sha = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", repo, "remote", "add", "origin", str(repo)], check=True)
    subprocess.run(["git", "-C", repo, "update-ref", "refs/remotes/origin/main", sha], check=True)
    subprocess.run(["git", "-C", repo, "config", "branch.main.remote", "origin"], check=True)
    subprocess.run(
        ["git", "-C", repo, "config", "branch.main.merge", "refs/heads/main"], check=True
    )
    operations = release_deploy.ReleaseOperations(
        release_deploy.StateStore(tmp_path / "state"),
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    state = SimpleNamespace(
        repo_root=str(repo), source_branch="main", source_upstream="origin/main"
    )
    operations.validate_reconciled_source(state, sha)
    subprocess.run(["git", "-C", repo, "checkout", "-q", "--detach", sha], check=True)
    with pytest.raises(release_deploy.DeployError, match="saved release branch"):
        operations.validate_reconciled_source(state, sha)


def test_changed_source_and_unknown_migration_are_refused(transaction):
    prepare(transaction)
    deployment, operations, _repo, _database = transaction
    operations.head = "3" * 40
    with pytest.raises(release_deploy.DeployError, match="source changed"):
        deployment.apply(execute=True, approve_plan=None)
    operations.head = OLD_SHA
    state = deployment.store.load()
    state.prepared["migrations"] = [{"migration_id": "unknown", "version": 1}]
    deployment.store.save(state)
    with pytest.raises(release_deploy.DeployError, match="migration registry"):
        deployment.apply(execute=True, approve_plan=None)


def test_source_check_allows_only_transaction_selected_runtime_links(tmp_path):
    repo = tmp_path / "repo"
    (repo / "ui").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", repo], check=True)
    (repo / "tracked").write_text("tracked\n")
    subprocess.run(["git", "-C", repo, "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            repo,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    target = tmp_path / "prepared-build"
    target.mkdir()
    (repo / "ui/.next").symlink_to(target)
    operations = release_deploy.ReleaseOperations(
        release_deploy.StateStore(tmp_path / "state"),
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    with pytest.raises(release_deploy.DeployError, match="ui/.next"):
        operations._source_status(repo)
    assert operations._source_status(repo, allowed_paths=frozenset({"ui/.next"})) == []


def test_receipt_refuses_changed_inputs_without_rerunning(tmp_path):
    store = release_deploy.StateStore(tmp_path / "state")
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="prepared",
        repo_root=str(tmp_path / "repo"),
        database=str(tmp_path / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
    )
    store.create(state)
    journal = release_deploy.ReceiptJournal(store)
    calls = []
    journal.run("example", {"value": 1}, lambda: calls.append(1) or {"ok": True})
    receipt = (store.directory / "receipts/example.json").read_bytes()
    assert journal.run("example", {"value": 1}, lambda: calls.append(2)) == {"ok": True}
    assert (store.directory / "receipts/example.json").read_bytes() == receipt
    with pytest.raises(release_deploy.DeployError, match="inputs changed"):
        journal.run("example", {"value": 2}, lambda: calls.append(3))
    assert calls == [1]


def _write_fake_host(bin_dir: Path) -> None:
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(
        """#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
root=Path(os.environ['FAKE_HOST_STATE']); state=json.loads(root.read_text())
a=sys.argv[1:]; a.remove('--user')
if a[0] in ('list-unit-files','list-units'):
 print('\\n'.join(f'{name} loaded active running' for name in sorted(state['units'])))
elif a[0]=='list-jobs': pass
elif a[0]=='show':
 name=a[1]; unit=state['units'].get(name, {'LoadState':'not-found','ActiveState':'inactive','UnitFileState':'disabled'})
 unit.setdefault('Id',name); unit.setdefault('MainPID','0'); unit.setdefault('ControlGroup',''); unit.setdefault('Triggers',''); unit.setdefault('ExecStart','')
 print('\\n'.join(f'{k}={v}' for k,v in unit.items()))
elif a[0]=='stop':
 for name in a[1:]:
  state['units'].setdefault(name,{})['ActiveState']='inactive'; state['units'][name]['MainPID']='0'
 root.write_text(json.dumps(state))
elif a[0] in ('start','enable','disable'):
 for name in [x for x in a[1:] if not x.startswith('-')]:
  unit=state['units'].setdefault(name,{'LoadState':'loaded','UnitFileState':'disabled'})
  if a[0]=='start':unit.update(ActiveState='active',MainPID='17')
  elif a[0]=='enable':unit['UnitFileState']='enabled'
  else:unit['UnitFileState']='disabled'
 root.write_text(json.dumps(state))
elif a[0]=='daemon-reload': pass
else: sys.exit(2)
"""
    )
    crontab = bin_dir / "crontab"
    crontab.write_text(
        """#!/usr/bin/env python3
import os,sys
from pathlib import Path
p=Path(os.environ['FAKE_CRONTAB']); a=sys.argv[1:]
if a==['-l']:
 if not p.exists(): print('no crontab for fixture',file=sys.stderr);sys.exit(1)
 print(p.read_text(),end='')
elif a==['-r']:
 code=int(os.environ.get('FAKE_CRONTAB_REMOVE_EXIT','0'))
 if code:sys.exit(code)
 if os.environ.get('FAKE_CRONTAB_KEEP')!='1':p.unlink(missing_ok=True)
elif a==['-']: p.write_text(sys.stdin.read())
else: sys.exit(2)
"""
    )
    ps = bin_dir / "ps"
    ps.write_text("#!/bin/sh\nprintf '%s' \"${FAKE_PS_OUTPUT:-}\"\n")
    for path in (systemctl, crontab, ps):
        path.chmod(0o755)


def test_quiesce_uses_only_configured_fake_systemctl_and_crontab(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_host(bin_dir)
    host_state = tmp_path / "host.json"
    host_state.write_text(
        json.dumps(
            {
                "units": {
                    "trading-engine-api.service": {
                        "LoadState": "loaded",
                        "ActiveState": "active",
                        "UnitFileState": "enabled",
                        "MainPID": "17",
                    }
                }
            }
        )
    )
    cron = tmp_path / "cron"
    cron.write_text("fixture cron\n")
    monkeypatch.setenv("FAKE_HOST_STATE", str(host_state))
    monkeypatch.setenv("FAKE_CRONTAB", str(cron))
    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    (repo / "logs").mkdir()
    (repo / "server").mkdir()
    (repo / "server/p15-registration.json").write_text(
        json.dumps({"registration_revision": 14, "code_identity": {"source_commit": OLD_SHA}})
    )
    home = tmp_path / "home"
    home.mkdir()
    store = release_deploy.StateStore(tmp_path / "state")
    os.mkdir(store.directory, 0o700)
    operations = release_deploy.ReleaseOperations(
        store,
        home=home,
        command_runner=release_deploy.CommandRunner(bin_dir),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    monkeypatch.setattr(operations, "request_json", lambda _url: ({"status": "old"}, {}))
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="applying",
        repo_root=str(repo),
        database=str(repo / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
    )
    state.inventory = operations.capture_inventory(state)
    result = operations.quiesce(state)
    assert result["crontab_removed"] is True
    assert not cron.exists()
    observed = json.loads(host_state.read_text())
    assert observed["units"]["trading-engine-api.service"]["ActiveState"] == "inactive"


@pytest.mark.parametrize("exit_code", [1, 2])
def test_quiesce_refuses_failed_crontab_removal(tmp_path, monkeypatch, exit_code):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_host(bin_dir)
    host_state = tmp_path / "host.json"
    host_state.write_text(json.dumps({"units": {}}))
    cron = tmp_path / "cron"
    cron.write_text("still scheduled\n")
    monkeypatch.setenv("FAKE_HOST_STATE", str(host_state))
    monkeypatch.setenv("FAKE_CRONTAB", str(cron))
    monkeypatch.setenv("FAKE_CRONTAB_REMOVE_EXIT", str(exit_code))
    monkeypatch.setenv("FAKE_PS_OUTPUT", "")
    store = release_deploy.StateStore(tmp_path / "state")
    os.mkdir(store.directory, 0o700)
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(bin_dir),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="applying",
        repo_root=str(tmp_path / "repo"),
        database=str(tmp_path / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
        inventory={
            "units": {
                name: {
                    "LoadState": "not-found",
                    "ActiveState": "inactive",
                    "UnitFileState": "disabled",
                }
                for name in release_deploy.install_automation.UNIT_SOURCES
            },
            "crontab": {"present": True, "content": "still scheduled\n"},
        },
    )
    with pytest.raises(release_deploy.DeployError, match="failed to remove"):
        operations.quiesce(state)
    assert cron.read_text() == "still scheduled\n"


def test_quiesce_verifies_crontab_is_absent_after_success_exit(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_host(bin_dir)
    host_state = tmp_path / "host.json"
    host_state.write_text(json.dumps({"units": {}}))
    cron = tmp_path / "cron"
    cron.write_text("still scheduled\n")
    monkeypatch.setenv("FAKE_HOST_STATE", str(host_state))
    monkeypatch.setenv("FAKE_CRONTAB", str(cron))
    monkeypatch.setenv("FAKE_CRONTAB_KEEP", "1")
    store = release_deploy.StateStore(tmp_path / "state")
    os.mkdir(store.directory, 0o700)
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(bin_dir),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="applying",
        repo_root=str(tmp_path / "repo"),
        database=str(tmp_path / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
        inventory={
            "units": {
                name: {
                    "LoadState": "not-found",
                    "ActiveState": "inactive",
                    "UnitFileState": "disabled",
                }
                for name in release_deploy.install_automation.UNIT_SOURCES
            },
            "crontab": {"present": True, "content": "still scheduled\n"},
        },
    )
    with pytest.raises(release_deploy.DeployError, match="survived removal"):
        operations.quiesce(state)


def test_quiesce_refuses_a_surviving_writer_from_the_release_checkout(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_host(bin_dir)
    host_state = tmp_path / "host.json"
    host_state.write_text(json.dumps({"units": {}}))
    monkeypatch.setenv("FAKE_HOST_STATE", str(host_state))
    monkeypatch.setenv("FAKE_CRONTAB", str(tmp_path / "missing-cron"))
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("FAKE_PS_OUTPUT", f"4242 1 /bin/bash {repo}/engine/run_daily.sh\n")
    store = release_deploy.StateStore(tmp_path / "state")
    os.mkdir(store.directory, 0o700)
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(bin_dir),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="applying",
        repo_root=str(repo),
        database=str(repo / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
        inventory={"units": {}, "crontab": {"present": False, "content": ""}},
    )
    with pytest.raises(release_deploy.DeployError, match="survived quiescence"):
        operations.quiesce(state)


def test_release_restores_exact_activation_and_crontab_with_autopush_held(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_host(bin_dir)
    units = {
        "trading-engine-api.service": {
            "LoadState": "loaded",
            "ActiveState": "active",
            "UnitFileState": "enabled",
            "MainPID": "17",
        },
        "trading-engine-ui.service": {
            "LoadState": "loaded",
            "ActiveState": "active",
            "UnitFileState": "enabled",
            "MainPID": "17",
        },
        "te-autopush.timer": {
            "LoadState": "loaded",
            "ActiveState": "active",
            "UnitFileState": "enabled",
            "MainPID": "17",
        },
    }
    host_state = tmp_path / "host.json"
    host_state.write_text(json.dumps({"units": units}))
    cron = tmp_path / "cron"
    monkeypatch.setenv("FAKE_HOST_STATE", str(host_state))
    monkeypatch.setenv("FAKE_CRONTAB", str(cron))
    monkeypatch.setenv("FAKE_PS_OUTPUT", "")
    store = release_deploy.StateStore(tmp_path / "state")
    os.mkdir(store.directory, 0o700)
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(bin_dir),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="rolling-back",
        repo_root=str(tmp_path / "repo"),
        database=str(tmp_path / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
        inventory={
            "units": units,
            "crontab": {"present": True, "content": "exact fixture cron\n"},
        },
    )
    result = operations.release_producers(state, include_autopush=False)
    assert result["autopush_held"] is True
    observed = json.loads(host_state.read_text())["units"]
    assert observed["trading-engine-api.service"]["ActiveState"] == "active"
    assert observed["trading-engine-ui.service"]["ActiveState"] == "active"
    assert observed["te-autopush.timer"]["ActiveState"] == "inactive"
    assert cron.read_text() == "exact fixture cron\n"


def test_runtime_directory_and_absence_restore_idempotently(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".venv").mkdir(parents=True)
    (repo / ".venv/marker").write_text("old")
    (repo / "ui").mkdir()
    state_dir = tmp_path / "state"
    store = release_deploy.StateStore(state_dir)
    os.mkdir(state_dir, 0o700)
    prepared = state_dir / "prepared"
    for relative in ("python", "node/node_modules", "node/.next"):
        (prepared / relative).mkdir(parents=True, exist_ok=True)
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="applying",
        repo_root=str(repo),
        database=str(repo / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
        prepared={
            "python_environment": str(prepared / "python"),
            "node_modules": str(prepared / "node/node_modules"),
            "ui_build": str(prepared / "node/.next"),
        },
    )
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    prior = operations.switch_runtimes(state)
    state.prior_runtimes = prior
    assert (repo / ".venv").is_symlink()
    assert (repo / "ui/node_modules").is_symlink()
    operations.restore_runtimes(state)
    operations.restore_runtimes(state)
    assert (repo / ".venv/marker").read_text() == "old"
    assert not os.path.lexists(repo / "ui/node_modules")
    assert not os.path.lexists(repo / "ui/.next")


def test_restore_database_is_byte_exact_and_quarantines_new_snapshot(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    database = repo / "store/market.duckdb"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"new database")
    snapshots = database.parent / "snapshots"
    snapshots.mkdir()
    (snapshots / "new.json").write_text("{}")
    state_dir = tmp_path / "state"
    store = release_deploy.StateStore(state_dir)
    os.mkdir(state_dir, 0o700)
    (state_dir / "incident").mkdir()
    bundle = state_dir / "recovery"
    bundle.mkdir(mode=0o700)
    restored = b"old database"
    (bundle / "market.duckdb").write_bytes(restored)
    digest = __import__("hashlib").sha256(restored).hexdigest()
    manifest = {
        "database": {"sha256": digest},
        "release_identity": {"git_sha": OLD_SHA},
        "prospective_evidence": {},
        "operational_artifacts": {},
        "operational_controls": {},
    }
    manifest_path = bundle / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    manifest_path.chmod(0o600)
    monkeypatch.setattr(
        release_deploy.backup_database,
        "verify_backup",
        lambda _bundle: {"manifest_sha256": "a" * 64},
    )
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="rolling-back",
        repo_root=str(repo),
        database=str(database),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
        backup={"manifest_sha256": "a" * 64},
    )
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    result = operations.restore_database(state)
    assert database.read_bytes() == restored
    assert result["database_sha256"] == digest
    assert (state_dir / "incident/quarantined-snapshots/new.json").is_file()


def test_forced_snapshot_probe_requires_snapshot_header(tmp_path, monkeypatch):
    database = tmp_path / "market.duckdb"
    duckdb.connect(str(database)).close()
    state_dir = tmp_path / "state"
    store = release_deploy.StateStore(state_dir)
    os.mkdir(state_dir, 0o700)
    python_env = Path(os.environ.get("VIRTUAL_ENV", Path(__file__).parents[1] / ".venv"))
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="verifying",
        repo_root=str(tmp_path),
        database=str(database),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
        prepared={"python_environment": str(python_env)},
    )
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://fixture",
        ui_url="http://fixture",
        minimum_free_bytes=0,
    )
    monkeypatch.setattr(
        operations,
        "request_json",
        lambda _url: ({"status": "ok"}, {"x-data-source": "snapshot"}),
    )
    assert operations._forced_snapshot(state, rolled_back=False) == {"header": "snapshot"}


def test_insufficient_recovery_workspace_refuses_before_copy(tmp_path, monkeypatch):
    database = tmp_path / "market.duckdb"
    database.write_bytes(b"1234")
    store = release_deploy.StateStore(tmp_path / "state")
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=10,
    )
    monkeypatch.setattr(
        release_deploy.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=100, used=95, free=5),
    )
    state = SimpleNamespace(database=str(database))
    with pytest.raises(release_deploy.DeployError, match="insufficient recovery workspace"):
        operations._check_workspace(state, copies=1)


def test_preflight_binds_the_approved_commit_dependency_locks(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "ui").mkdir(parents=True)
    (repo / "store").mkdir()
    (repo / "uv.lock").write_text("old python lock\n")
    (repo / "ui/package-lock.json").write_text("old node lock\n")
    (repo / "store/market.duckdb").write_bytes(b"synthetic")
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            repo,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "old",
        ],
        check=True,
    )
    old = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    (repo / "uv.lock").write_text("new python lock\n")
    (repo / "ui/package-lock.json").write_text("new node lock\n")
    (repo / "server").mkdir()
    (repo / "server/p15-registration.json").write_text(
        json.dumps({"code_identity": {"source_commit": old}})
    )
    subprocess.run(["git", "-C", repo, "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            repo,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "new",
        ],
        check=True,
    )
    approved = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", repo, "checkout", "-qB", "main", old], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "origin", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", repo, "update-ref", "refs/remotes/origin/main", approved], check=True
    )
    subprocess.run(["git", "-C", repo, "config", "branch.main.remote", "origin"], check=True)
    subprocess.run(
        ["git", "-C", repo, "config", "branch.main.merge", "refs/heads/main"], check=True
    )
    monkeypatch.setattr(
        release_deploy.worktree_audit,
        "build_audit",
        lambda _root: {
            "review_gates": {
                "index_empty": True,
                "ownership_complete": True,
                "untracked_files_safe": True,
            },
            "protected_research": {"identity_complete": True},
        },
    )
    store = release_deploy.StateStore(tmp_path / "new-parent/state")
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    result = operations.preflight_prepare(
        repo_root=repo,
        database=repo / "store/market.duckdb",
        approved_sha=approved,
        adapter_set="revision-15",
        d0="2026-10-19",
    )
    assert result["original_sha"] == old
    assert result["lock_sha256"] == {
        "uv.lock": hashlib.sha256(b"new python lock\n").hexdigest(),
        "ui/package-lock.json": hashlib.sha256(b"new node lock\n").hexdigest(),
    }
    assert result["registration_source_commit"] == old

    subprocess.run(["git", "-C", repo, "checkout", "-qB", "main", approved], check=True)
    (repo / "server/p15-registration.json").write_text(
        json.dumps({"code_identity": {"source_commit": "3" * 40}})
    )
    subprocess.run(["git", "-C", repo, "add", "."], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            repo,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "rewritten registration",
        ],
        check=True,
    )
    rewritten = subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", repo, "checkout", "-qB", "main", old], check=True)
    subprocess.run(
        ["git", "-C", repo, "update-ref", "refs/remotes/origin/main", rewritten], check=True
    )
    with pytest.raises(release_deploy.DeployError, match="not an ancestor"):
        operations.preflight_prepare(
            repo_root=repo,
            database=repo / "store/market.duckdb",
            approved_sha=rewritten,
            adapter_set="revision-15",
            d0="2026-10-19",
        )


def test_required_unit_that_does_not_converge_is_refused(tmp_path, monkeypatch):
    class Runner:
        def __init__(self):
            self.index = 0

        def run(self, *_args, **_kwargs):
            changes = {
                "service_units": [],
                "enable_units": [],
                "start_units": ["trading-engine-api.service"],
                "crontab": False,
                "enable_linger": False,
            }
            errors = ["provider response refused"] if self.index == 1 else []
            payload = {"status": "changes-required", "errors": errors, "changes": changes}
            returncode = 1 if self.index == 1 else 0
            self.index += 1
            return subprocess.CompletedProcess([], returncode, json.dumps(payload), "")

    root = tmp_path / "repo"
    root.mkdir()
    store = release_deploy.StateStore(tmp_path / "state")
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="applying",
        repo_root=str(root),
        database=str(root / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
        prepared={
            "python_environment": str(tmp_path / "python"),
            "unit_policy": {
                name: "optional" if name in release_deploy.OPTIONAL_UNITS else "required"
                for name in release_deploy.install_automation.UNIT_SOURCES
            },
        },
    )
    store.create(state)
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=Runner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    monkeypatch.setattr(operations, "_record_automation_mutations", lambda state: state.automation)
    with pytest.raises(release_deploy.DeployError, match="required automation"):
        operations.install_automation(state)


def test_optional_provider_unit_failure_is_classified_without_release_failure(
    tmp_path, monkeypatch
):
    class Runner:
        def __init__(self):
            self.index = 0

        def run(self, *_args, **_kwargs):
            changes = {
                "service_units": [],
                "enable_units": [],
                "start_units": ["massive-options-daily.service"],
                "crontab": False,
                "enable_linger": False,
            }
            errors = ["provider response refused"] if self.index == 1 else []
            payload = {"status": "changes-required", "errors": errors, "changes": changes}
            returncode = 1 if self.index == 1 else 0
            self.index += 1
            return subprocess.CompletedProcess([], returncode, json.dumps(payload), "")

    root = tmp_path / "repo"
    root.mkdir()
    store = release_deploy.StateStore(tmp_path / "state")
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="applying",
        repo_root=str(root),
        database=str(root / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
        prepared={
            "python_environment": str(tmp_path / "python"),
            "unit_policy": {
                name: "optional" if name in release_deploy.OPTIONAL_UNITS else "required"
                for name in release_deploy.install_automation.UNIT_SOURCES
            },
        },
    )
    store.create(state)
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=Runner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    monkeypatch.setattr(operations, "_record_automation_mutations", lambda state: state.automation)
    result = operations.install_automation(state)
    assert result["status"] == "optional-failures"
    assert result["optional_failures"] == ["massive-options-daily.service"]
    assert result["apply_errors"] == ["provider response refused"]


def test_prepared_dependency_without_executable_environment_is_refused(transaction):
    prepare(transaction)
    deployment, _operations, _repo, _database = transaction
    (Path(deployment.store.load().prepared["python_environment"]) / "bin/python").unlink()
    with pytest.raises(release_deploy.DeployError, match="no executable environment"):
        deployment.apply(execute=False, approve_plan=None)


def test_prepare_resolves_ui_toolchain_without_a_shell_path(tmp_path, monkeypatch):
    home = tmp_path / "home"
    node_bin = home / "tools/node/bin"
    node_bin.mkdir(parents=True)
    for name in ("node", "npm"):
        path = node_bin / name
        path.write_text("#!/bin/sh\nexit 0\n")
        path.chmod(0o755)
    git = Path(shutil.which("git"))
    uv = Path(shutil.which("uv"))
    monkeypatch.setenv("PATH", "")
    store = release_deploy.StateStore(tmp_path / "state")
    operations = release_deploy.ReleaseOperations(
        store,
        home=home,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
        tool_paths={"git": git, "uv": uv},
    )
    tools = operations._resolve_release_tools()
    assert tools["node"]["path"] == str(node_bin / "node")
    assert tools["npm"]["path"] == str(node_bin / "npm")

    (node_bin / "node").unlink()
    with pytest.raises(release_deploy.DeployError, match="required release executable.*node"):
        operations._resolve_release_tools()
    deployment = release_deploy.ReleaseDeployment(store, operations)
    with pytest.raises(release_deploy.DeployError, match="required release executable.*node"):
        deployment.prepare(
            repo_root=tmp_path / "not-reached",
            database=tmp_path / "not-reached.duckdb",
            approved_sha=NEW_SHA,
            adapter_set="none",
            d0=None,
            execute=True,
        )
    assert not store.directory.exists()


def test_optional_unit_failure_pauses_after_requiesce_and_can_be_accepted(transaction):
    prepare(transaction)
    deployment, operations, _repo, _database = transaction
    operations.optional_failures = ["massive-options-daily.service"]
    with pytest.raises(release_deploy.OptionalUnitsPaused) as pause:
        deployment.apply(execute=True, approve_plan=None)
    assert deployment.store.load().phase == "awaiting-optional-units"
    assert operations.calls[-1] == "quiesce"
    assert "publish-snapshot" not in operations.calls

    result = deployment.apply(
        execute=True,
        approve_plan=None,
        approve_optional=pause.value.digest,
    )
    assert result["status"] == "applied"
    assert operations.calls.count("install-automation") == 1
    assert operations.calls.count("publish-snapshot") == 1


def test_quiesce_refuses_new_unit_without_touching_it(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_host(bin_dir)
    unexpected = "trading-engine-surprise.timer"
    host_state = tmp_path / "host.json"
    host_state.write_text(
        json.dumps(
            {
                "units": {
                    unexpected: {
                        "LoadState": "loaded",
                        "ActiveState": "active",
                        "UnitFileState": "enabled",
                        "MainPID": "17",
                    }
                }
            }
        )
    )
    cron = tmp_path / "cron"
    cron.write_text("must remain\n")
    monkeypatch.setenv("FAKE_HOST_STATE", str(host_state))
    monkeypatch.setenv("FAKE_CRONTAB", str(cron))
    monkeypatch.setenv("FAKE_PS_OUTPUT", "")
    store = release_deploy.StateStore(tmp_path / "state")
    os.mkdir(store.directory, 0o700)
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(bin_dir),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="applying",
        repo_root=str(tmp_path / "repo"),
        database=str(tmp_path / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
        inventory={"units": {}, "crontab": {"present": True, "content": "must remain\n"}},
    )
    with pytest.raises(release_deploy.DeployError, match="outside saved inventory"):
        operations.quiesce(state)
    assert json.loads(host_state.read_text())["units"][unexpected]["ActiveState"] == "active"
    assert cron.read_text() == "must remain\n"


def test_private_alpha_units_are_never_claimed_by_release_inventory(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_host(bin_dir)
    host_state = tmp_path / "host.json"
    host_state.write_text(
        json.dumps(
            {
                "units": {
                    "live-287.timer": {
                        "LoadState": "loaded",
                        "ActiveState": "active",
                        "UnitFileState": "enabled",
                        "ExecStart": "/trading-alpha/live-287",
                    }
                }
            }
        )
    )
    monkeypatch.setenv("FAKE_HOST_STATE", str(host_state))
    monkeypatch.setenv("FAKE_CRONTAB", str(tmp_path / "cron"))
    store = release_deploy.StateStore(tmp_path / "state")
    os.mkdir(store.directory, 0o700)
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(bin_dir),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    assert "live-287.timer" not in operations._unit_names()


def test_rollback_does_not_disable_unit_never_installed_by_apply(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_host(bin_dir)
    name = "massive-options-daily.service"
    host_state = tmp_path / "host.json"
    host_state.write_text(json.dumps({"units": {}}))
    monkeypatch.setenv("FAKE_HOST_STATE", str(host_state))
    monkeypatch.setenv("FAKE_CRONTAB", str(tmp_path / "cron"))
    home = tmp_path / "home"
    home.mkdir()
    store = release_deploy.StateStore(tmp_path / "state")
    os.mkdir(store.directory, 0o700)
    operations = release_deploy.ReleaseOperations(
        store,
        home=home,
        command_runner=release_deploy.CommandRunner(bin_dir),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="rolling-back",
        repo_root=str(tmp_path / "repo"),
        database=str(tmp_path / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
        inventory={
            "unit_files": {name: {"kind": "absent"}},
            "units": {
                name: {
                    "LoadState": "not-found",
                    "ActiveState": "inactive",
                    "UnitFileState": "disabled",
                }
            },
        },
        automation={"installed_unit_files": [], "enablement_units": []},
    )
    assert operations.restore_units(state) == {"restored": [], "enablement_restored": []}


def test_state_loader_rejects_permissions_and_unknown_fields(tmp_path):
    store = release_deploy.StateStore(tmp_path / "state")
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="prepared",
        repo_root=str(tmp_path / "repo"),
        database=str(tmp_path / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
    )
    store.create(state)
    store.directory.chmod(0o755)
    with pytest.raises(release_deploy.DeployError, match="mode-0700"):
        store.load()
    store.directory.chmod(0o700)
    payload = json.loads(store.state_path.read_text())
    payload["surprise"] = True
    store.state_path.write_text(json.dumps(payload))
    with pytest.raises(release_deploy.DeployError, match="unknown or missing"):
        store.load()


def test_cli_defaults_to_plan_and_fault_injection_requires_opt_in(monkeypatch, capsys):
    monkeypatch.setattr(release_deploy, "StateStore", lambda _path: object())
    assert release_deploy.main(["--fail-after", "source-switch", "verify", "/tmp/state"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"


def test_cli_database_default_is_relative_to_selected_checkout(tmp_path):
    args = release_deploy._parser().parse_args(
        [
            "--repo-root",
            str(tmp_path),
            "prepare",
            str(tmp_path / "state"),
            "--approved-sha",
            NEW_SHA,
        ]
    )
    assert not args.database.is_absolute()
    assert (args.repo_root.resolve() / args.database) == tmp_path / "store/market.duckdb"


def test_running_source_switch_receipt_adopts_approved_head(transaction):
    prepare(transaction)
    deployment, operations, _repo, _database = transaction
    state = deployment.store.load()
    state.phase = "applying"
    state.inventory = operations.capture_inventory(state)
    state.backup = operations.create_backup(state)
    deployment.store.save(state)
    journal = release_deploy.ReceiptJournal(deployment.store)
    journal.run("capture-inventory", {"original_sha": OLD_SHA}, lambda: state.inventory)
    journal.run("quiesce", {"inventory": release_deploy._digest(state.inventory)}, lambda: {})
    journal.run(
        "predeploy-adapter-check",
        {"adapter_set": "none", "d0": None},
        lambda: {"adapter_set": "none"},
    )
    journal.run(
        "create-backup",
        {"original_sha": OLD_SHA, "database": state.database},
        lambda: state.backup,
    )
    operations.head = NEW_SHA
    running_receipt(
        deployment.store,
        "source-switch",
        {"from": OLD_SHA, "to": NEW_SHA},
    )
    result = deployment.apply(execute=True, approve_plan=None)
    assert result["status"] == "applied"
    assert operations.calls.count("source-switch") == 0
    assert journal.completed("source-switch")["reconciled"] is True


@pytest.mark.parametrize(
    "migration",
    [item.migration_id for item in release_deploy.ADAPTERS["revision-15"]],
)
def test_running_migration_receipt_adopts_verified_post_state(transaction, migration):
    prepare(transaction, adapter_set="revision-15")
    deployment, operations, _repo, _database = transaction
    state = deployment.store.load()
    spec = next(
        item for item in release_deploy.ADAPTERS["revision-15"] if item.migration_id == migration
    )
    plan = operations.plan if spec.approval_required else None
    intent = operations.migration_intent(state, spec, plan)
    inputs = {
        "migration": release_deploy.asdict(spec),
        "approved_sha": NEW_SHA,
        "plan": plan,
        "intent": intent,
    }
    running_receipt(deployment.store, f"migration-{migration}", inputs)
    operations.reconciled_migrations.add(migration)
    result = deployment.journal.run(
        f"migration-{migration}",
        inputs,
        lambda: (_ for _ in ()).throw(AssertionError("must not repeat mutation")),
        reconcile=lambda: operations.reconcile_migration(state, spec, plan, intent),
    )
    assert result == {"migration": migration, "reconciled": True}


def test_journal_recovers_a_process_killed_after_mutation(tmp_path):
    store = release_deploy.StateStore(tmp_path / "state")
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="applying",
        repo_root=str(tmp_path / "repo"),
        database=str(tmp_path / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
    )
    store.create(state)
    marker = tmp_path / "mutated"
    code = """
import os,sys
from pathlib import Path
from tools.release_deploy import ReceiptJournal,StateStore
store=StateStore(Path(sys.argv[1])); marker=Path(sys.argv[2])
def action(): marker.write_text('done'); os._exit(17)
ReceiptJournal(store).run('killed', {'value': 1}, action)
"""
    result = subprocess.run(
        [
            str(Path(__file__).parents[1] / ".venv/bin/python"),
            "-c",
            code,
            str(store.directory),
            str(marker),
        ],
        cwd=Path(__file__).parents[1],
        env=os.environ | {"PYTHONPATH": str(Path(__file__).parents[1])},
    )
    assert result.returncode == 17
    journal = release_deploy.ReceiptJournal(store)
    assert journal.read("killed")["status"] == "running"
    recovered = journal.run(
        "killed",
        {"value": 1},
        lambda: (_ for _ in ()).throw(AssertionError("must not repeat mutation")),
        reconcile=lambda: {"marker": "done"} if marker.read_text() == "done" else None,
    )
    assert recovered == {"marker": "done"}


def test_runtime_switch_recovers_after_old_symlink_was_unlinked(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    old = tmp_path / "old-runtime"
    prepared = tmp_path / "prepared-runtime"
    old.mkdir()
    prepared.mkdir()
    live = repo / ".venv"
    live.symlink_to(old)
    store = release_deploy.StateStore(tmp_path / "state")
    os.mkdir(store.directory, 0o700)
    saved = store.directory / "inventory/runtimes/venv"
    saved.mkdir(parents=True)
    release_deploy._atomic_json(saved / "identity.json", {"kind": "symlink", "target": str(old)})
    live.unlink()
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    assert operations._select_runtime(live, prepared, saved) == {
        "kind": "symlink",
        "target": str(old),
    }
    assert Path(os.path.realpath(live)) == prepared


def test_existing_complete_incident_is_verified_and_adopted(tmp_path):
    store = release_deploy.StateStore(tmp_path / "state")
    os.mkdir(store.directory, 0o700)
    incident = store.directory / "incident"
    incident.mkdir()
    (incident / "market.duckdb").write_bytes(b"incident")
    active = tmp_path / "market.duckdb"
    active.write_bytes(b"active")
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    state = SimpleNamespace(database=str(active))
    first = operations.reconcile_incident(state)
    assert first["database_sha256"] == hashlib.sha256(b"incident").hexdigest()
    assert operations.capture_incident(state) == first


def test_transaction_addressed_snapshot_is_adopted_without_republication(tmp_path, monkeypatch):
    database = tmp_path / "store/market.duckdb"
    directory = database.parent / "snapshots"
    directory.mkdir(parents=True)
    store = release_deploy.StateStore(tmp_path / "state")
    os.mkdir(store.directory, 0o700)
    state = SimpleNamespace(
        created_at="2026-10-19T01:02:03.000004+00:00",
        database=str(database),
        repo_root=str(tmp_path),
    )
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    name = operations._snapshot_name(state, "apply")
    snapshot = directory / name
    snapshot.write_bytes(b"snapshot")
    manifest = {"snapshot": name, "sha256": hashlib.sha256(b"snapshot").hexdigest()}
    manifest_path = snapshot.with_suffix(".json")
    manifest_path.write_text(json.dumps(manifest))
    manifest_path.chmod(0o600)
    (directory / "market-latest.duckdb").symlink_to(name)
    monkeypatch.setattr(
        release_deploy.publish_snapshot,
        "publish_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not republish")),
    )
    assert operations.publish_snapshot(state, frozenset(), purpose="apply") == manifest


def test_artifact_restore_removes_new_release_files_after_incident_capture(tmp_path):
    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    (repo / "logs").mkdir()
    (repo / "data/original.json").write_text("old\n")
    store = release_deploy.StateStore(tmp_path / "state")
    os.mkdir(store.directory, 0o700)
    state = SimpleNamespace(
        repo_root=str(repo), inventory={"artifacts": str(store.directory / "inventory/artifacts")}
    )
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    state.inventory["artifact_manifest"] = operations.capture_artifacts(state)
    (repo / "data/original.json").write_text("new\n")
    (repo / "data/new-release.json").write_text("new only\n")
    result = operations.restore_artifacts(state)
    assert (repo / "data/original.json").read_text() == "old\n"
    assert not (repo / "data/new-release.json").exists()
    assert result["quarantined_extra_paths"] == ["data/new-release.json"]


def test_apply_captures_artifacts_only_after_quiescence_and_lock(transaction):
    prepare(transaction)
    deployment, operations, _repo, _database = transaction
    deployment.apply(execute=True, approve_plan=None)
    assert operations.calls.index("quiesce") < operations.calls.index("locks")
    assert operations.calls.index("locks") < operations.calls.index("capture-artifacts")


def test_common_semantics_reject_killed_evidence_for_adapter_none(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "server").mkdir(parents=True)
    registration = {
        "registration_revision": 15,
        "code_identity": {"source_commit": OLD_SHA},
    }
    registration_path = repo / "server/p15-registration.json"
    registration_path.write_text(json.dumps(registration))
    semantic = {
        "registration_revision": 15,
        "registration_source_commit": OLD_SHA,
        "registration_sha256": hashlib.sha256(registration_path.read_bytes()).hexdigest(),
        "runtime_versions": {
            "forward_review": 12,
            "xs_forward_review": 23,
            "e1_forward": 8,
        },
    }
    state = SimpleNamespace(
        repo_root=str(repo),
        adapter_set="none",
        prepared={"semantic": semantic},
        inventory={"registration": semantic, "predeploy_meta": {}},
    )
    operations = release_deploy.ReleaseOperations(
        release_deploy.StateStore(tmp_path / "state"),
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    monkeypatch.setattr(
        operations,
        "_python_json",
        lambda *_args, **_kwargs: {"versions": semantic["runtime_versions"], "evidence": "valid"},
    )
    meta = {
        key: {"status": "ACCUMULATING", "runtime_contract_version": version}
        for key, version in semantic["runtime_versions"].items()
    }
    meta["forward_review"]["status"] = "KILLED"
    with pytest.raises(release_deploy.DeployError, match="not accumulating"):
        operations._common_semantics(state, meta, rolled_back=False)
    meta["forward_review"]["status"] = "ACCUMULATING"
    assert operations._common_semantics(state, meta, rolled_back=False)["evidence"] == "valid"


def test_route_verification_rejects_http_200_error_shell(tmp_path, monkeypatch):
    class Response:
        status = 200
        headers = {"Content-Type": "text/html"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"error"

    monkeypatch.setattr(
        release_deploy.urllib.request, "urlopen", lambda *_args, **_kwargs: Response()
    )
    operations = release_deploy.ReleaseOperations(
        release_deploy.StateStore(tmp_path / "state"),
        home=tmp_path,
        command_runner=release_deploy.CommandRunner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    with pytest.raises(release_deploy.DeployError, match="not semantically readable"):
        operations.request_route("http://fixture/positions", marker="position")


def test_actual_unit_mutations_are_derived_from_saved_inventory(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_host(bin_dir)
    name = "trading-engine-api.service"
    host_state = tmp_path / "host.json"
    host_state.write_text(
        json.dumps(
            {
                "units": {
                    name: {
                        "LoadState": "loaded",
                        "ActiveState": "inactive",
                        "UnitFileState": "enabled",
                        "MainPID": "0",
                    }
                }
            }
        )
    )
    monkeypatch.setenv("FAKE_HOST_STATE", str(host_state))
    monkeypatch.setenv("FAKE_CRONTAB", str(tmp_path / "cron"))
    root = tmp_path / "repo"
    source = root / release_deploy.install_automation.UNIT_SOURCES[name]
    source.parent.mkdir(parents=True)
    source.write_text("new unit\n")
    home = tmp_path / "home"
    installed = home / ".config/systemd/user" / name
    installed.parent.mkdir(parents=True)
    installed.write_text("new unit\n")
    store = release_deploy.StateStore(tmp_path / "state")
    state = release_deploy.ReleaseState(
        schema_version=1,
        transaction_id="fixture",
        created_at="now",
        updated_at="now",
        phase="applying",
        repo_root=str(root),
        database=str(root / "db"),
        approved_sha=NEW_SHA,
        original_sha=OLD_SHA,
        adapter_set="none",
        d0=None,
        inventory={
            "unit_files": {name: {"kind": "absent"}},
            "units": {
                name: {
                    "LoadState": "not-found",
                    "ActiveState": "inactive",
                    "UnitFileState": "disabled",
                }
            },
        },
    )
    store.create(state)
    operations = release_deploy.ReleaseOperations(
        store,
        home=home,
        command_runner=release_deploy.CommandRunner(bin_dir),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    recorded = operations._record_automation_mutations(state)
    assert recorded["installed_unit_files"] == [name]
    assert recorded["enablement_units"] == [name]
