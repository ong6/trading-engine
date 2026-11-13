"""Use yfinance's supported exception switch without changing retry semantics."""
import warnings
from datetime import date
from types import SimpleNamespace

import pytest
from yfinance.exceptions import YFTzMissingError
from yfinance.scrapers.history import PriceHistory

from server import p15_incremental_collect as incremental


@pytest.mark.parametrize("previous", [True, False])
def test_history_raises_without_deprecation_and_restores_config(monkeypatch, previous):
    # Actual installed history code, with missing timezone, fails before any HTTP.
    provider = PriceHistory(None, "XP", None)
    monkeypatch.setattr(incremental.collect.yf, "Ticker", lambda _: provider)
    monkeypatch.setattr(incremental.collect.yf.config.debug, "hide_exceptions", previous)
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        with pytest.raises(YFTzMissingError):
            incremental._history("XP", date(2026, 10, 26), date(2026, 10, 27))
    assert not [w for w in seen if issubclass(w.category, DeprecationWarning)]
    assert incremental.collect.yf.config.debug.hide_exceptions is previous


def test_success_restores_config_and_preserves_request(monkeypatch):
    def history(**kwargs):
        assert incremental.collect.yf.config.debug.hide_exceptions is False
        assert kwargs == dict(start="2026-10-26", end="2026-10-27", interval="1d",
                              auto_adjust=False, actions=False, timeout=30)
        return "response"

    monkeypatch.setattr(incremental.collect.yf, "Ticker",
                        lambda _: SimpleNamespace(history=history))
    monkeypatch.setattr(incremental.collect.yf.config.debug, "hide_exceptions", True)
    assert incremental._history("XP", date(2026, 10, 26), date(2026, 10, 27)) == "response"
    assert incremental.collect.yf.config.debug.hide_exceptions is True


def test_provider_error_still_gets_one_retry(monkeypatch):
    provider = PriceHistory(None, "XP", None)
    monkeypatch.setattr(incremental.collect.yf, "Ticker", lambda _: provider)
    sleeps = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        assert incremental._fetch_exact(
            {"ticker": "XP", "provider_ticker": "XP", "market_date": date(2026, 10, 26)},
            requested_at=None, history=incremental._history, sleep=sleeps.append,
        ) == (None, None)
    assert sleeps == [2]
