"""The revision-21 deploy and rollback git flow, against a throwaway origin and checkout.

The checkout mirrors the live one: branch main tracking a bare origin, uncommitted producer
output under data/, and an approved merge commit on origin/main. Engine modules the scripts
call are small stand-ins inside the checkout and host helpers are stubs, so these tests
exercise the scripts' git, phase and backup handling, not the store tools.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
OPS = REPO / "ops" / "storage-r21"

STUBS = {
    "engine/__init__.py": "",
    "engine/lib/__init__.py": "",
    # The normal data commit: commit data/, push, rebase once onto a moved origin.
    "engine/sync.py": '''
import subprocess
def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout
git("add", "--", "data/")
if git("diff", "--cached", "--name-only", "--", "data/").strip():
    git("commit", "-q", "-m", "data", "--", "data/")
    if subprocess.run(["git", "push", "-q", "origin", "HEAD:main"]).returncode:
        git("pull", "-q", "--rebase", "origin", "main")
        git("push", "-q", "origin", "HEAD:main")
''',
    "engine/schema_migrations.py": '''
import json
print(json.dumps({"status": "planned", "expected_pre_catalog_sha256":
    "865f64aad4529c6f2cde3d0fb72d7b70dd968b85f49905681db1aef825d59a65"}))
''',
    "engine/lib/db.py": '''
DEFAULT_DB = "store/market.duckdb"
class _Result:
    def fetchone(self):
        return (0,)
class _Connection:
    def execute(self, *_args):
        return _Result()
    def close(self):
        pass
def connect(*_args, **_kwargs):
    return _Connection()
''',
    "tools/__init__.py": "",
    # A backup create that fails part-way, leaving a partial bundle behind; verify passes
    # only for a bundle a test marked verified.
    "tools/backup_database.py": '''
import json, pathlib, sys
bundle = pathlib.Path(sys.argv[2])
if sys.argv[1] == "create":
    bundle.mkdir(parents=True)
    (bundle / "market.duckdb").write_bytes(b"partial")
    sys.exit(1)
if (bundle / "verified").exists():
    print(json.dumps({"status": "ok", "manifest_sha256": "m"}))
    sys.exit(0)
sys.exit(1)
''',
    "tools/publish_snapshot.py": "print('{}')\n",
    # The previous code's forward runners: valid only on records carrying the deployed digest.
    "farm/__init__.py": "",
    "farm/experiment_runner.py": '''
import json, sys
record = json.load(open("data/reports/experiments/e1-spy-monday-forward.json"))
sys.exit(0 if record["digest"] == "deployed" else "E1 forward checkpoint is invalid")
''',
    "engine/forward_review.py": '''
import json, sys
path = "data/reports/forward/sector_momentum.json"
valid = json.load(open(path))["digest"] == "deployed"
json.dump({"status": "ACCUMULATING" if valid else "INVALID", "digest": "deployed"},
          open(path, "w"))
sys.exit(0 if valid else 1)
''',
    "engine/xs_forward_review.py": '''
import json, sys
path = "data/reports/forward/xs_momentum_12_1.json"
valid = json.load(open(path))["digest"] == "deployed"
json.dump({"status": "ACCUMULATING" if valid else "INVALID", "digest": "deployed"},
          open(path, "w"))
sys.exit(0 if valid else 1)
''',
}

HOST_STUB = """
p21_call() { echo "$1" >> "$P21_STATE/host-calls"; }
p21_capture() { p21_call capture; }
p21_pause_pullers() { p21_call pause-pullers; }
p21_resume_pullers() { p21_call resume-pullers; }
p21_quiesce() { p21_call quiesce; }
p21_autopush() { p21_call autopush; git push -q origin HEAD:main; }
p21_readers_ready() { p21_call readers; }
p21_api_url() { printf 'http://127.0.0.1:9'; }
p21_stage_units() { p21_call stage; }
p21_schedule_check() { p21_call "schedule-check $1"; }
p21_release() { p21_call release; }
p21_remove_new_units() { p21_call remove-new-units; }
p21_release_previous() { p21_call release-previous; }
"""


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def _commit(root: Path, files: dict[str, str], message: str) -> str:
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", message)
    return _git(root, "rev-parse", "HEAD")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    for key, value in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
                       "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}.items():
        monkeypatch.setenv(key, value)
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    _git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    author = tmp_path / "author"
    subprocess.run(["git", "clone", "-q", str(origin), str(author)], check=True,
                   capture_output=True)
    _git(author, "checkout", "-q", "-b", "main")
    files = {f"ops/storage-r21/{path.name}": path.read_text() for path in OPS.iterdir()}
    files.update(STUBS)
    deployed = json.dumps({"status": "ACCUMULATING", "digest": "deployed"})
    files.update({f"data/reports/{record}": deployed for record in (
        "experiments/e1-spy-monday-forward.json", "forward/sector_momentum.json",
        "forward/xs_momentum_12_1.json")})
    files.update({"code.txt": "previous code\n", "data/report.json": "{}\n",
                  ".gitignore": "store/\n",
                  "server/p15-registration.json": '{"registration_revision": 19}\n'})
    _commit(author, files, "base")
    _git(author, "push", "-q", "-u", "origin", "main")
    live = tmp_path / "live"
    subprocess.run(["git", "clone", "-q", str(origin), str(live)], check=True,
                   capture_output=True)
    (live / "store").mkdir()
    (live / "store" / "market.duckdb").write_bytes(b"primary bytes")
    # The approved branch, merged into origin/main before the window.
    _git(author, "checkout", "-q", "-b", "storage-r21")
    _commit(author, {"code.txt": "revision 21 code\n",
                     "server/p15-registration.json": '{"registration_revision": 20}\n'},
            "revision 21")
    _git(author, "checkout", "-q", "main")
    _git(author, "merge", "-q", "--no-ff", "-m", "Merge revision 21", "storage-r21")
    approved = _git(author, "rev-parse", "HEAD")
    _git(author, "push", "-q", "origin", "main")
    host = tmp_path / "host-stub.bash"
    host.write_text(HOST_STUB)
    return {"tmp": tmp_path, "origin": origin, "author": author, "live": live,
            "approved": approved, "host": host}


def _run(sandbox: dict, script: str, state: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "P21_ROOT": str(sandbox["live"]), "P21_STATE": str(state),
           "P21_APPROVED_SHA": sandbox["approved"], "P21_PY": sys.executable,
           "P21_HOST_HELPERS": str(sandbox["host"]), "P21_SYNC_VENV": "0",
           "P21_BACKUP_PARENT": str(sandbox["tmp"] / "backups"), "PYTHONPATH": ""}
    if script == "deploy":
        command = ["bash", str(OPS / "deploy.sh")]
    else:
        command = ["bash", str(state / "rollback.sh")]
    return subprocess.run(command, cwd=sandbox["tmp"], env=env, capture_output=True,
                          text=True, timeout=120)


def _state(state: Path) -> dict:
    values = {}
    for line in (state / "state.env").read_text().splitlines():
        key, _, value = line.partition("=")
        values[key] = value
    return values


def test_rollback_after_a_failed_backup_create_reverts_on_main_and_leaves_the_store(sandbox):
    live, author, approved = sandbox["live"], sandbox["author"], sandbox["approved"]
    # Main moves between approval and deploy, by a data-only commit.
    moved = _commit(author, {"data/other.json": "{\"n\": 1}\n"}, "data: other")
    _git(author, "push", "-q", "origin", "main")
    # Producer output the live checkout has not committed yet.
    (live / "data" / "report.json").write_text('{"tonight": true}\n')
    (live / "data" / "new.json").write_text("{}\n")
    store_before = (live / "store" / "market.duckdb").read_bytes()
    state = sandbox["tmp"] / "state"

    deploy = _run(sandbox, "deploy", state)

    assert deploy.returncode != 0, deploy.stdout
    assert "producers stay quiesced" in deploy.stderr
    recorded = _state(state)
    assert recorded["P21_PHASE"] == "code-switched"
    assert "R21_BACKUP" not in recorded and "R21_MANIFEST" not in recorded
    assert list((sandbox["tmp"] / "backups").iterdir())          # the partial bundle
    assert _git(live, "symbolic-ref", "--short", "HEAD") == "main"
    assert _git(live, "merge-base", "--is-ancestor", moved, "HEAD") == ""
    assert (live / "code.txt").read_text() == "revision 21 code\n"
    # The producer output went through the data commit to origin, not aside.
    assert _git(live, "status", "--porcelain", "--untracked-files=no") == ""
    assert _git(live, "show", "origin/main:data/report.json") == '{"tonight": true}'

    rollback = _run(sandbox, "rollback", state)

    assert rollback.returncode == 0, rollback.stderr
    assert _git(live, "symbolic-ref", "--short", "HEAD") == "main"
    head = _git(live, "rev-parse", "HEAD")
    assert head == _git(live, "rev-parse", "origin/main")
    assert _git(live, "rev-parse", "HEAD^") != approved              # data commits kept
    assert "Revert" in _git(live, "log", "-1", "--format=%s")
    assert (live / "code.txt").read_text() == "previous code\n"
    assert (live / "data" / "report.json").read_text() == '{"tonight": true}\n'
    assert (live / "data" / "new.json").exists()
    assert (live / "store" / "market.duckdb").read_bytes() == store_before
    log = (state / "rollback.log").read_text()
    assert "prove the primary unchanged since quiesce" in log
    assert "restore the primary" not in log
    assert (state / "host-calls").read_text().splitlines()[-2:] == [
        "readers", "release-previous"]

    again = _run(sandbox, "rollback", state)

    assert again.returncode == 0, again.stderr
    assert _git(live, "rev-parse", "HEAD") == head                   # reverted once
    assert "already reverted" in (state / "rollback.log").read_text()


def test_deploy_refuses_main_that_moved_past_the_merge_with_code(sandbox):
    live, author = sandbox["live"], sandbox["author"]
    before = _git(live, "rev-parse", "HEAD")
    _commit(author, {"code.txt": "unapproved\n"}, "unapproved code")
    _git(author, "push", "-q", "origin", "main")
    state = sandbox["tmp"] / "state"

    deploy = _run(sandbox, "deploy", state)

    assert deploy.returncode != 0
    assert "changes files outside data/" in deploy.stderr
    assert _git(live, "rev-parse", "HEAD") == before
    # Only the first step ran: the nightly and te-autopush were paused, then resumed.
    assert (state / "host-calls").read_text().splitlines() == [
        "capture", "pause-pullers", "resume-pullers"]
    assert "resumed" in deploy.stderr
    assert (live / "store" / "market.duckdb").read_bytes() == b"primary bytes"


def test_rollback_refuses_a_changed_primary_without_a_verified_backup(sandbox):
    state = sandbox["tmp"] / "state"
    assert _run(sandbox, "deploy", state).returncode != 0
    (sandbox["live"] / "store" / "market.duckdb").write_bytes(b"written after quiesce")

    rollback = _run(sandbox, "rollback", state)

    assert rollback.returncode != 0
    assert "no verified backup is recorded" in rollback.stderr
    assert (sandbox["live"] / "code.txt").read_text() == "revision 21 code\n"


def test_rollback_without_a_backup_refuses_a_phase_past_the_backup(sandbox):
    state = sandbox["tmp"] / "state"
    assert _run(sandbox, "deploy", state).returncode != 0
    with (state / "state.env").open("a") as handle:
        handle.write("P21_PHASE=migrated\n")

    rollback = _run(sandbox, "rollback", state)

    assert rollback.returncode != 0
    assert "needs the verified backup" in rollback.stderr
    assert json.loads((state / "store-identity.json").read_text())["wal"] is None


def _released_state(sandbox: dict, *, deployed_records: str = "deployed") -> Path:
    """The state a deploy leaves at release: merge pulled, store migrated, records re-pinned."""
    live, tmp = sandbox["live"], sandbox["tmp"]
    _git(live, "pull", "-q", "--ff-only")
    if deployed_records != "deployed":       # records the backup's commit already carried
        for record in ("experiments/e1-spy-monday-forward.json",):
            (live / "data/reports" / record).write_text(json.dumps({"digest": deployed_records}))
        _git(live, "commit", "-qam", "data: before the deploy")
        _git(live, "push", "-q", "origin", "HEAD:main")
    deployed_sha = _git(live, "rev-parse", "HEAD")
    bundle = tmp / "backups" / "pre-migration"
    bundle.mkdir(parents=True)
    (bundle / "market.duckdb").write_bytes(b"primary bytes")
    (bundle / "verified").touch()
    (live / "store" / "market.duckdb").write_bytes(b"migrated and written since release")
    # The contract migrations re-pinned the records; a nightly since release committed them.
    for record in ("experiments/e1-spy-monday-forward.json", "forward/sector_momentum.json",
                   "forward/xs_momentum_12_1.json"):
        (live / "data/reports" / record).write_text(json.dumps({"digest": "revision-21"}))
    _git(live, "commit", "-qam", "data: nightly after release")
    _git(live, "push", "-q", "origin", "HEAD:main")
    state = tmp / "state"
    state.mkdir(mode=0o700)
    for name in ("rollback.sh", "common.bash"):
        shutil.copy(OPS / name, state / name)
    (state / "state.env").write_text("".join(f"{key}={value}\n" for key, value in {
        "P21_ROOT": live, "P21_STATE": state, "P21_PY": sys.executable,
        "P21_PREDEPLOY_SHA": deployed_sha, "P21_APPROVED_SHA": sandbox["approved"],
        "P21_DEPLOYED_SHA": deployed_sha, "R21_BACKUP": bundle, "R21_MANIFEST": "m",
        "P21_PHASE": "released"}.items()))
    return state


def test_rollback_after_release_restores_the_forward_records_and_requires_a_valid_refresh(
    sandbox,
):
    live = sandbox["live"]
    state = _released_state(sandbox)

    rollback = _run(sandbox, "rollback", state)

    assert rollback.returncode == 0, rollback.stderr
    assert (live / "store" / "market.duckdb").read_bytes() == b"primary bytes"
    assert (live / "code.txt").read_text() == "previous code\n"
    for record in ("experiments/e1-spy-monday-forward.json", "forward/sector_momentum.json",
                   "forward/xs_momentum_12_1.json"):
        assert json.loads((live / "data/reports" / record).read_text())["digest"] == "deployed"
    assert _git(live, "status", "--porcelain", "--untracked-files=no") == ""
    assert _git(live, "rev-parse", "HEAD") == _git(live, "rev-parse", "origin/main")
    assert "Revert" in _git(live, "log", "--format=%s", "-6")
    log = (state / "rollback.log").read_text()
    assert "restore the forward records" in log and "forward refresh" in log
    assert (state / "host-calls").read_text().splitlines()[-2:] == [
        "readers", "release-previous"]


def test_rollback_after_release_stops_before_release_when_the_refresh_is_invalid(sandbox):
    # The records at the backup's commit are themselves unusable: the refresh fails closed
    # and producers stay quiesced.
    state = _released_state(sandbox, deployed_records="unusable")

    rollback = _run(sandbox, "rollback", state)

    assert rollback.returncode != 0
    assert "producers stay quiesced" in rollback.stderr
    calls = (state / "host-calls").read_text().splitlines()
    assert "release-previous" not in calls and "readers" not in calls
