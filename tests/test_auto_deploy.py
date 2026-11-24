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
        self.timers: dict = {}
        self.activating: list[str] = []
        self.crontab = ""
        self.low_disk = None
        self.api_restarts = True
        self.full: set[str] = set()
        self.healthy = True

    def now(self):
        return self.moment

    def lock_held(self, path):
        return path.name in self.held

    def producers(self):
        return self.running

    def engine_schedule(self):
        return self.timers, self.activating, self.crontab

    def disk_problem(self):
        return self.low_disk

    def check_venv(self, worktree):
        return self.root / ".venv"

    def host_healthy(self):
        self.calls.append("healthy?")
        return self.healthy

    def heal_services(self):
        self.calls.append("heal")

    def full_tier(self, sha):
        return sha in self.full

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
        restarted = {"trading-engine-api.service": {"status": "ok"}} if self.api_restarts else {}
        return 0, {"status": "ok", "changes": {"restarted_services": restarted}}

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


def test_a_lock_skip_says_whether_a_commit_was_waiting_at_the_last_fetch(host):
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={target})
    assert deployer.decide(execute=False).outcome == "would-deploy"  # refreshes the mirror
    deployer.held = {".nightly.lock"}
    with pytest.raises(auto_deploy.Stop, match="producer-lock") as stop:
        deployer.decide(execute=True)
    assert stop.value.detail["waiting_at_last_fetch"] == 1
    receipt = json.loads(deployer.record(auto_deploy.Decision(
        stop.value.outcome, stop.value.reason, stop.value.detail), SAFE, SAFE).read_text())
    assert receipt["reason"] == "skipped:producer-lock:.nightly.lock waiting_at_last_fetch=1"
    deployer.held = set()
    assert deployer.decide(execute=True).outcome == "deployed"
    deployer.held = {".nightly.lock"}
    with pytest.raises(auto_deploy.Stop, match="producer-lock") as stop:
        deployer.decide(execute=True)
    assert stop.value.detail["waiting_at_last_fetch"] == 0  # counted from the live checkout now


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
    assert not (host["tmp"] / "state/state.json").exists()  # a dry run writes no deploy state


def test_one_run_at_a_time(host, capsys):
    args = ["--engine-root", str(host["live"]), "--state-dir", str(host["tmp"] / "state"),
            "--logs-dir", str(host["tmp"] / "logs")]
    with _deployer(host).run_lock():
        assert auto_deploy.main(args) == 0
    assert json.loads(capsys.readouterr().out)["decision"] == "skipped:run-in-progress"
    assert not (host["tmp"] / "state/state.json").exists()


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
    _git(host["live"], "checkout", "-q", "--", "README.md")
    _write(host["live"], "data/reports/n.json", '{"producer": "mid-day"}')
    assert deployer.decide(execute=False).outcome == "would-deploy"


def test_execute_keeps_uncommitted_producer_data(host):
    _commit(host["seed"], "meta", {"data/_meta.json": "{}"})
    _git(host["seed"], "push", "-q", "origin", "main")
    _git(host["live"], "pull", "-q", "--ff-only")
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    _write(host["live"], "data/_meta.json", '{"fresh": true}')
    decision = _deployer(host, green={target}).decide(execute=True)
    assert decision.outcome == "deployed", decision
    assert _git(host["live"], "rev-parse", "HEAD") == target
    assert (host["live"] / "data/_meta.json").read_text() == '{"fresh": true}'


def test_execute_rebases_data_commits_over_uncommitted_producer_data(host):
    _commit(host["seed"], "meta", {"data/_meta.json": "{}"})
    _git(host["seed"], "push", "-q", "origin", "main")
    _git(host["live"], "pull", "-q", "--ff-only")
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    _commit(host["live"], "nightly", {"data/reports/n.json": "{}"})
    _write(host["live"], "data/_meta.json", '{"fresh": true}')
    decision = _deployer(host, green={target}).decide(execute=True)
    assert decision.outcome == "deployed", decision
    assert _git(host["live"], "rev-parse", "HEAD~1") == target
    assert (host["live"] / "data/_meta.json").read_text() == '{"fresh": true}'
    assert (host["live"] / "data/reports/n.json").exists()


