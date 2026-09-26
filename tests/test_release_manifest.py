"""Deterministic release identity without row reads, network, or host mutation."""

from __future__ import annotations

import ast
import json
import os
import subprocess
from pathlib import Path

import duckdb
import pytest

from engine.lib.provenance import runtime_source_hash
from tools import release_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
LOCAL_PACKAGES = frozenset({"engine", "farm", "server", "sim", "tools"})


def _loaded_local_paths(root: Path, module: str) -> set[str]:
    parts = module.split(".")
    if not parts or parts[0] not in LOCAL_PACKAGES:
        return set()
    loaded = set()
    for end in range(1, len(parts) + 1):
        package = root.joinpath(*parts[:end], "__init__.py")
        if package.is_file():
            loaded.add(package.relative_to(root).as_posix())
    source = root.joinpath(*parts).with_suffix(".py")
    if source.is_file():
        loaded.add(source.relative_to(root).as_posix())
    return loaded


def _local_import_paths(root: Path, relative: str) -> set[str]:
    path = root / relative
    module_parts = list(path.relative_to(root).with_suffix("").parts)
    package_parts = module_parts[:-1]
    if module_parts[-1] == "__init__":
        package_parts = module_parts[:-1]
    imported = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=relative)):
        targets = []
        if isinstance(node, ast.Import):
            targets.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                keep = len(package_parts) - (node.level - 1)
                if keep < 0:
                    continue
                base_parts = package_parts[:keep]
            else:
                base_parts = []
            if node.module:
                base_parts += node.module.split(".")
            base = ".".join(base_parts)
            if base:
                targets.append(base)
            for alias in node.names:
                if alias.name != "*":
                    targets.append(".".join((*base_parts, alias.name)))
        for target in targets:
            imported.update(_loaded_local_paths(root, target))
    return imported


def _recursive_local_import_closure(root: Path, entrypoint: str) -> set[str]:
    closure = {entrypoint}
    pending = [entrypoint]
    while pending:
        imported = _local_import_paths(root, pending.pop())
        pending.extend(sorted(imported - closure))
        closure.update(imported)
    return closure


