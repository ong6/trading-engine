"""The CI workflow's structure and its paths filter (tools/affected_tests.py)."""
from __future__ import annotations

import http.client
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from tests.test_documentation_integrity import DOCUMENTATION_TREES
from tools import affected_tests as at

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
SETUP = yaml.safe_load((REPO_ROOT / ".github" / "actions" / "setup-engine" / "action.yml").read_text())
JOBS = WORKFLOW["jobs"]
TRIGGERS = WORKFLOW[True]  # YAML 1.1 reads the bare key `on` as a boolean


def _runs(job: str) -> str:
    return "\n".join(step.get("run", "") for step in JOBS[job]["steps"])


def test_paths_filter_lists_are_pinned():
    assert at.CONTENT_PATHS == ("data/", "docs/")
    assert at.CONTENT_SUFFIXES == (".csv", ".gif", ".html", ".ico", ".jpeg", ".jpg", ".json",
                                   ".jsonl", ".md", ".png", ".svg", ".txt", ".webp")
    assert at.FULL_SUITE_PATHS == (
        ".github/", "pyproject.toml", "tests/conftest.py", "tests/speed_plugin.py",
        "tests/content_reads.json", "tools/affected_tests.py", "uv.lock",
    )
    assert at.scope(["data/_meta.json", "docs/scope.md", "data/screens/latest.md"]) == "content"
    assert at.scope(["docs/history/incident-tools-2026-09-02/repair_restatements.py"]) == "code"
    assert at.scope(["docs/scope.md", "BUILDLOG.md"]) == "code"


def test_content_that_tests_read_still_triggers_those_tests():
    # Documentation integrity reads every Markdown file under data/ and docs/.
    assert {"data", "docs"} <= set(DOCUMENTATION_TREES)
    for name in ("tests/test_documentation_integrity.py", "tests/test_operating_contract.py"):
        assert name in at.CONTRACT_TESTS and name in at.CONTENT_READERS
    selection = at.select(["docs/scope-budget.json", "data/reports/league.md"])
    assert selection["mode"] == "selected"
    assert set(at.CONTRACT_TESTS) | set(at.CONTENT_READERS) <= set(selection["tests"])


def test_triggers_cover_main_pull_requests_the_schedule_and_manual_runs():
    assert TRIGGERS["push"]["branches"] == ["**"]
    assert "pull_request" in TRIGGERS
    assert re.fullmatch(r"\d+ \d+ \* \* \*", TRIGGERS["schedule"][0]["cron"])
    assert "workflow_dispatch" in TRIGGERS
    assert WORKFLOW["permissions"] == {"contents": "read"}
    concurrency = WORKFLOW["concurrency"]
    assert concurrency["cancel-in-progress"] == "${{ github.ref != 'refs/heads/main' }}"
    # each main commit has its own group: a queued main run never replaces a pending one
    assert "github.ref == 'refs/heads/main' && github.sha" in concurrency["group"]
    assert JOBS["changes"]["permissions"] == {"contents": "read", "actions": "read"}


def test_hygiene_always_runs_and_the_plan_gates_the_rest():
    assert "if" not in JOBS["hygiene"] and "needs" not in JOBS["hygiene"]
    assert "tools.public_hygiene --ci" in _runs("hygiene")
    assert "--ci-plan" in _runs("changes")
    assert JOBS["changes"]["steps"][0]["with"]["fetch-depth"] == 0
    gates = {
        "test": "needs.changes.outputs.tier == 'full'",
        "selected": "needs.changes.outputs.tier == 'selected'",
        "checks": "needs.changes.outputs.scope == 'code'",
        "ui-build": "needs.changes.outputs.scope == 'code'",
    }
    for job, condition in gates.items():
        assert JOBS[job]["needs"] == "changes"
        assert JOBS[job]["if"] == condition


def test_the_full_tier_runs_every_test_in_both_timezones():
    matrix = JOBS["test"]["strategy"]["matrix"]
    assert matrix == {"tz": ["UTC", "Asia/Singapore"], "shard": [0, 1, 2, 3]}
    assert JOBS["test"]["strategy"]["fail-fast"] is False
    command = next(line for line in _runs("test").splitlines() if "-m pytest" in line)
    assert "--test-shards=4 --test-shard=${{ matrix.shard }}" in command
    assert " -m " not in command.split("pytest", 1)[1] and " -k " not in command


