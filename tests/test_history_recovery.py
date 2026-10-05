"""Explicit recovery preserves frozen collection and rejects mixed listing history."""
from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest
from yfinance.scrapers.history import HistoryMetadata

from engine import history_recovery as recovery
from engine.lib import db
from tests.test_collect import _raw_frame


def _provider(monkeypatch, *, frame=None, metadata=None, lazy=False):
    identity = {"symbol": "AAA", "currency": "USD", "instrumentType": "EQUITY",
                "exchangeTimezoneName": "America/New_York",
                "firstTradeDate": pd.Timestamp("2026-10-02T09:30:00-04:00"),
                "regularMarketTime": pd.Timestamp("2026-10-05T09:46:00-04:00")}
    identity.update(metadata or {})
    calls = []

    class Ticker:
        def get_history_metadata(self):
            if lazy:
                return HistoryMetadata(SimpleNamespace(_history_metadata=identity))
            return identity

        def history(self, **kwargs):
            calls.append(kwargs)
            return _raw_frame("2026-10-02") if frame is None else frame

    monkeypatch.setattr(recovery.yf, "Ticker", lambda _ticker: Ticker())
    return calls


def _database(tmp_path):
    path = tmp_path / "market.duckdb"
    con = db.connect(path)
    db.init_schema(con)
    con.execute("INSERT INTO universe(ticker,yf_ticker,name,exchange,etf,added,active,liquid,backfill_done) "
                "VALUES ('AAA','AAA','Current security','Q',FALSE,'2026-10-02',TRUE,TRUE,FALSE)")
    con.close()
    return path


def test_explicit_history_proves_listing_coverage_and_excludes_intraday_tail(monkeypatch):
    calls = _provider(monkeypatch)
    frame, evidence = recovery.fetch_history("AAA", "AAA", False)
    assert list(frame["date"]) == [date(2026, 10, 2)]
    assert evidence["first_session"] == evidence["last_session"] == "2026-10-02"
    assert calls == [{"start": "2026-10-02", "end": "2026-10-03", "period": None,
                      "auto_adjust": False, "actions": False, "raise_errors": True}]


def test_provider_epoch_clocks_are_supported(monkeypatch):
    _provider(monkeypatch, metadata={
        "firstTradeDate": int(pd.Timestamp("2026-10-02T09:30:00-04:00").timestamp()),
        "regularMarketTime": int(pd.Timestamp("2026-10-02T16:00:00-04:00").timestamp()),
    })
    assert len(recovery.fetch_history("AAA", "AAA", False)[0]) == 1


def test_yfinance_lazy_metadata_identity_does_not_request_intraday_fields(monkeypatch):
    # The installed provider returns Mapping, not dict. Missing the lazy loader
    # also proves recovery never requests unrelated intraday metadata.
    _provider(monkeypatch, lazy=True)
    frame, evidence = recovery.fetch_history("AAA", "AAA", False)
    assert len(frame) == 1
    assert evidence["provider_ticker"] == "AAA"


@pytest.mark.parametrize("metadata", [
    {"symbol": "OTHER"}, {"currency": "EUR"}, {"instrumentType": "ETF"},
    {"firstTradeDate": pd.Timestamp("2026-10-01T09:30:00-04:00")},
])
def test_refuses_wrong_identity_or_truncated_coverage(monkeypatch, metadata):
    _provider(monkeypatch, metadata=metadata)
    with pytest.raises(recovery.HistoryRefused):
        recovery.fetch_history("AAA", "AAA", False)


@pytest.mark.parametrize("overrides", [
    {"Open": float("inf"), "High": float("inf")}, {"Low": -1}, {"High": 1},
    {"Volume": -1}, {"Volume": 0.5}, {"Close": 0},
])
def test_refuses_invalid_ohlcv(monkeypatch, overrides):
    frame = _raw_frame("2026-10-02")
    for field, value in overrides.items():
        frame[field] = value
    _provider(monkeypatch, frame=frame)
    with pytest.raises(recovery.HistoryRefused, match="invalid OHLCV"):
        recovery.fetch_history("AAA", "AAA", False)


def test_recovery_inserts_missing_rows_and_preserves_existing_row_exactly(monkeypatch, tmp_path):
    path = _database(tmp_path)
    frame = pd.concat([_raw_frame("2026-10-01"), _raw_frame("2026-10-02")])
    _provider(monkeypatch, frame=frame, metadata={
        "firstTradeDate": pd.Timestamp("2026-10-01T09:30:00-04:00"),
    })
    normalized, _ = recovery.fetch_history("AAA", "AAA", False)
    con = db.connect(path)
    db.upsert_prices(con, normalized.iloc[1:])
    before = con.execute("SELECT * FROM prices").fetchone()
    con.close()
    result = recovery.recover(path, "AAA")
    assert result["inserted_rows"] == result["existing_rows_unchanged"] == 1
    con = db.connect(path, read_only=True)
    assert con.execute("SELECT * FROM prices WHERE date='2026-10-02'").fetchone() == before
    assert con.execute("SELECT backfill_done FROM universe").fetchone() == (True,)
    con.close()
    with pytest.raises(recovery.HistoryRefused, match="pending"):
        recovery.recover(path, "AAA")


@pytest.mark.parametrize("change", ["old_listing", "different_price", "different_source"])
def test_refuses_conflicting_stored_security_or_prices_without_changes(monkeypatch, tmp_path, change):
    path = _database(tmp_path)
    _provider(monkeypatch)
    frame, _ = recovery.fetch_history("AAA", "AAA", False)
    con = db.connect(path)
    db.upsert_prices(con, frame)
    if change == "old_listing":
        con.execute("UPDATE prices SET date='2022-01-03'")
    elif change == "different_price":
        con.execute("UPDATE prices SET close=200")
    else:
        con.execute("UPDATE prices SET source='other'")
    before = con.execute("SELECT * FROM prices").fetchall()
    con.close()
    with pytest.raises(recovery.HistoryRefused):
        recovery.recover(path, "AAA")
    con = db.connect(path, read_only=True)
    assert con.execute("SELECT * FROM prices").fetchall() == before
    assert con.execute("SELECT backfill_done FROM universe").fetchone() == (False,)
    con.close()


@pytest.mark.parametrize("change", ["binding", "stored_price"])
def test_rechecks_binding_and_stored_prices_after_network(monkeypatch, tmp_path, change):
    path = _database(tmp_path)
    _provider(monkeypatch)

    def fetch(*args):
        result = recovery.fetch_history(*args)
        con = db.connect(path, wait_s=0)
        if change == "binding":
            con.execute("UPDATE universe SET name='Different security'")
        else:
            frame = result[0].copy()
            frame["close"] = 200
            db.upsert_prices(con, frame)
        con.close()
        return result

    with pytest.raises(recovery.HistoryRefused):
        recovery.recover(path, "AAA", fetch=fetch)
    con = db.connect(path, read_only=True)
    assert con.execute("SELECT backfill_done FROM universe").fetchone() == (False,)
    con.close()
