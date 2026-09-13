"""Bounded subprocess capture for read-only host-status probes."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import BinaryIO, Iterator, Sequence

MAX_HOST_COMMAND_BYTES = 1_048_576
HOST_COMMAND_TIMEOUT_SECONDS = 5.0
HOST_COMMAND_REAP_TIMEOUT_SECONDS = 1.0
_COMMAND_DEADLINE: ContextVar[float | None] = ContextVar(
    "host_command_deadline", default=None
)


@contextmanager
def command_budget(timeout: float = HOST_COMMAND_TIMEOUT_SECONDS) -> Iterator[None]:
    """Clamp nested host commands to one context-local wall-clock budget."""
    if timeout <= 0:
        raise ValueError("command budget must be positive")
    deadline = time.monotonic() + timeout
    inherited = _COMMAND_DEADLINE.get()
    token = _COMMAND_DEADLINE.set(
        deadline if inherited is None else min(deadline, inherited)
    )
    try:
        yield
    finally:
        _COMMAND_DEADLINE.reset(token)


def bounded_printable_line(value: object, *, max_chars: int) -> str | None:
    """Return trimmed printable single-line text within a Unicode-character budget."""
    if not isinstance(value, str) or max_chars <= 0:
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > max_chars or not normalized.isprintable():
        return None
    return normalized


def _stop(process: subprocess.Popen[bytes]) -> None:
    """Stop a private probe group without making failure cleanup unbounded."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=HOST_COMMAND_REAP_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        pass


def _capture(
    process: subprocess.Popen[bytes], deadline: float, max_output_bytes: int
) -> tuple[bytes, bytes] | None:
    stdout = process.stdout
    stderr = process.stderr
    if stdout is None or stderr is None:
        return None
    streams = {stdout: bytearray(), stderr: bytearray()}
    total = 0
    selector = selectors.DefaultSelector()
    try:
        for stream in streams:
            selector.register(stream, selectors.EVENT_READ)
        while selector.get_map():
            remaining_time = deadline - time.monotonic()
            events = selector.select(max(0, remaining_time))
            if remaining_time <= 0 or not events:
                return None
            for key, _mask in events:
                stream = key.fileobj
                chunk = os.read(stream.fileno(), min(64 * 1024, max_output_bytes + 1 - total))
                if not chunk:
                    selector.unregister(stream)
                    continue
                streams[stream].extend(chunk)
                total += len(chunk)
                if total > max_output_bytes:
                    return None
        return bytes(streams[stdout]), bytes(streams[stderr])
    finally:
        selector.close()


def _piped_streams(
    process: subprocess.Popen[bytes],
) -> tuple[BinaryIO, BinaryIO] | None:
    """Return both requested pipes or stop and close a malformed child."""
    stdout = process.stdout
    stderr = process.stderr
    if stdout is not None and stderr is not None:
        return stdout, stderr
    _stop(process)
    for stream in (stdout, stderr):
        if stream is not None:
            stream.close()
    return None


def _start_piped(
    args: Sequence[str], cwd: Path | None
) -> tuple[subprocess.Popen[bytes], BinaryIO, BinaryIO] | None:
    """Start one isolated child and require both capture pipes."""
    try:
        process = subprocess.Popen(
            args,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError:
        return None
    streams = _piped_streams(process)
    return None if streams is None else (process, *streams)


def _command_deadline(timeout: float) -> float | None:
    started = time.monotonic()
    deadline = started + timeout
    shared_deadline = _COMMAND_DEADLINE.get()
    if shared_deadline is not None:
        deadline = min(deadline, shared_deadline)
    return deadline if deadline > started else None


def run_bounded(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = HOST_COMMAND_TIMEOUT_SECONDS,
    max_output_bytes: int = MAX_HOST_COMMAND_BYTES,
) -> subprocess.CompletedProcess[str] | None:
    """Run one command with bounded combined output and wall-clock duration."""
    if timeout <= 0 or max_output_bytes <= 0:
        raise ValueError("command bounds must be positive")
    deadline = _command_deadline(timeout)
    if deadline is None:
        return None
    started = _start_piped(args, cwd)
    if started is None:
        return None
    process, stdout_pipe, stderr_pipe = started
    try:
        try:
            captured = _capture(process, deadline, max_output_bytes)
        except OSError:
            _stop(process)
            return None
        if captured is None:
            _stop(process)
            return None
        try:
            stdout_text, stderr_text = (value.decode("utf-8") for value in captured)
        except UnicodeDecodeError:
            _stop(process)
            return None
        remaining_time = deadline - time.monotonic()
        if remaining_time <= 0:
            _stop(process)
            return None
        try:
            returncode = process.wait(timeout=remaining_time)
        except subprocess.TimeoutExpired:
            _stop(process)
            return None
        return subprocess.CompletedProcess(tuple(args), returncode, stdout_text, stderr_text)
    finally:
        stdout_pipe.close()
        stderr_pipe.close()
        if process.poll() is None:
            _stop(process)
