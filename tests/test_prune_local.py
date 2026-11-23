"""tools/prune_local.py on temporary roots and real git clones."""
from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tools import prune_local

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
LATER = datetime.now(UTC) + timedelta(days=2)  # everything created by a test is "idle" then


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True).stdout.strip()


def _commit(repo: Path, name: str, text: str, message: str) -> str:
    (repo / name).write_text(text)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _age(path: Path, seconds: float) -> None:
    moment = datetime.now(UTC).timestamp() - seconds
    os.utime(path, (moment, moment), follow_symlinks=False)


@pytest.fixture
def lanes(tmp_path: Path, monkeypatch):
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)
    origin = tmp_path / "ong6/trading-engine.git"
    origin.parent.mkdir()
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    seed = tmp_path / "seed"
    _git(tmp_path, "clone", "-q", str(origin), str(seed))
    _commit(seed, ".gitignore", "/store/\n", "ignore")
    _commit(seed, "README.md", "engine\n", "readme")
    _git(seed, "push", "-q", "origin", "HEAD:refs/heads/main")
    _git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    root = tmp_path / "engine-lanes"
    root.mkdir()

    def clone(name: str) -> Path:
        path = root / name
        _git(root, "clone", "-q", str(origin), name)
        return path

    return {"root": root, "origin": origin, "seed": seed, "clone": clone,
            "claims": root / "CLAIMS.md"}


def _verdicts(lanes, *, apply=False) -> dict[str, dict]:
    items = prune_local.prune_lanes(lanes["root"], lanes["claims"], apply=apply, now=LATER)
    return {Path(item["path"]).name: item for item in items}


def test_a_merged_clean_idle_clone_is_removed_only_with_apply(lanes):
    clone = lanes["clone"]("done")
    (clone / "store").mkdir()
    (clone / "store/copy.duckdb").write_text("ignored")  # ignored files do not keep a clone
    assert _verdicts(lanes)["done"]["action"] == "remove"
    assert clone.exists()
    assert _verdicts(lanes, apply=True)["done"]["action"] == "removed"
    assert not clone.exists()


def test_dirty_untracked_and_stashed_clones_are_kept(lanes):
    tracked = lanes["clone"]("tracked")
    (tracked / "README.md").write_text("edited\n")
    untracked = lanes["clone"]("untracked")
    (untracked / "notes.txt").write_text("draft\n")
    stashed = lanes["clone"]("stashed")
    (stashed / "README.md").write_text("stash me\n")
    _git(stashed, "stash", "-q")
    verdicts = _verdicts(lanes, apply=True)
    assert verdicts["tracked"]["reason"] == "dirty"
    assert verdicts["untracked"]["reason"] == "dirty"
    assert verdicts["stashed"]["reason"] == "stash"
    assert all(path.exists() for path in (tracked, untracked, stashed))


def test_an_unpushed_branch_keeps_the_clone_and_a_pushed_one_does_not(lanes):
    work = lanes["clone"]("work")
    _git(work, "checkout", "-q", "-b", "feature")
    sha = _commit(work, "x.py", "x = 1\n", "feature work")
    _git(work, "checkout", "-q", "main")
    item = _verdicts(lanes)["work"]
    assert item["reason"] == "unpushed-commits"
    assert item["branches"] == {"feature": [sha[:12]]}
    _git(work, "push", "-q", "origin", "feature")
    assert _verdicts(lanes)["work"]["action"] == "remove"


def test_a_rebased_patch_equivalent_branch_counts_as_merged(lanes):
    work = lanes["clone"]("rebased")
    _git(work, "checkout", "-q", "-b", "feature")
    _commit(work, "x.py", "x = 1\n", "feature work")
    # main moves on, then lands the same patch on top (a rebase-merge): new SHA, same patch.
    seed = lanes["seed"]
    _git(seed, "pull", "-q", "origin", "main")
    _commit(seed, "y.py", "y = 1\n", "other work")
    _commit(seed, "x.py", "x = 1\n", "feature work (rebased)")
    _git(seed, "push", "-q", "origin", "HEAD:main")
    assert _verdicts(lanes)["rebased"]["action"] == "remove"
    _commit(work, "z.py", "z = 1\n", "not landed")
    assert _verdicts(lanes)["rebased"]["reason"] == "unpushed-commits"


