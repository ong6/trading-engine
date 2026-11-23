# BUILDLOG — trading-engine

Implementation log in the v2 format defined in [`AGENTS.md`](AGENTS.md), newest entries at the
bottom. Older entries are archived in [`docs/history/`](docs/history/README.md):
[`buildlog-archive.md`](docs/history/buildlog-archive.md) (2026-09-18 to 2026-10-31) and the
earlier logs listed in that index.

<!-- buildlog-format-v2 -->
## 2026-11-01 — Try the Nasdaq ETF route when the stock route has no data

- **Why:** the issue-batch reproduction `pytest tests/test_verify_prices.py::test_stock_no_data_tries_etf_with_same_comparison_rules` fails: only the stocks route is called. Real BAR, DGP, FNGD and VXX requests return traded histories on the ETF route.
- **What:** try the ETF route after an explicit empty stocks answer; retain both exact responses and preserve the original named gap when both routes are empty.
  Apply the existing comparison and indicative-series rules to the fallback; no share-class alias or tolerance changes.
- **Evidence:** `pytest -q -W error tests/test_verify_prices.py tests/test_tradingview_history_archive.py` exits 0 at `[100%]`; real BAR, DGP, FNGD and VXX agree over five sessions each. Required tiers report only the two expected P15 hash and registration-identity failures.
- **Metrics:** product +19 LOC; server/tools unchanged (session snapshot).
- **Next:** orchestrator acceptance after the post-r21 registration.

## 2026-11-01 — Retry proven TradingView mappings with append-only attempts

- **Why:** `pytest tests/test_tradingview_history_archive.py::test_corrected_provider_retries_refused_window_without_editing_cohort` fails with `assert 0 == 1`; a terminal original prefix blocks a proven corrected route.
- **What:** use nine proven provider corrections while keeping frozen symbols and prior attempts; partition refusal retries by the requested provider symbol.
  Retain the standard receipt and require overlapping valid closes within the verifier's existing bands before retaining corrected facts. A failed proof appends a refusal.
- **Evidence:** `pytest -q -W error tests/test_verify_prices.py tests/test_tradingview_history_archive.py` exits 0 at `[100%]`; nine real corrected requests retain receipts and append attempts with all prior rows identical. Required tiers report only the two expected P15 hash and registration-identity failures.
- **Metrics:** product +84 LOC; server/tools unchanged (session snapshot).
- **Next:** orchestrator acceptance after the post-r21 registration.

## 2026-11-01 — Wait for scoring store locks through the registered deadline

- **Why:** P15 lock lane; reproduction: `.venv/bin/python -m pytest -q -W error tests/test_p15_scoring_locks.py -k waits_past_sixty` fails all four phases with a real writer held for 65 fake-clock seconds; a valid response becomes unavailable after the 60-second write wait expires.
  The same test's `finalization-65` case also reproduces a completed run after a final store wait reaches noon.
- **What:** Apply one monotonic budget ending at the unchanged 12:00 UTC deadline to scoring's advisory locks and store opens, including response retention and finalization.
  Keep the registered 60-second retry floor, completed-sample replay and interrupted-sample refusal unchanged; no registration re-pin or unit change.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 8` has 6,653 passes; only the expected `test_p15_registered_file_hashes_match_checkout` and `test_registration_identity_holds_in_this_checkout` fail on the un-re-pinned scoring source. All eight lock cases pass, including no late finalization trace.
- **Metrics:** server +19 LOC; tools/product unchanged; tests +159 LOC (session snapshot).
- **Next:** orchestrator acceptance and the post-r21 registration revision.

## 2026-11-01 — Isolate operations digest tests from checkout receipts

- **Why:** demonstrated defect: `TRADING_ENGINE_DB=<temporary store>/market.duckdb .venv/bin/python -m pytest -q -W error tests/test_ops_digest.py::test_report_lists_every_run_and_stage_against_the_schedules` passes without a snapshot, but with the published October 15 pre-open receipt fails `assert '- trading-engine-p15-preopen: due 10-15 13:05Z' in missing`. Reproduced before the fix.
- **What:** all report tests pass their temporary database path instead of reading a checkout's published snapshot.
  The direct snapshot-receipt test also passes its temporary log directory.
  The completed October 15 receipt correctly satisfies the due window; the digest needs no change.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -o addopts=--dist=worksteal tests/test_ops_digest.py::test_report_lists_every_run_and_stage_against_the_schedules` → `1 passed` with and without the temporary published snapshot after the fix.
- **Metrics:** server/tools/product unchanged for this session.
- **Next:** nothing admitted.
## 2026-11-01 — Report new TradingView refusals without calling them failures

- **Why:** the issue-batch monitor reproduction, `pytest -q tests/test_miner_monitor.py::test_tradingview_new_refusals_degrade_status_without_claiming_failure`, reports `assert 'current' == 'issues'` after 19 newly refused windows and no failures.
- **What:** degrade the miner status when a slice adds terminal provider refusals, with a distinct refusal reason. Keep settled cumulative refusals visible without degrading a clean later slice.
  Give real failed attempts and unresolved windows precedence over refusals; retain the existing response fields and verification tolerances.
- **Evidence:** `.venv/bin/python -m tools.affected_tests --run` and `.venv/bin/python -m pytest -q -W error -n 8` both exit 0 at `[100%]`; regressions cover new refusals, clean later slices, failures and unresolved windows.
- **Metrics:** server +6 LOC; tools/product unchanged (session snapshot).
- **Next:** orchestrator review of provider mapping defects in the pinned archive and verifier.
## 2026-11-01 — Distinguish a spin-off and an offering from share splits

- **Why:** split-data lane; `tools.check_invariants --snapshot latest --only one_split_basis_per_ticker --only split_recorded_vs_restated` reproduces CTVA 2026-10-01 `skipped_already_adjusted` and GRML 2026-08-26 `unrecorded`, one regression each. SEC filings describe a Vylor share distribution and GRML's $5 offering.
- **What:** accept only GRML's offering-day false positive, with an owner and expiry; its break-day bars equal the provider and the five-session volume medians explain the flag.
  The orchestrator accepts the existing split repair for CTVA: `outcome='applied'`, ratio 6.665 is a provider history factor for a spin-off, not a share split; no spin-off action kind exists, and Vylor shares are not modelled. There are no CTVA fills, orders or positions; share effects act on nothing. No live store or registered source is changed.
- **Evidence:** `tools.check_invariants --snapshot <repaired-copy> --only one_split_basis_per_ticker --only split_recorded_vs_restated --gate` → both pass, zero regressions; copy apply changed 1,848 CTVA rows and preserved every original. Fast tier and full suite pass; the three pre-existing October 28 publication-order regressions remain in the handoff.
  Fresh-copy E1, sector and XS read paths and published-prior continuity results are identical; all stay ACCUMULATING. CTVA's current XS rank improves from 2,620 to 730, outside the top 50; no active book newly selects it. Walk-forward evidence stays current, although the database checksum changes.
- **Metrics:** server/tools/product unchanged.
- **Next:** orchestrator applies the reviewed repair after the live dry run confirms 1,848 CTVA rows.

## 2026-11-01 — Disclose the lost October 28 P15 scoring evidence

- **Why:** reproduced on the published November 1 snapshot: `tools.check_invariants --gate` reports `publication_order: regression (3 regression(s), 0 baselined)`, one October 28 window per P15 book without completed scoring. The daily-opportunity restart loop held the store; run 22 ended `deadline_start_refusal`.
- **What:** baseline only those three subjects, owned by the orchestrator and expiring 2027-04-20. The gap is real: all 66 aggregate candidate decisions and their evaluation evidence were lost; seven completed samples survive orphaned, and two returned responses lost their durable payload and usage. Actual charges are unverified.
  October 28's six fills and all three cash/close marks reconcile; October 29 has no new entries or AI exits from this scoring run. Its AI book stayed unchanged; control/hybrid executed three deterministic exits with intents written after the open. Pre-open reviewed older intents; three event windows are absent and one call was interrupted.
  Rank evaluation excludes the missing decisions (`decision_unavailable`, origin 21); book metrics include both sessions. The published evaluation report does not disclose this gap. No evidence, prices, store rows, invariant or registered value changed.