def test_execute_waits_when_the_move_would_overwrite_producer_data(host):
    _commit(host["seed"], "meta", {"data/_meta.json": "{}"})
    _git(host["seed"], "push", "-q", "origin", "main")
    _git(host["live"], "pull", "-q", "--ff-only")
    target = _push(host, "code and meta", {"engine/x.py": "x = 1\n",
                                           "data/_meta.json": '{"upstream": 1}'})
    _write(host["live"], "data/_meta.json", '{"fresh": true}')
    deployer = _deployer(host, green={target})
    with pytest.raises(auto_deploy.Stop, match="live-data-overlap"):
        deployer.deploy(target, [], [], {})
    assert (host["live"] / "data/_meta.json").read_text() == '{"fresh": true}'


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
    assert receipt["work_status"] == "degraded"
    assert "INVALID" in receipt["reason"]


def test_a_verified_deploy_keeps_only_the_newest_two_report_backups(host):
    backups = host["tmp"] / "state/backups"
    for age, name in enumerate(("20261122T100000Z", "20261121T100000Z", "20261120T100000Z")):
        (backups / name).mkdir(parents=True)
        os.utime(backups / name, (1_000_000_000 - age,) * 2)
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={target})
    decision = deployer.decide(execute=True)
    assert decision.outcome == "deployed", decision
    # this deploy's own backup has the real clock's mtime, so it is the newest
    assert sorted(path.name for path in backups.iterdir()) == [
        "20261122T100000Z", SAFE.strftime("%Y%m%dT%H%M%SZ")]
    assert "prune-backups:2" in deployer.steps


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
    assert "secret" not in (host["tmp"] / "state/ci-runs-v2.json").read_text()
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


def test_execute_refuses_when_an_engine_start_is_due_or_a_unit_is_active(host):
    from datetime import timedelta

    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={target})
    before = _git(host["live"], "rev-parse", "HEAD")
    deployer.timers = {"trading-engine-publish-on-change.timer": SAFE + timedelta(minutes=10)}
    with pytest.raises(auto_deploy.Stop, match="skipped:timer-soon"):
        deployer.decide(execute=True)
    assert deployer.decide(execute=False).outcome == "would-deploy"  # deciding is harmless
    deployer.timers = {"trading-engine-publish-on-change.timer": SAFE + timedelta(minutes=40)}
    deployer.activating = ["trading-engine-p15-events.service"]
    with pytest.raises(auto_deploy.Stop, match="skipped:unit-active"):
        deployer.decide(execute=True)
    assert _git(host["live"], "rev-parse", "HEAD") == before


def test_deploy_ticks_keep_the_publish_on_change_starts_out_of_the_look_ahead():
    from datetime import timedelta

    def minutes(unit):
        text = (auto_deploy.REPO_ROOT / "server" / unit).read_text()
        line = next(row for row in text.splitlines() if row.startswith("OnCalendar="))
        return [int(value) for value in line.split(":")[1].split(",")]

    starts = {f"{minute}+{hour}": SAFE.replace(minute=minute) + timedelta(hours=hour)
              for minute in minutes("trading-engine-publish-on-change.timer") for hour in (0, 1)}
    for tick in minutes("trading-engine-auto-deploy.timer"):
        for delay in (1, 2, 3):  # the timer-soon check runs after the gate, about a minute in
            moment = SAFE.replace(minute=tick) + timedelta(minutes=delay)
            assert auto_deploy.scheduled_soon("", starts, moment, auto_deploy.MUTATION_LEAD) \
                is None, (tick, delay)


def test_scheduled_soon_reads_engine_cron_lines_only():
    from datetime import timedelta

    crontab = ("17 * * * * ~/news-scraper/ensure_scraper.sh >> log 2>&1\n"
               "15 5 * * 6 cd ~/trading-engine && .venv/bin/python -m tools.verify_friday_postflight\n"
               "0 2 * * 0 ~/trading-engine/engine/run_weekly_liquid.sh >> log 2>&1\n")
    saturday = datetime(2026, 11, 28, 5, 5, tzinfo=UTC)
    lead = timedelta(minutes=15)
    assert auto_deploy.scheduled_soon(crontab, {}, saturday, lead).startswith("cron:cd ~/trading")
    assert auto_deploy.scheduled_soon(crontab, {}, saturday.replace(hour=4), lead) is None
    assert auto_deploy.scheduled_soon(crontab, {}, saturday.replace(minute=10, hour=6), lead) is None
    sunday = datetime(2026, 11, 29, 1, 50, tzinfo=UTC)
    assert "run_weekly_liquid" in auto_deploy.scheduled_soon(crontab, {}, sunday, lead)
    assert auto_deploy.scheduled_soon("", {"x.timer": None}, sunday, lead) is None


