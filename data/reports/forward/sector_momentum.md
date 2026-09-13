# Sector momentum — forward paper review

_Status **ACCUMULATING** · through 2026-09-11 · paper only · no automatic action._

This report uses only the shared persisted paper equity paths of `sector_momentum` and `spy_benchmark`. It does not reuse walk-forward folds or search parameters.

**Frozen kill criterion:** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Frozen observation boundary:** 2026-09-04 · fill model `v4` · execution profile `baseline_v1`.

The 2026-09-04 closing marks are the prospective baseline. Existing holdings were inherited from the pre-v4 paper path; no pre-baseline return is credited to this observation.

The registered test is not mature before 2027-09-04 and requires at least 200 shared sessions. No decision is permitted from this partial forward window.

| Measure | `sector_momentum` | `spy_benchmark` | Difference |
|---|---:|---:|---:|
| Return (2026-09-04 → 2026-09-11) | -0.56% | -0.76% | +0.21% |
| Max drawdown | -1.04% | -1.60% | +0.56% |

Shared observations: **5**; sessions in displayed window: **5**; first shared date: **2026-09-04**.

Candidate config SHA-256: `c72300f5e438958572985c2257f7bcdf800dfe2cfe89c73f55c471850cc6e67a`. Execution profile: `baseline_v1`. Profile SHA-256: `6340e47066716dbc6d3d221007033fb67069faf9cc9ec04aa95c89ec4de574db`. Runtime-contract SHA-256: `c430b451ee510c858705ba4235f81b68f9d7443745a60b4716035acb32741788`. Baseline-state SHA-256: `6009bf5f765b8f28e41636d60666af5d9319c121aa0668f214ba7a647cc0a902`. Equity-prefix SHA-256: `8bb4e84ed3f08ec61adb198991d2528e21a0b8b0a07a886b9dddf524416ee94d`. Forward-ledger SHA-256: `4735419b52c6e636d7e0f679bf8d0e1bdab6e2fdfea3ecaa27221ea7789c003b`.

A `CONTINUE` verdict only means the downside kill rule was not met. Promotion or live deployment requires separate positive-edge evidence and explicit approval.
