"""Live-store paths are named in few, reviewed places (deploy-gate lint).

A DuckDB handle on a live store file, even read-only, blocks its writers. This AST lint
finds every literal that names a live store file, ``store/market.duckdb`` or
``store/pit/<name>.duckdb`` (as one string, an f-string part or a ``/`` join of literals),
and every SQL ``ATTACH`` literal, in the engine, sim, farm, server and tools packages. Each
finding must be listed in ``ALLOWED`` with the reason it is safe; a new one fails until a
reviewer accepts a reason. Readers that only need data use the published snapshot
(``store/snapshots/market-latest.duckdb``) through ``engine.lib.snapshots``.

Strings with whitespace (docstrings, ``--help`` text, messages) are prose, not paths, and are
not findings unless they start with ``ATTACH``.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("engine", "sim", "farm", "server", "tools")
LIVE_STORE = re.compile(r"(?:^|/)store/(?:market\.duckdb|pit/[^/]+\.duckdb)$")
ATTACH = re.compile(r"^\s*ATTACH\b")  # SQL keyword case; prose "Attach ..." is not SQL

# "<path>: <finding>" -> why this use is safe. Grandfathered 2026-10-20; add an entry only
# with a reason a reviewer would accept.
_SECTION = "isolated provider store; this module is its single writer or reads it read-only"
ALLOWED: dict[str, str] = {
    "engine/lib/settings.py: store/market.duckdb": (
        "DEFAULT_DB, the one definition of the live store path; every opener goes through "
        "engine.lib.db.connect"),
    "engine/free_sources.py: store/pit/free-sources.duckdb": (
        "TRADING_ENGINE_FREE_SOURCES_DB default; " + _SECTION),
    "engine/free_massive_options.py: store/pit/options.duckdb": (
        "TRADING_ENGINE_MASSIVE_OPTIONS_DB default; " + _SECTION),
    "engine/free_massive_minute.py: store/pit/massive-minute.duckdb": (
        "massive-minute default; " + _SECTION),
    "tools/free_sec_bulk.py: store/pit/sec-bulk.duckdb": (
        "sec-bulk default; " + _SECTION),
    "tools/free_sec_bulk.py: store/pit/free-sources.duckdb": (
        "reference default for the SEC bulk import, attached READ_ONLY by "
        "engine/free_sec_bulk.py"),
    "tools/free_frozen_archive.py: store/pit/free-sources.duckdb": (
        "reference default for the frozen-archive audit, opened read-only by an operator"),
    "tools/ops_digest.py: store/market.duckdb": (
        "anchor for engine.lib.snapshots.latest_snapshot, which reads the snapshots "
        "directory beside it and never opens the store"),
    "tools/release_manifest.py: store/market.duckdb": (
        "operator CLI default for identifying the schema of a named DuckDB file"),
    "engine/free_sec_bulk.py: ATTACH": (
        "attaches the free-sources reference and the market snapshot READ_ONLY into its "
        "own SEC bulk store"),
    "engine/accounts/sources.py: ATTACH": (
        "attaches the provider point-in-time stores READ_ONLY inside an account fold, "
        "retrying briefly while a writer holds them"),
    "farm/walkforward/runner.py: ATTACH": (
        "attaches its private scratch replay copy READ_ONLY"),
    "tools/backup_database.py: ATTACH": (
        "copies the store READ_ONLY into a private bundle (the backup itself)"),
    "tools/publish_snapshot.py: ATTACH": (
        "attaches the verified backup bundle to publish an immutable snapshot"),
    "tools/free_sec.py: ATTACH": (
        "attaches the free store and a disposable store copy READ_ONLY in memory"),
    "tools/free_source_audit.py: ATTACH": (
        "attaches the free store and a disposable store copy READ_ONLY in memory"),
}


def _join(node: ast.AST) -> str | None:
    """``a / "store" / "market.duckdb"`` -> ``*/store/market.duckdb``; None if not a join."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        left, right = _join(node.left), _join(node.right)
        return f"{left or '*'}/{right or '*'}"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def findings(source: str) -> list[tuple[int, str]]:
    """(line, finding) for each live-store literal and ATTACH literal in ``source``."""
    out = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            match = LIVE_STORE.search(_join(node) or "")
            if match:
                out.add((node.lineno, match.group(0).lstrip("/")))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if ATTACH.match(node.value):
                out.add((node.lineno, "ATTACH"))
            elif not re.search(r"\s", node.value):
                match = LIVE_STORE.search(node.value)
                if match:
                    out.add((node.lineno, match.group(0).lstrip("/")))
    return sorted(out)


def _scan() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for package in SCANNED:
        for path in sorted((REPO_ROOT / package).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(REPO_ROOT).as_posix()
            for line, finding in findings(path.read_text()):
                found.setdefault(f"{relative}: {finding}", []).append(line)
    return found


def test_live_store_literals_are_allowed_with_a_reason():
    found = _scan()
    new = sorted(f"{key} (line {', '.join(map(str, lines))})"
                 for key, lines in found.items() if key not in ALLOWED)
    assert not new, (
        "live store path or ATTACH literal outside ALLOWED; read the published snapshot "
        "(engine.lib.snapshots) or add an entry with a reason:\n  " + "\n  ".join(new))


def test_allowed_entries_have_reasons_and_are_still_used():
    found = _scan()
    assert all(len(reason.split()) >= 5 for reason in ALLOWED.values())
    stale = sorted(set(ALLOWED) - set(found))
    assert not stale, f"ALLOWED entries no longer found (remove them): {stale}"


def test_the_lint_sees_each_form():
    source = '\n'.join([
        'from pathlib import Path',
        'A = Path("store/market.duckdb")',
        'B = ROOT / "store" / "pit" / "minute.duckdb"',
        'C = Path.home() / "trading-engine/store/pit/x.duckdb"',
        'D = f"{home}/trading-engine/store/market.duckdb"',
        'con.execute(f"ATTACH \'{path}\' AS other (READ_ONLY)")',
        'E = ROOT / "store" / "snapshots" / "market-latest.duckdb"',
        'F = Path(directory) / "market.duckdb"',
        'help_text = "DuckDB path (default store/market.duckdb)"',
    ])
    assert findings(source) == [
        (2, "store/market.duckdb"), (3, "store/pit/minute.duckdb"),
        (4, "store/pit/x.duckdb"), (5, "store/market.duckdb"), (6, "ATTACH"),
    ]
