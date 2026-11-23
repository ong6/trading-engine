# schemas/ — agent notes

- `datasets.yaml` is the dataset catalogue: location, owner, producer, readers, semantics, clock
  and key, retention, backup and rebuild rule for every dataset. `tests/test_dataset_catalogue.py`
  checks it against the code; update it in the same commit as a new table or store.
- `postmortem-v1.json` is the frozen schema for replay post-mortems.

More: [`../docs/data/README.md`](../docs/data/README.md).
