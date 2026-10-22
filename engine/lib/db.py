"""DuckDB storage layer for the trading engine.

One connection factory (`connect`), one schema initializer, and a price upsert
that rejects impossible observations before promoting them into the cache.

`connect` is THE way to open the store — read-write or read-only — so the
single-writer discipline (§12.7) lives in one function instead of nine
hand-rolled retry loops (refactor step 2, 2026-09-03). tests/test_no_bare_connect.py
fails the suite if `duckdb.connect(` appears anywhere else in the packages.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import duckdb
import pandas as pd

from engine.lib import settings
from engine.lib import snapshots as schema_registry
from engine.lib.data_quality import (
    PRICE_VALIDATOR_VERSION,
    PROVISIONAL_REPLACEMENT_SKIPPED,
    observation_reasons,
    price_bar_sql,
    provisional_open_only_fault,
    split_like_factor,
)
from engine.lib.log import get_logger

log = get_logger("db")

REPO_ROOT = settings.REPO_ROOT
DEFAULT_DB = settings.DEFAULT_DB

# A bar that represents an actual market session for the name. yfinance keeps
# emitting a dead quote — the last close repeated as o=h=l=c with volume 0 —
# for days after a name stops trading (BUILDLOG 2026-08-20c: EA, TALK), and
# those rows are otherwise indistinguishable from real ones. Every consumer
# that picks an "as-of" bar (screen, hist_screen, the stale list in _meta.json,
# the league's stale-mark detector) keys on this predicate, not on MAX(date).
# `volume = 0` alone is not proof of a phantom (thin names have legitimate
# zero-volume days), so a zero-volume bar is excluded as an AS-OF bar but never
# deleted from the series. A bar with a non-positive open, high or low is a
# phantom too, whatever its volume (rev-14: WBD 2026-10-05 open 0, volume 40).
# Column names are bare so it composes into any query whose FROM has `prices`
# in scope.
REAL_BAR_SQL = (
    "volume > 0 AND open > 0 AND high > 0 AND low > 0 "
    "AND NOT (open = high AND high = low AND low = close)"
)
MARKET_DATE_MIN_NAMES = 1_000
MARKET_DATE_MIN_COVERAGE = 0.90
MIGRATION_TABLE = schema_registry.MIGRATION_TABLE
MINIMUM_DATABASE_SCHEMA_ID = schema_registry.MINIMUM_SCHEMA_ID
CURRENT_DATABASE_SCHEMA_ID = schema_registry.CURRENT_SCHEMA_ID


@contextmanager
def registered_frame(con: duckdb.DuckDBPyConnection, name: str, frame: pd.DataFrame):
    """Register a temporary DataFrame view and always release its name."""
    con.register(name, frame)
    try:
        yield
    finally:
        con.unregister(name)


@contextmanager
def transaction(con: duckdb.DuckDBPyConnection, *, commit: bool = True,
                join_existing: bool = False):
    """Commit atomically and leave a borrowed connection reusable on failure.

    Process-level interruptions receive the same cleanup as ordinary errors.
    If rollback itself fails, preserve the original body/commit exception and
    attach the cleanup failure as a diagnostic note.
    """
    if join_existing:
        # DuckDB has no savepoints. An explicit transaction keeps the same ID
        # across statements; autocommit allocates a fresh ID for each one.
        first = con.execute("SELECT current_transaction_id()").fetchone()[0]
        second = con.execute("SELECT current_transaction_id()").fetchone()[0]
        if first == second:
            yield
            return
    con.execute("BEGIN TRANSACTION")
    try:
        yield
        con.execute("COMMIT" if commit else "ROLLBACK")
    except BaseException as exc:
        try:
            con.execute("ROLLBACK")
        except BaseException as rollback_exc:
            exc.add_note(f"transaction rollback also failed: {rollback_exc!r}")
        raise


def latest_real_prices_date(con: duckdb.DuckDBPyConnection) -> date | None:
    """Latest date containing at least one actually traded daily bar."""
    return con.execute(
        f"SELECT MAX(date) FROM prices WHERE {REAL_BAR_SQL}"
    ).fetchone()[0]


def latest_operational_market_date(
    con: duckdb.DuckDBPyConnection,
    *,
    minimum_names: int = MARKET_DATE_MIN_NAMES,
    minimum_coverage: float = MARKET_DATE_MIN_COVERAGE,
) -> date | None:
    """Latest real-bar date broad enough to advance nightly trading state.

    With an initialized liquid universe, a date must cover at least 90% of its
    active names and, for production-sized universes, at least 1,000 names. The
    absolute floor is capped at universe size so small initialized stores can
    still establish a date. Without an initialized active liquid universe,
    return no operational date rather than trusting an arbitrary price row.
    """
    if minimum_names < 1:
        raise ValueError("minimum_names must be positive")
    if not 0 < minimum_coverage <= 1:
        raise ValueError("minimum_coverage must be in (0, 1]")
    has_universe = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'universe'"
    ).fetchone()
    if has_universe is None:
        return None
    active_liquid = int(
        con.execute(
            "SELECT COUNT(*) FROM universe WHERE active = TRUE AND liquid = TRUE"
        ).fetchone()[0]
    )
    if active_liquid == 0:
        return None
    required = min(
        active_liquid,
        max(minimum_names, math.ceil(active_liquid * minimum_coverage)),
    )
    row = con.execute(
        f"SELECT p.date FROM prices p JOIN universe u ON u.ticker = p.ticker "
        f"WHERE u.active = TRUE AND u.liquid = TRUE AND {REAL_BAR_SQL} "
        "GROUP BY p.date HAVING COUNT(DISTINCT p.ticker) >= ? "
        "ORDER BY p.date DESC LIMIT 1",
        [required],
    ).fetchone()
    return None if row is None else row[0]

# Substrings DuckDB uses when the single-writer on-disk lock is contended or the
# file is open elsewhere. The bare "lock" (formerly only in server/db.py) is the
# superset the API relied on to answer 503 rather than 500; the specific
# phrases stay for documentation.
_LOCK_MARKERS = (
    "could not set lock on file",
    "conflicting lock is held",
    "already open",
    "being used",
    "lock",
)
_LOCK_RETRY_S = 5.0
_SCHEMA_CHANGE_AUTHORITY: ContextVar[bool] = ContextVar(
    "schema_change_authority", default=False,
)
_CREATE_OBJECT = re.compile(
    r'^CREATE\s+(?:OR\s+REPLACE\s+)?(TABLE|VIEW|INDEX)\s+(?:IF\s+NOT\s+EXISTS\s+)?'
    r'(?:(?:"?main"?)\.)?"?([A-Za-z_][A-Za-z0-9_]*)"?',
)
_DROP_OBJECT = re.compile(
    r'^DROP\s+(TABLE|VIEW)\s+(?:IF\s+EXISTS\s+)?"?([A-Za-z_][A-Za-z0-9_]*)"?$',
)
_ALTER_ADD = re.compile(
    r'^ALTER\s+TABLE\s+(?:(?:"?main"?)\.)?"?([A-Za-z_][A-Za-z0-9_]*)"?\s+'
    r'ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+"?([A-Za-z_][A-Za-z0-9_]*)"?',
)
_ALTER_NULLABLE = re.compile(
    r'^ALTER\s+TABLE\s+(?:(?:"?main"?)\.)?"?([A-Za-z_][A-Za-z0-9_]*)"?\s+'
    r'ALTER\s+COLUMN\s+"?([A-Za-z_][A-Za-z0-9_]*)"?\s+DROP\s+NOT\s+NULL',
)
_NULL_BACKFILL = re.compile(
    r'^UPDATE\s+"?([A-Za-z_][A-Za-z0-9_]*)"?\s+SET\s+'
    r'"?([A-Za-z_][A-Za-z0-9_]*)"?\s*=.*\s+WHERE\s+\2\s+IS\s+NULL$',
)
_COLD_TABLE_NAMES = frozenset({
    "intraday_prices", "bitemporal_facts", "source_response_receipts",
})
_RELATION_MUTATIONS = frozenset({
    "create", "create_view", "insert", "insert_into", "to_table", "to_view", "update",
})


class DBBusyError(RuntimeError):
    """The DB could not be opened because another process holds a lock.

    Raised by `connect(..., wait_s=0)` callers that must never wait (the API's
    503 path). `connect` itself re-raises DuckDB's own exception after its
    retry window; use `is_lock_error` to classify it.
    """


class SchemaMigrationRequired(RuntimeError):
    """An existing table has a legacy shape that runtime may not upgrade."""


class GuardedRelation:
    """Best-effort guard for relation methods; publication/backup are authoritative."""

    def __init__(self, relation, *, versioned: bool, preflight):
        self._relation = relation
        self._versioned = versioned
        self._preflight = preflight

    def __getattr__(self, name: str):
        attribute = getattr(self._relation, name)
        if (
            name in _RELATION_MUTATIONS
            and self._versioned
            and not _SCHEMA_CHANGE_AUTHORITY.get()
        ):
            def reject(*_args, **_kwargs):
                raise SchemaMigrationRequired(
                    "relation persistence requires an explicit migration"
                )

            return reject
        if not callable(attribute):
            return attribute

        def guarded(*args, **kwargs):
            if name == "query":
                sql_query = args[1] if len(args) > 1 else kwargs.get("sql_query")
                if isinstance(sql_query, str):
                    self._preflight(sql_query)
            result = attribute(*args, **kwargs)
            if isinstance(result, duckdb.DuckDBPyRelation):
                return GuardedRelation(
                    result, versioned=self._versioned, preflight=self._preflight,
                )
            return result

        return guarded


@contextmanager
def schema_change_authority():
    """Permit schema DDL only inside the recovery-gated migration transaction."""
    token = _SCHEMA_CHANGE_AUTHORITY.set(True)
    try:
        yield
    finally:
        _SCHEMA_CHANGE_AUTHORITY.reset(token)


class GuardedConnection:
    """Best-effort runtime guard; publication and backup enforce exact catalog state."""

    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        *,
        versioned: bool,
    ):
        self._connection = connection
        self._versioned = versioned

    def _object_exists(self, kind: str, name: str) -> bool:
        source = {"TABLE": "duckdb_tables()", "VIEW": "duckdb_views()",
                  "INDEX": "duckdb_indexes()"}[kind]
        column = {"TABLE": "table_name", "VIEW": "view_name", "INDEX": "index_name"}[kind]
        return self._connection.execute(
            f"SELECT 1 FROM {source} WHERE {column}=?", [name],
        ).fetchone() is not None

    def _assert_view_definition(self, statement: str, name: str) -> None:
        body = re.split(r"\s+AS\s+", " ".join(statement.strip().split()), maxsplit=1,
                        flags=re.IGNORECASE)
        if len(body) != 2:
            raise SchemaMigrationRequired(f"runtime view definition is invalid: {name}")
        probe = f"__schema_assert_{uuid4().hex}"
        try:
            self._connection.execute(f'CREATE TEMP VIEW "{probe}" AS {body[1]}')
            existing = self._connection.execute(
                "SELECT sql FROM duckdb_views() WHERE view_name=? AND NOT temporary",
                [name],
            ).fetchone()[0]
            proposed = self._connection.execute(
                "SELECT sql FROM duckdb_views() WHERE view_name=? AND temporary",
                [probe],
            ).fetchone()[0]
        finally:
            self._connection.execute(f'DROP VIEW IF EXISTS "{probe}"')
        existing_body = re.split(r"\s+AS\s+", existing, maxsplit=1, flags=re.IGNORECASE)[1]
        proposed_body = re.split(r"\s+AS\s+", proposed, maxsplit=1, flags=re.IGNORECASE)[1]
        if existing_body != proposed_body:
            raise SchemaMigrationRequired(
                f"{name} view definition requires an explicit schema migration"
            )

    def _drops_only_temporary(self, kind: str, name: str) -> bool:
        """An unqualified DROP resolves to the session's temporary object first."""
        function = "duckdb_tables()" if kind == "TABLE" else "duckdb_views()"
        column = "table_name" if kind == "TABLE" else "view_name"
        temporary = self._connection.execute(
            f"SELECT 1 FROM {function} WHERE temporary AND lower({column})=? LIMIT 1", [name],
        ).fetchone()
        return temporary is not None

    def _assert_schema_statement(self, statement: str) -> bool:
        if not self._versioned or _SCHEMA_CHANGE_AUTHORITY.get():
            return False
        normalized = " ".join(statement.strip().rstrip(";").split())
        upper = normalized.upper()
        if " TEMP " in f" {upper} " or upper.startswith("CREATE TEMP"):
            return False
        match = _DROP_OBJECT.match(upper)
        if match and self._drops_only_temporary(match.group(1), match.group(2).lower()):
            return False
        match = _CREATE_OBJECT.match(upper)
        if match:
            kind, name = match.groups()
            if "IF NOT EXISTS" in upper or "OR REPLACE VIEW" in upper:
                if self._object_exists(kind, name.lower()):
                    if "OR REPLACE VIEW" in upper:
                        self._assert_view_definition(statement, name.lower())
                    return True
            raise SchemaMigrationRequired(
                f"runtime schema creation requires an explicit migration: {name.lower()}"
            )
        match = _ALTER_ADD.match(upper)
        if match:
            table, column = (value.lower() for value in match.groups())
            if column in _columns(self._connection, table):
                return True
            raise SchemaMigrationRequired(
                f"{table} requires an explicit schema migration for column: {column}"
            )
        match = _ALTER_NULLABLE.match(upper)
        if match:
            table, column = (value.lower() for value in match.groups())
            nullable = self._connection.execute(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema='main' AND table_name=? AND column_name=?",
                [table, column],
            ).fetchone()
            if nullable == ("YES",):
                return True
            raise SchemaMigrationRequired(
                f"{table} requires an explicit schema migration for column: {column}"
            )
        match = _NULL_BACKFILL.match(upper)
        if match:
            table, column = (value.lower() for value in match.groups())
            pending = self._connection.execute(
                f'SELECT 1 FROM "{table}" WHERE "{column}" IS NULL LIMIT 1'
            ).fetchone()
            if pending is None:
                return True
            raise SchemaMigrationRequired(
                f"{table} requires an explicit schema migration backfill: {column}"
            )
        if re.match(r"^(?:CREATE|ALTER|DROP|COMMENT)\b", upper):
            raise SchemaMigrationRequired("runtime schema DDL requires an explicit migration")
        if upper.startswith(("COPY FROM DATABASE", "IMPORT DATABASE")):
            raise SchemaMigrationRequired("runtime schema copy requires an explicit migration")
        return False

    @staticmethod
    def _statement_tokens(statement: str) -> list[tuple[str, object]]:
        positioned = duckdb.tokenize(statement)
        return [
            (statement[start:end].strip(), kind)
            for (start, kind), (end, _next_kind) in zip(
                positioned, [*positioned[1:], (len(statement), None)], strict=True,
            )
        ]

    @staticmethod
    def _identifier_after(
        tokens: list[tuple[str, object]], start: int,
    ) -> str | None:
        names = []
        for value, kind in tokens[start:]:
            upper = value.upper()
            if not names and upper in {
                "FROM", "IGNORE", "INTO", "ONLY", "OR", "REPLACE", "TABLE",
            }:
                continue
            if kind == duckdb.token_type.identifier:
                names.append(value.strip('"').replace('""', '"').lower())
                continue
            if names and value == ".":
                continue
            break
        return None if not names else names[-1]

    def _assert_cold_statement(self, statement, tokens: list[tuple[str, object]]) -> None:
        if not self._versioned or _SCHEMA_CHANGE_AUTHORITY.get():
            return
        words = [value.upper() for value, _kind in tokens]
        statement_type = statement.type.name
        marker = None
        if statement_type == "DELETE":
            marker = "TRUNCATE" if "TRUNCATE" in words else "DELETE"
        elif statement_type == "UPDATE":
            marker = "UPDATE"
        elif statement_type == "MERGE_INTO":
            marker = "MERGE"
        elif statement_type == "INSERT":
            marker = "INSERT"
        if marker is None:
            return
        marker_index = words.index(marker)
        if marker == "DELETE":
            try:
                marker_index = words.index("FROM", marker_index + 1)
            except ValueError:
                return
        target = self._identifier_after(tokens, marker_index + 1)
        if target not in _COLD_TABLE_NAMES:
            return
        conflict_update = (
            statement_type == "INSERT"
            and (
                "REPLACE" in words[:words.index("INTO")]
                or ("CONFLICT" in words and "UPDATE" in words[words.index("CONFLICT"):])
            )
        )
        if statement_type != "INSERT" or conflict_update:
            raise SchemaMigrationRequired(
                f"cold table is append-only after schema activation: {target}"
            )

    def _preflight_schema_sql(self, statement: str) -> bool:
        statements = self._connection.extract_statements(statement)
        assertions = []
        for item in statements:
            tokens = self._statement_tokens(item.query)
            self._assert_cold_statement(item, tokens)
            assertions.append(self._assert_schema_statement(item.query))
        if len(statements) > 1 and any(assertions):
            raise SchemaMigrationRequired(
                "multi-statement runtime schema SQL requires an explicit migration"
            )
        return bool(assertions and assertions[0])

    def execute(self, statement: str, parameters=None):
        if self._preflight_schema_sql(statement):
            self._connection.execute("SELECT NULL WHERE FALSE")
        elif parameters is None:
            self._connection.execute(statement)
        else:
            self._connection.execute(statement, parameters)
        return self

    def executemany(self, statement: str, parameters):
        if self._preflight_schema_sql(statement):
            self._connection.execute("SELECT NULL WHERE FALSE")
        else:
            self._connection.executemany(statement, parameters)
        return self

    def sql(self, query: str, *args, **kwargs):
        if self._preflight_schema_sql(query):
            relation = self._connection.sql("SELECT NULL WHERE FALSE")
        else:
            relation = self._connection.sql(query, *args, **kwargs)
        return GuardedRelation(
            relation, versioned=self._versioned, preflight=self._preflight_schema_sql,
        )

    def query(self, query: str, *args, **kwargs):
        if self._preflight_schema_sql(query):
            relation = self._connection.query("SELECT NULL WHERE FALSE")
        else:
            relation = self._connection.query(query, *args, **kwargs)
        return GuardedRelation(
            relation, versioned=self._versioned, preflight=self._preflight_schema_sql,
        )

    def from_query(self, query: str, *args, **kwargs):
        return self.sql(query, *args, **kwargs)

    def table(self, table_name: str):
        return GuardedRelation(
            self._connection.table(table_name), versioned=self._versioned,
            preflight=self._preflight_schema_sql,
        )

    def view(self, view_name: str):
        return GuardedRelation(
            self._connection.view(view_name), versioned=self._versioned,
            preflight=self._preflight_schema_sql,
        )

    def duplicate(self):
        return GuardedConnection(
            self._connection.duplicate(), versioned=self._versioned,
        )

    def cursor(self):
        return GuardedConnection(self._connection.cursor(), versioned=self._versioned)

    def append(self, table_name: str, *args, **kwargs):
        if self._versioned and table_name.rsplit(".", 1)[-1] in _COLD_TABLE_NAMES:
            raise SchemaMigrationRequired(
                f"cold table is append-only through registered writers: {table_name}"
            )
        return self._connection.append(table_name, *args, **kwargs)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __getattr__(self, name: str):
        # DuckDB adds relation factories over time. This proxy is ergonomic
        # defense only; publish/backup revalidate the live catalog, and publish
        # separately proves the append-only cold prefix.
        return getattr(self._connection, name)


