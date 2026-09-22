"""Bounded, immutable local report I/O; no network or publication authority."""
import csv
import gzip
import io
import json
import re
from pathlib import Path

from cdr_report_terms import encoded, sha

MAX_FILE = 24 * 1024**2
MAX_OUTPUT = 256 * 1024**2
MAX_FILES = 5000
MAX_INPUT = 128 * 1024**2
MAX_PLAIN = 256 * 1024**2


def read_file(path, limit):
    path = Path(path)
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ValueError('Unsafe report input path')
    if path.stat().st_size > limit:
        raise ValueError('Report input byte budget exceeded')
    with path.open('rb') as stream:
        body = stream.read(limit + 1)
    if len(body) > limit:
        raise ValueError('Report input byte budget exceeded')
    return body


def read_bundle(root):
    raw = read_file(root / 'manifest.json', 1024**2)
    manifest = json.loads(raw)
    files = manifest['files']
    if not isinstance(files, dict) or not 2 <= len(files) <= 128:
        raise ValueError('Report asset inventory invalid')
    payloads, names = {}, set()
    compressed = plain_total = 0
    evidence = {'manifest_sha256': sha(raw), 'assets': {}}
    for kind, descriptor in files.items():
        name = descriptor['name']
        if (not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', name) or Path(name).name != name
                or '/' in name or '\\' in name or name in names):
            raise ValueError('Unsafe or duplicate report asset name')
        names.add(name)
        data = read_file(root / name, min(16 * 1024**2, MAX_INPUT - compressed))
        compressed += len(data)
        if len(data) != descriptor['bytes'] or sha(data) != descriptor['sha256']:
            raise ValueError('Report asset identity differs')
        limit = min(96 * 1024**2, MAX_PLAIN - plain_total)
        if name.endswith('.gz'):
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                plain = stream.read(limit + 1)
        else:
            plain = data
        if len(plain) > limit:
            raise ValueError('Report expanded input budget exceeded')
        plain_total += len(plain)
        payload = json.loads(plain)
        if not isinstance(payload, dict):
            raise ValueError('Report asset object required')
        if (kind in ('core', 'details') or 'run_date' in payload) and payload.get('run_date') != manifest['run_date']:
            raise ValueError('Report mixed edition dates')
        payloads[kind] = payload
        evidence['assets'][kind] = {'name': name, 'bytes': len(data), 'sha256': sha(data)}
    if not {'core', 'details'} <= payloads.keys():
        raise ValueError('Report core and details required')
    evidence['input_bytes'] = compressed
    evidence['expanded_input_bytes'] = plain_total
    return manifest, payloads, evidence


def csv_bytes(rows, fields, *, json_fields=()):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        values = {}
        for key in fields:
            value = row.get(key)
            if isinstance(value, (dict, list)):
                value = encoded(value).decode()
            if key in json_fields:
                # Valid JSON cannot contain an executable spreadsheet formula;
                # negative JSON numbers must remain directly parseable.
                json.loads(value)
            elif isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')):
                value = "'" + value
            values[key] = value
        writer.writerow(values)
        if stream.tell() > MAX_FILE:
            raise ValueError('Report CSV budget exceeded')
    return ('\ufeff' + stream.getvalue()).encode('utf-8')


class Writer:
    def __init__(self, root):
        self.root, self.files, self.total, self.expanded = root, [], 0, 0

    def write(self, name, body, *, compress=False, rows=None):
        if len(body) > MAX_FILE:
            raise ValueError('Report per-file expanded budget exceeded')
        raw = gzip.compress(body, mtime=0) if compress else body
        if (len(self.files) >= MAX_FILES or self.total + len(raw) > MAX_OUTPUT
                or self.expanded + len(body) > 4 * MAX_OUTPUT):
            raise ValueError('Report aggregate output budget exceeded')
        target = self.root / name
        if target.resolve().parent != (self.root / Path(name).parent).resolve() or self.root not in target.resolve().parents:
            raise ValueError('Unsafe report output name')
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            stream.write(raw)
        item = {'file': name, 'bytes': len(raw), 'sha256': sha(raw),
                'expanded_bytes': len(body), 'expanded_sha256': sha(body)}
        if rows is not None:
            item['rows'] = rows
        self.files.append(item)
        self.total += len(raw)
        self.expanded += len(body)
        return item
