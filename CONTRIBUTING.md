# Contributing

This is one person's research engine, published so the methodology can be read and
reused. Issues and pull requests are welcome; expect slow replies.

- **Read `docs/how-it-works.md` first.** The honesty rules there are not negotiable:
  never invent a price, point-in-time tables are append-only, no same-bar fills,
  every strategy is pre-registered with a kill criterion before evidence accrues.
- **Tests:** `.venv/bin/python -m pytest -q -W error` must pass. Tests use in-memory DuckDB only and
  never touch a live store or the network. Run `npm test` from `ui/` for the dependency-free UI
  response-contract tests.
- **Lint:** `.venv/bin/ruff check .` must pass. The API and operator-tool layers additionally
  enforce `.venv/bin/ruff check --select C90 server tools` and
  `.venv/bin/ruff check --select PLW2901,RET504 server tools`, keeping complexity bounded, raw
  database or filesystem values distinct from their validated public forms, and return paths free
  of dead intermediates. All executable source additionally
  enforces `.venv/bin/ruff check --select S101 engine farm sim server tools`; this keeps
  fail-closed runtime and proof guards active under optimized Python. This wider gate was
  introduced with an explicit protected-source transition after the remaining research assertions
  were replaced. Ruff
  formatting is not yet a repository gate; avoid a bulk formatter pass over protected research source unless its evidence migration is explicit.
  CI also byte-compiles every active Python package, including the source-run `tools/` package.
- **Dependency audit:** runtime Python dependencies must pass the pinned `pip-audit` CI step,
  and UI production dependencies must pass `npm audit --omit=dev --audit-level=moderate`.
  Dependabot proposes grouped weekly minor/patch updates for the root `uv` environment, GitHub
  Actions, and the `ui/` npm tree; major updates remain separate, and nothing is automatically
  merged or deployed. The CI workflow itself has read-only repository contents permission.
- **Environment:** `uv sync --extra dev --frozen` installs the editable project, locked runtime
  dependencies, pytest, and Ruff. Runtime-only installs do not pull test tooling; update and
  commit `uv.lock` deliberately whenever dependency declarations change.
- **Release identity:** `.venv/bin/python -m tools.release_manifest` emits a deterministic,
  read-only JSON identity covering Git and working-tree content, dependency locks, prospective
  evidence, experiment and strategy registrations, execution profiles, schema source, the
  DuckDB catalog schema, service units, and scheduler source. It exits nonzero for a dirty or
  incomplete tree. Named release-critical inputs and every parent path inside the checkout must be
  regular, non-symlinked entries; matching target bytes do not satisfy identity. Any symlink inside
  the protected research runtime also invalidates that runtime identity. Release-critical and
  ordinary working-tree file bytes are read through stable no-follow leaf and parent descriptors;
  a post-check symlink, FIFO, or concurrent replacement fails closed without following or blocking.
  Git-visible symlink target text is read relative to the same stable parent boundary without
  following the target, and a changing symlink is likewise rejected.
  Private before/after
  filesystem metadata snapshots cover every Git-visible file and parent while the manifest is
  built, so a transient modification cannot combine hashes from different tree states; this
  machine-specific metadata is never serialized into the reproducible manifest. The protected
  research runtime is independently hashed again at the end, covering executable source even when
  an ignored path is outside Git's inventory. Git commit, tree, branch, status count, and
  required-file tracking identity are also re-read before success, so a concurrent ref or index
  transition cannot be combined with the earlier source scan. Public DuckDB
  schema inspection opens every absolute parent and the database leaf without following symlinks,
  reads through the retained descriptor, and requires the leaf and visible parent chain to remain
  identity-stable during that read. A separate private snapshot retains full metadata for the leaf
  and device/inode identity for every parent component across the complete manifest build. Ordinary
  child-entry churn in a shared ancestor or DuckDB lock/WAL churn in the immediate directory
  therefore cannot create a false unsafe result, while a replaced path component, an ignored
  database changed after schema inspection, or a database absent initially and created during the
  scan still invalidates the result. `--allow-dirty` is diagnostic only:
  its output remains explicitly `non-releasable` and must not be treated as release certification.
  It reads no application rows and does not inspect credentials, contact remotes, or inspect
  installed services/crontab.
