"""Every table, column and index the code can create in the market store is in the baseline.

On a versioned store a first-use ``CREATE TABLE``, ``ALTER TABLE … ADD COLUMN`` or
``CREATE INDEX`` is refused with SchemaMigrationRequired, so whatever a producer, tool or store
creates lazily must already exist after migration 0000 (or a later migration).

Known bypasses (accepted residual risk; the runtime guard in engine/lib/db.py still refuses
these on a versioned store, and publication/backup re-verify the exact catalog):
- DDL assembled at run time from values this static scan cannot resolve (a loop variable is
  accepted only inside an initializer listed in BOOTSTRAP_CALLS);
- DuckDB relation-API persistence (``to_table``, ``create``, ``insert_into``), which the
  runtime guard refuses on a versioned store rather than this scan detecting it;
- statements against separate databases, listed in SEPARATE_DATABASES with their target;
- ``ALTER`` forms other than ``ADD COLUMN`` and ``ALTER COLUMN … DROP NOT NULL`` (none exist).
"""
from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

from engine import schema_migrations

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ("engine", "sim", "server", "tools", "farm")
EXTRA_FILES: tuple[str, ...] = ()
# Files whose CREATE TABLE statements target a database other than the market store.
SEPARATE_DATABASES = {
    "engine/free_sources.py": "store/pit/free-sources.duckdb",
    "engine/free_sec.py": "store/pit/free-sources.duckdb (free_sources.default_database)",
    "engine/free_sec_bulk.py": "store/pit/sec-bulk.duckdb",
    "engine/free_massive_minute.py": "store/pit/massive-minute.duckdb",
    "engine/free_massive_options.py": "store/pit/options.duckdb",
    "engine/daily_opportunities.py": "an in-memory scratch connection",
    "tools/ops_digest.py": "the ops SQLite database",
    "farm/replay/asof.py": "a W4 replay store under the research root (outside the checkout)",
    "farm/replay/clock.py": "a W4 replay store under the research root",
    "farm/replay/executor.py": "a W4 replay store under the research root",
    "farm/replay/lockbox.py": "the W4 lockbox store under the research root",
    "farm/replay/notes.py": "a W4 replay store under the research root",
    "farm/replay/store.py": "a W4 replay store under the research root",
    "farm/backtest/proofs.py": "a scratch copy of the store (proof fixtures)",
    "farm/credit_confirmed_experiment.py": "the experiment's scratch connection",
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


def _statements() -> list[tuple[str, int, str, str]]:
    """Every literal SQL string in market-store code: (file, line, module, text)."""
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
            if text is not None:
                found.append((relative, node.lineno, module_name, text))
    return found


def _created_tables() -> list[tuple[str, int, str]]:
    found = []
    for relative, line, module_name, text in _statements():
        for match in _CREATE.finditer(text):
            if match.group(1):
                continue  # session temp table
            name = match.group(2).strip('"')
            if name.startswith("{"):
                resolved = _resolve(module_name, name[1:-1])
                name = resolved if resolved is not None else name
            found.append((relative, line, name.split(".")[-1].lower()))
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


_ALTER = re.compile(
    r"\bALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?\"?(\w+)\"?\s+(?:ADD\s+(?:COLUMN\s+)?"
    r"(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+|\{[^}]+\})|ALTER\s+(?:COLUMN\s+)?\"?(\w+)\"?"
    r"\s+DROP\s+NOT\s+NULL)",
    re.IGNORECASE,
)
_INDEX = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?\"?(\w+)\"?",
    re.IGNORECASE,
)


def _baseline_columns() -> dict[str, dict[str, bool]]:
    """Column -> nullable for every table of the frozen baseline."""
    import duckdb

    baseline = schema_migrations.migrations()[0].module
    con = duckdb.connect()
    try:
        for sql in baseline.BASELINE_SEQUENCES.values():
            con.execute(sql)
        for sql in baseline.BASELINE_TABLES.values():
            con.execute(sql)
        rows = con.execute(
            "SELECT table_name, column_name, is_nullable FROM information_schema.columns"
        ).fetchall()
    finally:
        con.close()
    columns: dict[str, dict[str, bool]] = {}
    for table, column, nullable in rows:
        columns.setdefault(table, {})[column.lower()] = nullable == "YES"
    return columns


def test_every_runtime_column_and_index_exists_in_the_baseline():
    baseline = schema_migrations.migrations()[0].module
    columns = _baseline_columns()
    alters = indexes = 0
    missing = []
    for relative, line, _module, text in _statements():
        for match in _ALTER.finditer(text):
            alters += 1
            table, added, relaxed = (value and value.lower() for value in match.groups())
            if table not in columns:
                missing.append(f"{relative}:{line} ALTER of unknown table {table}")
            elif added is not None and added.startswith("{"):
                continue  # a loop over literal (column, type) pairs; checked below by value
            elif added is not None and added not in columns[table]:
                missing.append(f"{relative}:{line} {table}.{added}")
            elif relaxed is not None and not columns[table].get(relaxed, False):
                missing.append(f"{relative}:{line} {table}.{relaxed} nullable")
        for match in _INDEX.finditer(text):
            indexes += 1
            if match.group(1).lower() not in baseline.BASELINE_INDEXES:
                missing.append(f"{relative}:{line} index {match.group(1)}")
    assert alters > 20 and indexes >= 3  # the scan really sees the runtime DDL
    assert not missing, (
        "runtime DDL outside the migration baseline (add a migration): " + ", ".join(missing)
    )


def test_looped_forward_columns_exist_in_the_baseline():
    columns = _baseline_columns()["experiment_results"]
    assert {"trade_date", "gross_ret", "net_ret"} <= set(columns)
