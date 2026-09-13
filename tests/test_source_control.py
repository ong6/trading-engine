"""Read-only Git tracking projection for unattended generated-data sync."""

import subprocess
from contextlib import contextmanager
from subprocess import CompletedProcess

import pytest

from server import source_control


def _completed(stdout: str = "", returncode: int = 0, stderr: str = ""):
    return CompletedProcess((), returncode, stdout=stdout, stderr=stderr)


HEAD_OBJECT = "b" * 40
UPSTREAM_OBJECT = "a" * 40


def _tracked_observation(
    *,
    branch="main",
    remote="origin",
    merge_ref="refs/heads/main",
    upstream_ref="refs/remotes/origin/main",
    upstream="origin/main",
    upstream_object=UPSTREAM_OBJECT,
    head_object=HEAD_OBJECT,
):
    return (
        _completed(f"{branch}\n"),
        _completed(f"{remote}\n"),
        _completed(f"{merge_ref}\n"),
        _completed(),
        _completed(f"{upstream_ref}\x00{upstream}\n"),
        _completed(f"{upstream_object}\n"),
        _completed(f"{head_object}\n"),
    )


def _tracked_responses(*tail):
    return (
        *_tracked_observation(),
        *tail,
        *_tracked_observation(),
    )


@pytest.mark.parametrize(
    ("counts", "status"),
    [
        ("0\t0\n", "current"),
        ("2\t0\n", "unpushed"),
        ("0\t3\n", "behind"),
        ("2\t3\n", "diverged"),
        (f"{source_control.PUBLIC_TRACKING_COUNT_MAX}\t0\n", "unpushed"),
    ],
)
def test_source_control_reports_cached_tracking_relation(monkeypatch, tmp_path, counts, status):
    responses = iter(_tracked_responses(_completed(counts)))
    calls = []

    def fake_git(repo_root, *args):
        calls.append(args)
        return next(responses)

    monkeypatch.setattr(source_control, "_git", fake_git)

    result = source_control.status(repo_root=tmp_path)

    assert result == {
        "status": status,
        "reason": None,
        "branch": "main",
        "remote": "origin",
        "upstream": "origin/main",
        "ahead": int(counts.split()[0]),
        "behind": int(counts.split()[1]),
        "network_checked": False,
    }
    assert all(call[0] not in {"fetch", "ls-remote", "push"} for call in calls)


def test_source_control_reports_branch_without_upstream_as_local_only(monkeypatch, tmp_path):
    responses = iter(
        (
            _completed("main\n"),
            _completed(returncode=1),
            _completed(returncode=1),
            _completed("main\n"),
            _completed(returncode=1),
            _completed(returncode=1),
        )
    )
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    result = source_control.status(repo_root=tmp_path)

    assert result["status"] == "local-only"
    assert result["reason"] == "no-upstream"
    assert result["branch"] == "main"
    assert result["remote"] is None
    assert result["network_checked"] is False


@pytest.mark.parametrize(
    "failed",
    [
        _completed(returncode=2, stderr="usage error\n"),
        _completed(returncode=128, stderr="fatal: bad config\n"),
        _completed("unexpected\n", returncode=1),
        _completed(returncode=1, stderr="unexpected\n"),
    ],
)
def test_source_control_does_not_misclassify_config_failure_as_no_upstream(
    monkeypatch, tmp_path, failed
):
    responses = iter(
        (
            _completed("main\n"),
            failed,
            _completed(returncode=1),
        )
    )
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "git-unavailable"
    )


@pytest.mark.parametrize("missing_index", [0, 1])
def test_source_control_rejects_partial_tracking_configuration(
    monkeypatch, tmp_path, missing_index
):
    configured = [_completed("origin\n"), _completed("refs/heads/main\n")]
    configured[missing_index] = _completed(returncode=1)
    responses = iter((_completed("main\n"), *configured))
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "tracking-identity-invalid"
    )


