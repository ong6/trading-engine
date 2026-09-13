"""HTTP adapter tests for discretionary ticket mutations."""

import pytest
from fastapi import HTTPException

from server import main, ticket_contract


def test_create_route_maps_ticket_error_and_closes_connection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    monkeypatch.setattr(main, "write_con", lambda: con)
    monkeypatch.setattr(
        main.tickets,
        "create",
        lambda actual, body: (_ for _ in ()).throw(
            ticket_contract.TicketError(400, "bad ticket")
        ),
    )

    with pytest.raises(HTTPException, match="bad ticket") as exc_info:
        main.create_ticket(ticket_contract.TicketRequest(ticker="AAA", qty=1))

    assert exc_info.value.status_code == 400
    assert con.closed is True


def test_cancel_route_maps_ticket_error_and_closes_connection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    con = Connection()
    monkeypatch.setattr(main, "write_con", lambda: con)
    monkeypatch.setattr(
        main.tickets,
        "cancel",
        lambda actual, ticket_id: (_ for _ in ()).throw(
            ticket_contract.TicketError(409, "not pending")
        ),
    )

    with pytest.raises(HTTPException, match="not pending") as exc_info:
        main.cancel_ticket(7)

    assert exc_info.value.status_code == 409
    assert con.closed is True
