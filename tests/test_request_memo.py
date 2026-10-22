from __future__ import annotations

from datetime import date

import duckdb
import pytest

from server import agent_provider_responses as provider
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


def test_batched_cache_rows_hash_like_the_per_key_lookup():
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE prices (ticker VARCHAR, date DATE, open DOUBLE, high DOUBLE, "
        "low DOUBLE, close DOUBLE, volume BIGINT, source VARCHAR)"
    )
    con.execute(
        "INSERT INTO prices VALUES "
        "('AAA','2026-10-01',1,2,0.5,1.5,10,'yf'),('AAA','2026-10-02',1,2,0.5,1.6,11,'yf'),"
        "('BBB','2026-10-01',3,4,2.5,3.5,12,'yf'),('BBB','2026-10-01',3,4,2.5,3.6,13,'yf')"
    )
    keys = [("AAA", date(2026, 10, 1)), ("AAA", date(2026, 10, 2)),
            ("AAA", date(2026, 10, 3)), ("ZZZ", date(2026, 10, 1))]
    batched = provider._daily_price_cache_rows(con, [*keys, ("BBB", date(2026, 10, 1))])
    for ticker, fact_date in keys:
        arguments = {"dataset": "daily_price", "ticker": ticker, "fact_date": fact_date,
                     "kind": "daily_price", "available_tables": {"prices"}}
        assert provider._cache_value_sha256(con, **arguments) == provider._cache_value_sha256(
            con, **arguments, price_rows=batched)
    ambiguous = {"dataset": "daily_price", "ticker": "BBB", "fact_date": date(2026, 10, 1),
                 "kind": "daily_price", "available_tables": {"prices"}}
    for extra in ({}, {"price_rows": batched}):
        with pytest.raises(provider.ProviderResponseError, match="ambiguous"):
            provider._cache_value_sha256(con, **ambiguous, **extra)
    assert provider._daily_price_cache_rows(con, []) == {}
    con.close()


def test_a_reused_parse_hands_out_independent_copies(monkeypatch):
    parsed = []

    def parse(body, ticker, provider_ticker):
        parsed.append(body)
        return [{"dataset": "daily_price", "value": {"close": 1.0}}]

    monkeypatch.setattr(provider, "_parse_facts", parse)
    with request_memo.scope():
        first = provider._facts(b"{}", "AAA", "AAA")
        first[0]["value"]["close"] = 9.0
        first[0]["dataset"] = "changed"
        second = provider._facts(b"{}", "AAA", "AAA")
    assert second == [{"dataset": "daily_price", "value": {"close": 1.0}}]
    assert len(parsed) == 1


def test_a_with_that_writes_is_executed_every_time(raw):
    raw.con.execute("CREATE TABLE log (k INTEGER)")
    with request_memo.scope():
        con = request_memo.connection(raw)
        for _ in range(3):
            con.execute("WITH s AS (SELECT 1 AS k) INSERT INTO log SELECT k FROM s").fetchall()
    assert raw.con.execute("SELECT COUNT(*) FROM log").fetchone() == (3,)


def test_executemany_through_the_proxy_clears_the_reuse():
    raw = duckdb.connect()
    raw.execute("CREATE TABLE t (k INTEGER)")
    with request_memo.scope():
        con = request_memo.connection(raw)
        assert con.execute("SELECT COUNT(*) FROM t").fetchone() == (0,)
        con.executemany("INSERT INTO t VALUES (?)", [[1], [2]])
        assert con.execute("SELECT COUNT(*) FROM t").fetchone() == (2,)
    raw.close()


def test_register_through_the_proxy_clears_the_reuse():
    import pandas as pd

    raw = duckdb.connect()
    with request_memo.scope():
        con = request_memo.connection(raw)
        con.register("frame", pd.DataFrame({"k": [1]}))
        assert con.execute("SELECT COUNT(*) FROM frame").fetchone() == (1,)
        con.register("frame", pd.DataFrame({"k": [1, 2]}))
        assert con.execute("SELECT COUNT(*) FROM frame").fetchone() == (2,)
    raw.close()


def test_list_and_struct_cells_are_handed_out_as_fresh_copies():
    raw = duckdb.connect()
    with request_memo.scope():
        con = request_memo.connection(raw)
        query = "SELECT [1, 2] AS l, {'a': 1} AS s"
        first = con.execute(query).fetchall()
        first[0][0].append(99)
        first[0][1]["a"] = 5
        again = con.execute(query).fetchall()
        again[0][0].append(98)
        assert con.execute(query).fetchall() == [([1, 2], {"a": 1})]
    raw.close()


def test_large_results_are_read_through_and_not_kept(raw, monkeypatch):
    monkeypatch.setattr(request_memo, "MAX_KEPT_ROWS", 2)
    with request_memo.scope():
        con = request_memo.connection(raw)
        for _ in range(2):
            assert len(con.execute("SELECT k FROM t").fetchall()) == 3
        for _ in range(2):
            assert len(con.execute("SELECT k FROM t WHERE k < 3").fetchall()) == 2
    assert raw.statements.count("SELECT k FROM t") == 2
    assert raw.statements.count("SELECT k FROM t WHERE k < 3") == 1
