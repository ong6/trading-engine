# Walk-forward evidence guide

The generated [`README.md`](README.md) and the per-book pages linked from its summary table are
the latest human-readable cohort for the 18 active, replayable books.

The generated index still describes its `PASS`/`WATCH`/`REVIEW` triage as input to a “Sunday
review loop.” That sentence is retained output from the evidence-anchored report renderer, not a
current operating instruction. The model-driven review loop was retired on 2026-08-18; Sunday now
runs deterministic walk-forward revalidation only. Treat those labels as historical mechanical
triage, then use the current decision ledger and prospective monitors for decisions. Changing the
renderer requires an explicit evidence migration rather than a documentation-only edit to frozen
research source.

- [`results/`](results/) is the moving canonical JSON result directory. `GET /meta` field
  `walkforward_evidence` validates only the currently registered, replayable books against their
  live configs and the deployed source; an unregistered legacy result cannot make that cohort
  current.
- `monthly-*.md` and `monthly-*.json` are dated review snapshots. They remain historical records
  and do not supersede the latest generated index or live `/meta` validity.
- [`migrations/`](migrations/) contains immutable before/after cohorts retained for explicit source
  migrations. Those copies reproduce a reviewed comparison and are not scheduler inputs or a
  replacement for the canonical latest results.

Eight additional top-level pages are retained historical outputs, not members of the latest
cohort: [`adaptive_mr.md`](adaptive_mr.md),
[`adaptive_mr_frozen.md`](adaptive_mr_frozen.md), [`agentic_alloc.md`](agentic_alloc.md),
[`agentic_alloc_frozen.md`](agentic_alloc_frozen.md),
[`earnings_context_pead.md`](earnings_context_pead.md),
[`news_gated_momo.md`](news_gated_momo.md), and
[`stop_tuner_turtle.md`](stop_tuner_turtle.md) belong to the retired agentic layer;
[`multi_asset_trend.md`](multi_asset_trend.md) is the retained page for that retired strategy.
Their sibling JSON files remain for provenance, but unregistered legacy artifacts are ignored by
the live cohort validator. A file's presence does not mean its book is active.

No layer in this directory is independent prospective evidence or permission to promote, connect
to a broker, or use live capital. The frozen forward records under [`../forward/`](../forward/)
own the prospective comparisons.
