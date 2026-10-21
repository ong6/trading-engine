"""Synthetic-repository tests for the public hygiene gate."""

from __future__ import annotations

import io
import os
import subprocess
from pathlib import Path

import pytest

from tools import public_hygiene

PUBLIC_NAME = "Fixture Author"
PUBLIC_EMAIL = "fixture@example.com"


def _run(root: Path, *args: str, env: dict[str, str] | None = None, check: bool = True):
    return subprocess.run(
        [*args],
        cwd=root,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _git(root: Path, *args: str, env: dict[str, str] | None = None, check: bool = True):
    return _run(
        root,
        "git",
        "-c",
        "core.hooksPath=/dev/null",
        *args,
        env=env,
        check=check,
    )


def _repository(tmp_path: Path) -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(remote))
    root = tmp_path / "work"
    _git(tmp_path, "clone", str(remote), str(root))
    _git(root, "config", "user.name", PUBLIC_NAME)
    _git(root, "config", "user.email", PUBLIC_EMAIL)
    (root / "README.md").write_text("public fixture\n")
    _git(root, "add", "README.md")
    _git(root, "commit", "-m", "initial fixture")
    _git(root, "push", "-u", "origin", "HEAD")
    return root, remote


def _commit(root: Path, message: str = "fixture change", *, env=None) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-m", message, env=env)
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def _rules(findings: set[public_hygiene.Finding]) -> set[str]:
    return {finding.rule for finding in findings}


def _generic_secret(seed: str) -> str:
    material = f"Aa{seed}9!zZ7$kK3@"
    return (material * 4)[:32]


def test_safe_public_fixture_and_binary_commit_pass(tmp_path):
    root, _remote = _repository(tmp_path)
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    (root / "tests").mkdir()
    (root / "tests" / "fixture.txt").write_text(
        'api_key = "fixture-secret-value-long-enough"\n'
    )
    (root / "binary.bin").write_bytes(b"\x00" + b"AKIA" + b"A" * 16)
    head = _commit(root)

    scanner = public_hygiene.RepositoryScanner(root)

    assert scanner.scan_range(f"{base}..{head}") == set()


def test_unquoted_env_and_yaml_credentials_are_redacted(tmp_path, capsys):
    root, _remote = _repository(tmp_path)
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    candidates = [_generic_secret(seed) for seed in ("Api", "Tok", "Sec", "Pwd")]
    (root / ".env").write_text(
        "\n".join(
            (
                f"API_KEY={candidates[0]}",
                f"ACCESS_TOKEN: {candidates[1]}",
                f"export CLIENT_SECRET={candidates[2]}",
                f"PASSWORD: {candidates[3]} # private",
            )
        )
        + "\n"
    )
    head = _commit(root)

    findings = public_hygiene.RepositoryScanner(root).scan_range(f"{base}..{head}")
    result = public_hygiene.main(["--repo-root", str(root), "--range", f"{base}..{head}"])
    output = capsys.readouterr()

    assert result == 1
    assert len([item for item in findings if item.rule == "credential_assignment"]) == 4
    assert not any(candidate in output.out + output.err for candidate in candidates)


def test_fixture_word_outside_test_path_does_not_exempt_credential(tmp_path):
    root, _remote = _repository(tmp_path)
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    candidate = "fixture-" + _generic_secret("Outside")
    (root / ".env").write_text(f"API_KEY={candidate}\n")
    head = _commit(root)

    findings = public_hygiene.RepositoryScanner(root).scan_range(f"{base}..{head}")

    assert "credential_assignment" in _rules(findings)


def test_namespaced_json_and_punctuated_credentials_are_redacted(tmp_path, capsys):
    root, _remote = _repository(tmp_path)
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    candidates = [_generic_secret(seed) for seed in ("Tiingo", "Db", "Aws", "Json")]
    content = "\n".join(
        (
            f"TIINGO_API_KEY={candidates[0]}",
            f"database_password: {candidates[1]}",
            f'AWS_SECRET_ACCESS_KEY = "{candidates[2]}"',
            "{" + f'\"api_key\": \"{candidates[3]}\"' + "}",
        )
    )
    (root / "credentials.conf").write_text(content + "\n")
    head = _commit(root)
    scanner = public_hygiene.RepositoryScanner(root)

    committed = scanner.scan_range(f"{base}..{head}")
    worktree = scanner.scan_worktree()
    result = public_hygiene.main(
        ["--repo-root", str(root), "--range", f"{base}..{head}", "--worktree"]
    )
    output = capsys.readouterr()

    assert len([item for item in committed if item.rule == "credential_assignment"]) == 4
    assert len([item for item in worktree if item.rule == "credential_assignment"]) == 4
    assert result == 1
    assert not any(candidate in output.out + output.err for candidate in candidates)