def test_the_selected_tier_runs_the_tools_selection():
    assert "tools.affected_tests --base \"$BASE\" --head HEAD" in _runs("selected")
    matrix = JOBS["selected"]["strategy"]["matrix"]
    assert matrix["tz"] == "${{ fromJSON(needs.changes.outputs.timezones) }}"
    assert matrix["shard"] == "${{ fromJSON(needs.changes.outputs.shards) }}"
    first_shard = {step["run"] for step in JOBS["selected"]["steps"]
                   if step.get("if") == "matrix.shard == 0"}
    assert first_shard == {".venv/bin/ruff check .",
                           ".venv/bin/python -m compileall -q engine sim server tests farm tools"}


def test_one_gate_job_needs_every_job():
    gate = JOBS["ci"]
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == set(JOBS) - {"ci"}
    assert "--ci-verdict" in _runs("ci")


def test_actions_are_pinned_to_a_major_version():
    steps = [step for job in JOBS.values() for step in job["steps"]] + SETUP["runs"]["steps"]
    for step in steps:
        if "uses" in step and step["uses"] != "./.github/actions/setup-engine":
            assert re.fullmatch(r"[\w-]+/[\w-]+(/[\w-]+)*@v\d+", step["uses"]), step["uses"]


def test_python_jobs_restore_the_virtualenv_keyed_on_the_lock_and_save_it_before_tests():
    for job in ("test", "selected", "checks"):
        uses = [step.get("uses") for step in JOBS[job]["steps"]]
        assert "./.github/actions/setup-engine" in uses
        assert "uv sync" not in _runs(job)
    steps = SETUP["runs"]["steps"]
    names = [step.get("uses", step.get("run", "")).split("@")[0] for step in steps]
    restore, sync, save = (names.index("actions/cache/restore"),
                           names.index("uv sync --extra dev --frozen"),
                           names.index("actions/cache/save"))
    assert restore < sync < save == len(steps) - 1
    assert "hashFiles('uv.lock')" in steps[restore]["with"]["key"]
    assert "steps.python.outputs.python-version" in steps[restore]["with"]["key"]
    assert steps[save]["if"] == "steps.venv.outputs.cache-hit != 'true'"


def test_the_ui_build_skips_npm_ci_only_on_an_exact_node_modules_hit():
    steps = JOBS["ui-build"]["steps"]
    modules = next(step for step in steps if step.get("id") == "modules")
    assert "hashFiles('ui/package-lock.json', 'ui/package.json')" in modules["with"]["key"]
    assert "steps.node.outputs.node-version" in modules["with"]["key"]
    npm_ci = next(step for step in steps if step.get("run") == "npm ci")
    assert npm_ci["if"] == "steps.modules.outputs.cache-hit != 'true'"


def _commit(root: Path, files: dict[str, str | None]) -> str:
    """Write (or with None delete) ``files``, commit them and return the commit."""
    for name, text in files.items():
        if text is None:
            (root / name).unlink()
            continue
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c",
                    "user.email=t@example.invalid", "commit", "-qm", "c", "--allow-empty"],
                   check=True, capture_output=True)
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()


