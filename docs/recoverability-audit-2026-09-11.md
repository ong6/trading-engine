# Recoverability audit — 2026-09-11

This is a dated Workstream A snapshot. It records what was observed; it does not claim that the
repository is currently a clean or restorable release. Re-run every command and replace this
snapshot with a new dated audit before relying on it for deployment.

## Current disposition after the 2026-09-12 updates

Workstream A's exit gate remains **not met**. The tested state is still not recoverable from
`HEAD` or from an off-machine backup: the working tree is uncommitted, `main` has no usable
upstream, and no encrypted off-machine destination or independent-machine restore has been
authorized or proved. However, the former local-database-backup and same-host application gaps are
now closed. Schema-v2 bundles preserve the database, prospective checkpoints, and bounded
operational state, and the isolated-directory drill described at the end of this document passed.

## Initial decision at audit time

The running paper system was healthy and that working tree passed its quality gates, but
**the deployed state was not recoverable from `HEAD` or from an off-machine backup at initial
audit time**.

The initial blockers were source control and backup/recovery, not packaging:

- `HEAD` is `f4528cf2e58f0baae0dda8bac9bfcc76e5c972fd`, while the running tree contains 102
  modified and 179 untracked paths after this audit's documentation, manifest, and test additions.
- Active modules, tests, service units, documentation, `.github/dependabot.yml`, and `uv.lock`
  are among the untracked paths. A checkout of `HEAD` cannot reconstruct the tested system.
- `origin` exists, but `main` has no upstream tracking branch. `GET /meta` therefore correctly
  reports `source_control.status = local-only`; local commits are not an off-machine backup.
- The 3.8 GB `store/market.duckdb` was ignored and had no current backup. The only other DuckDB
  found under the workspace was the separate 2026-09-02 pre-rewrite backup. The updates below
  supersede this initial finding for local same-host recovery only.
- User service files installed under `~/.config/systemd/user/` exactly match the repository
  copies, but the repository copies are untracked.
- At initial observation, the five production cron entries and auxiliary Friday postflight entry
  were host state without versioned installation output. The update below closes that installer
  gap, but not the source-control or backup blockers.

Do not add broker integration or credentials until the remaining failures are closed.

## What was proved

The checks below passed against the current working tree:

- full Python test suite with warnings as errors;
- repository Ruff and `server tools` C901 checks;
- Python byte compilation and shell syntax checks;
- `uv lock --check`;
- Python runtime dependency audit with no known vulnerabilities;
- wheel construction containing all active `engine`, `farm`, `server`, and `sim` packages plus
  frozen experiment definitions;
- all UI contract tests;
- UI production dependency audit with no known vulnerabilities;
- Next.js production build;
- Markdown local-link checks and documentation contracts;
- Git diff whitespace checks.

The API and UI user services were active, enabled, and had zero restarts at observation time.
Their installed unit files matched the repository copies. User lingering was enabled.

The current research-runtime identity was:

```text
runtime_source_sha256=2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53
runtime_source_file_count=111
```

This is the research fingerprint used by current walk-forward evidence. It is not a complete
release identity: it deliberately excludes the API, UI, service files, dependency lockfiles,
documentation, and host schedules.

## Restore classes

### Versioned source and configuration

These must be reviewed and committed before a release can exist:

- `engine/`, `farm/`, `sim/`, `server/`, `ui/app/`, and `tools/`;
- Python and UI tests;
- `pyproject.toml`, `engine/requirements.txt`, `uv.lock`, `ui/package.json`, and
  `ui/package-lock.json`;
- API/UI service units, shell drivers, CI, Dependabot, and `.gitignore`;
- current operating, security, strategy, and live-readiness documentation;
- frozen experiment registration files under `farm/experiments/`.

Generated research reports and screens are a separate review group. They should not be mixed into
a source checkpoint without confirming that each file is an intended public artifact.

### Tracked generated evidence

`data/screens/` and `data/reports/` contain the committed, human-readable outputs. Prospective
JSON checkpoints under `data/reports/forward/` and
`data/reports/experiments/e1-spy-monday-forward.json` are especially important because they
anchor immutable forward prefixes.