def test_a_branch_deleted_upstream_is_not_on_origin(lanes):
    work = lanes["clone"]("gone")
    _git(work, "checkout", "-q", "-b", "feature")
    _commit(work, "x.py", "x = 1\n", "feature work")
    _git(work, "push", "-q", "origin", "feature")
    assert _verdicts(lanes)["gone"]["action"] == "remove"
    _git(lanes["seed"], "push", "-q", "origin", ":feature")  # the stale tracking ref stays
    assert _verdicts(lanes)["gone"]["reason"] == "unpushed-commits"


def test_stay_claimed_recent_and_non_git_directories_are_kept(lanes):
    lanes["clone"]("p25-docs")
    lanes["clone"]("p25-docs-old")
    fresh = lanes["clone"]("fresh")
    (fresh / "README.md").touch()
    os.utime(fresh / "README.md", (LATER.timestamp() - 3600,) * 2)
    (lanes["root"] / "scratch").mkdir()
    lanes["claims"].write_text("| P25 | `~/engine-lanes/p25-docs` | docs; p25-docs stay claimed |\n"
                               "| old | p25-docs-old | released |\n")
    verdicts = _verdicts(lanes, apply=True)
    assert verdicts["p25-docs"]["reason"] == "stay-claimed"
    assert verdicts["p25-docs-old"]["action"] == "removed"
    assert verdicts["fresh"]["reason"] == "recent-change"
    assert verdicts["scratch"]["reason"] == "not-git"
    assert (lanes["root"] / "scratch").exists()


def test_stay_claimed_matches_whole_names_only(tmp_path):
    claims = tmp_path / "CLAIMS.md"
    claims.write_text("stay claimed: r25-api, p24-meta-split.\n"
                      "p24-storage-r18 released\n")
    names = ["r25-api", "r25", "p24-meta-split", "p24-meta-split.work", "p24-storage-r18"]
    assert prune_local.stay_claimed(claims, names) == {"r25-api", "p24-meta-split"}
    assert prune_local.stay_claimed(tmp_path / "missing.md", names) == set()


def test_other_origins_failed_fetches_and_operations_in_progress_keep_the_clone(lanes):
    other = lanes["clone"]("other")
    _git(other, "remote", "set-url", "origin", str(lanes["root"].parent / "elsewhere.git"))
    offline = lanes["clone"]("offline")
    _git(offline, "remote", "set-url", "origin",
         str(lanes["root"].parent / "missing/ong6/trading-engine.git"))
    merging = lanes["clone"]("merging")
    (merging / ".git/MERGE_HEAD").write_text(_git(merging, "rev-parse", "HEAD"))
    verdicts = _verdicts(lanes, apply=True)
    assert verdicts["other"]["reason"] == "other-origin"
    assert verdicts["offline"]["reason"] == "fetch-failed"
    assert verdicts["merging"]["reason"] == "operation-in-progress"