- **Evidence:** `tools.check_invariants --snapshot <published snapshot> --gate` after disclosure reports `publication_order: pass (0 regression(s), 3 baselined)`; comparison preserves every invariant's facts and every other finding. The two existing market-data regressions remain.
- **Metrics:** server/tools/product unchanged.
- **Next:** orchestrator acceptance; evaluation disclosure and late-intent review are deferred.

## 2026-11-03 — Release price moves backed by unchanged history and completed actions

- **Why:** basis-release ruling; `.venv/bin/python -m pytest -q -W error -n 0 tests/test_basis_release.py` reproduces INTC and IOVA at `assert 0 == 22` and `assert 0 == 23`, despite twenty unchanged prior closes and completed action fetches.
- **What:** release only consecutive-close holds with twenty unchanged stored sessions in incoming history, no nearby captured corporate action and an action fetch completed successfully on or after the break. Keep existing revision tolerance, split-factor bands, scalar admission and split-revision holds.
  A split neither restated nor reported by its provider can pass this rule; `split_recorded_vs_restated` and `repair_integrity` remain the backstop. The source is stacked on the held revision 21 and is not deployed.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_basis_release.py tests/test_price_admission.py` exits 0 at `[100%]`; recorded-history replay releases 68/163 candidate holds and 0/6 backfill holds, using the published action snapshot.
- **Metrics:** product/engine +25 LOC; server/tools unchanged; tests +156 LOC against the branch base.
- **Next:** orchestrator acceptance and revision-21 deployment.

## 2026-11-03 — Audit the historical walk-forward timeouts without rewriting failures

- **Why:** P24 failure audit: the published snapshot and `/meta` still count 16 actionable jobs from October 19, each with `timeout: killed after 14400s`, after later weekly cohorts completed.
- **What:** Trace all 16 to the post-v2 replay slowdown and the inherited four-hour ceiling, already fixed by the queue isolation and offline dividend-projection changes.
  Eight have successful later book jobs; eight are obsolete after October 21 book retirements. Later anchors and runtime identities do not prove the original folds completed.
  Deliver per-job evidence and exact existing `engine.job_resolutions --kind cancelled` commands for the orchestrator to retire stale retries, retaining every failed row; no producer or read-model change is needed.
- **Evidence:** `PYTHONPATH=. .venv/bin/python "$WF_AUDIT_OUT/audit.py"` on the published snapshot and a jobs-only rehearsal: actionable 16 -> 0, historical 4 -> 20, failed=20 unchanged; all 1,005 job rows unchanged. The rehearsal database is removed.
- **Metrics:** server/tools/product unchanged.
- **Next:** orchestrator reviews and records the sixteen cancellation dispositions under the normal single-writer window; this lane makes no live-store write.
## 2026-11-03 — Trace pending fills to price-basis holds and provisional opens

- **Why:** stale-exposure lane; retained Yahoo bars checked against Nasdaq reproduce INTC and IOVA batches rejected despite unchanged historical prices: `admitted=0/5`, `basis_unverified` for both.
- **What:** identified the consecutive-close split-factor test as the hold: INTC fell 28.5761% on October 30; IOVA fell 35.4490% on October 29. Both match the existing band around 2/3, with no captured split action.
  ARX, BWET, IBTA, OGN and THG have November 2 bars stored with provisional open faults; Yahoo now supplies settled geometry. LXP and RAMP left the directory on November 2 and have no later provider bars; the existing five-session delisting rule first qualifies on November 6 if silence continues.
  No source or store changed. The defective admission rule is in pinned `engine/lib/db.py`, outside this lane's allowed paths; correction needs an orchestrator scope and release-rule ruling.
- **Evidence:** `PYTHONPATH=. .venv/bin/python -m pytest -q -s -W error -n 0 <session-output>/test_basis_hold_reproduction.py` → `2 failed in 0.77s`, each `assert 0 == 5`; all source bars pass scalar admission and the independent price comparison.
- **Metrics:** server/tools/product unchanged.
- **Next:** orchestrator admits the price-basis correction and its evidence-based release rule.

## 2026-11-11 — Keep schema-1 price readers on the generation hot file

- **Why:** the admitted revision-21 unblock; the new same-directory schema-1 reader test fails with `AssertionError: assert None == 1` because publication omits `schema_version`.
- **What:** publish schema-1 compatibility fields in the authenticated schema-2 manifest, pointing at the existing hot file; accept only a complete, matching compatibility pair.
  Keep generation byte verification, cold tables, lifetime pins and older schema-2 manifests working without another store copy.
- **Evidence:** `.venv/bin/python -m pytest -q -W error tests/test_publish_snapshot.py -k 'schema_one or compatibility'` → nine tests passed; the opened file's hash matches both manifest identities.
- **Metrics:** server unchanged; tools +3; product +9.
- **Next:** merge the three admitted stacked fixes, then one integrated re-pin.

## 2026-11-11 — Integrate and rehearse the revision-21 schema-1 unblock

- **Why:** the orchestrator admitted the November 3 schema-1 unblock proposal and the three stacked fixes; the new reader test reproduced the missing manifest field before the fix.
- **What:** merged current main and the P15 lock, ETF verifier/provider mapping and basis-release fixes, preserving their tests and log entries.
  Re-pinned revision 21 once through the existing runtime-then-registration sequence; all 169 P15 source files and E1/sector/XS digests agree, with registered rules unchanged.
  Published from a reduced real-data copy; the frozen reader accepted 59 latest-session rows and complete feature histories, and the opened hot file and generation hashes verified. Deleted the sandbox.
  Corrected the checklist's monthly confirmation gate and recorded both its layout and frozen-client refusals, the deploy disk shortfall, and the wider-history/expired-order operator steps.
- **Evidence:** `TZ=UTC .venv/bin/python -m pytest -q -W error -n 8` and the same command under `TZ=Asia/Singapore` → 6,700 passed each (270.42 s / 272.77 s); affected tests, Ruff, job audit and static schedule check pass.
- **Metrics:** session snapshot: server +19 LOC, tools +3, product +137.
- **Next:** orchestrator acceptance; before deploy, resolve the 44.49 GiB reserve shortfall and the separately disclosed confirmation dependency/reader amendment.
## 2026-11-12 — Continue minute capture after an invalid chunk

- **Why:** demonstrated defect: `.venv/bin/python -m pytest -q -W error -n 0 tests/test_free_massive_minute.py::test_invalid_middle_chunk_preserves_evidence_and_allows_later_chunks` fails before the fix with `engine.free_sources.FreeSourceError: Massive minute open is invalid`; the middle chunk aborts the manifest.
- **What:** preserve rejected raw responses before parsing, retain chunk failure context and reasons, and continue to later chunks without loading rejected bars.
  Retry a failed chunk at most once per run, no sooner than one hour after its last failure, using the shared provider limiter. Finished failures exit 1 with an incomplete summary and no completion marker.
  Read successful-load keys once and skip those chunks with one resume summary, avoiding repeated raw-page parsing and per-chunk resume logs.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 8` → `[100%]`, exit 0 (6378 tests); the fast tier also exits 0. The rate-limited VIDA probe returns three bars with zero OHLC, correctly rejected.
- **Metrics:** tools +71 LOC; server/product unchanged (session snapshot).
- **Next:** nothing admitted.

## 2026-11-12 — Repair splits skipped before post-ex-date bars arrived

