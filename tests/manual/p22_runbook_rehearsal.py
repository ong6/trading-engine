"""Exercise ``tools.release_deploy`` with an isolated checkout and fake host controls.

This is a manual acceptance wrapper, not a pytest test.  It never calls the real systemd user
manager or crontab.  The input is one approved immutable snapshot plus its matching evidence
tree; all database copies are removed before the wrapper exits.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from tools.install_automation import UNIT_SOURCES


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text)
    path.chmod(0o755)


def _fake_host(output: Path) -> Path:
    commands = output / "fake-host"
    commands.mkdir()
    units = {
        name: {
            "Id": name,
            "LoadState": "loaded",
            "ActiveState": "active",
            "SubState": "running",
            "UnitFileState": "enabled",
            "ExecStart": "fixture",
            "Triggers": "",
            "MainPID": "17",
            "ControlGroup": "",
        }
        for name in UNIT_SOURCES
    }
    for name in ("te-autopush.service", "te-autopush.timer"):
        units[name] = {**next(iter(units.values())), "Id": name}
    (output / "host-state.json").write_text(json.dumps({"units": units}, indent=2) + "\n")
    _write_executable(
        commands / "systemctl",
        """#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
p=Path(os.environ['RELEASE_HARNESS_HOST']); s=json.loads(p.read_text()); a=sys.argv[1:]
if '--user' in a:a.remove('--user')
if a[0] in ('list-unit-files','list-units'):
 print('\\n'.join(f'{n} loaded active running' for n in sorted(s['units'])))
elif a[0]=='list-jobs': pass
elif a[0]=='show':
 n=a[1]
 if n=='cron': u={'LoadState':'loaded','ActiveState':'active'}
 elif n=='crond': u={'LoadState':'not-found','ActiveState':'inactive'}
 else:u=s['units'].get(n,{'Id':n,'LoadState':'not-found','ActiveState':'inactive','SubState':'dead','UnitFileState':'disabled','ExecStart':'','Triggers':'','MainPID':'0','ControlGroup':''})
 print('\\n'.join(f'{k}={v}' for k,v in u.items()))
elif a[0] in ('is-enabled','is-active'):
 names=[x for x in a[1:] if not x.startswith('-')]
 key='UnitFileState' if a[0]=='is-enabled' else 'ActiveState'
 values=[s['units'].get(n,{}).get(key,'disabled' if key=='UnitFileState' else 'inactive') for n in names]
 if '--quiet' not in a: print('\\n'.join(values))
 sys.exit(0 if all(v in ('enabled','active') for v in values) else 1)
elif a[0] in ('stop','start','restart','enable','disable'):
 names=[x for x in a[1:] if not x.startswith('-')]
 for n in names:
  u=s['units'].setdefault(n,{'Id':n,'LoadState':'loaded','SubState':'dead','ExecStart':'','Triggers':'','ControlGroup':''})
  if a[0]=='stop':u.update(ActiveState='inactive',MainPID='0')
  elif a[0] in ('start','restart'):u.update(ActiveState='active',MainPID='17')
  elif a[0]=='enable':u['UnitFileState']='enabled'
  else:u['UnitFileState']='disabled'
 p.write_text(json.dumps(s))
elif a[0]=='daemon-reload':pass
else:sys.exit(2)
""",
    )
    _write_executable(
        commands / "crontab",
        """#!/usr/bin/env python3
import os,sys
from pathlib import Path
p=Path(os.environ['RELEASE_HARNESS_CRON']);a=sys.argv[1:]
if a==['-l']:
 if not p.exists():print('no crontab for fixture',file=sys.stderr);sys.exit(1)
 print(p.read_text(),end='')
elif a==['-r']:p.unlink(missing_ok=True)
elif a==['-']:p.write_text(sys.stdin.read())
else:sys.exit(2)
""",
    )
    _write_executable(commands / "ps", "#!/bin/sh\nexit 0\n")
    _write_executable(commands / "timedatectl", "#!/bin/sh\nprintf 'Etc/UTC\\n'\n")
    _write_executable(
        commands / "loginctl",
        "#!/bin/sh\nif [ \"$1\" = show-user ]; then printf 'yes\\n'; fi\n",
    )
    return commands


def _server(output: Path, port: int) -> subprocess.Popen[str]:
    script = output / "semantic-server.py"
    script.write_text(
        """import json,sys
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
class H(BaseHTTPRequestHandler):
 count=0
 def do_GET(self):
  if self.path=='/health':
   H.count+=1; body=json.dumps({'ok':True,'status':'ok','db_readable':True}).encode()
   self.send_response(200);self.send_header('Content-Type','application/json')
   if H.count%2==0:self.send_header('X-Data-Source','snapshot')
  elif self.path=='/meta':body=b'{}';self.send_response(200);self.send_header('Content-Type','application/json')
  else:body=b'<html>fixture</html>';self.send_response(200);self.send_header('Content-Type','text/html')
  self.end_headers();self.wfile.write(body)
 def log_message(self,*_args):pass
