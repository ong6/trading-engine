# Sector momentum — forward paper review

_Status **ACCUMULATING** · through 2026-09-09 · paper only · no automatic action._

This report uses only the shared persisted paper equity paths of `sector_momentum` and `spy_benchmark`. It does not reuse walk-forward folds or search parameters.

**Frozen kill criterion:** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Frozen observation boundary:** 2026-09-04 · fill model `v4` · execution profile `baseline_v1`.

The 2026-09-04 closing marks are the prospective baseline. Existing holdings were inherited from the pre-v4 paper path; no pre-baseline return is credited to this observation.

The registered test is not mature before 2027-09-04 and requires at least 200 shared sessions. No decision is permitted from this partial forward window.

| Measure | `sector_momentum` | `spy_benchmark` | Difference |
|---|---:|---:|---:|
| Return (2026-09-04 → 2026-09-09) | -0.19% | -1.01% | +0.81% |
| Max drawdown | -0.37% | -1.01% | +0.64% |

Shared observations: **3**; sessions in displayed window: **3**; first shared date: **2026-09-04**.

Candidate config SHA-256: `c72300f5e438958572985c2257f7bcdf800dfe2cfe89c73f55c471850cc6e67a`. Execution profile: `baseline_v1`. Profile SHA-256: `6340e47066716dbc6d3d221007033fb67069faf9cc9ec04aa95c89ec4de574db`. Runtime-contract SHA-256: `d8ad1e801ee5703ae8f29e7eb9e56fa0f2736c7f9b37afc10bad1704d27276ca`. Baseline-state SHA-256: `6009bf5f765b8f28e41636d60666af5d9319c121aa0668f214ba7a647cc0a902`. Equity-prefix SHA-256: `b644b15e62124c3b904c4e32a9b1d07d00374f345d85645311de61e2a0518bca`. Forward-ledger SHA-256: `4735419b52c6e636d7e0f679bf8d0e1bdab6e2fdfea3ecaa27221ea7789c003b`.

A `CONTINUE` verdict only means the downside kill rule was not met. Promotion or live deployment requires separate positive-edge evidence and explicit approval.
