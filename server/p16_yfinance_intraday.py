"""P16-only Yahoo five-minute adapter that can recover opening bars at noon."""
from __future__ import annotations

import hashlib
import math
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

from . import intraday_source

SOURCE_ID = "yfinance"
SOURCE_VERSION = "p16-yahoo-chart-5m-v1"
_NEW_YORK = ZoneInfo("America/New_York")


def parse(session_date: date, ticker: str, provider_ticker: str,
          response: intraday_source.Response) -> dict:
    """Normalize only the three opening slots without applying latest-bar freshness."""
    requested = intraday_source._utc(response.requested_at, "request timestamp")
    received = intraday_source._utc(response.received_at, "receipt timestamp")
    timestamps, values, fields = intraday_source._response_series(
        provider_ticker, response, requested, received)
    expected = {datetime.combine(session_date, time(9, 30 + 5 * index), _NEW_YORK)
                .astimezone(timezone.utc) for index in range(3)}
    bars, seen = [], set()
    for index, epoch in enumerate(timestamps):
        if isinstance(epoch, bool) or not isinstance(epoch, int):
            raise intraday_source.IntradaySourceError("intraday event timestamp is invalid")
        started = datetime.fromtimestamp(epoch, timezone.utc)
        if started not in expected:
            continue
        if started in seen or started > received:
            raise intraday_source.IntradaySourceError("intraday event timestamp is invalid")
        seen.add(started)
        row = [values[field][index] for field in fields]
        if any(value is None for value in row):
            continue
        o, high, low, close = map(intraday_source._price, row[:4])
        volume = row[4]
        if (isinstance(volume, bool) or not isinstance(volume, (int, float))
                or not math.isfinite(volume) or volume < 0 or not float(volume).is_integer()
                or low > min(o, high, close) or high < max(o, low, close)):
            raise intraday_source.IntradaySourceError("intraday OHLCV is invalid")
        bars.append({"start_at": started, "open": o, "high": high, "low": low,
                     "close": close, "volume": int(volume), "vwap_value": None,
                     "vwap_kind": None, "volume_scope": "bar", "halted": False})
    return {"source": SOURCE_ID, "source_version": SOURCE_VERSION,
            "venue": "Yahoo consolidated", "provider": "yahoo_chart_v8",
            "currency": "USD", "adjustment": "provider_chart_default",
            "resolution": "5m", "regular_session": True, "bars": bars}


def capture(session_date: date, ticker: str, provider_ticker: str, *,
            observed_at: datetime, fetch=intraday_source._fetch) -> dict:
    response = fetch(provider_ticker, observed_at)
    return {"receipt_sha256": hashlib.sha256(response.body).hexdigest(),
            "payload": parse(session_date, ticker, provider_ticker, response)}
