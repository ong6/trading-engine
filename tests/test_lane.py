"""Temporary-repository tests for exact-base lane coordination."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import zlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools import lane

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXED_NOW = datetime(2026, 10, 18, 18, 5, tzinfo=UTC)
CURRENT_CLAIMS_ZLIB_B64 = "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"


def _run(root: Path, *command: str, check: bool = True, env=None):
    return subprocess.run(
        list(command),
        cwd=root,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _git(root: Path, *args: str, check: bool = True):
    return _run(
        root,
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        *args,
        check=check,
    )


def _fixture(tmp_path: Path) -> dict:
    home = tmp_path / "home"
    root = home / "engine-lanes"
    root.mkdir(parents=True)
    remote = root / "remote.git"
    _git(root, "init", "--bare", str(remote))
    source = root / "source"
    _git(root, "clone", str(remote), str(source))
    _git(source, "config", "user.name", "Fixture Author")
    _git(source, "config", "user.email", "fixture@example.com")
    (source / ".gitignore").write_text(".venv/\n")
    (source / "README.md").write_text("fixture repository\n")
    (source / "uv.lock").write_text("version = 1\n")
    _git(source, "add", ".gitignore", "README.md", "uv.lock")
    _git(source, "commit", "-m", "fixture base")
    _git(source, "push", "-u", "origin", "HEAD")
    base = _git(source, "rev-parse", "HEAD").stdout.strip()
    python = source / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexit 0\n")
    python.chmod(0o700)
    claims = root / "CLAIMS.md"
    claims.write_text("# Engine lanes\n\nHuman-owned coordination file.\n")
    return {
        "base": base,
        "claims": claims,
        "home": home,
        "remote": remote,
        "root": root,
        "source": source,
        "uv": _fake_uv(tmp_path),
    }


def _create(fixture: dict, name: str = "lane-one", **overrides):
    arguments = {
        "lanes_root": fixture["root"],
        "home": fixture["home"],
        "lane": name,
        "source": fixture["source"],
        "branch": f"build/{name}",
        "base": fixture["base"],
        "claim_globs": (f"tools/{name}.py",),
        "owner": "fixture-owner",
        "session": "fixture-session",
        "clock": lambda: FIXED_NOW,
        "uv": str(fixture["uv"]),
    }
    arguments.update(overrides)
    return lane.create_lane(**arguments)


def _claims(fixture: dict) -> list[dict]:
    return lane._parse_claims(fixture["claims"].read_text())


def _commit(target: Path, relative: str = "work.txt") -> str:
    (target / relative).write_text("completed fixture\n")
    _git(target, "add", relative)
    _git(target, "commit", "-m", "fixture lane work")
    return _git(target, "rev-parse", "HEAD").stdout.strip()


def _status(fixture: dict, lane_name: str, head: str, *, state: str = "done") -> Path:
    row = next(row for row in _claims(fixture) if row["lane"] == lane_name)
    path = fixture["home"] / ".tae" / "out" / lane_name / "STATUS"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{state}\n"
        f"Lane: {lane_name}\n"
        f"Branch: {row['branch']}\n"
        f"Base: {row['base_sha']}\n"
        f"Head: {head}\n"
        "Summary: synthetic handoff\n"
    )
    return path


def _fake_uv(tmp_path: Path) -> Path:
    program = tmp_path / "fake-uv"
    program.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "mkdir -p \"$UV_PROJECT_ENVIRONMENT/bin\"\n"
        "touch \"$UV_PROJECT_ENVIRONMENT/bin/python\"\n"
        "chmod 755 \"$UV_PROJECT_ENVIRONMENT/bin/python\"\n"
    )
    program.chmod(0o700)
    return program


def test_create_uses_exact_base_public_identity_shared_environment_and_hook(tmp_path):
    fixture = _fixture(tmp_path)

    result = _create(fixture)

    target = fixture["root"] / "lane-one"
    assert _git(target, "rev-parse", "HEAD").stdout.strip() == fixture["base"]
    assert _git(target, "symbolic-ref", "--short", "HEAD").stdout.strip() == "build/lane-one"
    assert _git(target, "config", "--worktree", "--get", "user.email").stdout.strip() == (
        "fixture@example.com"
    )
    assert (target / ".venv").is_symlink()
    assert result["environment"]["kind"] == "shared-read-only"
    hook = Path(result["hook"]["path"])
    assert hook.read_bytes() == lane.HOOK_TEMPLATE.read_bytes()
    assert os.access(hook, os.X_OK)
    assert _git(target, "status", "--porcelain").stdout == ""
    assert _claims(fixture) == [result["claim"]]
    assert result["claim"]["claimed_at"] == "2026-10-18T18:05:00Z"


def test_create_reports_monotonic_setup_wall_time(tmp_path):
    fixture = _fixture(tmp_path)
    ticks = iter((100.0, 102.75))

    result = _create(fixture, timer=lambda: next(ticks))

    assert result["elapsed_seconds"] == 2.75
    assert result["environment"]["kind"] == "shared-read-only"


def test_same_lock_reuses_keyed_environment(tmp_path):
    fixture = _fixture(tmp_path)
    first = _create(fixture, "lane-one")
    second = _create(fixture, "lane-two")

    assert first["environment"]["lock_sha256"] == second["environment"]["lock_sha256"]
    assert first["environment"]["registry_key"] == second["environment"]["registry_key"]
    assert first["environment"]["selection"] == "built"
    assert second["environment"]["selection"] == "reused"
    assert (fixture["root"] / "lane-one" / ".venv").resolve() == (
        fixture["root"] / "lane-two" / ".venv"
    ).resolve()


def test_different_lock_builds_an_isolated_shared_environment(tmp_path):
    fixture = _fixture(tmp_path)
    old_base = fixture["base"]
    (fixture["source"] / "uv.lock").write_text("version = 2\n")
    _git(fixture["source"], "add", "uv.lock")
    _git(fixture["source"], "commit", "-m", "change lock fixture")
    fixture["base"] = old_base

    result = _create(fixture)

    target_venv = fixture["root"] / "lane-one" / ".venv"
    assert result["environment"]["kind"] == "shared-read-only"
    assert target_venv.is_symlink()
    assert (target_venv / "bin" / "python").is_file()


def test_shared_environment_is_registry_owned_read_only_and_audited(tmp_path):
    fixture = _fixture(tmp_path)
    result = _create(fixture)
    target = fixture["root"] / "lane-one"
    shared = Path(result["environment"]["registry_key"])
    interpreter = shared / "bin" / "python"

    assert shared.parent == fixture["root"] / ".shared-venvs"
    assert shared.is_dir() and not shared.is_symlink()
    assert target.joinpath(".venv").resolve() == shared
    assert interpreter.resolve().is_file() and os.access(interpreter, os.X_OK)
    assert not any(
        path.lstat().st_mode & 0o222
        for path in (shared, *shared.rglob("*"))
        if not path.is_symlink()
    )
    receipt = shared / "lane-environment-receipt.json"
    assert receipt.is_file()
    assert fixture["source"].joinpath(".venv").resolve() != shared

    head = _git(target, "rev-parse", "HEAD").stdout.strip()
    status = _status(fixture, "lane-one", head)
    interpreter.parent.chmod(0o755)
    interpreter.unlink()
    report = lane.audit_lane(
        lanes_root=fixture["root"],
        home=fixture["home"],
        lane="lane-one",
        status_path=status,
    )

    assert report["checks"]["environment_matches"] is False


def test_shared_environment_registry_refuses_symlink_escape(tmp_path):
    fixture = _fixture(tmp_path)
    outside = tmp_path / "outside-environments"
    outside.mkdir()
    (fixture["root"] / ".shared-venvs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(lane.LaneError, match="must be a real directory"):
        _create(fixture)

    assert list(outside.iterdir()) == []


def test_overlapping_active_claim_is_refused_before_worktree_creation(tmp_path):
    fixture = _fixture(tmp_path)
    _create(fixture, claim_globs=("tools/**",))

    with pytest.raises(lane.LaneError, match="overlaps active lane"):
        _create(
            fixture,
            "lane-two",
            claim_globs=("tools/lane.py",),
        )

    assert not (fixture["root"] / "lane-two").exists()
    assert [row["lane"] for row in _claims(fixture)] == ["lane-one"]


def test_legacy_claim_table_requires_complete_migration_and_blocks_overlap(tmp_path):
    fixture = _fixture(tmp_path)
    legacy = (
        "# Engine lanes\n\n"
        "| Lane | Clone / branch | Claims (only these files) |\n"
        "|---|---|---|\n"
        "| Historical lane (released) | old / old | `docs/old.md` |\n"
        "| Active platform lane | active / build/active | `tools/**` |\n"
    )
    fixture["claims"].write_text(legacy)

    with pytest.raises(lane.LaneError, match="legacy claims require"):
        _create(fixture, claim_globs=("tools/lane.py",))
    assert not (fixture["root"] / "lane-one").exists()

    legacy_rows = lane._legacy_claim_rows(legacy)
    by_label = {label: digest for digest, label in legacy_rows.items()}
    active_digest = by_label["Active platform lane"]
    manifest = {
        "legacy_sha256": lane._legacy_digest(legacy),
        "reviewed_rows": [
            {
                "claims": [],
                "expected_lane_count": 0,
                "row_label": "Historical lane (released)",
                "row_sha256": by_label["Historical lane (released)"],
                "state": "released",
            },
            {
                "claims": [
                    {
                        "base_sha": fixture["base"],
                        "branch": "build/active",
                        "claim_globs": ["tools/**"],
                        "lane": "active-platform",
                        "owner": "orchestrator",
                        "session": "legacy-migration",
                        "source": "source",
                    }
                ],
                "expected_lane_count": 1,
                "row_label": "Active platform lane",
                "row_sha256": active_digest,
                "state": "active",
            },
        ],
        "schema_version": lane.SCHEMA_VERSION,
    }
    manifest_path = tmp_path / "migration.json"
    manifest_path.write_text(json.dumps(manifest))

    result = lane.migrate_claims(
        lanes_root=fixture["root"],
        home=fixture["home"],
        manifest_path=manifest_path,
        clock=lambda: FIXED_NOW,
    )

    assert result == {"claim_count": 1, "legacy_row_count": 2, "migrated": True}

    with pytest.raises(lane.LaneError, match="overlaps active lane active-platform"):
        _create(fixture, claim_globs=("tools/lane.py",))
    assert not (fixture["root"] / "lane-one").exists()

    created = _create(fixture, "lane-two", claim_globs=("scratch/new.py",))

    assert created["claim"]["state"] == "active"


def test_reviewed_current_ledger_migration_expands_both_aggregate_rows(tmp_path):
    fixture = _fixture(tmp_path)
    snapshot = zlib.decompress(base64.b64decode(CURRENT_CLAIMS_ZLIB_B64))
    assert hashlib.sha256(snapshot).hexdigest() == lane.CURRENT_LEGACY_SHA256
    fixture["claims"].write_bytes(snapshot)
    _git(
        fixture["source"],
        "fetch",
        str(REPOSITORY_ROOT),
        lane.CURRENT_LEGACY_BASE,
    )
    migrated_lanes = {
        "b-platform",
        "b-release",
        "b-jobs",
        "b-catalog",
        "b-study",
        "r16-gen",
        "r16-raw",
    }
    for lane_name in migrated_lanes:
        (fixture["root"] / lane_name).symlink_to(
            fixture["source"], target_is_directory=True
        )

    result = lane.migrate_claims(
        lanes_root=fixture["root"],
        home=fixture["home"],
        current_ledger=True,
        clock=lambda: FIXED_NOW,
    )

    assert result == {"claim_count": 7, "legacy_row_count": 31, "migrated": True}
    rows = _claims(fixture)
    assert {row["lane"] for row in rows} == migrated_lanes
    counts = {}
    for row in rows:
        counts[row["legacy_row_sha256"]] = counts.get(row["legacy_row_sha256"], 0) + 1
    assert counts[lane.CURRENT_LEGACY_ROWS[-2][0]] == 5
    assert counts[lane.CURRENT_LEGACY_ROWS[-1][0]] == 2
    with pytest.raises(lane.LaneError, match="overlaps active lane b-platform"):
        _create(fixture, claim_globs=("tools/lane.py",))

    created = _create(fixture, "lane-new", claim_globs=("scratch/new.py",))

    assert created["claim"]["state"] == "active"


@pytest.mark.parametrize("kind", ["dirty", "unpushed", "stash"])
def test_existing_target_state_is_never_reused(tmp_path, kind):
    fixture = _fixture(tmp_path)
    target = fixture["root"] / "lane-one"
    _git(
        fixture["source"],
        "worktree",
        "add",
        "-b",
        "build/lane-one",
        str(target),
        fixture["base"],
    )
    if kind == "dirty":
        (target / "untracked.txt").write_text("fixture\n")
    elif kind == "unpushed":
        _commit(target)
    else:
        (target / "README.md").write_text("changed fixture\n")
        _git(target, "stash", "push", "-m", "fixture stash")

    with pytest.raises(lane.LaneError, match="target already exists") as error:
        _create(fixture)

    assert kind in str(error.value)


def test_partial_bootstrap_keeps_claim_and_resumes(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    original = lane._select_environment

    def fail_environment(*_args, **_kwargs):
        raise lane.LaneError("injected environment failure")

    monkeypatch.setattr(lane, "_select_environment", fail_environment)

    with pytest.raises(lane.LaneError, match="injected"):
        _create(fixture)

    assert (fixture["root"] / "lane-one").is_dir()
    assert _claims(fixture)[0]["state"] == "creating"
    with pytest.raises(lane.LaneError, match="overlaps active lane lane-one"):
        _create(fixture, "lane-two", claim_globs=("tools/lane-one.py",))

    monkeypatch.setattr(lane, "_select_environment", original)
    result = _create(fixture)

    assert result["claim"]["state"] == "active"
    assert _claims(fixture)[0]["state"] == "active"


@pytest.mark.parametrize(
    "crash_phase",
    ["reserved", "worktree", "environment_building", "before_activate", "active"],
)
def test_abrupt_create_termination_is_reserved_and_resumable(tmp_path, crash_phase):
    fixture = _fixture(tmp_path)

    class AbruptStop(BaseException):
        pass

    def stop_at(phase):
        if phase == crash_phase:
            raise AbruptStop(phase)

    with pytest.raises(AbruptStop, match=crash_phase):
        _create(fixture, phase_hook=stop_at)

    row = _claims(fixture)[0]
    assert row["state"] == ("active" if crash_phase == "active" else "creating")

    result = _create(fixture)

    assert result["claim"]["state"] == "active"
    assert _git(fixture["root"] / "lane-one", "rev-parse", "HEAD").stdout.strip() == (
        fixture["base"]
    )


def test_abort_marks_safe_creating_reservation_without_deleting_target(tmp_path):
    fixture = _fixture(tmp_path)

    class AbruptStop(BaseException):
        pass

    def stop_after_worktree(phase):
        if phase == "worktree":
            raise AbruptStop

    with pytest.raises(AbruptStop):
        _create(fixture, phase_hook=stop_after_worktree)
    target = fixture["root"] / "lane-one"

    result = lane.abort_lane(
        lanes_root=fixture["root"],
        home=fixture["home"],
        lane="lane-one",
        reason="fixture operator abort",
        clock=lambda: FIXED_NOW,
    )

    assert result["target_retained"] is True
    assert target.is_dir()
    assert _git(target, "rev-parse", "HEAD").stdout.strip() == fixture["base"]
    assert _claims(fixture)[0]["state"] == "aborted"
    with pytest.raises(lane.LaneError, match="aborted and cannot resume"):
        _create(fixture)


def test_concurrent_cli_creators_are_serialized_by_claim_lock(tmp_path):
    fixture = _fixture(tmp_path)
    environment = {
        **os.environ,
        "HOME": str(fixture["home"]),
        "PYTHONPATH": str(REPOSITORY_ROOT),
    }

    def command(name: str) -> list[str]:
        return [
            sys.executable,
            "-m",
            "tools.lane",
            "create",
            name,
            "--source",
            str(fixture["source"]),
            "--branch",
            f"build/{name}",
            "--base",
            fixture["base"],
            "--claim",
            "tools/shared.py",
            "--owner",
            "fixture-owner",
            "--session",
            name,
            "--uv",
            str(fixture["uv"]),
        ]

    first = subprocess.Popen(
        command("lane-one"),
        cwd=REPOSITORY_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    second = subprocess.Popen(
        command("lane-two"),
        cwd=REPOSITORY_ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    first.communicate(timeout=30)
    second.communicate(timeout=30)

    assert sorted((first.returncode, second.returncode)) == [0, 2]
    assert len([row for row in _claims(fixture) if row["state"] == "active"]) == 1


def test_release_refuses_unpushed_work_then_accepts_remote_handoff(tmp_path):
    fixture = _fixture(tmp_path)
    _create(fixture)
    target = fixture["root"] / "lane-one"
    head = _commit(target)
    status = _status(fixture, "lane-one", head)

    audit = lane.audit_lane(
        lanes_root=fixture["root"],
        home=fixture["home"],
        lane="lane-one",
        status_path=status,
    )
    assert audit["ok"] is False
    assert audit["checks"]["unpushed_free"] is False
    assert audit["unpushed_commit_count"] == 1
    with pytest.raises(lane.LaneError, match="unpushed_free"):
        lane.release_lane(
            lanes_root=fixture["root"],
            home=fixture["home"],
            lane="lane-one",
            status_path=status,
        )

    _git(target, "push", "-u", "origin", "HEAD")
    audit = lane.audit_lane(
        lanes_root=fixture["root"],
        home=fixture["home"],
        lane="lane-one",
        status_path=status,
    )
    released = lane.release_lane(
        lanes_root=fixture["root"],
        home=fixture["home"],
        lane="lane-one",
        status_path=status,
        clock=lambda: FIXED_NOW,
    )

    assert audit["ok"] is True
    assert audit["checks"]["unpushed_free"] is True
    assert audit["unpushed_commit_count"] == 0
    assert released["head_sha"] == head
    assert target.is_dir()
    row = _claims(fixture)[0]
    assert row["state"] == "released"
    assert row["released_at"] == "2026-10-18T18:05:00Z"


def test_release_rejects_stale_origin_and_unrelated_remote_advertisement(tmp_path):
    fixture = _fixture(tmp_path)
    _create(fixture)
    target = fixture["root"] / "lane-one"
    head = _commit(target)
    status = _status(fixture, "lane-one", head)
    branch_ref = "refs/heads/build/lane-one"
    _git(target, "push", "-u", "origin", "HEAD")
    _git(fixture["remote"], "update-ref", "-d", branch_ref)

    stale = lane.audit_lane(
        lanes_root=fixture["root"],
        home=fixture["home"],
        lane="lane-one",
        status_path=status,
    )

    assert stale["checks"]["unpushed_free"] is True
    assert stale["checks"]["handoff_remote_current"] is False
    assert stale["ok"] is False

    scratch = fixture["root"] / "scratch.git"
    _git(fixture["root"], "init", "--bare", str(scratch))
    _git(target, "remote", "add", "scratch", str(scratch))
    _git(target, "push", "scratch", f"HEAD:{branch_ref}")
    unrelated = lane.audit_lane(
        lanes_root=fixture["root"],
        home=fixture["home"],
        lane="lane-one",
        status_path=status,
    )

    assert unrelated["checks"]["unpushed_free"] is True
    assert unrelated["checks"]["handoff_remote_current"] is False
    with pytest.raises(lane.LaneError, match="handoff_remote_current"):
        lane.release_lane(
            lanes_root=fixture["root"],
            home=fixture["home"],
            lane="lane-one",
            status_path=status,
        )


def test_audit_and_release_reject_opaque_stash_subject(tmp_path):
    fixture = _fixture(tmp_path)
    _create(fixture)
    target = fixture["root"] / "lane-one"
    head = _commit(target)
    status = _status(fixture, "lane-one", head)
    _git(target, "push", "-u", "origin", "HEAD")
    (target / "README.md").write_text("hidden unpublished fixture\n")
    _git(target, "stash", "push", "-m", "temporary fixture")
    stash_commit = _git(target, "rev-parse", "refs/stash").stdout.strip()
    _git(target, "stash", "clear")
    _git(target, "stash", "store", "-m", "opaque receipt", stash_commit)

    report = lane.audit_lane(
        lanes_root=fixture["root"],
        home=fixture["home"],
        lane="lane-one",
        status_path=status,
    )

    assert report["checks"]["stash_free"] is False
    assert report["ok"] is False
    with pytest.raises(lane.LaneError, match="stash_free"):
        lane.release_lane(
            lanes_root=fixture["root"],
            home=fixture["home"],
            lane="lane-one",
            status_path=status,
        )


def test_abort_rejects_stash_from_prior_branch_with_opaque_subject(tmp_path):
    fixture = _fixture(tmp_path)
    source = fixture["source"]
    (source / "README.md").write_text("prior branch hidden fixture\n")
    _git(source, "stash", "push", "-m", "prior branch fixture")
    stash_commit = _git(source, "rev-parse", "refs/stash").stdout.strip()
    _git(source, "stash", "clear")
    _git(source, "stash", "store", "-m", "opaque prior receipt", stash_commit)

    class AbruptStop(BaseException):
        pass

    def stop_after_worktree(phase):
        if phase == "worktree":
            raise AbruptStop

    with pytest.raises(AbruptStop):
        _create(fixture, phase_hook=stop_after_worktree)

    with pytest.raises(lane.LaneError, match="not safe to abandon"):
        lane.abort_lane(
            lanes_root=fixture["root"],
            home=fixture["home"],
            lane="lane-one",
            reason="fixture abort must refuse hidden work",
        )
    assert _claims(fixture)[0]["state"] == "creating"


def test_release_refuses_dirty_tree_wrong_status_stash_store_and_process(tmp_path):
    fixture = _fixture(tmp_path)
    _create(fixture)
    target = fixture["root"] / "lane-one"
    head = _commit(target)
    status = _status(fixture, "lane-one", fixture["base"])
    (target / "README.md").write_text("stash fixture\n")
    _git(target, "stash", "push", "-m", "fixture stash", "--include-untracked")
    (target / "dirty.txt").write_text("fixture\n")
    store = target / "store"
    store.mkdir()
    (store / "protected.duckdb").write_text("fixture\n")
    sleeper = subprocess.Popen(["sleep", "30"], cwd=target)
    try:
        report = lane.audit_lane(
            lanes_root=fixture["root"],
            home=fixture["home"],
            lane="lane-one",
            status_path=status,
        )
        with pytest.raises(lane.LaneError, match="handoff audit failed"):
            lane.release_lane(
                lanes_root=fixture["root"],
                home=fixture["home"],
                lane="lane-one",
                status_path=status,
            )
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=5)

    assert report["checks"]["stash_free"] is False
    assert report["checks"]["store_free"] is False
    assert report["checks"]["running_process_free"] is False
    assert report["checks"]["status_head_matches"] is False
    assert _claims(fixture)[0]["state"] == "active"
    assert head != fixture["base"]


def test_running_process_is_found_when_script_but_not_cwd_is_in_lane(tmp_path):
    fixture = _fixture(tmp_path)
    _create(fixture)
    target = fixture["root"] / "lane-one"
    script = target / "hold.py"
    script.write_text("import time\ntime.sleep(30)\n")
    process = subprocess.Popen([sys.executable, str(script)], cwd=tmp_path)
    try:
        assert process.pid in lane._running_pids(target)
    finally:
        process.terminate()
        process.wait(timeout=5)


def test_live_checkout_symlink_and_non_public_identity_are_refused(tmp_path):
    fixture = _fixture(tmp_path)
    live = fixture["home"] / "trading-engine"
    live.mkdir()
    (fixture["root"] / "live-link").symlink_to(live, target_is_directory=True)

    with pytest.raises(lane.LaneError, match="live checkout"):
        _create(fixture, "live-link")
    private_email = "person" + "@" + "company" + ".invalid"
    with pytest.raises(lane.LaneError, match="commit_identity_email"):
        _create(fixture, email=private_email)


def test_create_never_invokes_publish_or_destructive_git_actions(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    calls = []
    original = lane._git

    def recording_git(repo, *args, **kwargs):
        calls.append(args)
        return original(repo, *args, **kwargs)

    monkeypatch.setattr(lane, "_git", recording_git)

    _create(fixture)

    forbidden = {"commit", "push", "merge", "rm"}
    assert not any(args and args[0] in forbidden for args in calls)
    assert not any(args[:2] == ("worktree", "remove") for args in calls)


@pytest.mark.parametrize(
    ("left", "right", "witness"),
    [
        ("*.py", "tools*", "tools.py"),
        ("file?.txt", "file[0-9].txt", "file1.txt"),
        ("[a-c]*.md", "*b.md", "b.md"),
        ("tools/**", "**/lane.py", "tools/nested/lane.py"),
        ("**/*.py", "tools/?ane.py", "tools/lane.py"),
    ],
)
def test_claim_matching_fails_safe_for_adversarial_intersections(left, right, witness):
    assert lane._exact_matches(left, witness)
    assert lane._exact_matches(right, witness)
    assert lane.claims_overlap(left, right) is True


def test_claim_matching_proves_only_sound_disjoint_paths():
    assert lane.claims_overlap("tools/**", "tools/lane.py") is True
    assert lane.claims_overlap("tools/*.py", "tools/lane.py") is True
    assert lane.claims_overlap("tools/lane.py", "tests/test_lane.py") is False
    assert lane.claims_overlap("tools/a.py", "tools/b.py") is False
    assert lane.claims_overlap("tools/*.py", "docs/*.py") is False


def test_exact_base_and_claim_block_validation_fail_closed(tmp_path):
    fixture = _fixture(tmp_path)

    with pytest.raises(lane.LaneError, match="full lowercase"):
        _create(fixture, base="HEAD")
    fixture["claims"].write_text(lane.CLAIMS_START + "\n{broken\n" + lane.CLAIMS_END)
    with pytest.raises(lane.LaneError, match="malformed structured JSON"):
        _create(fixture)


def test_environment_receipt_is_bound_to_current_lock(tmp_path):
    fixture = _fixture(tmp_path)
    _create(fixture)
    target = fixture["root"] / "lane-one"
    head = _commit(target)
    status = _status(fixture, "lane-one", head)
    (target / "uv.lock").write_text("tampered fixture\n")
    _git(target, "add", "uv.lock")
    _git(target, "commit", "-m", "tamper lock fixture")
    _status(fixture, "lane-one", _git(target, "rev-parse", "HEAD").stdout.strip())

    report = lane.audit_lane(
        lanes_root=fixture["root"],
        home=fixture["home"],
        lane="lane-one",
        status_path=status,
    )

    assert report["checks"]["environment_matches"] is False
