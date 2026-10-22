"""Test speed: shared synthetic setup, balanced workers and shards, RAM temp files.

Every test keeps its own private databases and runs exactly once per run.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter
from contextlib import closing, contextmanager
from functools import lru_cache
from pathlib import Path

import duckdb
import pytest

DURATIONS = Path(__file__).with_name("durations.json")
# Recorded per-test seconds at or above this go first when tests are distributed.
SLOW_TEST_SECONDS = 1.0
# Estimate for a file absent from the recorded durations (new since the last record).
UNKNOWN_TEST_SECONDS = 0.1
# Leave tmpfs alone unless this much is free; a full -n 8 run peaked at 3.3 GiB.
MEMORY_TEMP_MIN_FREE = 6 << 30


def pytest_addoption(parser):
    group = parser.getgroup("test speed")
    group.addoption("--test-shards", type=int, default=1, help="Number of CI file shards")
    group.addoption("--test-shard", type=int, default=0, help="Zero-based CI shard index")
    group.addoption("--record-durations", metavar="PATH", default=None,
                    help="Write per-file and slow-test durations from this run as JSON")
    group.addoption("--record-reads", metavar="PATH", default=None,
                    help="Write the repository files each test file opens or lists as JSON")
    group.addoption("--duration-budget", type=float, metavar="SECONDS", default=None,
                    help="Fail the run if a test not marked slow takes longer than this "
                         "(setup, call and teardown)")


@pytest.hookimpl(tryfirst=True)  # before the tmp_path factory reads --basetemp
def pytest_configure(config):
    count, index = config.getoption("test_shards"), config.getoption("test_shard")
    if count < 1 or not 0 <= index < count:
        raise pytest.UsageError("require --test-shards >= 1 and 0 <= --test-shard < --test-shards")
    if config.getoption("record_reads"):
        config.pluginmanager.register(_ReadRecorder(config), "test-speed-reads")
    if hasattr(config, "workerinput"):
        return
    if config.getoption("record_durations"):
        config.pluginmanager.register(_DurationRecorder(config), "test-speed-durations")
    if config.getoption("duration_budget") is not None:
        config.pluginmanager.register(_DurationBudget(config), "test-speed-budget")
    _use_memory_temp(config)


def _use_memory_temp(config, root=Path("/dev/shm")):
    """Put tmp_path and TMPDIR on tmpfs when there is room; files are unchanged.

    Most of the suite's waiting is fsync from DuckDB checkpoints and copied
    stores on disk. A RAM-backed base keeps every file operation real (locks,
    renames, copies, checkpoints) without the device flush. Workers inherit the
    base and TMPDIR, so dry-run copies stay on the same filesystem as tmp_path.
    The run directory is removed at exit; TEST_SPEED_TMPFS=0 or an explicit
    --basetemp keeps pytest's default on-disk temporary directories.
    """
    import getpass
    import os
    import tempfile

    if config.option.basetemp or os.environ.get("TEST_SPEED_TMPFS") == "0":
        return
    try:
        if shutil.disk_usage(root).free < MEMORY_TEMP_MIN_FREE or not os.access(root, os.W_OK):
            return
        parent = root / f"pytest-of-{getpass.getuser()}"
        parent.mkdir(mode=0o700, exist_ok=True)
        for stale in parent.glob("run-*"):
            if not _process_alive(stale.name.removeprefix("run-")):
                shutil.rmtree(stale, ignore_errors=True)
        run = parent / f"run-{os.getpid()}"
        (run / "tmp").mkdir(parents=True)
    except OSError:
        return
    previous = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = str(run / "tmp")
    tempfile.tempdir = None
    config.option.basetemp = str(run / "base")

    def cleanup():
        if previous is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = previous
        tempfile.tempdir = None
        shutil.rmtree(run, ignore_errors=True)

    config.add_cleanup(cleanup)


def _process_alive(pid):
    import os

    try:
        os.kill(int(pid), 0)
    except (ValueError, ProcessLookupError):
        return False
    except PermissionError:
        return True
    return True


def _recorded_durations():
    try:
        recorded = json.loads(DURATIONS.read_text())
    except (OSError, ValueError):
        return {}, {}
    return recorded.get("files", {}), recorded.get("slow_tests", {})


def shard_files(filenames, counts, file_seconds, shards):
    """Longest-first file assignment to the least-loaded shard; a partition.

    Every shard collects the same files, so each computes the same mapping.
    Stale or missing durations only change balance, never which tests run.
    """
    def cost(name):
        return file_seconds.get(name, counts[name] * UNKNOWN_TEST_SECONDS)

    loads = [0.0] * shards
    assignment = {}
    for name in sorted(filenames, key=lambda name: (-cost(name), name)):
        shard = min(range(shards), key=lambda index: (loads[index], index))
        assignment[name] = shard
        loads[shard] += cost(name)
    return assignment


def pytest_collection_modifyitems(config, items):
    """Balance CI file shards and start known-slow tests first under xdist.

    The default run selects everything; serial runs keep collection order.
    """
    file_seconds, slow_tests = _recorded_durations()
    count, index = config.getoption("test_shards"), config.getoption("test_shard")
    if count > 1:
        counts = Counter(item.nodeid.split("::", 1)[0] for item in items)
        assignment = shard_files(counts, counts, file_seconds, count)
        selected, excluded = [], []
        for item in items:
            filename = item.nodeid.split("::", 1)[0]
            (selected if assignment[filename] == index else excluded).append(item)
        items[:] = selected
        config.hook.pytest_deselected(items=excluded)
    if hasattr(config, "workerinput"):
        # Every worker orders the same collection identically, as xdist requires.
        items[:] = slow_first(items, slow_tests, config.workerinput["workercount"])


def slow_first(items, slow_tests, workers):
    """Give each worker's first block a longest-first share of the slow tests.

    With --dist=worksteal xdist splits the ordered collection into one
    contiguous block per worker (each the remaining count divided by the
    remaining workers) and an idle worker later steals the back half of the
    longest queue. Slow tests are binned longest-first onto the least-loaded
    block and placed at its front, so they never queue behind each other or
    get stolen; the other tests fill the blocks in collection order and keep
    their file locality. Only the order changes, never the set.
    """
    slow = sorted(
        (item for item in items if slow_tests.get(item.nodeid, 0.0) >= SLOW_TEST_SECONDS),
        key=lambda item: -slow_tests[item.nodeid],
    )
    bins, loads = [[] for _ in range(workers)], [0.0] * workers
    for item in slow:
        lightest = min(range(workers), key=lambda index: (loads[index], index))
        bins[lightest].append(item)
        loads[lightest] += slow_tests[item.nodeid]
    chosen = {id(item) for item in slow}
    rest = [item for item in items if id(item) not in chosen]
    ordered, remaining, start = [], len(items), 0
    for index, block in enumerate(bins):
        size = remaining // (workers - index)
        remaining -= size
        if len(block) > size:  # too few tests to give every worker a block
            return [*slow, *rest]
        ordered += block + rest[start:start + size - len(block)]
        start += size - len(block)
    return ordered


class _DurationRecorder:
    """Controller-side setup+call+teardown totals; workers report every phase."""

    def __init__(self, config):
        self.path = Path(config.getoption("record_durations"))
        self.seconds = Counter()

    def pytest_runtest_logreport(self, report):
        self.seconds[report.nodeid] += report.duration

    def pytest_sessionfinish(self, session):
        files = Counter()
        for nodeid, seconds in self.seconds.items():
            files[nodeid.split("::", 1)[0]] += seconds
        payload = {
            "comment": "Recorded by --record-durations; used only to order and shard tests.",
            "files": {name: round(value, 2) for name, value in sorted(files.items())},
            "slow_tests": {
                nodeid: round(value, 2) for nodeid, value in sorted(self.seconds.items())
                if value >= SLOW_TEST_SECONDS
            },
        }
        self.path.write_text(json.dumps(payload, indent=1) + "\n")


class _DurationBudget:
    """Controller side: a test over the budget must carry the ``slow`` marker.

    CI passes ``--duration-budget`` only on ``main``, where runner noise cannot block a
    pull request; the test still runs and its own result stands.
    """

    def __init__(self, config):
        self.budget = config.getoption("duration_budget")
        self.seconds = Counter()
        self.slow: set[str] = set()

    def pytest_runtest_logreport(self, report):
        self.seconds[report.nodeid] += report.duration
        if "slow" in report.keywords:
            self.slow.add(report.nodeid)

    def over_budget(self):
        return sorted(
            (nodeid, seconds) for nodeid, seconds in self.seconds.items()
            if seconds > self.budget and nodeid not in self.slow
        )

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session):
        over = self.over_budget()
        if not over:
            return
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        lines = [f"{len(over)} test(s) over the {self.budget:g} s budget without "
                 "@pytest.mark.slow:"]
        lines += [f"  {seconds:.1f} s {nodeid}" for nodeid, seconds in over]
        if reporter is not None:
            reporter.write_line("\n".join(lines), red=True)
        if session.exitstatus == pytest.ExitCode.OK:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


class _ReadRecorder:
    """Repository files each test opens or lists, for ``tools.affected_tests``.

    An audit hook in every process records paths under the repository root (outside
    ``.git`` and ``.venv``) against the running test; each test's set travels to the
    controller in its teardown report. Collection and module-import reads are not
    attributed, and a cached read counts only for the test that first made it.
    """

    SKIP = frozenset({".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"})

    def __init__(self, config):
        import sys

        self.config = config
        self.root = Path(config.rootpath).resolve()
        self.current: set[str] | None = None
        self.files: dict[str, set[str]] = {}
        sys.addaudithook(self._audit)

    def _audit(self, event, args):
        if self.current is None or event not in {"open", "os.listdir", "os.scandir", "glob.glob"}:
            return
        import os

        raw = args[0] if args and args[0] is not None else "."
        if isinstance(raw, int):
            return
        try:
            path = Path(os.path.normpath(os.path.join(os.getcwd(), os.fsdecode(raw))))
            relative = path.relative_to(self.root)
        except (TypeError, ValueError, OSError):
            return
        if not self.SKIP.intersection(relative.parts):
            self.current.add(relative.as_posix())

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item):
        self.current = set()
        yield
        self.current = None

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_teardown(self, item):
        yield
        item.user_properties.append(("repository_reads", sorted(self.current or ())))

    def pytest_runtest_logreport(self, report):
        if report.when == "teardown":
            reads = dict(report.user_properties).get("repository_reads", ())
            self.files.setdefault(report.nodeid.split("::", 1)[0], set()).update(reads)

    def pytest_sessionfinish(self, session):
        if hasattr(self.config, "workerinput"):
            return
        payload = {name: sorted(paths) for name, paths in sorted(self.files.items())}
        Path(self.config.getoption("record_reads")).write_text(json.dumps(payload, indent=1) + "\n")


@pytest.fixture(scope="session", autouse=True)
def test_duckdb_threads():
    """xdist supplies parallelism; small databases need one native worker.

    Explicit connection configurations and subsequent SET threads statements
    still take precedence for resource tests. Session templates also use UTC.
    """
    original = duckdb.connect

    def connect(*args, **kwargs):
        config = kwargs.get("config") if len(args) < 3 else args[2]
        if not config or not any(key.lower() == "threads" for key in config):
            config = {**(config or {}), "threads": 1}
            if len(args) < 3:
                kwargs["config"] = config
            else:
                args = (*args[:2], config, *args[3:])
        connection = original(*args, **kwargs)
        connection.execute("SET TimeZone='UTC'")
        return connection

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(duckdb, "connect", connect)
        yield


class _Uncacheable(Exception):
    pass


def _canonical(value):
    """Exact, type-tagged form of solver inputs; anything else is not cached."""
    import numpy as np

    kind = type(value)
    if value is None or kind in (bool, int, str):
        return (kind.__name__, value)
    if kind is float:
        return ("float", value.hex())
    if kind is np.ndarray and value.dtype != object:
        return ("ndarray", value.dtype.str, value.shape, value.tobytes())
    if isinstance(value, np.generic) and not isinstance(value, np.object_):
        return ("scalar", value.dtype.str, value.tobytes())
    if kind in (list, tuple):
        return (kind.__name__, tuple(_canonical(item) for item in value))
    if kind is dict and all(type(key) is str for key in value):
        return ("dict", tuple(sorted((key, _canonical(item)) for key, item in value.items())))
    raise _Uncacheable(kind.__name__)


def _without_timings(value):
    if isinstance(value, dict):
        return {key: _without_timings(item) for key, item in value.items()
                if key not in {"solve_seconds", "solve_seconds_total"}}
    if isinstance(value, list):
        return [_without_timings(item) for item in value]
    return value


@pytest.fixture(scope="session", autouse=True)
def p16_calibration_memo(request, tmp_path_factory):
    """Share each deterministic P16 lambda calibration across the run.

    `calibrate_lambda` is a pure function of its cases and grid apart from the
    retained solve timings (which no reader compares with a recomputation).
    The same synthetic cohorts are calibrated by many tests and again by the
    store's validation, about seven seconds each. A result is reused only for a
    byte-identical input while the calibration, optimizer and projection
    modules are unpatched; a test that substitutes any of them runs the real
    call. TEST_SPEED_VERIFY_MEMO=1 recomputes every reuse and fails on any
    difference outside the timings, or on an input the call mutated.
    """
    import fcntl
    import os
    import pickle

    from farm import p16_calibration, p16_optimizer, p16_projection

    original = p16_calibration.calibrate_lambda
    verify = os.environ.get("TEST_SPEED_VERIFY_MEMO") == "1"
    base = tmp_path_factory.getbasetemp()
    if hasattr(request.config, "workerinput"):
        base = base.parent
    root = base / "p16-calibration-memo"
    root.mkdir(exist_ok=True)
    modules = (p16_calibration, p16_optimizer, p16_projection)

    def calibrate_lambda(cases, grid=None):
        if not all(len(vars(module)) == len(state) and all(
                vars(module).get(name, state) is value for name, value in state.items())
                for module, state in pristine):
            return original(cases, grid)
        try:
            key = _canonical([cases, grid, p16_calibration.DEFAULT_LAMBDA_GRID])
        except _Uncacheable:
            return original(cases, grid)
        digest = hashlib.sha256(pickle.dumps(key, protocol=5)).hexdigest()
        path = root / f"{digest}.pickle"
        with (root / f"{digest}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if not path.exists():
                    result = original(cases, grid)
                    pending = root / f"{digest}.pending"
                    pending.write_bytes(pickle.dumps(result, protocol=5))
                    pending.replace(path)
                    return result
                cached = pickle.loads(path.read_bytes())
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
        if verify:
            fresh = original(cases, grid)
            assert _canonical([cases, grid, p16_calibration.DEFAULT_LAMBDA_GRID]) == key, (
                "calibrate_lambda mutated its input")
            assert _canonical(_without_timings(fresh)) == _canonical(
                _without_timings(cached)), "memoized calibration differs from a fresh solve"
        return cached

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(p16_calibration, "calibrate_lambda", calibrate_lambda)
        pristine = [(module, dict(vars(module))) for module in modules]
        yield


@pytest.fixture(scope="session")
def daily_database_template(request, tmp_path_factory, test_duckdb_threads):
    """Build once per run; every worker copies the same closed template."""
    from tests.test_daily_opportunities import _database

    with _shared_templates(request, tmp_path_factory, {"market": _database}) as templates:
        path = templates["market"]
        yield path


@contextmanager
def _shared_templates(request, tmp_path_factory, builders):
    """Serialize template creation; never keep a template connection open.

    xdist workers share the controller's base directory. Serial runs use their
    own base. pytest owns cleanup, so one worker cannot unlink another's source.
    """
    import fcntl

    base = tmp_path_factory.getbasetemp()
    if hasattr(request.config, "workerinput"):
        base = base.parent
    root = base / "closed-templates"
    root.mkdir(exist_ok=True)
    paths = {}
    for name, build in builders.items():
        path = root / f"{name}.duckdb"
        with (root / f"{name}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if not path.exists():
                    pending = root / f"{name}.pending.duckdb"
                    pending.unlink(missing_ok=True)
                    build(pending)
                    pending.replace(path)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
        paths[name] = path
    yield paths


@lru_cache(maxsize=1)
def dual_momentum_seed():
    """Retain all four tables generated by the original history helper."""
    from sim.schema import init_sim_schema
    from tests.agent_test_helpers import _build_dual_momentum_history, fixed_etf_market
    from tests.conftest import PRICES_DDL

    with closing(duckdb.connect()) as connection:
        connection.execute(PRICES_DDL)
        init_sim_schema(connection)
        fixed_etf_market(connection)
        market_date = _build_dual_momentum_history(connection)
        tables = ("prices", "universe", "corporate_actions", "actions_fetch_log")
        frames = {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY ALL").df()
            for table in tables
        }
        ddls = {
            table: connection.execute(
                "SELECT sql FROM duckdb_tables() WHERE table_name=?", [table],
            ).fetchone()[0]
            for table in ("corporate_actions", "actions_fetch_log")
        }
    return market_date, frames, ddls


@pytest.fixture(scope="session")
def account_database_templates(request, tmp_path_factory, test_duckdb_threads):
    """Closed source stores, privately copied before the real account lifecycle."""
    from tests import test_account_entrypoints_e2e

    builders = {
        name: getattr(test_account_entrypoints_e2e, name)
        for name in ("_main_store", "_daily_store", "_minute_store", "_short_store")
    }
    with _shared_templates(request, tmp_path_factory, builders) as templates:
        yield templates


def copy_daily_database(source, destination):
    """Copy a closed template into the calling test's own temporary directory."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def seed_dual_momentum_history(connection, seed):
    """Bulk insert cached rows, preserving the original replacement semantics."""
    market_date, frames, ddls = seed
    for table, frame in frames.items():
        if table in ddls:
            connection.execute(ddls[table].replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1))
        connection.execute(f"DELETE FROM {table}")
        connection.register("test_seed_rows", frame)
        try:
            connection.execute(f"INSERT INTO {table} SELECT * FROM test_seed_rows")
        finally:
            connection.unregister("test_seed_rows")
    return market_date


