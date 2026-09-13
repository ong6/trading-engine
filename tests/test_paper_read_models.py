"""Tests for the discretionary ticket-context read model."""

from datetime import date, datetime

import pytest

from server import market_read_models, paper_read_models
from tests.read_model_helpers import portfolio


def test_ticket_context_distinguishes_new_active_and_inactive_books(con, monkeypatch):
    unavailable = paper_read_models.ticket_context(con)
    assert unavailable["status"] == "unavailable"
    assert unavailable["as_of"] is None
    assert unavailable["equity"] is None

    day = date(2026, 9, 4)
    monkeypatch.setattr(market_read_models, "latest_prices_date", lambda _con: day)
    new = paper_read_models.ticket_context(con)
    assert new == {
        "portfolio_id": "discretionary",
        "status": "not-created",
        "as_of": day,
        "equity": 39_000.0,
        "equity_source": "configured_initial_cash",
        "risk_pct": 0.01,
        "experiment_max_pct": 0.0025,
        "max_open_r": 4.0,
    }

    portfolio(con, "discretionary")
    active = paper_read_models.ticket_context(con)
    assert active["status"] == "active"
    assert active["equity"] == pytest.approx(39_000.0)
    assert active["equity_source"] == "current_discretionary_equity"

    for unusable_equity in (0.0, -1.0, float("nan"), float("inf")):
        monkeypatch.setattr(
            paper_read_models.risk_book,
            "disc_state",
            lambda _con, *, as_of, value=unusable_equity: {"equity": value},
        )
        unusable = paper_read_models.ticket_context(con)
        assert unusable["status"] == "inactive"
        assert unusable["as_of"] == day
        assert unusable["equity"] is None
        assert unusable["equity_source"] is None

    con.execute("UPDATE portfolios SET active = FALSE WHERE id = 'discretionary'")
    inactive = paper_read_models.ticket_context(con)
    assert inactive["status"] == "inactive"
    assert inactive["equity"] is None
    assert inactive["equity_source"] is None


def test_ticket_context_without_market_date_is_unavailable_for_inactive_book(con):
    portfolio(con, "discretionary", active=False)

    result = paper_read_models.ticket_context(con)

    assert result["status"] == "unavailable"
    assert result["as_of"] is None
    assert result["equity"] is None
    assert result["equity_source"] is None


def test_ticket_context_rejects_non_date_as_of(con, monkeypatch):
    monkeypatch.setattr(market_read_models, "latest_prices_date", lambda _con: datetime(2026, 9, 4))

    with pytest.raises(ValueError, match="ticket-context as-of date"):
        paper_read_models.ticket_context(con)


@pytest.mark.parametrize(
    ("target", "attribute", "value", "message"),
    [
        ("risk_book", "RISK_PCT", True, "risk percent"),
        ("risk_book", "RISK_PCT", 1.1, "risk limits"),
        ("risk", "EXPERIMENT_MAX", 0.0, "experiment limit"),
        ("risk", "EXPERIMENT_MAX", 0.02, "risk limits"),
        ("risk", "MAX_OPEN_R", float("inf"), "open risk"),
    ],
)
def test_ticket_context_rejects_invalid_risk_limits(
    con, monkeypatch, target, attribute, value, message
):
    module = getattr(paper_read_models, target)
    monkeypatch.setattr(module, attribute, value)

    with pytest.raises(ValueError, match=message):
        paper_read_models.ticket_context(con)


def test_ticket_context_rejects_invalid_configured_initial_cash(con, monkeypatch):
    monkeypatch.setattr(paper_read_models, "INITIAL_CASH", 0.0)
    monkeypatch.setattr(market_read_models, "latest_prices_date", lambda _con: date(2026, 9, 4))

    with pytest.raises(ValueError, match="ticket-context equity"):
        paper_read_models.ticket_context(con)


def test_ticket_context_rejects_nonboolean_portfolio_state(con, monkeypatch):
    monkeypatch.setattr(paper_read_models, "_portfolio_row", lambda _con: (None,))
    monkeypatch.setattr(market_read_models, "latest_prices_date", lambda _con: date(2026, 9, 4))

    with pytest.raises(ValueError, match="portfolio state"):
        paper_read_models.ticket_context(con)


def test_ticket_context_final_projection_requires_exact_fields():
    payload = {
        "portfolio_id": "discretionary",
        "status": "active",
        "as_of": date(2026, 9, 4),
        "equity": 40_000.0,
        "equity_source": "current_discretionary_equity",
        "risk_pct": 0.01,
        "experiment_max_pct": 0.0025,
        "max_open_r": 4.0,
    }

    paper_read_models._validate_ticket_context_projection(payload)

    with pytest.raises(ValueError, match="projection shape"):
        paper_read_models._validate_ticket_context_projection({**payload, "internal": True})
    missing = dict(payload)
    missing.pop("max_open_r")
    with pytest.raises(ValueError, match="projection shape"):
        paper_read_models._validate_ticket_context_projection(missing)


def test_ticket_context_final_projection_requires_status_date_coherence():
    payload = {
        "portfolio_id": "discretionary",
        "status": "inactive",
        "as_of": None,
        "equity": None,
        "equity_source": None,
        "risk_pct": 0.01,
        "experiment_max_pct": 0.0025,
        "max_open_r": 4.0,
    }

    with pytest.raises(ValueError, match="ticket-context as-of date"):
        paper_read_models._validate_ticket_context_projection(payload)

    payload["status"] = "unavailable"
    paper_read_models._validate_ticket_context_projection(payload)
