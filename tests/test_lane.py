"""Temporary-repository tests for exact-base lane coordination."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools import lane

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXED_NOW = datetime(2026, 10, 18, 18, 5, tzinfo=UTC)


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


def test_same_lock_reuses_keyed_environment(tmp_path):
    fixture = _fixture(tmp_path)
    first = _create(fixture, "lane-one")
    second = _create(fixture, "lane-two")

    assert first["environment"]["lock_sha256"] == second["environment"]["lock_sha256"]
    assert first["environment"]["registry_key"] == second["environment"]["registry_key"]
    assert (fixture["root"] / "lane-one" / ".venv").resolve() == (
        fixture["root"] / "lane-two" / ".venv"
    ).resolve()


def test_different_lock_creates_private_frozen_environment(tmp_path):
    fixture = _fixture(tmp_path)
    old_base = fixture["base"]
    (fixture["source"] / "uv.lock").write_text("version = 2\n")
    _git(fixture["source"], "add", "uv.lock")
    _git(fixture["source"], "commit", "-m", "change lock fixture")
    fixture["base"] = old_base

    result = _create(fixture, uv=str(_fake_uv(tmp_path)))

    target_venv = fixture["root"] / "lane-one" / ".venv"
    assert result["environment"]["kind"] == "private-frozen"
    assert target_venv.is_dir()
    assert not target_venv.is_symlink()
    assert (target_venv / "bin" / "python").is_file()


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


def test_partial_bootstrap_is_retained_without_claim(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)

    def fail_environment(*_args, **_kwargs):
        raise lane.LaneError("injected environment failure")

    monkeypatch.setattr(lane, "_select_environment", fail_environment)

    with pytest.raises(lane.LaneError, match="injected"):
        _create(fixture)

    assert (fixture["root"] / "lane-one").is_dir()
    assert _claims(fixture) == []


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


def test_release_audits_status_and_keeps_unpushed_worktree(tmp_path):
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
    released = lane.release_lane(
        lanes_root=fixture["root"],
        home=fixture["home"],
        lane="lane-one",
        status_path=status,
        clock=lambda: FIXED_NOW,
    )

    assert audit["ok"] is True
    assert audit["unpushed_commit_count"] == 1
    assert released["head_sha"] == head
    assert target.is_dir()
    row = _claims(fixture)[0]
    assert row["state"] == "released"
    assert row["released_at"] == "2026-10-18T18:05:00Z"


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


def test_claim_matching_distinguishes_disjoint_paths_and_fails_safe_for_globs():
    assert lane.claims_overlap("tools/**", "tools/lane.py") is True
    assert lane.claims_overlap("tools/*.py", "tools/lane.py") is True
    assert lane.claims_overlap("tools/lane.py", "tests/test_lane.py") is False
    assert lane.claims_overlap("tools/a.py", "tools/b.py") is False


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
