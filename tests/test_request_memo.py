from __future__ import annotations

import duckdb
import pytest

from server import request_memo


class _Counting:
    def __init__(self, con):
        self.con, self.statements = con, []

    def execute(self, sql, *args):
        self.statements.append(sql)
        return self.con.execute(sql, *args)


@pytest.fixture
def raw():
    con = duckdb.connect()
    con.execute("CREATE TABLE t (k INTEGER, v VARCHAR)")
    con.execute("INSERT INTO t VALUES (1,'a'),(2,'b'),(3,'c')")
    yield _Counting(con)
    con.close()


def test_identical_reads_are_answered_once_inside_a_scope(raw):
    assert request_memo.connection(raw) is raw
    with request_memo.scope():
        con = request_memo.connection(raw)
        assert request_memo.underlying(con) is raw
        first = con.execute("SELECT v FROM t WHERE k = ?", [2]).fetchone()
        again = con.execute("SELECT v FROM t WHERE k = ?", [2]).fetchone()
        other = con.execute("SELECT v FROM t WHERE k = ?", [3]).fetchone()
        rows = con.execute("SELECT k FROM t ORDER BY k").fetchall()
        assert con.execute("SELECT k FROM t ORDER BY k").fetchall() == rows
        con.execute("SELECT k FROM t ORDER BY k")
        assert con.fetchall() == rows
        assert con.execute("SELECT v FROM t WHERE k = ?", [9]).fetchone() is None
        assert con.execute("SELECT v FROM t WHERE k = ?", [9]).fetchone() is None
    assert (first, again, other, rows) == (("b",), ("b",), ("c",), [(1,), (2,), (3,)])
    assert len(raw.statements) == 4


def test_a_write_or_volatile_read_is_never_reused(raw):
    with request_memo.scope():
        con = request_memo.connection(raw)
        assert con.execute("SELECT COUNT(*) FROM t").fetchone() == (3,)
        con.execute("INSERT INTO t VALUES (4,'d')")
        assert con.execute("SELECT COUNT(*) FROM t").fetchone() == (4,)
        con.execute("SELECT random() FROM t").fetchall()
        con.execute("SELECT random() FROM t").fetchall()
    assert len(raw.statements) == 5


def test_a_partly_read_result_is_read_through_and_not_kept(raw):
    with request_memo.scope():
        con = request_memo.connection(raw)
        result = con.execute("SELECT k FROM t ORDER BY k")
        assert result.fetchone() == (1,)
        assert result.fetchall() == [(2,), (3,)]
        assert con.execute("SELECT k FROM t ORDER BY k").fetchmany(2) == [(1,), (2,)]
        assert con.execute("SELECT k FROM t ORDER BY k").fetchall() == [(1,), (2,), (3,)]
        assert con.execute("SELECT k FROM t ORDER BY k").fetchall() == [(1,), (2,), (3,)]
    assert len(raw.statements) == 3


def test_reuse_keeps_values_but_never_failures_and_ends_with_the_scope():
    calls = []

    def compute():
        calls.append(1)
        return len(calls)

    def failing():
        calls.append(1)
        raise ValueError("bad")

    with request_memo.scope():
        assert request_memo.reuse("n", "k", compute) == 1
        assert request_memo.reuse("n", "k", compute) == 1
        for _ in range(2):
            with pytest.raises(ValueError):
                request_memo.reuse("n", "bad", failing)
    assert request_memo.reuse("n", "k", compute) == 4
    assert len(calls) == 4
