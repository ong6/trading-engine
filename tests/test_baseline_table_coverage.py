"""Every persistent table the code can create in the market store is owned by the baseline.

On a versioned store a first-use ``CREATE TABLE`` is refused with SchemaMigrationRequired, so
a table that a producer, tool or store creates lazily must already exist after migration 0000.
"""
from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

from engine import schema_migrations

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("engine", "sim", "server", "tools")
EXTRA_FILES = ("farm/experiment.py", "farm/experiment_runner.py")
# Files whose CREATE TABLE statements target a database other than the market store.
SEPARATE_DATABASES = {
    "engine/free_sources.py": "store/pit/free-sources.duckdb",
    "engine/free_sec.py": "store/pit/free-sources.duckdb (free_sources.default_database)",
    "engine/free_sec_bulk.py": "store/pit/sec-bulk.duckdb",
    "engine/free_massive_minute.py": "store/pit/massive-minute.duckdb",
    "engine/free_massive_options.py": "store/pit/options.duckdb",
    "engine/daily_opportunities.py": "an in-memory scratch connection",
    "tools/ops_digest.py": "the ops SQLite database",
}
LEDGER = {"engine/schema_migrations.py": "schema_migrations"}
_CREATE = re.compile(
    r"\bCREATE\s+(?:OR\s+REPLACE\s+)?(TEMP\s+|TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r"(\{[^}]+\}|\"?[A-Za-z_][\w.]*\"?)",
    re.IGNORECASE,
)


def _rendered(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant)
            else "{" + ast.unparse(part.value) + "}"
            for part in node.values
        )
    return None


def _resolve(module_name: str, expression: str) -> str | None:
    value: object = importlib.import_module(module_name)
    for attribute in expression.split("."):
        value = getattr(value, attribute, None)
        if value is None:
            return None
    return value if isinstance(value, str) else None


def _created_tables() -> list[tuple[str, int, str]]:
    files = [
        path for directory in SCANNED for path in sorted((ROOT / directory).rglob("*.py"))
    ] + [ROOT / relative for relative in EXTRA_FILES]
    found = []
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        if relative in SEPARATE_DATABASES or relative.startswith("engine/migrations/"):
            continue
        tree = ast.parse(path.read_text(), filename=relative)
        skipped = {
            id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.body and isinstance(node.body[0], ast.Expr)
        }
        skipped |= {
            id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr)
            for part in node.values
        }  # f-string fragments are scanned as part of their whole string
        module_name = relative[:-3].replace("/", ".")
        for node in ast.walk(tree):
            if id(node) in skipped:
                continue
            text = _rendered(node)
            if text is None:
                continue
            for match in _CREATE.finditer(text):
                if match.group(1):
                    continue  # session temp table
                name = match.group(2).strip('"')
                if name.startswith("{"):
                    resolved = _resolve(module_name, name[1:-1])
                    name = resolved if resolved is not None else name
                found.append((relative, node.lineno, name.split(".")[-1].lower()))
    return found


def test_every_created_table_is_created_by_the_baseline():
    baseline = schema_migrations.migrations()[0].module
    owned = set(baseline.EXPECTED_TABLES)
    owned_functions = {
        (module_name.replace(".", "/") + ".py", function_name)
        for module_name, function_name in baseline.BOOTSTRAP_CALLS
    }
    found = _created_tables()
    assert len(found) > 100  # the scan really sees the initializers
    unowned = []
    for relative, line, name in found:
        if LEDGER.get(relative) == name or name in owned:
            continue
        if name.startswith("{"):
            # A table named by a loop variable: its enclosing initializer must be bootstrapped.
            tree = ast.parse((ROOT / relative).read_text())
            enclosing = [
                node.name for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef)
                and node.lineno <= line <= (node.end_lineno or node.lineno)
            ]
            if any((relative, function) in owned_functions for function in enclosing):
                continue
        unowned.append(f"{relative}:{line} {name}")
    assert not unowned, (
        "CREATE TABLE outside the migration baseline (add its initializer to "
        "BOOTSTRAP_CALLS or list its separate database): " + ", ".join(unowned)
    )
