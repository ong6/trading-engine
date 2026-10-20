#!/usr/bin/env python3
"""Deploy gate: compose the pre-deploy checks against one exact tree and keep a receipt.

``python -m tools.deploy_gate --check WORKTREE`` refuses a checkout with uncommitted or
untracked changes, records ``HEAD^{tree}``, then runs each check with the checkout's own code
(its ``.venv`` interpreter when present, ``PYTHONPATH`` and working directory set to it):

  contract_tests         pytest tests/contracts (provider contracts, runtime env, no secrets)
  schedule_contract      tools.schedule_contract_check --static
  provider_replay        tools.provider_contracts replay --root WORKTREE (offline fixtures)
  provider_env           tools.provider_contracts env-check --root WORKTREE (this host)
  registration_identity  pytest tests/test_registration_identity.py, diffed from --base
  store_path_lint        pytest tests/test_live_store_paths.py tests/test_no_bare_connect.py
  invariants             shadow: the published check_invariants result (``--invariants run``
                         runs ``check_invariants --gate`` on the latest snapshot instead)

A check passes on exit 0. Every check but ``invariants`` blocks; the invariants check is in
shadow, so a regression or a missing result is a warning that never refuses. The tree is
re-read after the checks; if it moved the run cannot vouch for it. The receipt
``<receipts>/<tree-sha>.json`` (atomic) records the tree, HEAD, base, each check's verdict,
exit code, seconds and output tail, and the overall verdict.

The gate never opens a DuckDB file itself. The checks it runs write only private temporary
stores under the gate's own temporary directory (``TMPDIR``); with ``--invariants run``,
check_invariants opens the published snapshot read-only, never a live store.

Exit 0 when every blocking check passes, 2 when the gate refuses, 3 when it cannot check
(not a git checkout, a dirty tree, or the tree moved during the run).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from engine.lib.resources import write_text_atomic

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPTS = Path.home() / ".local/state/trading-engine/deploy-gate"
DEFAULT_ENGINE_ROOT = Path.home() / "trading-engine"
INVARIANTS_RESULT = Path("logs/ops/invariants.json")
STEP_TIMEOUT_S = 1800
TAIL_LINES = 25
CANNOT_CHECK = 3


class CannotCheck(Exception):
    """The worktree is not a clean git checkout the gate can name by tree SHA."""


@dataclass(frozen=True)
class Step:
    name: str
    argv: tuple[str, ...]
    shadow: bool = False


def _git(worktree: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(worktree), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise CannotCheck(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout.strip()


def tree_identity(worktree: Path) -> dict:
    """HEAD, its tree SHA and the clean-tree proof, or CannotCheck."""
    dirty = _git(worktree, "status", "--porcelain", "--untracked-files=normal")
    if dirty:
        listed = ", ".join(line[3:] for line in dirty.splitlines()[:5])
        raise CannotCheck(f"uncommitted or untracked changes: {listed}")
    return {"head_commit": _git(worktree, "rev-parse", "HEAD"),
            "tree_sha": _git(worktree, "rev-parse", "HEAD^{tree}")}


def steps(worktree: Path, python: str, invariants: str, engine_root: Path) -> list[Step]:
    pytest = (python, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-n", "2")
    found = [
        Step("contract_tests", (*pytest, "tests/contracts")),
        Step("schedule_contract", (python, "-m", "tools.schedule_contract_check", "--static")),
        Step("provider_replay", (python, "-m", "tools.provider_contracts", "replay",
                                 "--root", str(worktree), "--python", python)),
        Step("provider_env", (python, "-m", "tools.provider_contracts", "env-check",
                              "--root", str(worktree))),
        Step("registration_identity", (*pytest[:-2], "tests/test_registration_identity.py")),
        Step("store_path_lint", (*pytest[:-2], "tests/test_live_store_paths.py",
                                 "tests/test_no_bare_connect.py")),
    ]
    if invariants == "run":
        found.append(Step("invariants", (python, "-m", "tools.check_invariants", "--snapshot",
                                         "latest", "--engine-root", str(engine_root), "--gate"),
                          shadow=True))
    return found


def _tail(text: str) -> list[str]:
    return text.rstrip("\n").splitlines()[-TAIL_LINES:]


def run_step(step: Step, worktree: Path, env: dict[str, str]) -> dict:
    started = time.monotonic()
    try:
        done = subprocess.run(step.argv, cwd=worktree, env=env, capture_output=True, text=True,
                              timeout=STEP_TIMEOUT_S, stdin=subprocess.DEVNULL)
        code, output = done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired:
        code, output = None, f"timed out after {STEP_TIMEOUT_S}s"
    except OSError as exc:
        code, output = None, f"could not start: {exc}"
    verdict = "pass" if code == 0 else ("warn" if step.shadow else "fail")
    return {"mode": "shadow" if step.shadow else "blocking", "verdict": verdict,
            "exit_code": code, "seconds": round(time.monotonic() - started, 1),
            "command": [Path(step.argv[0]).name, *step.argv[1:]], "tail": _tail(output)}


def published_invariants(engine_root: Path) -> dict:
    """Shadow verdict from the ops digest's published result; reads JSON only."""
    path = engine_root / INVARIANTS_RESULT
    base = {"mode": "shadow", "exit_code": None, "seconds": 0.0,
            "command": ["read", str(INVARIANTS_RESULT)]}
    try:
        result = json.loads(path.read_text())
    except FileNotFoundError:
        return {**base, "verdict": "warn",
                "tail": [f"no published invariants result at {INVARIANTS_RESULT} "
                         "(the hourly digest writes it when the snapshot changes)"]}
    except (OSError, ValueError) as exc:
        return {**base, "verdict": "warn", "tail": [f"unreadable result: {exc}"]}
    status = result.get("status")
    snapshot = result.get("snapshot") or {}
    tail = [f"status {status}; snapshot {snapshot.get('name')} as of {snapshot.get('as_of')}; "
            f"checked {result.get('checked_at') or result.get('started_at')}"]
    return {**base, "verdict": "pass" if status == "pass" else "warn", "tail": tail}