- **Why:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_repair_integrity.py::test_skipped_split_is_restated_only_with_source_evidence` fails for `skipped_no_bars`: `assert [] == [('AAA', True), ('BBB', False)]`; a retained no-bars adjustment hides repairable history.
- **What:** Admit that recorded outcome to the existing split repair selection.
  Keep the complete source-history proof, mismatch refusal, audit trail and idempotence.
  On a published-snapshot copy, all six ETFs are repaired, five quarantines resolve and invariant regressions fall from six to zero. No touched file is P15-pinned.
- **Evidence:** `.venv/bin/python -m engine.repair_integrity --db <private-copy> --steps splits --since 2026-11-01 --apply` reports `candidates: 6, proven: 6, rows_changed: 28958`; affected tests and the full suite pass.
- **Metrics:** server 0, tools 0, product +1 LOC; tests +5 LOC.
- **Next:** nothing admitted.

## 2026-11-12 — Merge current main into storage revision 21

- **Why:** the orchestrator admits current main, including minute-capture recovery and no-bars split repair, into the undeployed revision 21.
- **What:** merge both fixes and current data; retain both sides' BUILDLOG entries in date order.
  Combine minute failure recovery with revision-21 raw-payload sealing; its inherited plain-file assertion fails with FileNotFoundError on a converted store, so read the preserved bytes through the payload reader.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_free_massive_minute.py tests/test_repair_integrity.py` → 26 passed.
- **Metrics:** merge includes upstream deltas; integration adaptation unchanged in code LOC.
- **Next:** archive capacity amendment and bounded no-bars split retry.

## 2026-11-12 — Give archives a volume-sized cap and recovery reserve

- **Why:** admitted revision-21 capacity amendment; the new dispatch tests reproduce a 90 GiB archive refusal and dispatch with one byte less than the store reserve plus two primary files; the warning still trips at 60 GiB.
- **What:** raise the total archive hard cap to 120 GiB and the live-store soft warning to 90 GiB, preserving the former 60:80 proportion.
  Before archive dispatch require 70 GiB plus twice the primary and WAL on their own filesystem; keep the root check and leave refused jobs pending with the reason logged.
  These are operational capacity settings, disclosed with revision 21; no statistical registered value changes.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_queue_runner.py` → dispatch boundaries, pending state and volume/WAL accounting pass.
- **Metrics:** final session snapshot: server 0, tools 0, product +59 LOC (both code fixes and runtime file-set additions).
- **Next:** bounded nightly retry for no-bars split skips.

## 2026-11-12 — Retry no-bars split skips after accepted bars arrive

- **Why:** admitted revision-21 retry; `.venv/bin/python -m pytest -q -W error -n 0 tests/test_actions.py -k 'nightly_retries_no_bars or nightly_no_bars_source'` fails: proven history leaves `rows_restated=0`, and the retry source-call list is empty.
- **What:** retry at most three recorded no-bars splits per reconciliation, only after accepted post-ex-date bars exist.
  Reuse repair-integrity candidate, full-history proof and application helpers; mismatch, empty history or source failure keeps the skip and quarantine and logs the refusal. No outer provider retry loop.
  Successful restatement resolves the split quarantine and preserves originals; later reconciliation is idempotent.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_actions.py tests/test_repair_integrity.py` → proof, refusal, no-post-bar, bound and idempotence cases pass.
- **Metrics:** final session snapshot: server 0, tools 0, product +59 LOC (both code fixes and runtime file-set additions).
- **Next:** correct the deploy checklist and re-pin the integrated revision once.

## 2026-11-12 — Correct revision-21 capacity and consumer deploy gates

- **Why:** orchestrator-admitted checklist corrections, backed by the capacity and private-consumer audits.
- **What:** confirmation 287 is closed by the October 30 commitment on its November 3 PENDING epoch; its timer was disabled today and its frozen code is preserved.
  Record live-287 compatibility and its diagnostic exception-name change, with read-only window checks; express the deploy reserve as primary plus WAL, and require a new pre-image after today's live split repair.
  Add the parent-queue archive drain and earnings/Friday evidence verification; expose the TradingView pause as an explicit orchestrator yes/no sign-off.
- **Evidence:** `git diff --check` → clean; the documented postflight command's help confirms read-only verification and the parent queue command retains normal admission.
- **Metrics:** code unchanged.
- **Next:** finalize the single runtime-then-P15 re-pin and repeat rehearsal and acceptance checks.

## 2026-11-12 — Finish the revision-21 capacity and retry integration

- **Why:** the orchestrator admits the capacity setting, source-proven nightly retry and checklist corrections into the undeployed revision-21 re-pin.
- **What:** merge current main, retain both fixes and log histories, and freeze P15's complete 175-file import closure plus E1/sector/XS runtime identities with their deployed predecessors unchanged.
  The new reduced real-data generation passes the unchanged T4 reader and exact file verification; its sandbox is deleted. Confirmation 287 remains closed and frozen; live-287 compatibility and post-deploy archive recovery are documented.
  Record today's eight deploy pre-flights; the 70 GiB plus three-primary reserve guard now passes, while merge, quiescence and TradingView yes/no remain with the orchestrator.
- **Evidence:** `TZ=UTC .venv/bin/python -m pytest -q -W error -n 8` and `TZ=Asia/Singapore .venv/bin/python -m pytest -q -W error -n 8` → 6,717 passed each (316.97 s / 306.79 s); required affected, lint, audit and identity checks pass.
- **Metrics:** session server 0, tools 0, product +59 LOC; relative to the prior published snapshot, merged upstream adds tools +69 and product +1.
- **Next:** orchestrator acceptance, main merge and deployment after the documented window pre-flights.

## 2026-11-12 — Finish minute capture with evidenced terminal rejections

- **Why:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_free_massive_minute.py -k 'cooldown or identical_parser or changed_response or terminal_marker'` fails before the fix: cooldown returns exit 1 (`assert 1 == 75`), and repeated parser rejections never become terminal (five failing cases).
- **What:** wait for the earliest failed-chunk cooldown when it fits the runtime bound; otherwise pause with exit 75.
  Three byte-identical responses rejected by the parser for the same reason over at least 48 hours become terminal, with immutable attempt evidence and an explicit operator retry.
  Complete loaded-or-terminal manifests with a rejection count/list and distinct marker status; clean-capture identity reads exclude those markers. No touched file is P15-pinned.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 8` → `[100%]`, exit 0; affected tests and all 21 minute-capture tests pass.
- **Metrics:** tools +118 LOC; server/product unchanged; tests +181 LOC (session snapshot).
- **Next:** nothing admitted.

## 2026-11-12 — Rotate and expire automatic no-bars split retries