def test_source_control_reports_missing_tracking_ref_as_local_only(monkeypatch, tmp_path):
    responses = iter(
        (
            _completed("main\n"),
            _completed("origin\n"),
            _completed("refs/heads/main\n"),
            _completed(),
            _completed("refs/remotes/origin/main\x00origin/main\n"),
            _completed(returncode=1),
            _completed("main\n"),
            _completed("origin\n"),
            _completed("refs/heads/main\n"),
            _completed(),
            _completed("refs/remotes/origin/main\x00origin/main\n"),
            _completed(returncode=1),
        )
    )
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    result = source_control.status(repo_root=tmp_path)

    assert result["status"] == "local-only"
    assert result["reason"] == "tracking-ref-missing"
    assert result["branch"] == "main"
    assert result["remote"] == "origin"


@pytest.mark.parametrize(
    "ref_check",
    [
        _completed(returncode=1),
        _completed("unexpected\n"),
        _completed(stderr="unexpected\n"),
    ],
)
def test_source_control_rejects_invalid_or_noisy_merge_ref(
    monkeypatch, tmp_path, ref_check
):
    responses = iter(
        (
            _completed("main\n"),
            _completed("origin\n"),
            _completed("refs/heads/bad ref\n"),
            ref_check,
        )
    )
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "tracking-identity-invalid"
    )


def test_source_control_rejects_unexpected_upstream_resolution_failure(monkeypatch, tmp_path):
    responses = iter(
        (
            _completed("main\n"),
            _completed("origin\n"),
            _completed("refs/heads/main\n"),
            _completed(),
            _completed(returncode=1, stderr="unexpected\n"),
        )
    )
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "git-unavailable"
    )


@pytest.mark.parametrize(
    "object_result",
    [
        _completed(returncode=2, stderr="object database failed\n"),
        _completed("not-an-object-id\n"),
        _completed("a" * 40 + "\n", stderr="unexpected\n"),
    ],
)
def test_source_control_rejects_failed_or_malformed_upstream_object_probe(
    monkeypatch, tmp_path, object_result
):
    responses = iter(
        (
            _completed("main\n"),
            _completed("origin\n"),
            _completed("refs/heads/main\n"),
            _completed(),
            _completed("refs/remotes/origin/main\x00origin/main\n"),
            object_result,
        )
    )
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "git-unavailable"
    )


@pytest.mark.parametrize(
    "counts",
    [
        "bad\n",
        "-1\t0\n",
        "1\n",
        f"{source_control.PUBLIC_TRACKING_COUNT_MAX + 1}\t0\n",
        f"0\t{source_control.PUBLIC_TRACKING_COUNT_MAX + 1}\n",
        "0 0\n",
        "0\t0",
        "0\t0\n\n",
        "0\t0\t0\n",
        "+0\t0\n",
        "٠\t0\n",
        " 0\t0\n",
        "0\t0 \n",
    ],
)
def test_source_control_rejects_invalid_tracking_counts(monkeypatch, tmp_path, counts):
    responses = iter(_tracked_responses(_completed(counts)))
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    result = source_control.status(repo_root=tmp_path)

    assert result["status"] == "invalid"
    assert result["reason"] == "tracking-count-invalid"


@pytest.mark.parametrize(
    "failure",
    [
        _completed(returncode=1),
        _completed(returncode=128, stderr="object database failed\n"),
        _completed("0\t0\n", stderr="unexpected\n"),
    ],
)
def test_source_control_distinguishes_count_command_failure_from_invalid_output(
    monkeypatch, tmp_path, failure
):
    responses = iter(_tracked_responses(failure))
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "git-unavailable"
    )


def test_source_control_fails_closed_when_git_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: None)

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "git-unavailable"
    )


@pytest.mark.parametrize("unavailable_call", range(1, 16))
def test_source_control_fails_closed_when_later_git_probe_is_unavailable(
    monkeypatch, tmp_path, unavailable_call
):
    responses = iter(_tracked_responses(_completed("0\t0\n")))
    call_count = 0

    def fake_git(repo_root, *args):
        nonlocal call_count
        call_count += 1
        response = next(responses)
        return None if call_count == unavailable_call else response

    monkeypatch.setattr(source_control, "_git", fake_git)

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "git-unavailable"
    )


def test_source_control_fails_closed_without_symbolic_branch(monkeypatch, tmp_path):
    monkeypatch.setattr(
        source_control,
        "_git",
        lambda repo_root, *args: _completed(returncode=1),
    )

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "branch-unavailable"
    )


