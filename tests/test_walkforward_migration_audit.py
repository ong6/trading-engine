"""Tests for the fail-closed walk-forward migration audit."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

from tools import audit_walkforward_migration as migration_audit

REPO_ROOT = Path(__file__).resolve().parents[1]
RETAINED_MIGRATION = REPO_ROOT / "data/reports/walkforward/migrations/2026-09-09-earnings-selector"


def _snapshot(tables: dict | None = None) -> dict:
    tables = {"prices": {"rows": 1}} if tables is None else tables
    payload = json.dumps(tables, sort_keys=True, separators=(",", ":"))
    return {"sha256": hashlib.sha256(payload.encode()).hexdigest(), "tables": tables}


def _artifact() -> dict:
    return {
        "config_id": "probe",
        "source_sha256": "a" * 64,
        "git_sha": "a" * 40,
        "generated_utc": "2026-09-08T00:00:00+00:00",
        "runtime_s": 10.0,
        "scratch_s": 2.0,
        "screen_s": 1.0,
        "screen_rows": 10,
        "data_snapshot": _snapshot(),
        "folds": [{"runtime_s": 3.0, "validate": {"total_return": 0.1}}],
        "summary": {"mean_validate_total": 0.1},
    }


def _write(path, payload):
    path.write_text(json.dumps(payload))


def _deeply_nested_json() -> str:
    depth = max(10_000, sys.getrecursionlimit() * 10)
    return '{"nested":' + ("[" * depth) + "0" + ("]" * depth) + "}"


def test_audit_allows_only_declared_provenance_and_runtime_fields(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    old = _artifact()
    new = _artifact()
    new.update(
        source_sha256="c" * 64,
        git_sha="d" * 40,
        generated_utc="2026-09-09T00:00:00+00:00",
        runtime_s=11.0,
        scratch_s=2.5,
        data_snapshot=_snapshot({"prices": {"rows": 2}}),
    )
    new["folds"][0]["runtime_s"] = 4.0
    _write(before / "probe.json", old)
    _write(after / "probe.json", new)
    _write(after / "retired.json", {"retained": True})

    result = migration_audit.audit(before, after)

    assert result["status"] == "equivalent"
    assert result["unexpected_difference_count"] == 0
    assert result["additional_replacement_artifacts"] == ["retired.json"]


def test_audit_reports_diagnostic_and_economic_changes_by_exact_path(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    old = _artifact()
    new = _artifact()
    new["screen_rows"] = 9
    new["screen_s"] = 1.1
    new["folds"][0]["validate"]["total_return"] = 0.2
    _write(before / "probe.json", old)
    _write(after / "probe.json", new)

    result = migration_audit.audit(before, after)

    assert result["status"] == "changed"
    assert [item["path"] for item in result["artifacts"]["probe.json"]["unexpected"]] == [
        "$.folds[0].validate.total_return",
        "$.screen_rows",
        "$.screen_s",
    ]


def test_audit_fails_closed_for_missing_replacement(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    _write(before / "probe.json", _artifact())

    result = migration_audit.audit(before, after)

    assert result["status"] == "changed"
    assert result["missing_artifacts"] == ["probe.json"]
    assert result["compared_artifacts"] == 0


@pytest.mark.parametrize("cohort", ["before", "after"])
def test_audit_rejects_symlinked_cohort_directory(tmp_path, cohort):
    real_before = tmp_path / "real-before"
    real_after = tmp_path / "real-after"
    real_before.mkdir()
    real_after.mkdir()
    _write(real_before / "probe.json", _artifact())
    _write(real_after / "probe.json", _artifact())
    before = real_before
    after = real_after
    alias = tmp_path / cohort
    alias.symlink_to(real_before if cohort == "before" else real_after, target_is_directory=True)
    if cohort == "before":
        before = alias
    else:
        after = alias

    label = {"before": "baseline", "after": "replacement"}[cohort]
    with pytest.raises(ValueError, match=f"{label} directory is unsafe"):
        migration_audit.audit(before, after)


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_audit_rejects_nonregular_json_artifact_without_blocking(tmp_path, kind):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    _write(before / "probe.json", _artifact())
    if kind == "symlink":
        target = tmp_path / "target.json"
        _write(target, _artifact())
        (after / "probe.json").symlink_to(target)
    else:
        os.mkfifo(after / "probe.json")

    with pytest.raises(ValueError, match="replacement JSON artifact is not regular"):
        migration_audit.audit(before, after)


def test_audit_rejects_inventory_change_during_comparison(tmp_path, monkeypatch):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    _write(before / "probe.json", _artifact())
    _write(after / "probe.json", _artifact())
    original = migration_audit._audit_artifact

    def compare_then_add(old, new):
        result = original(old, new)
        _write(after / "appeared.json", _artifact())
        return result

    monkeypatch.setattr(migration_audit, "_audit_artifact", compare_then_add)

    with pytest.raises(ValueError, match="replacement JSON inventory changed during audit"):
        migration_audit.audit(before, after)


def test_audit_rejects_artifact_replaced_after_inventory(tmp_path, monkeypatch):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    _write(before / "probe.json", _artifact())
    _write(after / "probe.json", _artifact())
    original = migration_audit._read_object_at
    calls = 0

    def replace_before_second_read(directory_fd, name, path, expected_metadata):
        nonlocal calls
        calls += 1
        if calls == 2:
            replacement = tmp_path / "replacement.json"
            _write(replacement, _artifact())
            replacement.replace(path)
        return original(directory_fd, name, path, expected_metadata)

    monkeypatch.setattr(migration_audit, "_read_object_at", replace_before_second_read)

    with pytest.raises(ValueError, match="JSON path changed while reading"):
        migration_audit.audit(before, after)


def test_audit_rejects_cohort_directory_replacement_during_comparison(tmp_path, monkeypatch):
    before = tmp_path / "before"
    after = tmp_path / "after"
    detached = tmp_path / "detached"
    before.mkdir()
    after.mkdir()
    _write(before / "probe.json", _artifact())
    _write(after / "probe.json", _artifact())
    original = migration_audit._audit_artifact

    def compare_then_replace(old, new):
        result = original(old, new)
        before.rename(detached)
        before.mkdir()
        _write(before / "probe.json", _artifact())
        return result

    monkeypatch.setattr(migration_audit, "_audit_artifact", compare_then_replace)

    with pytest.raises(ValueError, match="baseline directory path changed during audit"):
        migration_audit.audit(before, after)


def test_audit_rejects_invalid_replacement_json(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    _write(before / "probe.json", _artifact())
    (after / "probe.json").write_text("not json")

    with pytest.raises(ValueError, match="cannot read"):
        migration_audit.audit(before, after)


def test_audit_rejects_duplicate_json_keys(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    _write(before / "probe.json", _artifact())
    payload = json.dumps(_artifact()).replace(
        '"config_id": "probe"',
        '"config_id": "probe", "config_id": "probe"',
        1,
    )
    (after / "probe.json").write_text(payload)

    with pytest.raises(ValueError, match="duplicate JSON key: config_id"):
        migration_audit.audit(before, after)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_audit_rejects_nonfinite_json_number(tmp_path, constant):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    _write(before / "probe.json", _artifact())
    payload = json.dumps(_artifact()).replace('"screen_s": 1.0', f'"screen_s": {constant}', 1)
    (after / "probe.json").write_text(payload)

    with pytest.raises(ValueError, match="JSON (constant|number)"):
        migration_audit.audit(before, after)


def test_audit_rejects_excessively_nested_json(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    _write(before / "probe.json", _artifact())
    (after / "probe.json").write_text(_deeply_nested_json())

    with pytest.raises(ValueError, match="JSON nesting exceeds 100 levels"):
        migration_audit.audit(before, after)


def test_audit_rejects_missing_or_malformed_allowed_metadata(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    old = _artifact()
    new = _artifact()
    del new["source_sha256"]
    new["runtime_s"] = "fast"
    new["data_snapshot"] = "not-an-object"
    _write(before / "probe.json", old)
    _write(after / "probe.json", new)

    result = migration_audit.audit(before, after)

    assert result["status"] == "changed"
    assert [item["path"] for item in result["artifacts"]["probe.json"]["unexpected"]] == [
        "$.data_snapshot",
        "$.runtime_s",
        "$.source_sha256",
    ]


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("source_sha256", "not-a-sha256"),
        ("git_sha", "not-a-git-sha"),
        ("generated_utc", "not-a-timestamp"),
        ("generated_utc", "2026-09-08"),
        ("generated_utc", "2026-09-08T00:00:00"),
        ("runtime_s", -1.0),
        ("data_snapshot", {"tables": {}}),
        ("data_snapshot", {"sha256": int("1" * 64), "tables": {}}),
        ("data_snapshot", {"sha256": "b" * 64, "tables": []}),
    ],
)
def test_audit_rejects_individually_malformed_allowed_metadata(tmp_path, field, invalid_value):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    old = _artifact()
    new = _artifact()
    new[field] = invalid_value
    _write(before / "probe.json", old)
    _write(after / "probe.json", new)

    result = migration_audit.audit(before, after)

    assert result["status"] == "changed"
    assert [item["path"] for item in result["artifacts"]["probe.json"]["unexpected"]] == [
        f"$.{field}"
    ]


def test_audit_rejects_identical_invalid_metadata_and_fold_timing(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    old = _artifact()
    old["source_sha256"] = "invalid-in-both"
    old["folds"][0]["runtime_s"] = -1.0
    _write(before / "probe.json", old)
    _write(after / "probe.json", old)

    result = migration_audit.audit(before, after)

    assert result["status"] == "changed"
    assert [item["path"] for item in result["artifacts"]["probe.json"]["unexpected"]] == [
        "$.folds[0].runtime_s",
        "$.source_sha256",
    ]


def test_audit_rejects_snapshot_hash_that_does_not_match_tables(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    old = _artifact()
    new = _artifact()
    new["data_snapshot"]["sha256"] = "b" * 64
    _write(before / "probe.json", old)
    _write(after / "probe.json", new)

    result = migration_audit.audit(before, after)

    assert result["status"] == "changed"
    assert [item["path"] for item in result["artifacts"]["probe.json"]["unexpected"]] == [
        "$.data_snapshot"
    ]


def test_audit_rejects_identical_snapshot_hash_mismatch_once(tmp_path):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    artifact = _artifact()
    artifact["data_snapshot"]["sha256"] = "b" * 64
    _write(before / "probe.json", artifact)
    _write(after / "probe.json", artifact)

    result = migration_audit.audit(before, after)

    assert result["status"] == "changed"
    assert [item["path"] for item in result["artifacts"]["probe.json"]["unexpected"]] == [
        "$.data_snapshot"
    ]


def test_retained_earnings_selector_migration_reproduces_reviewed_audit():
    result = migration_audit.audit(RETAINED_MIGRATION / "before", RETAINED_MIGRATION / "after")

    assert result["status"] == "changed"
    assert result["baseline_artifacts"] == 18
    assert result["compared_artifacts"] == 18
    assert result["missing_artifacts"] == []
    assert result["additional_replacement_artifacts"] == []
    assert result["unexpected_difference_count"] == 34

    digest = hashlib.sha256()
    paths = sorted(RETAINED_MIGRATION.glob("*/*.json"))
    assert len(paths) == 36
    for path in paths:
        relative = path.relative_to(RETAINED_MIGRATION).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    assert digest.hexdigest() == "6584e73a7535ee1101ff58ffca990fab7f2e87d2cb0fce5cc7d20150f91aed24"


def test_cli_exit_code_reflects_equivalence(tmp_path, capsys):
    before = tmp_path / "before"
    after = tmp_path / "after"
    before.mkdir()
    after.mkdir()
    _write(before / "probe.json", _artifact())
    _write(after / "probe.json", _artifact())

    assert migration_audit.main([str(before), str(after)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "equivalent"

    changed = _artifact()
    changed["summary"]["mean_validate_total"] = 0.2
    _write(after / "probe.json", changed)
    assert migration_audit.main([str(before), str(after)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "changed"
