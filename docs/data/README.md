# Data

Where data lives, who writes it and the rules it follows. The repo ships no market store and no
credentials; stores are rebuilt locally by the producers.

- **Catalogue.** [`schemas/datasets.yaml`](../../schemas/datasets.yaml) is the contract for every
  dataset: location, schema owner, producer, readers, semantics (projection, append-only evidence,
  authoritative ledger), clock and key, retention, backup and rebuild rule.
  `tests/test_dataset_catalogue.py` keeps it in step with the code.
- **Operational store.** `store/market.duckdb` (override `TRADING_ENGINE_DB`, paths in
  `engine/lib/settings.py`). One writer at a time through `engine.lib.db.connect`; readers use the
  immutable snapshots under `store/snapshots/` (`market-latest.duckdb`).
- **Research-only stores** under `store/pit/` (free sources, SEC bulk, Massive minute and options,
  frozen-archive census) are isolated: they never price a fill or change operational prices.
  Their capture tools are `tools/free_*.py` and `tools/sec_edgar_capture.py`.
- **Committed outputs.** `data/screens/`, `data/reports/` (start at
  [`data/reports/README.md`](../../data/reports/README.md)) and `data/_meta.json`.
- **Licensed point-in-time imports** go through `engine/pit_import.py`; the manifest shape is
  [`pit-import-manifest.example.json`](pit-import-manifest.example.json).

Rules: never fabricate a price or bar; point-in-time rows are append-only with their availability
clock; data stays free (no paid vendors, no new API keys); TradingView and other research sources
never price fills, orders or risk; raw scraped text stays on the host, outside git. Daily private
backups of the store go to the owner's private data repository, restore-checked on every run.
Plain-language overview: [`../site/data.md`](../site/data.md).
