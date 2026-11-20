# Sector momentum — forward paper review

_Status **ACCUMULATING** · through 2026-11-20 · paper only · no automatic action._

This report uses only the shared persisted paper equity paths of `sector_momentum` and `spy_benchmark`. It does not reuse walk-forward folds or search parameters.

**Frozen kill criterion:** Trails spy_benchmark by >10% over 12 months without delivering a lower max drawdown.

**Frozen observation boundary:** 2026-09-04 · fill model `v5` · execution profile `baseline_v1`.

The 2026-09-04 closing marks are the prospective baseline. Existing holdings were inherited from the pre-v4 paper path; no pre-baseline return is credited to this observation.

Commissions and this evaluation clock restart at the recorded break **2026-10-19**.

The registered test is not mature before 2027-10-19 and requires at least 200 shared sessions. No decision is permitted from this partial forward window.

| Measure | `sector_momentum` | `spy_benchmark` | Difference |
|---|---:|---:|---:|
| Return (2026-10-19 → 2026-11-20) | -3.88% | -9.95% | +6.07% |
| Max drawdown | -6.27% | -10.72% | +4.44% |

Shared observations: **25**; sessions in displayed window: **25**; first shared date: **2026-09-04**.

Candidate config SHA-256: `c72300f5e438958572985c2257f7bcdf800dfe2cfe89c73f55c471850cc6e67a`. Execution profile: `baseline_v1`. Profile SHA-256: `6340e47066716dbc6d3d221007033fb67069faf9cc9ec04aa95c89ec4de574db`. Runtime-contract SHA-256: `02f4b3695ddcbf0dc0379ffb778293cf1b89d57fb06c575d7fb57e9492a28ae0`. Baseline-state SHA-256: `6009bf5f765b8f28e41636d60666af5d9319c121aa0668f214ba7a647cc0a902`. Equity-prefix SHA-256: `013c4a9a1c9cabda29b1f2ef765a3bf9a9b6ba8de381c4d7ce5ae7104b9202e5`. Forward-ledger SHA-256: `63140349c735803b60b62ea8d68cb301be1758558321c1dcdc0b38b9d0273b58`.

A `CONTINUE` verdict only means the downside kill rule was not met. Promotion or live deployment requires separate positive-edge evidence and explicit approval.
