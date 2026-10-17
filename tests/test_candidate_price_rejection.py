"""Invalid retained prices are an explicit read failure, never chart/ticket data."""

import asyncio
import json
from datetime import date

import pytest

from server import main
from tests.conftest import insert_bars
from tests.read_model_helpers import liquid_universe
from tests.test_server_routes import _request_messages


@pytest.mark.parametrize(
    ("field", "value", "reason", "public_value"),
    [
        ("high", 9.0, "public candidate OHLC geometry is invalid", 9.0),
        ("open", 0.0, "public candidate open is invalid", 0.0),
        ("low", float("nan"), "public candidate low is invalid", None),
    ],
)
def test_candidate_route_reports_invalid_retained_bar(con, monkeypatch, field, value, reason, public_value):
    day = date(2026, 10, 15)
    # SPY establishes market breadth independently of the invalid candidate bar.
    liquid_universe(con, ["SPY"])
    for ticker in ("SPY", "BAD"):
        insert_bars(con, ticker, [day], open_=10.0, high=11.0, low=9.5, close=10.0, volume=100)
    con.execute(f"UPDATE prices SET {field} = ? WHERE ticker = 'BAD'", [value])
    before = con.execute("SELECT * FROM prices ORDER BY ticker").fetchall()
    monkeypatch.setattr(main, "read_con", con.cursor)

    messages = asyncio.run(_request_messages("/candidates/bad"))
    assert next(m["status"] for m in messages if m["type"] == "http.response.start") == 422
    response = json.loads(b"".join(m.get("body", b"") for m in messages))
    bar = response["detail"]["bars"][0]
    assert response["detail"]["code"] == "inadmissible_price_data"
    assert response["detail"]["ticker"] == "BAD"
    assert bar["date"] == day.isoformat()
    assert bar["reason"] == reason
    assert bar[field] == public_value
    assert set(bar) == {"date", "open", "high", "low", "close", "reason"}
    after = con.execute("SELECT * FROM prices ORDER BY ticker").fetchall()
    assert repr(after) == repr(before)

    # An unrelated invalid ticker does not poison the valid candidate or sizing context.
    for path in ("/candidates/SPY", "/tickets/context"):
        messages = asyncio.run(_request_messages(path))
        assert next(m["status"] for m in messages if m["type"] == "http.response.start") == 200
