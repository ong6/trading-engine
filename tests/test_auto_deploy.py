"""tools/auto_deploy.py decides against real git repositories and fake host services."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tools import auto_deploy, ops_digest, release_deploy, repin

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
SAFE = datetime(2026, 11, 23, 10, 0, tzinfo=UTC)
DIGEST = "d" * 64


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


def _write(repo: Path, relative: str, text: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _commit(repo: Path, message: str, files: dict[str, str] | None = None) -> str:
    for relative, text in (files or {}).items():
        _write(repo, relative, text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _module(version: int = 7, digest: str = DIGEST) -> str:
    return (f"RUNTIME_CONTRACT_VERSION = {version}\n"
            f'EXPECTED_RUNTIME_CONTRACT_SHA256 = (\n    "{digest}"\n)\n')


def _report(family: repin.Family, digest: str = DIGEST) -> str:
    identity = {"runtime_contract_version": 7, "runtime_contract_sha256": digest}
    return json.dumps({"status": "ACCUMULATING", "frozen_runtime": identity}
                      if family.frozen_key else identity)


class FakeDeployer(auto_deploy.Deployer):
    def __init__(self, *args, green=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.green = set(green)
        self.moment = SAFE
        self.held: set[str] = set()
        self.running: list[str] = []
        self.calls: list[str] = []
        self.post_ok = True

    def now(self):
        return self.moment

    def lock_held(self, path):
        return path.name in self.held

    def producers(self):
        return self.running

    def ci_conclusions(self):
        return {sha: True for sha in self.green}

    def gate(self, worktree, deployed):
        self.calls.append(f"gate:{deployed[:7]}")
        assert (worktree / "README.md").exists()
        assert (worktree / ".venv").resolve() == (self.root / ".venv").resolve()
        assert _git(worktree, "status", "--porcelain", "--untracked-files=normal") == ""
        return {"gate": "PASS"}

    def automation(self, mode):
        self.calls.append(mode)
        return 0, {"status": "ok"}

    def post_check(self, expected):
        self.calls.append("post-check")
        if not self.post_ok:
            raise release_deploy.DeployError("/meta forward_review is INVALID")
        return {"generation_id": "g1"}


@pytest.fixture
def host(tmp_path: Path, monkeypatch):
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    _git(seed, "checkout", "-q", "-b", "main")
    files = {"README.md": "engine\n"}
    for family in repin.FAMILIES:
        files[family.path] = _module()
        files[family.report] = _report(family)
    for relative, text in files.items():
        _write(seed, relative, text)
    _commit(seed, "deployed")
    _git(seed, "push", "-q", "origin", "main")
    live = tmp_path / "live"
    _git(tmp_path, "clone", "-q", str(origin), str(live))
    (tmp_path / "venv/bin").mkdir(parents=True)
    (live / ".venv").symlink_to(tmp_path / "venv")
    (live / ".git/info/exclude").write_text("/.venv\n")
    return {"origin": origin, "seed": seed, "live": live, "tmp": tmp_path}


def _deployer(host, **kwargs) -> FakeDeployer:
    return FakeDeployer(engine_root=host["live"], state_dir=host["tmp"] / "state",
                        logs_dir=host["tmp"] / "logs",
                        autopush_lock=host["tmp"] / "autopush.lock", **kwargs)


def _push(host, message: str, files: dict[str, str]) -> str:
    sha = _commit(host["seed"], message, files)
    _git(host["seed"], "push", "-q", "origin", "main")
    return sha


@pytest.mark.parametrize("clock, blocked", [
    ("14:04", False), ("14:05", True), ("14:34", True), ("14:35", False),
    ("22:29", False), ("22:30", True), ("00:00", True), ("02:59", True), ("03:00", False),
])
def test_blocked_windows(clock, blocked):
    hour, minute = map(int, clock.split(":"))
    assert auto_deploy.in_blocked_window(SAFE.replace(hour=hour, minute=minute)) is blocked


def test_skips_in_a_window_while_a_producer_runs_or_a_lock_is_held(host):
    deployer = _deployer(host)
    deployer.moment = SAFE.replace(hour=23)
    with pytest.raises(auto_deploy.Stop, match="skipped:window"):
        deployer.decide(execute=False)
    deployer.moment = SAFE
    deployer.held = {".nightly.lock"}
    with pytest.raises(auto_deploy.Stop, match="skipped:producer-lock:.nightly.lock"):
        deployer.decide(execute=False)
    deployer.held = {"release-deploy.lock"}
    with pytest.raises(auto_deploy.Stop, match="skipped:release-transaction"):
        deployer.decide(execute=False)
    deployer.held, deployer.running = set(), ["bash /x/engine/run_daily.sh"]
    with pytest.raises(auto_deploy.Stop, match="skipped:producer-running"):
        deployer.decide(execute=False)


def test_lock_globs_find_running_guards(host):
    (host["live"] / ".nightly.running.lock").write_text("")
    deployer = _deployer(host)
    deployer.held = {".nightly.running.lock"}
    assert deployer.busy() == "producer-lock:.nightly.running.lock"


def test_up_to_date_and_no_green_ci(host):
    deployer = _deployer(host)
    with pytest.raises(auto_deploy.Stop, match="skipped:up-to-date"):
        deployer.decide(execute=False)
    _push(host, "code", {"engine/x.py": "x = 1\n"})
    with pytest.raises(auto_deploy.Stop, match="skipped:no-green-ci"):
        deployer.decide(execute=False)


def test_content_commit_needs_green_code_below_it(host):
    code = _push(host, "code", {"engine/x.py": "x = 1\n"})
    content = _push(host, "data", {"data/reports/a.json": "{}"})
    deployer = _deployer(host, green={content})
    deployed = _git(host["live"], "rev-parse", "HEAD")
    deployer.refresh_mirror()
    with pytest.raises(auto_deploy.Stop, match="no-green-ci"):
        deployer.pick_target(deployed, content)
    deployer.green = {content, code}
    assert deployer.pick_target(deployed, content) == content
    deployer.green = {code}
    assert deployer.pick_target(deployed, content) == code


def test_dry_run_would_deploy_without_touching_the_live_checkout(host):
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={target})
    before = _git(host["live"], "rev-parse", "HEAD")
    decision = deployer.decide(execute=False)
    assert decision.label == "dry-run would-deploy"
    assert decision.detail["target"] == target and decision.detail["migrations"] == []
    assert _git(host["live"], "rev-parse", "HEAD") == before
    assert _git(host["live"], "rev-parse", "origin/main") == before  # live was not fetched
    receipt = json.loads(deployer.record(decision, SAFE, SAFE).read_text())
    assert receipt["work_status"] == "noop" and receipt["decision"] == "dry-run would-deploy"
    assert ops_digest._job_receipt_row(receipt)[2] == "auto-deploy"
    state = json.loads((host["tmp"] / "state/state.json").read_text())
    assert state["deployed_sha"] == before


@pytest.mark.parametrize("path, reason", [
    ("uv.lock", "dependencies"), ("ui/package.json", "dependencies"),
    ("engine/migrations/0001_new.py", "schema-migration"),
])
def test_needs_human_for_release_deploy_changes(host, path, reason):
    target = _push(host, "risky", {path: "x\n"})
    deployer = _deployer(host, green={target})
    with pytest.raises(auto_deploy.Stop, match=f"needs-human:{reason}"):
        deployer.decide(execute=False)


def test_needs_human_for_a_contract_version_bump(host):
    target = _push(host, "bump", {"engine/forward_review.py": _module(version=8)})
    deployer = _deployer(host, green={target})
    with pytest.raises(auto_deploy.Stop, match="needs-human:contract-version:sector"):
        deployer.decide(execute=False)


def test_closure_change_is_rehearsed(host, monkeypatch):
    target = _push(host, "closure", {"engine/xs_forward_review.py": _module(digest="e" * 64)})
    deployer = _deployer(host, green={target})
    seen = []
    monkeypatch.setattr(repin, "rehearse", lambda root, families, live: seen.append(
        families) or {"status": "ok", "families": families})
    decision = deployer.decide(execute=False)
    assert decision.detail["migrations"] == ["xs"] and seen == [["xs"]]


def test_live_checkout_rules(host):
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={target})
    _commit(host["live"], "nightly", {"data/reports/n.json": "{}"})
    assert deployer.decide(execute=False).detail["local_data_commits"] == 1
    _commit(host["live"], "local code", {"engine/y.py": "y = 1\n"})
    with pytest.raises(auto_deploy.Stop, match="live-has-code-commits"):
        deployer.decide(execute=False)
    _git(host["live"], "reset", "-q", "--hard", "HEAD~1")
    _write(host["live"], "README.md", "dirty\n")
    with pytest.raises(auto_deploy.Stop, match="live-tree-dirty"):
        deployer.decide(execute=False)


def test_execute_fast_forwards_rebases_data_and_records(host):
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    _commit(host["live"], "nightly", {"data/reports/n.json": "{}"})
    deployer = _deployer(host, green={target})
    decision = deployer.decide(execute=True)
    assert decision.outcome == "deployed", decision
    assert _git(host["live"], "rev-parse", "HEAD~1") == target
    assert (host["live"] / "data/reports/n.json").exists()
    assert deployer.calls[-2:] == ["--apply", "post-check"]
    deployer.record(decision, SAFE, SAFE)
    state = json.loads((host["tmp"] / "state/state.json").read_text())
    assert state["deployed_sha"] == target
    assert state["last_attempt"]["decision"] == "deployed"


def test_failed_post_check_rolls_back(host):
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={target})
    deployer.post_ok = False
    before = _git(host["live"], "rev-parse", "HEAD")
    deployer.ops._wait_health = lambda: ({"ok": True}, {})
    decision = deployer.decide(execute=True)
    assert decision.label == "rolled-back"
    assert _git(host["live"], "rev-parse", "HEAD") == before
    assert deployer.calls[-3:] == ["--apply", "post-check", "--apply"]
    receipt = json.loads(deployer.record(decision, SAFE, SAFE).read_text())
    assert receipt["work_status"] == "terminal_failure"
    assert "INVALID" in receipt["reason"]


def test_execute_rechecks_the_window_before_mutating(host):
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={target})
    deployer.moment = SAFE.replace(hour=22, minute=15)  # the deploy could run into the nightly
    before = _git(host["live"], "rev-parse", "HEAD")
    with pytest.raises(auto_deploy.Stop, match="skipped:window"):
        deployer.decide(execute=True)
    assert _git(host["live"], "rev-parse", "HEAD") == before


def test_ci_runs_are_etag_cached(host, monkeypatch):
    deployer = auto_deploy.Deployer(engine_root=host["live"], state_dir=host["tmp"] / "state")
    monkeypatch.setattr(auto_deploy, "github_token", lambda: "secret")
    responses = [
        (200, {"ETag": '"v1"'}, json.dumps({"workflow_runs": [
            {"name": "ci", "event": "push", "head_branch": "main", "head_sha": "a",
             "conclusion": "success"},
            {"name": "ci", "event": "push", "head_branch": "main", "head_sha": "b",
             "conclusion": "failure"},
            {"name": "other", "event": "push", "head_branch": "main", "head_sha": "c",
             "conclusion": "success"}]}).encode()),
        (304, {}, b""),
        (403, {"X-RateLimit-Reset": "1"}, b""),
    ]
    sent = []
    deployer.http_get = lambda url, headers: sent.append(headers) or responses.pop(0)
    assert deployer.ci_conclusions() == {"a": True, "b": False}
    assert deployer.ci_conclusions() == {"a": True, "b": False}
    assert sent[1]["If-None-Match"] == '"v1"' and sent[1]["Authorization"] == "Bearer secret"
    assert "secret" not in (host["tmp"] / "state/ci-runs.json").read_text()
    with pytest.raises(auto_deploy.Stop, match="skipped:ci-unavailable"):
        deployer.ci_conclusions()


def test_github_token_comes_from_the_environment_or_the_hosts_file(tmp_path, monkeypatch):
    hosts = tmp_path / "hosts.yml"
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert auto_deploy.github_token(hosts) is None
    hosts.write_text("github.com:\n    user: someone\n    oauth_token: abc123\n")
    assert auto_deploy.github_token(hosts) == "abc123"
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")
    assert auto_deploy.github_token(hosts) == "from-env"


def test_main_records_a_failed_decision(host, monkeypatch, capsys):
    monkeypatch.setattr(auto_deploy.Deployer, "decide",
                        lambda self, execute: (_ for _ in ()).throw(OSError("disk")))
    code = auto_deploy.main(["--engine-root", str(host["live"]), "--state-dir",
                             str(host["tmp"] / "state"), "--logs-dir", str(host["tmp"] / "l")])
    assert code == 1
    assert json.loads(capsys.readouterr().out)["decision"] == "failed:OSError"


def test_receipts_match_the_registered_spec_and_are_pruned(host):
    deployer = _deployer(host)
    old = auto_deploy.Decision("skipped", "window")
    stale = deployer.record(old, SAFE.replace(month=10), SAFE.replace(month=10))
    fresh = json.loads(deployer.record(old, SAFE, SAFE).read_text())
    assert not stale.exists()
    spec = auto_deploy.job_contract.load_registry(auto_deploy.REPO_ROOT).get("auto-deploy")
    assert fresh["spec_sha256"] == spec.spec_sha256
    assert ops_digest.registered_receipt_alerts([fresh], SAFE) == ([], [], [])


def test_rollback_restores_migrated_reports(host, monkeypatch):
    target = _push(host, "closure", {"engine/xs_forward_review.py": _module(digest="e" * 64)})
    deployer = _deployer(host, green={target})
    deployer.post_ok = False
    deployer.ops._wait_health = lambda: ({"ok": True}, {})
    monkeypatch.setattr(repin, "rehearse", lambda *args: {"status": "ok"})
    report = host["live"] / "data/reports/forward/xs_momentum_12_1.json"
    published = report.read_text()
    real_run = deployer.run

    def run(argv, **kwargs):
        if "--migrate-runtime-contract" in argv:
            report.write_text(published.replace(DIGEST, "e" * 64))
            return subprocess.CompletedProcess(argv, 0, "", "")
        return real_run(argv, **kwargs)

    deployer.run = run
    before = _git(host["live"], "rev-parse", "HEAD")
    decision = deployer.decide(execute=True)
    assert decision.label == "rolled-back", decision
    assert report.read_text() == published
    assert _git(host["live"], "rev-parse", "HEAD") == before
    assert _git(host["live"], "status", "--porcelain") == ""
    assert "migrate:xs:0" in deployer.steps


def test_running_producers_matches_both_root_spellings_and_exempts_minute_capture(tmp_path):
    real = tmp_path / "data" / "engine"
    real.mkdir(parents=True)
    link = tmp_path / "engine"
    link.symlink_to(real)
    listing = "\n".join([
        f"101 /bin/bash {link}/engine/run_daily.sh",
        f"102 {real}/.venv/bin/python -m engine.collect",
        f"103 {link}/.venv/bin/python -m tools.free_massive_minute --max-runtime-hours 23",
        f"104 {link}/.venv/bin/python -m server.main",
        "105 /usr/bin/python -m engine.collect",
        f"106 /bin/bash {link}/engine/run_daily.sh",
    ])
    found = auto_deploy.running_producers(listing, link, own_pid=106)
    assert found == [f"/bin/bash {link}/engine/run_daily.sh",
                     f"{real}/.venv/bin/python -m engine.collect"]