- **Why:** orchestrator round-two review; `.venv/bin/python -m pytest -q -W error -n 0 tests/test_actions.py -k 'rotates_past_permanent or ages_out_without'` reproduces starvation (`NEW` is absent from the source calls) and fetches for two 61-day-old skips; a 21-row fixture also exposes weekend starvation in a calendar-day rotation.
- **What:** rotate three-candidate groups by a UTC weekday index, matching the Monday–Friday nightly; every member of a fixed eligible set gets its turn within ceil(count/3) scheduled nights while eligible.
  Retry only ex-dates from today minus 60 days through today; older skips remain available to manual repair and count once in the run summary without individual age-out logs.
  Keep the three-history bound, complete source proof, refusal watermark/quarantine and successful-restatement idempotence.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_actions.py tests/test_repair_integrity.py` → fairness, expiry, source-proof and existing action tests pass.
- **Metrics:** round-two snapshot: server 0, tools 0, product/engine +22 LOC; tests +91.
- **Next:** the single runtime-then-P15 re-pin, followed by all requested acceptance checks and reduced rehearsal.

## 2026-11-12 — Finish revision-21 retry fairness acceptance

- **Why:** the orchestrator's round-two starvation and infinite-retry defect is reproduced and admitted into the undeployed revision-21 re-pin.
- **What:** verify that five permanent refusals cannot hide the provable sixth split, that every member of a 21-row fixed eligible set gets a weekday turn, and that aged-out skips produce no provider fetch or individual age-out log.
  Re-pin sector/XS and the complete 175-file P15 closure once; E1's recomputed digest and all deployed predecessors stay unchanged. The same reduced real-data rehearsal passes with 122.9156 GiB minimum sampled free space; its sandbox is deleted.
  Update the checklist's pins and evidence, with the deployment gates still owned by the orchestrator.
- **Evidence:** `TZ=UTC .venv/bin/python -m pytest -q -W error -n 8` and `TZ=Asia/Singapore .venv/bin/python -m pytest -q -W error -n 8` → 6,728 passed each (317.32 s / 313.58 s); affected, Ruff, job/static schedule audits and identity checks pass.
- **Metrics:** round-two server 0, tools 0, product +22 LOC; the supplied upstream merge also adds tools +118 and tests +181 versus the round-one snapshot.
- **Next:** orchestrator acceptance and the documented merge/deploy window pre-flights.

## 2026-11-13 — Restore TradingView collection through the deployment lifecycle

- **Why:** owner collection decision and orchestrator revision-21 admission; `.venv/bin/python -m pytest -q -W error -n 0 tests/test_storage_r21_ops.py tests/test_schedule_contract.py tests/test_queue_runner.py tests/test_install_automation.py -k 'host_tradingview or host_accepts_active or schedule_state_follows or pending_job_1006 or stage_installs'` fails five cases: enabled release is skipped/refused, schedule and staging stay disabled, and job 1006 sees collection disabled.
- **What:** restore the collection flag and revision-20 timer/service registration; schedule, staging and release follow the one flag.
  Quiesce TradingView with every managed producer and resume it at release; preserve explicit pause tests and parent-queue dispatch for job 1006.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_storage_r21_ops.py tests/test_schedule_contract.py tests/test_install_automation.py tests/test_miner_monitor.py tests/test_tradingview_history_archive.py tests/test_stage_timings.py tests/test_service_units.py` → `[100%]`, exit 0; the corrected parent-queue suite also passes.
- **Metrics:** server +14 LOC, tools -1 LOC, product unchanged; final snapshot follows acceptance.
- **Next:** restore the retained option and macro collection flags.

## 2026-11-13 — Retain revision-20 option and macro collection

- **Why:** owner collection decision and orchestrator revision-21 admission; `.venv/bin/python -m pytest -q -W error -n 0 tests/test_signals.py tests/test_free_massive_options.py -k 'registered_config or unread_macro'` fails both cases with `assert False is True` before the flag changes.
- **What:** turn on the existing Massive options switch and the five-series macro switch; retained readers, parsers and storage paths need no restoration.
  Preserve explicit pause coverage and verify enabled collection through recorded-response option tests and macro parser fixtures.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_queue_runner.py tests/test_signals.py tests/test_free_massive_options.py` → `[100%]`, exit 0; all five macro parsers and recorded option responses pass.
- **Metrics:** server/tools/product unchanged; tests add enabled and paused parser coverage.
- **Next:** correct the checklist and perform the single revision-21 re-pin.

## 2026-11-13 — Apply the owner collection decision to the revision-21 checklist

- **Why:** owner decision at about 03:40 UTC: "why pause trading view? just get data as much as you need"; the orchestrator admits retaining all three revision-20 collection paths.
- **What:** remove TradingView YES/NO sign-off while preserving every window rule; document TradingView quiescence and release plus normal parent-queue dispatch for job 1006.
  Retain publish-on-change and its weekend rules; record the owner decision in feedback, product and scope, with the existing options timer hold unchanged.
- **Evidence:** `git diff --check` → clean; static schedule check reports `schedule contract: ok (static)`.
- **Metrics:** code unchanged.
- **Next:** the single P15 revision-21 re-pin, then required acceptance checks.

## 2026-11-13 — Re-pin revision 21 over the retained collection paths

- **Why:** owner-directed collection amendment to undeployed revision 21; pre-pin registration identity fails because committed `engine/signals.py` differs from the previous closure.
- **What:** hash the same 175-file P15 closure once, bind its last source change and rewrite collection/schedule disclosure with the November 13 owner decision.
  E1 v8, sector v12 and XS v23 keep their prior digests, file sets and deployed predecessors because none of their pinned files changed.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_p15_registration.py tests/test_registration_identity.py tests/test_experiment_runner.py tests/test_forward_review.py tests/test_xs_forward_review.py` → `[100%]`, exit 0.
- **Metrics:** code unchanged.
- **Next:** run affected tests, both full timezone suites and the remaining rehearsal/audit commands.

## 2026-11-13 — Finish revision-21 collection acceptance

- **Why:** the owner rejects all collection loss relative to revision 20; the orchestrator admits the retained flags, deploy lifecycle and single undeployed revision-21 re-pin.
- **What:** verify normal TradingView parent dispatch, deploy quiescence/release, retained option capture and all five macro parser paths; preserve each pause switch and publish-on-change.
  Record both full timezone suites and ten stub deploy/rollback cases; the disposable-home installer audit has no errors and proposes no TradingView stop/disable. The direct worktree context refusal is retained verbatim.
- **Evidence:** `TZ=UTC .venv/bin/python -m pytest -q -W error -n 8` → 6,740 passed (279.61 s); Asia/Singapore also 6,740 passed (279.59 s), zero failures/errors/skips; affected, Ruff, job/schedule and identity checks pass.
- **Metrics:** session server +14 LOC, tools -1 LOC, product unchanged; tests +193 LOC.
- **Next:** orchestrator acceptance and the documented merge/deploy window pre-flights.

## 2026-11-13 — Repair revision-21 predecessor migration and prove readers before release