def is_lock_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _LOCK_MARKERS)


_is_lock_error = is_lock_error  # back-compat alias


def connect(path: str | Path | None = None, *,
            read_only: bool = False,
            wait_s: float | None = None) -> duckdb.DuckDBPyConnection:
    """Open the store. The ONLY sanctioned `duckdb.connect` on a store path.

    path       None -> settings.DEFAULT_DB (honours TRADING_ENGINE_DB).
    read_only  False opens the single writer (creating parent dirs); True opens
               a reader, which still needs the writer lock to be free.
    wait_s     Lock-retry window when another process holds the lock:
                 None  -> TRADING_ENGINE_LOCK_WAIT_S (default 60s);
                 0     -> exactly one attempt, no retry (callers that must fail
                          fast, e.g. the API mapping contention to HTTP 503);
                 >0    -> max(env window, wait_s): an explicit value raises the
                          floor for callers that KNOW they may race a long writer
                          (the queue drain reacquiring the store after a parallel
                          batch can land inside a nightly's ~4-minute collect).
    After the window the original DuckDB exception is re-raised unchanged.
    """
    path = Path(path) if path is not None else settings.DEFAULT_DB
    # Producers (engine/, farm/, sim/, tools/ and the server runners) always read the primary:
    # only the API's request paths (server/db.py) pin published generations.
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)

    if wait_s is None:
        wait_s = settings.lock_wait_s()
    elif wait_s > 0:
        wait_s = max(settings.lock_wait_s(), float(wait_s))
    # ceil so the window is at least covered: 60s/5s -> 12 tries, 6s/5s -> 2.
    tries = max(1, math.ceil(wait_s / _LOCK_RETRY_S)) if wait_s > 0 else 1
    for attempt in range(1, tries + 1):
        try:
            connection = duckdb.connect(str(path), read_only=read_only)
            # Naive TIMESTAMP columns hold UTC: a timezone-aware value (fetch stamps)
            # must not be cast through the host's local zone on a non-UTC host.
            connection.execute("SET TimeZone='UTC'")
            versioned = connection.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='main' AND table_name=?", [MIGRATION_TABLE],
            ).fetchone() is not None
            if versioned and not read_only and not _SCHEMA_CHANGE_AUTHORITY.get():
                try:
                    schema_registry.require_compatible_schema(connection)
                except schema_registry.SchemaIdentityError:
                    connection.close()
                    raise
            return GuardedConnection(connection, versioned=versioned)
        except Exception as exc:  # duckdb.IOException et al.
            if isinstance(exc, schema_registry.SchemaIdentityError):
                raise SchemaMigrationRequired(str(exc)) from exc
            if not is_lock_error(exc) or attempt >= tries:
                raise
            log.info(f"[db] store locked (attempt {attempt}/{tries}) — "
                  f"retrying in {_LOCK_RETRY_S:.0f}s")
            time.sleep(_LOCK_RETRY_S)
    raise AssertionError("unreachable")  # pragma: no cover