ThreadingHTTPServer(('127.0.0.1',int(sys.argv[1])),H).serve_forever()
"""
    )
    return subprocess.Popen(
        [sys.executable, str(script), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--approved-sha", required=True)
    parser.add_argument("--adapter-set", choices=("none", "revision-15"), default="none")
    parser.add_argument("--d0")
    parser.add_argument("--port", type=int, default=18142)
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    if shutil.disk_usage(output).free - args.snapshot.stat().st_size < 70 * 1024**3:
        raise RuntimeError("copying the snapshot would leave less than 70 GiB free")
    home = output / "home"
    root = home / "trading-engine"
    home.mkdir()
    subprocess.run(["git", "clone", "--no-hardlinks", str(repo), str(root)], check=True)
    original = subprocess.check_output(
        ["git", "rev-parse", f"{args.approved_sha}^"], cwd=root, text=True
    ).strip()
    subprocess.run(["git", "checkout", "-B", "main", original], cwd=root, check=True)
    (root / ".venv").symlink_to(repo / ".venv")
    excludes = output / "git-excludes"
    excludes.write_text(".venv\n")
    subprocess.run(
        ["git", "config", "core.excludesFile", str(excludes)], cwd=root, check=True
    )
    shutil.rmtree(root / "data")
    shutil.copytree(args.evidence, root / "data")
    database = root / "store/market.duckdb"
    database.parent.mkdir(exist_ok=True)
    shutil.copy2(args.snapshot, database)
    evidence_logs = args.evidence.resolve().parent / "logs"
    if evidence_logs.is_dir():
        shutil.copytree(evidence_logs, root / "logs", dirs_exist_ok=True)
    else:
        (root / "logs").mkdir(exist_ok=True)
    (home / ".config/systemd/user").mkdir(parents=True)
    fake_host = _fake_host(output)
    cron = output / "crontab"
    cron.write_text("fixture cron\n")
    state = output / "release-state"
    server = _server(output, args.port)
    for _attempt in range(50):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{args.port}/ready", timeout=1).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        server.terminate()
        server.wait(timeout=10)
        raise RuntimeError("isolated semantic server did not start")
    environment = os.environ | {
        "PYTHONPATH": str(repo),
        "RELEASE_HARNESS_HOST": str(output / "host-state.json"),
        "RELEASE_HARNESS_CRON": str(cron),
    }
    release_tools = {name: shutil.which(name) for name in ("git", "uv", "node", "npm")}
    if any(path is None for path in release_tools.values()):
        raise RuntimeError("manual harness requires explicit git, uv, node and npm executables")
    base = [
        str(repo / ".venv/bin/python"),
        "-m",
        "tools.release_deploy",
        "--repo-root",
        str(root),
        "--database",
        str(database),
        "--home",
        str(home),
        "--host-command-dir",
        str(fake_host),
        "--git-path",
        release_tools["git"],
        "--uv-path",
        release_tools["uv"],
        "--node-path",
        release_tools["node"],
        "--npm-path",
        release_tools["npm"],
        "--api-url",
        f"http://127.0.0.1:{args.port}",
        "--ui-url",
        f"http://127.0.0.1:{args.port}",
        "--minimum-free-bytes",
        "0",
    ]

    def run(name: str, tail: list[str]) -> dict:
        result = subprocess.run(base + tail, env=environment, text=True, capture_output=True)
        (output / f"{name}.stdout").write_text(result.stdout)
        (output / f"{name}.stderr").write_text(result.stderr)
        if result.returncode != 0:
            raise RuntimeError(f"{name} failed with exit {result.returncode}")
        return json.loads(result.stdout)

    try:
        prepare = [
            "prepare",
            str(state),
            "--approved-sha",
            args.approved_sha,
            "--adapter-set",
            args.adapter_set,
        ]
        if args.d0:
            prepare.extend(("--d0", args.d0))
        assert run("prepare-plan", prepare)["status"] == "planned"
        assert run("prepare", prepare + ["--execute"])["status"] == "prepared"
        assert run("apply-plan", ["apply", str(state)])["status"] == "planned"
        applied = run("apply", ["apply", str(state), "--execute"])
        if applied["status"] == "awaiting-migration-approval":
            applied = run(
                "apply-approved",
                ["apply", str(state), "--approve-plan", applied["plan_sha256"], "--execute"],
            )
        if applied["status"] == "awaiting-optional-units":
            applied = run(
                "apply-optional-accepted",
                [
                    "apply",
                    str(state),
                    "--approve-optional",
                    applied["plan_sha256"],
                    "--execute",
                ],
            )
        assert applied["status"] == "applied"
        assert run("verify", ["verify", str(state), "--execute"])["status"] == "verified"
        assert run("rollback", ["rollback", str(state), "--execute"])["status"] == "rolled-back"
        assert (
            run(
                "resume",
                ["resume", str(state), "--reconciled-sha", original, "--execute"],
            )["status"]
            == "resumed"
        )
        (output / "result.json").write_text(
            json.dumps({"status": "passed", "original_sha": original}, indent=2) + "\n"
        )
        return 0
    finally:
        server.terminate()
        server.wait(timeout=10)
        deleted = []
        for path in output.rglob("*.duckdb*"):
            if path.is_file() or path.is_symlink():
                deleted.append(
                    {"path": str(path.relative_to(output)), "bytes": path.stat().st_size}
                )
                path.unlink()
        if root.exists():
            shutil.rmtree(root)
        prepared = state / "prepared"
        if prepared.exists():
            shutil.rmtree(prepared)
        (output / "cleanup.json").write_text(json.dumps({"deleted": deleted}, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