def test_multifield_nested_list_json_inline_yaml_and_api_tokens_are_redacted(
    tmp_path, capsys
):
    root, _remote = _repository(tmp_path)
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    candidates = [_generic_secret(seed) for seed in ("One", "Two", "Three", "Four", "Five", "Six", "Seven")]
    content = "\n".join(
        (
            "{" + f'\"api_key\":\"{candidates[0]}\",\"region\":\"us\"' + "}",
            "{" + f'\"service\":{{\"api_key\":\"{candidates[1]}\"}}' + "}",
            "[{" + f'\"api_key\":\"{candidates[2]}\"' + "}]",
            f"service: {{api_token: {candidates[3]}, region: us}}",
            f"TIINGO_API_TOKEN={candidates[4]}",
            "payload = " + r"{\"api_key\":\"" + candidates[5] + r"\"}",
            '"api_key":\n    ' + f'"{candidates[6]}"',
        )
    )
    (root / "serialized-credentials.txt").write_text(content + "\n")
    head = _commit(root)
    scanner = public_hygiene.RepositoryScanner(root)

    committed = scanner.scan_range(f"{base}..{head}")
    worktree = scanner.scan_worktree()
    result = public_hygiene.main(
        ["--repo-root", str(root), "--range", f"{base}..{head}", "--worktree"]
    )
    output = capsys.readouterr()

    assert len([item for item in committed if item.rule == "credential_assignment"]) == 7
    assert len([item for item in worktree if item.rule == "credential_assignment"]) == 7
    assert result == 1
    assert not any(candidate in output.out + output.err for candidate in candidates)


def test_documented_private_key_and_provider_prefix_set_is_redacted(tmp_path, capsys):
    root, _remote = _repository(tmp_path)
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    providers = [
        "AKIA" + "A1B2C3D4E5F6G7H8",
        "ASIA" + "H8G7F6E5D4C3B2A1",
        "ghp_" + "Ab9" * 10,
        "gho_" + "Bc8" * 10,
        "ghs_" + "Cd7" * 10,
        "github_pat_" + "De6_" * 8,
        "glpat-" + "Ef5_" * 8,
        "xoxb-" + "Fg4-" * 8,
        "AIza" + "Gh3_" * 7,
        "sk_live_" + "Hi2" * 7,
        "rk_live_" + "Ij1" * 7,
        "sk-" + "Jk9_" * 6,
        "sk-ant-" + "Kl8_" * 5,
        "npm_" + "Lm7" * 8,
        "pypi-" + "Mn6_" * 6,
    ]
    private_header = "-----BEGIN " + "OPENSSH PRIVATE KEY-----"
    (root / "provider-secrets.txt").write_text(
        private_header + "\n" + "\n".join(providers) + "\n"
    )
    head = _commit(root)
    scanner = public_hygiene.RepositoryScanner(root)

    committed = scanner.scan_range(f"{base}..{head}")
    worktree = scanner.scan_worktree()
    result = public_hygiene.main(
        ["--repo-root", str(root), "--range", f"{base}..{head}", "--worktree"]
    )
    output = capsys.readouterr()
    expected_rules = {
        "aws_access_key",
        "github_token",
        "gitlab_token",
        "slack_token",
        "google_api_key",
        "stripe_key",
        "model_api_key",
        "npm_token",
        "pypi_token",
        "private_key",
    }

    assert expected_rules <= _rules(committed)
    assert expected_rules <= _rules(worktree)
    assert result == 1
    assert private_header not in output.out + output.err
    assert not any(candidate in output.out + output.err for candidate in providers)


def test_checker_source_does_not_trigger_its_path_rules():
    source = Path(public_hygiene.__file__).read_text()

    findings = public_hygiene._scan_value(
        "tools/public_hygiene.py", source, denylist=()
    )

    assert not (_rules(findings) & {rule for rule, _pattern in public_hygiene._PATH_RULES})


def test_added_home_and_data_paths_are_redacted(tmp_path, capsys):
    root, _remote = _repository(tmp_path)
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    private_home = "/" + "home" + "/private-user/project"
    root_home = "/" + "root" + "/project"
    private_mount = "/" + "data" + "00/archive"
    (root / "paths.txt").write_text(f"{private_home}\n{root_home}\n{private_mount}\n")
    head = _commit(root)

    result = public_hygiene.main(["--repo-root", str(root), "--range", f"{base}..{head}"])
    output = capsys.readouterr()

    assert result == 1
    assert {"absolute_home_path", "absolute_root_home", "absolute_data_mount"} <= {
        row.rule for row in public_hygiene.RepositoryScanner(root).scan_range(f"{base}..{head}")
    }
    assert private_home not in output.out + output.err
    assert private_mount not in output.out + output.err


