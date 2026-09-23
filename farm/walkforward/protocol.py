#!/usr/bin/env python
"""The frozen walk-forward protocol — fold geometry and the exclusion list.

§12.3 mandates "nightly walk-forward re-validation of every active rule" under
the anti-overfitting protocol but does not pin the window lengths. The choices
below are registered HERE, in one place, before any evidence exists, and every
report prints them.

  D-WF1  Rolling-origin walk-forward, TRAIN 24 months → VALIDATE 12 months,
         stepped by the validate length so the validate windows are CONTIGUOUS
         and NON-OVERLAPPING and tile the recent past. 10 folds.

         Why these numbers:
         * 24-month train is long enough to contain both a drawdown and a
           recovery in most of the last decade, and short enough that the
           in-sample reference is the regime the book is actually in.
         * 12-month validate gives a MONTHLY-cadence book (dual_momentum,
           sector_momentum, low_vol, high_52wk, ew_benchmark) twelve real
           decisions per fold. Anything shorter and half the league is judged
           on 2-3 rebalances, which is noise.
         * Step = validate length is what makes each validate window fresh
           data: no session appears in two validate windows, so the ten
           validate results are ten disjoint out-of-sample measurements.
         * 10 folds ≈ 10 years of validate coverage. The original six-fold
           protocol was expanded prospectively on 2026-08-18 because one
           COVID/recovery window dominated every momentum mean; the registered
           rationale is recorded beside N_FOLDS below. More folds remains a
           params override, not a redesign.

  D-WF2  Each fold is an INDEPENDENT replay that starts fresh at the league's
         reference notional at its train start. The alternative (one long
         continuous replay sliced into folds) is cheaper but lets a book that
         halved its equity in fold 1 trade fold 6 at half size, where integer
         share rounding and the fill model's liquidity guard behave differently.
         A re-validation must measure the RULE at its designed size, not the
         archaeology of an account opened ten years ago.

  D-WF3  The window anchor is the LATEST session in the store, not league
         inception. This is a weekly re-validation feeding a weekly review, so
         it must include the most recent data. The newest validate window
         therefore overlaps the live league's forward record by however many
         sessions have passed since 2026-07-17; the reports label that overlap
         instead of hiding it, and it is a shadow of the live book, not extra
         out-of-sample evidence.

  D-WF4  The replayed config is the row in the LIVE `portfolios` table, not
         `sim/strategies/configs.py`. `portfolios.config` is the JSON frozen at
         the book's creation and is what `league.generate_all` actually reads,
         so re-validating anything else would re-validate a rule the league is
         not trading.

  D-WF5  There is no parameter fitting anywhere in this workload. The train
         window is a MEASUREMENT baseline (what the rule did on the sessions
         immediately before), not a search. That is deliberate: §12.3 says the
         farm exists "to kill bad ideas cheaply, not to find a lucky
         parameter". Parameter grids are item 13(b) and stay separate.
"""
from __future__ import annotations

import calendar as _cal
from dataclasses import asdict, dataclass
from datetime import date

# --------------------------------------------------------------------------- #
# frozen protocol constants (D-WF1)
# --------------------------------------------------------------------------- #
TRAIN_MONTHS = 24
VALIDATE_MONTHS = 12
STEP_MONTHS = 12          # == VALIDATE_MONTHS ⇒ disjoint validate windows
# 2026-08-18: 6 -> 10. NOT a fishing expedition; the reason is on the record.
# The 6-fold grid showed every momentum book's entire excess living in ONE fold
# (2018-08 -> 2021-08, COVID crash + recovery): drop that single window and
# template_top5 goes +32.9% -> -17.5%, template_top10_banded +11.5% -> -11.9%,
# momo_stopped +4.8% -> -12.4%. A protocol whose verdict can be flipped by one
# of six windows is measuring the window, not the rule. 10 folds reaches back to
# 2014 and costs 15% of the universe (2,827 -> 2,391 tickers with the required
# history) -- affordable now that the grid runs parallel (engine/queue_runner.py
# --jobs). The change is DIRECTIONAL and pre-committed: more evidence, never
# less, and it was chosen before re-running anything. Folds whose validate
# window opens at or before a book's data floor are still dropped and disclosed
# rather than silently shortened.
N_FOLDS = 10

# Books that cannot be walk-forwarded, with the reason printed in every report.
# Same shape (and the same two first entries) as the historical-backtest farm's
# exclusion list — a book is left OUT and said so, never faked to fill a row.
#
# KEYED BY CONFIG_ID, WHICH IS WHY `excluded_reason()` BELOW ALSO CHECKS THE
# STRATEGY. Every reason here is a property of the STRATEGY, not of one config:
# "no historical earnings dates" is true of anything running `pead_ear`'s rule.
# A config-keyed list therefore cannot cover a strategy's twins or a sweep's
# candidates by construction — and it did not. `earnings_context_pead`, the
# retired AI twin of `pead_ear`, ran the identical excluded strategy, was absent
# from this dict, replayed to 0 fills in all six then-current folds, and was published in the
# 2026-08-17 walk-forward summary as `+0.00% mean validate / -30.55% vs EW /
# REVIEW`. The inert guard in runner.py now catches the consequence; this
# catches the cause, one replay earlier and for free.
EXCLUDED: dict[str, str] = {
    "pead_ear": "no historical earnings dates — `earnings_calendar` spans only "
                "2026-04→2026-10, so the entry signal cannot be computed. "
                "Forward record only.",
    "discretionary": "human book — orders come from UI tickets, not code.",
    "macro_composite": "its inputs are point-in-time by `fetch_as_of`, and the "
                       "production `macro_signals` backfill stamps "
                       "fetch_as_of = today (honest: we did not have those "
                       "series in 2019). A historical replay therefore sees an "
                       "empty signal table and the book is inert, not wrong. "
                       "Needs a labelled `--pit-lag` reconstruction backfill "
                       "before it can be walk-forwarded.",
}

