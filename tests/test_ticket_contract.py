"""Discretionary ticket request shape and normalization tests."""

from dataclasses import asdict

import pytest
from pydantic import TypeAdapter

from server import main, ticket_contract
from tests.ticket_test_helpers import buy_body


@pytest.mark.parametrize(
    ("field", "value", "detail"),
    [
        ("side", "hold", "side must be 'buy' or 'sell'"),
        ("side", 1, "side must be 'buy' or 'sell'"),
        ("qty", True, "qty must be a number"),
        ("qty", float("inf"), "qty must be a positive number"),
        ("entry_ref", "bad", "entry_ref must be a positive finite number"),
        ("stop", 0, "stop must be a positive finite number"),
        ("target", -1, "target must be a positive finite number"),
        ("acknowledge_earnings", "yes", "acknowledge_earnings must be a boolean"),
    ],
)
def test_ticket_contract_rejects_malformed_fields(field, value, detail):
    with pytest.raises(ticket_contract.TicketError, match=detail) as exc_info:
        ticket_contract.normalize(buy_body(**{field: value}))

    assert exc_info.value.status_code == 400


def test_ticket_contract_rejects_unknown_fields():
    with pytest.raises(
        ticket_contract.TicketError, match=r"unknown ticket field\(s\): qtyy"
    ) as exc_info:
        ticket_contract.normalize(buy_body(qtyy=2))

    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    ("field", "limit"),
    [
        ("ticker", ticket_contract.TICKER_MAX_CHARS),
        ("playbook", ticket_contract.PLAYBOOK_MAX_CHARS),
        ("emotion", ticket_contract.EMOTION_MAX_CHARS),
        ("notes", ticket_contract.NOTES_MAX_CHARS),
        ("override_reason", ticket_contract.OVERRIDE_REASON_MAX_CHARS),
    ],
)
def test_ticket_contract_rejects_oversized_text_fields(field, limit):
    with pytest.raises(
        ticket_contract.TicketError,
        match=rf"{field} must be at most {limit} characters",
    ) as exc_info:
        ticket_contract.normalize(buy_body(**{field: "x" * (limit + 1)}))

    assert exc_info.value.status_code == 400


def test_ticket_contract_accepts_text_fields_at_their_limits():
    body = buy_body(
        ticker="a" * ticket_contract.TICKER_MAX_CHARS,
        playbook="p" * ticket_contract.PLAYBOOK_MAX_CHARS,
        emotion="e" * ticket_contract.EMOTION_MAX_CHARS,
        notes="n" * ticket_contract.NOTES_MAX_CHARS,
        override_reason="r" * ticket_contract.OVERRIDE_REASON_MAX_CHARS,
    )

    normalized = ticket_contract.normalize(body)

    assert normalized["ticker"] == body["ticker"].upper()
    for field in ("playbook", "emotion", "notes", "override_reason"):
        assert normalized[field] == body[field]


def test_ticket_http_schema_is_closed_and_declares_fields():
    schema_ref = main.app.openapi()["paths"]["/tickets"]["post"]["requestBody"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    schema = main.app.openapi()["components"]["schemas"][schema_ref.rsplit("/", 1)[-1]]

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"ticker", "qty"}
    assert set(schema["properties"]) == ticket_contract.TICKET_FIELDS
    assert schema["properties"]["side"]["enum"] == ["buy", "sell"]
    assert schema["properties"]["ticker"]["maxLength"] == ticket_contract.TICKER_MAX_CHARS
    for field, limit in (
        ("playbook", ticket_contract.PLAYBOOK_MAX_CHARS),
        ("emotion", ticket_contract.EMOTION_MAX_CHARS),
        ("notes", ticket_contract.NOTES_MAX_CHARS),
        ("override_reason", ticket_contract.OVERRIDE_REASON_MAX_CHARS),
    ):
        assert schema["properties"][field]["anyOf"][0]["maxLength"] == limit


def test_ticket_http_parser_enforces_declared_text_limits():
    adapter = TypeAdapter(ticket_contract.TicketRequest)

    with pytest.raises(ValueError, match="String should have at most 32 characters"):
        adapter.validate_python(buy_body(ticker="x" * 33))


def test_ticket_http_parsing_preserves_scalar_types_for_domain_validation():
    adapter = TypeAdapter(ticket_contract.TicketRequest)
    parsed = adapter.validate_python(buy_body(qty=True))

    assert parsed.qty is True
    with pytest.raises(ticket_contract.TicketError, match="qty must be a number"):
        ticket_contract.normalize(asdict(parsed))