def test_windows_home_boundaries_escaped_text_filenames_and_symlinks(tmp_path, capsys):
    root, _remote = _repository(tmp_path)
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    separator = "\\"
    terminal = "C:" + separator + "Users" + separator + "private-user"
    child = terminal + separator + "project"
    escaped = "C:" + separator * 2 + "Users" + separator * 2 + "private-user"
    (root / "windows.txt").write_text(f"{terminal}\n{child}\n{escaped}\n")
    (root / escaped).write_text("safe filename fixture\n")
    (root / "terminal-link").symlink_to(terminal)
    head = _commit(root)
    scanner = public_hygiene.RepositoryScanner(root)

    committed = scanner.scan_range(f"{base}..{head}")
    worktree = scanner.scan_worktree()
    result = public_hygiene.main(
        ["--repo-root", str(root), "--range", f"{base}..{head}", "--worktree"]
    )
    output = capsys.readouterr()

    committed_windows = [item for item in committed if item.rule == "absolute_windows_home"]
    worktree_windows = [item for item in worktree if item.rule == "absolute_windows_home"]
    assert len(committed_windows) >= 4
    assert len(worktree_windows) >= 4
    assert any(item.path == "terminal-link" for item in committed_windows)
    assert any(item.path == "<redacted-path>" for item in committed_windows)
    assert result == 1
    assert not any(candidate in output.out + output.err for candidate in (terminal, child, escaped))


def test_secret_content_and_filename_never_print_candidate(tmp_path, capsys):
    root, _remote = _repository(tmp_path)
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    secret = "gh" + "p_" + "A" * 36
    (root / "credential.txt").write_text(secret + "\n")
    (root / f"{secret}.txt").write_text("safe content\n")
    head = _commit(root)

    result = public_hygiene.main(["--repo-root", str(root), "--range", f"{base}..{head}"])
    output = capsys.readouterr()

    assert result == 1
    assert "github_token" in output.out
    assert "<redacted-path>" in output.out
    assert secret not in output.out + output.err


def test_symlink_targets_are_scanned_without_following_and_redacted(tmp_path, capsys):
    root, _remote = _repository(tmp_path)
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    home_target = "/" + "home" + "/private-user/missing"
    data_target = "/" + "data" + "00/missing"
    secret_target = "gh" + "p_" + "S" * 36
    denied_target = "private-host-" + "symlink"
    targets = {
        "home-link": home_target,
        "data-link": data_target,
        "secret-link": secret_target,
        "host-link": denied_target,
    }
    for name, target in targets.items():
        (root / name).symlink_to(target)
    head = _commit(root)
    denylist = tmp_path / "denylist"
    denylist.write_text(denied_target + "\n")
    denylist.chmod(0o600)
    scanner = public_hygiene.RepositoryScanner(root, (denied_target,))

    committed = scanner.scan_range(f"{base}..{head}")
    worktree = scanner.scan_worktree()
    result = public_hygiene.main(
        [
            "--repo-root",
            str(root),
            "--range",
            f"{base}..{head}",
            "--denylist",
            str(denylist),
        ]
    )
    output = capsys.readouterr()

    expected = {
        "absolute_home_path",
        "absolute_data_mount",
        "github_token",
        "host_private_denylist",
    }
    assert expected <= _rules(committed)
    assert expected <= _rules(worktree)
    assert result == 1
    assert not any(target in output.out + output.err for target in targets.values())


def test_only_added_lines_are_scanned(tmp_path):
    root, _remote = _repository(tmp_path)
    old_private_path = "/" + "home" + "/legacy-user/project"
    tracked = root / "notes.txt"
    tracked.write_text(old_private_path + "\nkept\n")
    base = _commit(root, "legacy fixture")
    tracked.write_text(old_private_path + "\nkept\nnew safe line\n")
    head = _commit(root)

    findings = public_hygiene.RepositoryScanner(root).scan_range(f"{base}..{head}")

    assert findings == set()


def test_invalid_metadata_and_tool_coauthor_are_rejected(tmp_path):
    root, _remote = _repository(tmp_path)
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    (root / "metadata.txt").write_text("changed\n")
    private_email = "author" + "@" + "company" + ".invalid"
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Private Author",
        "GIT_AUTHOR_EMAIL": private_email,
        "GIT_COMMITTER_NAME": "Private Author",
        "GIT_COMMITTER_EMAIL": private_email,
    }
    trailer = "Co-authored-by: " + "Tra" + "e CLI <fixture@example.com>"
    _git(root, "add", "metadata.txt")
    _git(root, "commit", "-m", "metadata fixture", "-m", trailer, env=env)
    head = _git(root, "rev-parse", "HEAD").stdout.strip()

    findings = public_hygiene.RepositoryScanner(root).scan_range(f"{base}..{head}")

    assert {"commit_identity_email", "tool_coauthor"} <= _rules(findings)