- **Worktree ownership:** `.venv/bin/python -m tools.worktree_audit --strict` recursively expands
  untracked directories and classifies every changed path. It fails for a nonempty index, an
  unknown ownership class, an unsafe or unstable untracked path, or incomplete protected research
  identity, and reports empty untracked regular files for review. Git-reported untracked leaves are
  classified through repeated no-follow metadata observations; symlinks, special nodes,
  replacements, and disappearances fail closed. Git's recursive porcelain inventory must also
  remain byte-identical across the audit. It never stages, deletes, or rewrites a file.
  A green result is an inventory gate, not a clean-tree or release claim.
- **Automation deployment:** `.venv/bin/python -m tools.install_automation` is read-only and
  reports service-source, enabled/active, user-lingering, and cron drift. The explicit `--apply`
  form preserves unrelated crontab lines, owns only its marked six-entry block, installs versioned
  user units, restarts only changed services, starts stopped units, enables lingering when needed,
  and verifies scheduler health. Unit sources, cron drivers, and the postflight verifier must be
  regular files reached through non-symlinked repository paths; installed unit copies must also be
  independent regular files. A linked installed unit is visible as drift, while a linked parent of
  the user unit directory is invalid and never written through. An inactive or disabled system cron
  daemon, non-UTC timezone, unwritable/symlinked log directory, or managed cron log target that
  exists as anything other than a regular non-symlink file is an invalid host prerequisite and
  requires separate operator/admin repair. Do not hand-edit inside its managed block. Apply mode
  re-plans immediately before mutation so stale dry-run state cannot authorize a write or discard an
  intervening unrelated crontab edit. Its plan records six launch-source hashes and two versioned
  unit-source hashes; apply reads all eight sources through bounded no-follow descriptors and
  revalidates all eight sources before mutation. Cron-source read/execute access is checked relative
  to the same anchored parent as its stable read, and permission drift around that check is rejected.
  Installed-unit comparison and atomic publication
  of pinned bytes share one retained descriptor for the user-unit directory. Identity checks detect
  symlink or ordinary-directory substitution before any cron or service-manager mutation. Apply
  reads and merges the latest crontab immediately before replacement, rechecks lingering and service
  enabled/active state at the mutation boundary, and reports any late repair. A fully converged apply
  issues no mutating systemd command. Native `crontab` has no compare-and-swap operation, so avoid
  editing the same user crontab during its final replacement command. The live `/meta.scheduler`
  launch audit also traverses each repository-owned driver, postflight module, and the `logs/`
  directory through no-follow descriptors, checks access against the opened object, and requires a
  second traversal to retain the same parent and leaf identity. A concurrent ordinary-file or
  directory replacement therefore fails closed rather than yielding a transient healthy result.
  Existing managed log targets use the same stable descriptor inspection; an absent target is
  allowed only when it remains absent across the probe so cron can create it normally. Existing
  logs may append normally during inspection, but their inode and file type must remain stable.
  The virtual-environment Python remains an intentionally supported interpreter symlink and is
  checked for executability separately.