def test_backups_keep_the_newest_two_and_the_in_flight_one(tmp_path):
    state = tmp_path / "state"
    backups = state / "auto-deploy/backups"
    for age, name in enumerate(["20261123T100000Z", "20261122T100000Z", "20261121T100000Z",
                                "20261120T100000Z"]):
        (backups / name).mkdir(parents=True)
        (backups / name / "report.json").write_text("{}")
        _age(backups / name, age * 3600)
    (state / "auto-deploy/state.json").write_text(json.dumps(
        {"in_flight": {"backup": str(backups / "20261120T100000Z")}}))
    store = tmp_path / "engine/store/backups"
    for age, name in enumerate(["c", "b", "a"]):
        (store / name).mkdir(parents=True)
        _age(store / name, age * 3600)
    result = prune_local.plan(state_root=state, engine_root=tmp_path / "engine",
                              lanes_root=tmp_path / "none", apply=True)
    deploy = {Path(item["path"]).name: (item["action"], item["reason"])
              for item in result["auto_deploy_backups"]}
    assert deploy == {"20261123T100000Z": ("keep", "newest-2"),
                      "20261122T100000Z": ("keep", "newest-2"),
                      "20261121T100000Z": ("removed", "older-than-newest-2"),
                      "20261120T100000Z": ("keep", "in-flight")}
    assert sorted(path.name for path in store.iterdir()) == ["b", "c"]
    assert result["summary"] == {"removed": 2, "kept_by_reason": {"in-flight": 1, "newest-2": 4}}


def _release(root: Path, name: str, created: str, phase: str | None) -> Path:
    release = root / name
    (release / "recovery").mkdir(parents=True)
    (release / "recovery/market.duckdb").write_text("copy")
    if phase is not None:
        (release / "state.json").write_text(json.dumps({"created_at": created, "phase": phase}))
    return release / "recovery"


def test_release_recovery_is_removed_only_when_final_and_not_among_the_newest_two(tmp_path):
    root = tmp_path / "releases"
    newest = _release(root, "r6", "2026-11-06T00:00:00Z", "applying")
    second = _release(root, "r5", "2026-11-05T00:00:00Z", "verified")
    pending = _release(root, "r4", "2026-11-04T00:00:00Z", "awaiting-migration-approval")
    rolled = _release(root, "r3", "2026-11-03T00:00:00Z", "rolled-back")
    unreadable = _release(root, "r2", "", None)
    (root / "r1").mkdir()  # no recovery bundle: nothing to report
    plan = {Path(item["path"]).parent.name: (item["action"], item["reason"])
            for item in prune_local.prune_releases(sorted(root.iterdir()))}
    assert plan == {"r6": ("keep", "newest-2-releases"), "r5": ("keep", "newest-2-releases"),
                    "r4": ("keep", "phase-not-final"), "r3": ("remove", "final-release"),
                    "r2": ("keep", "state-unreadable")}
    prune_local.prune_releases(sorted(root.iterdir()), apply=True)
    assert [path.exists() for path in (newest, second, pending, rolled, unreadable)] == [
        True, True, True, False, True]
    assert (root / "r3/state.json").exists()  # only the recovery bundle goes


def test_main_prints_a_dry_run_plan(tmp_path, capsys):
    backups = tmp_path / "state/auto-deploy/backups"
    for age, name in enumerate("cba"):
        (backups / name).mkdir(parents=True)
        _age(backups / name, age * 60)
    assert prune_local.main(["--state-root", str(tmp_path / "state"), "--engine-root",
                             str(tmp_path / "engine"), "--lanes-root", str(tmp_path / "lanes")]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry-run" and out["summary"]["remove"] == 1
    assert (backups / "a").exists()


def test_release_dirs_include_the_older_deploy_spelling(tmp_path):
    state = tmp_path / "state" / "trading-engine"
    _release(state / "releases", "r30", "2026-11-30T00:00:00Z", "verified")
    _release(tmp_path / "state", "r27-deploy", "2026-11-23T00:00:00Z", "verified")
    (tmp_path / "state" / "r21-deploy").mkdir()  # hand-made receipts: no recovery bundle
    (tmp_path / "state" / "store-sync.log").write_text("")
    names = [path.name for path in prune_local.release_dirs(state)]
    assert names == ["r21-deploy", "r27-deploy", "r30"]
    items = prune_local.prune_releases(prune_local.release_dirs(state))
    assert sorted(Path(item["path"]).parent.name for item in items) == ["r27-deploy", "r30"]
