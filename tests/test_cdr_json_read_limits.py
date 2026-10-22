"""Byte/JSON protocol controls only; no fabricated business records."""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest

from cdr_export_contract import read_json


@pytest.mark.parametrize('budget', [None, lambda **_charges: None])
def test_oversize_refused_before_payload_read_or_utf8_decode(tmp_path, monkeypatch, budget):
    path = tmp_path / 'control.json'
    path.write_bytes(b'\xff' * 8)
    monkeypatch.setattr(os, 'fdopen', lambda *_args, **_kwargs: pytest.fail('Oversize payload was opened for reading'))
    monkeypatch.setattr(Path, 'read_text', lambda *_args, **_kwargs: pytest.fail('Unbounded text read'))
    with pytest.raises(ValueError, match='bounded read limit'):
        read_json(path, budget=budget, max_bytes=7)
    assert path.read_bytes() == b'\xff' * 8


@pytest.mark.parametrize('body', [b'null', b'[]', b' true\n', b'"utf8-\xc3\xa9-\xf0\x9f\x90\x95"'])
@pytest.mark.parametrize('budget', [None, lambda **_charges: None])
def test_exact_byte_limit_keeps_json_semantics(tmp_path, body, budget):
    path = tmp_path / 'control.json'
    path.write_bytes(body)
    assert read_json(path, budget=budget, max_bytes=len(body)) == json.loads(body.decode('utf-8'))
    with pytest.raises(ValueError, match='bounded read limit'):
        read_json(path, budget=budget, max_bytes=len(body)-1)


def test_multibyte_limit_counts_encoded_bytes_not_characters(tmp_path):
    text = '"\u00e9\U0001f415"'
    path = tmp_path / 'control.json'
    body = text.encode('utf-8')
    path.write_bytes(body)
    assert len(body) > len(text)
    with pytest.raises(ValueError, match='bounded read limit'):
        read_json(path, max_bytes=len(text))
    assert read_json(path, max_bytes=len(body)) == '\u00e9\U0001f415'


@pytest.mark.parametrize('limit', [-1, None, True, False, 1.5, '8', []])
@pytest.mark.parametrize('budget', [None, lambda **_charges: None])
def test_invalid_limit_rejected_before_any_file_access(tmp_path, limit, budget):
    with pytest.raises(ValueError, match='nonnegative integer'):
        read_json(tmp_path / 'absent.json', budget=budget, max_bytes=limit)


@pytest.mark.parametrize('body,error', [(b'{', json.JSONDecodeError),
    (b'\xef\xbb\xbf{}', json.JSONDecodeError), (b'\xff', UnicodeDecodeError)])
@pytest.mark.parametrize('budget', [None, lambda **_charges: None])
def test_in_limit_malformed_json_and_invalid_utf8_stay_rejected(tmp_path, body, error, budget):
    path = tmp_path / 'control.json'
    path.write_bytes(body)
    with pytest.raises(error):
        read_json(path, budget=budget, max_bytes=len(body))


def test_zero_limit_reads_no_nonempty_payload_and_keeps_empty_json_error(tmp_path):
    path = tmp_path / 'control.json'
    path.write_bytes(b'0')
    with pytest.raises(ValueError, match='bounded read limit'):
        read_json(path, max_bytes=0)
    path.write_bytes(b'')
    with pytest.raises(json.JSONDecodeError):
        read_json(path, max_bytes=0)


def test_default_32mib_boundary_and_explicit_larger_cap(tmp_path):
    # A real large inert JSON string checks the default without inventing rates.
    cap = 32 * 1024 * 1024
    path = tmp_path / 'control.json'
    path.write_bytes(b'"' + b'x' * (cap-2) + b'"')
    assert len(read_json(path)) == cap-2
    with path.open('ab') as stream:
        stream.write(b' ')
    with pytest.raises(ValueError, match='bounded read limit'):
        read_json(path)
    assert len(read_json(path, max_bytes=cap+1)) == cap-2


def test_no_budget_still_checks_open_descriptor_and_closes_it(tmp_path, monkeypatch):
    path = tmp_path / 'control.json'
    path.write_bytes(b'{}')
    original_open, original_fstat = os.open, os.fstat
    descriptors = []
    def opened(*args, **kwargs):
        descriptor = original_open(*args, **kwargs)
        descriptors.append(descriptor)
        return descriptor
    def nonregular(descriptor):
        value = list(original_fstat(descriptor))
        value[0] = stat.S_IFIFO | 0o600
        return os.stat_result(value)
    monkeypatch.setattr(os, 'open', opened)
    monkeypatch.setattr(os, 'fstat', nonregular)
    with pytest.raises(ValueError, match='regular file'):
        read_json(path)
    assert len(descriptors) == 1
    with pytest.raises(OSError):
        original_fstat(descriptors[0])
    assert path.read_bytes() == b'{}'


def test_no_budget_rejects_linked_control_and_preserves_target(tmp_path):
    target, link = tmp_path / 'target.json', tmp_path / 'link.json'
    target.write_bytes(b'{}')
    try:
        link.symlink_to(target)
    except OSError as error:
        pytest.skip(f'Native link creation unavailable: {error}')
    with pytest.raises(ValueError, match='regular unlinked file'):
        read_json(link)
    assert target.read_bytes() == b'{}'


def test_no_budget_real_fifo_cannot_block_waiting_for_writer(tmp_path):
    if not hasattr(os, 'mkfifo'):
        pytest.skip('FIFO creation is unavailable on Windows')
    path = tmp_path / 'control.json'
    os.mkfifo(path)
    # Isolate a regression to a blocking text open behind a real process timeout.
    program = ('from pathlib import Path; import sys; from cdr_export_contract import read_json\n'
               'try: read_json(Path(sys.argv[1]))\n'
               'except ValueError as error: print(error)\n'
               'else: raise AssertionError("FIFO unexpectedly accepted")\n')
    child = subprocess.run([sys.executable, '-B', '-c', program, str(path)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=10)
    assert child.returncode == 0, child.stderr
    assert 'regular file' in child.stdout
