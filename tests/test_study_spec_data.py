from datetime import date, datetime, timedelta, timezone

import pytest

from farm.study.data import Bar, DataDeclaration, LookAheadError, MarketData, PriceSource
from farm.study.spec import EventStrategy, ExitRule, FillPoint, Order, PortfolioStrategy


def _orders(view, session):
    return [Order("AAA", "long", FillPoint.next_open(),
                  ExitRule.after_n_sessions(2, at=FillPoint.close_auction()), 1_000)]


def _weights(view, session):
    return {"AAA": 0.6, "BBB": -0.2}


def _bar(day, ticker="AAA", open_px=100.0, close=102.0, **kwargs):
    return Bar(ticker, day, open_px, 103.0, 99.0, close, 1_000.0, **kwargs)


def _source(name="primary", bars=None, **kwargs):
    return PriceSource.declared(source=name, bars=bars or [_bar(date(2024, 1, 2))], **kwargs)


def test_declarative_strategy_objects_validate_and_delegate():
    event = EventStrategy("event", "pre_open", _orders, 3, 1_000, {"z": [2, 1]})
    assert event.orders(None, date(2024, 1, 2))[0].exit.sessions == 2
    assert dict(event.parameters) == {"z": [2, 1]}
    portfolio = PortfolioStrategy(
        "portfolio", "15:45", _weights, "monthly", FillPoint.close_auction())
    assert portfolio.target_weights(None, date(2024, 1, 2)) == {"AAA": 0.6, "BBB": -0.2}
    assert FillPoint.bar_close("15:30").field == "bar_close@15:30"
    assert ExitRule.at_time("14:00").fill.field == "bar_close@14:00"


def test_specs_reject_bad_times_orders_parameters_and_closures():
    with pytest.raises(ValueError, match="HH:MM"):
        FillPoint.bar_close("9:30")
    with pytest.raises(ValueError, match="notional"):
        Order("AAA", "long", FillPoint.next_open(), ExitRule.same_session_close(), 0)
    with pytest.raises(ValueError, match="canonical JSON"):
        EventStrategy("bad", "pre_open", _orders, 1, 1, {"x": {1}})
    captured = 1

    def closure(view, session):
        return [] if captured else []

    with pytest.raises(ValueError, match="without a closure"):
        EventStrategy("bad", "pre_open", closure, 1, 1)


def test_close_is_unavailable_at_open_and_hard_max_cannot_be_crossed():
    day = date(2024, 1, 2)
    data = MarketData(_source())
    view = data.view(day, "at_open", day)
    with pytest.raises(LookAheadError, match="official open"):
        view.value("AAA", "open")
    with pytest.raises(LookAheadError, match="not known"):
        view.value("AAA", "close")
    assert data.view(day, "at_open", day, open_as_indication=True).value("AAA", "open") == 100
    with pytest.raises(LookAheadError, match="boundary"):
        view.value("AAA", "open", date(2024, 1, 3))


def test_daily_lag_and_intraday_availability_are_enforced():
    day = date(2024, 1, 2)
    source = _source(
        bars=[_bar(day, intraday_closes={"10:00": 101.0}, funding=0.001,
                   funding_at=datetime(2024, 1, 2, 21, tzinfo=timezone.utc))],
        daily_bar_lag=timedelta(hours=1))
    at_ten = MarketData(source).view(day, "10:00", day)
    assert at_ten.value("AAA", "bar_close@10:00") == 101
    with pytest.raises(LookAheadError):
        at_ten.value("AAA", "close")
    at_1700 = MarketData(source).view(day, "17:00", day)
    assert at_1700.value("AAA", "close") == 102
    assert at_1700.value("AAA", "funding") == pytest.approx(0.001)


def test_secondary_source_is_independent_and_never_falls_back():
    first, second = date(2024, 1, 2), date(2024, 1, 3)
    primary = _source(bars=[_bar(first), _bar(second, open_px=110)])
    secondary = _source("independent", bars=[_bar(first, open_px=101)])
    data = MarketData(primary, secondary)
    pair = data.fill_prices("AAA", first, "open", hard_max_date=second)
    assert pair.primary / pair.secondary - 1 == pytest.approx(100 / 101 - 1)
    uncovered = data.fill_prices("AAA", second, "open", hard_max_date=second)
    assert uncovered.primary == 110 and uncovered.secondary is None
    assert data.primary.declaration.snapshot_sha256 != data.secondary.declaration.snapshot_sha256


def test_duckdb_adapter_is_read_only_and_normalizes_rows(tmp_path):
    import duckdb

    path = tmp_path / "copy.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE prices(ticker VARCHAR, date DATE, open DOUBLE, high DOUBLE, "
                "low DOUBLE, close DOUBLE, volume DOUBLE)")
    con.execute("INSERT INTO prices VALUES ('AAA', DATE '2024-01-02', 1, 2, 0.5, 1.5, 10)")
    con.close()
    declaration = DataDeclaration("copy", "a" * 64, True, "point_in_time")
    source = PriceSource.from_duckdb(path, declaration)
    assert source.get("AAA", date(2024, 1, 2)).close == 1.5
    con = duckdb.connect(str(path), read_only=True)
    assert con.execute("SELECT COUNT(*) FROM prices").fetchone()[0] == 1
    con.close()