Git is useful for these only after the branch is tracked and a push is independently verified.
A local commit and a cached tracking ref do not prove off-machine durability.

### Ignored reproducible state

These can be regenerated and do not belong in a release:

- `.venv/`, Python bytecode, pytest/Ruff caches;
- `build/`, `dist/`, and `*.egg-info/`;
- `ui/node_modules/` and `ui/.next/`;
- lock files and ordinary logs;
- `data/eod/` and `data/universe.csv`.

Deleting them is not a recoverability improvement. Rebuild them only when needed.

### Ignored irreplaceable state

`store/market.duckdb` is not a disposable build artifact. It contains:

- the local market and point-in-time archives;
- paper portfolios, positions, orders, fills, costs, and equity;
- queue and experiment state;
- corporate-action, earnings, and fundamentals observations;
- audit and review records.

The database must be backed up from a transactionally consistent snapshot. Do not copy a live
DuckDB file while writers may be active and call the result a backup. The restore procedure must
verify database readability, required tables, row/count invariants, latest operational date,
prospective checkpoint identities, active portfolio state, and queue state before services are
enabled.

Future broker journals, credentials, authorization state, and reconciliation records must be
classified separately. Credentials must never enter Git or the same public artifact bundle.

## What the wheel does and does not prove

The wheel successfully packages the active Python modules and frozen experiment definitions. It
does not include:

- the Next.js application or Node lockfile;
- systemd units or cron installation;
- the DuckDB store or generated prospective evidence;
- operator documentation and restore procedures;
- host-specific paths, Node runtime, or user-lingering configuration.

The wheel is therefore a useful Python artifact, not a complete deployment or recovery bundle.

## Required closure sequence

1. Review the dirty tree by ownership group: runtime source, support/API, UI, tests,
   documentation/configuration, and generated evidence.
2. Confirm that every untracked active module and test is intentional. Remove nothing merely
   because it is untracked.
3. Create reviewable commits that preserve the current research runtime hash and frozen evidence,
   or perform an explicit evidence migration if that hash must change.
4. Set a real upstream for `main`, push, and independently verify the remote object IDs. This
   requires explicit operator approval.
5. Run `.venv/bin/python -m tools.release_manifest` from a clean candidate checkout and retain its
   JSON output with the release. The tool now covers Git commit/tree/working-tree identity, Python
   and UI lockfiles, research runtime, prospective evidence, experiment and strategy
   registrations, execution profiles, schema-defining source, the read-only DuckDB catalog
   schema, service units, and schedule source. It reads no application rows and fails closed for
   dirty, incomplete, or untracked required state; `--allow-dirty` produces a diagnostic snapshot
   that remains explicitly non-releasable. Database contents, backup integrity, and installed
   host state remain separate restore proofs. General Git symlinks are identity-bound by path and
   target, but every named release-critical input and its in-checkout parent path must be regular;
   a link to matching external bytes is incomplete. Any symlink anywhere inside the protected
   research runtime also invalidates its release identity rather than hashing external source.
6. Create an encrypted, off-machine, transactionally consistent database backup and an integrity
   manifest. The local create/verify mechanism is now `.venv/bin/python -m tools.backup_database`;
   encryption, retention, and off-machine storage still require operator-selected storage and
   credentials.
7. Use the versioned, idempotent `.venv/bin/python -m tools.install_automation --apply`
   deployment command to install the exact service units and six-entry managed cron block. Its
   default mode is a read-only drift audit; apply mode preserves unrelated cron lines, rejects
   malformed managed blocks, restarts only changed units, and verifies scheduler health.
8. Restore onto a second personal machine or isolated directory, install from locked
   dependencies, run all quality gates, load the database read-only, and compare the release and
   evidence identities.
9. Start the restored API/UI in submission-disabled paper mode and confirm the health,
   scheduler, forward-monitor, and paper-state projections.
10. Record the drill result in a new dated audit. Do not rewrite this snapshot.

## Work not performed

- No files were staged, committed, or pushed.
- No remote branch or backup destination was configured.
- No database backup was created.
- At initial audit time, no service or cron configuration was changed. The subsequent update below
  changed only how the same six trading-engine cron entries are managed.