def test_a_refused_target_is_not_rechecked_until_main_moves(host):
    target = _push(host, "risky", {"uv.lock": "x\n"})
    deployer = _deployer(host, green={target})
    with pytest.raises(auto_deploy.Stop) as refused:
        deployer.decide(execute=True)
    stop = refused.value
    deployer.record(auto_deploy.Decision(stop.outcome, stop.reason, stop.detail), SAFE, SAFE)
    with pytest.raises(auto_deploy.Stop, match="skipped:refused-target"):
        _deployer(host, green={target}).decide(execute=False)
    later = _push(host, "fix", {"engine/x.py": "x = 2\n"})
    with pytest.raises(auto_deploy.Stop, match="needs-human:dependencies"):
        _deployer(host, green={target, later}).decide(execute=False)


def test_a_dependency_bump_holds_back_only_itself(host):
    code = _push(host, "code", {"engine/x.py": "x = 1\n"})
    bump = _push(host, "bump", {"uv.lock": "x\n"})
    deployer = _deployer(host, green={code, bump})
    decision = deployer.decide(execute=True)
    assert decision.outcome == "deployed", decision
    assert _git(host["live"], "rev-parse", "HEAD") == code
    assert decision.detail["held_back"] == {"commit": bump, "reasons": ["dependencies"]}
    with pytest.raises(auto_deploy.Stop, match="needs-human:dependencies"):
        _deployer(host, green={code, bump}).decide(execute=False)


def test_a_rolled_back_target_is_refused_and_a_newer_green_commit_deploys(host):
    bad = _push(host, "bad", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={bad})
    deployer.post_ok = False
    deployer.ops._wait_health = lambda: ({"ok": True}, {})
    decision = deployer.decide(execute=True)
    assert decision.label == "rolled-back"
    deployer.record(decision, SAFE, SAFE)
    with pytest.raises(auto_deploy.Stop, match="skipped:refused-target"):
        _deployer(host, green={bad}).decide(execute=True)
    fix = _push(host, "fix", {"engine/x.py": "x = 2\n"})
    decision = _deployer(host, green={bad, fix}).decide(execute=True)
    assert decision.outcome == "deployed" and decision.detail["target"] == fix

@pytest.mark.parametrize("code, label", [
    (3, "skipped:gate-cannot-check"), (124, "skipped:gate-timeout"),
    (2, "needs-human:gate-refused"),
])
def test_a_gate_that_cannot_check_is_retried_and_a_refusal_needs_a_human(host, code, label):
    deployer = _deployer(host)
    deployer.run = lambda argv, **kw: subprocess.CompletedProcess(argv, code, "verdict\n", "")
    with pytest.raises(auto_deploy.Stop, match=label):
        auto_deploy.Deployer.gate(deployer, host["live"], "a" * 40)


def test_a_rolled_back_target_is_not_redeployed_after_data_only_pushes(host):
    bad = _push(host, "bad", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={bad})
    deployer.post_ok = False
    deployer.ops._wait_health = lambda: ({"ok": True}, {})
    deployer.record(deployer.decide(execute=True), SAFE, SAFE)
    data = _push(host, "data", {"data/reports/a.json": "{}"})
    with pytest.raises(auto_deploy.Stop, match="skipped:refused-target"):
        _deployer(host, green={bad, data}).decide(execute=True)
    fix = _push(host, "fix", {"engine/x.py": "x = 2\n"})  # CI not green yet: data is the target
    with pytest.raises(auto_deploy.Stop, match="skipped:refused-target"):
        _deployer(host, green={bad, data}).decide(execute=True)
    decision = _deployer(host, green={bad, data, fix}).decide(execute=True)
    assert decision.outcome == "deployed" and decision.detail["target"] == fix


