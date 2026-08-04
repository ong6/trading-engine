# Charter — `earnings_context_pead` (AI book 5 of 5)

**FROZEN 2026-08-04.** Registered before any evidence exists and not edited
afterwards. Amending a bound means killing this book and registering a new one
with a new id and a new 26-week clock.

## Objective

Run `pead_ear`'s algorithm unchanged (buy names whose earnings-day abnormal
return vs SPY is ≥ 5% on ≥2× average volume; 45-session or −8% exit) and
**classify the reaction behind each proposed entry from the day's headlines**,
vetoing or downscaling the classes that historically do not drift.

The classification the agent is asked for, per candidate:

| Class | Meaning | Default disposition |
|---|---|---|
| `guidance` | the move is driven by the company raising forward guidance or a structural beat | take at full size |
| `one_off` | the move is driven by a non-recurring item — an asset sale, a legal settlement, a tax benefit, a one-time charge reversal | downscale or veto |
| `sympathy` | the name moved on a *peer's* result or a sector headline, not its own | veto |
| `unclear` | no headline explains the move | take at full size — the algo's default stands |

`unclear` deliberately defaults to **taking** the trade. An agent that vetoes
what it cannot explain would quietly shrink the book toward whatever the news
feed happens to cover, which is a bias in the feed, not a signal.

## Permissions — asymmetric, enforced in code

| Allowed | Forbidden |
|---|---|
| `veto` a proposed BUY | adding any name the algo did not propose |
| `downscale` a proposed BUY (scale 0.25–1.00) | raising any size |
| — | touching a SELL, the −8% stop, or the 45-session exit |
| — | changing any numeric strategy parameter |

Enforcement is `sim/strategies/base.py::apply_agent_gate` plus
`agents/validator.py`. The gate reads only
`agents/earnings_context_pead/gate-<date>.json`. **No gate file for a date →
pure algo (fail-open).**

## Adjustable "parameters" and their hard bounds

No strategy parameter is adjustable — the algo is byte-identical to `pead_ear`'s.
The gate itself is bounded:

| Knob | Bound | Why this bound |
|---|---|---|
| `action` | `veto` or `downscale` only | the asymmetry is the whole safety argument |
| `scale` | 0.25 – 1.00 | below 0.25 a downscale is a veto in disguise |
| `max_decisions` | 15 per day | the book holds at most 10 concurrent names and rarely sees more than a handful of qualifying reactions a day |
| `max_veto_share_of_candidates` | 0.50 | past half, the agent is replacing the strategy rather than gating it |
| `reason_min_chars` | 20 | every veto is re-read at 26 weeks; an unstated reason is unreviewable |

<!-- BOUNDS -->
```json
{
  "book": "earnings_context_pead",
  "twin": "pead_ear",
  "kind": "gater",
  "cadence": "daily",
  "gate": {
    "allowed_actions": ["veto", "downscale"],
    "min_scale": 0.25,
    "max_scale": 1.0,
    "max_decisions": 15,
    "max_veto_share_of_candidates": 0.5,
    "reason_min_chars": 20
  },
  "params": {}
}
```

## Cadence

* **Daily gate session** — 21:40 UTC weekdays, ahead of the 22:30 UTC nightly.
  Earnings reactions are a daily event stream, so the session runs every weekday
  and is simply a no-op on days with no candidates.
* **Weekly lessons** — appended by the Sunday cycle: which classes actually
  predicted drift? That is the one durable thing this book can learn, and it is
  the question the 26-week review asks.

## Evidence the wrapper hands the session (nothing else; the model has zero tools)

1. This charter and `lessons.md`.
2. The day's news brief, `data/reports/news/latest.md`.
3. The algo's *preview* candidate list (this book's own `generate_orders` re-run
   read-only against the latest stored session), labelled as a preview.
4. Names with an earnings date inside the last two sessions
   (`earnings_calendar`, point-in-time as-of the decision date).
5. The book's current holdings and the league standing.

## Evaluation — pre-registered, no peeking, no re-registration

* **Evaluation date: 2027-02-01** (26 weeks from 2026-08-04).
* **Measure: spread vs the frozen twin `pead_ear`, net of costs, on the common
  window** (twin inception 2026-07-28, AI 2026-08-04 — rebase both to 1.00 on
  the first shared session).
* **Kill criterion: AI < twin at evaluation → the AGENT LOOP is killed;** the
  gate flag comes off and the book continues as pure algo.
* Interim numbers are reported and are **not** decision inputs.

## Decisions logged at registration

* **D-A5a — `unclear` defaults to TAKE.** See above: defaulting to veto would
  make the book's size a function of news coverage. Coverage is denser for large
  caps, so vetoing the unexplained would quietly turn a PEAD sleeve into a
  large-cap PEAD sleeve without anyone registering that change.
* **D-A5b — the class is recorded even when the disposition is "take".** The
  26-week question is *which classes predicted drift*, and that is unanswerable
  from vetoes alone — it needs the taken trades' classes too. The gate file
  therefore carries a `class` field on every decision including `action: null`
  informational rows, which `apply_agent_gate` ignores by construction (it acts
  only on `veto`/`downscale`).
* **D-A5c — the earnings-date list is point-in-time.** `earnings_calendar` is
  queried with `as_of <= decision date`, the same discipline the strategy
  itself uses, so a session can never see a date that was restated later.
