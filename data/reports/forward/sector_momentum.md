# Sector momentum — forward paper review

_Status **ACCUMULATING** · through 2026-09-30 · paper only · no automatic action._

This report uses only the shared persisted paper equity paths of `sector_momentum` and `spy_benchmark`. It does not reuse walk-forward folds or search parameters.

**Frozen kill criterion:** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Frozen observation boundary:** 2026-09-04 · fill model `v4` · execution profile `baseline_v1`.

The 2026-09-04 closing marks are the prospective baseline. Existing holdings were inherited from the pre-v4 paper path; no pre-baseline return is credited to this observation.

The registered test is not mature before 2027-09-04 and requires at least 200 shared sessions. No decision is permitted from this partial forward window.

| Measure | `sector_momentum` | `spy_benchmark` | Difference |
|---|---:|---:|---:|
| Return (2026-09-04 → 2026-09-30) | -0.05% | -0.73% | +0.68% |
| Max drawdown | -1.33% | -2.09% | +0.76% |

Shared observations: **18**; sessions in displayed window: **18**; first shared date: **2026-09-04**.

Candidate config SHA-256: `c72300f5e438958572985c2257f7bcdf800dfe2cfe89c73f55c471850cc6e67a`. Execution profile: `baseline_v1`. Profile SHA-256: `6340e47066716dbc6d3d221007033fb67069faf9cc9ec04aa95c89ec4de574db`. Runtime-contract SHA-256: `8a91b71295afd533c1d508645daad2b62e9dc80deab506f2b422b095b1b8a2ce`. Baseline-state SHA-256: `6009bf5f765b8f28e41636d60666af5d9319c121aa0668f214ba7a647cc0a902`. Equity-prefix SHA-256: `084dfd7645e86450f6022244b341dc350a9239a22c47e1ad0c8e8ff8a9bea656`. Forward-ledger SHA-256: `8bad1f4026a06ae26ab42a9546fa7c819d98a1f0aab08ecb92822af4847e670e`.

A `CONTINUE` verdict only means the downside kill rule was not met. Promotion or live deployment requires separate positive-edge evidence and explicit approval.