- No ignored caches, logs, or runtime files were deleted.
- No frozen strategy, simulator, execution profile, or research evidence was changed.

Until the closure sequence passes, Workstream A's exit gate remains **not met**.

## Same-day closure update — automation installation

The versioned `tools.install_automation` command was added and applied after the initial snapshot.
It migrated the same five production entries and one auxiliary postflight entry into a marked,
tool-owned block while preserving unrelated news-scraper entries and retired-workflow comments.
Both service units already matched and were not rewritten or restarted. A second read-only audit
returned `ok` with no planned changes; the live scheduler remained `ok` at production 5/5 plus
postflight 1/1. Closure-sequence item 7 is implemented and exercised on this host, but remains
unrecoverable from a clean checkout until the new tool, units, and related source are reviewed and
committed. Items 3, 4, 6, 8, 9, and 10 remain open.

## Same-day closure update — local backup mechanism

`tools.backup_database` now creates a private bundle only at an explicit destination outside the
checkout. It refuses overwrite atomically at publication time, acquires every cooperating scheduled-writer lock plus queue and
backup locks without waiting, uses DuckDB's database-copy operation, and publishes atomically only
after verification. Its manifest binds every table count, catalog identity, latest price date,
queue states, active portfolio identity, the three prospective checkpoints, database bytes, and
release identity. A separate `verify` command reopens the copied database read-only and checks all
recorded hashes and invariants, including fail-closed evidence paths. The release manifest binds
the complete local dependency closure loaded by the recovery entry point, including the nightly
and report semantic validators and their helpers, rather than only the entry-point file.

This implements the local mechanism needed by item 6; it does not complete that item. No encryption,
retention policy, off-machine destination, independent-machine restore, or credential configuration
has been selected. Those boundaries remain explicit so a local copy cannot be mislabeled disaster
recovery. Items 3, 4, 6, 8, 9, and 10 remain open.

The mechanism was then exercised once against the 3.6 GB live store, well before the Friday
nightly window. It atomically published an owner-private local bundle outside the checkout and a
second process verified its 3,655,872,512-byte database, 28 tables, three evidence files, and
manifest. The snapshot retained 475 jobs, 1,064 orders, 1,039 fills, zero pending/running jobs, and
the protected 111-file research identity. The live ledger remained identical, both services kept
zero restarts, scheduler health remained 5/5 plus 1/1, and no temporary publication directory was
left behind. This is useful restore material on the same disk, but it is neither encrypted nor
off-machine and therefore does not close item 6.

## Same-day closure update — isolated read-only application drill

The verified local bundle was then exercised through a separate API process on loopback port
18000, with `TRADING_ENGINE_DB` pointed at the bundled `market.duckdb` and
`TRADING_ENGINE_DATA_DIR` pointed at the bundled evidence tree. Eight read-only endpoints returned
HTTP 200: `/health`, `/meta`, `/research/readiness`, `/league`, `/positions`, `/orders`, `/journal`,
and `/tickets/context`. Health reported the backup database path, the restored latest price date was
2026-09-10, and the three forward projections remained honestly `ACCUMULATING`, `WAITING`, and
`ACCUMULATING`. The temporary server was terminated and port 18000 closed afterward. The production
API remained on the live database with zero restarts, and live ledger counts were unchanged.

This proves that the local database/evidence bundle can support the current checkout's read-only
application projections. It does not complete items 8–10: the drill reused this working tree and
environment, did not rebuild from reviewed committed source, did not exercise the service installer
against an isolated home, and did not run on an independent machine. No mutation endpoint was called
and no restored service was left running.

The already-built production Next.js server was subsequently started on loopback port 13000 with
its server-side API origin pointed at the backup API on port 18000. The dashboard, league,
positions, journal, and SPY candidate routes all returned HTTP 200; rendered output contained the
expected `ACCUMULATING`/`WAITING` research states and no application, fetch, or response-validation
error marker. Browser proxy configuration remains fixed to production port 8000, so the drill
intentionally exercised server rendering only and did not submit a browser mutation. Both temporary
processes were stopped and both ports closed. This strengthens the same-host application proof but
still does not replace a clean-checkout or independent-machine restore.

