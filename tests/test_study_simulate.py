from datetime import date, datetime, timezone

import pytest

from farm.study.benchmark import Benchmark
from farm.study.costs import CostSelection, calculate
from farm.study.data import Bar, DerivedInput, LookAheadError, MarketData, PriceSource
from farm.study.report import build_report
from farm.study.run import run_simulate_jobs
from farm.study.simulate import simulate_events, simulate_portfolio
from farm.study.spec import EventStrategy, ExitRule, FillPoint, Order, PortfolioStrategy
from farm.study.universe import ListingInterval, Universe

D0, D1, D2, D3 = (date(2024, 1, day) for day in (2, 3, 4, 5))
COSTS = CostSelection("ibkr_tiered_auction_v1", ("ibkr_fixed_v1",))


def _bar(ticker, day, open_px=100.0, close=110.0, *, intraday=105.0,
         funding=None):
    available = [value for value in (open_px, close) if value is not None]
    return Bar(ticker, day, open_px, max(available), min(available), close, 1_000_000,
               funding=funding, intraday_closes={"14:00": intraday})


def _fixture(bars, listings=None, secondary=None, derived=()):
    source = PriceSource.declared(source="primary", bars=bars)
    intervals = listings or tuple(
        ListingInterval(ticker, min(bar.session for bar in bars if bar.ticker == ticker))
        for ticker in sorted({bar.ticker for bar in bars}))
    return MarketData(source, secondary, derived), Universe(source, intervals)


def _fill_orders(view, session):
    if session != D0:
        return []
    close = ExitRule.same_session_close()
    return [
        Order("NEXT", "long", FillPoint.next_open(), close, 10_000),
        Order("OPEN", "long", FillPoint.open_auction(), close, 10_000),
        Order("BAR", "long", FillPoint.bar_close("14:00"), close, 10_000),
        Order("CLOSE", "long", FillPoint.close_auction(), close, 10_000),
    ]


def test_every_fill_point_is_taken_from_its_named_bar():
    bars = []
    for day in (D0, D1, D2):
        bars.extend(_bar(ticker, day, 100 + (day == D1) * 5, 110 + (day == D1) * 5)
                    for ticker in ("OPEN", "CLOSE", "BAR", "NEXT"))
    data, universe = _fixture(bars)
    strategy = EventStrategy(
        "fills", "pre_open", _fill_orders, 4, 10_000, max_new_per_session=4)
    ledger = simulate_events(strategy, data, universe, (D0, D2), COSTS, Benchmark("cash"))
    trades = {trade.ticker: trade for trade in ledger.trades}
    assert (trades["OPEN"].entry_session, trades["OPEN"].entry_price) == (D0, 100)
    assert (trades["CLOSE"].entry_session, trades["CLOSE"].entry_price) == (D0, 110)
    assert (trades["BAR"].entry_field, trades["BAR"].entry_price) == ("bar_close@14:00", 105)
    assert (trades["NEXT"].entry_session, trades["NEXT"].entry_price) == (D1, 105)
    assert trades["OPEN"].gross_return == pytest.approx(0.1)
    assert trades["CLOSE"].gross_return == 0


def _condition_hit(view, position):
    return view.value(position.ticker, "close") >= 105


def _condition_never(view, position):
    return False


def _exit_orders(view, session):
    if session != D0:
        return []
    return [
        Order("FIXED", "long", FillPoint.open_auction(),
              ExitRule.after_n_sessions(2, at=FillPoint.close_auction()), 10_000),
        Order("TIME", "long", FillPoint.open_auction(), ExitRule.at_time("14:00"), 10_000),
        Order("HIT", "long", FillPoint.open_auction(),
              ExitRule.first_condition(_condition_hit, 2), 10_000),
        Order("FALLBACK", "long", FillPoint.open_auction(),
              ExitRule.first_condition(_condition_never, 2), 10_000),
    ]


def test_every_exit_rule_including_condition_hit_and_fallback():
    closes = {D0: 100, D1: 106, D2: 108, D3: 109}
    bars = [_bar(ticker, day, 100, closes[day], intraday=103)
            for day in closes for ticker in ("FIXED", "TIME", "HIT", "FALLBACK")]
    data, universe = _fixture(bars)
    strategy = EventStrategy(
        "exits", "pre_open", _exit_orders, 4, 10_000, max_new_per_session=4,
        close_as_indication=True)
    ledger = simulate_events(strategy, data, universe, (D0, D3), COSTS, Benchmark("cash"))
    trades = {trade.ticker: trade for trade in ledger.trades}
    assert (trades["FIXED"].exit_session, trades["FIXED"].exit_reason) == (
        D2, "after_n_sessions")
    assert (trades["TIME"].exit_session, trades["TIME"].exit_price) == (D0, 103)
    assert (trades["HIT"].exit_session, trades["HIT"].exit_reason) == (
        D1, "first_condition")
    assert (trades["FALLBACK"].exit_session, trades["FALLBACK"].exit_reason) == (
        D2, "first_condition_fallback")


