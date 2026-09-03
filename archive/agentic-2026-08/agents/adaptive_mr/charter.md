# Charter — `adaptive_mr` (AI book 2 of 5)

**FROZEN 2026-08-04.** Registered before any evidence exists and not edited
afterwards. Amending a bound means killing this book and registering a new one
with a new id and a new 26-week clock.

## Objective

Run `mr_overlay`'s algorithm — daily mean-reversion entries on trend-template
passers, exit on a close above the prior high or a time stop — and let a weekly
session move five parameters inside hard bounds, from the book's own trade
autopsies and its walk-forward record. The agent never places a trade and never
names a stock.

The question it exists to answer: **does a bounded weekly parameter adjustment,
justified by MAE/MFE and hold-time evidence, beat leaving the parameters alone?**
The honest prior is that it does not. That is why the twin exists.

## Adjustable parameters and their hard bounds

Bounds are ±50% around the live book's registered values, rounded to sensible
integers, then floored/capped where the parameter has a structural meaning.

| Param | Start | Min | Max | Why the bound |
|---|---|---|---|---|
| `rsi_max` | 10 | 5 | 15 | ±50%. Below 5, RSI(2) almost never triggers and the book goes inert; above 15 it stops being an oversold entry |
| `down_closes` | 3 | 2 | 4 | ±50% rounded to integers. 1 would drop the consecutive-decline requirement entirely — that is a different strategy, not a tuning |
| `weight` | 0.10 | 0.05 | 0.15 | ±50%. With `max_concurrent` at its own cap, 0.15×8 = 120% would be levered — the validator's cross-check rejects any pair whose product exceeds 1.00 |
| `max_concurrent` | 5 | 3 | 8 | ±50% rounded (2.5→3, 7.5→8) |
| `time_stop` | 10 | 5 | 15 | ±50%. This is the parameter the 2026-07-28 calendar-bug entry showed the book is most sensitive to, so it is in scope — but a 5-session floor keeps it a *time* stop rather than a same-week exit |

**Session limits:** at most **2** parameters changed per session, each by at most
**25%** of its current value. A tuner that can jump a parameter to its bound in
one week is not tuning, it is searching — and a search over live forward data is
the curve-fitting this whole design exists to prevent.

<!-- BOUNDS -->
```json
{
  "book": "adaptive_mr",
  "twin": "adaptive_mr_frozen",
  "kind": "tuner",
  "cadence": "weekly",
  "max_changes_per_session": 2,
  "max_relative_step": 0.25,
  "params": {
    "rsi_max":        {"type": "number",  "min": 5,    "max": 15,   "start": 10},
    "down_closes":    {"type": "integer", "min": 2,    "max": 4,    "start": 3},
    "weight":         {"type": "number",  "min": 0.05, "max": 0.15, "start": 0.10},
    "max_concurrent": {"type": "integer", "min": 3,    "max": 8,    "start": 5},
    "time_stop":      {"type": "integer", "min": 5,    "max": 15,   "start": 10}
  },
  "cross_checks": [
    {"kind": "product_max", "params": ["weight", "max_concurrent"], "max": 1.0,
     "why": "slot weight x concurrency must not exceed 100% of equity"}
  ]
}
```

## Cadence

**Sunday 10:30 UTC**, after the 06:00 UTC walk-forward grid has drained (~3h), so
the session reads a *fresh* out-of-sample re-validation rather than last week's.
One session per week, one proposal per session. No mid-week adjustments — a book
whose parameters can move on a bad Tuesday is a book being managed by its
drawdown.

## Evidence the wrapper hands the session (nothing else; the model has zero tools)

1. This charter and `agents/adaptive_mr/lessons.md`.
2. The applied+rejected change history, `agents/adaptive_mr/changes.jsonl`.
3. League standings (`data/reports/league.md`) and the AI-vs-twin spread.
4. **Trade autopsies** (`farm/autopsy.py`) — closed round trips with MAE/MFE,
   hold sessions, time-stop hit rate, how much winners gave back.
5. The walk-forward report for this book and its twin
   (`data/reports/walkforward/`).
6. The execution-drag report (`data/reports/execution-drag.md`).
7. The macro_signals composite reading (regime context).
8. The latest news brief (`data/reports/news/latest.md`).

No live web access, no tools, one turn.

## Evaluation — pre-registered, no peeking, no re-registration

* **Evaluation date: 2027-02-01** (26 weeks from 2026-08-04).
* **Measure: spread vs `adaptive_mr_frozen`, net of costs, on the common window.**
* **Kill criterion: AI < twin at evaluation → the AGENT LOOP is killed.** The
  book reverts to its last applied parameters and runs as a static algo; the
  algorithm is not killed by this test.
* Interim numbers are reported and are **not** decision inputs.

## Decisions logged at registration

* **D-A2a — a NEW frozen twin rather than the live `mr_overlay` book.** Unlike
  books 1/4/5, `mr_overlay` is the league's current leader and its record
  already carries a pre-fix artefact (the 2026-07-28 `trading_days_between`
  calendar bug meant its early "10-day" stops actually fired after one session).
  A twin created on the same day as the AI book, from the same parameters,
  compares cleanly from session one.
* **D-A2b — ±50% bounds, 25% per-session step, 2 params per session.** The
  spec's suggested ±50% sets the outer fence; the step and count limits are what
  make the loop *slow* enough that each change gets several weeks of evidence
  before the next one lands on top of it. Without them a 26-week window would
  contain 26 overlapping experiments and answer nothing.
* **D-A2c — the weight×concurrency cross-check.** Both parameters are
  independently in-bounds at 0.15 and 8, but their product is 120% of equity.
  `apply_fill` would clamp the excess to cash and the book would silently run at
  a different concurrency than its config claims. The validator rejects the pair
  rather than letting the clamp hide it.
