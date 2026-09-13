"""Git synchronization policy: local commits do not require a remote."""

import json
import subprocess
from subprocess import CompletedProcess

from engine import sync


def test_commit_message_prefers_explicit_screen_date(monkeypatch, tmp_path):
    meta = tmp_path / "_meta.json"
    meta.write_text(
        json.dumps(
            {
                "screen_date": "2026-09-04",
                "last_screen": "2026-09-07T22:30:00+00:00",
                "passing_count": 588,
                "new_today_count": 59,
            }
        )
    )
    monkeypatch.setattr(sync, "META_PATH", meta)

    assert sync._commit_message() == "screen: 2026-09-04 (588 passing, 59 new)"


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "data").mkdir()
    (repo / "data" / "report.json").write_text('{"version": 1}\n')
    (repo / "README.md").write_text("initial\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "sync test")
    _git(repo, "config", "user.email", "sync@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


def test_upstream_returns_configured_tracking_ref(monkeypatch):
    responses = iter(
        [
            CompletedProcess((), 0, stdout="main\n", stderr=""),
            CompletedProcess((), 0, stdout="origin\n", stderr=""),
            CompletedProcess((), 0, stdout="refs/heads/main\n", stderr=""),
            CompletedProcess((), 0, stdout="git@example/repo.git\n", stderr=""),
            CompletedProcess((), 0, stdout="origin/main\n", stderr=""),
        ]
    )
    monkeypatch.setattr(
        sync,
        "_git",
        lambda *args: next(responses),
    )
    assert sync._upstream() == sync.Upstream("origin", "main", "origin/main")


def test_upstream_ignores_stale_remote_without_tracking_branch(monkeypatch):
    responses = iter(
        [
            CompletedProcess((), 0, stdout="main\n", stderr=""),
            CompletedProcess((), 0, stdout="origin\n", stderr=""),
            CompletedProcess((), 0, stdout="refs/heads/main\n", stderr=""),
            CompletedProcess((), 0, stdout="git@example/repo.git\n", stderr=""),
            CompletedProcess((), 1, stdout="", stderr="missing upstream ref"),
        ]
    )
    monkeypatch.setattr(
        sync,
        "_git",
        lambda *args: next(responses),
    )
    assert sync._upstream() is None


def test_upstream_requires_both_tracking_config_values(monkeypatch):
    responses = iter(
        [
            CompletedProcess((), 0, stdout="main\n", stderr=""),
            CompletedProcess((), 1, stdout="", stderr="missing remote"),
            CompletedProcess((), 1, stdout="", stderr="missing merge"),
        ]
    )
    monkeypatch.setattr(sync, "_git", lambda *args: next(responses))
    assert sync._upstream() is None


def test_upstream_rejects_missing_configured_remote(monkeypatch):
    responses = iter(
        [
            CompletedProcess((), 0, stdout="main\n", stderr=""),
            CompletedProcess((), 0, stdout="gone\n", stderr=""),
            CompletedProcess((), 0, stdout="refs/heads/main\n", stderr=""),
            CompletedProcess((), 2, stdout="", stderr="No such remote"),
        ]
    )
    monkeypatch.setattr(sync, "_git", lambda *args: next(responses))
    assert sync._upstream() is None


def test_upstream_supports_local_dot_remote(monkeypatch):
    responses = iter(
        [
            CompletedProcess((), 0, stdout="topic\n", stderr=""),
            CompletedProcess((), 0, stdout=".\n", stderr=""),
            CompletedProcess((), 0, stdout="refs/heads/main\n", stderr=""),
            CompletedProcess((), 0, stdout="main\n", stderr=""),
        ]
    )
    monkeypatch.setattr(sync, "_git", lambda *args: next(responses))
    assert sync._upstream() == sync.Upstream(".", "main", "main")


def test_sync_pushes_explicit_upstream_despite_pushremote(monkeypatch, tmp_path):
    calls = []

    def fake_git(*args):
        calls.append(args)
        if args == ("diff", "--cached", "--name-only", "--", "data/"):
            return CompletedProcess(args, 0, stdout="data/report.json\n", stderr="")
        return CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_git", fake_git)
    monkeypatch.setattr(sync, "_rebase_in_progress", lambda: None)
    monkeypatch.setattr(
        sync,
        "_upstream",
        lambda: sync.Upstream("origin", "main", "refs/remotes/origin/main"),
    )
    monkeypatch.setattr("sys.argv", ["sync.py"])

    assert sync.main() == 0
    assert any(args[:2] == ("commit", "--only") and args[-2:] == ("--", "data/")
               for args in calls)
    assert ("push", "origin", "HEAD:refs/heads/main") in calls
    assert ("push",) not in calls


def test_sync_refuses_preexisting_staged_work(monkeypatch):
    calls = []

    def fake_git(*args):
        calls.append(args)
        if args == ("diff", "--cached", "--name-only"):
            return CompletedProcess(args, 0, stdout="README.md\n", stderr="")
        return CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_git", fake_git)
    monkeypatch.setattr(sync, "_rebase_in_progress", lambda: None)
    monkeypatch.setattr("sys.argv", ["sync.py"])

    assert sync.main() == 1
    assert not any(args[0] in {"add", "commit", "push"} for args in calls)


def test_sync_dry_run_restores_only_its_data_path(monkeypatch):
    calls = []

    def fake_git(*args):
        calls.append(args)
        if args == ("diff", "--cached", "--name-only", "--", "data/"):
            return CompletedProcess(args, 0, stdout="data/report.json\n", stderr="")
        return CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_git", fake_git)
    monkeypatch.setattr(sync, "_rebase_in_progress", lambda: None)
    monkeypatch.setattr("sys.argv", ["sync.py", "--dry-run"])

    assert sync.main() == 0
    assert ("add", "--", "data/") in calls
    assert ("reset", "--quiet", "--", "data/") in calls
    assert not any(args[0] in {"commit", "push"} for args in calls)


def test_sync_commit_failure_restores_its_data_path(monkeypatch):
    calls = []

    def fake_git(*args):
        calls.append(args)
        if args == ("diff", "--cached", "--name-only", "--", "data/"):
            return CompletedProcess(args, 0, stdout="data/report.json\n", stderr="")
        if args[:2] == ("commit", "--only"):
            return CompletedProcess(args, 1, stdout="", stderr="hook rejected commit")
        return CompletedProcess(args, 0, stdout="", stderr="")

    monkeypatch.setattr(sync, "_git", fake_git)
    monkeypatch.setattr(sync, "_rebase_in_progress", lambda: None)
    monkeypatch.setattr("sys.argv", ["sync.py"])

    assert sync.main() == 1
    assert ("reset", "--quiet", "--", "data/") in calls
    assert not any(args[0] == "push" for args in calls)


def test_sync_real_git_commits_only_data_and_preserves_unstaged_code(monkeypatch, tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "data" / "report.json").write_text('{"version": 2}\n')
    (repo / "README.md").write_text("operator edit\n")
    monkeypatch.setattr(sync, "REPO_ROOT", repo)
    monkeypatch.setattr(sync, "META_PATH", repo / "data" / "missing-meta.json")
    monkeypatch.setattr("sys.argv", ["sync.py"])

    assert sync.main() == 0
    assert _git(repo, "show", "--name-only", "--format=", "HEAD") == "data/report.json"
    assert _git(repo, "show", "HEAD:data/report.json") == '{"version": 2}'
    assert _git(repo, "show", "HEAD:README.md") == "initial"
    assert _git(repo, "diff", "--name-only") == "README.md"
    assert _git(repo, "diff", "--cached", "--name-only") == ""


def test_sync_real_git_refuses_staged_operator_work_without_touching_data(monkeypatch, tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "data" / "report.json").write_text('{"version": 2}\n')
    (repo / "README.md").write_text("operator edit\n")
    _git(repo, "add", "README.md")
    before = _git(repo, "diff", "--cached", "--binary")
    monkeypatch.setattr(sync, "REPO_ROOT", repo)
    monkeypatch.setattr(sync, "META_PATH", repo / "data" / "missing-meta.json")
    monkeypatch.setattr("sys.argv", ["sync.py"])

    assert sync.main() == 1
    assert _git(repo, "rev-list", "--count", "HEAD") == "1"
    assert _git(repo, "diff", "--cached", "--binary") == before
    assert _git(repo, "diff", "--name-only") == "data/report.json"