# The same reasons, reachable by strategy so that ANY config running the rule is
# covered — twins, sweep candidates, and configs nobody has written yet.
EXCLUDED_STRATEGIES: dict[str, str] = {
    "agent_only_policy": "agent decisions are external retained inputs, not a deterministic "
                         "historical strategy generator. Forward evaluation only.",
    "pead_ear": EXCLUDED["pead_ear"],
    "discretionary": EXCLUDED["discretionary"],
    "macro_composite": EXCLUDED["macro_composite"],
}


def excluded_reason(config_id: str, strategy: str | None = None) -> str | None:
    """Why this book cannot be walk-forwarded, or None.

    Checks the config_id first so a one-off exclusion can name a single book,
    then falls back to the strategy so every config of an excluded rule is
    covered without anyone having to remember to list it.
    """
    hit = EXCLUDED.get(config_id)
    if hit is not None:
        return hit
    if strategy is None:
        return None
    hit = EXCLUDED_STRATEGIES.get(strategy)
    if hit is None:
        return None
    return f"{hit} (excluded via strategy `{strategy}`)"


# --------------------------------------------------------------------------- #
# fold geometry
# --------------------------------------------------------------------------- #
def minus_months(d: date, months: int) -> date:
    y, m = d.year, d.month - months
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, min(d.day, _cal.monthrange(y, m)[1]))


@dataclass(frozen=True)
class Fold:
    """One walk-forward fold, in CALENDAR dates (sessions resolved later).

    The replay runs `train_start → validate_end` in one pass and the equity
    curve is split at `split_date`:

        train    (train_start, split_date]
        validate (split_date,  validate_end]

    `split_date`'s equity row is the base of the validate slice, so the two
    windows abut exactly and no session's return is counted twice.
    """
    index: int            # 1 = oldest fold, N = newest
    train_start: date
    split_date: date
    validate_end: date

    def as_dict(self) -> dict:
        d = asdict(self)
        for k in ("train_start", "split_date", "validate_end"):
            d[k] = d[k].isoformat()
        return d


def make_folds(anchor: date, *, train_months: int = TRAIN_MONTHS,
               validate_months: int = VALIDATE_MONTHS,
               step_months: int = STEP_MONTHS,
               n_folds: int = N_FOLDS) -> list[Fold]:
    """The fold grid, oldest first, ending at `anchor`.

    Boundaries walk backwards from the anchor in `step_months` strides; each
    fold's validate window is the stride that ENDS at its boundary, and its
    train window is the `train_months` immediately before that window opens.
    """
    if n_folds < 1:
        raise ValueError("n_folds must be >= 1")
    folds: list[Fold] = []
    for k in range(n_folds):
        validate_end = minus_months(anchor, k * step_months)
        split_date = minus_months(validate_end, validate_months)
        train_start = minus_months(split_date, train_months)
        folds.append(Fold(index=n_folds - k, train_start=train_start,
                          split_date=split_date, validate_end=validate_end))
    folds.reverse()
    return folds


def protocol_dict(anchor: date, folds: list[Fold], *,
                  train_months: int = TRAIN_MONTHS,
                  validate_months: int = VALIDATE_MONTHS,
                  step_months: int = STEP_MONTHS) -> dict:
    return {
        "train_months": train_months,
        "validate_months": validate_months,
        "step_months": step_months,
        "n_folds": len(folds),
        "anchor": anchor.isoformat(),
        "folds": [f.as_dict() for f in folds],
    }


def describe(anchor: date, folds: list[Fold], *,
             train_months: int = TRAIN_MONTHS,
             validate_months: int = VALIDATE_MONTHS,
             step_months: int = STEP_MONTHS) -> str:
    head = (f"train {train_months}mo → validate {validate_months}mo, "
            f"step {step_months}mo, {len(folds)} folds, anchored {anchor}")
    rows = [f"  fold {f.index}: train {f.train_start} → {f.split_date} | "
            f"validate {f.split_date} → {f.validate_end}" for f in folds]
    return "\n".join([head] + rows)


if __name__ == "__main__":  # pragma: no cover - quick inspection
    import argparse
    ap = argparse.ArgumentParser(description="Print the walk-forward fold grid.")
    ap.add_argument("--anchor", default=date.today().isoformat())
    ap.add_argument("--folds", type=int, default=N_FOLDS)
    a = ap.parse_args()
    anc = date.fromisoformat(a.anchor)
    print(describe(anc, make_folds(anc, n_folds=a.folds)))