- **Why:** the orchestrator reproduced XS rejecting the deployed report because only `runtime_contract_files` differs; the sector closure differs the same way, and deploy omitted the checklist's pre-release reader proofs.
- **What:** pin literal deployed sector/XS file lists independently, retaining the exact digest and every published-evidence comparison; migrate to the current closure and refuse added, missing or reordered predecessor files.
  Copy deployed frozen-runtime fixture blocks and verify continuity on disposable databases; E1's deployed file list and recomputed digest already match, so its source is unchanged.
  Run both unchanged read-only checklist proof blocks after reader verification, save their output and keep producers quiesced on either failure; all 13 deploy/rollback rehearsal cases pass.
  Re-pin sector/XS and the same 175-file P15 closure once, preserving every frozen setting. The published reports pass their metadata guards; `con=None` then reaches database evidence evaluation and cannot return a migrated report.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 8 tests/test_forward_review.py tests/test_xs_forward_review.py tests/test_experiment_runner.py tests/test_forward_cost_break_continuity.py tests/test_r15_integration.py tests/test_sector_forward_status.py tests/test_xs_forward_status.py tests/test_storage_r21_ops.py` → 162 passed; Ruff, job/static schedule and registration identity pass. Full/affected gates remain incomplete at 99%; diagnostic stacks show generated account-delivery tests in DuckDB operations, and a one-thread standalone seed passes.
- **Metrics:** server 0, tools 0, product +96 LOC; tests +210 LOC.
- **Next:** blocked: orchestrator selects a permitted runner for the unfinished full/affected gates and clarifies the database-dependent published-report proof; merge/deploy gates remain closed.

## 2026-11-13 — Name the orchestrating setup without a model version

- **Why:** owner feedback of 2026-11-13 (`docs/feedback.md`), after a prompt audit of the agent docs.
- **What:** `AGENTS.md` says Claude directing Codex or other sessions, and the closing heading drops
  "(unchanged)". No rule, gate or registered file changes.
- **Evidence:** `.venv/bin/python -m pytest -q tests/test_operating_contract.py tests/test_public_hygiene.py` passes.
- **Metrics:** unchanged.
- **Next:** nothing admitted.

## 2026-11-13 — Accept revision 21 and record the closed confirmation timer as disabled

- **Why:** revision-21 deploy (owner, 2026-11-13: deploy without holding); reproduction: with this
  branch `python -m tools.schedule_contract_check --live` reported `not-enabled: confirm-287.timer`,
  which the deploy's before-release schedule gate refuses.
- **What:** the orchestrator ran both timezone suites outside the writer's sandbox (green) and
  replayed the sector and XS runtime migrations on the latest published snapshot against the live
  published reports (both migrate). The schedule contract now lists the closed trial-287
  confirmation timer and service as disabled, matching the host since 2026-11-12.
- **Evidence:** `python -m tools.schedule_contract_check --live` → only `not-installed:
  trading-engine-publish-on-change.timer`, which the deploy installs before its gate.
- **Metrics:** unchanged.
- **Next:** merge to main and deploy revision 21 by its checklist.

## 2026-11-13 — Deploy revision 21 (storage generations, capacity, retained collection)

- **Why:** owner direction of 2026-11-13 to deploy without holding; the old 80 GiB cap had refused
  four archive jobs nightly since 2 Nov.
- **What:** merged `72d4459b` and ran `ops/storage-r21/deploy.sh` from 05:48 UTC: backup, schema
  migration, E1/sector/XS runtime migrations, first generation and the trial-375 reader proof passed.
  The live-287 import proof stopped the script: its block resolves `massive_287` from
  `trading-alpha/live`, but the module is in `trading-alpha/research`. The orchestrator reran that
  proof with the path corrected (pass), ran the schedule gate and released at 07:02 UTC. Release
  dropped the two news-scraper cron lines the contract requires; they were restored from the
  pre-deploy crontab before the released check passed. Receipts: `~/.local/state/r21-deploy/`.
- **Evidence:** every command in the checklist's "Verify after release" block exits zero;
  `/health` serves `x-generation-stale: false`; registration identity passes.
- **Metrics:** unchanged since the merge snapshot.
- **Next:** drain archive jobs 1006/1007/1009/1014; fix the proof path and the crontab release defect.

## 2026-11-13 — Recover basis-held history before nightly and exact-label retries

- **Why:** retained XP gap reproduction on deployed main: `pytest -q tests/test_basis_recovery.py`
  fails all five cases; five-day and exact-day requests cannot supply the required prior overlap.
- **What:** select history for unresolved basis holds from twenty stored sessions before the
  earliest held date; admit it through the unchanged proof, then retry exact labels.
  Context requests share the existing twenty-request label budget and run once per ticker.
  XS accepts the literal deployed revision-21 predecessor; revision-22 expectations and release index updated.
- **Evidence:** `pytest -q tests/test_basis_recovery.py` passes five cases; retained replay
  releases 0/34 nightly names and XP (five exact dates); SGRY lacks successful action evidence.
- **Metrics:** server +29, tools unchanged, product +39 LOC.
- **Next:** orchestrator deploys revision 22 with the explicit XS runtime migration.

## 2026-11-13 — Preserve external cron entries at automation release

- **Why:** `pytest -q tests/test_install_automation.py::test_release_preserves_external_lines_inside_the_managed_block`
  fails on deployed main: both news-scraper lines inside the managed markers disappear.
- **What:** replace only installer-owned entries and generated comments; retain external lines
  even when they were inserted inside the old managed block.
- **Evidence:** `pytest -q tests/test_install_automation.py` passes, including preservation at
  the release mutation boundary and idempotence after rendering the retained external lines.
- **Metrics:** server unchanged, tools +7, product unchanged LOC.
- **Next:** orchestrator deploys revision 22 with the explicit XS runtime migration.

## 2026-11-13 — Use the supported yfinance exception setting

- **Why:** `pytest -q tests/test_incremental_history.py` reproduces the installed provider's
  deprecated argument warning in both prior debug states and the unscoped exception setting.
- **What:** scope the provider's supported hide-exceptions setting to each exact history call
  and restore it on success or error; keep the request arguments and bounded retry unchanged.
- **Evidence:** `pytest -q -W error tests/test_incremental_history.py` passes four cases using
  installed yfinance: no deprecated warning, errors raise, one retry, both settings restored.
- **Metrics:** server +7, tools unchanged, product unchanged LOC.
- **Next:** orchestrator deploys revision 22 with the explicit XS runtime migration.

## 2026-11-13 — Revision 22 deployed

- **Why:** the revision 22 release note (`docs/revision-22-basis-recovery.md`) asks for a
  deploy in a release window with producers idle; the archive queue drain had finished.
- **What:** merged revision 22 to main, pulled it into the live checkout, ran the XS runtime
  contract migration (now v23, verdict still `REVIEW-KILL`) and re-applied the installer.
  Both external news-scraper cron lines survived beside the six engine lines.
- **Evidence:** `python -m tools.check_invariants --snapshot latest` exits 0; `/health` is 200
  and `/meta` shows no `INVALID` forward record. `tools.schedule_contract_check --live` still
  reports one violation that predates the deploy: the 07:42 UTC TradingView history run
  failed while the queue drain held the store.
- **Metrics:** unchanged.
- **Next:** nothing admitted; the next scheduled incremental and label run performs recovery.

## 2026-11-19 — Revision 23: unblock the nightly and recover stalled drivers

- **Why:** reproduced defects. The 2026-11-13 nightly hung in `server.p15_incremental_collect`
  for five days holding the store (stack: `_basis_unverified`, DuckDB workers idle); the same
  run on a store copy hung at the same statement within four minutes. Massive daily capture
  has failed since 11-17 on a `DELAYED` envelope. Owner asked for self-recovery.
- **What:** the basis-hold query runs as two statements instead of one UNION ALL over the
  registered frame; Massive grouped-daily accepts `DELAYED`; a ten-minute driver watchdog
  terminates a cron run idle past its runtime on two passes (never lock waiters) and starts a
  bounded catch-up nightly. P15 revision 23; E1, sector and XS accept their published
  revision-22 digests for an explicit migration (rehearsed on a store copy: digest-only diff).
- **Evidence:** the fixed collector on the same store copy finished (`market_date 2026-11-18`).
- **Metrics:** tools +1 module (`tools/driver_watchdog.py`); production otherwise unchanged.
- **Next:** deploy, run the three runtime migrations, then a catch-up nightly before 14:05 UTC.

## 2026-11-19 — Revision 24: keep the league and the P15 window on one session

- **Why:** reproduced on the live store. After the stalled nightly was terminated, P15
  scoring ran first and marked the P15 books for 2026-11-13; the catch-up nightly then stopped
  at market-date (`active portfolio checkpoints disagree: 2026-11-12, 2026-11-13`), and the
  league step treated those P15 marks as 11-13 being stepped for every book.
- **What:** outside a rerun the league's done-guard ignores P15 marks; the P15 window waits
  (`waiting_for_league`) until every active league book has stepped the session; the watchdog
  starts P15 scoring after a finished catch-up. Sector and XS re-pinned for migration.
- **Evidence:** store-copy rehearsal: P15 book rows identical across the 11-13 league step;
  13, 16, 17 and 18 Nov stepped; market-date `2026-11-18`.
- **Metrics:** unchanged.
- **Next:** deploy, migrate, replay 13–18 Nov on the live store, then the nightly stages.

## 2026-11-20 — Record the twelve lost November P15 scoring windows

- **Why:** R25 integrity reproduction: the November 20 snapshot reports 19 regressions;
  revisions 23 and 24 explain the irrecoverable November 13, 16, 17 and 18 scoring loss.
- **What:** accept only those four dates for the three named P15 books, under the existing
  `window_without_scoring_run` class. No scoring backfill or invariant rule changed.
  The six unrecorded-split alerts retain identical fetched closes on both sides of their moves.
  EMBJ's recorded 4:1 split has post-ex bars now; the bounded retry selects it on November 20.
  Split alerts remain visible: current source history is unavailable for the repair proof.
- **Evidence:** `python -m tools.check_invariants --snapshot store/snapshots/market-20261120T074859716512Z.duckdb --engine-root .`
  reports 7 regressions, down from 19; publication order has 0 regressions and 15 baselined rows.
- **Metrics:** server/tools/product LOC unchanged.
- **Next:** obtain current source history, rehearse EMBJ's existing evidence-gated repair and
  adjudicate the six remaining split-sized moves before deployment.

## 2026-11-20 — Accept six source-confirmed market moves in the split baseline

- **Why:** R25 round-two orchestrator adjudication: fresh Yahoo/yfinance history agrees
  with the stored closes and reports no splits since September 1 for the six flagged names.
- **What:** accept only NVEC October 22, AMUU/KORU/MUU/UVXY November 5 and APPS November 10
  under `split_recorded_vs_restated` / `unrecorded`, expiring January 20, 2027.
  Each reason records the provider check and unchanged retained observations, with no nearby
  split row or rewrite audit. The supplied table is retained in lane output as
  `provider-check-2026-11-20.md`; the invariant rule and all prices are unchanged.
- **Evidence:** `python -m tools.check_invariants --snapshot store/snapshots/market-20261120T074859716512Z.duckdb --engine-root .`
  reports 1 regression (EMBJ), down from 7; `split_recorded_vs_restated` has 0 regressions.
- **Metrics:** server/tools/product LOC unchanged.
- **Next:** EMBJ is expected to clear through the bounded source-proven retry after the
  2026-11-20 nightly; the orchestrator will verify the newly published snapshot. No EMBJ exception.

## 2026-11-20 — Scope hourly operations findings to the engine

- **Why:** owner-directed digest repair; four regression tests on the unchanged source fail:
  unrelated services fail the digest/contract, expected off-hours publication warns, and old
  noise returns as a daily chronic reminder.
- **What:** share engine ownership between the schedule check and digest; retain declared
  dependencies, engine commands and every store-holder check. Exclude expected off-hours
  publication from warning counts and remove its old chronic reminders.
  Replay the captured hour: five contract violations become zero, warnings 29 become 27;
  WARN remains for settlement retries and TradingView failures. Weekend receipts replace old
  failures; the two unchecked held names correctly keep price verification partial.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_ops_digest.py tests/test_schedule_contract.py`
  → 207 pass. Both timezone suites: 6,762 pass, 27 fail; baseline reproduces six watchdog
  lock failures and a representative API hang. Full acceptance remains blocked.
