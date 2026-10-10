# P22 lifecycle writer brief

## 2026-10-10 — P22 lifecycle round 6 (binding orchestrator rulings)

These rulings supersede the earlier checkpoint and historical-risk rules.
Deploy target remains Sunday 2026-10-18, D0 2026-10-19.

A. **Accounting is one pure fold from account inception.**
`state = fold(all effective-dated events of the account)`: fills, corporate actions,
cash settlements, dividends, financing and fees. Replay the whole account every settle
(nightly, late, verify and `/results`). Stored cash, lots and equity are a cache written
atomically from the fold and verified against it. Delete partial checkpoint restoration.
Every event has a stable identity from its full key, including its date; a per-date
sequence number alone is never an identity.

B. **Orders keep receipt units.** Store an order in the units in force at receipt and
convert to its execution session's units inside the fold. A pre-split MOO filled late
fills its pre-split quantity; the later split applies exactly once.

C. **Risk acts as-known, never backdated.** Halts and resumes take effect when processed.
API resume is effective at receipt and rejects a past effective time. After every settle,
run risk on corrected history as of now: drawdown from the corrected peak re-measured
from the latest resume, daily loss for the latest settled session, and fold/cache mismatch.
Late data never un-fills orders already executed while active. Delete historical-risk replay.

D. **Any failure halts.** Any exception during fold, settle or verify rolls back the
transaction, then persists mismatch evidence and halts in a separate transaction.
Nightly and late entry points exit nonzero.
