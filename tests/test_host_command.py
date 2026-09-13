"""Tests for bounded read-only host-command capture."""

import os
import sys
import time
from io import BytesIO
from pathlib import Path
from subprocess import TimeoutExpired

import pytest

from server import host_command


def _python(source: str) -> list[str]:
    return [sys.executable, "-c", source]


def _assert_process_stopped(pid: int) -> None:
    deadline = time.monotonic() + 1
    while True:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().split()[2]
        except (FileNotFoundError, ProcessLookupError):
            state = None
        if state in {None, "X", "Z"} or time.monotonic() >= deadline:
            break
        time.sleep(0.01)
    assert state in {None, "X", "Z"}


@pytest.mark.parametrize("value", [None, "", "   ", "a\nb", "a\tb", "a\x00b", "x" * 5])
def test_bounded_printable_line_rejects_non_public_text(value):
    assert host_command.bounded_printable_line(value, max_chars=4) is None


def test_bounded_printable_line_trims_framing_and_counts_unicode_characters():
    assert host_command.bounded_printable_line("  Etc/UTC\n", max_chars=7) == "Etc/UTC"
    assert host_command.bounded_printable_line("💥" * 4, max_chars=4) == "💥" * 4


def test_bounded_command_captures_stdout_stderr_and_exit_status(tmp_path):
    result = host_command.run_bounded(
        _python("import os,sys; print(os.getcwd()); print('warning', file=sys.stderr); sys.exit(3)"),
        cwd=tmp_path,
    )

    assert result is not None
    assert result.returncode == 3
    assert result.stdout == f"{tmp_path}\n"
    assert result.stderr == "warning\n"


@pytest.mark.parametrize("missing_stream", ["stdout", "stderr"])
def test_bounded_command_fails_closed_when_pipe_is_missing(monkeypatch, missing_stream):
    class Process:
        pid = 123
        stdout = None if missing_stream == "stdout" else BytesIO()
        stderr = None if missing_stream == "stderr" else BytesIO()

    process = Process()
    stopped = []
    monkeypatch.setattr(host_command.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(host_command, "_stop", lambda value: stopped.append(value))

    assert host_command.run_bounded(["probe"]) is None
    assert stopped == [process]
    present_stream = process.stderr if process.stdout is None else process.stdout
    assert present_stream is not None and present_stream.closed


def test_bounded_command_rejects_combined_output_above_limit():
    result = host_command.run_bounded(
        _python("import sys; sys.stdout.write('a' * 5); sys.stderr.write('b' * 4)"),
        max_output_bytes=8,
    )

    assert result is None


def test_bounded_command_accepts_output_at_exact_limit():
    result = host_command.run_bounded(
        _python("import sys; sys.stdout.write('a' * 4); sys.stderr.write('b' * 4)"),
        max_output_bytes=8,
    )

    assert result is not None
    assert len(result.stdout.encode()) + len(result.stderr.encode()) == 8


def test_bounded_command_times_out_and_reaps_child(tmp_path):
    pid_path = tmp_path / "pid"
    result = host_command.run_bounded(
        _python(
            "import os,time; "
            f"open({str(pid_path)!r}, 'w').write(str(os.getpid())); "
            "time.sleep(10)"
        ),
        timeout=0.05,
    )

    assert result is None
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)


def test_bounded_command_times_out_after_child_closes_output_pipes(tmp_path):
    pid_path = tmp_path / "pid"
    result = host_command.run_bounded(
        _python(
            "import os,time; "
            f"open({str(pid_path)!r}, 'w').write(str(os.getpid())); "
            "os.close(1); os.close(2); time.sleep(10)"
        ),
        timeout=0.05,
    )

    assert result is None
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)


def test_bounded_command_timeout_kills_descendant_holding_output_pipes(tmp_path):
    child_pid_path = tmp_path / "child-pid"
    child_source = "import time; time.sleep(10)"
    result = host_command.run_bounded(
        _python(
            "import subprocess,sys,time; child = "
            f"subprocess.Popen([sys.executable, '-c', {child_source!r}]); "
            f"open({str(child_pid_path)!r}, 'w').write(str(child.pid)); "
            "time.sleep(10)"
        ),
        timeout=0.1,
    )

    assert result is None
    _assert_process_stopped(int(child_pid_path.read_text()))


def test_bounded_command_rejects_non_utf8_output():
    result = host_command.run_bounded(
        _python("import os; os.write(1, bytes([255]))"),
    )

    assert result is None