- **Database recovery:** create a private, transactionally consistent bundle outside the checkout
  with `.venv/bin/python -m tools.backup_database create /absolute/backup/path`, then independently
  check it with `.venv/bin/python -m tools.backup_database verify /absolute/backup/path`. Creation
  canonicalizes only the destination parent and retains one no-follow descriptor for it through
  temporary creation, publication, cleanup, and synchronization. The private temporary bundle is
  also opened once without following a symlink; creation writes and verifies through that
  descriptor and requires its parent entry to retain the same inode. It refuses a pre-existing or
  concurrently inserted destination leaf, syncs the verified bundle, publishes with atomic no-replace
  semantics relative to the descriptor, and syncs that descriptor. Linux `/proc/self/fd` and
  `renameat2` no-replace support are required; unavailable primitives fail closed. Replacing the visible parent
  before publication aborts and cleans the temporary bundle from the original directory without
  writing into the replacement; replacement detected after publication reports failure while
  preserving the verified bundle in the original directory for inspection. Exceptions and Python
  process interruptions clean unchanged unpublished temporary bundles through the retained
  descriptor. If a temporary entry was replaced, cleanup preserves both ambiguous private trees
  for inspection instead of deleting either; it never removes an already published destination.
  It acquires all cooperating driver,
  metadata,
  queue, and backup locks, copies the DuckDB catalog and data with
  DuckDB itself, and preserves the three prospective checkpoints plus release identity. Schema v2
  also preserves seven exact operational artifacts: collector metadata, Friday postflight, latest
  and date-bound screen outputs, and league Markdown/CSV. Their layout beneath `evidence/` is
  directly usable as a restored `TRADING_ENGINE_DATA_DIR`; verification remains compatible with
  schema-v1 bundles that predate them. Independent verification opens every absolute bundle-parent
  component and the root without following symlinks, retains the root descriptor for all reads,
  snapshots the inode, type, size, and timestamps of the exact descriptor-rooted tree before and
  after verification, and finally requires the visible path to identify the same root and parent
  chain. A root or nested-entry replacement during verification therefore fails even when the
  replacement has identical bytes. Verification also rejects symlinked bundles, manifests,
  databases, evidence paths, and dangling destination links so a passing bundle is self-contained.
  Manifest creation times must use the producer's canonical UTC `datetime.isoformat()` spelling,
  rather than a parser-equivalent alternate form. Repository-contained source locations likewise
  require the producer's canonical nonempty relative POSIX path, without normalized aliases.
  It requires owner-only permissions on the bundle root,
  every directory below it, and sensitive files, and validates the exact manifest and
  release-identity schema instead of
  accepting missing or malformed recovery metadata. Recorded sizes and snapshot counts must be
  non-negative integers (booleans and fractions are invalid), while hashes and the latest-price
  date must use their canonical formats. V2 rejects missing, unexpected, remapped, symlinked, or
  altered operational artifacts and any unmanifested bundle file, directory, symlink, or special
  node.
  Lock paths must be regular non-symlink files and their parents must be non-symlinked directories;
  an unsafe lock path aborts before any snapshot is published.
  After those locks are held, creation opens every canonical source-parent component and the
  database leaf without following symlinks; DuckDB copies and identifies its schema through the
  retained file descriptor. Its
  inode, size, modification time, and change time must remain stable and match the requested source
  pathname before and after publication; the visible no-follow parent chain must also retain the
  opened parent identity. Replacement or in-place mutation before publication
  cleans the temporary bundle; detection after publication reports failure and preserves the
  verified bundle for inspection.
  Evidence sources use descriptor-relative no-follow traversal, must be regular files no larger
  than 1 MiB, and must remain stable for the bounded read.
  If the final parent-directory sync fails after publication, creation reports failure but
  preserves the already verified bundle for explicit inspection; it never deletes published
  recovery data while durability is uncertain.
  It also reconciles v2 screen metadata and screen/league reports against the copied database, so
  fresh hashes cannot legitimize a semantically mixed snapshot.
  The tool does not encrypt,
  upload, schedule, or select an off-machine destination; those remain explicit operator decisions.
  Never treat an unverified local bundle as disaster recovery.
- **Prove by running, not by inspection.** A PR that changes the simulator, the
  screen or the fill model should show a before/after replay.
- **Audit evidence migrations:** save the active result JSON before a required
  walk-forward refresh, then run
  `.venv/bin/python tools/audit_walkforward_migration.py BEFORE_DIR data/reports/walkforward/results`.
  Exit 0 permits only data/source/Git/timestamp and declared runtime fields to differ; exit 1
  lists every additional diagnostic or economic JSON path. Review and document those differences
  instead of broadening the allowlist to make a migration pass. The auditor recomputes each
  snapshot digest from its canonical `tables` payload, so a well-formed but false SHA-256 is not
  accepted as provenance; duplicate JSON keys are rejected as ambiguous. Both cohort directory
  chains are retained without following symlinks, every `.json` leaf must be a bounded regular
  file, and the inventories, file identities, and bytes must remain stable through the complete
  comparison. For a material migration,
  retain immutable copies of both compared cohorts under `data/reports/walkforward/migrations/`;
  the live `results/` directory is replaced by later scheduled runs.
- **Data:** the repo ships no market data. `store/`, `data/eod/`, `data/screens/`
  are regenerated locally by the nightly.
- **No broker code.** Execution against real money is out of scope by design.