- **Metrics:** session server +36, tools +63, product unchanged LOC; snapshot budget passes.
- **Next:** orchestrator verifies full acceptance in its runner, then merges and deploys.

## 2026-11-20 — Restore workspace ownership in the hourly digest

- **Why:** orchestrator round 2; the current head fails restored workspace/overlay checks,
  loses command-owned warning history, hides ignored wrappers and silently degrades discovery.
- **What:** use every declared workspace marker and slice, restore strict overlay assertions,
  and carry observed command/stop/timer ownership into history and reports.
  Name ignored units and loaded overlay dependencies; failed or incomplete discovery keeps WARN.
  Render the same metrics with the actual overlay: 23 runs, 27 warnings, no contract violations;
  prepare removal of the unrelated notes-sync declarations for the orchestrator.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_ops_digest.py tests/test_schedule_contract.py tests/test_operating_contract.py tests/test_public_hygiene.py`
  → 252 pass; restored/new checks fail on the preceding head. Ruff and metrics budget pass.
- **Metrics:** session server +1, tools +54, product unchanged LOC.
- **Next:** orchestrator updates the local overlay and runs full acceptance before deployment.
## 2026-11-20 — Hand snapshot capture lock ownership to the publisher

- **Why:** revision-25 snapshot brief; `pytest -q -n 0 tests/test_drivers.py::test_snapshot_releases_producer_lock_after_capture_keeps_run_guard` fails on main with `BlockingIOError` after capture: the driver parent and tee still hold fd 9.
- **What:** explicitly unlock the shared fd 9 before publishing; the publisher acquires producer locks only for capture. A separate running lock excludes overlapping drivers through the done marker, and the watchdog observes that guard and defers catch-up.
  The digest reader is outside the authorized scope and still reports the tail interrupted; its proposed guard-reader change remains blocked on scope approval. Weekly drivers have no held-lock publisher invocation.
- **Evidence:** `pytest -q -n 0 'tests/test_drivers.py::test_snapshot_releases_producer_lock_after_capture_keeps_run_guard[locks]' tests/test_driver_watchdog.py::test_watchdog_observes_snapshot_tail_and_defers_catch_up` → two passed; the digest variant fails until its reader changes.
- **Metrics:** lane delta: server 0, tools +5, product 0 LOC; tests +123.
- **Next:** orchestrator admits the status-reader change and completes capture rehearsal with enough free space.

## 2026-11-20 — Verify snapshot multisets with counts and one containment pass

- **Why:** P24 nightly-speed and the revision-25 snapshot brief admit an output-identical removal of the reverse EXCEPT ALL pass.
- **What:** count both relations exactly and retain source EXCEPT ALL generation; equal cardinality plus containment proves multiset equality. Count verified cold rows from the actual source.
  Document the schema-v2 metric names: cold_verification_seconds covers all tables, while cold_verification_rows reports only cold rows.
- **Evidence:** `pytest -q -n 0 tests/test_publish_snapshot.py::test_semantic_equality_multiset_property` → 105 multiset cases pass, including duplicates, NULLs and empty relations; final focused five-test runs pass under both timezones.
  Both checks pass on the same verified 160-table, 99,904,744-row generation copies: 1,000.94 → 552.24 seconds (44.8% less). Both cold sides are Parquet views, so this is not a full publication-stage timing.
  Full capture refused its unchanged 70 GiB reserve (67.1 GiB free, 33.7 GiB additional need); both full suites and the affected tier stalled at 98% and were interrupted, with failures observed.
- **Metrics:** lane delta: server 0, tools +12, product 0 LOC; tests +72; the combined metrics snapshot passes budget.
- **Next:** orchestrator resolves the reader scope and completes full capture, publication timing and timezone suites before the shared re-pin.

## 2026-11-20 — Revision-25 round two: publication retries and observer capture waits

- **Why:** orchestrator journal evidence shows every daytime capture timing out at 25 minutes; the 17:15 hourly observer gives up after 60 seconds inside a roughly 120-second capture.
  `pytest -q -n 0` on the new timeout, failure-backoff, observer-lease and digest regression cases fails before the fix: 25-minute timeout, immediate second failure, 60-second lease, and interrupted digest status.
- **What:** the digest reads the running guard through the done marker. Publish-on-change gets 45 minutes (16 minutes above the recorded 29-minute stage); its single oneshot and publication mutex prevent timer overlap.
  Durable attempt state backs off an hour after failure, or an hour after detecting a killed attempt; ordinary producer contention remains a skip. Both P9 cadences wait up to 300 seconds with one shared store deadline inside the ten-minute unit.
  P15 pre-open already has a sufficient deadline-bound wait; events exclude capture with the nightly guard across lease releases. The out-folder rehearsal checks the reserve, full publication, concurrent writer access and post-capture failure preserving the served generation.
- **Evidence:** `pytest -W error -n 0 tests/test_publish_snapshot.py -k 'publish_on_change or semantic_equality or writer_wins or publication_tail'` → 12 passed; another 320 focused tests pass in each timezone. Ruff and metrics budget pass; full suite and full-store rehearsal stay with the orchestrator.
- **Metrics:** round-two delta: server +23, tools +60, product 0 LOC; tests +165.
- **Next:** orchestrator runs the full source-copy rehearsal and suite, then performs the shared registration revision.

## 2026-11-20 — Revision-25 final round: inherited capture lock and retention guard

- **Why:** orchestrator round-three review; regressions on b1d050ac fail for the missing inherited-fd hand-off, corrupt/non-UTC backoff markers, and quiet snapshot-tail retention. The current real producer-lock error path already passes its new PublicationBusy test.
- **What:** retain the inherited nightly descriptor through capture and explicitly unlock its shared open description afterward, including parent/tee aliases; all early exits unlock it too. The running guard still covers the tail.
  Invalid backoff state expires with a warning. Retention uses the shared running-guard reader; the repo audit found no other missed nightly-liveness reader. The rehearsal reports wall time at verified nice 19 and margin against 45 minutes.
  Real kernel/queued-writer and DuckDB lock-error tests close the coverage gaps. Watchdog fixtures acquire their flock before exec so the real holder stays visible in a PID namespace and test-owned children are cleaned up.
- **Evidence:** `pytest -W error -n 0 tests/test_publish_snapshot.py` → all 85 publication cases pass (UTC 84 plus the added real-DuckDB case; Singapore 85); another 349 focused cases pass in each timezone. Ruff, rehearsal compilation/real priority helper and metrics budget pass; full suite stays with the orchestrator.
- **Metrics:** final-round delta: server 0, tools +34, product 0 LOC; tests +198.
- **Next:** orchestrator runs the quiet-window full-store rehearsal and full suite, then performs the shared re-pin.

## 2026-11-23 — Admit P25: continuous deploy, docs and code cleanup

- **Why:** owner instruction of 2026-11-23 (deploy merged work, clean docs and code, short
  backup history, UI frozen); P25 plan opened as active.
- **What:** add `docs/plans/p25-ship-autodeploy-cleanup.md` and its index row; put P25 first in
  `docs/product.md` "Focus now" with the UI frozen.
- **Evidence:** `.venv/bin/python -m tools.affected_tests --run` passes.
- **Metrics:** unchanged.
- **Next:** integrate batch B and issue registration revision 25.
## 2026-11-20 — Keep API liveness independent of snapshot verification

- **Why:** revision-25 API latency reproduction on a published snapshot copy: cold
  `server.main.health()` takes 10.13 s, including 9.97 s hashing 7.31 GiB of generation files;
  the digest times out after 5 s. A verified generation's `/meta` takes 1.12 s.
- **What:** make liveness an async, in-memory response; verify the first generation at
  startup and pre-verify publications in a separate worker through the unchanged read gate.
  Metadata is identical before/after and matches the captured JSON shape; normal requests
  take 1.57 s, but a request racing publication verification still takes 10.83 s.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0 tests/test_api_latency.py tests/test_server_routes.py tests/test_meta_projection.py tests/test_server_db.py`
  → 130 passed with a runner-only asyncio wakeup workaround; three regressions fail on main.
  Both full timezone suites: 6,778 passed, six unchanged watchdog failures because the runner
  hides inherited shell locks from `/proc/locks`; one failure also reproduced on main.