That drill exposed and then closed one isolation defect: the environment override originally
changed only server-rendered fetches while browser `/api/*` rewrites remained pinned to production
port 8000. A shared `api-origin.mjs` validator now configures both paths. It accepts only an explicit
`http://127.0.0.1:PORT` origin and fails build/start for credentials, paths, queries, fragments,
HTTPS, hostnames, wildcard binds, or remote hosts. The alternate-loopback production build passed,
and a second isolated run proved `/api/health`, `/api/meta`, and `/` all reached the backup API;
the proxied health payload named the bundled database. Both temporary processes were stopped.

## Same-day closure update — working-tree ownership

The recursive `tools.worktree_audit` inventory and
`docs/worktree-review-2026-09-11.md` now classify every individual changed path, including files
that ordinary short status collapses into an untracked directory. The review found no unknown
owner, empty untracked file, untracked symlink, or discard candidate. All active untracked modules,
tests/helpers, UI contracts, service units, documentation, and the dependency lock are intentional
and must be preserved. This completes the inventory and intent decisions in items 1 and 2, but it
does not stage or commit them. Items 3, 4, 6, 8, 9, and 10 remain open.

## 2026-09-12 update — operationally complete local bundle

A second same-host restore drill exposed a bounded schema-v1 omission: the copied database and
three prospective checkpoints served core read models, but `/meta` could not reconstruct the
current price-verification, Friday-postflight, or nightly-report state. The backup format is now
schema v2. In addition to the v1 content, it records and hashes exactly seven allowlisted files:
`data/_meta.json`, `logs/friday-postflight.json`, `data/screens/latest.md`, the date-bound screen
Markdown and CSV selected from the snapshot's `latest_price_date`, and the league Markdown and
CSV. They are restored under `evidence/<original-relative-path>`. The verifier remains compatible
with existing schema-v1 bundles, while v2 fails closed on missing, unexpected, remapped, symlinked,
non-private, or byte-altered operational artifacts. Across both schema versions, verification also
rejects any unmanifested file, directory, symlink, or special node anywhere in the bundle. Every
bundle directory is created as `0700`, and verification rejects a non-owner-private directory at
any depth. It also reuses the API's read-only nightly validator: metadata and screen counts/policy, latest and
dated screen Markdown, active league membership and stale marks, and the complete league CSV must
agree with the copied DuckDB snapshot. Re-hashing a mixed set of otherwise well-formed files
cannot make that bundle verify.
Independent verification also anchors the public bundle path. It opens each absolute parent
component and the bundle root without following symlinks, retains that root descriptor for every
verification phase, and compares the complete descriptor-rooted tree's inode, type, size,
modification-time, and change-time identity before and after those phases. Before reporting
success it re-traverses the visible no-follow parent chain and requires the requested pathname to
still name the retained root. Deterministic regressions replace the root with a byte-identical
valid bundle after manifest loading and replace a nested operational artifact with identical
bytes after evidence verification; both operations are now detected instead of producing `ok`.
A further regression swaps in different operational bytes only for semantic reconciliation and
restores the original file before the final tree scan; its changed filesystem identity is still
detected. Initial symlinks in the public bundle's parent chain are also rejected.
Creation now also holds the shared `data/_meta.json.lock` for the full snapshot window in addition
to every scheduled-driver, queue-drain, and backup lock. Direct metadata producers therefore
cannot replace `_meta.json` between the database copy and semantic validation; lock contention
fails closed before publication and leaves no destination behind. Lock files are opened without
following the final symlink and must be regular files beneath non-symlinked directory paths; an
unsafe lock node or parent fails before the database copy starts.
Prospective and operational source artifacts are likewise opened by descriptor-relative traversal
without following any path-component symlink. Each must be a regular file no larger than 1 MiB;
descriptor and pathname identity, size, modification time, and change time must remain stable
through the bounded read. Platforms without the required no-follow/directory-open primitives fail
closed rather than silently weakening this guarantee.
Every canonical source-parent component and the database leaf are also opened without following
symlinks after all cooperating locks are held, and DuckDB copies through `/proc/self/fd`. The
source descriptor identity and metadata must remain stable
and must still match the requested source pathname before and after publication. Re-traversing the
visible parent chain without following symlinks must also reach the retained parent descriptor.
Release schema
identity is read from that same descriptor while retaining the requested source location in the
manifest.
Deterministic tests replace the pathname with another valid DuckDB file and mutate the original
file's metadata after copying; both cases abort before publication. Another replaces the source
during publication and proves the command reports failure while preserving the verified published
bundle. A parent-symlink swap immediately before traversal also fails closed.
Replacing the source parent with a symlink back to the original directory after copying likewise
fails, even though the final database inode is otherwise unchanged.
Destination handling canonicalizes only the parent and never resolves through an absent final
leaf. It opens that parent without following a symlink and retains the descriptor for private
temporary-directory creation, atomic no-replace publication, cleanup, and final synchronization.
The random private temporary directory also remains open by descriptor for all writes,
verification, and root synchronization, and its parent entry must retain the opened inode before
publication. Linux `/proc/self/fd` descriptor traversal and `renameat2` no-replace publication are
required; unavailable primitives fail closed and an unchanged temporary entry is cleaned.
The fully verified pre-publication result remains valid across the rename, so creation does not
reopen the published bundle by its potentially replaced pathname. The opened directory identity
must still match the visible parent before and after publication.
A file, directory, or symlink inserted at the final leaf is preserved and causes failure. A parent
pathname replaced before publication receives no bundle, while cleanup still occurs in the
original anchored directory. Replacement detected after publication reports failure and preserves
the verified bundle in that original directory for inspection. Pre-publication exceptions and
Python process interruptions also clean an unchanged temporary bundle through the retained
descriptor. If its entry was replaced, cleanup preserves the replacement and displaced private
tree for explicit inspection rather than risking deletion of the wrong object; published recovery
data is never removed by that cleanup. After verification, every bundle file
and directory is synchronized before publication and the retained destination-parent descriptor
is synchronized afterward; success therefore includes an explicit local-filesystem durability
barrier.