def _missing_orders(view, session):
    if session != D0:
        return []
    exit_rule = ExitRule.after_n_sessions(1, at=FillPoint.close_auction())
    return [Order("NOENTRY", "long", FillPoint.open_auction(), exit_rule, 10_000),
            Order("NOEXIT", "long", FillPoint.open_auction(), exit_rule, 10_000)]


def test_missing_entry_is_unfilled_and_missing_exit_waits_for_a_real_bar():
    bars = [_bar("NOENTRY", D0, None, 100), _bar("NOEXIT", D0, 100, 100),
            _bar("NOEXIT", D1, 101, None), _bar("NOEXIT", D2, 102, 111)]
    data, universe = _fixture(bars)
    ledger = simulate_events(
        EventStrategy("missing", "pre_open", _missing_orders, 2, 10_000,
                      max_new_per_session=2),
        data, universe, (D0, D2), COSTS, Benchmark("cash"))
    assert ledger.unfilled_counts == {"missing_entry_bar": 1}
    assert len(ledger.trades) == 1
    assert ledger.trades[0].exit_session == D2
    assert ledger.trades[0].flags == ("missing_exit_bar",)


def _delist_orders(view, session):
    if session != D0:
        return []
    exit_rule = ExitRule.after_n_sessions(3, at=FillPoint.close_auction())
    return [Order("LAST", "long", FillPoint.open_auction(), exit_rule, 10_000),
            Order("FALL", "long", FillPoint.open_auction(), exit_rule, 10_000)]


def test_delisting_uses_last_close_or_configured_return_without_a_price():
    bars = [_bar("LAST", D0, 100, 100), _bar("LAST", D1, 90, 80),
            _bar("FALL", D0, 100, None), _bar("MARKET", D0), _bar("MARKET", D1),
            _bar("MARKET", D2), _bar("MARKET", D3)]
    listings = (ListingInterval("LAST", D0, D1), ListingInterval("FALL", D0, D1),
                ListingInterval("MARKET", D0))
    data, universe = _fixture(bars, listings)
    ledger = simulate_events(
        EventStrategy("delist", "pre_open", _delist_orders, 2, 10_000,
                      max_new_per_session=2),
        data, universe, (D0, D3), COSTS, Benchmark("cash"))
    trades = {trade.ticker: trade for trade in ledger.trades}
    assert (trades["LAST"].exit_session, trades["LAST"].exit_price,
            trades["LAST"].exit_reason) == (D1, 80, "delisting")
    assert trades["FALL"].exit_price == pytest.approx(70)
    assert trades["FALL"].exit_reason == "delisting_fallback"
    assert trades["FALL"].flags == ("delisting_return",)


def _unordered_orders(view, session):
    if session != D0:
        return []
    return [Order(name, "long", FillPoint.open_auction(), ExitRule.same_session_close(), 10_000)
            for name in ("CCC", "AAA", "BBB")]


def _unknown_order(view, session):
    return [Order("UNKNOWN", "long", FillPoint.open_auction(),
                  ExitRule.same_session_close(), 10_000)]


def test_tie_break_makes_max_new_and_max_concurrent_deterministic():
    bars = [_bar(name, D0) for name in ("AAA", "BBB", "CCC")]
    data, universe = _fixture(bars)
    limited_new = simulate_events(
        EventStrategy("new", "pre_open", _unordered_orders, 3, 10_000,
                      max_new_per_session=1, order_sort_key=("ticker",)),
        data, universe, [D0], COSTS, Benchmark("cash"))
    assert [trade.ticker for trade in limited_new.trades] == ["AAA"]
    assert limited_new.rejected_counts == {"max_new_per_session": 2}
    limited_slots = simulate_events(
        EventStrategy("slots", "pre_open", _unordered_orders, 1, 10_000,
                      max_new_per_session=3, order_sort_key=("ticker",)),
        data, universe, [D0], COSTS, Benchmark("cash"))
    assert [trade.ticker for trade in limited_slots.trades] == ["AAA"]
    assert limited_slots.rejected_counts == {"max_concurrent": 2}
    unknown = simulate_events(
        EventStrategy("unknown", "pre_open", _unknown_order, 1, 10_000),
        data, universe, [D0], COSTS, Benchmark("cash"))
    assert unknown.rejected_counts == {"not_in_universe": 1}


