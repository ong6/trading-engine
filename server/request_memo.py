"""Request-scoped reuse of identical reads and pure parses in slow status read models.

Status projections re-validate retained evidence. They issue the same SELECT with the
same parameters many times (one calendar or table-existence probe per label) and parse
the same stored provider body once per observation that cites it. Inside ``scope()``:

- ``connection(con)`` returns a proxy whose identical SELECTs, with identical
  parameters, are answered from an earlier answer. Only pure reads are reused: a
  SELECT/WITH without data-changing or session keywords and without volatile functions.
  Any other statement, and any other call through the proxy (``executemany``,
  ``register``, ...), clears the reuse. A result is kept only up to ``MAX_KEPT_ROWS``
  rows, so large one-off reads are not held, and rows holding lists or maps are handed
  out as fresh copies. The read models hold one read-only
  connection for the whole projection, and DuckDB's file lock keeps every writer out
  while it is open, so a repeated read cannot differ.
- ``reuse(namespace, key, compute)`` returns a pure parse result computed once per key.
  A raising computation is never kept, so a failure is raised again every time.

Nothing is kept between requests; outside ``scope()`` both helpers compute directly.
"""

from __future__ import annotations

import copy
import re
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator, TypeVar

T = TypeVar("T")
_MEMO: ContextVar[dict | None] = ContextVar("status_request_memo", default=None)
_READ = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_VOLATILE = re.compile(
    r"\b(random|nextval|currval|uuid|gen_random_uuid|now|current_timestamp|current_date|"
    r"current_time|get_current_timestamp|setseed|today)\b",
    re.IGNORECASE,
)
# A WITH can carry INSERT/UPDATE/DELETE; anything naming a write or session change is not
# a pure read (an identifier that merely looks like one only costs the reuse).
_NOT_PURE = re.compile(
    r"\b(insert|update|delete|merge|upsert|copy|create|drop|alter|attach|detach|pragma|set|"
    r"reset|call|export|import|install|load|vacuum|checkpoint|truncate|begin|commit|"
    r"rollback|use)\b",
    re.IGNORECASE,
)
MAX_KEPT_ROWS = 10_000
_MISSING = object()


@contextmanager
def scope() -> Iterator[None]:
    """Reuse identical reads and parses until the block exits (nested scopes share one)."""
    if _MEMO.get() is not None:
        yield
        return
    token = _MEMO.set({})
    try:
        yield
    finally:
        _MEMO.reset(token)


def reuse(namespace: str, key: object, compute: Callable[[], T]) -> T:
    memo = _MEMO.get()
    if memo is None:
        return compute()
    slot = (namespace, key)
    value = memo.get(slot, _MISSING)
    if value is _MISSING:
        value = compute()
        memo[slot] = value
    return value


def _frozen(value: object) -> object:
    if isinstance(value, (list, tuple)):
        return (type(value).__name__, tuple(_frozen(item) for item in value))
    if isinstance(value, dict):
        return ("dict", tuple(sorted((repr(k), _frozen(v)) for k, v in value.items())))
    hash(value)
    return (type(value).__name__, value)


def _pure_read(sql: object) -> bool:
    return (isinstance(sql, str) and bool(_READ.match(sql)) and not _VOLATILE.search(sql)
            and not _NOT_PURE.search(sql))


def _mutable(rows: list) -> bool:
    return any(isinstance(cell, (list, dict, set, bytearray)) for row in rows for cell in row)


class _Result:
    """One statement's rows: replayed from the memo, or read through and then kept."""

    def __init__(self, raw, sql: str, params: tuple, cached: tuple | None,
                 store: Callable[[tuple], None] | None):
        self._raw, self._sql, self._params = raw, sql, params
        self._store = store
        if cached is not None:
            self.description, rows, mutable = cached
            # Lists and maps are handed out fresh so a caller's change never leaks.
            rows = copy.deepcopy(rows) if mutable else rows
            self._rows, self._index, self._live = rows, 0, None
        else:
            self._live = raw.execute(sql, *params)
            self.description = self._live.description
            self._rows, self._index = [], 0

    def _keep(self, rows: list) -> None:
        if self._store is not None and len(rows) <= MAX_KEPT_ROWS:
            mutable = _mutable(rows)
            self._store((self.description, copy.deepcopy(rows) if mutable else rows, mutable))
        self._store = None

    def fetchall(self) -> list:
        if self._live is None:
            rows = list(self._rows[self._index:])
            self._index = len(self._rows)
            return rows
        whole = self._index == 0 and not self._rows
        rows = self._rows[self._index:] + self._live.fetchall()
        if whole:
            self._keep(list(rows))
        self._rows, self._index = [], 0
        self._live = _Exhausted()
        return rows

    def fetchone(self):
        if self._index < len(self._rows):
            row = self._rows[self._index]
            self._index += 1
            return row
        if self._live is None:
            return None
        first_read = not self._rows and self._index == 0
        row = self._live.fetchone()
        if first_read:
            # A result of at most one row is kept whole; a longer one is read through.
            following = None if row is None else self._live.fetchone()
            if following is None:
                self._keep([] if row is None else [row])
                self._rows, self._index = ([] if row is None else [row]), 1 if row else 0
                self._live = _Exhausted()
                return row
            self._rows, self._index = [row, following], 1
            self._store = None
        return row

    def fetchmany(self, size: int = 1) -> list:
        rows = []
        while len(rows) < size:
            row = self.fetchone()
            if row is None:
                break
            rows.append(row)
        return rows

    def __getattr__(self, name: str):
        # Frames, Arrow and the relational API read the statement again, unshared.
        return getattr(self._raw.execute(self._sql, *self._params), name)


class _Exhausted:
    def fetchall(self) -> list:
        return []

    def fetchone(self):
        return None


class _ReusingConnection:
    def __init__(self, raw, memo: dict):
        self._raw, self._memo, self._last = raw, memo, None

    def execute(self, sql: str, *args, **kwargs):
        if kwargs:
            self._clear()
            self._last = self._raw.execute(sql, *args, **kwargs)
            return self._last
        params = args
        key = None
        if _pure_read(sql):
            try:
                key = ("sql", sql, _frozen(params))
            except TypeError:
                key = None
        if key is None:
            # Not a pure read: run it once on the raw connection and hand back its own
            # result, so .df()/.fetchnumpy()/.arrow() never execute it a second time.
            self._clear()
            self._last = self._raw.execute(sql, *params)
            return self._last
        cached = self._memo.get(key)
        store = None if cached is not None else (
            lambda value, key=key: self._memo.__setitem__(key, value))
        self._last = _Result(self._raw, sql, params, cached, store)
        return self._last

    def _clear(self) -> None:
        for slot in [slot for slot in self._memo if slot[0] == "sql"]:
            del self._memo[slot]

    def fetchone(self):
        return self._last.fetchone()

    def fetchall(self):
        return self._last.fetchall()

    def fetchmany(self, size: int = 1):
        return self._last.fetchmany(size)

    @property
    def description(self):
        return self._last.description

    def __getattr__(self, name: str):
        # executemany, register, sql and the rest bypass the memo and may change what a
        # later read sees, so they clear it.
        self._clear()
        return getattr(self._raw, name)


def connection(con):
    """``con`` with identical reads reused while ``scope()`` is active."""
    memo = _MEMO.get()
    if memo is None or isinstance(con, _ReusingConnection):
        return con
    return _ReusingConnection(con, memo)


def underlying(con):
    """The connection a reusing proxy reads through, or ``con`` itself."""
    return con._raw if isinstance(con, _ReusingConnection) else con
