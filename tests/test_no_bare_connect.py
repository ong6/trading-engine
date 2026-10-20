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
SCANNED = ("engine", "sim", "farm", "server")  # agents/ archived 2026-09-03
PUBLISHER_SCANNED = (*SCANNED, "tools")
CONNECT_SCANNED = (*SCANNED, "tools")
FACTORY = REPO_ROOT / "engine" / "lib" / "db.py"
# Whole-file exceptions with a stated reason; add one only with a reason a reviewer
# would accept. The tools/ entries were grandfathered when tools/ joined the scan
# (2026-10-20): none of them opens a live store file.
ALLOWED: dict[str, str] = {
    "tools/backup_database.py": (
        "in-memory connection that ATTACHes the store READ_ONLY to copy it, then opens "
        "only the private bundle copy read-only to verify it"),
    "tools/check_invariants.py": (
        "opens a vetted published snapshot read-only; refuses any live store path first"),
    "tools/free_sec.py": "in-memory connection over READ_ONLY attachments of copies",
    "tools/free_source_audit.py": "in-memory connection over READ_ONLY attachments of copies",
    "tools/publish_snapshot.py": (
        "in-memory connection that attaches the verified backup bundle READ_ONLY"),
    "tools/release_manifest.py": (
        "operator CLI reading the schema of a named DuckDB file read-only"),
}
DIRECT_WRITE_ALLOWED = {
    "tools/backup_database.py": (
        "copies into a private verified bundle that is atomically published as one directory"
    ),
}

CALL = re.compile(r"duckdb\s*\.\s*connect\s*\(")


def _offenders(allowed: dict[str, str] = ALLOWED) -> list[str]:
    out = []
    for pkg in CONNECT_SCANNED:
        for path in sorted((REPO_ROOT / pkg).rglob("*.py")):
            if "__pycache__" in path.parts or path == FACTORY:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            for lineno, line in enumerate(path.read_text().splitlines(), 1):
                code = line.split("#", 1)[0]
                if CALL.search(code) and rel not in allowed:
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


def test_allowed_connect_exceptions_are_still_used():
    used = {line.split(":", 1)[0] for line in _offenders(allowed={})}
    stale = sorted(set(ALLOWED) - used)
    assert not stale, f"ALLOWED files no longer call duckdb.connect (remove them): {stale}"


def test_dataframe_registration_is_centralized_in_db_helper():
    offenders = []
    for pkg in SCANNED:
        for path in sorted((REPO_ROOT / pkg).rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr != "register" or not isinstance(node.func.value, ast.Name):
                    continue
                if node.func.value.id != "con" or path == FACTORY:
                    continue
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}")
    assert not offenders, (
        "temporary DataFrame registration outside db.registered_frame: "
        + ", ".join(offenders)
    )


def test_explicit_transactions_are_centralized_in_db_helper():
    statements = {"BEGIN TRANSACTION", "COMMIT", "ROLLBACK"}
    offenders = []
    for pkg in SCANNED:
        for path in sorted((REPO_ROOT / pkg).rglob("*.py")):
            if path == FACTORY:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or node.value not in statements:
                    continue
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{node.lineno}: {node.value}"
                )
    assert not offenders, (
        "explicit transaction control outside db.transaction: " + ", ".join(offenders)
    )


def test_production_path_writes_are_centralized_in_atomic_helpers():
    offenders = []
    for pkg in PUBLISHER_SCANNED:
        for path in sorted((REPO_ROOT / pkg).rglob("*.py")):
            relative = path.relative_to(REPO_ROOT).as_posix()
            if path == FACTORY or relative in DIRECT_WRITE_ALLOWED:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if node.func.attr not in {"write_text", "write_bytes"}:
                    continue
                offenders.append(f"{relative}:{node.lineno}: {node.func.attr}")
    assert not offenders, (
        "direct Path write outside an atomic publisher: " + ", ".join(offenders)
    )