def _require_columns(
    con: duckdb.DuckDBPyConnection, table: str, required: frozenset[str],
) -> None:
    columns = _columns(con, table)
    missing = sorted(required - columns)
    if missing:
        raise SchemaMigrationRequired(
            f"{table} requires an explicit schema migration for columns: "
            + ", ".join(missing)
        )


def _columns(con: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {
        row[0]
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='main' AND table_name=?", [table],
        ).fetchall()
    }


def _table_exists(con: duckdb.DuckDBPyConnection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='main' AND table_name=?",
        [table],
    ).fetchone() is not None


def database_catalog(con: duckdb.DuckDBPyConnection) -> dict:
    """Stable operational catalog identity, excluding its migration ledger."""
    return schema_registry.catalog(con)


def database_catalog_sha256(con: duckdb.DuckDBPyConnection) -> str:
    return schema_registry.catalog_sha256(con)


def recorded_schema_id(con: duckdb.DuckDBPyConnection) -> int | None:
    try:
        return schema_registry.recorded_schema_id(con)
    except schema_registry.SchemaIdentityError as exc:
        raise SchemaMigrationRequired(str(exc)) from exc


def require_compatible_database_schema(
    con: duckdb.DuckDBPyConnection,
    *,
    minimum: int = MINIMUM_DATABASE_SCHEMA_ID,
    maximum: int = CURRENT_DATABASE_SCHEMA_ID,
) -> dict:
    """Verify the recorded range and current catalog without changing the DB."""
    try:
        return schema_registry.require_compatible_schema(
            con, minimum=minimum, maximum=maximum,
        )
    except schema_registry.SchemaIdentityError as exc:
        raise SchemaMigrationRequired(str(exc)) from exc


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create all tables IF NOT EXISTS. Safe to call on every run."""
    for table, columns in (
        ("prices", frozenset({"first_fetched_at"})),
        ("screen_results", frozenset({"universe_policy"})),
        ("jobs", frozenset({"priority", "mem_mb", "last_error"})),
    ):
        if _table_exists(con, table):
            _require_columns(con, table, columns)
    init_price_rejects_schema(con)
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS prices (
            ticker     VARCHAR NOT NULL,
            date       DATE    NOT NULL,
            open       DOUBLE,
            high       DOUBLE,
            low        DOUBLE,
            close      DOUBLE,
            volume     BIGINT,
            source     VARCHAR DEFAULT 'yfinance',
            fetched_at TIMESTAMP,
            first_fetched_at TIMESTAMP,
            PRIMARY KEY (ticker, date)
        )
        """
    )
    _require_columns(con, "prices", frozenset({"first_fetched_at"}))
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS universe (
            ticker        VARCHAR PRIMARY KEY,
            yf_ticker     VARCHAR,
            name          VARCHAR,
            exchange      VARCHAR,
            etf           BOOLEAN,
            member        VARCHAR,
            added         DATE,
            active        BOOLEAN DEFAULT TRUE,
            liquid        BOOLEAN DEFAULT FALSE,
            backfill_done BOOLEAN DEFAULT FALSE
        )
        """
    )
    # Append-only point-in-time record of the universe as filed each day.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS universe_snapshot (
            snapshot_date DATE,
            ticker        VARCHAR,
            name          VARCHAR,
            exchange      VARCHAR,
            etf           BOOLEAN,
            member        VARCHAR,
            active        BOOLEAN,
            liquid        BOOLEAN,
            PRIMARY KEY (snapshot_date, ticker)
        )
        """
    )
    # Populated by the screener in M1 — created now so the schema is stable.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS screen_results (
            run_date        DATE,
            ticker          VARCHAR,
            close           DOUBLE,
            rs_rank         INTEGER,
            template_score  INTEGER,
            passes_template BOOLEAN,
            dist_50d        DOUBLE,
            dist_200d       DOUBLE,
            off_52w_low     DOUBLE,
            off_52w_high    DOUBLE,
            base_tight      BOOLEAN,
            vol_dryup       BOOLEAN,
            new_today       BOOLEAN,
            universe_policy VARCHAR DEFAULT 'all',
            PRIMARY KEY (run_date, ticker)
        )
        """
    )
    # Minimal job bookkeeping — backfill uses this for progress/resumability.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id         INTEGER PRIMARY KEY,
            kind       VARCHAR,
            params     VARCHAR,
            state      VARCHAR DEFAULT 'queued',
            progress   VARCHAR,
            created_at TIMESTAMP,
            updated_at TIMESTAMP,
            priority   INTEGER DEFAULT 100,
            mem_mb     INTEGER DEFAULT 0,
            last_error VARCHAR,
            timeout_s  INTEGER     -- per-job ceiling; NULL = the kind's default
        )
        """
    )
    _require_columns(
        con, "jobs", frozenset({"priority", "mem_mb", "last_error"})
    )


