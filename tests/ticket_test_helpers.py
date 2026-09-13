"""Shared setup for discretionary-ticket contract and mutation tests."""

from server import tickets


def liquid_universe(con, *tickers):
    con.execute(
        "CREATE TABLE universe "
        "(ticker VARCHAR PRIMARY KEY, active BOOLEAN, liquid BOOLEAN)"
    )
    con.executemany(
        "INSERT INTO universe VALUES (?, TRUE, TRUE)",
        [(ticker,) for ticker in tickers],
    )


def passing_risk(monkeypatch):
    gates = [{"name": "test_gate", "status": "pass", "detail": "ok"}]
    monkeypatch.setattr(tickets.risk, "evaluate_gates", lambda con, ticket, **kwargs: gates)
    monkeypatch.setattr(tickets.risk, "is_allowed", lambda actual, ticket: (True, []))
    return gates


def buy_body(**overrides):
    body = {
        "ticker": "aaa",
        "side": "buy",
        "qty": 2,
        "entry_ref": 10,
        "stop": 9,
        "target": 12,
        "playbook": "experiment",
        "emotion": "calm",
        "notes": "test",
        "acknowledge_earnings": True,
        "override_regime": False,
        "override_reason": None,
    }
    body.update(overrides)
    return body