The retained original schema-v1 bundle still verifies with database SHA-256
`2641cc29d604eb1993e566373f52bc427a1a3e246b53c9103fddd56f26b1ede8`, manifest SHA-256
`f6daba9600a69a79ecca147ce1a7ec18de263b94aeb9a196a53ef350f04d0542`, 28 tables, three
prospective files, and zero operational artifacts. A fresh v2 bundle was then created at
`/data00/home/jun.ong/trading-engine-restore-drill.Uol8Ay/bundle-v2`, copied independently to
`restored-v2`, and both copies verified with database SHA-256
`5e085f45c4baaf82480ef8af8232f6735cc1097bf002a801102a4fec7f68df28`, manifest SHA-256
`7eeb18ba654ebd6a3c66c031494a6eaf97be362d485328db1fc6335227dd6ae3`, 3,702,796,288 database
bytes, 28 tables, three prospective files, and seven operational artifacts.

A temporary API on loopback port 18000 used only the copied v2 database and
`restored-v2/evidence/data`. `/health`, `/meta`, `/research/readiness`, `/league`, `/positions`,
`/orders`, `/journal`, and `/tickets/context` returned successfully. Restored monitoring remained
honest: nightly evidence and Friday postflight were `current`, price verification remained
`issues` with 17 material disagreements, and forward families remained paper-only with no ready
research family. The copied database held 479 jobs, 1,120 orders, 1,039 fills, 21 active
portfolios, and no pending/running job. A hostile Host header returned HTTP 400. The temporary API
was then stopped.

This closes the operational-artifact defect in the local bundle format and proves a successful
isolated-directory restore with the current checkout. It does not prove encryption, retention,
clean-checkout reconstruction, source review/commit, service installation in an isolated home,
or independent-machine/off-machine recovery. Those portions of items 3, 4, 6, and 8–10 remain
open; the roughly 14 GB retained drill directory must remain available until this work is handed
off or deliberately superseded.