def init_queue_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Assert the current `jobs` shape and create `intraday_prices` if absent.

    Existing jobs tables are never upgraded during producer startup. Legacy
    shapes must pass through the explicit migration runner first.
    """
    _require_columns(
        con, "jobs", frozenset({"priority", "mem_mb", "last_error"})
    )

    # Intraday archive: append-only, UTC timestamps. The (ticker, ts, interval)
    # primary key + the anti-join insert together guarantee we never update or
    # overwrite a captured bar.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS intraday_prices (
            ticker   VARCHAR   NOT NULL,
            ts       TIMESTAMP NOT NULL,
            interval VARCHAR   NOT NULL,
            open     DOUBLE,
            high     DOUBLE,
            low      DOUBLE,
            close    DOUBLE,
            volume   BIGINT,
            source   VARCHAR DEFAULT 'yfinance',
            as_of    DATE,
            PRIMARY KEY (ticker, ts, interval)
        )
        """
    )


def init_screen_policy_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Stamp every screen row with the UNIVERSE POLICY that produced it.

    WHY a column and not a note in the report: `ew_benchmark` is the yardstick
    every other book is scored against, and it is defined by whatever the screen
    passed that day. If the screen's universe policy can change without leaving
    a trace in the row, two screens built under different policies look
    identical in `screen_results` and every downstream comparison silently mixes
    them. Making the row self-describing is the only place the check cannot be
    forgotten.

    DEFAULT 'all' is deliberate and it is TRUE of the existing rows: every
    screen stored before 2026-08-20 ran with no exclusions, so backfilling them
    as 'all' states a fact rather than guessing one.

    Existing screen tables are never upgraded during producer startup. Legacy
    shapes must pass through the explicit migration runner first.
    """
    _require_columns(con, "screen_results", frozenset({"universe_policy"}))


def init_mining_schema(con: duckdb.DuckDBPyConnection) -> None:
    """M4 §12.2 additions: the append-only, point-in-time `fundamentals`
    (weekly snapshot), `earnings_calendar` (daily), and their per-attempt fetch
    logs.

    Kept SEPARATE from init_schema so the nightly collect path is untouched;
    every object creation is guarded by IF NOT EXISTS, so it is safe to run
    against the live single-writer DB and first-run on the real store just works.

    Both tables are keyed by (ticker, ..., as_of) with as_of = the pull date, so
    a re-run on the same day is a no-op (see insert_fundamentals / insert_earnings
    anti-joins) and a past snapshot is NEVER updated — point-in-time discipline.
    """
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals (
            ticker             VARCHAR NOT NULL,
            as_of              DATE    NOT NULL,
            market_cap         DOUBLE,
            trailing_pe        DOUBLE,
            forward_pe         DOUBLE,
            price_to_book      DOUBLE,
            price_to_sales     DOUBLE,
            enterprise_value   DOUBLE,
            ev_to_ebitda       DOUBLE,
            ev_to_revenue      DOUBLE,
            ebitda             DOUBLE,
            trailing_eps       DOUBLE,
            forward_eps        DOUBLE,
            profit_margins     DOUBLE,
            dividend_yield     DOUBLE,
            beta               DOUBLE,
            shares_outstanding DOUBLE,
            sector             VARCHAR,
            industry           VARCHAR,
            quote_type         VARCHAR,
            currency           VARCHAR,
            source             VARCHAR DEFAULT 'yfinance',
            fetched_at         TIMESTAMP,
            PRIMARY KEY (ticker, as_of)
        )
        """
    )
    # A missing fundamentals row is a gap rather than an empty observation.
    # Preserve every attempt so operators can distinguish an untried ticker
    # from a failed response while failures remain eligible for retry.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS fundamentals_fetch_log (
            ticker       VARCHAR   NOT NULL,
            as_of        DATE      NOT NULL,
            status       VARCHAR   NOT NULL CHECK (status IN ('ok', 'failed')),
            n_fields     INTEGER   NOT NULL,
            source       VARCHAR   DEFAULT 'yfinance',
            attempted_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS fundamentals_fetch_log_resume_idx
        ON fundamentals_fetch_log (as_of, ticker, status)
        """
    )
    # Earnings dates are forward-looking estimates that move; every daily pull is
    # its own as_of-stamped snapshot so a gate lookup uses the LATEST snapshot per
    # ticker. is_estimate = the source returned a date window (not a confirmed day).
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS earnings_calendar (
            ticker        VARCHAR NOT NULL,
            earnings_date DATE    NOT NULL,
            as_of         DATE    NOT NULL,
            is_estimate   BOOLEAN,
            source        VARCHAR DEFAULT 'yfinance',
            fetched_at    TIMESTAMP,
            PRIMARY KEY (ticker, earnings_date, as_of)
        )
        """
    )
    # A calendar row can prove that a ticker returned a date, but the absence of
    # one cannot distinguish a successful empty response from an interrupted or
    # failed request. Preserve every attempt so same-day recovery can skip only
    # completed pulls while retaining failures for retry and diagnosis.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS earnings_fetch_log (
            ticker       VARCHAR   NOT NULL,
            as_of        DATE      NOT NULL,
            status       VARCHAR   NOT NULL CHECK (status IN ('ok', 'empty', 'failed')),
            n_dates      INTEGER   NOT NULL,
            source       VARCHAR   DEFAULT 'yfinance',
            attempted_at TIMESTAMP NOT NULL
        )
        """
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS earnings_fetch_log_resume_idx
        ON earnings_fetch_log (as_of, ticker, status)
        """
    )


