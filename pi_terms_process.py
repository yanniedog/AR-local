"""Bound transport logs without imposing a file-size limit on private CLI state."""
from __future__ import annotations

import asyncio
import os
import signal
import subprocess


class LogLimitError(ValueError):
    """One transport stream exceeded its byte allowance."""


class UnsupportedPlatformError(ValueError):
    """The Pi transport requires POSIX process-group containment."""


async def _copy(stream, target, limit):
    written = 0
    while chunk := await stream.read(65536):
        keep = chunk[:max(0, limit - written)]
        target.write(keep)
        written += len(keep)
        if len(keep) != len(chunk):
            raise LogLimitError('transport_log_limit')


async def _feed(stream, payload):
    try:
        stream.write(payload)
        await stream.drain()
    except (BrokenPipeError, ConnectionResetError):
        pass  # A child that rejects its input supplies the exit status.
    finally:
        stream.close()
    try:
        await stream.wait_closed()
    except (BrokenPipeError, ConnectionResetError):
        pass


async def _stop(process):
    if os.name == 'posix':
        # Failures stop the entire private group, even if its leader exited.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    async def drain(stream):
        while await stream.read(65536):
            pass
    # Drain bounded reader buffers after killing writers. Process.wait alone
    # can deadlock when asyncio has paused a full pipe after a log overflow.
    await asyncio.wait_for(asyncio.gather(
        drain(process.stdout), drain(process.stderr), process.wait()), 5)


async def _run(argv, payload, stdout, stderr, env, cwd, timeout, limit):
    if os.name != 'posix':
        raise UnsupportedPlatformError('Pi transport requires POSIX process groups')
    process = await asyncio.create_subprocess_exec(
        *argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, cwd=cwd, limit=65536, start_new_session=True)
    tasks = [asyncio.create_task(coro) for coro in (
        _feed(process.stdin, payload), _copy(process.stdout, stdout, limit),
        _copy(process.stderr, stderr, limit), process.wait())]
    try:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout)
        return subprocess.CompletedProcess(argv, process.returncode)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await _stop(process)
        raise
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def run_bounded(argv, *, input, stdout, stderr, env, cwd, timeout, limit):
    if limit <= 0 or timeout <= 0:
        raise ValueError('positive transport bounds required')
    try:
        return asyncio.run(_run(argv, input, stdout, stderr, env, cwd, timeout, limit))
    except asyncio.TimeoutError:
        raise subprocess.TimeoutExpired(argv, timeout) from None