def _same_helper(candidate, original):
    """pytest's prepend mode can import a test file under two module names."""
    return (getattr(candidate, "__name__", None) == original.__name__
            and getattr(getattr(candidate, "__code__", None), "co_filename", None)
            == original.__code__.co_filename)


@pytest.fixture(autouse=True)
def populated_test_setup(request, monkeypatch, utc_duckdb_connections):
    """Replace only the helper aliases used by this test module.

    Template fixtures run before the test body can patch producers or connection
    factories. Helpers and aliases are restored after every test; assertions,
    production readers/writers and numerical calibration remain real.
    """
    from tests import test_account_entrypoints_e2e, test_daily_opportunities, test_p22_round2

    daily = test_daily_opportunities._database
    if _same_helper(getattr(request.module, "_database", None), daily):
        template = request.getfixturevalue("daily_database_template")

        def copied(path):
            copy_daily_database(template, path)

        monkeypatch.setattr(request.module, "_database", copied)

    harness = getattr(request.module, "Harness", None)
    harness_init = harness.__init__ if harness is not None else None
    if (_same_helper(getattr(request.module, "_main_store", None),
                     test_account_entrypoints_e2e._main_store)
            or _same_helper(harness_init, test_p22_round2.Harness.__init__)):
        templates = request.getfixturevalue("account_database_templates")
        for name, source in templates.items():
            def copied_account(path, source=source):
                copy_daily_database(source, path)

            monkeypatch.setattr(test_account_entrypoints_e2e, name, copied_account)
            monkeypatch.setattr(test_p22_round2, name, copied_account)
            if hasattr(request.module, name):
                monkeypatch.setattr(request.module, name, copied_account)
            if harness_init is not None:
                monkeypatch.setitem(harness_init.__globals__, name, copied_account)
