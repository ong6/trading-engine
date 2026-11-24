#!/usr/bin/env python3
"""Continuous deployer: bring the live checkout to the newest green ``main`` commit, or say why not.

``python -m tools.auto_deploy --execute`` is run by ``trading-engine-auto-deploy.timer``
four times an hour. Without ``--execute`` it decides and reports but never changes the live
checkout, its units, its reports or ``state.json``. One run at a time holds ``run.lock`` in the
state directory; another exits ``skipped:run-in-progress``. Each run records one decision:

  deployed                 the live checkout was moved to the target and post-checked
  dry-run would-deploy     every check passed; ``--execute`` would deploy the target
  skipped:<reason>         nothing to do now (a blocked window, a producer, up to date, ...)
  needs-human:<reason>     the range needs ``tools/release_deploy.py`` or a person
  rolled-back              the post-check failed: the previous commit was restored and the
                           target's code is refused until a commit outside ``data/`` changes
                           it (data-only pushes do not retry it; newer code deploys)
  recovered                an unverified host (a crashed deploy, a failed rollback, unhealthy
                           unverified code) was brought back to the last verified commit
  recovery-failed          recovery did not verify; it retries with backoff and, after three
                           failures, clears failed engine units and restarts the API and UI

Self-heal, never alerts: state.json records ``last_good_sha`` after every verified deploy
(the first run trusts the deployed checkout; a healthy hand deploy is adopted) and an
``in_flight`` marker while the checkout is moved. A run first converges: an in-flight marker,
a pending recovery or unhealthy unverified code restores the reports, resets to the last good
commit (``--keep``, else a hard reset of tracked files; untracked store files are untouched,
uncommitted ``data/`` edits are put back unless the reset changed that file, in which case the
receipt names the saved copy, and a ``refs/auto-deploy/pre-recovery-*`` ref keeps every commit),
re-applies data-only commits, re-runs ``install_automation --apply`` and checks the host. Dry
runs report ``would-recover``.

A recorded recovery (an in-flight marker or a failed recovery) skips the 22:30-03:00 window
and looks ahead 5 minutes instead of 15 for a timer; it keeps the 14:05-14:35 window and never
runs past a held lock, a producer, a release transaction or a running unit.

Steps: (1) skip inside 14:05-14:35 and 22:30-03:00 UTC, while any producer lock is held
(observed through ``/proc/locks``, never acquired), a producer process runs or a release
transaction holds its lock; (2) fetch ``origin/main`` into a private mirror under the state
directory and pick the newest commit whose GitHub Actions ``ci`` push run succeeded, also
requiring green CI on the newest code-touching commit up to it (content-only pushes run a
reduced tier); (3) run ``tools.deploy_gate --check`` (the deployed gate code) on a worktree of
the target with ``--base <deployed>``, plus the registration and forward-record tests;
(4) refuse dependency, schema-migration and contract-version changes; (5) require a clean live
``main`` whose only unpushed commits touch ``data/``; (6) when a forward-record closure digest
changed, rehearse the digest-only migration on the newest snapshot, back up the reports and run
``--migrate-runtime-contract``; (7) ``install_automation --apply``; (8) post-check ``/health``,
``/ready``, ``/meta`` and the automation audit; (9) on failure ``git reset --keep`` the previous
commit (only when no commit landed since), restore the reports and re-apply.

Mutation holds the release transaction lock and the te-autopush lock, so neither can race it.
State lives in ``~/.local/state/trading-engine/auto-deploy/``; one receipt per run goes to the
``job-runs`` tree of the logs directory, which ``tools/ops_digest.py`` reads. After a verified
deploy or a successful recovery only the newest two report backups under ``backups/`` are kept.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Iterator

import yaml

from engine import job_contract
from engine.lib import store_limits
from engine.lib.resources import write_text_atomic
from engine.lib.settings import REPO_ROOT
from server.driver_log import _lock_held
from tools import affected_tests, backup_database, prune_local, release_deploy, repin, run_job

JOB_ID = "auto-deploy"
STATE_DIR = Path.home() / ".local/state/trading-engine/auto-deploy"
ENGINE_ROOT = Path.home() / "trading-engine"
AUTOPUSH_LOCK = Path.home() / ".local/state/te-autopush.lock"
GH_HOSTS = Path.home() / ".config/gh/hosts.yml"
API_URL = "http://127.0.0.1:8000"
REPOSITORY = "ong6/trading-engine"
RUNS_URL = (f"https://api.github.com/repos/{REPOSITORY}/actions/runs"
            "?branch=main&event=push&per_page=100")
WORKFLOW = "ci"
BLOCKED_WINDOWS = ((time(14, 5), time(14, 35)), (time(22, 30), time(3, 0)))
MUTATION_LEAD = timedelta(minutes=15)  # the mutating half must end before a window or a start
RECOVERY_LEAD = timedelta(minutes=5)  # a recovery takes seconds to a few minutes
PROBE_ONLY = "unhealthy-unverified-code"  # recovery found by the health probe alone
# Gate and forward tests take about a minute; with MUTATION_LEAD they fit inside the unit's
# TimeoutStartSec (50 min), so a hung check ends with a receipt instead of a systemd kill.
GATE_TIMEOUT = FORWARD_TESTS_TIMEOUT = 900
CHECK_TIMEOUTS = frozenset({"gate-timeout", "forward-tests-timeout", "check-venv-timeout"})
CHECK_TIMEOUT_LIMIT = 3  # consecutive timeouts on one target before it needs a person
# Scheduled engine starts that must not land inside a mutation. The deployer itself, the
# read-only digest and the ten-minute watchdog are excluded (the watchdog's catch-up takes the
# nightly lock, which the producer-lock check sees).
ENGINE_UNIT = re.compile(r"^(?:trading-engine-|massive-)")
SCHEDULE_EXEMPT = frozenset({"trading-engine-auto-deploy", "trading-engine-ops-digest",
                             "trading-engine-driver-watchdog", "massive-minute-capture"})
RECOVERY_BASE = timedelta(minutes=15)  # backoff after a failed recovery: 15, 30, 60 ... minutes
RECOVERY_CAP = timedelta(hours=4)
HEAL_AFTER = 3  # consecutive failed recoveries before failed units are cleared and apps restarted
APP_UNITS = ("trading-engine-api.service", "trading-engine-ui.service")
HUMAN_PATHS = ("uv.lock", "pyproject.toml", "engine/requirements.txt", "ui/package.json",
               "ui/package-lock.json",
               # The long-running minute capture is exempt from the producer check, so a
               # change to its own code waits for a person to restart it.
               "engine/free_massive_minute.py", "tools/free_massive_minute.py")
# Runs most of the day against its own database, never the market store: not a deploy blocker.
LONG_RUNNING_EXEMPT = re.compile(r"(?:engine|tools)\.free_massive_minute\b")
MIGRATIONS = "engine/migrations/"
FORWARD_TESTS = ("tests/test_p15_registration.py", "tests/test_forward_review.py",
                 "tests/test_xs_forward_review.py", "tests/test_experiment_runner.py")
# Every lock file in these directories counts: the producer locks, the running guards, the
# P15/P16 and opportunity locks, snapshot publication and the price-verification reader.
LOCK_DIRECTORIES = ((), ("store",), ("store", "snapshots"), ("logs",))
META_KEYS = {"e1": "e1_forward", "sector": "forward_review", "xs": "xs_forward_review"}
WORK_STATUS = {"deployed": "success", "would-deploy": "noop", "skipped": "noop",
               "needs-human": "degraded", "rolled-back": "degraded",
               "recovered": "degraded", "recovery-failed": "terminal_failure",
               "failed": "terminal_failure"}


class Stop(Exception):
    """End the run with one decision."""

    def __init__(self, outcome: str, reason: str = "", **detail):
        super().__init__(f"{outcome}:{reason}" if reason else outcome)
        self.outcome, self.reason, self.detail = outcome, reason, detail


@dataclass
class Decision:
    outcome: str
    reason: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        if self.outcome == "would-deploy":
            return "dry-run would-deploy"
        return f"{self.outcome}:{self.reason}" if self.reason else self.outcome


def in_blocked_window(moment: datetime, windows=BLOCKED_WINDOWS) -> bool:
    clock = moment.astimezone(UTC).time()
    for start, end in windows:
        if (start <= clock < end) if start < end else (clock >= start or clock < end):
            return True
    return False


def _cron_field(spec: str, value: int, low: int, high: int) -> bool:
    for item in spec.split(","):
        span, _slash, raw_step = item.partition("/")
        step = int(raw_step) if raw_step else 1
        if span == "*":
            start, end = low, high
        elif "-" in span:
            start, end = (int(x) for x in span.split("-", 1))
        else:
            start = end = int(span)
        if start <= value <= end and (value - start) % step == 0:
            return True
    return False


def cron_fires(spec: str, moment: datetime) -> bool:
    """Whether a five-field cron spec (no names) fires at ``moment`` (UTC host)."""
    minute, hour, day, month, weekday = spec.split()
    dow = (moment.weekday() + 1) % 7  # cron: Sunday is 0
    return (_cron_field(minute, moment.minute, 0, 59) and _cron_field(hour, moment.hour, 0, 23)
            and _cron_field(day, moment.day, 1, 31) and _cron_field(month, moment.month, 1, 12)
            and (_cron_field(weekday, dow, 0, 7) or (dow == 0 and _cron_field(weekday, 7, 0, 7))))


def scheduled_soon(crontab: str, timers: dict[str, datetime | None], moment: datetime,
                   lead: timedelta) -> str | None:
    """The first engine start (timer or engine cron line) due within ``lead`` of ``moment``."""
    for unit, due in sorted(timers.items()):
        if due is not None and moment <= due <= moment + lead:
            return unit
    minute = moment.replace(second=0, microsecond=0)
    for line in crontab.splitlines():
        fields = line.split(None, 5)
        if len(fields) < 6 or line.lstrip().startswith("#") or "trading-engine" not in fields[5]:
            continue
        spec = " ".join(fields[:5])
        probe = minute
        while probe <= moment + lead:
            if probe >= moment - timedelta(minutes=1) and cron_fires(spec, probe):
                return f"cron:{fields[5].split('>>')[0].strip()[:80]}"
            probe += timedelta(minutes=1)
    return None


def running_producers(listing: str, root: Path, *, own_pid: int) -> list[str]:
    """Producer commands under ``root`` in a ``ps -eo pid=,args=`` listing.

    The checkout is matched by its given and its resolved path (a symlinked home spells it
    two ways); the long-running minute capture is exempt.
    """
    roots = {str(root), str(root.resolve())}
    found = []
    for line in listing.splitlines():
        pid, _sep, command = line.strip().partition(" ")
        if not pid.isdigit() or int(pid) == own_pid:
            continue
        if (any(spelling in command for spelling in roots)
                and release_deploy.PRODUCER_PATTERN.search(command)
                and not LONG_RUNNING_EXEMPT.search(command)):
            found.append(command.strip())
    return found


def github_token(hosts: Path = GH_HOSTS) -> str | None:
    """``$GITHUB_TOKEN``, else github.com's ``oauth_token`` in the gh CLI's hosts file.

    Read at run time only; never logged, printed, cached or written anywhere."""
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    try:
        entry = (yaml.safe_load(hosts.read_text()) or {}).get("github.com") or {}
    except (OSError, ValueError, AttributeError, yaml.YAMLError):
        return None
    token = entry.get("oauth_token") if isinstance(entry, dict) else None
    return token if isinstance(token, str) and token.strip() else None


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Deployer:
    """One run. Every host interaction is a method so tests can replace it."""

    def __init__(self, *, engine_root: Path = ENGINE_ROOT, state_dir: Path = STATE_DIR,
                 logs_dir: Path | None = None, api_url: str = API_URL,
                 autopush_lock: Path = AUTOPUSH_LOCK, runs_url: str = RUNS_URL):
        self.root = engine_root.resolve()
        self.state_dir = state_dir
        self.logs_dir = logs_dir or self.root / "logs"
        self.api_url = api_url.rstrip("/")
        self.autopush_lock = autopush_lock
        self.runs_url = runs_url
        self.mirror = state_dir / "mirror"
        self.worktree = state_dir / "worktree"
        self.steps: list[str] = []
        self.drill_rollback = False
        self.execute = False  # set by decide(); a dry run writes no state.json
        self.locked_out = False  # another run holds the run lock: write the receipt only
        self.ops = release_deploy.ReleaseOperations(
            release_deploy.StateStore(state_dir), home=Path.home(),
            command_runner=release_deploy.CommandRunner(), api_url=self.api_url,
            ui_url="http://127.0.0.1:3000",
            minimum_free_bytes=store_limits.reserve_bytes())

    @contextmanager
    def run_lock(self) -> Iterator[None]:
        """One run at a time, dry runs included: they share the gate worktree and state.json."""
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        with open(self.state_dir / "run.lock", "a") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                self.locked_out = True
                raise Stop("skipped", "run-in-progress") from exc
            yield

    # ---- host seams -------------------------------------------------------------------
    def now(self) -> datetime:
        return datetime.now(UTC)

    def run(self, argv: list[str], *, cwd: Path, env: dict | None = None,
            timeout: float = 600) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(argv, cwd=cwd, env={**os.environ, **(env or {})},
                                  capture_output=True, text=True, timeout=timeout, check=False,
                                  stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired as exc:
            return subprocess.CompletedProcess(argv, 124, "", str(exc))
        except OSError as exc:  # could not start (a missing interpreter): not a timeout
            return subprocess.CompletedProcess(argv, 127, "", str(exc))

    def git(self, root: Path, *args: str, check: bool = True) -> str:
        done = self.run(["git", "--no-optional-locks", *args], cwd=root, timeout=300)
        if check and done.returncode:
            raise Stop("failed", "git", command=" ".join(args), error=done.stderr.strip()[-300:])
        return done.stdout.strip() if done.returncode == 0 else ""

    def lock_held(self, path: Path) -> bool | None:
        return _lock_held(path) if path.exists() else False

    def producers(self) -> list[str]:
        listing = self.run(["ps", "-eo", "pid=,args="], cwd=self.root, timeout=30).stdout
        return running_producers(listing, self.root, own_pid=os.getpid())

    def http_get(self, url: str, headers: dict) -> tuple[int, dict, bytes]:
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, dict(response.headers.items()), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers.items()), b""

    # ---- step 1: may we run at all? ------------------------------------------------------
    def busy(self) -> str | None:
        locks = set(backup_database.LOCK_FILES)
        for parts in LOCK_DIRECTORIES:
            locks |= {str(path.relative_to(self.root))
                      for path in self.root.joinpath(*parts).glob("*.lock")}
        for relative in sorted(locks):
            held = self.lock_held(self.root / relative)
            if held is not False:
                return f"producer-lock:{relative}" if held else f"lock-unknown:{relative}"
        found = self.producers()
        if found:
            return "producer-running"
        common = Path(self.git(self.root, "rev-parse", "--git-common-dir"))
        transaction = (common if common.is_absolute() else self.root / common) / \
            "release-deploy.lock"
        # Inside mutation_locks this process holds that lock itself; only another holder counts.
        if not self.ops.transaction_lock_held and self.lock_held(transaction) is not False:
            return "release-transaction"
        return None

    def engine_schedule(self) -> tuple[dict[str, datetime | None], list[str], str]:
        """Engine timers' next starts, engine units now activating, and the crontab."""
        listed = self.run(["systemctl", "--user", "list-units", "--all", "--no-legend",
                           "--plain", "--type=timer,service"], cwd=self.root, timeout=30)
        if listed.returncode:
            raise Stop("skipped", "schedule-unknown", error=listed.stderr.strip()[-200:])
        timers, activating = [], []
        for line in listed.stdout.splitlines():
            fields = line.split()
            if len(fields) < 4:
                continue
            name, _load, active = fields[0], fields[1], fields[2]
            stem = name.rsplit(".", 1)[0]
            if not ENGINE_UNIT.match(stem) or stem in SCHEDULE_EXEMPT:
                continue
            if name.endswith(".timer"):
                timers.append(name)
            elif active in {"activating", "reloading"} or fields[3] in {"start", "running"} \
                    and active == "active" and not name.endswith(("api.service", "ui.service")):
                activating.append(name)
        due: dict[str, datetime | None] = {}
        if timers:
            shown = self.run(["systemctl", "--user", "show", "-p", "Id",
                              "-p", "NextElapseUSecRealtime", *timers], cwd=self.root, timeout=30)
            unit = None
            for line in shown.stdout.splitlines():
                key, _sep, value = line.partition("=")
                if key == "Id":
                    unit = value
                elif key == "NextElapseUSecRealtime" and unit:
                    try:
                        due[unit] = datetime.strptime(value.strip(), "%a %Y-%m-%d %H:%M:%S %Z"
                                                      ).replace(tzinfo=UTC)
                    except ValueError:
                        due[unit] = None
        crontab = self.run(["crontab", "-l"], cwd=self.root, timeout=30).stdout
        return due, activating, crontab

    def save_state(self, **changes) -> dict:
        """Merge ``changes`` into state.json at once (``None`` removes a key)."""
        state = self.load_state()
        for key, value in changes.items():
            if value is None:
                state.pop(key, None)
            else:
                state[key] = value
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_text_atomic(self.state_dir / "state.json",
                          json.dumps(state, indent=1, sort_keys=True) + "\n")
        return state

    def code_differs(self, good: str) -> bool:
        """Whether the live checkout's tracked code (outside data/) differs from ``good``."""
        done = self.run(["git", "diff", "--quiet", good, "HEAD", "--", ".", ":(exclude)data"],
                        cwd=self.root, timeout=120)
        return done.returncode != 0

    def host_healthy(self) -> bool:
        """Liveness, readiness and the automation audit on the code that is live now."""
        try:
            self.ops._wait_health()
        except release_deploy.DeployError:
            return False
        code, _summary = self.automation("--audit")
        return code == 0

    def heal_services(self) -> None:
        """The backstop after repeated failed recoveries: clear failed units, restart the apps."""
        self.run(["systemctl", "--user", "reset-failed", "trading-engine-*"], cwd=self.root)
        done = self.run(["systemctl", "--user", "restart", *APP_UNITS], cwd=self.root,
                        timeout=900)
        self.steps.append(f"heal:restart:{done.returncode}")

    def heal_blocked(self) -> str | None:
        """Why the backstop restart must wait, re-checked just before it: the pre-open window
        or an engine start due within RECOVERY_LEAD."""
        moment, preopen = self.now(), BLOCKED_WINDOWS[:1]
        if in_blocked_window(moment, preopen) or in_blocked_window(moment + RECOVERY_LEAD,
                                                                    preopen):
            return "window"
        try:
            timers, _activating, crontab = self.engine_schedule()
        except Stop:
            return "schedule-unknown"
        soon = scheduled_soon(crontab, timers, moment, RECOVERY_LEAD)
        return f"timer-soon:{soon}" if soon else None

    def disk_problem(self) -> str | None:
        """Keep the store reserve: a rollback must still work on a full day."""
        try:
            store_limits.require_free_space(self.root / "store", purpose="a deploy")
        except store_limits.DiskSpaceError as exc:
            return str(exc)
        return None

    def load_state(self) -> dict:
        try:
            state = json.loads((self.state_dir / "state.json").read_text())
        except (OSError, ValueError):
            return {}
        return state if isinstance(state, dict) else {}

    def _gate_now(self, *, lead: timedelta = timedelta(0), recovery: bool = False) -> None:
        """Skip unless the host may change now. A recorded recovery (a broken or unverified
        host) may run in the nightly window, whose producers show as locks and processes, and
        looks ahead only RECOVERY_LEAD for a timer; the pre-open window still holds it."""
        moment = self.now()
        windows = BLOCKED_WINDOWS[:1] if recovery else BLOCKED_WINDOWS
        if recovery and lead:
            lead = RECOVERY_LEAD
        if in_blocked_window(moment, windows) or in_blocked_window(moment + lead, windows):
            raise Stop("skipped", "window")
        reason = self.busy()
        if reason:
            raise Stop("skipped", reason)
        low = self.disk_problem()
        if low:
            raise Stop("skipped", "low-disk", error=low[:200])
        if lead:
            timers, activating, crontab = self.engine_schedule()
            if activating:
                raise Stop("skipped", "unit-active", units=activating)
            soon = scheduled_soon(crontab, timers, moment, lead)
            if soon:
                raise Stop("skipped", "timer-soon", unit=soon)

    # ---- step 2: target -------------------------------------------------------------------
    def waiting_at_last_fetch(self) -> int | None:
        """First-parent ``main`` commits past the live checkout's base on ``main`` now, as of
        the mirror's last fetch (local and read-only; None when the mirror cannot say)."""
        base = self.git(self.root, "merge-base", "HEAD", "refs/remotes/origin/main", check=False)
        if not base:
            return None
        done = self.run(["git", "rev-list", "--count", "--first-parent",
                         f"{base}..refs/remotes/origin/main"], cwd=self.mirror, timeout=30)
        return int(done.stdout) if done.returncode == 0 and done.stdout.strip().isdigit() else None

    def refresh_mirror(self) -> tuple[str, str]:
        """Fetch origin/main and the live HEAD into the private mirror; never write the live tree."""
        if not (self.mirror / ".git").exists() and not (self.mirror / "HEAD").exists():
            self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            done = self.run(["git", "clone", "-q", "--no-checkout", str(self.root),
                             str(self.mirror)], cwd=self.state_dir, timeout=1800)
            if done.returncode:
                raise Stop("failed", "mirror", error=done.stderr.strip()[-300:])
            url = self.git(self.root, "remote", "get-url", "origin")
            self.git(self.mirror, "remote", "set-url", "origin", url)
        fetched = self.run(["git", "fetch", "-q", "origin", "+main:refs/remotes/origin/main"],
                           cwd=self.mirror, timeout=600)
        if fetched.returncode:
            raise Stop("skipped", "fetch-failed", error=fetched.stderr.strip()[-300:])
        self.git(self.mirror, "fetch", "-q", str(self.root), "+HEAD:refs/live/head")
        return (self.git(self.mirror, "rev-parse", "refs/remotes/origin/main"),
                self.git(self.mirror, "rev-parse", "refs/live/head"))

    def ci_conclusions(self) -> dict[str, bool]:
        """head SHA -> whether its ``ci`` push run on main succeeded (ETag-cached).

        The run's conclusion is success only when every job did, so the ``checks`` job
        (ruff, audits) and the verdict job count as much as the test shards."""
        cache_path = self.state_dir / "ci-runs-v2.json"  # v2 records run ids
        try:
            cache = json.loads(cache_path.read_text())
        except (OSError, ValueError):
            cache = {}
        headers = {"Accept": "application/vnd.github+json",
                   "User-Agent": "trading-engine-auto-deploy"}
        if cache.get("etag"):
            headers["If-None-Match"] = cache["etag"]
        token = github_token()  # the host's shared anonymous quota (60/h) runs out
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            status, response_headers, body = self.http_get(self.runs_url, headers)
        except (OSError, urllib.error.URLError, ValueError) as exc:
            raise Stop("skipped", "ci-unavailable", error=str(exc)[:200]) from exc
        if status == 304 and "runs" in cache:
            runs = cache["runs"]
        elif status == 200:
            try:
                runs = json.loads(body)["workflow_runs"]
            except (ValueError, KeyError, TypeError) as exc:
                raise Stop("skipped", "ci-unavailable", error="malformed runs") from exc
            runs = [{"head_sha": run.get("head_sha"), "conclusion": run.get("conclusion"),
                     "id": run.get("id")}
                    for run in runs if run.get("name") == WORKFLOW
                    and run.get("event") == "push" and run.get("head_branch") == "main"]
            etag = {key.lower(): value for key, value in response_headers.items()}.get("etag")
            write_text_atomic(cache_path, json.dumps({"etag": etag, "runs": runs}) + "\n")
        else:  # a rate limit (403/429) or any other answer: no verdict this run
            raise Stop("skipped", "ci-unavailable", http_status=status)
        green: dict[str, bool] = {}
        self.run_ids: dict[str, int] = {}
        for run in runs:
            sha = run["head_sha"]
            green[sha] = green.get(sha, False) or run["conclusion"] == "success"
            if run["conclusion"] == "success" and run.get("id"):
                self.run_ids[sha] = run["id"]
        return green

    def full_tier(self, sha: str) -> bool:
        """Whether ``sha``'s green run executed the test shards (CI runs the full tier when its
        push range touches code, so it covers code commits pushed with it that had no run)."""
        run_id = getattr(self, "run_ids", {}).get(sha)
        if not run_id:
            return False
        headers = {"Accept": "application/vnd.github+json",
                   "User-Agent": "trading-engine-auto-deploy"}
        token = github_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        url = self.runs_url.split("/runs?", 1)[0] + f"/runs/{run_id}/jobs?per_page=100"
        try:
            status, _headers, body = self.http_get(url, headers)
            jobs = json.loads(body)["jobs"] if status == 200 else []
        except (OSError, urllib.error.URLError, ValueError, KeyError, TypeError):
            return False
        shards = [job for job in jobs if str(job.get("name", "")).startswith("test (")]
        return bool(shards) and all(job.get("conclusion") == "success" for job in shards)

    def touches_code(self, commit: str) -> bool:
        parents = self.git(self.mirror, "rev-list", "--parents", "-n", "1", commit).split()[1:2]
        names = self.git(self.mirror, "diff", "--name-only", "--no-renames", parents[0], commit
                         ).splitlines() if parents else ["(root)"]
        return not all(affected_tests.is_content(name) for name in names if name)

    def pick_target(self, deployed: str, origin: str) -> str:
        candidates = self.git(self.mirror, "rev-list", "--first-parent",
                              f"{deployed}..{origin}").split()
        if not candidates:
            raise Stop("skipped", "up-to-date", deployed=deployed)
        green = self.ci_conclusions()
        code = {commit: self.touches_code(commit) for commit in candidates}
        for index, commit in enumerate(candidates):
            if not green.get(commit):
                continue
            newest_code = next((c for c in candidates[index:] if code[c]), None)
            if newest_code is None or green.get(newest_code) or self.full_tier(commit):
                return commit
        raise Stop("skipped", "no-green-ci", newest=origin)

    # ---- steps 3-5: checks -----------------------------------------------------------------
    def human_reasons(self, deployed: str, target: str) -> list[str]:
        reasons = []
        changed = self.git(self.mirror, "diff", "--name-status", "--no-renames", deployed,
                           target).splitlines()
        paths = {line.split("\t", 1)[1] for line in changed if "\t" in line}
        if paths & set(HUMAN_PATHS):
            reasons.append("dependencies")
        if any(path.startswith(MIGRATIONS) for path in paths):
            reasons.append("schema-migration")
        for family in repin.FAMILIES:
            versions = {repin._literal(self.git(self.mirror, "show", f"{ref}:{family.path}"),
                                       "RUNTIME_CONTRACT_VERSION") for ref in (deployed, target)}
            if len(versions) > 1:
                reasons.append(f"contract-version:{family.key}")
        return reasons

    def prepare_worktree(self, target: str) -> Path:
        if self.worktree.exists():
            self.git(self.mirror, "worktree", "remove", "--force", str(self.worktree),
                     check=False)
            shutil.rmtree(self.worktree, ignore_errors=True)
        self.git(self.mirror, "worktree", "prune")
        self.git(self.mirror, "worktree", "add", "-q", "--detach", str(self.worktree), target)
        # The gate and the forward tests need pytest, which the production environment lacks:
        # link the deployer's own check environment (the target's lock plus the dev extra).
        venv = self.check_venv(self.worktree)
        if venv.exists():
            exclude = Path(self.git(self.mirror, "rev-parse", "--git-common-dir"))
            exclude = (exclude if exclude.is_absolute() else self.mirror / exclude) / "info/exclude"
            exclude.parent.mkdir(parents=True, exist_ok=True)
            if "/.venv\n" not in (exclude.read_text() if exclude.exists() else ""):
                with exclude.open("a") as handle:
                    handle.write("/.venv\n")
            (self.worktree / ".venv").symlink_to(venv.resolve())
        return self.worktree

    def check_venv(self, worktree: Path) -> Path:
        """``state_dir/check-venv``: the worktree's frozen lock with the dev extra, rebuilt only
        when ``uv.lock`` changes (dependency ranges are refused, so it matches production)."""
        venv = self.state_dir / "check-venv"
        lock = worktree / "uv.lock"
        stamp = venv / ".uv-lock-sha256"
        digest = hashlib.sha256(lock.read_bytes()).hexdigest() if lock.exists() else ""
        if stamp.exists() and stamp.read_text().strip() == digest:
            return venv
        uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
        done = self.run([uv, "sync", "--frozen", "--extra", "dev", "--quiet"], cwd=worktree,
                        env={"UV_PROJECT_ENVIRONMENT": str(venv)}, timeout=1800)
        error = (done.stderr or done.stdout)[-300:]
        if done.returncode == 127:  # uv could not start: retrying will not help
            raise Stop("needs-human", "check-venv-cannot-start", error=error)
        if done.returncode == 124:
            raise Stop("skipped", "check-venv-timeout", error=error)
        if done.returncode:
            raise Stop("skipped", "check-venv", error=error)
        write_text_atomic(stamp, digest + "\n")
        self.steps.append("check-venv:built")
        return venv

    def gate(self, worktree: Path, deployed: str) -> dict:
        done = self.run([sys.executable, "-m", "tools.deploy_gate", "--check", str(worktree),
                         "--base", deployed, "--engine-root", str(self.root),
                         "--receipts", str(self.state_dir / "gate-receipts")],
                        cwd=REPO_ROOT, env={"PYTHONPATH": str(REPO_ROOT)}, timeout=GATE_TIMEOUT)
        tail = done.stdout.strip().splitlines()[-6:]
        if done.returncode in (3, 124):  # cannot check (dirty or moved tree), or timed out
            reason = "gate-cannot-check" if done.returncode == 3 else "gate-timeout"
            raise Stop("skipped", reason, exit=done.returncode, tail=tail or [done.stderr[-300:]])
        if done.returncode:
            raise Stop("needs-human", "gate-refused", exit=done.returncode, tail=tail)
        with tempfile.TemporaryDirectory(prefix="auto-deploy-tests-") as private:
            tests = self.run([str(worktree / ".venv/bin/python"), "-m", "pytest", "-q",
                              "-p", "no:cacheprovider",
                              "-n", "2", *FORWARD_TESTS], cwd=worktree,
                             env={"PYTHONPATH": str(worktree), "TMPDIR": private,
                                  "PYTHONDONTWRITEBYTECODE": "1"}, timeout=FORWARD_TESTS_TIMEOUT)
        if tests.returncode == 124:  # timed out: retried next tick
            raise Stop("skipped", "forward-tests-timeout",
                       tail=(tests.stdout + tests.stderr).strip().splitlines()[-6:])
        if tests.returncode:
            raise Stop("needs-human", "forward-tests",
                       tail=(tests.stdout + tests.stderr).strip().splitlines()[-6:])
        return {"gate": tail[-1] if tail else "", "forward_tests": "pass"}

    def count_check_timeout(self, target: str, stop: Stop) -> None:
        """Count consecutive check timeouts on one target's code; the third one makes the
        target ``needs-human`` (recorded as refused) instead of another retry."""
        seen = self.load_state().get("check_timeouts") or {}
        previous = seen.get("target")  # keyed on the code: a data-only push keeps counting
        same = bool(previous) and (previous == target or self.same_code(previous, target))
        count = seen.get("count", 0) + 1 if same else 1
        if count < CHECK_TIMEOUT_LIMIT:
            self.save_state(check_timeouts={"target": target, "count": count})
            return
        self.save_state(check_timeouts=None)
        raise Stop("needs-human", stop.reason, target=target, timeouts=count,
                   **stop.detail) from stop

    def migrations_needed(self, target: str) -> list[str]:
        """Families whose target closure digest differs from the live published report."""
        needed = []
        for family in repin.FAMILIES:
            literal = repin._literal(self.git(self.mirror, "show", f"{target}:{family.path}"),
                                     "EXPECTED_RUNTIME_CONTRACT_SHA256")
            report = json.loads((self.root / family.report).read_text())
            if report.get("status") == "INVALID":
                raise Stop("needs-human", f"invalid-report:{family.key}")
            if repin._report_identity(report, family)["runtime_contract_sha256"] != literal:
                needed.append(family.key)
        return needed

    def live_state(self, live_head: str, origin: str) -> list[str]:
        """Unpushed live commits (all data-only), or Stop."""
        branch = self.git(self.root, "symbolic-ref", "--quiet", "--short", "HEAD", check=False)
        if branch != "main":
            raise Stop("skipped", "live-not-on-main")
        git_dir = Path(self.git(self.root, "rev-parse", "--absolute-git-dir"))
        if any((git_dir / name).exists() for name in
               ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD")):
            raise Stop("skipped", "live-operation-in-progress")
        # Producers rewrite tracked files under data/ (``data/_meta.json``) between the commits
        # that record them, so a dirty data/ path is normal; anything else is not.
        dirty = self.live_dirty_paths()
        outside = sorted(path for path in dirty if not path.startswith("data/"))
        if outside:
            raise Stop("skipped", "live-tree-dirty", paths=outside[:5])
        local = self.git(self.mirror, "rev-list", live_head, f"^{origin}").split()
        for commit in local:
            names = self.git(self.mirror, "diff-tree", "--no-commit-id", "--name-only", "-r",
                             "-m", commit).splitlines()
            if any(not name.startswith("data/") for name in names):
                raise Stop("skipped", "live-has-code-commits", commit=commit)
        return local

    def live_dirty_paths(self) -> set[str]:
        """Tracked paths with uncommitted changes in the live checkout."""
        return set(self.git(self.root, "diff", "--name-only", "--no-renames", "HEAD"
                            ).splitlines())

    def dirty_overlap(self, target: str) -> list[str]:
        """Dirty live paths whose committed content differs between HEAD and ``target``.

        Moving the checkout would have to overwrite those edits, so the run waits for the
        producer's next commit instead."""
        dirty = self.live_dirty_paths()
        if not dirty:
            return []
        changed = set(self.git(self.root, "diff", "--name-only", "--no-renames", "HEAD",
                               target).splitlines())
        return sorted(dirty & changed)

    # ---- steps 6-9: mutation ------------------------------------------------------------------
    @contextmanager
    def mutation_locks(self) -> Iterator[None]:
        with ExitStack() as stack:
            try:
                stack.enter_context(self.ops.transaction_lock(self.root, f"auto-deploy-{uuid.uuid4()}"))
            except release_deploy.DeployError as exc:
                raise Stop("skipped", "release-transaction") from exc
            self.autopush_lock.parent.mkdir(parents=True, exist_ok=True)
            handle = stack.enter_context(open(self.autopush_lock, "a"))  # noqa: SIM115
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise Stop("skipped", "autopush-running") from exc
            yield

    def python(self) -> str:
        venv = self.root / ".venv/bin/python"
        return str(venv) if venv.exists() else sys.executable

    def automation(self, mode: str) -> tuple[int, dict]:
        done = self.run([self.python(), "-m", "tools.install_automation", "--repo-root",
                         str(self.root), mode], cwd=self.root,
                        env={"PYTHONPATH": str(self.root)}, timeout=1800)
        try:
            summary = json.loads(done.stdout)
        except ValueError:
            summary = {"status": "invalid-output", "stderr": done.stderr.strip()[-300:]}
        return done.returncode, summary if isinstance(summary, dict) else {}

    def post_check(self, expected: dict[str, str]) -> dict:
        health, _headers = self.ops._wait_health()
        meta, _ = self.ops.request_json(f"{self.api_url}/meta")
        for key, family in META_KEYS.items():
            entry = meta.get(family) or {}
            if entry.get("status") in (None, "INVALID"):
                raise release_deploy.DeployError(f"/meta {family} is {entry.get('status')}")
            if entry.get("runtime_contract_sha256") != expected[key]:
                raise release_deploy.DeployError(f"/meta {family} runtime mismatch")
        code, summary = self.automation("--audit")
        if code:
            raise release_deploy.DeployError(f"automation audit: {summary.get('status')}")
        return {"generation_id": health["ready"].get("generation_id")}

    def _report_files(self, family: repin.Family, directory: Path) -> list[Path]:
        """The family's published report files (E1 also writes ``e1-spy-monday.md``)."""
        prefix = Path(family.report).stem.removesuffix("-forward")
        return sorted(path for path in directory.glob(prefix + "*") if path.is_file())

    def migrate(self, families: list[str], backup: Path) -> None:
        backup.mkdir(mode=0o700, parents=True, exist_ok=True)
        for family in repin.FAMILIES:
            if family.key in families:
                for path in self._report_files(family, self.root.joinpath(family.report).parent):
                    shutil.copy2(path, backup / path.name)
        for family in repin.FAMILIES:
            if family.key not in families:
                continue
            done = self.run(repin.migration_argv(self.python(), family), cwd=self.root,
                            env={"PYTHONPATH": str(self.root)}, timeout=1800)
            self.steps.append(f"migrate:{family.key}:{done.returncode}")
            if done.returncode:
                raise release_deploy.DeployError(
                    f"{family.key} migration exited {done.returncode}: "
                    f"{(done.stderr or done.stdout).strip()[-200:]}")

    def restore_reports(self, families: list[str], backup: Path) -> None:
        for family in repin.FAMILIES:
            if family.key in families:
                for saved in self._report_files(family, backup):
                    shutil.copy2(saved, self.root.joinpath(family.report).parent / saved.name)

    def deploy(self, target: str, local: list[str], families: list[str],
               expected: dict[str, str]) -> Decision:
        self._gate_now(lead=MUTATION_LEAD)
        with self.mutation_locks():
            self._gate_now(lead=MUTATION_LEAD)
            previous = self.git(self.root, "rev-parse", "HEAD")
            self.git(self.root, "fetch", "-q", "origin")
            overlap = self.dirty_overlap(target)
            if overlap:
                raise Stop("skipped", "live-data-overlap", paths=overlap[:5])
            backup = self.state_dir / "backups" / self.now().strftime("%Y%m%dT%H%M%SZ")
            # Written before the checkout moves: until this run verifies or rolls back, the next
            # run treats the host as unverified, even if this process dies right after the move.
            marker = {"previous": previous, "target": target, "families": families,
                      "backup": str(backup), "at": _iso(self.now())}
            self.save_state(in_flight=marker)
            try:
                if local:
                    # --autostash carries the producers' uncommitted data/ edits across the
                    # rebase; none of them overlaps the move (checked above).
                    done = self.run(["git", "rebase", "--autostash", "-q", target],
                                    cwd=self.root, timeout=600)
                    if done.returncode:
                        self.run(["git", "rebase", "--abort"], cwd=self.root)
                        raise Stop("skipped", "rebase-conflict")
                else:
                    self.git(self.root, "merge", "-q", "--ff-only", target)
            except Stop:
                if self.git(self.root, "rev-parse", "HEAD", check=False) == previous:
                    self.save_state(in_flight=None)  # the checkout never moved
                raise
            moved = self.git(self.root, "rev-parse", "HEAD")
            self.steps.append(f"moved:{previous[:12]}->{moved[:12]}")
            self.save_state(in_flight={**marker, "moved": moved})
            try:
                self.migrate(families, backup)
                code, summary = self.automation("--apply")
                self.steps.append(f"apply:{summary.get('status')}")
                if code:
                    raise release_deploy.DeployError(f"install_automation --apply: "
                                                     f"{summary.get('errors')}")
                restarted = (summary.get("changes") or {}).get("restarted_services") or {}
                if families and "trading-engine-api.service" not in restarted:
                    # /meta compares against the API's imported contract constants.
                    raise release_deploy.DeployError("migrated without an API restart")
                checked = self.post_check(expected)
                if self.drill_rollback:  # an operator drill: prove the rollback path for real
                    raise release_deploy.DeployError("rollback drill")
            except Exception as exc:  # noqa: BLE001 - any failure after the move rolls back
                return self.roll_back(previous, moved, families, backup,
                                      f"{type(exc).__name__}: {exc}"[:300])
            self.save_state(in_flight=None, last_good_sha=moved, recovery=None)
            self.prune_backups()
            return Decision("deployed", detail={"target": target, "previous": previous,
                                                "migrated": families, **checked})

    def prune_backups(self, directory: str = "backups") -> None:
        """Once the host is verified, keep only the newest two report backups (trading-data is
        the backup of record), or saved producer data sets after a recovery."""
        try:
            items = prune_local.prune_entries(self.state_dir / directory, apply=True)
        except OSError as exc:
            self.steps.append(f"prune-{directory}:error:{exc}"[:200])
            return
        removed = sum(item["action"] == "removed" for item in items)
        failed = sum(item["action"] == "remove-failed" for item in items)
        self.steps.append(f"prune-{directory}:{removed}" + (f":failed:{failed}" if failed else ""))

    def roll_back(self, previous: str, moved: str, families: list[str], backup: Path,
                  error: str) -> Decision:
        if self.git(self.root, "rev-parse", "HEAD") != moved:
            return Decision("rolled-back", "rollback-deferred",
                            {"error": error, "previous": previous, "recovery": "next run"})
        try:
            self.restore_reports(families, backup)  # back to the committed bytes first
            self.git(self.root, "reset", "-q", "--keep", previous)
            code, summary = self.automation("--apply")
            if code:
                raise release_deploy.DeployError(f"re-apply: {summary.get('errors')}")
            self.ops._wait_health()
        except (Stop, OSError, release_deploy.DeployError) as exc:
            # Never terminal: the in-flight marker stays, so the next run recovers.
            return Decision("rolled-back", "rollback-failed",
                            {"error": error, "rollback_error": str(exc)[:300],
                             "previous": previous, "recovery": "next run"})
        self.save_state(in_flight=None)
        return Decision("rolled-back", detail={"error": error, "previous": previous})

    # ---- self-heal ----------------------------------------------------------------------------
    def recover(self, good: str, in_flight: dict | None, why: str) -> Decision:
        """Bring the live checkout back to ``good``, keeping data commits and untracked files."""
        state = self.load_state()
        attempts = state.get("recovery") or {}
        due = attempts.get("next_at")
        if due and self.now() < datetime.fromisoformat(due.replace("Z", "+00:00")):
            raise Stop("skipped", "recovery-backoff", next_at=due, why=why)
        # Only state-recorded recovery skips the nightly window: recovery that began with an
        # unhealthy probe alone stays gated like a deploy on every retry.
        origin = attempts.get("why", PROBE_ONLY) if attempts else why  # unknown: gated
        recorded = origin != PROBE_ONLY
        self._gate_now(lead=MUTATION_LEAD, recovery=recorded)
        detail: dict = {"why": why, "good": good}
        with self.mutation_locks():
            self._gate_now(lead=MUTATION_LEAD, recovery=recorded)
            try:
                head = self.git(self.root, "rev-parse", "HEAD")
                stamp = self.now().strftime("%Y%m%dT%H%M%SZ")
                self.git(self.root, "update-ref", f"refs/auto-deploy/pre-recovery-{stamp}", head)
                if in_flight and in_flight.get("backup"):
                    self.restore_reports(in_flight.get("families") or [],
                                         Path(in_flight["backup"]))
                picks = [commit for commit in self.git(
                    self.root, "rev-list", "--reverse", "--no-merges", "--cherry-pick",
                    "--right-only", f"{good}...{head}").split() if self._data_only(commit)]
                keep = self.run(["git", "reset", "-q", "--keep", good], cwd=self.root)
                saved = None
                if keep.returncode:
                    # --keep refuses over local edits: reset tracked files (untracked store
                    # files are never touched; the pre-recovery ref keeps every commit), after
                    # copying the producers' uncommitted data/ edits aside.
                    saved = self.save_dirty_data(stamp)
                    if saved:  # named before the reset, so a failed recovery's receipt keeps it
                        detail["data_saved"] = str(saved["dir"])
                    self.git(self.root, "reset", "-q", "--hard", good)
                    self.steps.append("recover:hard-reset")
                skipped = []
                for commit in picks:
                    done = self.run(["git", "cherry-pick", "--allow-empty", "--keep-redundant-commits",
                                     commit], cwd=self.root)
                    if done.returncode:
                        self.run(["git", "cherry-pick", "--abort"], cwd=self.root)
                        skipped.append(commit)
                detail.update(reapplied=len(picks) - len(skipped), skipped=skipped,
                              backup_ref=f"refs/auto-deploy/pre-recovery-{stamp}")
                if saved:
                    detail.update(self.restore_dirty_data(saved, head))
                    detail.pop("data_saved")  # restored, or named again in data_kept
                self.steps.append(f"recover:{head[:12]}->{good[:12]}")
                code, summary = self.automation("--apply")
                self.steps.append(f"apply:{summary.get('status')}")
                if code or not self.host_healthy():
                    raise release_deploy.DeployError("host unhealthy after recovery")
            except (Stop, OSError, RuntimeError, release_deploy.DeployError) as exc:
                if isinstance(exc, Stop) and exc.outcome != "failed":
                    raise
                if isinstance(exc, Stop):  # a failed git step: keep its command and error
                    exc = RuntimeError(f"{exc}: {exc.detail.get('command')}: "
                                       f"{exc.detail.get('error')}")
                failures = int(attempts.get("failures", 0)) + 1
                delay = min(RECOVERY_BASE * 2 ** (failures - 1), RECOVERY_CAP)
                if failures >= HEAL_AFTER:
                    blocked = self.heal_blocked()  # the recovery may have run long
                    if blocked:
                        self.steps.append(f"heal:skipped:{blocked}")
                        detail["heal_skipped"] = blocked
                    else:
                        self.heal_services()
                self.save_state(recovery={"failures": failures, "why": origin,
                                          "next_at": _iso(self.now() + delay),
                                          **({"data_saved": detail["data_saved"]}
                                             if "data_saved" in detail else {})})
                return Decision("recovery-failed", why, {**detail, "error": str(exc)[:300],
                                                         "failures": failures})
        self.save_state(in_flight=None, recovery=None, last_good_sha=good)
        self.prune_backups()
        self.prune_backups("recovery-data")
        return Decision("recovered", why, detail)

    def save_dirty_data(self, stamp: str) -> dict | None:
        """Copy uncommitted tracked ``data/`` edits aside before a hard reset discards them."""
        paths = sorted(path for path in self.live_dirty_paths() if path.startswith("data/"))
        if not paths:
            return None
        saved = self.state_dir / "recovery-data" / stamp
        for relative in paths:
            source = self.root / relative
            if source.is_file():  # a deleted path is restored as a deletion
                (saved / relative).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                shutil.copy2(source, saved / relative)
        return {"dir": saved, "paths": paths}

    def restore_dirty_data(self, saved: dict, head: str) -> dict:
        """Put saved edits back where the recovery left the committed file as it was before;
        otherwise keep the reset file and leave the saved copy for a person (named here)."""
        kept = []
        for relative in saved["paths"]:
            before, after = (self.git(self.root, "rev-parse", "-q", "--verify", f"{ref}:{relative}",
                                      check=False) for ref in (head, "HEAD"))
            if before != after:
                kept.append(relative)
                continue
            copy, live = saved["dir"] / relative, self.root / relative
            if copy.is_file():
                live.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(copy, live)
            else:
                live.unlink(missing_ok=True)
        self.steps.append(f"recover:data-restored:{len(saved['paths']) - len(kept)}")
        if not kept:
            shutil.rmtree(saved["dir"], ignore_errors=True)
            return {}
        return {"data_kept": {"dir": str(saved["dir"]), "paths": kept}}

    def same_code(self, first: str, second: str, *, root: Path | None = None,
                  proven: bool = False) -> bool:
        """Whether two commits (in the mirror, or ``root``) have the same tracked tree outside
        ``data/``. A git error counts as the same code (keep refusing) unless ``proven``
        asks for a successful comparison."""
        done = self.run(["git", "diff", "--quiet", first, second, "--", ".", ":(exclude)data"],
                        cwd=root or self.mirror, timeout=120)
        return done.returncode == 0 if proven else done.returncode != 1

    def _data_only(self, commit: str) -> bool:
        names = self.git(self.root, "diff-tree", "--no-commit-id", "--name-only", "-r",
                         commit).splitlines()
        return bool(names) and all(name.startswith("data/") for name in names)

    def converge(self, *, execute: bool) -> Decision | None:
        """Before deploying: recover an unverified host, or adopt verified manual changes."""
        state = self.load_state()
        good = state.get("last_good_sha")
        in_flight = state.get("in_flight")
        if not good:
            head = self.git(self.root, "rev-parse", "HEAD")
            if execute:  # the first real run trusts the deployed checkout
                self.save_state(last_good_sha=head)
            self.steps.append(f"bootstrap-good:{head[:12]}")
            return None
        why = None
        if in_flight:
            why = "unverified-deploy"
        elif state.get("recovery"):
            why = "recovery-pending"
        elif self.code_differs(good):
            if self.host_healthy():  # a person deployed by hand and the host is healthy
                head = self.git(self.root, "rev-parse", "HEAD")
                if execute:
                    rolled = (state.get("rolled_back") or {}).get("target")
                    # The rolled-back code now runs healthy by hand: stop refusing it.
                    forget = bool(rolled) and self.same_code(rolled, head, root=self.root,
                                                             proven=True)
                    self.save_state(last_good_sha=head,
                                    rolled_back=None if forget else state.get("rolled_back"))
                self.steps.append(f"adopted:{head[:12]}")
                return None
            why = PROBE_ONLY
        if why is None:
            return None
        if not execute:
            raise Stop("skipped", "would-recover", why=why, good=good)
        return self.recover(good, in_flight, why)

    # ---- one run ------------------------------------------------------------------------------
    def blocking_commit(self, deployed: str, target: str) -> tuple[str, list[str]] | None:
        """The oldest first-parent commit in the range that needs a person, with its reasons."""
        for commit in reversed(self.git(self.mirror, "rev-list", "--first-parent",
                                        f"{deployed}..{target}").split()):
            reasons = self.human_reasons(f"{commit}^", commit)
            if reasons:
                return commit, reasons
        return None

    def decide(self, *, execute: bool) -> Decision:
        self.execute = execute
        state = self.load_state()
        pending = bool(state.get("in_flight")) or (
            (state.get("recovery") or {}).get("why", PROBE_ONLY) != PROBE_ONLY)
        try:
            self._gate_now(recovery=pending)
        except Stop as stop:
            # Say whether a commit was waiting (fetching now would need the gates to pass).
            waiting = self.waiting_at_last_fetch()
            if stop.outcome == "skipped" and waiting is not None:
                stop.detail["waiting_at_last_fetch"] = waiting
            raise
        healed = self.converge(execute=execute)
        if healed is not None:
            return healed
        if pending:
            self._gate_now()
        state = self.load_state()
        origin, live_head = self.refresh_mirror()
        refused = state.get("refused") or {}
        if refused.get("origin") == origin:
            raise Stop("skipped", "refused-target", target=refused.get("target"),
                       refused_for=refused.get("reason"))
        try:
            decision = self._decide(execute=execute, origin=origin, live_head=live_head)
            decision.detail.setdefault("origin", origin)
            return decision
        except Stop as stop:
            if stop.outcome == "needs-human":
                stop.detail.setdefault("origin", origin)
            raise

    def _decide(self, *, execute: bool, origin: str, live_head: str) -> Decision:
        deployed = self.git(self.mirror, "merge-base", live_head, origin)
        target = self.pick_target(deployed, origin)
        held_back = None
        if self.human_reasons(deployed, target):
            commit, reasons = self.blocking_commit(deployed, target)
            limit = self.git(self.mirror, "rev-parse", f"{commit}^")
            if limit == deployed or self.git(self.mirror, "merge-base", limit,
                                             deployed) != deployed:
                raise Stop("needs-human", ",".join(reasons), target=target, blocking=commit)
            try:
                target = self.pick_target(deployed, limit)
            except Stop as stop:  # nothing green before the blocking commit
                raise Stop("needs-human", ",".join(reasons), target=target,
                           blocking=commit) from stop
            held_back = {"commit": commit, "reasons": reasons}
        rolled_back = (self.load_state().get("rolled_back") or {}).get("target")
        if rolled_back and self.same_code(rolled_back, target):
            # Only data-only commits since the rolled-back target: the same code would fail
            # again. Refused until a commit outside data/ changes the code.
            raise Stop("skipped", "refused-target", target=target, rolled_back=rolled_back)
        local = self.live_state(live_head, origin)
        families = self.migrations_needed(target)
        expected = {family.key: repin._literal(
            self.git(self.mirror, "show", f"{target}:{family.path}"),
            "EXPECTED_RUNTIME_CONTRACT_SHA256") for family in repin.FAMILIES}
        try:
            worktree = self.prepare_worktree(target)
            checks = self.gate(worktree, deployed)
        except Stop as stop:
            if stop.reason in CHECK_TIMEOUTS and self.execute:
                self.count_check_timeout(target, stop)
            raise
        if self.execute and self.load_state().get("check_timeouts"):
            self.save_state(check_timeouts=None)
        if families:
            try:
                checks["rehearsal"] = repin.rehearse(worktree, families, self.root)
            except repin.Refused as exc:
                raise Stop("needs-human", "rehearsal", error=str(exc)[:300]) from exc
        detail = {"deployed": deployed, "target": target, "local_data_commits": len(local),
                  "migrations": families, **checks}
        if held_back:
            detail["held_back"] = held_back
        if not execute:
            return Decision("would-deploy", detail=detail)
        decision = self.deploy(target, local, families, expected)
        decision.detail = {**detail, **decision.detail}
        return decision

    def record(self, decision: Decision, started: datetime, ended: datetime) -> Path:
        spec = job_contract.load_registry(REPO_ROOT).by_id.get(JOB_ID)
        run_id = str(uuid.uuid4())
        scheduled = _iso(started)
        reason = decision.label
        if decision.detail.get("target"):
            reason += f" target={decision.detail['target'][:12]}"
        if "waiting_at_last_fetch" in decision.detail:
            reason += f" waiting_at_last_fetch={decision.detail['waiting_at_last_fetch']}"
        if decision.detail.get("error"):
            reason += f" ({decision.detail['error']})"
        status = WORK_STATUS[decision.outcome]
        receipt = {
            "schema_version": 1, "run_id": run_id, "attempt": 1, "job_id": JOB_ID,
            "spec_version": spec.version if spec else 1,
            "spec_sha256": spec.spec_sha256 if spec else "unregistered",
            "idempotency_key": f"{JOB_ID}:{spec.version if spec else 1}:{scheduled}",
            "scheduled_for": scheduled, "started_at": scheduled, "ended_at": _iso(ended),
            "work_status": status, "reason": reason[:2000],
            "process_exit": 0 if status in {"success", "noop", "degraded"} else 1,
            "decision": decision.label, "detail": decision.detail, "steps": self.steps,
        }
        slot = started.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = self.logs_dir / "job-runs" / JOB_ID / slot / run_id / "receipt.json"
        write_text_atomic(path, json.dumps(receipt, indent=1, sort_keys=True) + "\n")
        if spec:  # 96 runs a day: keep only the registered retention
            run_job.prune_receipts(path.parents[2], spec.retention_days, ended)
        if self.locked_out or not self.execute:  # deploy state belongs to real runs only
            return path
        state_path = self.state_dir / "state.json"
        try:
            state = json.loads(state_path.read_text())
        except (OSError, ValueError):
            state = {}
        if decision.outcome in {"needs-human", "rolled-back"} and decision.detail.get("origin"):
            state["refused"] = {"origin": decision.detail["origin"],
                                "target": decision.detail.get("target"),
                                "reason": decision.label, "receipt": str(path)}
        target = decision.detail.get("target")
        if (decision.outcome == "rolled-back" and target and not self.drill_rollback
                and not self.same_code(decision.detail.get("deployed", ""), target,
                                       proven=True)):
            # Only new code is remembered as bad: not a drill, not a data-only target.
            state["rolled_back"] = {"target": target, "receipt": str(path)}
        remembered = (state.get("rolled_back") or {}).get("target")
        if decision.outcome == "deployed" and remembered and not self.same_code(remembered,
                                                                                 target):
            state.pop("rolled_back")  # different code deployed and verified
        if decision.outcome == "deployed":
            state["deployed_sha"] = decision.detail["target"]
        elif decision.detail.get("deployed") and decision.outcome not in {
                "rolled-back", "recovered", "recovery-failed"}:
            state["deployed_sha"] = decision.detail["deployed"]  # follows an adopted hand deploy
        state["last_attempt"] = {"at": _iso(ended), "decision": decision.label,
                                 "receipt": str(path)}
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_text_atomic(state_path, json.dumps(state, indent=1, sort_keys=True) + "\n")
        return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--execute", action="store_true", help="act; the default only decides")
    parser.add_argument("--engine-root", type=Path, default=ENGINE_ROOT)
    parser.add_argument("--state-dir", type=Path, default=STATE_DIR)
    parser.add_argument("--logs-dir", type=Path, help="receipt root (default ENGINE_ROOT/logs)")
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument("--autopush-lock", type=Path, default=AUTOPUSH_LOCK)
    parser.add_argument("--drill-rollback", action="store_true",
                        help="with --execute: fail the post-check once after it passes")
    args = parser.parse_args(argv)
    deployer = Deployer(engine_root=args.engine_root.expanduser(),
                        state_dir=args.state_dir.expanduser(), logs_dir=args.logs_dir,
                        api_url=args.api_url, autopush_lock=args.autopush_lock.expanduser())
    deployer.drill_rollback = args.drill_rollback and args.execute
    started = deployer.now()
    with ExitStack() as stack:
        try:
            stack.enter_context(deployer.run_lock())
            decision = deployer.decide(execute=args.execute)
        except Stop as stop:
            decision = Decision(stop.outcome, stop.reason, stop.detail)
        except (OSError, ValueError, KeyError, release_deploy.DeployError, repin.Refused) as exc:
            decision = Decision("failed", type(exc).__name__, {"error": str(exc)[:300]})
        receipt = deployer.record(decision, started, deployer.now())
    print(json.dumps({"decision": decision.label, "detail": decision.detail,
                      "steps": deployer.steps, "receipt": str(receipt)}, indent=1,
                     sort_keys=True))
    return 1 if decision.outcome in {"failed", "recovery-failed"} else 0


if __name__ == "__main__":
    sys.exit(main())
