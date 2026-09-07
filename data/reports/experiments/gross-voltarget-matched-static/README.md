# Gross-volatility targeting — matched-static review

_Decision **INCONCLUSIVE-LEGACY** · paper only · no automatic action._

Some cells survive permissive kill gates, but no cell establishes positive timing value and the v2 artifacts lack complete source/data/profile provenance.

This evaluates all 9 predeclared dynamic cells against the nearest-volatility fold from 5 static-exposure controls. Matching is deterministic and fold-local; no cell is selected for trading.

| Lookback | Target | Kill gates | RA wins vs static | Mean timing excess | 90% CI | Vol-slope | 90% CI | Timing edge? |
|---:|---:|---|---:|---:|---:|---:|---:|---|
| 40 | +10.00% | SURVIVES | 70% | -0.93% | [-3.55%, +0.96%] | -0.078 | [-0.456, +0.031] | no |
| 60 | +10.00% | SURVIVES | 60% | -1.84% | [-5.19%, +0.73%] | -0.156 | [-0.683, -0.001] | no |
| 120 | +10.00% | SURVIVES | 50% | -1.91% | [-4.80%, +0.32%] | -0.136 | [-0.611, +0.014] | no |
| 40 | +15.00% | KILLED | 80% | -0.36% | [-4.54%, +2.77%] | +0.107 | [-0.545, +0.272] | no |
| 60 | +15.00% | KILLED | 80% | -1.47% | [-6.62%, +2.13%] | +0.024 | [-0.814, +0.241] | no |
| 120 | +15.00% | KILLED | 60% | -1.84% | [-6.40%, +1.45%] | +0.016 | [-0.758, +0.230] | no |
| 40 | +20.00% | KILLED | 70% | +1.87% | [-2.72%, +5.57%] | +0.133 | [-0.677, +0.352] | no |
| 60 | +20.00% | KILLED | 70% | +0.69% | [-4.06%, +4.39%] | +0.067 | [-0.809, +0.313] | no |
| 120 | +20.00% | KILLED | 60% | +0.30% | [-4.35%, +4.25%] | +0.047 | [-0.870, +0.349] | no |

`RA wins` compares validate return/annualized-volatility with the matched static control. The slope regresses timing excess on the same fold's EW benchmark volatility. Intervals use 10,000 paired fold resamples with seed `20260820`.

The three 10%-target cells survive the original permissive drawdown/return gates. That is not proof of edge: every mean timing-excess interval contains zero, no volatility-slope interval is wholly positive, nine candidate cells were searched, and the inputs are legacy fill-model-v2 artifacts without complete provenance. No paper registration, rerun, parameter choice, or live action follows.