def test_public_claude_coauthor_trailer_is_admitted(tmp_path):
    root, _remote = _repository(tmp_path)
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    (root / "metadata.txt").write_text("changed\n")
    trailer = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
    _git(root, "add", "metadata.txt")
    _git(root, "commit", "-m", "metadata fixture", "-m", trailer)
    head = _git(root, "rev-parse", "HEAD").stdout.strip()

    findings = public_hygiene.RepositoryScanner(root).scan_range(f"{base}..{head}")

    assert "tool_coauthor" not in _rules(findings)

def test_merge_only_addition_is_scanned(tmp_path):
    root, _remote = _repository(tmp_path)
    base_branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    (root / "choice.txt").write_text("base\n")
    _commit(root)
    _git(root, "checkout", "-b", "side")
    (root / "choice.txt").write_text("side\n")
    _commit(root, "side fixture")
    _git(root, "checkout", base_branch)
    (root / "choice.txt").write_text("main\n")
    _commit(root, "main fixture")
    merge = _git(root, "merge", "--no-ff", "side", check=False)
    assert merge.returncode != 0
    secret = "gh" + "p_" + "M" * 36
    (root / "choice.txt").write_text(secret + "\n")
    head = _commit(root, "merge fixture")

    findings = public_hygiene.RepositoryScanner(root).scan_range(f"{head}^!")

    assert "github_token" in _rules(findings)


def test_pre_push_handles_new_and_deleted_branches(tmp_path):
    root, _remote = _repository(tmp_path)
    _git(root, "checkout", "-b", "feature")
    (root / "feature.txt").write_text("safe\n")
    head = _commit(root)
    scanner = public_hygiene.RepositoryScanner(root)

    new_branch = public_hygiene._pre_push_commits(
        scanner,
        [f"refs/heads/feature {head} refs/heads/feature {public_hygiene.ZERO_SHA}\n"],
        "origin",
    )
    deleted = public_hygiene._pre_push_commits(
        scanner,
        [f"(delete) {public_hygiene.ZERO_SHA} refs/heads/old {head}\n"],
        "origin",
    )

    assert head in new_branch
    assert deleted == []


def test_private_denylist_requires_owner_only_mode_and_redacts(tmp_path, capsys):
    root, _remote = _repository(tmp_path)
    denied = "private-host-" + "fixture"
    denylist = tmp_path / "denylist"
    denylist.write_text(denied + "\n")
    denylist.chmod(0o644)
    with pytest.raises(public_hygiene.HygieneError, match="mode 0600"):
        public_hygiene.load_denylist(denylist)
    denylist.chmod(0o600)
    (root / "host.txt").write_text(denied + "\n")

    result = public_hygiene.main(
        ["--repo-root", str(root), "--worktree", "--denylist", str(denylist)]
    )
    output = capsys.readouterr()

    assert result == 1
    assert "host_private_denylist" in output.out
    assert denied not in output.out + output.err


def test_worktree_refuses_oversize_text_but_skips_oversize_binary(tmp_path):
    root, _remote = _repository(tmp_path)
    (root / "large.txt").write_bytes(b"a" * (public_hygiene.MAX_TEXT_BYTES + 1))
    (root / "large.bin").write_bytes(b"\x00" + b"a" * public_hygiene.MAX_TEXT_BYTES)

    findings = public_hygiene.RepositoryScanner(root).scan_worktree()

    limits = [finding for finding in findings if finding.rule == "text_size_limit"]
    assert [finding.path for finding in limits] == ["large.txt"]


def test_ci_all_zero_base_scans_head_commit(tmp_path, monkeypatch):
    root, _remote = _repository(tmp_path)
    (root / "ci.txt").write_text("safe\n")
    head = _commit(root)
    scanner = public_hygiene.RepositoryScanner(root)
    monkeypatch.setenv("PUBLIC_HYGIENE_BASE_SHA", public_hygiene.ZERO_SHA)
    monkeypatch.setenv("PUBLIC_HYGIENE_HEAD_SHA", head)

    assert public_hygiene._ci_commits(scanner) == [head]


def test_malformed_pre_push_input_fails_closed(tmp_path, monkeypatch, capsys):
    root, _remote = _repository(tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("malformed\n"))

    result = public_hygiene.main(["--repo-root", str(root), "--pre-push"])

    assert result == 2
    assert "malformed pre-push" in capsys.readouterr().err