def _one_order(view, session):
    return ([Order("AAA", "long", FillPoint.open_auction(),
                   ExitRule.same_session_close(), 10_000)] if session == D0 else [])


def test_native_ledger_matches_hand_replay_field_for_field_and_feeds_report():
    primary = [_bar("AAA", D0, 100, 110)]
    secondary = PriceSource.declared(source="secondary", bars=[_bar("AAA", D0, 101, 111)])
    data, universe = _fixture(primary, secondary=secondary)
    ledger = simulate_events(
        EventStrategy("one", "pre_open", _one_order, 1, 10_000), data, universe,
        [D0], COSTS, Benchmark("cash"))
    entry = calculate(COSTS.primary, side="buy", notional=10_000, fill_price=100).total
    exit_ = calculate(COSTS.primary, side="sell", notional=11_000, fill_price=110).total
    sensitivity_entry = calculate(
        COSTS.sensitivities[0], side="buy", notional=10_000, fill_price=100).total
    sensitivity_exit = calculate(
        COSTS.sensitivities[0], side="sell", notional=11_000, fill_price=110).total
    gross = 110 / 100 - 1
    expected = {
        "entry_session": D0.isoformat(), "exit_session": D0.isoformat(), "ticker": "AAA",
        "side": "long", "entry_field": "open", "exit_field": "close",
        "entry_price": 100.0, "exit_price": 110.0, "shares": 100.0,
        "notional": 10_000, "mdv60": None, "auction_volume": None,
        "costs_by_profile": {
            COSTS.primary: {"entry": entry, "exit": exit_, "funding": 0.0,
                            "total": entry + exit_},
            COSTS.sensitivities[0]: {"entry": sensitivity_entry, "exit": sensitivity_exit,
                                     "funding": 0.0,
                                     "total": sensitivity_entry + sensitivity_exit}},
        "gross_return": gross, "net_return": gross - (entry + exit_) / 10_000,
        "net_returns_by_profile": {
            COSTS.primary: gross - (entry + exit_) / 10_000,
            COSTS.sensitivities[0]: gross - (sensitivity_entry + sensitivity_exit) / 10_000},
        "benchmark_return": 0.0, "excess_return": gross - (entry + exit_) / 10_000,
        "absolute_net_positive": True, "exit_reason": "same_session_close", "flags": []}
    assert ledger.trades[0].as_dict() == expected
    report = build_report(
        identity="a" * 64, data=data, costs=COSTS, benchmark=Benchmark("cash"),
        variants=[{"variant": "one", "net_return": ledger.trades[0].net_return,
                   "benchmark_return": 0.0, "excess_return": ledger.trades[0].excess_return,
                   "absolute_net_positive": True, "trades": 1, "one_sided_t": 0.0}],
        folds=[], hard_max_date=D0, ledger=ledger, close_as_indication=True,
        runtime_seconds=0.1, worker_count=1, job_count=1,
        serial_parallel_identical=True)
    assert report["independent_price_cross_check"]["covered_trades"] == 1
    assert report["execution"]["exit_reasons"] == {"same_session_close": 1}
    assert any("close_as_indication" in caveat for caveat in report["caveats"])


def _bad_orders(view, session):
    view.value("AAA", "close")
    return []


def _bad_predicate(view, position):
    view.value(position.ticker, "open", D3)
    return False


def _bad_predicate_order(view, session):
    return ([Order("AAA", "long", FillPoint.open_auction(),
                   ExitRule.first_condition(_bad_predicate, 2), 10_000)]
            if session == D0 else [])


def test_order_and_exit_predicate_lookahead_raise():
    data, universe = _fixture([_bar("AAA", day) for day in (D0, D1, D2, D3)])
    with pytest.raises(LookAheadError):
        simulate_events(EventStrategy("bad", "pre_open", _bad_orders, 1, 10_000),
                        data, universe, (D0, D2), COSTS, Benchmark("cash"))
    with pytest.raises(LookAheadError):
        simulate_events(
            EventStrategy("bad-predicate", "pre_open", _bad_predicate_order, 1, 10_000,
                          close_as_indication=True),
            data, universe, (D0, D3), COSTS, Benchmark("cash"))


