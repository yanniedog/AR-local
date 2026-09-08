"""Windows reader locks compatible with the installed existence-based writer."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid


@contextmanager
def process_writer_lock(target: Path):
    """Keep the name present only while this process owns its Windows handle.

    CREATE_NEW preserves the installed writer's exclusion protocol. O_TEMPORARY
    asks Windows to delete the file when the handle closes, including abnormal
    process termination. No finally-only unlink or stale-lock reclamation is
    required, and no existing lock is opened or replaced.
    """
    if os.name != "nt":
        raise ValueError("Live receipt locks require Windows; inspect a frozen snapshot")
    path = target / "catalog/.receiver.lock"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_BINARY | os.O_TEMPORARY
    descriptor = os.open(path, flags, 0o600)
    try:
        payload = json.dumps({"pid": os.getpid(), "nonce": uuid.uuid4().hex,
                              "started_at": datetime.now(timezone.utc).isoformat()}).encode()
        if os.write(descriptor, payload) != len(payload):
            raise OSError("Incomplete reader lock record")
        yield
    finally:
        os.close(descriptor)
