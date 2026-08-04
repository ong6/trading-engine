# Charter — `stop_tuner_turtle` (AI book 4 of 5)

**FROZEN 2026-08-04.** Registered before any evidence exists and not edited
afterwards. Amending a bound means killing this book and registering a new one
with a new id and a new 26-week clock.

## Objective

Run `turtle_breakout`'s algorithm — 55-session close breakouts on trend-template
passers, ATR-risk sizing, a chandelier trail, no entries while SPY is below its
200-day — and let a weekly session move the **stop and sizing geometry** inside
hard bounds, from the stopped-trade autopsy.

The specific question: **were our stops too tight or too loose?** Every stopped
trade is one of two things — a premature stop (the name recovered and we gave up
the move) or a disaster avoided (it kept falling). The autopsy's MAE/MFE record
separates them; this agent's only job is to move the geometry in the direction
that evidence points, slowly.

## Adjustable parameters and their hard bounds

Bounds are ±50% around the live book's registered values.

| Param | Start | Min | Max | Why the bound |
|---|---|---|---|---|
| `stop_mult` | 2.5 | 1.25 | 3.75 | ±50%. The initial-risk ATR multiple — the parameter a trend book is most sensitive to, and the one the autopsy speaks to most directly |
| `trail_mult` | 3.0 | 1.5 | 4.5 | ±50%. Below 1.5×ATR a chandelier trail fires on ordinary noise; above 4.5 it stops being a trail |
| `entry_lookback` | 55 | 28 | 83 | ±50% rounded to integers. 28 is still a real multi-week breakout; 83 is still inside the data every passing name has |
| `risk_frac` | 0.0075 | 0.00375 | 0.01125 | ±50% of 0.75% risk per trade |
| `atr_period`, `max_positions`, `max_weight` | 20, 10, 0.15 | — | **not adjustable** | these define the book's shape, not its stop geometry. Letting concurrency move would make the spread unattributable between "better stops" and "more bets" |

**Session limits:** at most **2** parameters changed per session, each by at most
**25%** of its current value. And a structural check the bounds alone do not
catch: **`trail_mult` must stay ≥ `stop_mult`**. A trail tighter than the initial
stop means a position can be trailed out before it has ever been at risk of its
own stop — an incoherent configuration that is nonetheless reachable from two
individually in-bounds numbers (e.g. stop 3.75, trail 1.5).

<!-- BOUNDS -->
```json
{
  "book": "stop_tuner_turtle",
  "twin": "turtle_breakout",
  "kind": "tuner",
  "cadence": "weekly",
  "max_changes_per_session": 2,
  "max_relative_step": 0.25,
  "params": {
    "stop_mult":      {"type": "number",  "min": 1.25,    "max": 3.75,    "start": 2.5},
    "trail_mult":     {"type": "number",  "min": 1.5,     "max": 4.5,     "start": 3.0},
    "entry_lookback": {"type": "integer", "min": 28,      "max": 83,      "start": 55},
    "risk_frac":      {"type": "number",  "min": 0.00375, "max": 0.01125, "start": 0.0075}
  },
  "cross_checks": [
    {"kind": "ge", "left": "trail_mult", "right": "stop_mult",
     "why": "a trail tighter than the initial stop is incoherent — the position would be trailed out before it was ever at initial risk"}
  ]
}
```

## Cadence

**Sunday 10:30 UTC**, after the 06:00 UTC walk-forward grid drains. A stop
parameter needs weeks of trades to judge, so weekly is already fast; the 25%
step limit is what keeps each change legible in the record.

## Evidence the wrapper hands the session (nothing else; the model has zero tools)

1. This charter, `lessons.md`, `changes.jsonl`.
2. League standings and the AI-vs-twin spread.
3. **Trade autopsies** (`farm/autopsy.py`) — the primary evidence for this book:
   per closed trade the MAE (how far it went against us), the MFE (how far it
   went for us), how much winners gave back, and the share of losers whose MAE
   went beyond 5/10/15/20%.
4. Walk-forward report for this book and `turtle_breakout`.
5. Execution drag (slippage against the modelled fill), macro composite, and the
   latest news brief.

## Evaluation — pre-registered, no peeking, no re-registration

* **Evaluation date: 2027-02-01** (26 weeks from 2026-08-04).
* **Measure: spread vs the live `turtle_breakout` book, net of costs, on the
  common window** (twin inception 2026-07-28, AI 2026-08-04 — rebase both to
  1.00 on the first shared session).
* **Kill criterion: AI < twin at evaluation → the AGENT LOOP is killed;** the
  book keeps its last applied geometry and runs static.
* Interim numbers are reported and are **not** decision inputs.

## Decisions logged at registration

* **D-A4a — the twin is the live `turtle_breakout` book.** Same reasoning as
  book 1: it runs the identical algorithm and already has a forward record. The
  7-session inception gap is handled by common-window rebasing, never by
  comparing raw inception-to-date returns.
* **D-A4b — sizing (`risk_frac`) is in scope but concurrency is not.** Stop
  distance and risk-per-trade are two halves of one geometry: widening the stop
  without touching risk mechanically shrinks position size, and an agent that
  can only move one of them is being asked to hold a rope at one end. Position
  *count*, by contrast, is a different lever entirely — it changes how much of
  the book is at risk at once, and letting it move would make a good spread
  unattributable.
* **D-A4c — the trail ≥ stop cross-check is registered as a bound, not left to
  the model's judgement.** It is exactly the kind of constraint a fluent
  proposal can violate while sounding reasonable, and it is trivially checkable
  in code. Anything checkable in code is checked in code.
