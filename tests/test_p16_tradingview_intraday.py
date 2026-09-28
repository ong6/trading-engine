"""Contract tests for the separate TradingView five-minute chart path."""
from __future__ import annotations

import json
from datetime import date, datetime, timezone

from server import p16_tradingview_intraday as source
from server import tradingview_source as tv


def _transcript():
    epochs = [
        int(datetime(2026, 10, 5, 13, minute, tzinfo=timezone.utc).timestamp())
        for minute in (30, 35, 40)
    ]
    packets = [
        {"m": "symbol_resolved", "p": ["cs_p16fills", "ser_1",
         {"source_id": "test", "exchange": "NASDAQ"}]},
        {"m": "timescale_update", "p": ["cs_p16fills", {"$prices": {"s": [
            {"v": [epoch, 100 + i, 101 + i, 99 + i, 100.5 + i, 1000 + i]}
            for i, epoch in enumerate(epochs)
        ]}}]},
        {"m": "series_completed", "p": ["cs_p16fills", "$prices"]},
    ]
    body = json.dumps({
        "schema_version": 1, "mode": "p16_history_5m",
        "source_version": source.SOURCE_VERSION, "endpoint": tv.ENDPOINT,
        "request": source.request_identity("NASDAQ:AAA"), "sent": [],
        "received": [tv._packet(packet["m"], packet["p"]) for packet in packets],
    }).encode()
    return tv.Transcript(
        body, datetime(2026, 10, 5, 13, 29, tzinfo=timezone.utc),
        datetime(2026, 10, 5, 13, 46, tzinfo=timezone.utc),
    )


def test_commands_request_five_minute_regular_split_adjusted_series():
    rows = source.commands("NASDAQ:AAA", "cs_fixture")
    assert rows[-1][0] == "create_series"
    assert rows[-1][1][-2:] == [source.RESOLUTION, source.BAR_COUNT]
    assert '"adjustment":"splits"' in rows[2][1][-1]
    assert '"session":"regular"' in rows[2][1][-1]


def test_parse_returns_exact_first_three_start_stamped_bars():
    parsed = source.parse("NASDAQ:AAA", date(2026, 10, 5), _transcript())
    assert parsed["resolution"] == "5"
    assert [row["start_at"].minute for row in parsed["bars"]] == [30, 35, 40]
    assert all(row["vwap_value"] is None for row in parsed["bars"])
