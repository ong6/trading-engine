# Retired PIT restore identities

These inputs were removed locally on 2026-10-18 only after an independently fetched release
proved every member. Restore into an empty temporary directory first. Never open an absent
DuckDB destination: DuckDB may silently create an empty database.

## Accepted release

- Private data repository: `ong6/trading-data`
- Release tag: `research-evidence-20261005-f7d4f695396c-52da75c8`
- Release manifest SHA-256: `f7d4f695396c6eb013a1238d612920748ba2d153c6cbf071da577f90ec755e06`
- Assets: `manifest.json`, `manifest.sha256`, and `archive-00000.part` through
  `archive-00037.part`

Using an authenticated GitHub CLI, download the named tag into a new temporary directory:

```sh
gh release download research-evidence-20261005-f7d4f695396c-52da75c8 \
  --repo ong6/trading-data --pattern 'manifest*' --pattern 'archive-*.part' \
  --dir "$RESTORE_TMP"
```

Refuse unless the downloaded `manifest.json` has the exact digest above. Verify every archive
part against the digest recorded in that manifest, concatenate parts in bytewise filename order,
and extract only the named target beneath the temporary directory. Compare every extracted
member with the manifest before installing it at its repository-relative destination. Refuse an
existing destination and require at least 70 GiB free after restoration.

## M4: short-data database

- Destination: `store/pit/short-data.duckdb`
- Bytes: `2060988416`
- SHA-256: `59406972cdcd82f316a0034e699113be682768328fb8aeb4aadb54829f99fa66`
- Required relations: `regsho_threshold`, `finra_short_interest`
- Readers: `engine.accounts.sources`, `sim.shorts`, and account settlement

After extraction, verify the exact byte length and SHA-256, then open the temporary database
read-only and require both relations before an atomic install. Account execution attaches this
database read-only. A missing or invalid database makes only dependent paper-account work
unavailable; it never authorizes a refetch, an empty replacement, or a broker route.
