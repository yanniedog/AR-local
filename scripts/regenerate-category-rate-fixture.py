"""Offline real-data projection/equivalence proof; never run by the Pi canary.

Run without arguments to check checked-in bytes; --write recreates only the two
named test fixture artifacts from the independently pinned original gzip.
"""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.retained_category_rates import (PROJECTION, PROJECTION_SHA256, RUN_DATE, SECTIONS,
                                     SOURCE, SOURCE_SHA256, expected_header)


def generate():
    original = SOURCE.read_bytes()
    assert hashlib.sha256(original).hexdigest() == SOURCE_SHA256
    core = json.loads(gzip.decompress(original))
    assert core['run_date'] == RUN_DATE
    assert [(name, len(value['rates'])) for name, value in core['sections'].items()] == list(SECTIONS)
    encode = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode() + b'\n'
    decoded = encode(expected_header()) + b''.join(
        encode([section, ordinal, row]) for section, value in core['sections'].items()
        for ordinal, row in enumerate(value['rates']))
    rebuilt = {section: [] for section in core['sections']}
    for line in decoded.splitlines()[1:]:
        section, ordinal, row = json.loads(line)
        assert ordinal == len(rebuilt[section])
        rebuilt[section].append(row)
    assert all(rebuilt[name] == value['rates'] for name, value in core['sections'].items())
    output = io.BytesIO()
    # Empty filename, zero timestamp and GzipFile's fixed OS byte avoid platform
    # headers and wall-clock bytes in this deterministic fixture.
    with gzip.GzipFile(filename='', fileobj=output, mode='wb', mtime=0, compresslevel=9) as stream:
        stream.write(decoded)
    body = output.getvalue()
    provenance = {'schema': 'retained-category-rates-provenance-v1',
        'source': SOURCE.relative_to(ROOT).as_posix(), 'source_sha256': SOURCE_SHA256,
        'projection': PROJECTION.relative_to(ROOT).as_posix(),
        'projection_sha256': hashlib.sha256(body).hexdigest(),
        'decoded_sha256': hashlib.sha256(decoded).hexdigest(),
        'run_date': RUN_DATE, 'sections': [list(row) for row in SECTIONS],
        'equivalence': 'Every original rate row, field, value and order preserved; only unused top-level/section collections omitted.',
        'regenerate': 'python -B scripts/regenerate-category-rate-fixture.py --write'}
    return body, (json.dumps(provenance, indent=2, ensure_ascii=False) + '\n').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    body, provenance = generate()
    assert hashlib.sha256(body).hexdigest() == PROJECTION_SHA256, 'projection differs from independent pin'
    paths = [(PROJECTION, body), (PROJECTION.with_suffix('.provenance.json'), provenance)]
    for path, expected in paths:
        if args.write:
            path.write_bytes(expected)
        else:
            assert path.read_bytes() == expected, str(path) + ' differs from regenerated fixture'
    print('PASS: exact original-to-projection equivalence and deterministic fixture bytes')


if __name__ == '__main__':
    main()