def init_signals_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Macro/market-regime signal additions: the append-only, point-in-time
    `macro_signals` table (engine/signals.py writes it, sim/strategies/
    macro_composite.py reads it).

    Kept SEPARATE from init_schema so the nightly collect path is untouched;
    every statement is CREATE TABLE IF NOT EXISTS so it is safe against the live
    single-writer DB and a first run on the real store just works.

    Two dates per row, and the distinction is the whole point:
      * obs_date    — the date the DATA is about (a VIX close, a claims week, a
                      margin-debt month-end).
      * fetch_as_of — the date WE first stored the value. A strategy reading
                      as-of D must gate on BOTH (obs_date <= D AND
                      fetch_as_of <= D), which makes publication lag and
                      backfill-after-the-fact impossible to accidentally
                      look-ahead through.

    DECISION D-MS1 — first-observed value wins, no restatement. Inserts are
    append-only via an anti-join on (series, obs_date): a value that arrives
    REVISED later (ICSA is revised weekly; NFCI and the FINRA margin series get
    restated; CFTC reissues reports) is silently dropped rather than overwriting
    what we first saw. That is the honest real-time series — the number a
    decision made on fetch_as_of actually had in front of it. Revisions are only
    ever accepted as NEW obs_dates. If a fully-revised (non-real-time) history is
    ever wanted it belongs in a separate table, not by rewriting this one.
    """
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS macro_signals (
            series      VARCHAR NOT NULL,   -- e.g. 'dix', 'vix', 'icsa'
            obs_date    DATE    NOT NULL,   -- the data's own date
            value       DOUBLE  NOT NULL,
            fetch_as_of DATE    NOT NULL,   -- when WE first stored it
            PRIMARY KEY (series, obs_date)
        )
        """
    )


def insert_macro_signals(con: duckdb.DuckDBPyConnection,
                         rows: "list[tuple[str, date, float]]",
                         fetch_as_of: date | None = None) -> int:
    """Append-only insert into `macro_signals` via anti-join. Returns rows added.

    `rows` is [(series, obs_date, value)]. fetch_as_of defaults to today (UTC).
    Rows with a None/NaN value or a missing date are dropped — we never store a
    fabricated observation. Existing (series, obs_date) keys are NEVER updated
    (decision D-MS1 above), so a re-run of the same backfill inserts 0 rows.

    `fetch_as_of` may be a single date (the normal case: the run's own date) or a
    per-row callable taking (series, obs_date) and returning a date — used ONLY
    by the opt-in `--pit-lag` reconstruction (decision D-MS2 in engine/signals.py)
    on scratch copies, never by the nightly.
    """
    if not rows:
        return 0
    stamp = fetch_as_of or datetime.now(timezone.utc).date()
    per_row = callable(stamp)

    clean: list[tuple[str, date, float, date]] = []
    seen: set[tuple[str, date]] = set()
    for series, obs_date, value in rows:
        if series is None or obs_date is None or value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if math.isnan(value) or math.isinf(value):
            continue
        if isinstance(obs_date, datetime):
            obs_date = obs_date.date()
        key = (series, obs_date)
        if key in seen:      # guard the PK against dupes inside one batch
            continue
        seen.add(key)
        clean.append((series, obs_date, value,
                      stamp(series, obs_date) if per_row else stamp))
    if not clean:
        return 0

    df = pd.DataFrame(clean, columns=["series", "obs_date", "value", "fetch_as_of"])
    before = con.execute("SELECT COUNT(*) FROM macro_signals").fetchone()[0]
    with registered_frame(con, "_incoming_signals", df):
        con.execute(
            """
            INSERT INTO macro_signals (series, obs_date, value, fetch_as_of)
            SELECT i.series, i.obs_date, i.value, i.fetch_as_of
            FROM _incoming_signals i
            LEFT JOIN macro_signals m
                   ON m.series = i.series AND m.obs_date = i.obs_date
            WHERE m.series IS NULL
            """
        )
    after = con.execute("SELECT COUNT(*) FROM macro_signals").fetchone()[0]
    return after - before


def init_actions_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Corporate-actions additions: `corporate_actions` (the point-in-time record
    of splits + dividends as reported by the source), `split_adjustments` (the
    reconciliation watermark — one row per split we have DECIDED about, so a
    restatement is never applied twice) and `actions_fetch_log` (per-name pull
    bookkeeping, the backfill's resume set).

    Kept SEPARATE from init_schema so the nightly collect path is untouched; every
    statement is CREATE TABLE IF NOT EXISTS so it is safe against the live store.

    `corporate_actions` is append-only in spirit: INSERT OR REPLACE on the PK is a
    same-value idempotent re-fetch, never a rewrite of history with new meaning.
    """
    if _table_exists(con, "actions_fetch_log"):
        _require_columns(
            con, "actions_fetch_log", frozenset({"source", "attempted_at"})
        )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS corporate_actions (
            ticker     VARCHAR NOT NULL,
            ex_date    DATE    NOT NULL,
            kind       VARCHAR NOT NULL,   -- 'split' | 'dividend'
            value      DOUBLE  NOT NULL,   -- split: ratio new/old; dividend: $/share
            source     VARCHAR DEFAULT 'yfinance',
            fetched_at TIMESTAMP,
            PRIMARY KEY (ticker, ex_date, kind)
        )
        """
    )
    # The reconciliation watermark. One row per (ticker, ex_date) split the
    # reconciler has ADJUDICATED, whatever the verdict:
    #   applied           - the stored series showed the pre-split scale, we restated
    #   noop_restated     - the stored series already matched the post-split scale
    #                       (the normal case for history the July backfill pulled)
    #   skipped_sanity    - observed move disagrees with BOTH hypotheses -> never guess
    #   skipped_ambiguous - ratio too close to 1 to tell the cases apart
    #   skipped_no_bars   - not enough stored bars around ex_date to decide
    # Presence of a row is what makes reconciliation idempotent: a split is only
    # ever considered once.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS split_adjustments (
            ticker        VARCHAR NOT NULL,
            ex_date       DATE    NOT NULL,
            ratio         DOUBLE,
            outcome       VARCHAR,
            observed      DOUBLE,   -- the stored one-session close ratio at the break
            break_date    DATE,     -- session where the stored scale actually changes
            rows_restated BIGINT,
            applied_at    TIMESTAMP,
            PRIMARY KEY (ticker, ex_date)
        )
        """
    )
    # Per-name pull bookkeeping so a killed backfill resumes where it stopped.
    # Preserve every attempt: completed `ok`/`empty` rows are resume evidence,
    # while `failed` rows remain eligible for a later retry.
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS actions_fetch_log (
            ticker      VARCHAR   NOT NULL,
            fetched_on  DATE      NOT NULL,
            n_splits    INTEGER   NOT NULL,
            n_dividends INTEGER   NOT NULL,
            status      VARCHAR   NOT NULL CHECK (status IN ('ok', 'empty', 'failed')),
            source      VARCHAR   DEFAULT 'yfinance',
            -- NULL only on rows logged before the attempt stamp existed (before
            -- 2026-09-07); writers always stamp it and readers order NULLS LAST.
            attempted_at TIMESTAMP
        )
        """
    )
    _require_columns(
        con, "actions_fetch_log", frozenset({"source", "attempted_at"})
    )
    con.execute(
        """
        CREATE INDEX IF NOT EXISTS actions_fetch_log_resume_idx
        ON actions_fetch_log (fetched_on, ticker, status)
        """
    )


