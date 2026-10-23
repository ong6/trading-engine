"""The revision-20 deploy and rollback git flow, against a throwaway origin and checkout.

The checkout mirrors the live one: branch main tracking a bare origin, uncommitted producer
output under data/, and an approved merge commit on origin/main. Engine modules the scripts
call are small stand-ins inside the checkout and host helpers are stubs, so these tests
exercise the scripts' git, phase and backup handling, not the store tools.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
OPS = REPO / "ops" / "storage-r20"

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
    # A backup create that fails part-way, leaving a partial bundle behind.
    "tools/backup_database.py": '''
import pathlib, sys
if sys.argv[1] == "create":
    bundle = pathlib.Path(sys.argv[2])
    bundle.mkdir(parents=True)
    (bundle / "market.duckdb").write_bytes(b"partial")
sys.exit(1)
''',
}

HOST_STUB = """
p20_call() { echo "$1" >> "$P20_STATE/host-calls"; }
p20_capture() { p20_call capture; }
p20_quiesce() { p20_call quiesce; }
p20_autopush() { p20_call autopush; git push -q origin HEAD:main; }
p20_readers_ready() { p20_call readers; }
p20_api_url() { printf 'http://127.0.0.1:9'; }
p20_stage_units() { p20_call stage; }
p20_schedule_check() { p20_call "schedule-check $1"; }
p20_release() { p20_call release; }
p20_remove_new_units() { p20_call remove-new-units; }
p20_release_previous() { p20_call release-previous; }
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
    files = {f"ops/storage-r20/{path.name}": path.read_text() for path in OPS.iterdir()}
    files.update(STUBS)
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
    _git(author, "checkout", "-q", "-b", "storage-r20")
    _commit(author, {"code.txt": "revision 20 code\n",
                     "server/p15-registration.json": '{"registration_revision": 20}\n'},
            "revision 20")
    _git(author, "checkout", "-q", "main")
    _git(author, "merge", "-q", "--no-ff", "-m", "Merge revision 20", "storage-r20")
    approved = _git(author, "rev-parse", "HEAD")
    _git(author, "push", "-q", "origin", "main")
    host = tmp_path / "host-stub.bash"
    host.write_text(HOST_STUB)
    return {"tmp": tmp_path, "origin": origin, "author": author, "live": live,
            "approved": approved, "host": host}


def _run(sandbox: dict, script: str, state: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "P20_ROOT": str(sandbox["live"]), "P20_STATE": str(state),
           "P20_APPROVED_SHA": sandbox["approved"], "P20_PY": sys.executable,
           "P20_HOST_HELPERS": str(sandbox["host"]), "P20_SYNC_VENV": "0",
           "P20_BACKUP_PARENT": str(sandbox["tmp"] / "backups"), "PYTHONPATH": ""}
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
    assert recorded["P20_PHASE"] == "code-switched"
    assert "R20_BACKUP" not in recorded and "R20_MANIFEST" not in recorded
    assert list((sandbox["tmp"] / "backups").iterdir())          # the partial bundle
    assert _git(live, "symbolic-ref", "--short", "HEAD") == "main"
    assert _git(live, "merge-base", "--is-ancestor", moved, "HEAD") == ""
    assert (live / "code.txt").read_text() == "revision 20 code\n"
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
    assert not (state / "host-calls").exists()                       # nothing was stopped
    assert (live / "store" / "market.duckdb").read_bytes() == b"primary bytes"


def test_rollback_refuses_a_changed_primary_without_a_verified_backup(sandbox):
    state = sandbox["tmp"] / "state"
    assert _run(sandbox, "deploy", state).returncode != 0
    (sandbox["live"] / "store" / "market.duckdb").write_bytes(b"written after quiesce")

    rollback = _run(sandbox, "rollback", state)

    assert rollback.returncode != 0
    assert "no verified backup is recorded" in rollback.stderr
    assert (sandbox["live"] / "code.txt").read_text() == "revision 20 code\n"


def test_rollback_without_a_backup_refuses_a_phase_past_the_backup(sandbox):
    state = sandbox["tmp"] / "state"
    assert _run(sandbox, "deploy", state).returncode != 0
    with (state / "state.env").open("a") as handle:
        handle.write("P20_PHASE=migrated\n")

    rollback = _run(sandbox, "rollback", state)

    assert rollback.returncode != 0
    assert "needs the verified backup" in rollback.stderr
    assert json.loads((state / "store-identity.json").read_text())["wal"] is None
