"""Exact named study-cost profiles layered over ``sim.execution`` identities."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

from engine.lib.provenance import canonical_sha256
from sim import costs as engine_costs
from sim import execution
from sim.execution import ExecutionProfile


@dataclass(frozen=True)
class StudyCostProfile:
    execution: ExecutionProfile
    family: str
    commission: str
    pass_through_per_share: float = 0.0
    sec_rate: float = 0.0000028
    taf_per_share: float = 0.000166
    auction_allowance_rate: float = 0.0
    taker_rate: float = 0.0
    funding_from_data: bool = False
    verified_against_fills: bool = False
    engine_profile: str | None = None

    @property
    def id(self) -> str:
        return self.execution.id

    @property
    def payload(self) -> dict:
        if self.engine_profile:
            return engine_costs.resolve_profile(self.engine_profile).payload
        if self.family == "sim_execution":
            return self.execution.as_dict()
        return {"execution": self.execution.as_dict(), "family": self.family,
                "commission": self.commission,
                "pass_through_per_share": self.pass_through_per_share,
                "sec_rate": self.sec_rate, "taf_per_share": self.taf_per_share,
                "auction_allowance_rate": self.auction_allowance_rate,
                "taker_rate": self.taker_rate, "funding_from_data": self.funding_from_data,
                "verified_against_fills": self.verified_against_fills}

    @property
    def sha256(self) -> str:
        return canonical_sha256(self.payload)


def _base(profile_id: str, description: str) -> ExecutionProfile:
    return ExecutionProfile(
        id=profile_id, description=description, spread_rule="study_exact_v1",
        fixed_adverse_bps=0.0, max_participation=1.0)


IBKR_TIERED_AUCTION_V1 = StudyCostProfile(
    _base("ibkr_tiered_auction_v1", "IBKR tiered auction schedule, unverified"),
    "equity", "tiered", pass_through_per_share=0.0020, auction_allowance_rate=0.0002)
IBKR_FIXED_V1 = StudyCostProfile(
    _base("ibkr_fixed_v1", "IBKR fixed schedule, unverified"),
    "equity", "fixed", auction_allowance_rate=0.0002)
BINANCE_SPOT_BASE_V1 = StudyCostProfile(
    _base("binance_spot_base_v1", "Binance spot base schedule, unverified"),
    "crypto", "none", sec_rate=0, taf_per_share=0, taker_rate=0.0010)
BINANCE_PERP_BASE_V1 = StudyCostProfile(
    _base("binance_perp_base_v1", "Binance perpetual base schedule, unverified"),
    "crypto", "none", sec_rate=0, taf_per_share=0, taker_rate=0.0005,
    funding_from_data=True)
BASELINE_V1 = StudyCostProfile(
    execution.BASELINE, "sim_execution", "delegated", verified_against_fills=False)
IBKR_PRO_TIERED_V1 = StudyCostProfile(
    _base("ibkr_pro_tiered_v1", "Verified effective-dated IBKR Pro Tiered schedule"),
    "engine_costs", "delegated", verified_against_fills=False,
    engine_profile="ibkr_pro_tiered_v1")

PROFILES = {profile.id: profile for profile in (
    BASELINE_V1, IBKR_TIERED_AUCTION_V1, IBKR_FIXED_V1,
    BINANCE_SPOT_BASE_V1, BINANCE_PERP_BASE_V1, IBKR_PRO_TIERED_V1)}


@dataclass(frozen=True)
class CostBreakdown:
    profile_id: str
    value: float
    shares: float
    commission: float
    pass_through: float
    sec: float
    taf: float
    auction_allowance: float
    taker: float
    slippage: float
    funding: float
    total: float

    def as_dict(self) -> dict:
        return asdict(self)


def resolve(profile: str | StudyCostProfile) -> StudyCostProfile:
    if isinstance(profile, StudyCostProfile):
        return profile
    try:
        return PROFILES[profile]
    except KeyError as exc:
        raise ValueError(f"unknown study cost profile {profile!r}") from exc


def calculate(profile: str | StudyCostProfile, *, side: str, notional: float,
              fill_price: float, mdv60: float | None = None,
              funding_rate: float = 0.0, session_date=None,
              fill_kind: str = "moo", instrument="stock",
              fractional_shares: bool = False) -> CostBreakdown:
    """Return exact per-side dollar costs; funding_rate is signed for the position."""
    selected = resolve(profile)
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if not all(math.isfinite(value) and value > 0 for value in (notional, fill_price)):
        raise ValueError("notional and fill price must be positive and finite")
    if not math.isfinite(funding_rate) or (funding_rate and not selected.funding_from_data):
        raise ValueError("funding is accepted only by a funding-enabled profile")
    value = float(notional)
    shares = value / fill_price
    if selected.engine_profile:
        if session_date is None:
            raise ValueError("session_date is required by effective-dated cost profiles")
        charged_shares = shares if fractional_shares else math.floor(shares)
        if charged_shares <= 0:
            raise ValueError("whole-share cost calculation has zero executable shares")
        charged = engine_costs.charge(
            selected.engine_profile, side=side, qty=charged_shares, price=fill_price,
            fill_kind=fill_kind, instrument=instrument, session_date=session_date,
        )
        return CostBreakdown(
            selected.id, charged_shares * fill_price, charged_shares,
            charged.commission, charged.pass_through,
            charged.sec_fee, charged.finra_taf,
            charged.exchange_fee + charged.clearing_fee + charged.cat_fee
            + charged.occ_fee + charged.orf_fee,
            0.0, 0.0, 0.0, charged.total_usd,
        )
    if selected.family == "sim_execution":
        components = execution.cost_components(
            selected.execution, side=side, qty=shares, open_px=fill_price,
            median_dollar_volume=mdv60)
        delegated = value * components["total_bps"] / 10_000
        return CostBreakdown(
            selected.id, value, shares, components["commission_dollars"],
            0.0, 0.0, 0.0, 0.0, 0.0,
            value * components["market_bps"] / 10_000, 0.0, delegated)
    commission = pass_through = auction = taker = slippage = 0.0
    if selected.commission == "tiered":
        commission = min(max(0.35, 0.0035 * shares), 0.01 * value)
        pass_through = selected.pass_through_per_share * shares
    elif selected.commission == "fixed":
        commission = max(1.00, 0.005 * shares)
    if selected.family == "equity":
        auction = selected.auction_allowance_rate * value
    else:
        if mdv60 is None or not math.isfinite(mdv60) or mdv60 < 5_000_000:
            raise ValueError("crypto cost profiles require MDV60 >= USD 5M")
        slippage = value * (0.0005 if mdv60 >= 50_000_000 else 0.0015)
        taker = selected.taker_rate * value
    sec = selected.sec_rate * value if side == "sell" else 0.0
    taf = selected.taf_per_share * shares if side == "sell" else 0.0
    funding = value * funding_rate if selected.funding_from_data else 0.0
    total = commission + pass_through + sec + taf + auction + taker + slippage + funding
    return CostBreakdown(selected.id, value, shares, commission, pass_through, sec, taf,
                         auction, taker, slippage, funding, total)


@dataclass(frozen=True)
class CostSelection:
    primary: str
    sensitivities: tuple[str, ...]

    def __post_init__(self) -> None:
        resolve(self.primary)
        if not self.sensitivities or self.primary in self.sensitivities:
            raise ValueError("at least one distinct harsher sensitivity is required")
        if len(set(self.sensitivities)) != len(self.sensitivities):
            raise ValueError("sensitivity profiles must be unique")
        for profile in self.sensitivities:
            resolve(profile)

    @property
    def hashes(self) -> dict[str, str]:
        return {name: resolve(name).sha256 for name in (self.primary, *self.sensitivities)}

    def require_harsher(self, total_costs: dict[str, float]) -> None:
        primary = total_costs.get(self.primary)
        if primary is None or any(total_costs.get(name, -math.inf) <= primary
                                  for name in self.sensitivities):
            raise ValueError("each sensitivity must cost more than primary on the run")
