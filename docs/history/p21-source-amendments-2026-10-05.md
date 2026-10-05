# Operational source amendments — 2026-10-05

P21 explicitly admits infrastructure corrections and behavior-preserving complexity work.
No registered strategy, scoring constant, limit, cohort outcome, label, book rule, look, activation
clock or schedule changes. No production model call is used for the rehearsal.

## Active evidence path: P15 revision 11

Revision 10 and its exact source files remain reproducible at commit `46bd665`. Revision 11
binds the source commit recorded in `server/p15-registration.json` and its full dependency map.
It covers complete independent-price receipts and explicit symbol/nonfinite checks, corrected
request pacing after delayed wakeups, a full-history fallback that proves completed listing
coverage, and named helper extraction in evidence/scoring/pre-open/capture code.

The registration tests verify unchanged runtime constants and a complete local dependency
closure in addition to every file hash and the committed source identity. The focused
registration/evaluation/pre-open/scoring/verifier/account fixture rehearsal passed 99 cases.
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

Independent functional review, a complete supported-Linux suite and normal publication checks
still precede live deployment. The ordinary macOS release-manifest tests rely on Linux `/proc`
filesystem identity and do not provide supported-host release proof. Source and registration
amendments are prepared here; a fixture rehearsal alone is not production activation.
