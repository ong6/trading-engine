from __future__ import annotations

import hashlib
import json
import os
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
        self.calls: list[str] = []
        self.releases: list[bool] = []
        self.migrations: list[str] = []
        self.plan = {"invalid_rows": 2, "moved": 0}

    def preflight_prepare(self, **kwargs):
        self.calls.append("preflight")
        return {
            "original_sha": OLD_SHA,
            "approved_sha": kwargs["approved_sha"],
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

    def switch_source(self, state):
        self.calls.append("source-switch")
        self.head = state.approved_sha
        return {"git_sha": self.head}

    def switch_runtimes(self, _state):
        self.calls.append("runtime-switch")
        return {
            ".venv": {"kind": "symlink", "target": "/prior/python"},
            "ui/node_modules": {"kind": "absent"},
            "ui/.next": {"kind": "absent"},
        }

    def plan_migration(self, _state, migration):
        self.calls.append(f"plan:{migration.migration_id}")
        return self.plan

    def apply_migration(self, _state, migration, _plan):
        self.calls.append(f"migration:{migration.migration_id}")
        self.migrations.append(migration.migration_id)
        return {"migration": migration.migration_id}

    def install_automation(self, _state):
        self.calls.append("install-automation")
        return {"status": "ok"}

    def publish_snapshot(self, _state, _held_locks):
        self.calls.append("publish-snapshot")
        return {"sha256": "f" * 64}

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

    def restore_source(self, state):
        self.calls.append("restore-source")
        self.head = state.original_sha
        return {"git_sha": self.head}

    def restore_runtimes(self, _state):
        self.calls.append("restore-runtimes")
        return {"restored": True}

    def restore_database(self, _state):
        self.calls.append("restore-database")
        return {"restored": True}

    def restore_units(self, _state):
        self.calls.append("restore-units")
        return {"restored": True}

    def _head(self, _root):
        return self.head

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
    result = deployment.resume(reconciled_sha=OLD_SHA, execute=True)
    assert result["status"] == "resumed"
    assert operations.releases[-1] is True


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
 if not p.exists(): sys.exit(1)
 print(p.read_text(),end='')
elif a==['-r']: p.unlink(missing_ok=True)
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
    subprocess.run(["git", "-C", repo, "checkout", "-q", old], check=True)
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
        adapter_set="none",
        d0=None,
    )
    assert result["original_sha"] == old
    assert result["lock_sha256"] == {
        "uv.lock": hashlib.sha256(b"new python lock\n").hexdigest(),
        "ui/package-lock.json": hashlib.sha256(b"new node lock\n").hexdigest(),
    }


def test_mismatched_installed_unit_is_refused(tmp_path):
    class Runner:
        def run(self, *_args, **_kwargs):
            payload = {
                "status": "ok",
                "applied": True,
                "service_units": {"fixture.service": {"matches": False}},
            }
            return subprocess.CompletedProcess([], 0, json.dumps(payload), "")

    root = tmp_path / "repo"
    root.mkdir()
    store = release_deploy.StateStore(tmp_path / "state")
    operations = release_deploy.ReleaseOperations(
        store,
        home=tmp_path,
        command_runner=Runner(),
        api_url="http://invalid",
        ui_url="http://invalid",
        minimum_free_bytes=0,
    )
    state = SimpleNamespace(
        repo_root=str(root), prepared={"python_environment": str(tmp_path / "python")}
    )
    with pytest.raises(release_deploy.DeployError, match="installed unit mismatch"):
        operations.install_automation(state)


def test_prepared_dependency_without_executable_environment_is_refused(transaction):
    prepare(transaction)
    deployment, _operations, _repo, _database = transaction
    (Path(deployment.store.load().prepared["python_environment"]) / "bin/python").unlink()
    with pytest.raises(release_deploy.DeployError, match="no executable environment"):
        deployment.apply(execute=False, approve_plan=None)


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