- **Metrics:** server +20, tools 0, product 0 LOC versus the session's initial snapshot.
- **Next:** blocked: orchestrator acceptance needs normal process-lock visibility and a
  decision on the metadata latency boundary during publication verification.

## 2026-11-20 — Serve verified generations while publication verification runs

- **Why:** revision-25 round-two decision; the round-one snapshot-copy race took 10.83 s
  because request readers still verified inline, and liveness alone hid database readiness.
- **What:** retain a verified connection and lifetime pin, with independent request cursors;
  switch only after background verification and keep prior requests pinned until close.
  Cold data reads return not ready immediately; `/ready` reports the worker's readability
  result, and its failure gives the digest the same severity as unavailable liveness.
  Metadata retains every original value and adds served-generation pending fields; its
  snapshot-copy publication race takes 2.01 s, with health/readiness below 1 ms.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 8` under UTC and Asia/Singapore
  → 6,783 passed each; the six sandbox-only watchdog failures are accepted by the orchestrator.
  Focused: 290 passed; corrected accounting/concurrent-reader fixtures: 32 passed per zone.
- **Metrics:** server +154, tools +2, product 0 LOC versus the round-two initial snapshot.
- **Next:** orchestrator acceptance and API restart.

## 2026-11-20 — Report generation failures and bound verification retries

- **Why:** revision-25 round-three review; tests on the round-two head reproduce silent
  failed verification, per-poll retries, cursor timezone loss and missing health/lifetime guards.
- **What:** report refresh errors/times, pending age and generation status; warn on actual
  failures and retry after 60 seconds, doubling to a ten-minute cap or retrying a changed identity.
  Readiness degrades for failure, pending past 15 minutes, the existing 3.5-hour stale budget,
  a five-minute heartbeat gap or three query I/O errors in five minutes; digest severity follows it.
  Reapply UTC/resource settings on cursors and finalize leaked leases; preserve coherent
  continuous reads through the switch and clear active failure after successful verification.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 0` on the focused API/readiness,
  read-model, digest and account-reader tests → 315 passed under each timezone; 16 new
  regressions fail on the round-two head. Full suite deferred to the orchestrator as instructed.
- **Metrics:** server +180, tools +29, product 0 LOC versus the round-three initial snapshot.
- **Next:** orchestrator full-suite acceptance and API restart.

## 2026-11-20 — Readiness warns on normal staleness and retries one verification failure

- **Why:** independent review of round 3: a served generation older than the 3.5 h evidence budget is
  normal overnight and at weekends (publish-on-change runs only in US market hours; 3h53m and 4h05m
  gaps on 2026-11-20), but readiness returned 503 and the digest would FAIL every night. A single
  transient verification error also failed readiness at once, and a leased connection's finalizer could
  deadlock on the non-reentrant selector lock.
- **What:** `generation_stale` and `pending_timeout` keep `/ready` at 200 with `warning: true`; the
  digest ignores `generation_stale` (the served `as_of` stays on `/meta`) and warns on `pending_timeout`.
  `verification_failed` needs two consecutive failures (the retry backoff spaces them by at least 60 s).
  The selector lock is reentrant. The stale check runs last, so a dead worker, read errors or
  overdue verification are never masked by the stale warning (follow-up review).
- **Evidence:** focused API, database, route, meta and digest tests pass under UTC and Asia/Singapore;
  new tests pin the warning states, the probe severities and lock reentrancy.
- **Next:** orchestrator full suite, then deploy with the revision-25 batch.

## 2026-11-23 — Revision 25: snapshot capture lock, API readiness, bounded publication wait

- **Why:** P25 scope item 1 (batch B); reproductions in the lane entries above, plus a
  release check that would have rolled back: `/health` no longer reports `db_readable`.
- **What:** merge `r25/snapshot-lock` and `r25/api-latency`; bound the nightly's wait on
  `.generation-publish.lock` to 50 minutes and ignore EBADF when unlocking a closed inherited
  descriptor; release verification reads `/ready` and probes `/meta` for the forced snapshot;
  the UI treats the new not-ready 503 as busy; the job manifest matches the 45-minute unit.
  EMBJ needs no code change: Yahoo has not back-adjusted its 4:1 split, so the source proof
  correctly refuses until it does (bounded retry continues for 60 days from the ex-date).
