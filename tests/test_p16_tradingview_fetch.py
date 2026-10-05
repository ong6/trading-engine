"""Exact transcript and bounded-failure checks for the inactive five-minute source."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from server import p16_tradingview_intraday as capture

NOW = datetime(2026, 10, 5, 13, 40, tzinfo=timezone.utc)
SYMBOL = "NASDAQ:AAPL"


def _frame(value):
    body = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    return f"~m~{len(body)}~m~{body}"


class _Socket:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.sent = []
        self.timeouts = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def send(self, message):
        self.sent.append(message)

    def recv(self, *, timeout):
        self.timeouts.append(timeout)
        item = next(self.messages)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def socket_factory(monkeypatch):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(capture, "datetime", FrozenDatetime)
    monkeypatch.setattr(capture, "time", SimpleNamespace(monotonic=lambda: 0.0))

    def install(messages):
        socket = _Socket(messages)
        monkeypatch.setattr(capture, "connect", lambda *_args, **_kwargs: socket)
        return socket

    return install


def test_fetch_preserves_exact_packet_order_and_heartbeat_after_completion(socket_factory):
    first = _frame("~h~7") + _frame({"m": "timescale_update", "p": []})
    last = _frame({"m": "series_completed", "p": []}) + _frame("~h~8")
    socket = socket_factory([first, last])
    result = capture.fetch(SYMBOL)
    expected = {
        "schema_version": 1, "mode": "p16_history_5m",
        "source_version": "p16-tradingview-chart-5m-v1", "endpoint": capture.tv.ENDPOINT,
        "request": {"symbol": SYMBOL, "resolution": "5", "bar_count": 40,
                    "session": "regular", "adjustment": "splits"},
        "sent": [capture.tv._packet(method, params)
                 for method, params in capture.commands(SYMBOL, "cs_p16fills")]
                + [_frame("~h~7"), _frame("~h~8")],
        "received": [first, last],
    }
    assert result.body == json.dumps(expected, sort_keys=True, separators=(",", ":")).encode()
    assert result.requested_at == result.received_at == NOW
    assert socket.sent == expected["sent"]
    assert socket.timeouts == [15.0, 15.0]
    assert socket.closed


@pytest.mark.parametrize(("message", "reason"), [
    (b"binary", "binary frame"),
    (_frame({"m": "protocol_error", "p": []}), "protocol error"),
    (OSError("unavailable"), "request failed"),
    (TimeoutError("no response"), "request failed"),
])
def test_fetch_preserves_failure_and_closes_socket(socket_factory, message, reason):
    socket = socket_factory([message])
    with pytest.raises(capture.tv.TradingViewSourceError, match=reason):
        capture.fetch(SYMBOL)
    assert socket.closed
    assert len(socket.timeouts) == 1


def test_fetch_deadline_does_not_start_another_receive(socket_factory, monkeypatch):
    socket = socket_factory([])
    clock = iter([0.0, 2.0])
    monkeypatch.setattr(capture, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    with pytest.raises(capture.tv.TradingViewSourceError, match="request timed out"):
        capture.fetch(SYMBOL, timeout=1.0)
    assert socket.timeouts == []
    assert socket.closed


@pytest.mark.parametrize("boundary", ["send", "receive", "serialized"])
def test_fetch_rejects_oversized_transcript_at_each_boundary(socket_factory, monkeypatch, boundary):
    done = _frame({"m": "series_completed", "p": []})
    sent_size = sum(len(capture.tv._packet(method, params).encode())
                    for method, params in capture.commands(SYMBOL, "cs_p16fills"))
    limits = {"send": 1, "receive": sent_size, "serialized": sent_size + len(done) + 1}
    socket = socket_factory([done])
    monkeypatch.setattr(capture.tv, "MAX_TRANSCRIPT_BYTES", limits[boundary])
    with pytest.raises(capture.tv.TradingViewSourceError, match="transcript is too large"):
        capture.fetch(SYMBOL)
    assert socket.closed
