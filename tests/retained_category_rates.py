"""Bounded, hash-bound real rate fixtures; never manufacture acceptance data."""
from contextlib import contextmanager
import gzip
import hashlib
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'docs/evidence/backup-observation-20260911/publication/v1-core.json.gz'
PROJECTION = Path(__file__).parent / 'fixtures/category-rates-20260911.ndjson.gz'
SOURCE_SHA256 = '5f76873341f48d9296b6bad652f677fdbd530900cecb5f2d5946fe7a55e439f4'
PROJECTION_SHA256 = '534c5373259d5700a8361ba4679b9bfd59e4bc59f03a41d14b05e36b588e3637'
RUN_DATE = '2026-09-11'
SECTIONS = (('Mortgage', 8028), ('Savings', 2096), ('TD', 6354))
MAX_COMPRESSED = 1024 * 1024
MAX_RECORD = 65536


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def verified_bytes(path, expected):
    """Parse only the immutable compressed bytes whose digest was checked."""
    require(not path.is_symlink() and path.is_file(), 'fixture must be a regular file')
    with path.open('rb') as stream:
        body = stream.read(MAX_COMPRESSED + 1)
    require(len(body) <= MAX_COMPRESSED, 'compressed fixture exceeds bound')
    require(hashlib.sha256(body).hexdigest() == expected, 'fixture hash mismatch')
    return body


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON key')
        result[key] = value
    return result


def record(stream):
    line = stream.readline(MAX_RECORD + 1)
    require(len(line) <= MAX_RECORD and line.endswith(b'\n'), 'truncated or oversized fixture record')
    return json.loads(line, object_pairs_hook=unique_object)


def expected_header():
    return {'schema': 'retained-category-rates-v1', 'source_sha256': SOURCE_SHA256,
            'run_date': RUN_DATE, 'sections': [list(row) for row in SECTIONS]}


def section_records(stream, complete):
    require(record(stream) == expected_header(), 'fixture header differs')
    for name, count in SECTIONS:
        rates = []
        for ordinal in range(count):
            value = record(stream)
            require(isinstance(value, list) and len(value) == 3
                    and value[0] == name and type(value[1]) is int and value[1] == ordinal
                    and isinstance(value[2], dict), 'fixture row order/count/shape differs')
            rates.append(value[2])
        yield name, {'rates': rates}
        del rates  # Do not retain the previous section while loading its successor.
    require(stream.read(1) == b'', 'unexpected trailing fixture record')
    complete['done'] = True


@contextmanager
def rate_sections():
    """All sections must be consumed; partial reads cannot certify the fixture."""
    verified_bytes(SOURCE, SOURCE_SHA256)
    compressed = verified_bytes(PROJECTION, PROJECTION_SHA256)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode='rb') as stream:
        complete = {'done': False}
        rows = section_records(stream, complete)
        try:
            yield rows
            require(complete['done'], 'fixture stream not completely consumed')
        finally:
            rows.close()


def core_metadata():
    return {'run_date': RUN_DATE, 'sections': dict.fromkeys(name for name, _ in SECTIONS)}
