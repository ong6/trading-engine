# Sector momentum — forward paper review

_Status **ACCUMULATING** · through 2026-10-22 · paper only · no automatic action._

This report uses only the shared persisted paper equity paths of `sector_momentum` and `spy_benchmark`. It does not reuse walk-forward folds or search parameters.

**Frozen kill criterion:** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Frozen observation boundary:** 2026-09-04 · fill model `v5` · execution profile `baseline_v1`.

The 2026-09-04 closing marks are the prospective baseline. Existing holdings were inherited from the pre-v4 paper path; no pre-baseline return is credited to this observation.

Commissions and this evaluation clock restart at the recorded break **2026-10-19**.

The registered test is not mature before 2027-10-19 and requires at least 200 shared sessions. No decision is permitted from this partial forward window.

| Measure | `sector_momentum` | `spy_benchmark` | Difference |
|---|---:|---:|---:|
| Return (2026-10-19 → 2026-10-22) | +0.37% | -0.33% | +0.69% |
| Max drawdown | -0.87% | -1.17% | +0.31% |

Shared observations: **4**; sessions in displayed window: **4**; first shared date: **2026-09-04**.

Candidate config SHA-256: `c72300f5e438958572985c2257f7bcdf800dfe2cfe89c73f55c471850cc6e67a`. Execution profile: `baseline_v1`. Profile SHA-256: `6340e47066716dbc6d3d221007033fb67069faf9cc9ec04aa95c89ec4de574db`. Runtime-contract SHA-256: `bad2576494c4c1357d8045018d98da3d1575ed096844b66423f094ee104dd7ea`. Baseline-state SHA-256: `6009bf5f765b8f28e41636d60666af5d9319c121aa0668f214ba7a647cc0a902`. Equity-prefix SHA-256: `ce8ef52c5f000ca28e126e3786736a6981cac85b083a5fcfb6085bac6cd2f717`. Forward-ledger SHA-256: `b27c225b0b919f20e2ee8d4365e192c9484d9488bfad7a33d1028d68f3f1ab34`.

A `CONTINUE` verdict only means the downside kill rule was not met. Promotion or live deployment requires separate positive-edge evidence and explicit approval.
