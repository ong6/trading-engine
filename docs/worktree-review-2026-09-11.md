# Working-tree ownership review — 2026-09-11

> **Historical snapshot.** This records the local implementation as inspected on 2026-09-11,
> layered over Git commit `ae227637e627a71ecc2700002d21204f85262021`.
> Counts below are provenance, not current status. Run the strict audit and release manifest
> commands below for the live tree.

This snapshot does not turn uncommitted files into a release, an off-machine copy, or evidence
that a strategy is profitable.

## Decision

At the snapshot boundary, every changed path had an identified owner, the Git index was empty, and
no untracked path was an unknown temporary file. The reviewed untracked modules, tests, service
units, documentation, and lockfile were intentional parts of the implementation and had to be
preserved. No discard candidate was found. That tree was nevertheless not clean or recoverable
from `HEAD`: 22 release-required files remained untracked, all local changes still needed
reviewable commits, and `main` had no usable upstream.

The authoritative current recursive inventory is:

```bash
.venv/bin/python -m tools.worktree_audit --strict
```

Unlike default short status, this expands every file inside an untracked directory. Strict mode
fails if the index is nonempty, any path lacks an ownership class, an untracked path is a symlink,
or the protected research identity is incomplete. Current schema-v3 audits also fail closed for
Git-reported untracked special or unstable paths and for a changing Git inventory. They separately list empty untracked regular
files for review. It is read-only: it does not stage, commit, delete, format, or rewrite files.

## Snapshot

The 2026-09-11 completed inventory contained 336 paths: 102 tracked modifications and 234
untracked files.

| Owner | Changed | Untracked | Review conclusion |
|---|---:|---:|---|
| Protected research (`engine/`, `farm/`, `sim/`, `pyproject.toml`) | 62 | 21 | Preserve byte-for-byte while its published evidence is active. |
| Support/API and operator tools | 64 | 59 | Active imports, API owners, service units, monitors, and versioned operator tools. |
| Tests and shared test helpers | 102 | 88 | Collected by the current warnings-as-errors suite. |
| UI | 70 | 53 | Runtime contract modules, seven UI suites, and the versioned UI service. |
| Documentation/configuration | 37 | 13 | Current guides, dated evidence, CI/Dependabot, and the locked dependency graph. |
| Generated evidence | 1 | 0 | Tracked nightly metadata; renderer ownership is preserved. |

There are zero staged paths, zero unknown-owner paths, zero untracked symlinks, and zero empty
untracked files. Ignored `build/`, `dist/`, `*.egg-info/`, `ui/.next/`, and `scratch/` contents are
reproducible or local diagnostic state and are not release inputs. Their presence does not explain
or reduce the 336 reviewable paths.

## Why the untracked source is intentional

- The 21 protected research files participate in the exact 111-file runtime identity
  `2876fdc6e5d36e532b535fb229dcbb653fba6077f4d5f7fe01b63db581cc6c53`. The current 18-artifact
  cohort carries that same identity. Removing or rewriting one would invalidate current evidence.
- The support/API set is imported by the running API, scheduler and evidence projections, or the
  operator tools. Its shared host-command runner is a release-critical scheduler source. API and UI
  service-unit tests compare the versioned unit bytes to deployment.
- Pytest recursively collects every `tests/test_*.py` module. The five non-test helpers are imported
  by their owning suites. Full warnings-as-errors verification passed after the inventory tool was
  added.
- The UI contract modules are imported by the application or its seven Node test suites. All 31 UI
  tests and the production build pass.
- The untracked root `uv.lock` is required by frozen environment installation and passes
  `uv lock --check`; the release manifest already fails closed while it is untracked.
- Release identity construction now requires one coherent scan rather than merely equal starting
  and ending bytes. Private before/after filesystem metadata covers every Git-visible file and
  parent, so a required file changed only during one named-group hash still makes identity
  incomplete; this host-specific metadata is not serialized into the reproducible manifest.
  A separate final protected-runtime hash covers ignored Python/shell source outside Git's visible
  inventory and reports `research-runtime-changed-during-scan` if that identity differs.
  Git commit, tree, branch, status/count state, and required-file tracking identity are also
  re-read before return; a concurrent empty commit now reports
  `git-identity-changed-during-scan` even though no working-tree bytes changed.
  Public DuckDB schema inspection traverses every absolute parent and opens the database leaf
  without following symlinks, reads through the retained descriptor, and rejects leaf, metadata,
  or parent-chain replacement during catalog inspection. A private complete-parent-chain/leaf
  identity snapshot also spans the complete manifest build: full metadata binds the database leaf,
  while device/inode identity binds every parent without mistaking unrelated shared-ancestor child
  churn for path replacement. It covers a post-catalog change to the ignored database and transient
  immediate-parent or higher-ancestor swaps that are restored before return. A database absent at the initial observation but created before catalog inspection also
  fails as a changed path; a database that remains absent retains the distinct `database-missing`
  reason. Backup creation's internal schema read remains attached to its separately secured source
  descriptor.
- Recovery identity covers the complete local module closure loaded by the backup entry point,
  including its nightly/report semantic validators and their helpers. It therefore changes when
  recovery meaning changes, not only when `tools/backup_database.py` changes. A source-level test
  recursively resolves local imports and requires that declared closure to remain exact.
- New documentation and configuration files are linked from current indexes or covered by parsed
  documentation/configuration tests. Dated documents remain provenance snapshots rather than live
  status authorities.

This establishes intent and ownership, not correctness by inspection. Correctness evidence remains
the full test/build/audit suite and live invariants recorded in `BUILDLOG.md`.

## Required commit sequence

No staging or commit was performed during this review. To avoid one unreviewable mega-commit, use
the ownership boundary and preserve dependency order:

1. dependency lock, packaging, CI, and shared provenance/data-quality infrastructure;
2. execution model and protected research runtime, with the existing fingerprint and migration
   evidence explicitly retained;
3. support/API read models, monitors, tickets, and operator tools;
4. UI contracts, pages, and versioned service units;
5. tests and helpers paired with the source they prove;
6. documentation/configuration and generated evidence, without hand-editing renderer-owned report
   indexes;
7. run the full verification suite, require an empty index after each dry-run check, then run the
   release manifest from a clean candidate checkout;
8. configure and verify an upstream only with explicit operator approval.

The split must be planned from diffs, not implemented by moving or deleting untracked files. Each
commit should be independently reviewable and should not leave the unattended nightly unable to
import a module it currently uses.
