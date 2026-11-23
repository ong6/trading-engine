"""tools/repin.py writes the next registration revision mechanically, or refuses."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from engine.lib.provenance import canonical_sha256
from tools import repin

ROOT = Path(__file__).resolve().parents[1]
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
SECTOR_OLD = "a" * 64
REASON_24 = (
    "Revision 24 after deployed revision 23: the league step no longer treats P15 window marks "
    "for a session as that session being stepped. Sector v12 and XS v23 keep their contract "
    "versions and migrate only the literal deployed revision-23 digests; E1 v8 is unchanged. "
    "No admission gate, label rule, fetch limit, frozen statistic, strategy, model, schedule or "
    "retained outcome is tuned. The deployed revision-20 model amendment and revision-21 to "
    "revision-23 collection, storage and recovery behavior remain in force.")

MODULE = '''import hashlib
import json
import os
import sys
from pathlib import Path

RUNTIME_CONTRACT_VERSION = {version}
SUPERSEDED_RUNTIME_CONTRACT_SHA256 = '{superseded}'
EXPECTED_RUNTIME_CONTRACT_SHA256 = (
    "{expected}"
)
RUNTIME_CONTRACT_FILES = ('{closure}',)
# The deployed code identity of this same contract version (revision 1, installed
# 2026-01-01). Revision 2 changes something unrelated;
# it does not change what the pair computes.
AMENDED_RUNTIME_CONTRACT_SHA256 = '{amended}'
{amended_files}

def _runtime_contract_sha256():
    root = Path(__file__).resolve().parents[1]
    return hashlib.sha256((root / '{closure}').read_bytes()).hexdigest()


if __name__ == "__main__":
    report = Path(os.environ["TRADING_ENGINE_DATA_DIR"]) / "{report_rel}"
    payload = json.loads(report.read_text())
    frozen = payload["frozen_runtime"] if "frozen_runtime" in payload else payload
    frozen["runtime_contract_sha256"] = _runtime_contract_sha256()
    if os.environ.get("REHEARSAL_TAMPER"):
        payload["status"] = "CONTINUE"
    report.write_text(json.dumps(payload))
    sys.exit(0)
'''


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(repo: Path, relative: str, text: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _module(family: repin.Family, digest: str) -> str:
    closure = f"sim/{family.key}_closure.py"
    files = ("AMENDED_RUNTIME_CONTRACT_FILES = (\n    'engine/old.py',\n)"
             if family.frozen_key else "")
    return MODULE.format(version=7, superseded="c" * 64, expected=digest, closure=closure,
                         amended=SECTOR_OLD, amended_files=files,
                         report_rel=str(Path(family.report).relative_to("data")))


def _report(family: repin.Family, digest: str, status: str = "ACCUMULATING") -> dict:
    identity = {"runtime_contract_version": 7, "runtime_contract_sha256": digest,
                "runtime_contract_files": [f"sim/{family.key}_closure.py"]}
    if family.frozen_key:
        return {"status": status, "frozen_runtime": identity}
    return identity


def _registration(repo: Path, files: list[str], revision: int, reason: str) -> dict:
    payload = {
        "books": {"config_sha256": "x"},
        "code_identity": {"files": {path: _sha(repo / path) for path in files},
                          "source_commit": ""},
        "registration_revision": revision,
        "revision_reason": reason,
        "schema_version": 1,
    }
    return payload


def _seal(repo: Path, payload: dict) -> None:
    payload.pop("registration_sha256", None)
    payload["registration_sha256"] = canonical_sha256(payload)
    _write(repo, repin.REGISTRATION, json.dumps(payload, indent=2) + "\n")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    repo = tmp_path / "engine"
    repo.mkdir()
    _git(repo, "init", "-q")
    _write(repo, "engine/__init__.py", "")
    _write(repo, "farm/__init__.py", "")
    _write(repo, "sim/pinned.py", "VALUE = 1\n")
    for family in repin.FAMILIES:
        closure = repo / f"sim/{family.key}_closure.py"
        _write(repo, f"sim/{family.key}_closure.py", f"# {family.key} v1\n")
        digest = _sha(closure)
        _write(repo, family.path, _module(family, digest))
        _write(repo, family.report, json.dumps(_report(family, digest), indent=2))
        fixture = _report(family, SECTOR_OLD)
        _write(repo, family.fixture, json.dumps(
            fixture.get("frozen_runtime", fixture), indent=2) + "\n")
    _write(repo, repin.XS_TEST, f'def test_revision2_migration_requires_literal_revision1_'
           f'predecessor():\n    assert "{SECTOR_OLD}"\n')
    _write(repo, repin.REGISTRATION_TEST,
           '    assert registration["registration_revision"] == 1\n'
           '    assert registration["revision_reason"] == "first"\n')
    _commit(repo, "code")
    pinned = ["sim/pinned.py", *(family.path for family in repin.FAMILIES),
              *(f"sim/{family.key}_closure.py" for family in repin.FAMILIES)]
    payload = _registration(repo, pinned, 1, "first")
    payload["code_identity"]["source_commit"] = _git(repo, "rev-parse", "HEAD")
    _seal(repo, payload)
    _commit(repo, "register revision 1")
    _git(repo, "tag", "deployed")
    return repo


def _plan(repo: Path, sentence: str | None = "the change is safe.") -> repin.Plan:
    return repin.plan(repo, "deployed", sentence, derived_check=lambda _root: None)


def _reason(tmp_path: Path, text: str = "the nightly no longer pulls code.") -> Path:
    path = tmp_path / "reason.txt"
    path.write_text(text + "\n")
    return path


def test_current_checkout_needs_nothing(repo):
    assert not _plan(repo).needed


def test_pinned_change_writes_the_next_revision(repo, tmp_path, monkeypatch):
    _write(repo, "sim/pinned.py", "VALUE = 2\n")
    code = _commit(repo, "change a pinned file")
    monkeypatch.setattr(repin, "_derived_identities", lambda _root: None)
    assert repin.main(["--root", str(repo), "--deployed", "deployed", "--check"]) == 2
    assert _git(repo, "rev-parse", "HEAD") == code

    assert repin.main(["--root", str(repo), "--deployed", "deployed",
                       "--reason-file", str(_reason(tmp_path))]) == 0
    registration = json.loads((repo / repin.REGISTRATION).read_text())
    recorded = registration.pop("registration_sha256")
    assert recorded == canonical_sha256(registration)
    assert registration["registration_revision"] == 2
    assert registration["code_identity"]["source_commit"] == code
    assert registration["code_identity"]["files"]["sim/pinned.py"] == _sha(repo / "sim/pinned.py")
    assert registration["revision_reason"].startswith(
        "Revision 2 after deployed revision 1: the nightly no longer pulls code. "
        "E1 v7, sector v7 and XS v7 are unchanged. No admission gate")
    test = (repo / repin.REGISTRATION_TEST).read_text()
    assert '== 2\n' in test and json.dumps(registration["revision_reason"]) in test
    assert list(json.loads((repo / repin.REGISTRATION).read_text())) == [
        "books", "code_identity", "registration_revision", "revision_reason", "schema_version",
        "registration_sha256"]
    assert _git(repo, "status", "--porcelain") == ""
    assert repin.main(["--root", str(repo), "--deployed", "deployed", "--check"]) == 0


def test_closure_change_accepts_the_published_identity_first(repo):
    sector = next(family for family in repin.FAMILIES if family.key == "sector")
    published = json.loads((repo / sector.report).read_text())["frozen_runtime"]
    _write(repo, "sim/sector_closure.py", "# sector v2\n")
    _commit(repo, "change the sector closure")
    result = _plan(repo)
    assert result.changed_families == ["sector"]
    assert sorted(result.contract_edits) == [sector.path, sector.fixture]
    commits = repin.apply(repo, result)
    assert len(commits) == 2
    module = (repo / sector.path).read_text()
    assert _sha(repo / "sim/sector_closure.py") in module
    assert f"AMENDED_RUNTIME_CONTRACT_SHA256 = '{published['runtime_contract_sha256']}'" in module
    assert "AMENDED_RUNTIME_CONTRACT_FILES = (\n    'sim/sector_closure.py',\n)" in module
    assert "(revision 1, installed\n# " in module
    assert "Revision 2 changes code inside this closure;\n" in module
    fixture = json.loads((repo / sector.fixture).read_text())
    assert fixture["runtime_contract_sha256"] == published["runtime_contract_sha256"]
    registration = json.loads((repo / repin.REGISTRATION).read_text())
    assert registration["code_identity"]["source_commit"] == commits[0]
    assert "Sector v7 keeps its contract version and migrates only the literal deployed " \
           "revision-1 digest; E1 v7 and XS v7 are unchanged." in registration["revision_reason"]
    assert not _plan(repo, None).needed


def test_xs_closure_change_updates_the_literal_predecessor_test(repo):
    _write(repo, "sim/xs_closure.py", "# xs v2\n")
    _commit(repo, "change the xs closure")
    result = _plan(repo)
    assert result.changed_families == ["xs"]
    test = result.contract_edits[repin.XS_TEST]
    assert "def test_revision2_migration_requires_literal_revision1_predecessor(" in test
    published = json.loads((repo / "data/reports/forward/xs_momentum_12_1.json").read_text())
    assert published["frozen_runtime"]["runtime_contract_sha256"] in test


@pytest.mark.parametrize("change, message", [
    (lambda repo: _write(repo, "engine/forward_review.py", (repo / "engine/forward_review.py")
                         .read_text().replace("RUNTIME_CONTRACT_VERSION = 7",
                                              "RUNTIME_CONTRACT_VERSION = 8")),
     "frozen constants changed: RUNTIME_CONTRACT_VERSION"),
    (lambda repo: _write(repo, "farm/experiment_runner.py", (repo / "farm/experiment_runner.py")
                         .read_text().replace("SUPERSEDED_RUNTIME_CONTRACT_SHA256 = 'c",
                                              "SUPERSEDED_RUNTIME_CONTRACT_SHA256 = 'd")),
     "SUPERSEDED_RUNTIME_CONTRACT_SHA256"),
    (lambda repo: _seal(repo, {**json.loads((repo / repin.REGISTRATION).read_text()),
                               "books": {"config_sha256": "y"}}),
     "registered values changed since deployed: books"),
])
def test_refuses_registered_value_changes(repo, change, message):
    change(repo)
    _commit(repo, "tamper")
    with pytest.raises(repin.Refused, match=message):
        _plan(repo)


def test_refuses_an_invalid_published_report(repo):
    _write(repo, "data/reports/forward/sector_momentum.json", json.dumps(
        {"status": "INVALID", "frozen_runtime": {}}))
    _commit(repo, "invalid report")
    _git(repo, "tag", "-f", "deployed")
    with pytest.raises(repin.Refused, match="sector report at deployed is INVALID"):
        _plan(repo)


def test_refuses_when_derived_identities_fail_and_writes_nothing(repo, tmp_path, monkeypatch):
    _write(repo, "sim/pinned.py", "VALUE = 3\n")
    head = _commit(repo, "change")

    def failing(_root):
        raise repin.Refused("derived identities do not match the code")

    monkeypatch.setattr(repin, "_derived_identities", failing)
    assert repin.main(["--root", str(repo), "--deployed", "deployed",
                       "--reason-file", str(_reason(tmp_path))]) == 2
    assert _git(repo, "rev-parse", "HEAD") == head and _git(repo, "status", "--porcelain") == ""


def test_refuses_a_dirty_tree_and_a_missing_reason(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(repin, "_derived_identities", lambda _root: None)
    _write(repo, "sim/pinned.py", "VALUE = 4\n")
    assert repin.main(["--root", str(repo), "--deployed", "deployed"]) == 2
    _commit(repo, "change")
    with pytest.raises(repin.Refused, match="needs --reason-file"):
        _plan(repo, None)
    with pytest.raises(repin.Refused, match="one sentence"):
        repin.read_sentence(_reason(tmp_path, 'no full stop "quoted"'))


def test_reason_template_reproduces_the_revision_24_form():
    sentence = ("the league step no longer treats P15 window marks for a session as that "
                "session being stepped.")
    versions = {"e1": 8, "sector": 12, "xs": 23}
    assert repin.reason_text(24, 23, sentence, versions, ["sector", "xs"]) == REASON_24


def test_rehearsal_allows_only_runtime_identity_changes(repo, tmp_path, monkeypatch):
    engine_root = tmp_path / "live"
    (engine_root / "store/snapshots").mkdir(parents=True)
    (engine_root / "store/snapshots/market-20261101T000000Z.duckdb").write_bytes(b"")
    (engine_root / "data/reports/forward").mkdir(parents=True)
    sector = next(family for family in repin.FAMILIES if family.key == "sector")
    published = repo / sector.report
    (engine_root / sector.report).write_text(published.read_text())
    _write(repo, "sim/sector_closure.py", "# sector v2\n")
    result = repin.rehearse(repo, ["sector"], engine_root)
    assert result["families"] == ["sector"]
    assert (engine_root / sector.report).read_text() == published.read_text()
    monkeypatch.setenv("REHEARSAL_TAMPER", "1")
    with pytest.raises(repin.Refused, match="sector rehearsal changed status"):
        repin.rehearse(repo, ["sector"], engine_root)
    assert repin.rehearse(repo, [], engine_root)["families"] == []


@pytest.mark.slow  # about 15 s: a shared clone, five closure digests and one registration test
def test_reproduces_revision_25_byte_for_byte(tmp_path, monkeypatch):
    pinned, deployed = "8a0d9baf504bb29a2bb5a0f5a4cfa5aa6b261b1b", "4534a88acfb8a03fc089c0b8c3f6033fd6c80635"
    for commit in (pinned, deployed):
        if subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=ROOT,
                          capture_output=True).returncode:
            pytest.skip("revision-25 history is not in this checkout")
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(ROOT), str(clone)],
                   check=True)
    _git(clone, "checkout", "-q", f"{pinned}^")
    reason = json.loads(_git(clone, "show", f"{pinned}:{repin.REGISTRATION}"))["revision_reason"]
    sentence = reason.split(": ", 1)[1].split(" E1 v8, sector v12")[0]
    assert repin.main(["--root", str(clone), "--deployed", deployed,
                       "--reason-file", str(_reason(tmp_path, sentence))]) == 0
    assert _git(clone, "diff", pinned, "HEAD", "--stat") == ""