@pytest.mark.parametrize(
    "result",
    [
        _completed(returncode=128, stderr="fatal: not a repository\n"),
        _completed(returncode=1, stderr="unexpected\n"),
        _completed("unexpected\n", returncode=1),
        _completed("main\n", stderr="unexpected\n"),
    ],
)
def test_source_control_distinguishes_branch_probe_failure_from_detached_head(
    monkeypatch, tmp_path, result
):
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: result)

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "git-unavailable"
    )


@pytest.mark.parametrize("noisy_index", [0, 1])
def test_source_control_rejects_diagnostics_from_successful_config_read(
    monkeypatch, tmp_path, noisy_index
):
    configured = [_completed("origin\n"), _completed("refs/heads/main\n")]
    configured[noisy_index] = _completed(configured[noisy_index].stdout, stderr="unexpected\n")
    responses = iter((_completed("main\n"), *configured))
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "git-unavailable"
    )


@pytest.mark.parametrize(
    "branch",
    ["main\nother\n", "main\x00suffix\n", "x" * (source_control.PUBLIC_IDENTITY_MAX_CHARS + 1)],
)
def test_source_control_rejects_malformed_public_branch(monkeypatch, tmp_path, branch):
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: _completed(branch))

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "branch-unavailable"
    )


@pytest.mark.parametrize(
    ("remote", "merge_ref", "upstream"),
    [
        ("\n", "refs/heads/main\n", "refs/remotes/origin/main\x00origin/main\n"),
        (
            "origin\nmirror\n",
            "refs/heads/main\n",
            "refs/remotes/origin/main\x00origin/main\n",
        ),
        (
            "origin\n",
            "refs/heads/main\x00suffix\n",
            "refs/remotes/origin/main\x00origin/main\n",
        ),
        ("origin\n", "refs/heads/main\n", "origin/main\nother\n"),
        (
            "x" * (source_control.PUBLIC_IDENTITY_MAX_CHARS + 1),
            "refs/heads/main\n",
            "refs/remotes/origin/main\x00origin/main\n",
        ),
    ],
)
def test_source_control_rejects_malformed_tracking_identity(
    monkeypatch, tmp_path, remote, merge_ref, upstream
):
    responses = iter(
        (
            _completed("main\n"),
            _completed(remote),
            _completed(merge_ref),
            _completed(),
            _completed(upstream),
            _completed("a" * 40 + "\n"),
        )
    )
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "tracking-identity-invalid"
    )


def test_source_control_accepts_exact_public_identity_budget(monkeypatch, tmp_path):
    branch = "b" * source_control.PUBLIC_IDENTITY_MAX_CHARS
    remote = "r" * source_control.PUBLIC_IDENTITY_MAX_CHARS
    upstream = "u" * source_control.PUBLIC_IDENTITY_MAX_CHARS
    responses = iter(
        (
            *_tracked_observation(branch=branch, remote=remote, upstream=upstream),
            _completed("0\t0\n"),
            *_tracked_observation(branch=branch, remote=remote, upstream=upstream),
        )
    )
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    result = source_control.status(repo_root=tmp_path)

    assert result["status"] == "current"
    assert result["branch"] == branch
    assert result["remote"] == remote
    assert result["upstream"] == upstream


