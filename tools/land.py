#!/usr/bin/env python3
"""Land a reviewed branch on ``main`` from a lane clone; the deployer takes it from there.

``python -m tools.land BRANCH [--lane DIR] [--reason-file FILE] [--push]``

1. clone the repository into ``--lane`` (default ``~/engine-lanes/land``) if it is missing,
   fetch ``origin`` and reset the lane's ``main`` to ``origin/main``;
2. merge ``origin/BRANCH`` (a conflict stops the run with the merge aborted);
3. ``tools.repin --check``; when a registration revision is needed, write it with
   ``--reason-file`` (one sentence) or stop and ask for one;
4. the fast tier (``tools.affected_tests --run``), then the full suite;
5. with ``--push``, push ``main``. Without it the lane is left ready to push.

Exit 0 when landed (or ready to push), 2 when a step refused.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LANE = Path.home() / "engine-lanes" / "land"


class Refused(RuntimeError):
    """A landing step failed; the lane shows where."""


def step(argv: list[str], cwd: Path, label: str) -> None:
    print(f"== {label}: {' '.join(argv)}", flush=True)
    if subprocess.run(argv, cwd=cwd, check=False).returncode:
        raise Refused(label)


def land(branch: str, lane: Path, reason_file: Path | None, push: bool,
         deployed: str | None = None) -> None:
    if not (lane / ".git").exists():
        url = subprocess.run(["git", "remote", "get-url", "origin"], cwd=REPO_ROOT,
                             capture_output=True, text=True, check=True).stdout.strip()
        step(["git", "clone", "-q", url, str(lane)], lane.parent, "clone")
    step(["git", "fetch", "-q", "origin"], lane, "fetch")
    step(["git", "checkout", "-q", "-B", "main", "origin/main"], lane, "reset main")
    step(["uv", "sync", "--frozen", "--extra", "dev", "-q"], lane, "environment")
    try:
        step(["git", "merge", "-q", "--no-edit", f"origin/{branch}"], lane, f"merge {branch}")
    except Refused:
        subprocess.run(["git", "merge", "--abort"], cwd=lane, check=False)
        raise
    python = str(lane / ".venv/bin/python")
    repin = [python, "-m", "tools.repin", *(["--deployed", deployed] if deployed else [])]
    check = subprocess.run([*repin, "--check"], cwd=lane, check=False).returncode
    if check == 2:
        if reason_file is None:
            raise Refused("a registration revision is needed: rerun with --reason-file")
        step([*repin, "--reason-file", str(reason_file.resolve())], lane, "re-pin")
    elif check:
        raise Refused("repin --check")
    step([python, "-m", "tools.affected_tests", "--run"], lane, "fast tier")
    step([python, "-m", "pytest", "-q", "-W", "error", "-n", "8"], lane, "full suite")
    if push:
        step(["git", "push", "-q", "origin", "main"], lane, "push main")
        print(f"landed {branch}; the deployer picks main up once CI is green")
    else:
        print(f"{branch} is merged and verified in {lane}; push with `git push origin main`")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("branch")
    parser.add_argument("--lane", type=Path, default=DEFAULT_LANE)
    parser.add_argument("--reason-file", type=Path)
    parser.add_argument("--deployed", help="passed to tools.repin (default: its own)")
    parser.add_argument("--push", action="store_true", help="push main when every step passed")
    args = parser.parse_args(argv)
    try:
        land(args.branch, args.lane.expanduser().resolve(), args.reason_file, args.push,
             args.deployed)
    except Refused as exc:
        print(f"REFUSED  {exc}")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
