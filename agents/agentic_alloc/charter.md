# Charter — `agentic_alloc` (AI book 3 of 5)

**FROZEN 2026-08-04.** Registered before any evidence exists and not edited
afterwards. Amending a bound means killing this book and registering a new one
with a new id and a new 26-week clock.

## Objective

Own four algorithmic sleeves and decide **only how much of each to hold**. The
sleeve contents are code and are identical to the frozen twin's, so the spread
between the two books is a pure measurement of the allocation decision and of
nothing else.

| Sleeve | Contents (frozen, algorithmic) |
|---|---|
| `trend` | top 3 of the 11 SPDR sector ETFs by mean 3/6/12-month **total** return, equal weight; a slot whose ETF has a non-positive 12-month total return sits in cash |
| `mr` | SPY, held only while SPY's RSI(2) < 30 at the weekly signal; otherwise cash |
| `defensive` | XLU / XLP / XLV, equal weight |
| `cash` | BIL (a real instrument, so the sleeve earns its coupon — idle cash in this engine earns 0% by design) |

The agent's whole job: set `{trend, mr, defensive, cash}` each Sunday from the
macro_signals composite and per-sleeve walk-forward health.

## Adjustable parameters and their hard bounds

| Knob | Start | Bound | Why |
|---|---|---|---|
| each sleeve weight | 0.25 | **0.00 – 0.40** | the spec's registered range. A 40% cap means no single sleeve can become the book, so a wrong call is a drag and never a wipeout. With four sleeves capped at 40%, at least three must carry real weight for the sum to reach 100% — concentration is structurally impossible |
| sum of weights | 1.00 | **= 1.00 ± 0.001** | the book is always fully allocated; "go to cash" is expressed as the cash sleeve, not as an unallocated remainder, so every decision is visible |
| turnover per session | — | **Σ\|Δw\| ≤ 0.30** | caps a single week at a 15% swing between two sleeves. Without it the agent could invert the whole book weekly and the 26-week record would measure whipsaw, not judgement |
| `trend_n`, `mr_rsi_max` | 3, 30 | **not adjustable** | sleeve *contents* are frozen; if these moved, the twin would no longer isolate the allocation decision |

<!-- BOUNDS -->
```json
{
  "book": "agentic_alloc",
  "twin": "agentic_alloc_frozen",
  "kind": "tuner",
  "cadence": "weekly",
  "max_changes_per_session": 1,
  "max_relative_step": 1.0,
  "params": {
    "sleeve_weights": {
      "type": "simplex",
      "keys": ["trend", "mr", "defensive", "cash"],
      "min": 0.0,
      "max": 0.40,
      "sum": 1.0,
      "sum_tol": 0.001,
      "max_total_turnover": 0.30,
      "start": {"trend": 0.25, "mr": 0.25, "defensive": 0.25, "cash": 0.25}
    }
  },
  "cross_checks": []
}
```

(`max_relative_step` is inert for a simplex — the binding limit is
`max_total_turnover`, which is checked against the CURRENT applied weights.)

## Cadence

**Sunday 10:30 UTC**, after the 06:00 UTC walk-forward grid drains. Weekly
matches the book's own weekly rebalance cadence: a weight decided on Sunday is
expressed by the next weekly signal, so there is no window in which the config
and the holdings disagree for long.

## Evidence the wrapper hands the session (nothing else; the model has zero tools)

1. This charter, `lessons.md`, `changes.jsonl`.
2. League standings and the AI-vs-twin spread.
3. **The macro_signals composite** — the four pre-registered blocks (breadth,
   credit, VIX term structure, macro) and the resulting allocation reading. This
   is the primary regime input for this book.
4. Per-sleeve walk-forward health (`data/reports/walkforward/`), plus the live
   sector/defensive books' standings as sleeve proxies.
5. Trade autopsies for this book (`farm/autopsy.py`).
6. Execution drag and the latest news brief.

## Evaluation — pre-registered, no peeking, no re-registration

* **Evaluation date: 2027-02-01** (26 weeks from 2026-08-04).
* **Measure: spread vs `agentic_alloc_frozen`, net of costs, on the common
  window.** Both books were created the same day, so the common window is the
  full record.
* **Kill criterion: AI < twin at evaluation → the AGENT LOOP is killed;** the
  book continues at its last applied weights as a static allocator.
* Interim numbers are reported and are **not** decision inputs.

## Decisions logged at registration

* **D-A3a — the cash sleeve holds BIL rather than sitting in cash.** This
  engine's idle cash earns 0% (documented, broker-realistic). A cash sleeve that
  earns nothing would make "be defensive" a guaranteed loser against a twin that
  also holds it — but worse, it would understate what a real cash allocation
  does. BIL is already priced, already dividend-credited, and is the same cash
  proxy `dual_momentum` uses.
* **D-A3b — sleeve contents are frozen and only weights move.** The alternative
  (letting the agent also pick sleeve members) collapses the experiment: a
  spread would then be unattributable between selection and allocation, and
  selection is what the other four books already test.
* **D-A3c — the 30% turnover cap is on the SUM of absolute weight changes**, not
  per sleeve. Per-sleeve caps are gameable by moving every sleeve a little; the
  sum is the honest measure of how much the book actually turned over.
* **D-A3d — a 0% floor, not a 5% floor.** Forcing a minimum in every sleeve
  would prevent the agent from ever expressing a clean "no" and would put a
  permanent, un-vetoable drag in the book that the twin also carries — which
  sounds symmetric but is not: it would compress the very spread being measured.