def test_a_forward_test_timeout_is_retried(host):
    deployer = _deployer(host)
    deployer.run = lambda argv, **kw: subprocess.CompletedProcess(
        argv, 124 if "pytest" in argv else 0, "verdict\n", "timed out")
    with pytest.raises(auto_deploy.Stop, match="skipped:forward-tests-timeout"):
        auto_deploy.Deployer.gate(deployer, host["live"], "a" * 40)


def test_a_drill_or_a_data_only_rollback_is_not_remembered_as_bad_code(host):
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    drill = _deployer(host, green={target})
    drill.drill_rollback = True
    drill.ops._wait_health = lambda: ({"ok": True}, {})
    drill.record(drill.decide(execute=True), SAFE, SAFE)
    assert "rolled_back" not in _state(host)
    data = _push(host, "data", {"data/reports/a.json": "{}"})
    decision = _deployer(host, green={target, data}).decide(execute=True)
    assert decision.outcome == "deployed", decision
    later = _push(host, "data", {"data/reports/b.json": "{}"})
    failing = _deployer(host, green={later})
    failing.post_ok = False
    failing.ops._wait_health = lambda: ({"ok": True}, {})
    failing.record(failing.decide(execute=True), SAFE, SAFE)
    assert _state(host)["refused"]["reason"] == "rolled-back"
    assert "rolled_back" not in _state(host)  # the code it ran is the deployed code


def test_low_disk_skips_before_any_work(host):
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={target})
    deployer.low_disk = "refusing a deploy: 60.0 GiB free"
    with pytest.raises(auto_deploy.Stop, match="skipped:low-disk"):
        deployer.decide(execute=False)


def test_a_migration_without_an_api_restart_rolls_back(host, monkeypatch):
    target = _push(host, "closure", {"engine/xs_forward_review.py": _module(digest="e" * 64)})
    deployer = _deployer(host, green={target})
    deployer.api_restarts = False
    deployer.ops._wait_health = lambda: ({"ok": True}, {})
    monkeypatch.setattr(repin, "rehearse", lambda *args: {"status": "ok"})
    real_run = deployer.run
    deployer.run = lambda argv, **kw: (subprocess.CompletedProcess(argv, 0, "", "")
                                       if "--migrate-runtime-contract" in argv
                                       else real_run(argv, **kw))
    decision = deployer.decide(execute=True)
    assert decision.label == "rolled-back"
    assert "without an API restart" in decision.detail["error"]


def _state(host) -> dict:
    return json.loads((host["tmp"] / "state/state.json").read_text())


def _failed_rollback(host):
    """Deploy, fail the post-check, and fail the rollback's re-apply: the host is unverified."""
    good = _git(host["live"], "rev-parse", "HEAD")
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={target})
    deployer.post_ok = False
    applies = iter([(0, {"status": "ok"}), (1, {"status": "error", "errors": ["boom"]})])
    deployer.automation = lambda mode: next(applies)
    decision = deployer.decide(execute=True)
    assert decision.label == "rolled-back:rollback-failed", decision
    deployer.record(decision, SAFE, SAFE)
    assert _state(host)["in_flight"]["moved"] == target
    return good, target


def test_a_run_that_dies_after_moving_the_checkout_is_recovered(host):
    good = _git(host["live"], "rev-parse", "HEAD")
    _deployer(host).save_state(last_good_sha=good)
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={target})
    real_git = deployer.git

    def git(root, *args, check=True):
        out = real_git(root, *args, check=check)
        if args[:1] == ("merge",):
            raise SystemExit("killed")  # the unit timeout or a reboot, right after the move
        return out

    deployer.git = git
    with pytest.raises(SystemExit):
        deployer.decide(execute=True)
    assert _git(host["live"], "rev-parse", "HEAD") == target
    assert _state(host)["in_flight"]["previous"] == good
    decision = _deployer(host, green={target}).decide(execute=True)
    assert decision.label == "recovered:unverified-deploy", decision
    assert _git(host["live"], "rev-parse", "HEAD") == good


def test_pre_mutation_timeouts_fit_inside_the_unit_timeout():
    unit = (auto_deploy.REPO_ROOT / "server/trading-engine-auto-deploy.service").read_text()
    minutes = int(unit.split("TimeoutStartSec=", 1)[1].split("min", 1)[0])
    # a hung gate or test run ends with a receipt, and a mutation still fits after it
    assert (auto_deploy.GATE_TIMEOUT + auto_deploy.FORWARD_TESTS_TIMEOUT
            + auto_deploy.MUTATION_LEAD.total_seconds()) <= minutes * 60


