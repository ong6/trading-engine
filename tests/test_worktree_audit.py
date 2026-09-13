"""Read-only recursive worktree ownership inventory."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tools import worktree_audit


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    )


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "README.md").write_text("original\n")
    (root / "engine").mkdir()
    (root / "engine" / "runtime.py").write_text("VALUE = 1\n")
    (root / "farm").mkdir()
    (root / "sim").mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "Audit Test")
    _git(root, "config", "user.email", "audit@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    return root


def test_audit_recursively_classifies_changes_and_preserves_empty_index(tmp_path):
    root = _repository(tmp_path)
    (root / "README.md").write_text("changed\n")
    (root / "server" / "nested").mkdir(parents=True)
    (root / "server" / "nested" / "module.py").write_text("VALUE = 2\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_module.py").write_text("def test_ok(): pass\n")
    (root / "data").mkdir()
    (root / "data" / "report.json").write_text("{}\n")

    audit = worktree_audit.build_audit(root)

    assert audit["schema_version"] == 3
    assert audit["summary"]["changed_path_count"] == 4
    assert audit["summary"]["tracked_changed_count"] == 1
    assert audit["summary"]["untracked_count"] == 3
    assert audit["summary"]["ownership_counts"] == {
        "docs-configuration": 1,
        "generated-evidence": 1,
        "support-api": 1,
        "tests": 1,
    }
    assert audit["review_gates"]["index_empty"] is True
    assert audit["review_gates"]["ownership_complete"] is True
    assert audit["review_gates"]["untracked_files_safe"] is True
    assert audit["review_gates"]["untracked_symlink_paths"] == []
    assert audit["review_gates"]["untracked_special_paths"] == []
    assert audit["review_gates"]["unstable_untracked_paths"] == []
    assert audit["review_gates"]["unsafe_untracked_paths"] == []
    assert audit["review_gates"]["empty_untracked_file_paths"] == []
    assert audit["protected_research"]["identity_complete"] is True
    assert [row["path"] for row in audit["paths"]] == [
        "README.md",
        "data/report.json",
        "server/nested/module.py",
        "tests/test_module.py",
    ]


def test_audit_flags_staged_and_unknown_paths(tmp_path, monkeypatch, capsys):
    root = _repository(tmp_path)
    (root / "misc").mkdir()
    (root / "misc" / "unknown.txt").write_text("unknown\n")
    (root / "README.md").write_text("staged\n")
    _git(root, "add", "README.md")
    monkeypatch.setattr(
        worktree_audit,
        "research_runtime_identity",
        lambda _root: {"sha256": "a" * 64, "file_count": 1},
    )

    audit = worktree_audit.build_audit(root)

    assert audit["review_gates"]["index_empty"] is False
    assert audit["review_gates"]["staged_paths"] == ["README.md"]
    assert audit["review_gates"]["ownership_complete"] is False
    assert audit["review_gates"]["unknown_paths"] == ["misc/unknown.txt"]
    assert worktree_audit.main(["--repo-root", str(root), "--strict"]) == 1
    assert '"ownership_complete": false' in capsys.readouterr().out


def test_status_parser_keeps_rename_origin_and_special_characters():
    rows = worktree_audit._parse_status(
        b"R  docs/new name.md\0docs/old name.md\0?? server/quote's.py\0"
    )

    assert rows[0]["path"] == "docs/new name.md"
    assert rows[0]["original_path"] == "docs/old name.md"
    assert rows[0]["staged"] is True
    assert rows[1]["path"] == "server/quote's.py"
    assert rows[1]["untracked"] is True


def test_strict_audit_rejects_untracked_symlink_and_reports_empty_file(
    tmp_path, monkeypatch, capsys
):
    root = _repository(tmp_path)
    server = root / "server"
    server.mkdir()
    target = server / "target.py"
    target.write_text("VALUE = 1\n")
    (server / "linked.py").symlink_to(target)
    (server / "empty.py").touch()
    monkeypatch.setattr(
        worktree_audit,
        "research_runtime_identity",
        lambda _root: {"sha256": "a" * 64, "file_count": 1},
    )

    audit = worktree_audit.build_audit(root)

    assert audit["review_gates"]["untracked_files_safe"] is False
    assert audit["review_gates"]["untracked_symlink_paths"] == ["server/linked.py"]
    assert audit["review_gates"]["unsafe_untracked_paths"] == ["server/linked.py"]
    assert audit["review_gates"]["empty_untracked_file_paths"] == ["server/empty.py"]
    assert worktree_audit.main(["--repo-root", str(root), "--strict"]) == 1
    assert '"untracked_files_safe": false' in capsys.readouterr().out


def test_strict_audit_rejects_untracked_special_file(tmp_path, monkeypatch, capsys):
    root = _repository(tmp_path)
    server = root / "server"
    server.mkdir()
    os.mkfifo(server / "events.pipe")
    status = b"?? server/events.pipe\0"
    original_git = worktree_audit._git

    def git_with_reported_special(repo_root, *args):
        if args and args[0] == "status":
            return status
        return original_git(repo_root, *args)

    monkeypatch.setattr(worktree_audit, "_git", git_with_reported_special)
    monkeypatch.setattr(
        worktree_audit,
        "research_runtime_identity",
        lambda _root: {"sha256": "a" * 64, "file_count": 1},
    )

    audit = worktree_audit.build_audit(root)

    assert audit["review_gates"]["untracked_files_safe"] is False
    assert audit["review_gates"]["untracked_special_paths"] == ["server/events.pipe"]
    assert audit["review_gates"]["unsafe_untracked_paths"] == ["server/events.pipe"]
    assert worktree_audit.main(["--repo-root", str(root), "--strict"]) == 1
    assert '"untracked_files_safe": false' in capsys.readouterr().out


def test_untracked_path_replaced_during_inspection_is_unstable(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    server = root / "server"
    server.mkdir()
    target = server / "module.py"
    target.write_text("VALUE = 1\n")
    replacement = tmp_path / "replacement.py"
    replacement.write_text("VALUE = 1\n")
    original_stat = worktree_audit.os.stat
    observed = False

    def stat_then_replace(path, *, dir_fd=None, follow_symlinks=True):
        nonlocal observed
        result = original_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        if path == target.name and dir_fd is not None and not observed:
            observed = True
            target.unlink()
            replacement.replace(target)
        return result

    monkeypatch.setattr(worktree_audit.os, "stat", stat_then_replace)

    assert worktree_audit._untracked_path_state(root, "server/module.py") == "unstable"
    assert observed is True


def test_audit_rejects_changed_git_inventory(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    server = root / "server"
    server.mkdir()
    (server / "first.py").write_text("VALUE = 1\n")
    original_groups = worktree_audit._change_groups

    def groups_then_add(repo_root, rows):
        result = original_groups(repo_root, rows)
        (server / "second.py").write_text("VALUE = 2\n")
        return result

    monkeypatch.setattr(worktree_audit, "_change_groups", groups_then_add)

    with pytest.raises(worktree_audit.AuditError, match="working tree changed during audit"):
        worktree_audit.build_audit(root)


def test_strict_audit_rejects_incomplete_protected_identity(tmp_path, monkeypatch, capsys):
    root = _repository(tmp_path)
    monkeypatch.setattr(
        worktree_audit,
        "research_runtime_identity",
        lambda _root: {"sha256": None, "file_count": 1},
    )

    audit = worktree_audit.build_audit(root)

    assert audit["protected_research"]["identity_complete"] is False
    assert worktree_audit.main(["--repo-root", str(root), "--strict"]) == 1
    assert '"identity_complete": false' in capsys.readouterr().out
