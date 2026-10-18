"""Observed P15 horizons survive quarantine without supplying an execution price."""
from datetime import date, datetime, timezone

import pytest

from engine.lib import db
from engine.p15_calendar import observed_sessions
from server import agent_evaluation
from sim import p15_books, portfolio
from tests.conftest import insert_bars
from tests.test_agent_evaluation_reporting import _schema2_common_label, _validate_common
from tests.test_p15_books import _activate
from tools import p15_evidence_validation


def rejected(con, day, reason, *, recorded_at=datetime(2026, 10, 17)):
    db.append_price_observations(con, [dict(ticker='SPY', date=day, open=100,
                                high=99, low=98, close=100, volume=1000,
                                fetched_at=datetime(2026, 10, 16))],
                                reason=reason, batch_id='fixture', recorded_at=recorded_at)


def test_observed_calendar_preserves_hard_rejects_and_limits_basis_holds(con):
    insert_bars(con, 'SPY', [date(2026, 10, 14)])
    rejected(con, date(2026, 10, 15), 'high_geometry')
    rejected(con, date(2026, 10, 15), 'low_geometry')
    rejected(con, date(2026, 10, 16), 'basis_unverified')
    rejected(con, date(2026, 10, 17), 'basis_unverified')
    for reason in ('identical_duplicate', 'replacement_predecessor', 'split_restatement_predecessor'):
        rejected(con, date(2026, 10, 19), reason)
    expected = [date(2026, 10, 14), date(2026, 10, 15), date(2026, 10, 16)]
    assert observed_sessions(con) == expected
    assert observed_sessions(con, after=expected[0], limit=1) == expected[1:2]
    assert observed_sessions(con, through=expected[1]) == expected[:2]
    assert observed_sessions(con, after=expected[0], include_after=True) == expected
    assert observed_sessions(con, known_at=datetime(2026, 10, 16, 22, tzinfo=timezone.utc)) == []
    assert observed_sessions(con, known_at=datetime(2026, 10, 17, 1, tzinfo=timezone.utc)) == expected[1:]


def test_reject_date_preserves_stored_label_hash_and_maturity(con):
    _schema2_common_label(con)
    before = con.execute('SELECT * FROM agent_evaluation_labels_v2 ORDER BY id').fetchall()
    baseline = _validate_common(con)
    columns = [r[0] for r in con.execute("DESCRIBE agent_evaluation_labels_v2").fetchall()]
    day = dict(zip(columns, before[0], strict=True))['exit_date']
    rejected(con, day, 'high_geometry')
    con.execute("DELETE FROM prices WHERE ticker='SPY' AND date=?", [day])
    status = _validate_common(con)
    assert status['labels_source_revised'] == 1
    assert con.execute('SELECT * FROM agent_evaluation_labels_v2 ORDER BY id').fetchall() == before
    assert baseline['labels_source_revised'] == 0
    assert p15_evidence_validation.validation_sessions(
        con, source_market_date=day, entry_date=day, exit_date=day,
        horizon_sessions=1, include_source_date=True) == [day]
    assert agent_evaluation._label_outcome(con, 'AAA', [day], datetime(2026, 10, 20, tzinfo=timezone.utc)) is None


@pytest.mark.parametrize('kind', ['missing', 'geometry', 'zero_volume'])
def test_window_waits_and_audits_missing_sleeve_price_without_money(con, kind):
    signal, day = date(2026, 10, 14), date(2026, 10, 15)
    insert_bars(con, 'SPY', [signal])
    _activate(con, signal)
    p15_books.run_window(con, signal, observed_at=datetime(2026, 10, 14, 22, tzinfo=timezone.utc))
    for book in p15_books.BOOK_IDS:
        con.execute("INSERT INTO sim_positions VALUES (?,'SPY',1,100)", [book])
    if kind != 'missing':
        insert_bars(con, 'SPY', [day], high=99 if kind == 'geometry' else 101,
                    low=98, volume=0 if kind == 'zero_volume' else 1000)
    rejected(con, day, 'high_geometry')
    before = {book: (portfolio.get_cash(con, book), portfolio.get_positions(con, book))
              for book in p15_books.BOOK_IDS}
    now = datetime(2026, 10, 16, 2, tzinfo=timezone.utc)
    result = p15_books.run_window(con, day, observed_at=now)
    assert result['status'] == 'completed' and result['pending'] == 3 and result['filled'] == 0
    assert con.execute('SELECT DISTINCT status,reason FROM p15_order_intents').fetchall() == [('pending', 'untrusted_bar')]
    assert con.execute("SELECT COUNT(*) FROM audit_log WHERE action='waiting_bar' AND payload LIKE '%untrusted_bar%'").fetchone() == (6,)
    assert {book: (portfolio.get_cash(con, book), portfolio.get_positions(con, book))
            for book in p15_books.BOOK_IDS} == before
    assert all(result['marks'][book]['carried'] == ['SPY'] for book in p15_books.BOOK_IDS)
    assert p15_books.run_window(con, day, observed_at=now)['status'] == 'completed'
    assert con.execute("SELECT COUNT(*) FROM audit_log WHERE action='waiting_bar'").fetchone() == (6,)


def test_no_rejects_preserves_label_bytes_and_price_calendar(con):
    _schema2_common_label(con)
    before = con.execute('SELECT * FROM agent_evaluation_labels_v2 ORDER BY id').fetchall()
    expected = [row[0] for row in con.execute("SELECT DISTINCT date FROM prices WHERE ticker='SPY' ORDER BY date").fetchall()]
    assert observed_sessions(con) == expected
    assert _validate_common(con) == {'labels_source_revised': 0, 'labels_source_revised_ids': []}
    db.init_price_rejects_schema(con)
    assert observed_sessions(con) == expected
    assert _validate_common(con) == {'labels_source_revised': 0, 'labels_source_revised_ids': []}
    assert con.execute('SELECT * FROM agent_evaluation_labels_v2 ORDER BY id').fetchall() == before
