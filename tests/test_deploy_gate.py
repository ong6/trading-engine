"""tools/deploy_gate.py composes its checks' verdicts against one exact tree."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools import deploy_gate
from tools.deploy_gate import Step

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True, env={**os.environ, **GIT_ENV}).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    repo = tmp_path / "checkout"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "symbolic-ref", "HEAD", "refs/heads/main")
    (repo / "README.md").write_text("candidate\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "candidate")
    return repo


def _exits(name: str, code: int, *, shadow: bool = False, note: str = "") -> Step:
    script = f"import sys, os; print({note!r}, os.environ['TMPDIR']); sys.exit({code})"
    return Step(name, (sys.executable, "-c", script), shadow=shadow)


def _gate(repo: Path, tmp_path: Path, monkeypatch, fakes: list[Step], **kwargs):
    monkeypatch.setattr(deploy_gate, "steps", lambda *_args: fakes)
    engine_root = tmp_path / "engine"
    return deploy_gate.check(repo, base="main", receipts=tmp_path / "receipts",
                             engine_root=engine_root, **kwargs)


def test_all_pass_writes_a_receipt_keyed_by_tree(repo, tmp_path, monkeypatch):
    engine_root = tmp_path / "engine"
    (engine_root / "logs/ops").mkdir(parents=True)
    (engine_root / "logs/ops/invariants.json").write_text(json.dumps(
        {"status": "pass", "snapshot": {"name": "market-x.duckdb"}}))
    code, receipt = _gate(repo, tmp_path, monkeypatch,
                          [_exits("contract_tests", 0), _exits("registration_identity", 0)])
    tree = _git(repo, "rev-parse", "HEAD^{tree}")
    assert code == 0 and receipt["verdict"] == "pass" and receipt["tree_sha"] == tree
    stored = json.loads((tmp_path / "receipts" / f"{tree}.json").read_text())
    assert stored["steps"]["contract_tests"]["verdict"] == "pass"
    assert stored["steps"]["invariants"]["verdict"] == "pass"
    assert stored["head_commit"] == _git(repo, "rev-parse", "HEAD")
    assert stored["base"]["merge_base"] == stored["head_commit"]


def test_a_blocking_failure_refuses(repo, tmp_path, monkeypatch):
    code, receipt = _gate(repo, tmp_path, monkeypatch,
                          [_exits("contract_tests", 0), _exits("registration_identity", 1)])
    assert code == 2 and receipt["verdict"] == "refuse"
    assert receipt["refused_by"] == ["registration_identity"]


def test_shadow_invariants_only_warn(repo, tmp_path, monkeypatch):
    code, receipt = _gate(repo, tmp_path, monkeypatch,
                          [_exits("contract_tests", 0), _exits("invariants", 2, shadow=True)],
                          invariants="run")
    assert code == 0 and receipt["verdict"] == "pass"
    assert receipt["warnings"] == ["invariants"]
    assert receipt["steps"]["invariants"]["mode"] == "shadow"


def test_missing_published_invariants_is_a_warning(repo, tmp_path, monkeypatch):
    code, receipt = _gate(repo, tmp_path, monkeypatch, [_exits("contract_tests", 0)])
    assert code == 0 and receipt["warnings"] == ["invariants"]
    assert "no published invariants result" in receipt["steps"]["invariants"]["tail"][0]


def test_checks_run_with_a_private_removed_tmpdir(repo, tmp_path, monkeypatch):
    _code, receipt = _gate(repo, tmp_path, monkeypatch,
                           [_exits("contract_tests", 0, note="tmp")])
    line = receipt["steps"]["contract_tests"]["tail"][0]
    assert line.startswith("tmp ") and "deploy-gate-" in line
    assert not Path(line.split(" ", 1)[1]).exists()


def test_a_dirty_tree_cannot_be_checked(repo, tmp_path, monkeypatch):
    (repo / "README.md").write_text("edited\n")
    with pytest.raises(deploy_gate.CannotCheck, match="changes: README.md$"):
        _gate(repo, tmp_path, monkeypatch, [_exits("contract_tests", 0)])
    (repo / "README.md").write_text("candidate\n")
    (repo / "new.py").write_text("")
    with pytest.raises(deploy_gate.CannotCheck, match="new.py"):
        _gate(repo, tmp_path, monkeypatch, [_exits("contract_tests", 0)])
    assert not (tmp_path / "receipts").exists()


def test_a_tree_that_moves_during_the_check_is_not_vouched_for(repo, tmp_path, monkeypatch):
    script = "import pathlib; pathlib.Path('README.md').write_text('moved')"
    moving = Step("contract_tests", (sys.executable, "-c", script))
    with pytest.raises(deploy_gate.CannotCheck):
        _gate(repo, tmp_path, monkeypatch, [moving])
    assert not (tmp_path / "receipts").exists()


def test_cli_exit_codes(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deploy_gate, "steps", lambda *_args: [_exits("contract_tests", 1)])
    args = ["--check", str(repo), "--base", "main", "--receipts", str(tmp_path / "r"),
            "--engine-root", str(tmp_path / "engine")]
    assert deploy_gate.main(args) == 2
    assert "REFUSE" in capsys.readouterr().out
    (repo / "x").write_text("")
    assert deploy_gate.main(args) == deploy_gate.CANNOT_CHECK


def test_real_steps_cover_every_named_check(tmp_path):
    names = [step.name for step in deploy_gate.steps(tmp_path, "python", "run", tmp_path)]
    assert names == ["contract_tests", "schedule_contract", "provider_replay", "provider_env",
                     "registration_identity", "store_path_lint", "invariants"]
    published = [step.name for step in deploy_gate.steps(tmp_path, "py", "published", tmp_path)]
    assert "invariants" not in published