def test_a_failed_rollback_is_recovered_on_the_next_run(host):
    good, target = _failed_rollback(host)
    assert _git(host["live"], "rev-parse", "HEAD") == good  # reset done, re-apply failed
    with pytest.raises(auto_deploy.Stop, match="skipped:would-recover"):
        _deployer(host, green={target}).decide(execute=False)  # a dry run never acts
    deployer = _deployer(host, green={target})
    decision = deployer.decide(execute=True)
    assert decision.label == "recovered:unverified-deploy", decision
    assert _git(host["live"], "rev-parse", "HEAD") == good
    state = _state(host)
    assert "in_flight" not in state and state["last_good_sha"] == good
    assert _git(host["live"], "for-each-ref", "refs/auto-deploy/")


def test_pending_recovery_skips_the_nightly_window_but_not_pre_open_timers_or_locks(host):
    from datetime import timedelta

    good, target = _failed_rollback(host)
    deployer = _deployer(host, green={target})
    deployer.moment = SAFE.replace(hour=14, minute=22)  # pre-open: non-engine jobs run then
    with pytest.raises(auto_deploy.Stop, match="skipped:window"):
        deployer.decide(execute=True)
    deployer.moment = SAFE.replace(hour=23)  # inside the nightly window
    deployer.timers = {"trading-engine-p15-scoring.timer": deployer.moment + timedelta(minutes=2)}
    with pytest.raises(auto_deploy.Stop, match="skipped:timer-soon"):
        deployer.decide(execute=True)
    deployer.timers = {"trading-engine-p15-scoring.timer": deployer.moment + timedelta(minutes=9)}
    deployer.held = {".nightly.lock"}
    with pytest.raises(auto_deploy.Stop, match="skipped:producer-lock"):
        deployer.decide(execute=True)
    deployer.held, deployer.activating = set(), ["trading-engine-p15-scoring.service"]
    with pytest.raises(auto_deploy.Stop, match="skipped:unit-active"):
        deployer.decide(execute=True)
    deployer.activating = []
    decision = deployer.decide(execute=True)
    assert decision.label == "recovered:unverified-deploy", decision
    assert _git(host["live"], "rev-parse", "HEAD") == good


def test_recovery_falls_back_to_a_hard_reset_and_keeps_data_commits(host):
    good = _git(host["live"], "rev-parse", "HEAD")
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    _git(host["live"], "pull", "-q", "--ff-only", "origin", "main")  # a deploy that crashed
    _deployer(host).save_state(last_good_sha=good, in_flight={
        "previous": good, "moved": target, "families": [],
        "backup": str(host["tmp"] / "state/backups/none")})
    data = _commit(host["live"], "nightly", {"data/reports/n.json": "{}"})
    (host["live"] / "engine/x.py").write_text("local edit\n")  # makes --keep refuse
    (host["live"] / "store").mkdir(exist_ok=True)
    (host["live"] / "store/untracked.duckdb").write_text("keep me")
    deployer = _deployer(host, green={target})
    decision = deployer.decide(execute=True)
    assert decision.outcome == "recovered", decision
    assert "recover:hard-reset" in deployer.steps
    assert _git(host["live"], "rev-parse", "HEAD~1") == good
    assert (host["live"] / "data/reports/n.json").exists() and decision.detail["reapplied"] == 1
    assert (host["live"] / "store/untracked.duckdb").read_text() == "keep me"
    assert data  # the original stays reachable through the pre-recovery ref


