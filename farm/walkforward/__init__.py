"""Weekly walk-forward re-validation of every active league rule (design §12.3).

Feeds the Sunday review loop (execution design §6): "changes only at reviews,
one at a time, justified by walk-forward evidence not last week's P&L".

Four pieces:

  protocol.py  the FROZEN fold protocol — train/validate lengths, fold dates,
               which books are excluded and why
  runner.py    one queue job per book: a shared read-only input store, private
               writable overlay, and real league replay for every fold
  report.py    data/reports/walkforward/ — per-book pages + the index
  grid.py      enumerate / enqueue the weekly grid (job kind 'walkforward')

Nothing here runs in the weekday nightly. The live store is opened read-only
(SELECT + COPY … TO parquet only); each queue run shares one immutable scratch
base while job-local writes land in overlays deleted on completion.
"""