def _flat_weights(view, session):
    return {}


def _long_weights(view, session):
    return {"AAA": 1.0}


def test_portfolio_marks_every_session_holds_missing_bars_and_charges_turnover():
    bars = [_bar("AAA", D0, 100, 100), _bar("AAA", D1, 100, 110),
            _bar("AAA", D3, 110, 121)]
    bars.extend(_bar("MARKET", day, 100, 100) for day in (D0, D1, D2, D3))
    data, universe = _fixture(bars)
    flat = simulate_portfolio(
        PortfolioStrategy("flat", "pre_open", _flat_weights, "daily",
                          FillPoint.open_auction()),
        data, universe, (D0, D3), COSTS, Benchmark("cash"))
    assert flat.returns.tolist() == [0, 0, 0, 0]
    ledger = simulate_portfolio(
        PortfolioStrategy("long", "pre_open", _long_weights, "daily",
                          FillPoint.open_auction()),
        data, universe, (D0, D3), COSTS, Benchmark("cash"))
    assert len(ledger.days) == 4
    assert ledger.days[0].turnover == pytest.approx(100_000)
    assert ledger.days[0].costs_by_profile[COSTS.primary] > 0
    assert ledger.days[2].net_return == 0
    assert ledger.days[2].flags == ("missing_bar",)


def test_portfolio_applies_supplied_perpetual_funding():
    warmup = date(2024, 1, 1)
    bars = [_bar("AAA", warmup, 100, 100, funding=0.001),
            _bar("AAA", D0, 100, 100, funding=0.001),
            _bar("AAA", D1, 100, 100, funding=0.001)]
    data, universe = _fixture(bars)
    costs = CostSelection("binance_perp_base_v1", ("binance_spot_base_v1",))
    ledger = simulate_portfolio(
        PortfolioStrategy("perp", "pre_open", _long_weights, "daily",
                          FillPoint.open_auction()),
        data, universe, (D0, D1), costs, Benchmark("cash"))
    assert ledger.days[0].costs_by_profile[costs.primary] > 100
    assert ledger.days[0].returns_by_profile[costs.primary] < 0


def test_derived_inputs_are_timestamp_and_hard_max_gated_and_declared():
    derived = DerivedInput(
        "events",
        [{"session": D0, "ticker": "AAA",
          "available_at": datetime(2024, 1, 2, 15, 0, tzinfo=timezone.utc),
          "eligible": True},
         {"session": D1, "ticker": "AAA",
          "available_at": datetime(2024, 1, 3, 15, 0, tzinfo=timezone.utc),
          "eligible": False}],
        "available_at", {"source": "study-private", "rule": "published timestamp"})
    data, _ = _fixture([_bar("AAA", D0), _bar("AAA", D1)], derived=(derived,))
    assert data.view(D0, "10:30", D0).derived("events", "eligible", ticker="AAA") is True
    assert data.view(D0, "10:30", D0).value("AAA", "events.eligible") is True
    with pytest.raises(LookAheadError):
        data.view(D0, "09:45", D0).derived("events", "eligible", ticker="AAA")
    with pytest.raises(LookAheadError):
        data.view(D0, "10:30", D0).derived(
            "events", "eligible", session=D1, ticker="AAA")
    report = build_report(
        identity="b" * 64, data=data, costs=COSTS, benchmark=Benchmark("cash"),
        variants=[{"variant": "x", "net_return": 0.0, "benchmark_return": 0.0,
                   "excess_return": 0.0, "absolute_net_positive": False,
                   "trades": 0, "one_sided_t": 0.0}], folds=[], hard_max_date=D0,
        runtime_seconds=0.0, worker_count=1, job_count=1,
        serial_parallel_identical=None)
    assert report["data"]["derived_inputs"][0]["name"] == "events"


def _parallel_native(job):
    close = 101 + job.parameters["offset"]
    data, universe = _fixture([_bar("AAA", D0, 100, close)])
    return simulate_events(
        EventStrategy("one", "pre_open", _one_order, 1, 10_000), data, universe,
        [D0], COSTS, Benchmark("cash"))


def test_simulate_jobs_are_serial_parallel_byte_identical():
    variants = {"b": {"offset": 2}, "a": {"offset": 1}}
    serial = run_simulate_jobs(variants, [1, 2], _parallel_native,
                               master_seed=8, max_workers=1)
    parallel = run_simulate_jobs(variants, [1, 2], _parallel_native,
                                 master_seed=8, max_workers=2)
    assert serial.json_bytes == parallel.json_bytes
