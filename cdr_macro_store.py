"""Read the live macro WAL safely; this database is not an immutable export."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3


@contextmanager
def read_store(path: Path):
    connection = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=5.0)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        yield connection
    finally:
        connection.close()
