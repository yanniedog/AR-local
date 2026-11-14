"""Prove actual restore name semantics; never change filesystem policy."""
import os
from pathlib import Path
import stat
import uuid


def _identity(path, *, directory=False):
    value = path.lstat()
    expected = stat.S_ISDIR if directory else stat.S_ISREG
    if (not expected(value.st_mode) or not value.st_ino
            or getattr(value, 'st_file_attributes', 0) & 0x400
            or (not directory and value.st_nlink != 1)):
        raise ValueError('unsafe restore case probe identity')
    return value.st_dev, value.st_ino


def _read(path, expected, body):
    if _identity(path) != expected:
        raise ValueError('restore case probe was replaced')
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    with os.fdopen(os.open(path, flags), 'rb') as stream:
        value = os.fstat(stream.fileno())
        if (value.st_dev, value.st_ino) != expected or stream.read(len(body) + 1) != body:
            raise ValueError('restore case probe identity/content differs')
    if _identity(path) != expected:
        raise ValueError('restore case probe changed while reading')


def _pair(parent, nonce, files, guard):
    first = None
    for name, body in [(f'.ArCase-{nonce}', b'upper-name'), (f'.arcase-{nonce}', b'lower-name')]:
        guard(); path = parent / name
        try:
            with path.open('xb') as stream:
                value = os.fstat(stream.fileno())
                identity = value.st_dev, value.st_ino
                files.append((path, identity, body))
                stream.write(body)
        except FileExistsError:
            if first is None or _identity(path) != first[1]:
                raise ValueError('ambiguous restore case probe collision')
            _read(path, first[1], first[2])
            return False
        _read(path, identity, body)
        if first is not None and identity == first[1]:
            raise ValueError('restore case probe names alias one file')
        first = path, identity, body
    # Keep literal paths in a list: WindowsPath equality itself folds case.
    for path, identity, body in files[-2:]: _read(path, identity, body)
    return True


def workspace_case_capability(work, guard):
    """Probe the protected new root; retain bounded evidence without deletion."""
    work = Path(work); original = _identity(work, directory=True)
    nonce = uuid.uuid4().hex
    files, directories, levels = [], [], []
    current = work
    try:
        for depth in range(3):
            guard()
            if depth:
                current = current / ('.case-probe-' + nonce if depth == 1 else 'nested')
                current.mkdir(mode=0o700)
                directories.append((current, _identity(current, directory=True)))
            levels.append(_pair(current, nonce, files, guard))
        if _identity(work, directory=True) != original:
            raise ValueError('restore case probe workspace changed')
        return dict(schema='ar-restore-case-capability-v1', case_sensitive=all(levels),
                    root=levels[0], child=levels[1], nested_child=levels[2],
                    probe_nonce=nonce, artifacts_retained=True)
    finally:
        # A pathname check followed by unlink/rmdir is not identity-atomic.
        # Keep at most six tiny files and two directories as private evidence.
        # Replacements fail qualification and are never deleted by this probe.
        for path, identity in [(work, original), *directories]:
            if _identity(path, directory=True) != identity:
                raise ValueError('restore case probe directory replaced before verification')
        for path, identity, body in files:
            _read(path, identity, body)


def create_name_index(index, *, case_sensitive):
    folded_constraint = '' if case_sensitive else ' UNIQUE'
    index.execute(f'CREATE TABLE files(logical TEXT PRIMARY KEY, folded TEXT{folded_constraint}, value TEXT)')
    index.execute('CREATE TABLE path_names(identity TEXT PRIMARY KEY, logical TEXT NOT NULL, kind TEXT NOT NULL)')


def reserve_name(index, logical, *, case_sensitive, guard):
    """Do not merge directory aliases even when their leaf filenames differ."""
    parts = logical.split('/')
    for position in range(1, len(parts) + 1):
        guard(); name = '/'.join(parts[:position])
        key = name if case_sensitive else name.casefold()
        kind = 'file' if position == len(parts) else 'directory'
        prior = index.execute('SELECT logical,kind FROM path_names WHERE identity=?', (key,)).fetchone()
        if prior is None:
            index.execute('INSERT INTO path_names VALUES(?,?,?)', (key, name, kind))
        elif prior != (name, kind):
            raise ValueError('archive directory/file alias requires distinct safe paths')