def upsert_actions(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """INSERT OR REPLACE corporate-action rows.

    df columns: ticker, ex_date, kind, value. Rows with a NaN/None value, a NaT
    ex_date or a non-positive value are dropped — a split ratio of 0 or a NaN
    dividend is not a fact, and we never store a fabricated action. Returns the
    number of rows written.
    """
    cols = ["ticker", "ex_date", "kind", "value"]
    if df is None or df.empty:
        return 0
    df = df[cols].copy()
    df = df.dropna(subset=["ex_date", "value"])
    df = df[df["value"] > 0]
    df = df.drop_duplicates(subset=["ticker", "ex_date", "kind"])
    if df.empty:
        return 0

    df["source"] = "yfinance"
    df["fetched_at"] = datetime.now(timezone.utc)

    with registered_frame(con, "_incoming_actions", df):
        con.execute(
            """
            INSERT OR REPLACE INTO corporate_actions
                (ticker, ex_date, kind, value, source, fetched_at)
            SELECT ticker, ex_date, kind, value, source, fetched_at
            FROM _incoming_actions
            """
        )
    return len(df)


def insert_actions_fetch_log(
    con: duckdb.DuckDBPyConnection,
    rows: list[dict],
    fetched_on: date | None = None,
) -> int:
    """Append validated per-ticker action-fetch outcomes, retaining retries."""
    if not rows:
        return 0
    fetched_on = fetched_on or datetime.now(timezone.utc).date()
    attempted_at = datetime.now(timezone.utc)
    values = []
    for row in rows:
        status = row.get("status")
        n_splits = int(row.get("n_splits", 0))
        n_dividends = int(row.get("n_dividends", 0))
        if status not in {"ok", "empty", "failed"}:
            raise ValueError(f"invalid actions fetch status: {status!r}")
        if n_splits < 0 or n_dividends < 0:
            raise ValueError("action fetch counts must be non-negative")
        if status in {"empty", "failed"} and (n_splits or n_dividends):
            raise ValueError("inconsistent actions fetch outcome")
        if status == "ok" and not (n_splits or n_dividends):
            raise ValueError("inconsistent actions fetch outcome")
        values.append(
            [row["ticker"], fetched_on, n_splits, n_dividends, status,
             row.get("source", "yfinance"), attempted_at]
        )
    con.executemany(
        """
        INSERT INTO actions_fetch_log
            (ticker, fetched_on, n_splits, n_dividends, status, source, attempted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return len(values)


# Columns the fundamentals miner supplies (order-independent; as_of/source/
# fetched_at are stamped by insert_fundamentals). Kept next to the schema so the
# two never drift.
_FUNDAMENTAL_COLS = [
    "ticker", "market_cap", "trailing_pe", "forward_pe", "price_to_book",
    "price_to_sales", "enterprise_value", "ev_to_ebitda", "ev_to_revenue",
    "ebitda", "trailing_eps", "forward_eps", "profit_margins", "dividend_yield",
    "beta", "shares_outstanding", "sector", "industry", "quote_type", "currency",
]


def insert_fundamentals(con: duckdb.DuckDBPyConnection, df: pd.DataFrame,
                        as_of: date | None = None) -> int:
    """Append-only, point-in-time insert into `fundamentals` via anti-join.

    df carries one row per ticker with any subset of _FUNDAMENTAL_COLS present;
    missing columns are stored as NULL (never fabricated). Only (ticker, as_of)
    keys not already stored are inserted — an existing snapshot is NEVER updated.
    as_of defaults to today (UTC). Returns rows inserted.
    """
    if df is None or df.empty:
        return 0
    as_of = as_of or datetime.now(timezone.utc).date()

    df = df.copy()
    for col in _FUNDAMENTAL_COLS:
        if col not in df.columns:
            df[col] = None
    df = df[_FUNDAMENTAL_COLS]
    df = df.drop_duplicates(subset=["ticker"])
    if df.empty:
        return 0

    df["as_of"] = as_of
    df["source"] = "yfinance"
    df["fetched_at"] = datetime.now(timezone.utc)

    insert_cols = _FUNDAMENTAL_COLS + ["as_of", "source", "fetched_at"]
    before = con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
    select_list = ", ".join(f"i.{c}" for c in insert_cols)
    with registered_frame(con, "_incoming_fund", df):
        con.execute(
            f"""
            INSERT INTO fundamentals ({', '.join(insert_cols)})
            SELECT {select_list}
            FROM _incoming_fund i
            LEFT JOIN fundamentals f
                   ON f.ticker = i.ticker AND f.as_of = i.as_of
            WHERE f.ticker IS NULL
            """
        )
    after = con.execute("SELECT COUNT(*) FROM fundamentals").fetchone()[0]
    return after - before


def insert_fundamentals_fetch_log(
    con: duckdb.DuckDBPyConnection,
    rows: list[dict],
    as_of: date | None = None,
) -> int:
    """Append per-ticker fundamentals outcomes without erasing retries.

    `ok` accompanies a committed snapshot row. `failed` covers transport errors
    and unusable responses; those attempts remain visible and retryable.
    """
    if not rows:
        return 0
    as_of = as_of or datetime.now(timezone.utc).date()
    values = []
    for row in rows:
        status = row.get("status")
        if status not in {"ok", "failed"}:
            raise ValueError(f"invalid fundamentals fetch status: {status!r}")
        n_fields = int(row.get("n_fields", 0))
        if n_fields < 0 or (status == "ok") != (n_fields > 0):
            raise ValueError(
                "inconsistent fundamentals fetch outcome: "
                f"status={status!r}, n_fields={n_fields}"
            )
        values.append([
            row["ticker"],
            as_of,
            status,
            n_fields,
            "yfinance",
            row.get("attempted_at") or datetime.now(timezone.utc),
        ])
    con.executemany(
        """
        INSERT INTO fundamentals_fetch_log
            (ticker, as_of, status, n_fields, source, attempted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return len(values)


def insert_earnings(con: duckdb.DuckDBPyConnection, df: pd.DataFrame,
                    as_of: date | None = None) -> int:
    """Append-only insert into `earnings_calendar` via anti-join.

    df columns: ticker, earnings_date, is_estimate. as_of defaults to today
    (UTC). Only (ticker, earnings_date, as_of) keys not already stored are
    inserted — existing rows are NEVER touched. Rows with a NaT earnings_date are
    dropped (never store a fabricated date). Returns rows inserted.
    """
    cols = ["ticker", "earnings_date", "is_estimate"]
    if df is None or df.empty:
        return 0
    as_of = as_of or datetime.now(timezone.utc).date()

    df = df[[c for c in cols if c in df.columns]].copy()
    for col in cols:
        if col not in df.columns:
            df[col] = None
    df = df.dropna(subset=["earnings_date"])
    df = df.drop_duplicates(subset=["ticker", "earnings_date"])
    if df.empty:
        return 0

    df["as_of"] = as_of
    df["source"] = "yfinance"
    df["fetched_at"] = datetime.now(timezone.utc)

    before = con.execute("SELECT COUNT(*) FROM earnings_calendar").fetchone()[0]
    with registered_frame(con, "_incoming_earn", df):
        con.execute(
            """
            INSERT INTO earnings_calendar
                (ticker, earnings_date, is_estimate, as_of, source, fetched_at)
            SELECT i.ticker, i.earnings_date, i.is_estimate, i.as_of, i.source, i.fetched_at
            FROM _incoming_earn i
            LEFT JOIN earnings_calendar e
                   ON e.ticker = i.ticker AND e.earnings_date = i.earnings_date
                  AND e.as_of = i.as_of
            WHERE e.ticker IS NULL
            """
        )
    after = con.execute("SELECT COUNT(*) FROM earnings_calendar").fetchone()[0]
    return after - before


def insert_earnings_fetch_log(
    con: duckdb.DuckDBPyConnection,
    rows: list[dict],
    as_of: date | None = None,
) -> int:
    """Append per-ticker earnings fetch outcomes without erasing retries.

    `ok` means at least one usable date was returned, `empty` means the request
    succeeded without a usable date, and `failed` means the request exhausted
    its retry. Failed attempts remain visible and do not count as completed for
    resume purposes.
    """
    if not rows:
        return 0
    as_of = as_of or datetime.now(timezone.utc).date()
    allowed = {"ok", "empty", "failed"}
    values = []
    for row in rows:
        status = row.get("status")
        if status not in allowed:
            raise ValueError(f"invalid earnings fetch status: {status!r}")
        n_dates = int(row.get("n_dates", 0))
        if n_dates < 0 or (status == "ok") != (n_dates > 0):
            raise ValueError(
                f"inconsistent earnings fetch outcome: status={status!r}, n_dates={n_dates}"
            )
        values.append([
            row["ticker"],
            as_of,
            status,
            n_dates,
            "yfinance",
            row.get("attempted_at") or datetime.now(timezone.utc),
        ])
    con.executemany(
        """
        INSERT INTO earnings_fetch_log
            (ticker, as_of, status, n_dates, source, attempted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        values,
    )
    return len(values)


def init_price_rejects_schema(con) -> None:
    """The sole revision-15 append-only evidence table (also archives predecessors).

    Intraday bars re-fetched equal to the stored bar are summarized, one row per
    batch and interval with reason ``intraday_identical_refetch`` and no ticker.
    """
    con.execute("""
        CREATE TABLE IF NOT EXISTS price_observation_rejects (
            observation_id VARCHAR PRIMARY KEY,
            batch_id VARCHAR NOT NULL,
            ticker VARCHAR,
            date DATE,
            ts TIMESTAMP,
            interval VARCHAR NOT NULL,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
            volume VARCHAR,
            source VARCHAR,
            fetched_at TIMESTAMP,
            first_fetched_at TIMESTAMP,
            recorded_at TIMESTAMP NOT NULL,
            reason VARCHAR NOT NULL,
            validator_version VARCHAR NOT NULL,
            observation_json VARCHAR NOT NULL
        )
    """)


def _observation_json(row) -> str:
    # Repr strings distinguish NULL, NaN and infinities without emitting
    # nonstandard JSON, and retain unrepresentable incoming volume/date values.
    return json.dumps({key: (None if value is None else repr(value))
                       for key, value in row.items()}, sort_keys=True)


def observation_rows(cursor) -> list[dict]:
    """Retain SQL NULLs and BIGINTs exactly, without DataFrame float coercion."""
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def append_price_observations(con, rows, *, reason: str, batch_id: str,
                              recorded_at=None) -> None:
    """Append originals, never update or delete evidence; caller owns transaction."""
    if not rows:
        return
    init_price_rejects_schema(con)
    now = recorded_at if recorded_at is not None else datetime.now(timezone.utc)
    values = []
    for row in rows:
        def timestamp(key, row=row):
            try:
                value = pd.Timestamp(row.get(key))
                if pd.isna(value):
                    return None
                return value.tz_convert("UTC").tz_localize(None) if value.tzinfo else value
            except (TypeError, ValueError, OverflowError):
                return None

        def number(key, row=row):
            try:
                return float(row.get(key))
            except (TypeError, ValueError, OverflowError):
                return None

        day = timestamp("date")
        values.append([
            str(uuid4()), batch_id, str(row.get("ticker")),
            None if day is None else day.date(), timestamp("ts"),
            row.get("interval", "1d"), *(number(f) for f in ("open", "high", "low", "close")),
            None if row.get("volume") is None else str(row["volume"]),
            row.get("source", "yfinance"), timestamp("fetched_at"),
            timestamp("first_fetched_at"), now, reason, PRICE_VALIDATOR_VERSION,
            _observation_json(row),
        ])
    insert_values(con, "INSERT INTO price_observation_rejects VALUES", values, width=18)


def insert_values(con, statement: str, rows: list[list], *, width: int,
                  rows_per_statement: int = 500) -> None:
    """Run ``statement`` with multi-row VALUES; ``executemany`` executes once per row."""
    marks = "(" + ",".join("?" * width) + ")"
    for first in range(0, len(rows), rows_per_statement):
        part = rows[first:first + rows_per_statement]
        if any(len(row) != width for row in part):
            raise ValueError("insert row width does not match its statement")
        con.execute(f"{statement} {','.join([marks] * len(part))}",
                    [value for row in part for value in row])


def _comparison_value(value):
    if value is None or value is pd.NA:
        return None
    if isinstance(value, int):
        return value
    try:
        number = float(value)
        return number if math.isfinite(number) else repr(number)
    except (TypeError, ValueError, OverflowError):
        return repr(value)


def _admit_provisional_open_faults(con, rows: list[dict], reasons: list[list[str]]) -> None:
    """Clear the reasons of same-night bars whose only fault is the open's geometry.

    The bar is stored exactly as fetched (no clamping) and stays provisional by its
    `fetched_at`; the next night's settled re-fetch replaces it through the normal
    path. A bar dated before the store's newest session is stale, so it is judged as
    settled and stays rejected. It never displaces a stored bar whose own geometry is
    complete: that newcomer is retained as `provisional_replacement_skipped`, which
    is evidence, not an invalid date.
    """
    has_prices = con.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name='prices'").fetchone()
    latest = con.execute("SELECT MAX(date) FROM prices").fetchone()[0] if has_prices else None
    candidates = [i for i, row in enumerate(rows)
                  if provisional_open_only_fault(row, reasons[i], latest)]
    if not candidates:
        return
    keys = pd.DataFrame({
        "ticker": [str(rows[i]["ticker"]) for i in candidates],
        "date": [pd.Timestamp(rows[i]["date"]).date() for i in candidates],
    })
    complete = set()
    if has_prices:
        with registered_frame(con, "_provisional_keys", keys):
            complete = {(ticker, day) for ticker, day in con.execute(
                "SELECT p.ticker,p.date FROM prices p JOIN _provisional_keys k "
                f"ON p.ticker=k.ticker AND p.date=k.date WHERE {price_bar_sql()}"
            ).fetchall()}
    for i, key in zip(candidates, keys.itertuples(index=False), strict=True):
        reasons[i] = ([PROVISIONAL_REPLACEMENT_SKIPPED]
                      if (key.ticker, key.date) in complete else [])


def _validated_observations(con, df, *, intraday: bool, now, batch_id: str):
    frame = df.copy()
    if "source" not in frame:
        frame["source"] = "yfinance"
    if "fetched_at" not in frame:
        frame["fetched_at"] = now
    rows = frame.to_dict("records")
    reasons = [observation_reasons(row, intraday=intraday) for row in rows]
    if not intraday:
        _admit_provisional_open_faults(con, rows, reasons)
    groups = {}
    for i, row in enumerate(rows):
        try:
            stamp = pd.Timestamp(row.get("ts" if intraday else "date"))
            canonical_time = (stamp.tz_localize("UTC") if stamp.tzinfo is None
                              else stamp.tz_convert("UTC")) if intraday else stamp.date()
        except (TypeError, ValueError, OverflowError):
            canonical_time = str(row.get("ts" if intraday else "date"))
        coordinate = (str(row.get("ticker")), str(canonical_time))
        if intraday:
            coordinate += (str(row.get("interval")),)
        groups.setdefault(coordinate, []).append(i)
    for indexes in groups.values():
        if len(indexes) < 2:
            continue
        tuples = {tuple(_comparison_value(rows[i].get(f))
                        for f in ("open", "high", "low", "close", "volume"))
                  for i in indexes}
        if len(tuples) > 1:
            for i in indexes:
                reasons[i].append("conflicting_duplicate")
        else:
            for i in indexes[1:]:
                reasons[i].append("identical_duplicate")
    for row, invalid in zip(rows, reasons, strict=True):
        if invalid:
            append_price_observations(con, [row], reason=",".join(invalid),
                                      batch_id=batch_id, recorded_at=now)
    df.attrs["rejected_tickers"] = {
        row["ticker"] for row, invalid in zip(rows, reasons, strict=True)
        if invalid and not set(invalid) <= {"identical_duplicate", PROVISIONAL_REPLACEMENT_SKIPPED}
    }
    return frame.iloc[[i for i, r in enumerate(reasons) if not r]].copy()


def _basis_unverified(con, frame) -> set[str]:
    """Check overlap revisions and both edges of each affected daily window."""
    if frame.empty:
        return set()
    with registered_frame(con, "_basis_incoming", frame[["ticker", "date", "close"]]):
        stored = con.execute("""
            WITH bounds AS (SELECT ticker, MIN(date) lo, MAX(date) hi
                            FROM _basis_incoming GROUP BY ticker)
            SELECT p.ticker, p.date, p.close FROM prices p JOIN bounds b USING(ticker)
            WHERE p.date BETWEEN b.lo AND b.hi
               OR p.date = (SELECT MAX(q.date) FROM prices q
                            WHERE q.ticker=b.ticker AND q.date < b.lo)
               OR p.date = (SELECT MIN(q.date) FROM prices q
                            WHERE q.ticker=b.ticker AND q.date > b.hi)
        """).fetchall()
    actions = {}
    if con.execute("SELECT 1 FROM information_schema.tables WHERE table_name='corporate_actions'").fetchone():
        with registered_frame(con, "_basis_names", frame[["ticker"]].drop_duplicates()):
            for ticker, day, ratio in con.execute(
                "SELECT c.ticker,c.ex_date,c.value FROM corporate_actions c "
                "JOIN _basis_names n USING(ticker) WHERE c.kind='split'"
            ).fetchall():
                actions.setdefault(ticker, []).append((day, ratio))
    retained = {}
    for ticker, day, close in stored:
        if close is not None and math.isfinite(close) and close > 0:
            retained.setdefault(ticker, {})[day] = close
    held = set()
    for ticker, incoming in frame.groupby("ticker", sort=False):
        old = retained.get(ticker, {})
        new = {pd.Timestamp(day).date(): float(close)
               for day, close in zip(incoming.date, incoming.close, strict=True)}
        merged = {**old, **new}

        def unexplained(ratio, day, ticker=ticker):
            if split_like_factor(ratio) is None:
                return False
            return not any(abs((ex - day).days) <= 7 and value > 0
                           and (abs(math.log(ratio / value)) <= math.log(1.08)
                                or abs(math.log(ratio * value)) <= math.log(1.08))
                           for ex, value in actions.get(ticker, []))

        if any(day in old and unexplained(close / old[day], day)
               for day, close in new.items()):
            held.add(ticker)
            continue
        ordered = sorted(merged)
        for previous, day in zip(ordered, ordered[1:], strict=False):
            if previous not in new and day not in new:
                continue
            ratio = merged[day] / merged[previous]
            if previous in old and day in old and math.isclose(
                    ratio, old[day] / old[previous], rel_tol=1e-6):
                continue
            if unexplained(ratio, day):
                held.add(ticker)
                break
    return held


def insert_intraday(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Append admissible UTC session bars; rejected originals remain evidence."""
    if df is None or df.empty:
        return 0
    now = datetime.now(timezone.utc)
    batch_id = str(uuid4())
    with transaction(con, join_existing=True):
        init_price_rejects_schema(con)
        frame = _validated_observations(con, df, intraday=True, now=now, batch_id=batch_id)
        if frame.empty:
            return 0
        frame["as_of"] = now.date()
        frame["ts"] = pd.to_datetime(frame["ts"], utc=True).dt.tz_localize(None)
        with registered_frame(con, "_incoming_intraday", frame):
            repeats = observation_rows(con.execute(
                "SELECT i.*, (p.open IS NOT DISTINCT FROM i.open "
                "AND p.high IS NOT DISTINCT FROM i.high AND p.low IS NOT DISTINCT FROM i.low "
                "AND p.close IS NOT DISTINCT FROM i.close "
                "AND p.volume IS NOT DISTINCT FROM i.volume "
                "AND p.source IS NOT DISTINCT FROM i.source) AS _identical_to_stored "
                "FROM _incoming_intraday i JOIN intraday_prices p "
                "ON p.ticker=i.ticker AND p.ts=i.ts AND p.interval=i.interval"
            ))
            identical, changed = [], []
            for row in repeats:
                (identical if row.pop("_identical_to_stored") else changed).append(row)
            append_price_observations(con, changed, reason="intraday_existing_key",
                                      batch_id=batch_id, recorded_at=now)
            _append_identical_refetch_summary(con, identical, batch_id=batch_id,
                                              recorded_at=now)
            return len(con.execute("""
                INSERT INTO intraday_prices
                    (ticker,ts,interval,open,high,low,close,volume,source,as_of)
                SELECT i.ticker,i.ts,i.interval,i.open,i.high,i.low,i.close,
                       i.volume,i.source,i.as_of FROM _incoming_intraday i
                ANTI JOIN intraday_prices p
                ON p.ticker=i.ticker AND p.ts=i.ts AND p.interval=i.interval
                RETURNING ticker
            """).fetchall())


INTRADAY_IDENTICAL_REFETCH = "intraday_identical_refetch"


def _append_identical_refetch_summary(con, rows: list[dict], *, batch_id: str,
                                      recorded_at) -> None:
    """One evidence row per interval for re-fetched bars equal to the stored bar.

    A nightly 7-day 1m and 60-day 5m pull re-fetches about six million stored bars;
    one row each held no information the stored bar does not. A bar that differs
    from the stored one keeps its own ``intraday_existing_key`` row.
    """
    by_interval: dict[str, list[dict]] = {}
    for row in rows:
        by_interval.setdefault(str(row.get("interval")), []).append(row)
    values = []
    for interval, group in sorted(by_interval.items()):
        tickers = sorted({str(row.get("ticker")) for row in group})
        stamps = [pd.Timestamp(row["ts"]) for row in group]
        fetched = [pd.Timestamp(row["fetched_at"]) for row in group
                   if row.get("fetched_at") is not None]
        fetched = [s.tz_convert("UTC").tz_localize(None) if s.tzinfo else s for s in fetched]
        summary = {"bar_count": len(group), "ticker_count": len(tickers),
                   "tickers_sha256": hashlib.sha256(",".join(tickers).encode()).hexdigest(),
                   "first_ts": min(stamps).isoformat(), "last_ts": max(stamps).isoformat(),
                   "first_fetched_at": min(fetched).isoformat() if fetched else None,
                   "last_fetched_at": max(fetched).isoformat() if fetched else None}
        values.append([str(uuid4()), batch_id, None, None, None, interval,
                       None, None, None, None, None, group[0].get("source", "yfinance"),
                       max(fetched) if fetched else None, None, recorded_at,
                       INTRADAY_IDENTICAL_REFETCH, PRICE_VALIDATOR_VERSION,
                       json.dumps(summary, sort_keys=True)])
    insert_values(con, "INSERT INTO price_observation_rejects VALUES", values, width=18)


def upsert_prices(con: duckdb.DuckDBPyConnection, df: pd.DataFrame) -> int:
    """Promote valid coherent daily bars, atomically retaining rejected originals.

    Invalid replacements leave trusted values AND both availability stamps alone.
    The return count covers promoted keys only, never rejected observations.
    """
    if df is None or df.empty:
        return 0
    now = datetime.now(timezone.utc)
    batch_id = str(uuid4())
    with transaction(con, join_existing=True):
        init_price_rejects_schema(con)
        frame = _validated_observations(con, df, intraday=False, now=now, batch_id=batch_id)
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        held = _basis_unverified(con, frame)
        df.attrs["rejected_tickers"].update(held)
        append_price_observations(con, frame[frame.ticker.isin(held)].to_dict("records"),
                                  reason="basis_unverified", batch_id=batch_id, recorded_at=now)
        frame = frame[~frame.ticker.isin(held)]
        if frame.empty:
            return 0
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        frame["first_fetched_at"] = frame["fetched_at"]
        from engine import actions
        actions.record_split_like_rewrites(con, frame)
        with registered_frame(con, "_incoming_prices", frame):
            previous = observation_rows(con.execute(
                "SELECT p.* FROM prices p JOIN _incoming_prices i "
                "ON p.ticker=i.ticker AND p.date=i.date"
            ))
            append_price_observations(con, previous, reason="replacement_predecessor",
                                      batch_id=batch_id, recorded_at=now)
            has_first = con.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_name='prices' "
                "AND column_name='first_fetched_at'"
            ).fetchone()
            availability = (", first_fetched_at" if has_first else "")
            update_availability = """
                ,first_fetched_at=COALESCE(prices.first_fetched_at,prices.fetched_at,
                                          CAST(excluded.first_fetched_at AS TIMESTAMP))
            """ if has_first else ""
            con.execute(f"""
                INSERT INTO prices
                    (ticker,date,open,high,low,close,volume,source,fetched_at{availability})
                SELECT ticker,date,open,high,low,close,volume,source,fetched_at{availability}
                FROM _incoming_prices
                ON CONFLICT(ticker,date) DO UPDATE SET
                    open=excluded.open,high=excluded.high,low=excluded.low,
                    close=excluded.close,volume=excluded.volume,source=excluded.source,
                    fetched_at=excluded.fetched_at{update_availability}
            """)
        return len(frame)


def backfill_first_fetched_at(con: duckdb.DuckDBPyConnection) -> int:
    """Explicitly add/backfill availability for the registered D0 migration."""
    columns = {
        row[0]
        for row in con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='main' AND table_name='prices'"
        ).fetchall()
    }
    if "first_fetched_at" not in columns:
        con.execute("ALTER TABLE prices ADD COLUMN first_fetched_at TIMESTAMP")
    pending = con.execute(
        """SELECT COUNT(*) FROM prices
        WHERE first_fetched_at IS NULL AND fetched_at IS NOT NULL"""
    ).fetchone()[0]
    con.execute(
        """UPDATE prices SET first_fetched_at=fetched_at
        WHERE first_fetched_at IS NULL AND fetched_at IS NOT NULL"""
    )
    return int(pending)
