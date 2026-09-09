# Parameter-sweep archive

These directories retain completed historical parameter grids. Their ranking tables compare
cells within the experiment that produced them; they are not a queue of strategies awaiting
promotion, and phrases such as “starting point” or “what a good row would look like” preserve the
interpretation written when each report was generated.

The current decision is maintained in
[`../../../docs/strategy-research-backlog.md`](../../../docs/strategy-research-backlog.md), which
supersedes any apparent next-step language inside an older ranking. No completed grid establishes
positive excess over its proper control, and none authorizes a paper book, parameter selection,
another nearby search, broker access, or live capital.

## Retained legacy grids

- `banding/`
- `concentration/`
- `dd_throttle/`
- `gross_voltarget/`
- `meanrev/`
- `momo_stop/`
- `sector_cap/`
- `static_exposure/`
- `turtle_stops/`
- `voltarget/`

These are legacy unversioned outputs retained for provenance. The recurring sweep allowlist
`farm.sweep.sweep.OPEN_RECURRING_GRIDS` is intentionally empty. A future recurring grid requires
a new frozen charter version and publishes separately under
`data/reports/sweeps/<grid>/charters/<version>/`; it does not overwrite or reinterpret this
archive.
