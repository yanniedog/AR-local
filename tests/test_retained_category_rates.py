"""Small structural corruption controls; never decode the full original core."""
import gzip
import hashlib
import json

import pytest

from tests import retained_category_rates as fixture


@pytest.fixture
def control(monkeypatch, tmp_path):
    source, projection = tmp_path / 'source.gz', tmp_path / 'projection.gz'
    source.write_bytes(b'isolated structural control, not business data')
    monkeypatch.setattr(fixture, 'SOURCE', source)
    monkeypatch.setattr(fixture, 'PROJECTION', projection)
    monkeypatch.setattr(fixture, 'SOURCE_SHA256', hashlib.sha256(source.read_bytes()).hexdigest())
    monkeypatch.setattr(fixture, 'SECTIONS', (('Mortgage', 2), ('Savings', 1)))
    records = [['Mortgage', 0, {'rate': '1', 'extra': {'preserved': [True, None]}}],
               ['Mortgage', 1, {'rate': '1', 'extra': {'preserved': [True, None]}}],
               ['Savings', 0, {'rate': '2'}]]

    def install(rows=None, *, decoded=None):
        if decoded is None:
            decoded = b''.join(json.dumps(value).encode() + b'\n'
                               for value in [fixture.expected_header(), *(records if rows is None else rows)])
        body = gzip.compress(decoded, mtime=0)
        projection.write_bytes(body)
        monkeypatch.setattr(fixture, 'PROJECTION_SHA256', hashlib.sha256(body).hexdigest())
        return decoded

    install()
    return records, install


def consume():
    with fixture.rate_sections() as sections:
        return list(sections)


def test_all_fields_and_legitimate_equal_rows_preserved(control):
    rows = consume()
    assert rows == [('Mortgage', {'rates': [value[2] for value in control[0][:2]]}),
                    ('Savings', {'rates': [control[0][2][2]]})]


@pytest.mark.parametrize('kind', ['duplicate', 'reorder', 'missing', 'extra', 'wrong_section', 'boolean_ordinal', 'not_object'])
def test_record_inventory_corruption_refused(control, kind):
    rows, install = control
    if kind == 'duplicate': rows[1] = rows[0]
    elif kind == 'reorder': rows[:2] = rows[1::-1]
    elif kind == 'missing': rows.pop()
    elif kind == 'extra': rows.append(rows[-1])
    elif kind == 'wrong_section': rows[0][0] = 'Unknown'
    elif kind == 'boolean_ordinal': rows[0][1] = False
    else: rows[0][2] = []
    install(rows)
    with pytest.raises(ValueError): consume()


@pytest.mark.parametrize('kind', ['unterminated', 'oversized', 'header', 'duplicate_key', 'malformed', 'trailing'])
def test_bounded_json_and_complete_stream(control, kind):
    _, install = control
    decoded = install()
    if kind == 'unterminated': decoded = decoded.rstrip(b'\n')
    elif kind == 'oversized': decoded = b' ' * (fixture.MAX_RECORD + 1) + decoded
    elif kind == 'header': decoded = decoded.replace(b'retained-category-rates-v1', b'unknown-schema')
    elif kind == 'duplicate_key': decoded = decoded.replace(b'"rate": "1"', b'"rate": "1", "rate": "1"', 1)
    elif kind == 'malformed': decoded = decoded.replace(b'"rate": "1"', b'"rate": broken', 1)
    else: decoded += b'\n'
    install(decoded=decoded)
    with pytest.raises(ValueError): consume()


def test_partial_consumer_is_not_success(control):
    with pytest.raises(ValueError, match='not completely consumed'):
        with fixture.rate_sections() as sections:
            next(sections)


@pytest.mark.parametrize('target', ['SOURCE', 'PROJECTION'])
def test_independent_hash_pins_refuse_mutation(control, target):
    getattr(fixture, target).write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash mismatch'): consume()


def test_compressed_limit_and_truncated_gzip(control, monkeypatch):
    monkeypatch.setattr(fixture, 'MAX_COMPRESSED', 1)
    with pytest.raises(ValueError, match='exceeds bound'): consume()
    monkeypatch.setattr(fixture, 'MAX_COMPRESSED', 1024 * 1024)
    body = fixture.PROJECTION.read_bytes()[:-8]
    fixture.PROJECTION.write_bytes(body)
    monkeypatch.setattr(fixture, 'PROJECTION_SHA256', hashlib.sha256(body).hexdigest())
    with pytest.raises(EOFError): consume()


def test_caller_failure_is_not_hidden_by_completion_check(control):
    with pytest.raises(RuntimeError, match='caller failure'):
        with fixture.rate_sections() as sections:
            next(sections)
            raise RuntimeError('caller failure')
    assert len(consume()) == 2
