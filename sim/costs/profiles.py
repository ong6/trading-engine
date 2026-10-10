"""Shared immutable types for versioned broker-cost profiles."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Callable

from engine.lib.provenance import canonical_sha256


@dataclass(frozen=True)
class RateRow:
    component: str
    rate: float
    effective_from: date
    effective_to: date | None = None

    def applies(self, session_date: date) -> bool:
        return self.effective_from <= session_date and (
            self.effective_to is None or session_date <= self.effective_to
        )

    def as_dict(self) -> dict:
        out = asdict(self)
        out["effective_from"] = self.effective_from.isoformat()
        out["effective_to"] = (
            self.effective_to.isoformat() if self.effective_to else None
        )
        return out


@dataclass(frozen=True)
class FeeBreakdown:
    profile_id: str
    commission: float = 0.0
    exchange_fee: float = 0.0
    clearing_fee: float = 0.0
    pass_through: float = 0.0
    cat_fee: float = 0.0
    sec_fee: float = 0.0
    finra_taf: float = 0.0
    occ_fee: float = 0.0
    orf_fee: float = 0.0
    total_usd: float = 0.0

    def as_dict(self) -> dict:
        return asdict(self)


Calculator = Callable[..., FeeBreakdown]


@dataclass(frozen=True)
class CostProfile:
    id: str
    description: str
    rates: tuple[RateRow, ...]
    verified: dict
    calculator: Calculator = field(repr=False, compare=False)

    @property
    def payload(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "rates": [row.as_dict() for row in self.rates],
            "verified": self.verified,
        }

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.payload)

    def charge(self, **kwargs) -> FeeBreakdown:
        return self.calculator(**kwargs)
