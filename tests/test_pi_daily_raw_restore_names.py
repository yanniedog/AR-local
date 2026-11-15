"""Technical filesystem/path controls; actual archives are qualified separately."""
import hashlib
import json
import os
import sqlite3
import tarfile

import pytest

import pi_daily_raw_restore as restore
import pi_daily_raw_restore_names as names
from tests.test_pi_daily_raw_restore import make_archive, qualify, rewrite_archive


def test_actual_workspace_probe_records_nested_behavior_and_retains_evidence(tmp_path):
    keep = tmp_path / 'keep'; keep.write_bytes(b'original')
    result = names.workspace_case_capability(tmp_path, lambda: None)
    assert result['case_sensitive'] == all(result[key] for key in ('root', 'child', 'nested_child'))
    assert all(type(result[key]) is bool for key in ('root', 'child', 'nested_child'))
    assert result['artifacts_retained'] is True and len(result['probe_nonce']) == 32
    assert keep.read_bytes() == b'original'
    assert (tmp_path / ('.case-probe-' + result['probe_nonce']) / 'nested').is_dir()


def test_probe_never_deletes_by_path_after_identity_checks(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('pathname deletion cannot guarantee identity preservation')
    monkeypatch.setattr(type(tmp_path), 'unlink', forbidden)
    monkeypatch.setattr(type(tmp_path), 'rmdir', forbidden)
    assert names.workspace_case_capability(tmp_path, lambda: None)['artifacts_retained']


def test_parent_capability_never_assumes_child_inheritance(tmp_path, monkeypatch):
    monkeypatch.setattr(names, '_pair', lambda path, *_: path == tmp_path)
    result = names.workspace_case_capability(tmp_path, lambda: None)
    assert {key: result[key] for key in ('case_sensitive', 'root', 'child', 'nested_child')} == dict(
        case_sensitive=False, root=True, child=False, nested_child=False)
    assert result['artifacts_retained'] is True


def test_replaced_probe_is_preserved_and_never_becomes_insensitive_success(tmp_path, monkeypatch):
    original = names._pair; replaced = []
    def replace(parent, nonce, files, guard):
        result = original(parent, nonce, files, guard)
        if parent == tmp_path:
            path = files[0][0]; path.rename(tmp_path / 'preserved-original')
            path.write_bytes(b'foreign'); replaced.append(path)
        return result
    monkeypatch.setattr(names, '_pair', replace)
    with pytest.raises(ValueError, match='replaced'):
        names.workspace_case_capability(tmp_path, lambda: None)
    assert replaced[0].read_bytes() == b'foreign'
    assert (tmp_path / 'preserved-original').read_bytes() == b'upper-name'


def test_replaced_nested_directory_prevents_file_cleanup_through_new_path(tmp_path, monkeypatch):
    original = names._pair
    def replace(parent, *args):
        result = original(parent, *args)
        if parent.name == 'nested':
            parent.rename(tmp_path / 'preserved-directory'); parent.mkdir()
        return result
    monkeypatch.setattr(names, '_pair', replace)
    with pytest.raises(ValueError, match='directory replaced'):
        names.workspace_case_capability(tmp_path, lambda: None)
    assert list((tmp_path / 'preserved-directory').iterdir())


@pytest.mark.parametrize('case_sensitive', [False, True])
def test_literal_name_registry_rejects_exact_duplicates_and_file_directory_overlap(case_sensitive):
    with sqlite3.connect(':memory:') as index:
        names.create_name_index(index, case_sensitive=case_sensitive)
        names.reserve_name(index, 'data/leaf', case_sensitive=case_sensitive, guard=lambda: None)
        with pytest.raises(ValueError, match='alias'):
            names.reserve_name(index, 'data/leaf/child', case_sensitive=case_sensitive, guard=lambda: None)
        index.execute('INSERT INTO files VALUES(?,?,?)', ('data/leaf', 'data/leaf', '{}'))
        with pytest.raises(sqlite3.IntegrityError):
            index.execute('INSERT INTO files VALUES(?,?,?)', ('data/leaf', 'data/leaf', '{}'))


@pytest.mark.parametrize('second', ['data/Axis Lending/a.json', 'data/Axis Lending/b.json'])
def test_insensitive_registry_rejects_case_aliased_parent_even_for_different_leaves(second):
    with sqlite3.connect(':memory:') as index:
        names.create_name_index(index, case_sensitive=False)
        names.reserve_name(index, 'data/AXIS Lending/a.json', case_sensitive=False, guard=lambda: None)
        with pytest.raises(ValueError, match='alias'):
            names.reserve_name(index, second, case_sensitive=False, guard=lambda: None)


def test_sensitive_registry_preserves_literal_full_paths_and_directory_aliases():
    paths = ['data/AXIS/a.json', 'data/Axis/a.json', 'data/AXIS/b.json', 'data/Axis/c.json',
             'data/ß/x.json', 'data/ss/x.json']
    with sqlite3.connect(':memory:') as index:
        names.create_name_index(index, case_sensitive=True)
        for path in paths:
            names.reserve_name(index, path, case_sensitive=True, guard=lambda: None)
            index.execute('INSERT INTO files VALUES(?,?,?)', (path, path.casefold(), '{}'))
        assert [row[0] for row in index.execute('SELECT logical FROM files ORDER BY logical')] == sorted(paths)


def add_actual_holder_case_names(members):
    # Exact observed holder names, technical bodies: no invented financial data.
    manifest = json.loads(members[0][1]); records = {row['logical_path']: row for row in manifest['files']}
    files = {member.name: (member, body) for member, body in members[1:]}
    for label in ('AXIS Lending', 'Axis Lending', 'FinStreet', 'Finstreet'):
        path = 'data/runs/2026-11-13/banks/_holders/' + label + '/_register-brand.json'
        body = json.dumps({'technical_case_control': label}).encode()
        member = tarfile.TarInfo(path); member.mode = 0o600
        member.pax_headers = {'mtime': '0.000000000'}
        files[path] = member, body
        records[path] = dict(logical_path=path, size=len(body), sha256=hashlib.sha256(body).hexdigest(),
                             mode='0o600', uid=0, gid=0, mtime_ns=0)
    manifest['files'] = [records[key] for key in sorted(records)]
    manifest['file_count'] = len(records); manifest['total_bytes'] = sum(row['size'] for row in records.values())
    members[:] = [(members[0][0], json.dumps(manifest).encode()), *[files[key] for key in sorted(files)]]


def test_case_sensitive_filesystem_restores_all_observed_holder_spellings(tmp_path):
    # Determine platform eligibility independently: an always-False production
    # probe must fail this test, rather than turn its positive path into a skip.
    current = tmp_path / 'independent-name-proof'
    for depth in range(3):
        current.mkdir()
        first, second = current / 'Case', current / 'case'
        first.write_bytes(b'upper')
        try:
            with second.open('xb') as stream: stream.write(b'lower')
        except FileExistsError:
            assert os.path.samefile(first, second)
            pytest.skip('independently verified case-insensitive filesystem')
        assert not os.path.samefile(first, second)
        assert first.read_bytes() == b'upper' and second.read_bytes() == b'lower'
        current = current / 'nested'
    assert names.workspace_case_capability(tmp_path, lambda: None)['case_sensitive']
    inputs = rewrite_archive(make_archive(tmp_path), add_actual_holder_case_names, tmp_path)
    result = qualify(tmp_path, inputs)
    assert result['result'] == 'PASS' and result['workspace_names']['case_sensitive']
    base = tmp_path / 'restored/exact/data/runs/2026-11-13/banks/_holders'
    identities = []
    for label in ('AXIS Lending', 'Axis Lending', 'FinStreet', 'Finstreet'):
        path = base / label / '_register-brand.json'
        assert json.loads(path.read_bytes()) == {'technical_case_control': label}
        identities.append(path.stat().st_ino)
    assert len(set(identities)) == 4


def test_insensitive_restore_rejects_observed_holders_before_materialization(tmp_path, monkeypatch):
    inputs = rewrite_archive(make_archive(tmp_path), add_actual_holder_case_names, tmp_path)
    monkeypatch.setattr(restore, 'workspace_case_capability', lambda *_:
        dict(schema='ar-restore-case-capability-v1', case_sensitive=False, root=False, child=False, nested_child=False))
    with pytest.raises(ValueError, match='alias'): qualify(tmp_path, inputs)
    assert not (tmp_path / 'restored/exact').exists()
    assert json.loads((tmp_path / 'restored/restore-result.json').read_bytes())['result'] == 'FAIL'


@pytest.mark.parametrize('limits', [dict(entries=3), dict(name_bytes=20)])
def test_deep_prefix_amplification_stops_before_over_budget_insert(limits):
    with sqlite3.connect(':memory:') as index:
        names.create_name_index(index, case_sensitive=True, **limits)
        with pytest.raises(ValueError, match='name index budget'):
            names.reserve_name(index, '/'.join(['ab'] * 100), case_sensitive=True, guard=lambda: None)
        count, size, max_count, max_size = index.execute('SELECT * FROM name_budget').fetchone()
        assert count == index.execute('SELECT count(*) FROM path_names').fetchone()[0]
        assert count <= max_count and size <= max_size


def test_shared_prefixes_are_charged_once_and_unicode_uses_utf8_bytes():
    with sqlite3.connect(':memory:') as index:
        names.create_name_index(index, case_sensitive=False, entries=3, name_bytes=26)
        for path in ('é/a', 'é/b', 'é/a'):
            names.reserve_name(index, path, case_sensitive=False, guard=lambda: None)
        assert index.execute('SELECT entries,bytes FROM name_budget').fetchone() == (3, 20)
        with pytest.raises(ValueError, match='name index budget'):
            names.reserve_name(index, 'é/c', case_sensitive=False, guard=lambda: None)


def test_archive_name_budget_failure_precedes_materialization_and_is_receipted(tmp_path):
    from dataclasses import replace
    inputs = make_archive(tmp_path)
    with pytest.raises(ValueError, match='name index budget'):
        qualify(tmp_path, inputs, limits=replace(restore.Limits(), name_entries=1))
    assert not (tmp_path / 'restored/exact').exists()
    result = json.loads((tmp_path / 'restored/restore-result.json').read_bytes())
    assert result['result'] == 'FAIL' and result['budgets']['name_entries'] == 1
