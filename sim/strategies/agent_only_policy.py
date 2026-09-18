"""No-op strategy for an active, separately attributed agent-only paper book.

Orders for this book come only from the authenticated P5 decision consumer.
Keeping the book active lets the existing simulator own fills, corporate
actions, marks, settlement, and recovery without giving algorithm generation
an alternate path into the account.
"""
from __future__ import annotations

from .base import PortfolioView, Strategy


class AgentOnlyPolicy(Strategy):
    cadence = "daily"

    def generate_orders(self, con, pf: PortfolioView, as_of):
        return []
