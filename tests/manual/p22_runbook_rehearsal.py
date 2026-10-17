"""Execute the P22 runbook in an isolated checkout and runtime unit namespace.

Manual proof harness, not a documentation-pinning pytest test. Requires a captured
published snapshot and its evidence tree. No live cron, source or store mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

PARSER = argparse.ArgumentParser(description=__doc__)
PARSER.add_argument('--output', type=Path, required=True)
PARSER.add_argument('--snapshot', type=Path, required=True)
PARSER.add_argument('--evidence', type=Path, required=True)
ARGS = PARSER.parse_args()
REPO = Path(__file__).resolve().parents[2]
OUT = ARGS.output.resolve()
OUT.mkdir(exist_ok=True)
ROOT = OUT / 'checkout'
RUNTIME_UNITS = Path(os.environ['XDG_RUNTIME_DIR']) / 'systemd/user'
UNITS = OUT / 'units'
PREFIX = 'p22-rb-'
PYTHON = REPO / ".venv/bin/python"
API_PORT, UI_PORT = 18142, 13142
ENV = os.environ | {
    'PATH': str(OUT / 'bin') + ':' + os.environ['PATH'],
    'PYTHONPATH': str(ROOT),
    'TRADING_ENGINE_DB': str(ROOT / 'store/market.duckdb'),
    'TRADING_ENGINE_DATA_DIR': str(ROOT / 'data'),
    'TRADING_ENGINE_STORE_DIR': str(OUT / 'notes'),
    'TRADING_ENGINE_AGENTS_DIR': str(OUT / 'agents'),
    'TRADING_ENGINE_WATCHLIST': str(OUT / 'notes/watchlist.md'),
    'TRADING_ENGINE_FREE_SOURCES_DB': str(OUT / 'daily.duckdb'),
    'TRADING_ENGINE_FREE_SOURCES_DIR': str(OUT / 'free-sources'),
    'TRADING_ENGINE_MASSIVE_MINUTE_DB': str(OUT / 'minute.duckdb'),
    'TRADING_ENGINE_MASSIVE_OPTIONS_DB': str(OUT / 'options.duckdb'),
    'TRADING_ENGINE_MASSIVE_OPTIONS_DIR': str(OUT / 'options'),
    'TRADING_ENGINE_SHORT_DATA_DB': str(OUT / 'short.duckdb'),
    'TRADING_ENGINE_ACCOUNTS_TOKEN_FILE': str(OUT / 'absent-token'),
    'PYTHONDONTWRITEBYTECODE': '1',
    'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
    'P22_HARNESS_OUT': str(OUT),
}
RESULTS = []
UNIT_NAMES = set()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def command(args, cwd=ROOT, env=ENV):
    return subprocess.check_output(list(map(str, args)), cwd=cwd, env=env, text=True)


def systemctl(*args):
    return command(['/usr/bin/systemctl', '--user', *args])


def run(name, script, expected=0, extra=None):
    path = OUT / (name + '.bash')
    path.write_text(script)
    subprocess.run(['/usr/bin/bash', '-n', path], check=True)
    with (OUT / (name + '.log')).open('w') as log:
        proc = subprocess.run(['/usr/bin/bash', '--noprofile', '--norc', '-x', path],
                              cwd=ROOT, env=ENV | (extra or {}), stdout=log,
                              stderr=subprocess.STDOUT)
    record = {'name': name, 'exit': proc.returncode, 'expected': expected,
              'transcript': str(OUT / (name + '.log'))}
    RESULTS.append(record)
    (OUT / 'proofs.json').write_text(json.dumps(RESULTS, indent=2) + '\n')
    print(record, flush=True)
    assert proc.returncode == expected, record


def state_identity(state):
    files = ['predeploy.sha', 'unit-state.json', 'predeploy.crontab',
             'resume-services', 'resume-timers', 'functions.bash',
             'predeploy-bundle/manifest.json']
    return {name: sha(state / name) for name in files}


def render(block, state):
    text = block.replace('$HOME/trading-engine', str(ROOT))
    text = text.replace('$HOME/p22-deploy-20261018', str(state))
    text = text.replace('$HOME/.config/systemd/user', str(UNITS))
    # All names, discovery prefixes, reader selectors and process patterns use
    # the same namespace; systemctl remains the real host binary.
    for prefix in ('trading-engine-', 'massive-', 'te-autopush', 'store-sync',
                   'trading-data-backup'):
        text = text.replace(prefix, PREFIX + prefix)
    text = text.replace('127.0.0.1:8000', f'127.0.0.1:{API_PORT}')
    text = text.replace('127.0.0.1:3000', f'127.0.0.1:{UI_PORT}')
    links = '\n'.join(f'ln -sf {UNITS / name} {RUNTIME_UNITS / name}' for name in sorted(UNIT_NAMES) if 'accounts-settle' in name or 'options-daily' in name)
    text = text.replace('systemctl --user daemon-reload', links + '\nsystemctl --user daemon-reload')
    return text


def write_unit(name, text):
    name = PREFIX + name
    assert not (UNITS / name).exists()
    (UNITS / name).write_text(text)
    (RUNTIME_UNITS / name).symlink_to(UNITS / name)
    UNIT_NAMES.add(name)


def service_env():
    return '\n'.join(f'Environment="{key}={value}"' for key, value in ENV.items()
                     if key.startswith(('TRADING_ENGINE_', 'PYTHONPATH', 'OPENBLAS_',
                                        'OMP_', 'MKL_', 'P22_HARNESS_')))


def prepare():
    subprocess.run(['df', '-h', str(OUT)], check=True)
    assert shutil.disk_usage(OUT).free - ARGS.snapshot.stat().st_size >= 70 * 1024**3
    assert not ROOT.exists()
    subprocess.run(['/usr/bin/git', 'clone', '--no-hardlinks', str(REPO), str(ROOT)], check=True)
    original = command(['/usr/bin/git', 'rev-parse', 'origin/main']).strip()
    target = command(['/usr/bin/git', 'rev-parse', 'HEAD']).strip()
    subprocess.run(['/usr/bin/git', 'clone', '--bare', '--no-hardlinks', str(REPO), str(OUT / 'upstream.git')], check=True)
    command(['/usr/bin/git', 'update-ref', 'refs/heads/main', target], cwd=OUT / 'upstream.git')
    command(['/usr/bin/git', 'remote', 'set-url', 'origin', OUT / 'upstream.git'])
    command(['/usr/bin/git', 'checkout', '--detach', original])
    ENV['P22_APPROVED_SHA'] = target
    (OUT / 'bin').mkdir()
    UNITS.mkdir()
    (OUT / 'bin/git').symlink_to('/usr/bin/git')
    # Deliberately virtualize only cron storage. No call reaches host crontab.
    (OUT / 'bin/crontab').write_text('''#!/usr/bin/python3
import os,sys
from pathlib import Path
p=Path(os.environ['P22_HARNESS_OUT'])/'crontab'
a=sys.argv[1:]
if a==['-l']:
 if not p.exists():sys.exit(1)
 print(p.read_text(),end='')
elif a==['-r']:
 if not p.exists():sys.exit(1)
 p.unlink()
else:p.write_bytes(Path(a[0]).read_bytes())
''')
    (OUT / 'bin/crontab').chmod(0o755)
    (OUT / 'crontab').write_text('30 22 * * 1-5 isolated/engine/run_daily.sh\n')
    # Venv's interpreter is reusable; all module imports come from the copied source.
    (ROOT / '.venv').symlink_to(REPO / '.venv')
    shutil.rmtree(ROOT / 'data')
    shutil.copytree(ARGS.evidence, ROOT / 'data')
    (ROOT / 'logs').mkdir(exist_ok=True)
    # The supplied evidence directory is from the cited readiness rehearsal.
    reviewed = ARGS.evidence.parents[1] / 'rehearsal-main/logs/friday-postflight.json'
    if reviewed.exists():
        shutil.copy2(reviewed, ROOT / 'logs/friday-postflight.json')
    (ROOT / 'store').mkdir()
    DB = ROOT / 'store/market.duckdb'
    shutil.copy2(ARGS.snapshot, DB)
    DB.chmod(0o600)
    identity = {'original': original, 'target': target, 'snapshot': str(ARGS.snapshot),
                'snapshot_sha256': json.loads(ARGS.snapshot.with_suffix('.json').read_text())['sha256'], 'copy_sha256': sha(DB),
                'git': command(['/usr/bin/git', '--version']).strip()}
    assert identity['snapshot_sha256'] == identity['copy_sha256']
    (OUT / 'identity.json').write_text(json.dumps(identity, indent=2) + '\n')
    # The backup/incident/publication copies below are outputs of the literal
    # procedure, not additional input-store copies.
    # Initial snapshot is produced from the one copied store by the actual tool.
    run('prepare-snapshot', '.venv/bin/python -m tools.publish_snapshot --source store/market.duckdb\n')
    # A local wrapper supplies known refusal/success behavior to the options
    # timer without provider traffic; it never changes registered source bytes.
    (OUT / 'oneshot.py').write_text('''import os,sys
from pathlib import Path
out=Path(os.environ['P22_HARNESS_OUT'])
if (out/'force-timer-failure').exists():
 print('controlled provider refusal',flush=True);sys.exit(2)
print('isolated first activation complete',flush=True)
''')
    # Actual UI build/start, with Next's real /api/health rewrite to copied API.
    shutil.copytree(REPO / 'ui/node_modules', ROOT / 'ui/node_modules', symlinks=True)
    npm = shutil.which('npm')
    env_lines = service_env()
    write_unit('trading-engine-api.service', f'''[Service]
Type=simple
WorkingDirectory={ROOT}
ExecStart={PYTHON} -m uvicorn server.main:app --host 127.0.0.1 --port {API_PORT}
{env_lines}
''')
    write_unit('trading-engine-ui.service', f'''[Service]
Type=simple
WorkingDirectory={ROOT}/ui
ExecStartPre={npm} run build
ExecStart={npm} run start -- --hostname 127.0.0.1 --port {UI_PORT}
Environment=UI_INTERNAL_API_ORIGIN=http://127.0.0.1:{API_PORT}
Environment=NEXT_TELEMETRY_DISABLED=1
Environment=PATH={os.environ["PATH"]}
TimeoutStartSec=5min
''')
    (OUT / 'sentinel.py').write_text('''import os
print('sentinel ready',flush=True)
r,w=os.pipe();os.read(r,1)
''')
    for name in ('te-autopush', 'massive-minute', 'store-sync'):
        write_unit(name + '.service', f'''[Service]
Type=simple
ExecStart={PYTHON} {OUT}/sentinel.py
''')
        write_unit(name + '.timer', f'''[Timer]
OnCalendar=2099-01-01 00:00:00 UTC
Unit={PREFIX}{name}.service
[Install]
WantedBy=timers.target
''')
    systemctl('daemon-reload')
    systemctl('start', PREFIX + 'te-autopush.timer', PREFIX + 'massive-minute.service')
    # Capture the real prior reader activation state.
    systemctl('start', '--no-block', PREFIX + 'trading-engine-api.service', PREFIX + 'trading-engine-ui.service')
    subprocess.run(['curl', '--fail', '--silent', '--retry', '20', '--retry-connrefused',
                    '--retry-delay', '1', f'http://127.0.0.1:{API_PORT}/health'], check=True)


def install_sources():
    # In the copied checkout only, render the four install inputs. They are
    # unregistered unit templates and intentionally excluded from source-refusal.
    for name in ('trading-engine-accounts-settle', 'massive-options-daily'):
        original = (REPO / 'server' / (name + '.service')).read_text()
        original = original.replace('%h/trading-engine', str(ROOT))
        if name == 'massive-options-daily':
            # Control only external provider work; timer/status logic is literal.
            original = re.sub(r'^ExecStart=.*\n', '', original, flags=re.M)
            original += f'ExecStart={PYTHON} {OUT}/oneshot.py\n'
        original = original.replace('[Service]', '[Service]\n' + service_env())
        (ROOT / 'server' / (PREFIX + name + '.service')).write_text(original)
        timer = (REPO / 'server' / (name + '.timer')).read_text()
        timer = timer.replace('Unit=' + name, 'Unit=' + PREFIX + name)
        # Keep Persistent=true and force a due calendar activation in isolation.
        timer = re.sub(r'^OnCalendar=.*$', 'OnCalendar=2020-01-01 00:00:00 UTC', timer, flags=re.M)
        (ROOT / 'server' / (PREFIX + name + '.timer')).write_text(timer)
        UNIT_NAMES.update({PREFIX + name + '.service', PREFIX + name + '.timer'})



def cleanup():
    # Names are fixed and never include a live unit.
    for name in UNIT_NAMES:
        subprocess.run(['/usr/bin/systemctl', '--user', 'stop', name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    for name in UNIT_NAMES:
        p = RUNTIME_UNITS / name
        if p.exists() or p.is_symlink():
            p.unlink()
        for directory in (RUNTIME_UNITS, Path.home() / '.config/systemd/user'):
            for relative in (name, 'timers.target.wants/' + name):
                p = directory / relative
                if p.is_symlink():
                    p.unlink()
    subprocess.run(['/usr/bin/systemctl', '--user', 'daemon-reload'], check=True)
    deleted = []
    for p in OUT.rglob('*.duckdb'):
        if p.is_symlink():
            p.unlink()
        elif p.is_file():
            deleted.append({'path': str(p), 'bytes': p.stat().st_size})
            p.unlink()
    for p in OUT.rglob('*.duckdb.wal'):
        p.unlink()
    if ROOT.exists():
        shutil.rmtree(ROOT)
    (OUT / 'cleanup.json').write_text(json.dumps({'copies_deleted': deleted,
                                                'checkout_deleted': not ROOT.exists()}, indent=2) + '\n')


text = (REPO / 'docs/settlement-runbook.md').read_text()
section = text[text.index('Block 1 —'):text.index('## P22 deploy/rollback rehearsal —')]
BLOCKS = re.findall(r'```bash\n(.*?)```', section, re.S)
assert len(BLOCKS) == 6
for i, block in enumerate(BLOCKS, 1):
    (OUT / f'literal-{i}.bash').write_text(block)
    subprocess.run(['/usr/bin/bash', '-n', OUT / f'literal-{i}.bash'], check=True)
try:
    prepare()
    install_sources()
    # Namespaced install input files are test fixtures, not operator edits.
    command(['/usr/bin/git', 'config', 'core.excludesFile', OUT / 'excludes'])
    (OUT / 'excludes').write_text('server/p22-rb-*\n.venv\n')
    state = OUT / 'state'
    blocks = [render(b, state) for b in BLOCKS]
    run('full-deploy', ''.join(blocks[:3]))
    saved = state_identity(state)
    run('second-setup-refused', blocks[0], expected=1)
    assert state_identity(state) == saved
    # Fresh Bash knows no prior function or shell variable.
    run('fresh-shell-recovery', blocks[3] + blocks[4])
    assert state_identity(state) == saved
    assert command(['/usr/bin/systemctl', '--user', 'show', PREFIX + 'te-autopush.timer', '--property=ActiveState', '--value']).strip() == 'inactive'
    # Reconcile the copied main only and execute the final explicit release block.
    original = json.loads((OUT / 'identity.json').read_text())['original']
    command(['/usr/bin/git', 'checkout', '-B', 'main', original])
    run('recovery-explicit-release', blocks[3].split('p22_quiesce\n')[0] + blocks[5],
        extra={'P22_RECONCILED_SHA': original})
    # Remove completed incident/backup snapshot duplicates before reusing the
    # single working store for the forced-failure scenario.
    for completed in state.rglob('*.duckdb'):
        completed.unlink()
    # A second incident has its own immutable setup. The store is reused, not recopied.
    state2 = OUT / 'failure-state'
    failure = [render(b, state2) for b in BLOCKS]
    install_sources()
    (OUT / 'force-timer-failure').touch()
    run('forced-mid-deploy-failure', ''.join(failure[:3]), expected=1)
    saved2 = state_identity(state2)
    (OUT / 'force-timer-failure').unlink()
    run('failed-deploy-fresh-shell-recovery', failure[3] + failure[4])
    assert state_identity(state2) == saved2
    # Refuse unarchived source/index changes before any incident mutation.
    (ROOT / 'unknown-source.txt').write_text('unexplained edit\n')
    run('source-change-refused', failure[3], expected=1)
    (ROOT / 'unknown-source.txt').unlink()
    # Stage a real source edit.
    (ROOT / 'unknown-source.txt').write_text('staged edit\n')
    command(['/usr/bin/git', 'add', 'unknown-source.txt'])
    run('staged-change-refused', failure[3], expected=1)
    command(['/usr/bin/git', 'reset', 'HEAD', '--', 'unknown-source.txt'])
    (ROOT / 'unknown-source.txt').unlink()
    # Test actual argv matching with a DB handle closed (there is no DB open).
    probe = 'set -eEuo pipefail\nP22_ROOT=' + str(ROOT) + '\nP22_STATE=' + str(state2) + '\nexport P22_ROOT P22_STATE\nsource "$P22_STATE/functions.bash"\n'
    drivers = ['run_daily.sh', 'run_weekly_walkforward.sh', 'run_weekly_liquid.sh',
               'run_weekend_sweeps.sh', 'run_weekly_verify.sh']
    descendants = ['tools.verify_friday_postflight --publish', 'engine.collect',
                   'engine.verify_prices', 'engine.queue_runner', 'engine.sync',
                   'tools.free_massive_minute']
    for index, driver in enumerate(drivers + descendants):
        argv = (f'/bin/bash {ROOT}/engine/{driver}' if driver in drivers else
                f'{ROOT}/.venv/bin/python -m {driver}')
        process = subprocess.Popen([argv, str(OUT / 'sentinel.py')], executable=str(PYTHON),
                                   cwd=ROOT, env=ENV, stdout=subprocess.PIPE, text=True)
        try:
            assert process.stdout.readline().strip() == 'sentinel ready'
            run(f'driver-detected-{index + 1}', probe + 'p22_process_check\n', expected=1)
        finally:
            process.terminate()
            process.wait(timeout=10)
    # Hold an actual producer lock; literal rollback refuses before incident mkdir.
    lock = subprocess.Popen([str(PYTHON), '-c',
        "import fcntl,os;f=open('.liquid.lock','a');fcntl.flock(f,fcntl.LOCK_EX);print('locked',flush=True);r,w=os.pipe();os.read(r,1)"],
        cwd=ROOT, env=ENV, stdout=subprocess.PIPE, text=True)
    try:
        assert lock.stdout.readline().strip() == 'locked'
        run('rollback-lock-refused', probe + 'p22_lock\n', expected=1)
    finally:
        lock.terminate()
        lock.wait(timeout=10)
    print('ALL LITERAL RUNBOOK PROOFS PASSED', flush=True)
finally:
    cleanup()
