"""P15 comparator-book initialization and isolation contracts."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from server import p15_books
from sim.schema import init_sim_schema


def test_initialization_creates_exact_inactive_empty_books(con):
    created = date(2026, 9, 25)
    result = p15_books.initialize_books(
        con, created, initialized_at=datetime(2026, 9, 25, tzinfo=timezone.utc)
    )
    replay = p15_books.initialize_books(con, created)

    assert result == replay == {
        "status": "ready", "book_count": 3, "active_count": 0,
        "runtime_counts": {"sim_orders": 0, "sim_fills": 0,
                           "sim_positions": 0, "sim_equity": 0},
    }
    rows = con.execute(
        "SELECT id,active,cash,initial_cash,execution_profile FROM portfolios "
        "WHERE id IN (?,?,?) ORDER BY id", list(p15_books.BOOK_IDS)
    ).fetchall()
    assert [row[0] for row in rows] == sorted(p15_books.BOOK_IDS)
    assert all(row[1:] == (False, 10_000.0, 10_000.0, "baseline_v1") for row in rows)


def test_activation_is_atomic_aligned_and_rejects_contamination(con):
    init_sim_schema(con)
    checkpoint = date(2026, 9, 24)
    con.execute(
        "INSERT INTO portfolios (id,name,strategy,config,created,active,cash,initial_cash,"
        "execution_profile) VALUES ('control','control','noop','{}',?,TRUE,100,100,'baseline_v1')",
        [date(2026, 1, 1)],
    )
    con.execute("INSERT INTO sim_equity VALUES ('control',?,100,100,0)", [checkpoint])
    p15_books.initialize_books(con, checkpoint)

    result = p15_books.activate_books(con, checkpoint)

    assert result == {"status": "active", "book_count": 3,
                      "checkpoint": checkpoint.isoformat()}
    assert con.execute(
        "SELECT COUNT(*) FROM portfolios WHERE id IN (?,?,?) AND active", list(p15_books.BOOK_IDS)
    ).fetchone() == (3,)
    assert con.execute(
        "SELECT COUNT(*) FROM sim_equity WHERE portfolio_id IN (?,?,?) AND date=?",
        [*p15_books.BOOK_IDS, checkpoint],
    ).fetchone() == (3,)

    with pytest.raises(p15_books.P15BookError, match="jointly inactive"):
        p15_books.activate_books(con, checkpoint)


def test_mixed_activation_and_runtime_rows_fail_closed(con):
    checkpoint = date(2026, 9, 24)
    p15_books.initialize_books(con, checkpoint)
    con.execute("UPDATE portfolios SET active=TRUE WHERE id=?", [p15_books.BOOK_IDS[0]])
    with pytest.raises(p15_books.P15BookError, match="mixed activation"):
        p15_books.activation_state(con)

    con.execute("UPDATE portfolios SET active=FALSE WHERE id=?", [p15_books.BOOK_IDS[0]])
    con.execute(
        "INSERT INTO sim_orders VALUES (1,?,'SPY','buy',1,?,'pending',NULL)",
        [p15_books.BOOK_IDS[0], checkpoint],
    )
    with pytest.raises(p15_books.P15BookError, match="runtime state"):
        p15_books.activate_books(con, checkpoint)
