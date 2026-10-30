"""Replay archived hourly digest inputs without probing the host or opening stores.

The JSONL fixture captures immutable hourly metrics, original producer messages where
available, and journal lifecycle counts. Unrecoverable log signatures retain their
archived level; replay never guesses a zero counter. See the lane evidence for capture.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from tools import ops_digest

FIXTURE = Path(__file__).parent / 'fixtures/ops_digest/archived-hours.jsonl'


def replay(inputs: Path, state: Path) -> list[dict]:
    results = []
    for line in inputs.read_text().splitlines():
        row = json.loads(line)
        signals = defaultdict(ops_digest.SourceSignals)
        for source, level, count, raw, signature in row['signals']:
            signal = signals[source]
            if raw is None:
                signal.counts[level] += count
                signal.signatures[level, signature] += count
            else:
                signal.add(raw)
                if found := ops_digest.classify(raw):
                    signal.counts[found] += count - 1
                    signal.signatures[found, ops_digest.signature(raw)] += count - 1
        failure = (row['failed_runs'] > 0
                   or any(c['severity'] == 'fail' for c in row['gateway']['checks'])
                   or any(p['target'] == '/health' and p['http_status'] != 200
                          for p in row['probes']))
        data = {'status': 'FAIL' if failure else row['before'],
                'failed_runs': row['failed_runs'], 'signals': signals, 'gaps': [],
                'runs': row['runs'], 'work': [('external-work', SimpleNamespace(label=s))
                                             for s in row['work']],
                'contract': row['contract'], 'gateway': row['gateway'], 'probes': row['probes']}
        hour = datetime.strptime(row['hour'], '%Y-%m-%dT%H').replace(tzinfo=UTC)
        ops_digest.apply_finding_history(hour, data, state)
        results.append({'hour': row['hour'], 'before': row['before'], 'after': data['status'],
                        'failed_runs': row['failed_runs'], 'journal_failed': row['journal_failed'],
                        'alerts': [i for i in data['findings'] if i['alert']],
                        'chronic': [i for i in data['findings'] if i['category'] == 'chronic']})
    return results