def _git(root, *args):
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("store/\n")
    for relative in release_manifest.REQUIRED_FILES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative}\n")
    (root / "engine" / "runtime.py").write_text("VALUE = 1\n")
    (root / "farm").mkdir(exist_ok=True)
    (root / "sim" / "runtime.py").write_text("VALUE = 2\n")
    _git(root, "init")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(root, "config", "user.name", "Release Test")
    _git(root, "config", "user.email", "release@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "fixture")
    database = root / "store" / "market.duckdb"
    database.parent.mkdir()
    connection = duckdb.connect(str(database))
    connection.execute("CREATE TABLE release_probe (id INTEGER PRIMARY KEY, note VARCHAR)")
    connection.close()
    return root


def test_clean_manifest_is_deterministic_and_release_eligible(tmp_path):
    root = _repository(tmp_path)

    first = release_manifest.build_manifest(root)
    second = release_manifest.build_manifest(root)

    assert first == second
    assert first["schema_version"] == 8
    assert first["status"] == "release-candidate"
    assert first["release_eligible"] is True
    assert first["identity_complete"] is True
    assert first["reasons"] == []
    assert first["git"]["branch"] == "main"
    assert first["git"]["dirty"] is False
    assert first["git"]["required_files_tracked"] is True
    assert first["git"]["network_checked"] is False
    assert first["git"]["working_tree"]["sha256"] is not None
    assert first["git"]["working_tree"]["missing_paths"] == []
    source_sha256, source_file_count = runtime_source_hash(root)
    assert first["research_runtime"] == {
        "sha256": source_sha256,
        "file_count": source_file_count,
    }
    assert first["dependencies"]["file_count"] == len(release_manifest.DEPENDENCY_FILES)
    assert first["strategy_registrations"]["file_count"] == 1
    assert first["execution_profiles"]["file_count"] == 1
    assert set(first["agent_sources"]["files"]) == set(
        release_manifest.AGENT_SOURCE_FILES
    )
    assert first["agent_sources"]["sha256"] is not None
    assert "engine/p15_evaluation.py" in release_manifest.AGENT_SOURCE_FILES
    assert "data/reports/agent-eval/p15.md" in release_manifest.PROSPECTIVE_EVIDENCE_FILES
    assert set(first["broker_boundary_sources"]["files"]) == set(
        release_manifest.BROKER_BOUNDARY_SOURCE_FILES
    )
    assert first["broker_boundary_sources"]["sha256"] is not None
    assert set(first["independent_risk_sources"]["files"]) == set(
        release_manifest.INDEPENDENT_RISK_SOURCE_FILES
    )
    assert first["independent_risk_sources"]["sha256"] is not None
    assert set(first["audit_sources"]["files"]) == {
        "tools/initialize_agent_paper_book.py",
        "tools/migrate_agent_human_approval.py",
        "tools/migrate_agent_paper_attribution.py",
        "tools/migrate_agent_paper_authority_store.py",
        "tools/migrate_agent_release_review.py",
        "tools/market_data_source.py",
        "tools/release_manifest.py",
        "tools/worktree_audit.py",
    }
    assert set(first["recovery_sources"]["files"]) == set(
        release_manifest.RECOVERY_SOURCE_FILES
    )
    assert first["recovery_sources"]["sha256"] is not None
    assert len(first["manifest_sha256"]) == 64
    assert first["database_schema"]["status"] == "ok"
    assert first["database_schema"]["table_count"] == 1
    assert first["database_schema"]["location"] == {
        "kind": "repository-relative",
        "path": "store/market.duckdb",
    }


def test_recovery_identity_binds_semantic_validator(tmp_path):
    root = _repository(tmp_path)
    first = release_manifest.build_manifest(root)

    validator = root / "server" / "nightly_reports.py"
    validator.write_text(validator.read_text() + "# changed\n")
    second = release_manifest.build_manifest(root)

    assert first["recovery_sources"]["sha256"] != second["recovery_sources"]["sha256"]


def test_agent_identity_binds_proposal_boundary(tmp_path):
    root = _repository(tmp_path)
    first = release_manifest.build_manifest(root)

    boundary = root / "server" / "agent_contract.py"
    boundary.write_text(boundary.read_text() + "# changed\n")
    second = release_manifest.build_manifest(root)

    assert first["agent_sources"]["sha256"] != second["agent_sources"]["sha256"]


def test_broker_boundary_identity_binds_simulator_adapter(tmp_path):
    root = _repository(tmp_path)
    first = release_manifest.build_manifest(root)

    boundary = root / "server" / "simulator_broker_adapter.py"
    boundary.write_text(boundary.read_text() + "# changed\n")
    second = release_manifest.build_manifest(root)

    assert (
        first["broker_boundary_sources"]["sha256"]
        != second["broker_boundary_sources"]["sha256"]
    )


def test_independent_risk_identity_binds_risk_contract(tmp_path):
    root = _repository(tmp_path)
    first = release_manifest.build_manifest(root)

    risk = root / "server" / "broker_risk.py"
    risk.write_text(risk.read_text() + "# changed\n")
    second = release_manifest.build_manifest(root)

    assert (
        first["independent_risk_sources"]["sha256"]
        != second["independent_risk_sources"]["sha256"]
    )


def test_independent_risk_identity_binds_paper_intent_contract(tmp_path):
    root = _repository(tmp_path)
    first = release_manifest.build_manifest(root)

    contract = root / "server" / "broker_paper_intent.py"
    contract.write_text(contract.read_text() + "# changed\n")
    second = release_manifest.build_manifest(root)

    assert (
        first["independent_risk_sources"]["sha256"]
        != second["independent_risk_sources"]["sha256"]
    )


def test_independent_risk_identity_binds_human_review_boundary(tmp_path):
    root = _repository(tmp_path)
    first = release_manifest.build_manifest(root)

    review = root / "server" / "broker_human_paper_review.py"
    review.write_text(review.read_text() + "# changed\n")
    second = release_manifest.build_manifest(root)

    assert (
        first["independent_risk_sources"]["sha256"]
        != second["independent_risk_sources"]["sha256"]
    )


def test_independent_risk_identity_binds_human_approval_contract(tmp_path):
    root = _repository(tmp_path)
    first = release_manifest.build_manifest(root)

    approval = root / "server" / "broker_human_paper_approval.py"
    approval.write_text(approval.read_text() + "# changed\n")
    second = release_manifest.build_manifest(root)

    assert (
        first["independent_risk_sources"]["sha256"]
        != second["independent_risk_sources"]["sha256"]
    )


def test_independent_risk_identity_binds_human_review_cli(tmp_path):
    root = _repository(tmp_path)
    first = release_manifest.build_manifest(root)

    cli = root / "tools" / "review_agent_paper_intent.py"
    cli.write_text(cli.read_text() + "# changed\n")
    second = release_manifest.build_manifest(root)

    assert (
        first["independent_risk_sources"]["sha256"]
        != second["independent_risk_sources"]["sha256"]
    )


def test_independent_risk_identity_binds_fault_drills(tmp_path):
    root = _repository(tmp_path)
    first = release_manifest.build_manifest(root)

    drills = root / "server" / "broker_risk_fault_drills.py"
    drills.write_text(drills.read_text() + "# changed\n")
    second = release_manifest.build_manifest(root)

    assert (
        first["independent_risk_sources"]["sha256"]
        != second["independent_risk_sources"]["sha256"]
    )


def test_recovery_sources_match_recursive_local_import_closure():
    assert set(release_manifest.RECOVERY_SOURCE_FILES) == _recursive_local_import_closure(
        REPO_ROOT, "tools/backup_database.py"
    )


def test_dirty_manifest_never_claims_release_eligibility(tmp_path):
    root = _repository(tmp_path)
    (root / "local-note.txt").write_text("uncommitted\n")

    manifest = release_manifest.build_manifest(root)

    assert manifest["status"] == "non-releasable"
    assert manifest["release_eligible"] is False
    assert manifest["identity_complete"] is True
    assert "dirty-working-tree" in manifest["reasons"]
    assert manifest["git"]["changed_path_count"] == 1


def test_working_tree_identity_binds_uncommitted_content(tmp_path):
    root = _repository(tmp_path)
    note = root / "local-note.txt"
    note.write_text("first\n")
    first = release_manifest.build_manifest(root)

    note.write_text("other\n")
    second = release_manifest.build_manifest(root)

    assert first["git"]["changed_path_count"] == second["git"]["changed_path_count"] == 1
    assert first["git"]["working_tree"]["sha256"] != second["git"]["working_tree"]["sha256"]
    assert first["manifest_sha256"] != second["manifest_sha256"]


def test_stable_release_symlink_read_rejects_target_replacement(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    first_target = root / "first.txt"
    second_target = root / "second.txt"
    first_target.write_text("first\n")
    second_target.write_text("second\n")
    link = root / "current.txt"
    link.symlink_to(first_target.name)
    original_readlink = release_manifest.os.readlink
    replaced = False

    def readlink_then_replace(path, *, dir_fd=None):
        nonlocal replaced
        target = original_readlink(path, dir_fd=dir_fd)
        if not replaced:
            replaced = True
            link.unlink()
            link.symlink_to(second_target.name)
        return target

    monkeypatch.setattr(release_manifest.os, "readlink", readlink_then_replace)

    with pytest.raises(OSError, match="changed during read"):
        release_manifest._read_stable_symlink(link)

    assert replaced is True


def test_working_tree_identity_rejects_symlink_swapped_to_fifo_after_classification(
    tmp_path, monkeypatch
):
    root = _repository(tmp_path)
    target = root / "target.txt"
    target.write_text("target\n")
    link = root / "current.txt"
    link.symlink_to(target.name)
    _git(root, "add", "target.txt", "current.txt")
    _git(root, "commit", "-m", "add symlink fixture")
    original_is_symlink = Path.is_symlink
    replaced = False

    def classify_then_replace(path):
        nonlocal replaced
        result = original_is_symlink(path)
        if path == link and result and not replaced:
            replaced = True
            link.unlink()
            os.mkfifo(link)
        return result

    monkeypatch.setattr(Path, "is_symlink", classify_then_replace)

    identity = release_manifest._working_tree_identity(root)

    assert replaced is True
    assert identity["missing_paths"] == ["current.txt"]


def test_changed_path_count_handles_newlines_and_renames(tmp_path):
    root = _repository(tmp_path)
    original = root / "rename-me.txt"
    original.write_text("tracked\n")
    _git(root, "add", "rename-me.txt")
    _git(root, "commit", "-m", "add rename fixture")

    _git(root, "mv", "rename-me.txt", "renamed.txt")
    (root / "line\nbreak.txt").write_text("untracked\n")

    manifest = release_manifest.build_manifest(root)

    assert manifest["git"]["changed_path_count"] == 2
    assert manifest["git"]["dirty"] is True


def test_target_checkout_owns_registration_and_profile_identities(tmp_path):
    root = _repository(tmp_path)
    first = release_manifest.build_manifest(root)

    (root / "sim" / "strategies" / "configs.py").write_text("CONFIGS = []\n")
    (root / "sim" / "execution.py").write_text("PROFILES = {}\n")
    second = release_manifest.build_manifest(root)

    assert first["strategy_registrations"] != second["strategy_registrations"]
    assert first["execution_profiles"] != second["execution_profiles"]


def test_working_tree_change_during_scan_fails_closed(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    actual = release_manifest._working_tree_identity(root)
    changed = {**actual, "sha256": "f" * 64}
    observed = iter((actual, changed))
    monkeypatch.setattr(release_manifest, "_working_tree_identity", lambda _root: next(observed))

    manifest = release_manifest.build_manifest(root)

    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "working-tree-changed-during-scan" in manifest["reasons"]


def test_git_head_change_during_scan_fails_closed(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    original_file_groups = release_manifest._file_groups
    committed = False

    def groups_then_commit(repo_root):
        nonlocal committed
        result = original_file_groups(repo_root)
        if not committed:
            committed = True
            _git(repo_root, "commit", "--allow-empty", "-m", "concurrent commit")
        return result

    monkeypatch.setattr(release_manifest, "_file_groups", groups_then_commit)

    manifest = release_manifest.build_manifest(root)

    assert committed is True
    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "git-identity-changed-during-scan" in manifest["reasons"]


def test_required_file_transient_change_during_scan_fails_closed(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    target = root / "uv.lock"
    original = target.read_text()
    original_sha256 = release_manifest._sha256
    changed = False

    def hash_with_transient_change(path):
        nonlocal changed
        if path == target and not changed:
            changed = True
            target.write_text("transient replacement\n")
            try:
                return original_sha256(path)
            finally:
                target.write_text(original)
        return original_sha256(path)

    monkeypatch.setattr(release_manifest, "_sha256", hash_with_transient_change)

    manifest = release_manifest.build_manifest(root)

    assert changed is True
    assert target.read_text() == original
    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "working-tree-changed-during-scan" in manifest["reasons"]


def test_ignored_runtime_source_transient_change_fails_closed(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    ignored = root / "engine" / "generated-cache"
    ignored.mkdir()
    with (root / ".gitignore").open("a") as handle:
        handle.write("engine/generated-cache/\n")
    _git(root, "add", ".gitignore")
    _git(root, "commit", "-m", "ignore generated runtime fixture")
    transient = ignored / "transient.py"
    original_runtime_hash = release_manifest.runtime_source_hash
    changed = False

    def hash_with_transient_source(repo_root):
        nonlocal changed
        if not changed:
            changed = True
            transient.write_text("VALUE = 'transient'\n")
            try:
                return original_runtime_hash(repo_root)
            finally:
                transient.unlink()
        return original_runtime_hash(repo_root)

    monkeypatch.setattr(release_manifest, "runtime_source_hash", hash_with_transient_source)

    manifest = release_manifest.build_manifest(root)

    assert changed is True
    assert not transient.exists()
    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "research-runtime-changed-during-scan" in manifest["reasons"]


def test_database_schema_identity_changes_without_reading_rows(tmp_path):
    root = _repository(tmp_path)
    first = release_manifest.build_manifest(root)

    database = root / "store" / "market.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute("INSERT INTO release_probe VALUES (1, 'data-only')")
    connection.close()
    rows_changed = release_manifest.build_manifest(root)
    assert rows_changed["database_schema"] == first["database_schema"]

    connection = duckdb.connect(str(database))
    connection.execute("ALTER TABLE release_probe ADD COLUMN created DATE")
    connection.close()
    schema_changed = release_manifest.build_manifest(root)
    assert schema_changed["database_schema"]["sha256"] != first["database_schema"]["sha256"]
    assert schema_changed["manifest_sha256"] != first["manifest_sha256"]


def test_missing_database_schema_fails_closed(tmp_path):
    root = _repository(tmp_path)
    (root / "store" / "market.duckdb").unlink()

    manifest = release_manifest.build_manifest(root)

    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "database-missing" in manifest["reasons"]
    assert manifest["database_schema"]["sha256"] is None


def test_database_appearing_during_scan_fails_closed(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    database = root / "store" / "market.duckdb"
    database.unlink()
    original_git_identity = release_manifest._git_identity
    appeared = False

    def identify_then_create(repo_root):
        nonlocal appeared
        result = original_git_identity(repo_root)
        if not appeared:
            appeared = True
            connection = duckdb.connect(str(database))
            connection.execute("CREATE TABLE release_probe (id INTEGER PRIMARY KEY)")
            connection.close()
        return result

    monkeypatch.setattr(release_manifest, "_git_identity", identify_then_create)

    manifest = release_manifest.build_manifest(root)

    assert appeared is True
    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "database-schema-path-unsafe" in manifest["reasons"]
    assert manifest["database_schema"]["status"] == "unsafe"


def test_symlinked_database_schema_fails_closed(tmp_path):
    root = _repository(tmp_path)
    database = root / "store" / "market.duckdb"
    external = tmp_path / "external.duckdb"
    database.replace(external)
    database.symlink_to(external)

    manifest = release_manifest.build_manifest(root)

    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "database-schema-path-unsafe" in manifest["reasons"]
    assert manifest["database_schema"]["status"] == "unsafe"
    assert manifest["database_schema"]["sha256"] is None


def test_symlinked_database_parent_fails_closed(tmp_path):
    root = _repository(tmp_path)
    parent = root / "store"
    external = tmp_path / "external-store"
    parent.replace(external)
    parent.symlink_to(external, target_is_directory=True)

    manifest = release_manifest.build_manifest(root)

    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "database-schema-path-unsafe" in manifest["reasons"]
    assert manifest["database_schema"]["status"] == "unsafe"


def test_database_replaced_during_schema_scan_fails_closed(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    database = root / "store" / "market.duckdb"
    replacement = tmp_path / "replacement.duckdb"
    displaced = tmp_path / "displaced.duckdb"
    connection = duckdb.connect(str(replacement))
    connection.execute("CREATE TABLE release_probe (id INTEGER PRIMARY KEY, note VARCHAR)")
    connection.close()
    original_catalog = release_manifest._database_catalog
    replaced = False

    def catalog_then_replace(connection):
        nonlocal replaced
        result = original_catalog(connection)
        if not replaced:
            replaced = True
            database.replace(displaced)
            replacement.replace(database)
        return result

    monkeypatch.setattr(release_manifest, "_database_catalog", catalog_then_replace)

    manifest = release_manifest.build_manifest(root)

    assert replaced is True
    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "database-schema-path-unsafe" in manifest["reasons"]


def test_database_parent_replaced_during_schema_scan_fails_closed(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    database = root / "store" / "market.duckdb"
    parent = database.parent
    displaced = tmp_path / "displaced-store"
    original_catalog = release_manifest._database_catalog
    replaced = False

    def catalog_then_replace(connection):
        nonlocal replaced
        result = original_catalog(connection)
        if not replaced:
            replaced = True
            parent.replace(displaced)
            parent.symlink_to(displaced, target_is_directory=True)
        return result

    monkeypatch.setattr(release_manifest, "_database_catalog", catalog_then_replace)

    manifest = release_manifest.build_manifest(root)

    assert replaced is True
    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "database-schema-path-unsafe" in manifest["reasons"]


def test_database_metadata_changed_during_schema_scan_fails_closed(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    database = root / "store" / "market.duckdb"
    original_catalog = release_manifest._database_catalog
    changed = False

    def catalog_then_touch(connection):
        nonlocal changed
        result = original_catalog(connection)
        if not changed:
            changed = True
            os.utime(database, None)
        return result

    monkeypatch.setattr(release_manifest, "_database_catalog", catalog_then_touch)

    manifest = release_manifest.build_manifest(root)

    assert changed is True
    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "database-schema-path-unsafe" in manifest["reasons"]


def test_database_parent_metadata_churn_during_schema_scan_is_allowed(
    tmp_path, monkeypatch
):
    root = _repository(tmp_path)
    database = root / "store" / "market.duckdb"
    parent = database.parent
    original_catalog = release_manifest._database_catalog
    changed = False

    def catalog_then_touch_parent(connection):
        nonlocal changed
        result = original_catalog(connection)
        if not changed:
            changed = True
            before = parent.stat()
            os.utime(parent, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
        return result

    monkeypatch.setattr(release_manifest, "_database_catalog", catalog_then_touch_parent)

    manifest = release_manifest.build_manifest(root)

    assert changed is True
    assert manifest["database_schema"]["status"] == "ok"
    assert manifest["identity_complete"] is True
    assert manifest["release_eligible"] is True


def test_shared_database_ancestor_metadata_churn_is_allowed(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    ancestor = tmp_path.parent
    original_git_identity = release_manifest._git_identity
    changed = False

    def identify_then_touch(repo_root):
        nonlocal changed
        result = original_git_identity(repo_root)
        if not changed:
            changed = True
            before = ancestor.stat()
            os.utime(ancestor, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
        return result

    monkeypatch.setattr(release_manifest, "_git_identity", identify_then_touch)

    manifest = release_manifest.build_manifest(root)

    assert changed is True
    assert manifest["database_schema"]["status"] == "ok"
    assert manifest["identity_complete"] is True
    assert manifest["release_eligible"] is True


def test_database_changed_after_schema_scan_fails_closed(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    database = root / "store" / "market.duckdb"
    original_runtime_identity = release_manifest.research_runtime_identity
    changed = False

    def change_database_after_schema(repo_root):
        nonlocal changed
        if not changed:
            changed = True
            os.utime(database, None)
        return original_runtime_identity(repo_root)

    monkeypatch.setattr(
        release_manifest, "research_runtime_identity", change_database_after_schema
    )

    manifest = release_manifest.build_manifest(root)

    assert changed is True
    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "database-schema-path-unsafe" in manifest["reasons"]


def test_external_database_parent_swapped_and_restored_fails_closed(
    tmp_path, monkeypatch
):
    root = _repository(tmp_path)
    parent = tmp_path / "external-store"
    parent.mkdir()
    database = parent / "market.duckdb"
    replacement_parent = tmp_path / "replacement-store"
    replacement_parent.mkdir()
    replacement = replacement_parent / database.name
    for path in (database, replacement):
        connection = duckdb.connect(str(path))
        connection.execute(
            "CREATE TABLE release_probe (id INTEGER PRIMARY KEY, note VARCHAR)"
        )
        connection.close()
    displaced_parent = tmp_path / "displaced-store"
    original_file_groups = release_manifest._file_groups
    original_runtime_identity = release_manifest.research_runtime_identity
    swapped = False
    restored = False

    def groups_then_swap(repo_root):
        nonlocal swapped
        result = original_file_groups(repo_root)
        if not swapped:
            swapped = True
            parent.replace(displaced_parent)
            replacement_parent.replace(parent)
        return result

    def restore_then_measure(repo_root):
        nonlocal restored
        if not restored:
            restored = True
            parent.replace(replacement_parent)
            displaced_parent.replace(parent)
        return original_runtime_identity(repo_root)

    monkeypatch.setattr(release_manifest, "_file_groups", groups_then_swap)
    monkeypatch.setattr(release_manifest, "research_runtime_identity", restore_then_measure)

    manifest = release_manifest.build_manifest(root, database)

    assert swapped is True
    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "database-schema-path-unsafe" in manifest["reasons"]


def test_external_database_ancestor_swapped_and_restored_fails_closed(
    tmp_path, monkeypatch
):
    root = _repository(tmp_path)
    ancestor = tmp_path / "external-root"
    parent = ancestor / "nested" / "store"
    parent.mkdir(parents=True)
    database = parent / "market.duckdb"
    replacement_ancestor = tmp_path / "replacement-root"
    replacement_parent = replacement_ancestor / "nested" / "store"
    replacement_parent.mkdir(parents=True)
    replacement = replacement_parent / database.name
    for path in (database, replacement):
        connection = duckdb.connect(str(path))
        connection.execute(
            "CREATE TABLE release_probe (id INTEGER PRIMARY KEY, note VARCHAR)"
        )
        connection.close()
    displaced_ancestor = tmp_path / "displaced-root"
    original_file_groups = release_manifest._file_groups
    original_runtime_identity = release_manifest.research_runtime_identity
    swapped = False
    restored = False

    def groups_then_swap(repo_root):
        nonlocal swapped
        result = original_file_groups(repo_root)
        if not swapped:
            swapped = True
            ancestor.replace(displaced_ancestor)
            replacement_ancestor.replace(ancestor)
        return result

    def restore_then_measure(repo_root):
        nonlocal restored
        if not restored:
            restored = True
            ancestor.replace(replacement_ancestor)
            displaced_ancestor.replace(ancestor)
        return original_runtime_identity(repo_root)

    monkeypatch.setattr(release_manifest, "_file_groups", groups_then_swap)
    monkeypatch.setattr(release_manifest, "research_runtime_identity", restore_then_measure)

    manifest = release_manifest.build_manifest(root, database)

    assert swapped is True
    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "database-schema-path-unsafe" in manifest["reasons"]


def test_relative_database_override_is_resolved_from_repository(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    monkeypatch.chdir(tmp_path)

    manifest = release_manifest.build_manifest(root, Path("store/market.duckdb"))

    assert manifest["database_schema"]["status"] == "ok"
    assert manifest["database_schema"]["location"]["path"] == "store/market.duckdb"


def test_internal_database_read_path_preserves_requested_location(tmp_path):
    root = _repository(tmp_path)
    requested = root / "store" / "market.duckdb"
    alternate = tmp_path / "secured-source.duckdb"
    connection = duckdb.connect(str(alternate))
    connection.execute("CREATE TABLE secured_probe (id INTEGER)")
    connection.close()

    manifest = release_manifest.build_manifest(
        root, requested, _database_read_path=alternate
    )

    assert manifest["database_schema"]["status"] == "ok"
    assert manifest["database_schema"]["table_count"] == 1
    assert manifest["database_schema"]["location"] == {
        "kind": "repository-relative",
        "path": "store/market.duckdb",
    }


def test_internal_database_connection_reads_schema_while_transaction_is_open(
    tmp_path,
):
    root = _repository(tmp_path)
    database = root / "store" / "market.duckdb"
    connection = duckdb.connect(str(database))
    connection.execute("BEGIN TRANSACTION")
    try:
        manifest = release_manifest.build_manifest(
            root,
            database,
            _database_connection=connection,
        )
    finally:
        connection.execute("ROLLBACK")
        connection.close()

    assert manifest["database_schema"]["status"] == "ok"
    assert manifest["database_schema"]["table_count"] == 1
    assert manifest["identity_complete"] is True
    assert manifest["release_eligible"] is True


def test_internal_database_connection_must_match_requested_database(tmp_path):
    root = _repository(tmp_path)
    database = root / "store" / "market.duckdb"
    other = tmp_path / "other.duckdb"
    connection = duckdb.connect(str(other))
    connection.execute("CREATE TABLE unrelated (id INTEGER)")
    try:
        manifest = release_manifest.build_manifest(
            root,
            database,
            _database_connection=connection,
        )
    finally:
        connection.close()

    assert manifest["database_schema"]["status"] == "unsafe"
    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "database-schema-path-unsafe" in manifest["reasons"]


def test_internal_database_connection_rejects_path_replacement(
    tmp_path,
    monkeypatch,
):
    root = _repository(tmp_path)
    database = root / "store" / "market.duckdb"
    replacement = tmp_path / "replacement.duckdb"
    displaced = tmp_path / "displaced.duckdb"
    replacement_connection = duckdb.connect(str(replacement))
    replacement_connection.execute("CREATE TABLE replacement_probe (id INTEGER)")
    replacement_connection.close()
    connection = duckdb.connect(str(database))
    original_catalog = release_manifest._database_catalog
    replaced = False

    def catalog_then_replace(actual):
        nonlocal replaced
        result = original_catalog(actual)
        if not replaced:
            replaced = True
            database.replace(displaced)
            replacement.replace(database)
        return result

    monkeypatch.setattr(
        release_manifest,
        "_database_catalog",
        catalog_then_replace,
    )
    try:
        manifest = release_manifest.build_manifest(
            root,
            database,
            _database_connection=connection,
        )
    finally:
        connection.close()

    assert replaced is True
    assert manifest["database_schema"]["status"] == "unsafe"
    assert manifest["identity_complete"] is False
    assert manifest["release_eligible"] is False
    assert "database-schema-path-unsafe" in manifest["reasons"]


def test_missing_required_file_fails_closed(tmp_path):
    root = _repository(tmp_path)
    (root / "uv.lock").unlink()

    manifest = release_manifest.build_manifest(root)

    assert manifest["release_eligible"] is False
    assert manifest["identity_complete"] is False
    assert "dependencies-incomplete" in manifest["reasons"]
    assert manifest["dependencies"]["sha256"] is None
    assert manifest["dependencies"]["files"]["uv.lock"] is None


def test_symlinked_required_file_fails_closed_without_hashing_external_bytes(tmp_path):
    root = _repository(tmp_path)
    dependency = root / "uv.lock"
    external = tmp_path / "external.lock"
    external.write_text(dependency.read_text())
    dependency.unlink()
    dependency.symlink_to(external)

    manifest = release_manifest.build_manifest(root)

    assert manifest["release_eligible"] is False
    assert manifest["identity_complete"] is False
    assert "dependencies-incomplete" in manifest["reasons"]
    assert manifest["dependencies"]["sha256"] is None
    assert manifest["dependencies"]["files"]["uv.lock"] is None
    assert manifest["git"]["working_tree"]["sha256"] is not None


def test_required_file_below_symlinked_directory_fails_closed(tmp_path):
    root = _repository(tmp_path)
    external = tmp_path / "external-ui"
    (root / "ui").replace(external)
    (root / "ui").symlink_to(external, target_is_directory=True)

    manifest = release_manifest.build_manifest(root)

    assert manifest["release_eligible"] is False
    assert manifest["identity_complete"] is False
    assert "dependencies-incomplete" in manifest["reasons"]
    assert manifest["dependencies"]["files"]["ui/package-lock.json"] is None


@pytest.mark.parametrize("replacement_type", ["symlink", "fifo"])
def test_file_set_rejects_required_file_replaced_after_precheck(
    tmp_path, monkeypatch, replacement_type
):
    root = _repository(tmp_path)
    relative = "uv.lock"
    target = root / relative
    displaced = tmp_path / "original.lock"
    original_check = release_manifest._is_in_tree_regular_file
    replaced = False

    def check_then_replace(repo_root, requested_relative):
        nonlocal replaced
        result = original_check(repo_root, requested_relative)
        if requested_relative == relative and not replaced:
            replaced = True
            target.replace(displaced)
            if replacement_type == "symlink":
                target.symlink_to(displaced)
            else:
                os.mkfifo(target)
        return result

    monkeypatch.setattr(
        release_manifest, "_is_in_tree_regular_file", check_then_replace
    )

    result = release_manifest._file_set(root, (relative,))

    assert replaced is True
    assert result == {
        "sha256": None,
        "file_count": 1,
        "files": {relative: None},
    }


def test_stable_release_file_read_rejects_visible_replacement(tmp_path, monkeypatch):
    root = _repository(tmp_path)
    target = root / "uv.lock"
    target_inode = target.stat().st_ino
    displaced = tmp_path / "original.lock"
    replacement = tmp_path / "replacement.lock"
    replacement.write_bytes(target.read_bytes())
    original_read = release_manifest.os.read
    replaced = False

    def read_then_replace(descriptor, size):
        nonlocal replaced
        chunk = original_read(descriptor, size)
        if chunk and not replaced and os.fstat(descriptor).st_ino == target_inode:
            replaced = True
            target.replace(displaced)
            replacement.replace(target)
        return chunk

    monkeypatch.setattr(release_manifest.os, "read", read_then_replace)

    with pytest.raises(OSError, match="changed during read"):
        release_manifest._read_stable_regular_file(target)

    assert replaced is True


def test_symlinked_research_source_invalidates_runtime_identity(tmp_path):
    root = _repository(tmp_path)
    source = root / "engine" / "runtime.py"
    external = tmp_path / "external-runtime.py"
    external.write_text(source.read_text())
    source.unlink()
    source.symlink_to(external)

    manifest = release_manifest.build_manifest(root)

    assert manifest["release_eligible"] is False
    assert manifest["identity_complete"] is False
    assert "research-runtime-incomplete" in manifest["reasons"]
    assert manifest["research_runtime"]["sha256"] is None
    assert manifest["research_runtime"]["file_count"] > 0
    assert manifest["git"]["working_tree"]["sha256"] is not None


def test_untracked_required_file_is_not_a_release_candidate(tmp_path):
    root = _repository(tmp_path)
    _git(root, "rm", "--cached", "ui/trading-engine-ui.service")

    manifest = release_manifest.build_manifest(root)

    assert manifest["identity_complete"] is True, manifest["reasons"]
    assert manifest["release_eligible"] is False
    assert "required-files-untracked" in manifest["reasons"]
    assert manifest["git"]["untracked_required_files"] == [
        "ui/trading-engine-ui.service"
    ]


def test_cli_dirty_override_only_allows_diagnostic_exit(monkeypatch, capsys, tmp_path):
    root = _repository(tmp_path)
    (root / "local-note.txt").write_text("uncommitted\n")

    assert release_manifest.main(["--repo-root", str(root)]) == 1
    first = json.loads(capsys.readouterr().out)
    assert first["status"] == "non-releasable"
    assert first["release_eligible"] is False

    assert release_manifest.main(["--repo-root", str(root), "--allow-dirty"]) == 0
    second = json.loads(capsys.readouterr().out)
    assert second["status"] == "non-releasable"
    assert second["release_eligible"] is False