def test_source_control_uses_structured_git_tracking_without_network(tmp_path):
    def run(*args):
        subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    subprocess.run(
        ["git", "init", "-q", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    run("config", "user.email", "test@example.invalid")
    run("config", "user.name", "Test")
    (tmp_path / "tracked").write_text("content\n")
    run("add", "tracked")
    run("commit", "-qm", "initial")
    run("branch", "-M", "main")
    run("remote", "add", "origin", "/no/network")
    run("config", "branch.main.remote", "origin")
    run("config", "branch.main.merge", "refs/heads/main")

    missing = source_control.status(repo_root=tmp_path)
    assert missing["status"] == "local-only"
    assert missing["reason"] == "tracking-ref-missing"
    assert missing["remote"] == "origin"

    run("update-ref", "refs/remotes/origin/main", "HEAD")
    assert source_control.status(repo_root=tmp_path)["status"] == "current"


def test_source_control_counts_pinned_objects_but_displays_short_name(monkeypatch, tmp_path):
    responses = iter(_tracked_responses(_completed("0\t0\n")))
    calls = []

    def fake_git(repo_root, *args):
        calls.append(args)
        return next(responses)

    monkeypatch.setattr(source_control, "_git", fake_git)

    result = source_control.status(repo_root=tmp_path)

    assert result["upstream"] == "origin/main"
    assert (
        "rev-list",
        "--left-right",
        "--count",
        f"{HEAD_OBJECT}...{UPSTREAM_OBJECT}",
    ) in calls


@pytest.mark.parametrize(
    "changed_observation",
    [
        _tracked_observation(branch="other"),
        _tracked_observation(remote="mirror"),
        _tracked_observation(merge_ref="refs/heads/other"),
        _tracked_observation(
            upstream_ref="refs/remotes/origin/other", upstream="origin/other"
        ),
        _tracked_observation(upstream_object="c" * 40),
        _tracked_observation(head_object="d" * 40),
    ],
)
def test_source_control_rejects_changed_repository_observation(
    monkeypatch, tmp_path, changed_observation
):
    responses = iter(
        (*_tracked_observation(), _completed("0\t0\n"), *changed_observation)
    )
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "git-unavailable"
    )


def test_source_control_rejects_no_upstream_becoming_tracked(monkeypatch, tmp_path):
    responses = iter(
        (
            _completed("main\n"),
            _completed(returncode=1),
            _completed(returncode=1),
            *_tracked_observation(),
        )
    )
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "git-unavailable"
    )


def test_source_control_rejects_missing_tracking_ref_appearing(monkeypatch, tmp_path):
    missing = (
        _completed("main\n"),
        _completed("origin\n"),
        _completed("refs/heads/main\n"),
        _completed(),
        _completed("refs/remotes/origin/main\x00origin/main\n"),
        _completed(returncode=1),
    )
    responses = iter((*missing, *_tracked_observation()))
    monkeypatch.setattr(source_control, "_git", lambda repo_root, *args: next(responses))

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "git-unavailable"
    )


def test_source_control_detects_concurrent_tracking_ref_change(tmp_path, monkeypatch):
    def run(*args):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    subprocess.run(
        ["git", "init", "-q", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    run("config", "user.email", "test@example.invalid")
    run("config", "user.name", "Test")
    (tmp_path / "tracked").write_text("initial\n")
    run("add", "tracked")
    run("commit", "-qm", "initial")
    run("branch", "-M", "main")
    run("remote", "add", "origin", "/no/network")
    run("config", "branch.main.remote", "origin")
    run("config", "branch.main.merge", "refs/heads/main")
    run("update-ref", "refs/remotes/origin/main", "HEAD")
    initial_upstream = run("rev-parse", "refs/remotes/origin/main").stdout.strip()
    (tmp_path / "tracked").write_text("changed\n")
    run("add", "tracked")
    run("commit", "-qm", "second")

    tracking_counts = source_control._tracking_counts

    def move_ref_after_count(repo_root, head_object, upstream_object):
        assert upstream_object == initial_upstream
        result = tracking_counts(repo_root, head_object, upstream_object)
        run("update-ref", "refs/remotes/origin/main", "HEAD")
        return result

    monkeypatch.setattr(source_control, "_tracking_counts", move_ref_after_count)

    assert source_control.status(repo_root=tmp_path) == source_control.invalid_status(
        "git-unavailable"
    )


def test_source_control_runs_inside_one_command_budget(monkeypatch, tmp_path):
    events = []

    @contextmanager
    def fake_budget():
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    def fake_status(repo_root):
        assert repo_root == tmp_path
        events.append("status")
        return {"status": "current"}

    monkeypatch.setattr(source_control, "command_budget", fake_budget)
    monkeypatch.setattr(source_control, "_status", fake_status)

    assert source_control.status(repo_root=tmp_path) == {"status": "current"}
    assert events == ["enter", "status", "exit"]


def test_source_control_status_helpers_reject_undocumented_reasons():
    with pytest.raises(ValueError, match="unknown source-control invalid reason"):
        source_control.invalid_status("invented")
    with pytest.raises(ValueError, match="unknown source-control local-only reason"):
        source_control._local_only_status("main", "invented")
