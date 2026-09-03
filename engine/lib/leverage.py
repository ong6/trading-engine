#!/usr/bin/env python
"""Conservative classifier for leveraged / inverse exchange-traded products.

WHY THIS EXISTS
---------------
The M1 trend-template screen ranks by relative strength. A 3x fund is, by
construction, the highest-RS expression of whatever its underlying just did, so
a momentum screen mechanically prefers it over the unlevered name — the screen
is not finding an edge, it is finding the biggest multiplier on the same edge.
Two separate defects follow, and they are independent of each other:

  1. RETURN/RISK DISTORTION. A backtest that holds 3x funds books 3x the move
     and understates the real drawdown, because the daily-reset decay and the
     path dependence never show up in an equal-weight monthly rebalance.
  2. DATA-QUALITY BLOWUP. These products reverse-split constantly (a 3x inverse
     fund in a bull market halves and halves again). The stored `prices` are
     back-adjusted, so an old bar can carry an absurd synthetic close — DRIP
     ranges $35.57 to $83,000 in this store. Orders sized off those prices are
     nonsense and get rejected, stranding cash in the replay.

WHY IT IS DELIBERATELY UNDER-INCLUSIVE
--------------------------------------
A false positive silently deletes a LEGITIMATE company or fund from the
universe, which quietly changes every screen and every benchmark forever. A
false negative leaves one leveraged fund in a 500-name screen. The first error
is much worse, so every rule below is anchored on a token that only a leveraged
or inverse product carries, and the ambiguous tokens are REFUSED BY NAME:

  `Bear`      -> `Build-A-Bear Workshop, Inc.` (BBW) is a real, liquid stock.
                 `Ranger Equity Bear Bear ETF` is an actively-managed short
                 fund, not a leveraged one.
  `Short`     -> 218 universe names contain it; the overwhelming majority are
                 short-DURATION bond funds (`Vanguard Short-Term Bond ETF`).
  `Ultra`     -> `Ultra Clean Holdings`, `Ultragenyx`, `Ultrapar`, `Ultralife`
                 are operating companies. `JPMorgan Ultra-Short Income ETF` and
                 ~30 peers are ultra-short BOND funds. Only the `ProShares
                 Ultra*` family and the `UltraPro` brand are leveraged.
  `Bull`      -> `Simplify Bond Bull ETF`, `TrueShares Quarterly Bull Hedge`.
  bare `NX`   -> `10x Genomics, Inc.` (TXG) is a real, liquid stock whose name
                 matches a naive `\\d+X` multiplier regex.

So a bare multiplier token is only decisive when the name ALSO carries a
direction/leverage word, or the row is flagged as an exchange-traded product
and the multiplier is >= 1.5 (which rules out `IncomeSTKd 1x Bitcoin & 1x Gold
Premium ETF`, a 1x covered-call fund).

USAGE
-----
    from engine.lib import leverage
    leverage.classify("Direxion Daily S&P 500 Bull 3X ETF", etf=True)
    -> Match(rule='multiplier', evidence='3X')

    leverage.flagged_tickers(con)          # set[str] over the `universe` table
    leverage.register_exclusion(con)       # TEMP table `_lev_excluded` for SQL

Nothing here reads or writes the store on import; every DB helper takes a
connection the caller owns.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# tokens
# --------------------------------------------------------------------------- #
# A standalone leverage multiplier: 2X, 3x, -1x, 1.5X, -3X. The lookbehind
# rejects `SPX`/`TSXD`-style embeddings and the lookahead rejects `2xMonthly`
# (which a later rule catches on the word `Leveraged` instead). `.` is in the
# lookbehind so a version-like `1.5x` is read whole, not as a bare `5x`.
_MULTIPLIER = re.compile(r"(?<![A-Za-z0-9.])(-?\d+(?:\.\d+)?)[Xx](?![A-Za-z0-9])")

# Direction / structure words that turn a bare multiplier into a leverage claim.
_CONTEXT = re.compile(
    r"(?i)\b(long|short|bull|bear|inverse|leverag\w*|daily|ultra\w*|target)\b"
)

# `Inverse` has no legitimate use in a fund or company name in this universe —
# all 20 matches are -1x/-2x/-3x products (checked 2026-08-20).
_INVERSE = re.compile(r"(?i)\binverse\b")

# The two leveraged brands whose names do NOT always carry a multiplier token.
# `ProShares Ultra*` is 2x long / 2x short (`UltraShort`) / 3x (`UltraPro`) —
# all 98 matches are leveraged. `UltraPro` is matched separately because
# `UltraPro Short Dow30` (SDOW) and `UltraPro MidCap400` (UMDD) drop the issuer.
_PROSHARES_ULTRA = re.compile(r"(?i)\bproshares\s+ultra")
_ULTRAPRO = re.compile(r"(?i)\bultrapro\b")

# `ProShares Short <underlying>` is the -1x line (SH, PSQ, DOG, RWM, ...). The
# anchor is required: `ProShares Long Online/Short Stores ETF` (CLIX) is a
# long/short equity fund, not an inverse one, and must not match.
_PROSHARES_SHORT = re.compile(r"(?i)^\s*proshares\s+short\b")

# `Leveraged` as a product descriptor (`3x Leveraged ETN`, `-3 Inverse
# Leveraged ETNs`, `Daily Leveraged ETF`) and the `Leverage Shares` issuer.
_LEVERAGE_WORD = re.compile(r"(?i)\bleverage[d]?\b")
# ... except `Leveraged Loan`, which is a CREDIT ASSET CLASS, not a leveraged
# fund. `State Street SPDR S&P Leveraged Loan ETF` (LVLN) is unlevered.
_LEVERAGED_LOAN = re.compile(r"(?i)\bleveraged\s+loan")

# Direxion's Bull/Bear line is leveraged without exception. Kept as its own rule
# so the classifier does not depend on Direxion continuing to print the
# multiplier in the name; `Bull`/`Bear` alone is never enough (see module docs).
_DIREXION = re.compile(r"(?i)\bdirexion\b")
_BULL_BEAR = re.compile(r"(?i)\b(bull|bear)\b")

# Below this absolute multiplier a bare `<n>X ... ETF` is not a leverage claim
# (`IncomeSTKd 1x Bitcoin & 1x Gold Premium ETF` is a 1x income fund). A 1x
# INVERSE fund still gets flagged — it carries `Short`/`Bear`/`Inverse` and so
# clears the context test instead.
_MIN_BARE_MULT = 1.5


@dataclass(frozen=True)
class Match:
    """Why a name was flagged. `rule` is stable and safe to log/aggregate."""
    rule: str
    evidence: str


def classify(name: str | None, etf: bool | None = None) -> Match | None:
    """Return a Match if `name` is a leveraged/inverse product, else None.

    `etf` is the universe's own exchange-traded-product flag. It is used ONLY to
    promote a bare `>=1.5x` multiplier (the `2x Bitcoin ETF` family, which
    carries no direction word). It never flags anything on its own, and a False
    value never suppresses a rule — several leveraged ETNs are filed etf=False
    (`MicroSectors FANG Index -3X Inverse Leveraged ETNs`, FNGD).
    """
    if not name:
        return None

    # 1. Explicit `Inverse` — decisive on its own.
    if _INVERSE.search(name):
        return Match("inverse", "Inverse")

    # 2. `Leveraged` as a descriptor, minus the leveraged-loan asset class.
    if _LEVERAGE_WORD.search(name) and not _LEVERAGED_LOAN.search(name):
        return Match("leveraged_word", "Leverage(d)")

    # 3. The two leveraged brands that can omit the multiplier.
    if _ULTRAPRO.search(name):
        return Match("ultrapro", "UltraPro")
    if _PROSHARES_ULTRA.search(name):
        return Match("proshares_ultra", "ProShares Ultra*")

    # 4. The ProShares -1x line.
    if _PROSHARES_SHORT.search(name):
        return Match("proshares_short", "ProShares Short <underlying>")

    # 5. Direxion Bull/Bear.
    if _DIREXION.search(name) and _BULL_BEAR.search(name):
        return Match("direxion_bull_bear", "Direxion Bull/Bear")

    # 6. A multiplier token, but only with corroboration (see module docs).
    m = _MULTIPLIER.search(name)
    if m:
        mult = abs(float(m.group(1)))
        if _CONTEXT.search(name):
            return Match("multiplier", m.group(0))
        if etf and mult >= _MIN_BARE_MULT:
            return Match("multiplier_etp", m.group(0))

    return None


def is_leveraged(name: str | None, etf: bool | None = None) -> bool:
    return classify(name, etf) is not None


# --------------------------------------------------------------------------- #
# store helpers
# --------------------------------------------------------------------------- #
def flagged_rows(con) -> list[tuple[str, str, bool, bool, str, str]]:
    """Every flagged universe row as (ticker, name, etf, liquid, rule, evidence).

    Sorted by ticker so the audit list is diffable between runs. Reads
    `universe` only — safe on a read-only connection.
    """
    rows = con.execute(
        "SELECT ticker, name, COALESCE(etf, FALSE), COALESCE(liquid, FALSE) "
        "FROM universe ORDER BY ticker"
    ).fetchall()
    out = []
    for tk, name, etf, liq in rows:
        m = classify(name, etf)
        if m:
            out.append((tk, name, bool(etf), bool(liq), m.rule, m.evidence))
    return out


def flagged_tickers(con) -> set[str]:
    """Set of universe tickers the classifier flags. Read-only."""
    return {r[0] for r in flagged_rows(con)}


def register_exclusion(con, table: str = "_lev_excluded") -> int:
    """Materialize the flagged set as a TEMP table for SQL anti-joins.

    The historical screen (`farm/backtest/hist_screen.py`) is one set-based
    DuckDB pass over 15 years, so the exclusion has to be expressible in SQL.
    Classifying in Python and shipping the resulting ticker list keeps ONE
    implementation of the rules — a second regex written in SQL would drift.

    Requires a writable connection (a scratch replay DB); returns the row count.
    """
    tickers = sorted(flagged_tickers(con))
    con.execute(f"CREATE OR REPLACE TEMP TABLE {table} (ticker VARCHAR)")
    if tickers:
        con.executemany(f"INSERT INTO {table} VALUES (?)", [(t,) for t in tickers])
    return len(tickers)


# --------------------------------------------------------------------------- #
# policy
# --------------------------------------------------------------------------- #
# The screen's universe policy. `all` is the DEFAULT and is what every screen
# stored before 2026-08-20 was produced under, so old rows read back correctly.
# Turning the exclusion on changes which names pass, which changes
# `ew_benchmark`, which is the yardstick every other book is scored against —
# a versioned decision, never a silent default.
POLICY_ALL = "all"
POLICY_EX_LEVERAGED = "ex-leveraged"
POLICIES = (POLICY_ALL, POLICY_EX_LEVERAGED)
DEFAULT_POLICY = POLICY_ALL

# Env override so the nightly/farm can set the policy without a code change.
POLICY_ENV = "TRADING_ENGINE_UNIVERSE_POLICY"


def resolve_policy(cli_value: str | None = None) -> str:
    """CLI flag wins, then the env var, then `all`. Raises on an unknown name —
    a typo must not silently fall back to the permissive policy."""
    import os
    val = cli_value or os.environ.get(POLICY_ENV) or DEFAULT_POLICY
    val = val.strip()
    if val not in POLICIES:
        raise SystemExit(
            f"[leverage] unknown universe policy {val!r} — expected one of "
            f"{', '.join(POLICIES)}"
        )
    return val