- **Evidence:** `pytest -q -W error -n 8` passes under `TZ=UTC` and `TZ=Asia/Singapore`.
- **Metrics:** see the metrics snapshot.
- **Next:** fast-forward the live checkout, `install_automation --apply`, verify `/ready`.
## 2026-11-23 — Continuous deploy tooling: mechanical re-pin, dry-run deployer, landing command

- **Why:** P25 scope items 2-4 (active plan `docs/plans/p25-ship-autodeploy-cleanup.md`); the
  nightly's `git pull --rebase` moved pinned code onto the host before any migration ran.
- **What:** `tools/repin.py` writes the next registration revision (closure digests first, then
  the pin) and refuses any registered-value change; `tools/auto_deploy.py`, on a new 15-minute
  timer in dry-run mode, takes the newest green `main` commit through the deploy gate, migrations,
  `install_automation --apply`, post-checks and rollback, recording each decision for the digest;
  `tools/land.py` merges, re-pins, verifies and pushes a branch. The nightly now takes only
  data-only upstream commits; registration revision 26 pins that. Three tests that asserted
  revision 24 read the registration instead.
- **Evidence:** `python -m pytest tests/test_repin.py -k revision_25` reproduces the revision-25
  pin byte for byte from its parent and the same sentence; the full suite passes under UTC and
  Asia/Singapore.
- **Metrics:** tools +1,190 LOC (repin, auto_deploy, land), server and product unchanged.
- **Next:** run the deployer in dry run through one full nightly cycle, then add `--execute`.

## 2026-11-23 — Deploy revision 25

- **Why:** P25 scope item 1; revision 25 on `main` with both CI runs green (the `checks` job
  had been red on two production asserts, fixed before deploy).
- **What:** fast-forwarded the live checkout to the revision-25 head and ran
  `install_automation --apply`: publish-on-change unit installed, API and UI restarted. No
  forward-record migration (no closure digest changed). Deploy gate passed on the same tree.
- **Evidence:** `/health` 200 in 1 ms, `/ready` 200 (`warning: generation_stale`, weekend gap),
  `/meta` 200 in 1.05 s (was about 10 s); `install_automation` audit and registration identity pass.
- **Metrics:** unchanged.
- **Next:** auto-deployer in dry run (P25 scope items 2–4, registration revision 26).

## 2026-11-23 — Deployer review: schedule-aware mutation, self-heal, no alerts

- **Why:** P25 scope items 2–4; the owner-side review of the deployer and the owner's decision
  to self-heal rather than alert.
- **What:** refuse to mutate when an engine timer or engine cron line is due within 15 minutes or
  an engine unit runs; remember refused targets until `main` moves; let a dependency, schema or
  contract-version commit hold back only itself; keep the 70 GiB reserve; require an API restart
  after a migration. Self-heal: record the last verified commit and an in-flight marker, recover
  a crashed deploy, failed rollback or unhealthy unverified code back to it with backoff, and
  clear failed units and restart the apps after three failed recoveries. Producers are matched by
  both checkout spellings; the minute capture no longer blocks deploys. `--drill-rollback` added.
- **Evidence:** `pytest -q -W error -n 8` passes under `TZ=UTC` and `TZ=Asia/Singapore`; 41
  deployer tests cover each rule.
- **Metrics:** see the metrics snapshot.
- **Next:** deploy revision 26 with the deployer timer in dry run, then a supervised drill.

## 2026-11-23 — Docs state current truth and are organised for progressive discovery

- **Why:** P25 scope item 5 (docs), with the owner-side review of the docs lane.
- **What:** root `AGENTS.md` is an 80-line contract and task map; every top-level code folder has
  an `AGENTS.md` plus a `CLAUDE.md` that loads it; `docs/` is organised into operate, change,
  extend, architecture and data with a short index; dated audits, finished plans, the feedback
  ledger and BUILDLOG entries before 2026-11-01 moved to `docs/history/`; `product.md`,
  `scope.md`, the runbooks, the root README and `docs/site/` lost dated status and attributions.
  The doc-index test now checks reachability from `docs/README.md`.
- **Evidence:** `.venv/bin/python -m pytest -q -W error -n 8` exits 0; the review's acceptance
  `git grep` for dated or attributed status prints nothing.
- **Metrics:** engine, server, sim and farm unchanged; tests +14 lines; docs and BUILDLOG lines down.
- **Next:** P25 scope item 8, the extension guide in `docs/extend/README.md`.

## 2026-11-23 — Remove one-shot deploy scripts and superseded agent schema migrations

- **Why:** P25 scope item 7 (code cleanup).
- **What:** deleted `ops/storage-r21/` and its test (they ran at the revision-21 deploy, whose
  receipts the host keeps), and `tools.migrate_agent_human_approval`, `_paper_attribution` and
  `_release_review` with their tests, fault-drill cases and release-manifest audit entries
  (migration 0000, applied at revision 21, creates their tables). Registration revision 27
  re-pins `tools/release_manifest.py`; no registered value changes. Kept: the paper-authority
  store migration (migration 0000 calls it), `migrate_cost_profiles` (the sector and XS
  forward-record continuity tests replay it), `convert_raw_payloads` (not yet run).
- **Evidence:** `pytest -q -W error -n 8` exits 0 under `TZ=UTC` and `TZ=Asia/Singapore`;
  `python -m tools.repin --check` prints "registration is current".
- **Metrics:** server -45, tools -711, tests -1418 lines; ops scripts -663.
- **Next:** P25 scope item 7, stale remote branches and lane clones.

## 2026-11-23 — Let the deployer move a live checkout with uncommitted producer data

- **Why:** reproduced on the host: every `tools.auto_deploy --execute` from 08:16 to 08:32 UTC
  returned `skipped:live-tree-dirty` because `data/_meta.json` is rewritten between the
  producer commits that record it, so the deployer could act only right after a nightly commit.
- **What:** uncommitted changes under `data/` no longer block a deploy; any other dirty path
  still does. The move waits (`skipped:live-data-overlap`) only when it would overwrite one of
  those edits, and rebasing data-only local commits uses `--autostash`.
- **Evidence:** `pytest -q -W error -n 0 tests/test_auto_deploy.py` passes under `TZ=UTC` and
  `TZ=Asia/Singapore` (three new cases: fast-forward and rebase keep the edit, overlap waits).
- **Metrics:** tools +27 lines, tests +45.
- **Next:** release batch C (dependency update) and switch the deployer timer to `--execute`.

## 2026-11-23 — Keep local backups short: newest two deploy copies, finished clones removed

- **Why:** P25 scope item 6 (short local backup history; `trading-data` on GitHub is the backup
  of record).
- **What:** `tools/prune_local.py` keeps the newest two deployer report backups and store backups,
  removes `recovery/` of finished release transactions older than the newest two (under
  `releases/` or the older `~/.local/state/*-deploy`), and removes lane clones that are quiet for
  24 hours with every commit on origin. A daily 12:20 UTC timer runs it; the deployer prunes its
  own backups after each verified deploy or recovery.
- **Evidence:** `pytest -q -W error -n 0 tests/test_prune_local.py tests/test_auto_deploy.py` passes
  under `TZ=UTC` and `TZ=Asia/Singapore`; a host dry run keeps two backups and three active clones.
- **Metrics:** tools +350 lines, tests +245.
- **Next:** the extension guide (`docs/extend/README.md`).

## 2026-11-23 — Write the add-a-strategy guide

- **Why:** P25 scope item 8 (one short documented path for adding a strategy or experiment).
- **What:** `docs/extend/README.md` replaces its stub with the funnel (register, screen on the
  shared backtest core, confirm, paper book), where each kind of code goes, and the rules that bite.
- **Evidence:** `tools.affected_tests --run` passes (documentation links and index).
- **Metrics:** unchanged.
- **Next:** switch the deployer timer to `--execute`.

<!-- append-only-tail: insert new verified entries immediately above this line -->
