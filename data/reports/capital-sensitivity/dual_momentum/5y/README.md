# Capital sensitivity — `dual_momentum` / `5y`

_Every row is a complete strategy replay. Returns were not rescaled from another account size. This is paper research, not authorization for live trading._

Evidence class: `fixed_etf_history` · fill model `v4` · source `0e1f682e34fa96e32363c09c00a96c7699ac8aa44364081327c82a0579ab2262` · data `b1b031ac37c5b658034fd5b6234fdbe61facab5cba9cdd4afb1159c542fa3785`.

Capacity observations are bounds at the sampled account sizes, not an interpolated or guaranteed trading capacity.

- `baseline_v1`: Largest tested capital with zero capacity rejects: **$1,000,000**; first tested capital with a capacity reject: **$10,000,000**.
- `cost_2x_v1`: Largest tested capital with zero capacity rejects: **$1,000,000**; first tested capital with a capacity reject: **$10,000,000**.

| Profile | Start | Return | Max DD | Fills | Total rejects | Capacity rejects | Rejected notional | p95 participation | Max participation | Turnover | Market cost $ | Total cost $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `baseline_v1` | $10,000 | 50.64% | -23.08% | 25 | 0 | 0 | $0 | 0.00% | 0.00% | 18.73× | $187 | $187 |
| `baseline_v1` | $39,000 | 50.74% | -23.14% | 34 | 0 | 0 | $0 | 0.00% | 0.00% | 18.76× | $732 | $732 |
| `baseline_v1` | $100,000 | 50.74% | -23.14% | 34 | 0 | 0 | $0 | 0.01% | 0.01% | 18.76× | $1,876 | $1,876 |
| `baseline_v1` | $250,000 | 50.74% | -23.14% | 34 | 0 | 0 | $0 | 0.02% | 0.03% | 18.76× | $4,691 | $4,691 |
| `baseline_v1` | $1,000,000 | 50.74% | -23.14% | 34 | 0 | 0 | $0 | 0.10% | 0.11% | 18.76× | $18,765 | $18,765 |
| `baseline_v1` | $10,000,000 | 49.37% | -23.14% | 32 | 4 | 3 | $37,368,459 | 0.84% | 0.95% | 13.70× | $137,005 | $137,005 |
| `cost_2x_v1` | $10,000 | 48.11% | -23.56% | 24 | 0 | 0 | $0 | 0.00% | 0.00% | 18.57× | $371 | $371 |
| `cost_2x_v1` | $39,000 | 48.20% | -23.60% | 33 | 0 | 0 | $0 | 0.00% | 0.00% | 18.59× | $1,450 | $1,450 |
| `cost_2x_v1` | $100,000 | 48.20% | -23.60% | 34 | 0 | 0 | $0 | 0.01% | 0.01% | 18.59× | $3,718 | $3,718 |
| `cost_2x_v1` | $250,000 | 48.20% | -23.60% | 34 | 0 | 0 | $0 | 0.02% | 0.03% | 18.59× | $9,296 | $9,296 |
| `cost_2x_v1` | $1,000,000 | 48.20% | -23.60% | 34 | 0 | 0 | $0 | 0.10% | 0.11% | 18.59× | $37,183 | $37,183 |
| `cost_2x_v1` | $10,000,000 | 47.44% | -23.60% | 31 | 5 | 3 | $36,960,321 | 0.84% | 0.94% | 13.60× | $272,084 | $272,084 |