def test_a_hard_reset_recovery_keeps_uncommitted_producer_data(host):
    _commit(host["seed"], "meta", {"data/_meta.json": "{}", "data/reports/r.json": "{}"})
    _git(host["seed"], "push", "-q", "origin", "main")
    _git(host["live"], "pull", "-q", "--ff-only")
    good = _git(host["live"], "rev-parse", "HEAD")
    target = _push(host, "code", {"engine/x.py": "x = 1\n", "data/reports/r.json": '{"t": 1}'})
    _git(host["live"], "pull", "-q", "--ff-only", "origin", "main")  # a deploy that crashed
    _deployer(host).save_state(last_good_sha=good, in_flight={
        "previous": good, "moved": target, "families": [],
        "backup": str(host["tmp"] / "state/backups/none")})
    (host["live"] / "engine/x.py").write_text("local edit\n")  # makes --keep refuse
    _write(host["live"], "data/_meta.json", '{"fresh": true}')
    _write(host["live"], "data/reports/r.json", '{"producer": 2}')  # recovery changes its base
    deployer = _deployer(host, green={target})
    decision = deployer.decide(execute=True)
    assert decision.outcome == "recovered", decision
    assert "recover:hard-reset" in deployer.steps
    assert (host["live"] / "data/_meta.json").read_text() == '{"fresh": true}'
    assert (host["live"] / "data/reports/r.json").read_text() == "{}"
    kept = decision.detail["data_kept"]
    assert kept["paths"] == ["data/reports/r.json"]
    assert (Path(kept["dir"]) / "data/reports/r.json").read_text() == '{"producer": 2}'


def test_failed_recoveries_back_off_and_then_heal_services(host):
    from datetime import timedelta

    _good, target = _failed_rollback(host)
    moment = SAFE
    for attempt in range(1, auto_deploy.HEAL_AFTER + 1):
        deployer = _deployer(host, green={target})
        deployer.healthy = False
        deployer.moment = moment
        decision = deployer.decide(execute=True)
        assert decision.label == "recovery-failed:unverified-deploy"
        assert decision.detail["failures"] == attempt
        assert ("heal" in deployer.calls) == (attempt == auto_deploy.HEAL_AFTER)
        early = _deployer(host, green={target})
        early.moment = moment + timedelta(minutes=1)
        with pytest.raises(auto_deploy.Stop, match="skipped:recovery-backoff"):
            early.decide(execute=True)
        moment += auto_deploy.RECOVERY_BASE * 2 ** (attempt - 1)
    deployer = _deployer(host, green={target})
    deployer.moment = moment
    assert deployer.decide(execute=True).outcome == "recovered"
    assert "recovery" not in _state(host)


def test_a_failed_git_step_counts_as_a_failed_recovery(host):
    _good, target = _failed_rollback(host)
    deployer = _deployer(host, green={target})
    real_git = deployer.git

    def git(root, *args, check=True):
        if args[0] == "update-ref":
            raise auto_deploy.Stop("failed", "git", command="update-ref", error="locked")
        return real_git(root, *args, check=check)

    deployer.git = git
    decision = deployer.decide(execute=True)
    assert decision.label == "recovery-failed:unverified-deploy", decision
    assert decision.detail["failures"] == 1 and _state(host)["recovery"]["failures"] == 1


def test_a_healthy_hand_deploy_is_adopted_and_unhealthy_code_is_recovered(host):
    _deployer(host).save_state(last_good_sha=_git(host["live"], "rev-parse", "HEAD"))
    good = _git(host["live"], "rev-parse", "HEAD")
    hand = _push(host, "hand", {"engine/x.py": "x = 9\n"})
    _git(host["live"], "pull", "-q", "--ff-only", "origin", "main")
    deployer = _deployer(host, green={hand})
    with pytest.raises(auto_deploy.Stop, match="skipped:up-to-date"):
        deployer.decide(execute=True)
    assert f"adopted:{hand[:12]}" in deployer.steps and _state(host)["last_good_sha"] == hand
    _deployer(host).save_state(last_good_sha=good)
    sick = _deployer(host, green={hand})
    sick.healthy = False
    decision = sick.decide(execute=True)
    assert decision.label == "recovery-failed:unhealthy-unverified-code"  # still unhealthy
    assert _git(host["live"], "rev-parse", "HEAD") == good


def test_deployed_sha_follows_an_adopted_hand_deploy(host):
    first = _git(host["live"], "rev-parse", "HEAD")
    _deployer(host).save_state(last_good_sha=first, deployed_sha=first)
    hand = _push(host, "hand", {"engine/x.py": "x = 9\n"})
    _git(host["live"], "pull", "-q", "--ff-only", "origin", "main")
    deployer = _deployer(host, green={hand})
    with pytest.raises(auto_deploy.Stop, match="skipped:up-to-date") as stop:
        deployer.decide(execute=True)
    deployer.record(auto_deploy.Decision(stop.value.outcome, stop.value.reason,
                                         stop.value.detail), SAFE, SAFE)
    assert _state(host)["deployed_sha"] == hand