def _toy(root: Path, files: dict[str, str]) -> str:
    """A repository with one commit, then ``files`` committed; returns the first commit."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True, capture_output=True)
    base = _commit(root, {"engine/__init__.py": "", "tests/test_engine.py": "import engine\n",
                          "docs/guide.md": "# Guide\n"})
    _commit(root, files)
    return base


def test_a_content_push_selects_and_a_code_push_runs_everything(tmp_path):
    base = _toy(tmp_path / "content", {"docs/guide.md": "# Guide v2\n", "data/r.json": "{}\n"})
    plan = at.ci_plan("push", base, root=tmp_path / "content")
    assert (plan["tier"], plan["scope"], plan["timezones"]) == ("selected", "content",
                                                                 ["UTC", "Asia/Singapore"])
    assert plan["shard_count"] == len(plan["shards"]) >= 1
    base = _toy(tmp_path / "code", {"engine/__init__.py": "VALUE = 1\n"})
    assert at.ci_plan("push", base, root=tmp_path / "code")["tier"] == "full"


@pytest.mark.parametrize(("event", "base"), [
    ("schedule", "HEAD~1"), ("workflow_dispatch", "HEAD~1"), ("push", "0" * 40),
    ("push", ""), ("push", "1234567"),
])
def test_no_usable_base_or_a_scheduled_run_is_full(tmp_path, event, base):
    _toy(tmp_path, {"docs/guide.md": "# Guide v2\n"})
    plan = at.ci_plan(event, base, root=tmp_path)
    assert (plan["tier"], plan["shard_count"], plan["timezones"]) == (
        "full", 4, ["UTC", "Asia/Singapore"])


def test_pull_requests_and_branches_run_the_fast_tier_in_one_timezone(tmp_path):
    base = _toy(tmp_path / "code", {"engine/__init__.py": "VALUE = 1\n"})
    for event, ref in (("pull_request", "refs/pull/7/merge"), ("push", "refs/heads/lane")):
        plan = at.ci_plan(event, base, ref, root=tmp_path / "code")
        assert (plan["tier"], plan["scope"], plan["timezones"], plan["shards"]) == (
            "selected", "code", ["UTC"], [0])
    base = _toy(tmp_path / "project", {"pyproject.toml": "[project]\n"})
    plan = at.ci_plan("pull_request", base, "refs/pull/7/merge", root=tmp_path / "project")
    assert (plan["tier"], plan["timezones"], plan["shard_count"]) == ("selected", ["UTC"], 4)
    assert "full-suite path" in plan["reasons"][-1]


def test_a_content_push_after_an_untested_code_push_still_runs_everything(tmp_path):
    # A passed its full run; B (code) was cancelled, failed or skipped; C changes content.
    a = _toy(tmp_path, {"docs/guide.md": "# Guide v2\n"})
    b = _commit(tmp_path, {"engine/__init__.py": "VALUE = 1\n"})
    _commit(tmp_path, {"data/r.json": "{}\n"})
    assert at.ci_plan("push", b, root=tmp_path)["tier"] == "selected"  # what event.before gave
    plan = at.ci_plan("push", a, root=tmp_path)  # the last fully green commit
    assert (plan["tier"], plan["scope"]) == ("full", "code")


def test_a_code_change_reverted_within_the_range_is_still_code(tmp_path):
    base = _toy(tmp_path, {"engine/__init__.py": "VALUE = 1\n"})
    _commit(tmp_path, {"engine/__init__.py": ""})
    assert at.changed_files(base, "HEAD", root=tmp_path) == []
    assert at.ci_plan("push", base, root=tmp_path)["tier"] == "full"


def test_an_empty_range_or_a_rewind_is_full(tmp_path):
    first = _toy(tmp_path, {"docs/guide.md": "# Guide v2\n"})
    head = _commit(tmp_path, {})  # empty commit
    for event, ref in (("push", at.MAIN_REF), ("pull_request", "refs/pull/7/merge")):
        plan = at.ci_plan(event, head, ref, root=tmp_path)
        assert (plan["tier"], plan["scope"]) == ("full", "code"), plan["reasons"]
    subprocess.run(["git", "-C", str(tmp_path), "checkout", "-q", first], check=True)
    plan = at.ci_plan("push", head, root=tmp_path)  # main moved back behind its base
    assert plan["tier"] == "full" and "not an ancestor" in plan["reasons"][0]


def test_the_last_full_success_needs_every_full_test_job_green(monkeypatch):
    def job(name, conclusion="success"):
        return {"name": name, "conclusion": conclusion}

    full = [job(f"test ({tz}, {shard})") for tz in ("UTC", "Asia/Singapore") for shard in range(4)]
    runs = {"workflow_runs": [
        {"event": "push", "head_sha": "c1", "jobs_url": "j/selected"},
        {"event": "pull_request", "head_sha": "c2", "jobs_url": "j/full"},
        {"event": "push", "head_sha": "c3", "jobs_url": "j/red"},
        {"event": "schedule", "head_sha": "c4", "jobs_url": "j/full"},
    ]}
    pages = {"j/selected": [job("selected (UTC, 0)")], "j/full": full,
             "j/red": [*full[:-1], job("test (Asia/Singapore, 3)", "cancelled")]}

    def fake(url, token):
        assert token == "t"
        return runs if "/workflows/ci.yml/runs?" in url else {"jobs": pages[url.split("?")[0]]}

    monkeypatch.setattr(at, "github_json", fake)
    assert at.last_full_success("o/r", "t") == "c4"
    runs["workflow_runs"].pop()
    assert at.last_full_success("o/r", "t") is None


@pytest.mark.parametrize("lookup", [None, OSError("no network"), http.client.IncompleteRead(b"")])
def test_main_without_a_fully_green_base_plans_the_full_tier(monkeypatch, tmp_path, lookup):
    def last(*args):
        if isinstance(lookup, Exception):
            raise lookup
        return lookup

    monkeypatch.setattr(at, "last_full_success", last)
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_OUTPUT", str(tmp_path / "out"))
    assert at.main(["--ci-plan", "push", "--ref", at.MAIN_REF, "--base", "HEAD~1"]) == 0
    assert "tier=full\n" in (tmp_path / "out").read_text()


def _needs(tier="full", scope="code", **results):
    jobs = dict.fromkeys(("hygiene", "changes", "test", "selected", "checks", "ui-build"),
                         "skipped")
    jobs.update(hygiene="success", changes="success")
    jobs.update(results)
    needs = {name: {"result": result, "outputs": {}} for name, result in jobs.items()}
    needs["changes"]["outputs"] = {"tier": tier, "scope": scope}
    return needs


def test_the_gate_requires_what_the_plan_required():
    assert at.ci_verdict(_needs(test="success", checks="success", **{"ui-build": "success"})) == []
    assert at.ci_verdict(_needs("selected", "content", selected="success")) == []
    assert at.ci_verdict(_needs(checks="success", **{"ui-build": "success"})) == ["test: skipped"]
    assert at.ci_verdict(_needs("selected", "content", selected="failure")) == ["selected: failure"]
    assert at.ci_verdict(_needs("selected", "content", selected="success", hygiene="failure")) == [
        "hygiene: failure"]
    for tier, scope in (("full", "other"), ("full", None), ("selected", "")):
        assert at.ci_verdict(_needs(tier, scope, test="success", selected="success")) == [
            "checks: skipped", "ui-build: skipped"]
    assert at.ci_verdict(_needs("?", "content", test="success")) == ["selected: skipped"]
    broken = _needs(changes="failure")
    assert at.ci_verdict(broken) == ["changes: failure"]
    assert at.ci_verdict(_needs("selected", "content", selected="success", checks="cancelled")) == [
        "checks: cancelled"]


@pytest.mark.parametrize("workers", [["-n", "0"], ["-n", "2"]])
def test_the_duration_budget_fails_only_tests_not_marked_slow(workers):
    marked = "tests/test_study_bench.py"  # marked slow, about a second
    unmarked = "tests/test_affected_tests.py::test_joined_literal_path_parts_name_one_path"

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *workers,
             marked, unmarked, *args],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=300,
        )

    over = run("--duration-budget=0.000001")
    assert over.returncode == 1, over.stdout[-2000:]
    assert "1 test(s) over the 1e-06 s budget without @pytest.mark.slow:" in over.stdout
    assert unmarked in over.stdout and "test_study_bench" not in over.stdout.split("budget")[-1]
    assert run("--duration-budget=60").returncode == 0


def test_the_duration_budget_does_not_charge_shared_setup(monkeypatch):
    from types import SimpleNamespace

    from _pytest.reports import TestReport

    from tests import speed_plugin

    clock = iter([10.0, 28.0])
    monkeypatch.setattr(speed_plugin.time, "perf_counter", lambda: next(clock))
    monkeypatch.setitem(speed_plugin._SHARED_SETUP, "seconds", 0.0)
    with speed_plugin._shared_setup():  # e.g. waiting for another worker's calibration
        pass
    assert speed_plugin._SHARED_SETUP["seconds"] == 18.0

    report = TestReport("t.py::waits", ("t.py", 0, "waits"), {}, "passed", None, "call", [],
                        duration=20.0)
    report.shared_setup_seconds = 18.0
    report = TestReport._from_json(report._to_json())  # as xdist carries it to the controller
    budget = speed_plugin._DurationBudget(
        SimpleNamespace(getoption=lambda name: 15.0))
    budget.pytest_runtest_logreport(report)
    budget.pytest_runtest_logreport(TestReport(
        "t.py::slow", ("t.py", 1, "slow"), {}, "passed", None, "call", [], duration=16.0))
    assert budget.over_budget() == [("t.py::slow", 16.0)]


def test_main_runs_the_budget_and_nothing_else_does():
    test_env = JOBS["test"]["env"]
    assert test_env["DURATION_BUDGET"] == "${{ github.ref == 'refs/heads/main' && '15' || '' }}"
    assert '${DURATION_BUDGET:+--duration-budget=$DURATION_BUDGET}' in _runs("test")
    assert "duration-budget" not in _runs("selected")
