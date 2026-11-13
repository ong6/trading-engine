# Revision 22 release

Revision 22 follows deployed revision 21. It supplies source history for unresolved basis
holds through the existing twenty-session proof, then re-asks exact labels; context requests
share the twenty-request label budget. It also preserves external cron lines during installer
release and scopes yfinance's supported exception setting to each exact history request.
Admission, labels, frozen statistics and the fetch limit remain unchanged.

The retained November 13 snapshot releases XP's five label dates, but none of the 34 nightly
names. Fourteen nightly names lack successful action-fetch evidence; twenty lack retained
twenty-session source overlap. SGRY lacks successful action-fetch evidence. A future response
must pass the same proof before any of those holds can release.

Only the XS closure changes. The migration accepts its literal deployed revision-21 digest
and file list, preserving all published evidence and its `REVIEW-KILL` verdict. The E1 and
sector closures remain unchanged. The read-only replay against the newest published snapshot
passed the XS migration with every non-runtime section identical.

After orchestrator merge and acceptance, run in the live checkout during a release window with
producers idle, before allowing another producer run. Use the existing release-window and
quiescence rules in the [runbook](settlement-runbook.md). The additional step between the pull
and installer is the XS migration:

```sh
cd ~/trading-engine
git pull --ff-only origin main
.venv/bin/python -m tools.registration_identity
.venv/bin/python -m engine.xs_forward_review --migrate-runtime-contract
.venv/bin/python -m tools.install_automation --apply
.venv/bin/python -m engine.job_contract audit
.venv/bin/python -m tools.schedule_contract_check --live
```

Stop release on any nonzero exit. The migration reads the primary and replaces only the
published XS runtime identity after validating the exact predecessor and all evidence.
The next scheduled incremental and label run performs recovery automatically. The installer
preserves operator-managed news jobs even when they are inside the old managed markers.