def check(worktree: Path, *, base: str, receipts: Path, engine_root: Path,
          invariants: str = "published", python: str | None = None) -> tuple[int, dict]:
    worktree = worktree.resolve()
    started = datetime.now(UTC)
    before = tree_identity(worktree)
    merge_base = _git(worktree, "merge-base", base, "HEAD")
    venv = worktree / ".venv/bin/python"
    python = python or (str(venv) if venv.exists() else sys.executable)
    results = {}
    with tempfile.TemporaryDirectory(prefix="deploy-gate-") as private:
        env = {**os.environ, "PYTHONPATH": str(worktree), "TMPDIR": private,
               "PYTHONDONTWRITEBYTECODE": "1", "REGISTRATION_BASE_REF": merge_base}
        for step in steps(worktree, python, invariants, engine_root):
            results[step.name] = run_step(step, worktree, env)
            print(f"{results[step.name]['verdict'].upper():<5} {step.name} "
                  f"({results[step.name]['seconds']}s)", flush=True)
    if invariants == "published":
        results["invariants"] = published_invariants(engine_root)
        print(f"{results['invariants']['verdict'].upper():<5} invariants (published)", flush=True)
    after = tree_identity(worktree)
    if after != before:
        raise CannotCheck(f"the tree moved during the check: {before} -> {after}")
    refused = sorted(name for name, item in results.items() if item["verdict"] == "fail")
    receipt = {
        "schema_version": 1, **before,
        "base": {"ref": base, "merge_base": merge_base},
        "worktree": str(worktree), "gate_source": str(REPO_ROOT),
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "verdict": "refuse" if refused else "pass", "refused_by": refused,
        "warnings": sorted(name for name, item in results.items() if item["verdict"] == "warn"),
        "steps": results,
    }
    path = receipts.expanduser() / f"{before['tree_sha']}.json"
    write_text_atomic(path, json.dumps(receipt, indent=1, sort_keys=True) + "\n")
    receipt["receipt_path"] = str(path)
    return (2 if refused else 0), receipt


def _summary(receipt: dict) -> str:
    lines = [f"deploy gate: {receipt['verdict'].upper()} tree {receipt['tree_sha']} "
             f"(HEAD {receipt['head_commit'][:12]}, base {receipt['base']['ref']})"]
    for name, item in receipt["steps"].items():
        if item["verdict"] != "pass":
            lines.append(f"- {item['verdict']} {name} (exit {item['exit_code']}):")
            lines += [f"    {line}" for line in item["tail"][-8:]]
    lines.append(f"receipt: {receipt['receipt_path']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", type=Path, required=True, metavar="WORKTREE")
    parser.add_argument("--base", default="origin/main",
                        help="registration diffs start at the merge base with this revision")
    parser.add_argument("--receipts", type=Path, default=DEFAULT_RECEIPTS)
    parser.add_argument("--engine-root", type=Path, default=DEFAULT_ENGINE_ROOT,
                        help="live checkout whose published invariants result is read")
    parser.add_argument("--invariants", choices=("published", "run"), default="published")
    parser.add_argument("--python", help="interpreter for the checks (default WORKTREE/.venv)")
    parser.add_argument("--json", action="store_true", help="print the receipt as JSON")
    args = parser.parse_args(argv)
    try:
        code, receipt = check(args.check, base=args.base, receipts=args.receipts,
                              engine_root=args.engine_root.expanduser(),
                              invariants=args.invariants, python=args.python)
    except CannotCheck as exc:
        print(f"deploy gate: CANNOT CHECK {args.check}: {exc}")
        return CANNOT_CHECK
    print(json.dumps(receipt, indent=1, sort_keys=True) if args.json else _summary(receipt))
    return code


if __name__ == "__main__":
    sys.exit(main())
