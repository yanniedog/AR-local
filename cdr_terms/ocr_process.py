"""Native OCR subprocess boundary, used only inside an admitted outer worker."""
from __future__ import annotations

import subprocess
import time


def bounded_command(command, *, output, errors, deadline, guard, watched):
    """No shell, inherited console, pipes, unbounded logs or renewal of deadline.

    The owning terms worker's existing resource supervisor remains responsible
    for aggregate memory/descendants. This helper owns only its direct process.
    """
    reason = guard()
    if reason:
        raise ValueError('ocr_operational_deferral:' + str(reason))
    kwargs = {'stdin': subprocess.DEVNULL, 'stdout': output, 'stderr': errors,
              'shell': False, 'close_fds': True}
    if hasattr(subprocess, 'CREATE_NO_WINDOW'):
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    process = subprocess.Popen(command, **kwargs)
    try:
        while True:
            reason = guard()
            if reason:
                raise ValueError('ocr_operational_deferral:' + str(reason))
            if time.monotonic() >= deadline:
                raise ValueError('ocr_deadline_exceeded')
            if any(path.exists() and path.stat().st_size > maximum for path, maximum in watched):
                raise ValueError('ocr_output_byte_limit')
            status = process.poll()
            if status is not None:
                if status != 0:
                    raise ValueError('ocr_native_command_failed')
                return
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    finally:
        try:
            if process.poll() is None:
                process.kill()  # Direct owned child only; never signal-zero probing.
            process.wait(timeout=1)
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError('ocr_cleanup_unverified') from error