def test_bounded_command_invalid_utf8_kills_descendant_after_parent_exits(tmp_path):
    child_pid_path = tmp_path / "child-pid"
    child_source = "import os,time; os.close(1); os.close(2); time.sleep(10)"
    result = host_command.run_bounded(
        _python(
            "import os,subprocess,sys; child = "
            f"subprocess.Popen([sys.executable, '-c', {child_source!r}]); "
            f"open({str(child_pid_path)!r}, 'w').write(str(child.pid)); "
            "os.write(1, bytes([255]))"
        ),
    )

    assert result is None
    _assert_process_stopped(int(child_pid_path.read_text()))


def test_command_budget_is_context_local_nested_and_restored(monkeypatch):
    monotonic_values = iter((100.0, 102.0))
    monkeypatch.setattr(host_command.time, "monotonic", lambda: next(monotonic_values))

    with host_command.command_budget(5):
        assert host_command._COMMAND_DEADLINE.get() == 105.0
        with host_command.command_budget(10):
            assert host_command._COMMAND_DEADLINE.get() == 105.0
        assert host_command._COMMAND_DEADLINE.get() == 105.0

    assert host_command._COMMAND_DEADLINE.get() is None


def test_expired_command_budget_does_not_launch_process(monkeypatch):
    monotonic_values = iter((100.0, 105.0))
    monkeypatch.setattr(host_command.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(
        host_command.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("expired command must not launch"),
    )

    with host_command.command_budget(5):
        assert host_command.run_bounded(["probe"]) is None


def test_command_budget_clamps_command_deadline(monkeypatch):
    class Process:
        stdout = BytesIO()
        stderr = BytesIO()

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    monotonic_values = iter((100.0, 101.0, 102.0))
    observed_deadlines = []
    monkeypatch.setattr(host_command.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(host_command.subprocess, "Popen", lambda *args, **kwargs: Process())
    monkeypatch.setattr(
        host_command,
        "_capture",
        lambda process, deadline, max_output_bytes: (
            observed_deadlines.append(deadline) or (b"", b"")
        ),
    )

    with host_command.command_budget(5):
        assert host_command.run_bounded(["probe"], timeout=10) is not None

    assert observed_deadlines == [105.0]


@pytest.mark.parametrize("timeout", [0, -1])
def test_command_budget_rejects_invalid_timeout(timeout):
    with pytest.raises(ValueError, match="command budget must be positive"):
        with host_command.command_budget(timeout):
            pass


def test_wait_timeout_stops_group_even_if_leader_exits_before_finalizer(monkeypatch):
    class Process:
        pid = 123
        stdout = BytesIO()
        stderr = BytesIO()

        def wait(self, timeout=None):
            if timeout is not None:
                raise TimeoutExpired(("probe",), timeout)
            return 0

        def poll(self):
            return 0

    process = Process()
    stopped = []
    monkeypatch.setattr(host_command.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(host_command, "_capture", lambda *args, **kwargs: (b"", b""))
    monkeypatch.setattr(host_command, "_stop", lambda value: stopped.append(value))

    assert host_command.run_bounded(["probe"], timeout=1) is None
    assert stopped == [process]


def test_stop_bounds_reap_after_killing_private_process_group(monkeypatch):
    class Process:
        pid = 123

        def wait(self, timeout=None):
            assert timeout == host_command.HOST_COMMAND_REAP_TIMEOUT_SECONDS
            raise TimeoutExpired(("probe",), timeout)

    killed = []
    monkeypatch.setattr(
        host_command.os,
        "killpg",
        lambda pid, sig: killed.append((pid, sig)),
    )

    host_command._stop(Process())

    assert killed == [(123, host_command.signal.SIGKILL)]


def test_stop_falls_back_to_leader_kill_and_contains_cleanup_errors(monkeypatch):
    class Process:
        pid = 123

        def kill(self):
            raise PermissionError("leader kill denied")

        def wait(self, timeout=None):
            assert timeout == host_command.HOST_COMMAND_REAP_TIMEOUT_SECONDS
            raise ChildProcessError("already reaped elsewhere")

    def fail_group_kill(_pid, _signal):
        raise PermissionError("group kill denied")

    monkeypatch.setattr(host_command.os, "killpg", fail_group_kill)

    host_command._stop(Process())


@pytest.mark.parametrize(
    ("timeout", "max_output_bytes"),
    [(0, 1), (-1, 1), (1, 0), (1, -1)],
)
def test_bounded_command_rejects_invalid_bounds(timeout, max_output_bytes):
    with pytest.raises(ValueError, match="command bounds must be positive"):
        host_command.run_bounded(
            _python("pass"), timeout=timeout, max_output_bytes=max_output_bytes
        )
