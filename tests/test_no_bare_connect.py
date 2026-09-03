"""Single-writer discipline is structural, not conventional (refactor step 2).

`engine.lib.db.connect(path, read_only=..., wait_s=...)` is the ONLY sanctioned
`duckdb.connect(` on a store path. Every other module must go through it so the
lock-retry window, the read-only flag and the TRADING_ENGINE_DB override live
in one place. This test greps the packages and fails on any stray call.

Deliberately outside the scan:
  tests/    in-memory fixtures (`duckdb.connect()`) and tmp_path stores
  scratch/  gitignored throwaway scripts
  docs/     docs/repro_fill_integer_clamp.py opens ":memory:" — no store path
  ui/, .venv/  not Python of ours
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("engine", "sim", "farm", "server", "agents")
FACTORY = REPO_ROOT / "engine" / "lib" / "db.py"
# Exact-line exceptions with a stated reason. Empty on purpose — add one only
# with a reason a reviewer would accept.
ALLOWED: dict[str, str] = {}

CALL = re.compile(r"duckdb\s*\.\s*connect\s*\(")


def _offenders() -> list[str]:
    out = []
    for pkg in SCANNED:
        for path in sorted((REPO_ROOT / pkg).rglob("*.py")):
            if "__pycache__" in path.parts or path == FACTORY:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                code = line.split("#", 1)[0]
                if CALL.search(code) and rel not in ALLOWED:
                    out.append(f"{rel}:{lineno}: {line.strip()}")
    return out


def test_factory_is_the_only_duckdb_connect():
    assert FACTORY.exists()
    calls = [n for n in ast.walk(ast.parse(FACTORY.read_text()))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "connect" and isinstance(n.func.value, ast.Name)
             and n.func.value.id == "duckdb"]
    assert len(calls) == 1, "engine/lib/db.py must call duckdb.connect exactly once"
    bad = _offenders()
    assert not bad, (
        "bare duckdb.connect( outside engine/lib/db.py — use engine.lib.db.connect("
        "path, read_only=..., wait_s=...):\n  " + "\n  ".join(bad))


def test_scan_actually_covers_the_packages():
    n = sum(1 for pkg in SCANNED for _ in (REPO_ROOT / pkg).rglob("*.py"))
    assert n > 40, f"only {n} files scanned — is the test running from the repo?"
