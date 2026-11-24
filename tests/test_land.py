"""tools/land.py merges a branch into fresh main in a lane, verifies it and pushes on request."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tools import land

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
FAKE = """#!/usr/bin/env bash
echo "$*" >> "${LAND_LOG:?}"
case "$*" in
  *"tools.repin --check"*) exit "${REPIN_CHECK:-0}" ;;
  *"pytest"*) exit "${SUITE_EXIT:-0}" ;;
esac
exit 0
"""


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


def _commit(repo: Path, name: str, text: str) -> str:
    (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def lanes(tmp_path: Path, monkeypatch):
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "checkout", "-q", "-b", "main")
    (work / ".gitignore").write_text(".venv/\n")
    _commit(work, "base.txt", "base\n")
    _git(work, "push", "-q", "origin", "main")
    _git(work, "checkout", "-q", "-b", "feature")
    _commit(work, "feature.txt", "feature\n")
    _git(work, "push", "-q", "origin", "feature")
    lane = tmp_path / "lane"
    _git(tmp_path, "clone", "-q", str(origin), str(lane))
    bin_dir = tmp_path / "bin"
    for path in (lane / ".venv/bin/python", bin_dir / "uv"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(FAKE)
        path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("LAND_LOG", str(tmp_path / "log"))
    return {"origin": origin, "work": work, "lane": lane, "log": tmp_path / "log"}


def test_lands_and_pushes_after_every_check(lanes):
    assert land.main(["feature", "--lane", str(lanes["lane"]), "--push"]) == 0
    assert (lanes["lane"] / "feature.txt").exists()
    assert _git(lanes["origin"], "rev-parse", "main") == _git(lanes["lane"], "rev-parse", "HEAD")
    calls = lanes["log"].read_text().splitlines()
    assert [call.split()[1] for call in calls if call.startswith("-m")] == [
        "tools.repin", "tools.affected_tests", "pytest"]


def test_the_environment_is_synced_after_the_merge(lanes):
    uv = lanes["lane"].parent / "bin/uv"
    uv.write_text('#!/usr/bin/env bash\necho "sync sees feature: $(cat feature.txt 2>/dev/null)" '
                  '>> "${LAND_LOG:?}"\n')
    assert land.main(["feature", "--lane", str(lanes["lane"])]) == 0
    assert "sync sees feature: feature" in lanes["log"].read_text().splitlines()


def test_stops_before_push_without_flag_or_when_a_check_fails(lanes, monkeypatch):
    before = _git(lanes["origin"], "rev-parse", "main")
    assert land.main(["feature", "--lane", str(lanes["lane"])]) == 0
    assert _git(lanes["origin"], "rev-parse", "main") == before
    monkeypatch.setenv("SUITE_EXIT", "1")
    assert land.main(["feature", "--lane", str(lanes["lane"]), "--push"]) == 2
    assert _git(lanes["origin"], "rev-parse", "main") == before


def test_a_needed_revision_requires_a_reason(lanes, monkeypatch, tmp_path):
    monkeypatch.setenv("REPIN_CHECK", "2")
    assert land.main(["feature", "--lane", str(lanes["lane"]), "--push"]) == 2
    reason = tmp_path / "reason.txt"
    reason.write_text("the change is safe.\n")
    assert land.main(["feature", "--lane", str(lanes["lane"]), "--reason-file",
                      str(reason)]) == 0
    assert f"tools.repin --reason-file {reason}" in lanes["log"].read_text()


def test_a_conflict_aborts_the_merge(lanes):
    _git(lanes["work"], "checkout", "-q", "main")
    _commit(lanes["work"], "feature.txt", "main side\n")
    _git(lanes["work"], "push", "-q", "origin", "main")
    assert land.main(["feature", "--lane", str(lanes["lane"]), "--push"]) == 2
    assert not (lanes["lane"] / ".git/MERGE_HEAD").exists()
