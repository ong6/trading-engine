# Operational source amendments — 2026-10-05

P21 explicitly admits infrastructure corrections and behavior-preserving complexity work.
No registered strategy, scoring constant, limit, cohort outcome, label, book rule, look, activation
clock or schedule changes. No production model call is used for the rehearsal.

## Earlier evidence path: P15 revision 11

Revision 10 and its exact source files remain reproducible at commit `46bd665`. Revision 11
binds the source commit recorded in `server/p15-registration.json` and its full dependency map.
It covers complete independent-price receipts and explicit symbol/nonfinite/schema checks,
corrected request pacing after delayed wakeups and named helper extraction in
evidence/scoring/pre-open/capture code. Malformed source refusals retain exact response bytes;
public receipt references are relative. Optional TradingView failures become missing cross-checks.
Explicit provider `symbol_error`/`series_error` responses complete the raw transcript immediately;
capture retains it before classifying the symbol as unavailable. No price row or retry is added.

The complete Linux run exposed the collector's existing whole-file dependency in the frozen XS
forward record. `engine/collect.py` is restored byte-for-byte to the baseline, preserving that
record's exact source hash and all published boundaries. Complete listing recovery instead lives
in the explicit `engine.history_recovery` maintenance command: no runtime wrapper or new schedule,
no stored-price overwrite, and no mark as complete when prior-incarnation rows or overlapping
prices conflict. Its output retains the provider metadata and normalized coverage used.

The registration tests verify unchanged runtime constants and a complete local dependency
closure in addition to every file hash and the committed source identity. The focused
registration/evaluation/pre-open/scoring/verifier/account and operating-contract fixture rehearsal
passed 127 cases after independent review corrections.
Original written evidence is unchanged. New source hashes are disclosed because operational
behavior was corrected; they are not silently substituted into older research registrations.
Any private consumer freezing one of these files needs its own explicit dependency decision.

## Inactive execution research: P16 source amendment

P16 remains inactive. The only contract payload change is
`execution_realism.code_sha256.tradingview_5m`, binding the refactored adapter. Its nested
`registration_sha256` and the outer contract digest are recomputed from their complete payloads.
The old contract and original adapter remain reproducible at `46bd665`; other registration
fields are equal. This grants no execution authority and starts no producer.

The adapter refactor is checked against the original with nine mocked-network cases: exact
transcript serialization, heartbeat handling after completion, binary/protocol failures,
transport timeout/error, deadline, and outbound/inbound/final-size limits. Both source versions
pass the same cases. The 12 other P16 modules use helper extraction without contract changes;
144 focused tests passed before integration. All 32 previously reported server/tools advisory
complexity findings are removed at the existing threshold of ten, with no exemptions.

## Deployment gate

Independent functional review and the complete supported-Linux suite passed at `184a127`
(4,381 tests). Publication checks then caught a redundant return assignment in the standalone
capture pacing helper. Its behavior-identical correction passes all CI Ruff selectors and 41
focused source/capture/registration tests; it changes no registered dependency. Both timezone CI runs and UI checks passed at `bdfa24d` and `4a6d050`. The ordinary macOS release-manifest tests rely on Linux `/proc`
filesystem identity and do not provide supported-host release proof. Revision 11 was deployed on 2026-10-05; API and UI restarted successfully and health checks passed.
All 135 source bindings were independently verified, while the frozen XS collector stayed byte-identical.
The later history-metadata Mapping correction is outside the registered dependency closure.
P16 remains registered but inactive; these infrastructure updates grant no new execution authority.

## P15 revision 12 — complete recovery metadata

The recorded daily backup exposed the recovery helper's 1 MiB limit for the complete
`data/_meta.json` snapshot. Its existing locked-copy fallback preserved logical database
recovery; that result did not establish a verified operational bundle. Revision 12 binds
source commit `de071fc995aefef6172ff76c52e7dc4afb2e5819` for the narrow correction.
Both descriptor-based copying and operational verification now admit this exact metadata
path up to 8 MiB, matching the existing snapshot contract. Other artifacts retain 1 MiB caps.

The dependency set remains 135 paths. Only `tools/backup_database.py` changes its source pin;
revision number/reason, source commit and the complete registration digest are updated through
the established amendment path. The exact source-commit assertion remains enforced. All other
registration fields are byte-equivalent as parsed values, including policy, activation clock,
books, scoring values, labels, gates, delivery and schedules. The research runtime remains
`e533fb3b2cbb71a883fdb88ff4af0b6257676575c4e7bc0bfb80df4cf0373c4e` across 202 source files, and the frozen collector is unchanged.

Independent backup regression acceptance and the normal P15 registration/operating rehearsal
are required before publication. No production model-policy call, activation or schedule change
is part of that rehearsal. Revision 11 and its original source commit remain reproducible.