def test_a_rollback_drill_rolls_back_a_good_deploy(host):
    before = _git(host["live"], "rev-parse", "HEAD")
    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={target})
    deployer.drill_rollback = True
    deployer.ops._wait_health = lambda: ({"ok": True}, {})
    decision = deployer.decide(execute=True)
    assert decision.label == "rolled-back" and "rollback drill" in decision.detail["error"]
    assert deployer.calls[-3:] == ["--apply", "post-check", "--apply"]
    assert _git(host["live"], "rev-parse", "HEAD") == before


def test_check_venv_is_built_once_per_lock(host, monkeypatch):
    worktree = host["tmp"] / "wt"
    worktree.mkdir()
    (worktree / "uv.lock").write_text("lock-1\n")
    deployer = auto_deploy.Deployer(engine_root=host["live"], state_dir=host["tmp"] / "state",
                                    logs_dir=host["tmp"] / "logs")
    calls = []

    def run(argv, *, cwd, env=None, timeout=600):
        calls.append((argv[1:3], env["UV_PROJECT_ENVIRONMENT"]))
        pathlib.Path(env["UV_PROJECT_ENVIRONMENT"]).mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(argv, 0, "", "")

    import pathlib
    deployer.run = run
    venv = deployer.check_venv(worktree)
    assert venv == host["tmp"] / "state/check-venv"
    assert deployer.check_venv(worktree) == venv and len(calls) == 1  # reused while unchanged
    (worktree / "uv.lock").write_text("lock-2\n")
    deployer.check_venv(worktree)
    assert len(calls) == 2 and calls[0] == (["sync", "--frozen"], str(venv))


def test_a_full_tier_run_covers_code_pushed_with_it(host):
    code = _commit(host["seed"], "code", {"engine/x.py": "x = 1\n"})
    head = _commit(host["seed"], "plan", {"docs/plan.md": "status\n"})
    _git(host["seed"], "push", "-q", "origin", "main")  # one push: only the head has a run
    deployer = _deployer(host, green={head})
    with pytest.raises(auto_deploy.Stop, match="skipped:no-green-ci"):
        deployer.decide(execute=False)  # a reduced-tier run proves nothing about the code
    deployer = _deployer(host, green={head})
    deployer.full = {head}
    decision = deployer.decide(execute=False)
    assert decision.outcome == "would-deploy" and decision.detail["target"] == head
    assert code


def test_full_tier_reads_the_runs_test_shards(host, monkeypatch):
    deployer = auto_deploy.Deployer(engine_root=host["live"], state_dir=host["tmp"] / "state",
                                    logs_dir=host["tmp"] / "logs")
    deployer.run_ids = {"a" * 40: 7}
    monkeypatch.setattr(auto_deploy, "github_token", lambda: None)
    answers = {
        "full": {"jobs": [{"name": "test (UTC, 0)", "conclusion": "success"},
                          {"name": "selected", "conclusion": "skipped"}]},
        "reduced": {"jobs": [{"name": "test (UTC, 0)", "conclusion": "skipped"},
                             {"name": "selected", "conclusion": "success"}]},
    }
    for label, expected in (("full", True), ("reduced", False)):
        deployer.http_get = lambda url, headers, label=label: (
            200, {}, json.dumps(answers[label]).encode())
        assert deployer.full_tier("a" * 40) is expected
    assert deployer.full_tier("b" * 40) is False


def test_the_recheck_inside_the_mutation_lock_ignores_its_own_transaction_lock(host):
    from server.driver_log import _lock_held

    target = _push(host, "code", {"engine/x.py": "x = 1\n"})
    deployer = _deployer(host, green={target})
    real = lambda path: _lock_held(path) if path.exists() else False  # noqa: E731
    deployer.lock_held = real  # the real /proc/locks observer
    decision = deployer.decide(execute=True)
    assert decision.outcome == "deployed", decision
    with deployer.ops.transaction_lock(deployer.root, "someone-else"):
        other = _deployer(host, green={target})
        other.lock_held = real
        with pytest.raises(auto_deploy.Stop, match="skipped:release-transaction"):
            other.decide(execute=False)
