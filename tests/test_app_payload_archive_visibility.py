"""Post-upload visibility must never waive immutable byte verification."""
from types import SimpleNamespace

import pytest

import app_payload_revisions_github as backend
from app_payload_revisions_state import RevisionError


@pytest.fixture
def upload(tmp_path, monkeypatch):
    asset = tmp_path / 'core-2026-06-10-0123456789ab.json.gz'
    asset.write_bytes(b'exact retained payload')
    store = backend.GitHubRevisionStore('yanniedog/AR-local', gh='gh')
    monkeypatch.setattr(backend, 'publication_key', lambda: b'fixture key gate')
    monkeypatch.setattr(store, 'ensure_release', lambda _: None)
    calls, sleeps, reads = [], [], []
    monkeypatch.setattr(store, '_run', lambda args: calls.append(args) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(backend.time, 'sleep', sleeps.append)

    def observed(values):
        iterator = iter(values)

        def read(*args, **kwargs):
            reads.append((args, kwargs))
            result = next(iterator)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(store, 'read', read)

    return store, asset, calls, sleeps, reads, observed


def test_public_404_after_upload_waits_for_exact_bytes_without_reupload(upload):
    store, asset, calls, sleeps, reads, observed = upload
    observed([None, None, None, asset.read_bytes()])
    store.archive('revision-test', [asset])
    assert len(calls) == 1 and '--clobber' not in calls[0]
    assert sleeps == [1, 2]
    assert all(kwargs == {'require_encrypted': True} for _, kwargs in reads)


def test_permanent_404_has_finite_attempts_and_preserves_failure(upload):
    store, asset, calls, sleeps, reads, observed = upload
    observed([None] * 5)
    with pytest.raises(RevisionError, match='public archive verification failed'):
        store.archive('revision-test', [asset])
    assert len(calls) == 1 and len(reads) == 5
    assert sleeps == [1, 2, 4]


@pytest.mark.parametrize('bad', [b'different bytes', b''])
def test_present_mismatched_bytes_never_retry_or_reupload(upload, bad):
    store, asset, calls, sleeps, reads, observed = upload
    observed([None, bad])
    with pytest.raises(RevisionError, match='verification failed'):
        store.archive('revision-test', [asset])
    assert len(calls) == 1 and len(reads) == 2 and sleeps == []


def test_uncertain_upload_accepts_delayed_exact_public_bytes(upload, monkeypatch):
    store, asset, calls, sleeps, reads, observed = upload

    def timed_out(args):
        calls.append(args)
        raise RevisionError('upload outcome uncertain')

    monkeypatch.setattr(store, '_run', timed_out)
    observed([None, None, asset.read_bytes()])
    store.archive('revision-test', [asset])
    assert len(calls) == 1 and sleeps == [1]


def test_uncertain_upload_still_raises_original_failure_when_missing(upload, monkeypatch):
    store, asset, calls, sleeps, reads, observed = upload

    def timed_out(args):
        calls.append(args)
        raise RevisionError('upload outcome uncertain')

    monkeypatch.setattr(store, '_run', timed_out)
    observed([None] * 5)
    with pytest.raises(RevisionError, match='upload outcome uncertain'):
        store.archive('revision-test', [asset])
    assert len(calls) == 1 and sleeps == [1, 2, 4]


def test_http_error_during_verification_is_not_treated_as_missing(upload):
    store, asset, calls, sleeps, reads, observed = upload
    observed([None, RevisionError('public download failed with HTTP 403')])
    with pytest.raises(RevisionError, match='HTTP 403'):
        store.archive('revision-test', [asset])
    assert len(calls) == 1 and len(reads) == 2 and sleeps == []


def test_preexisting_immutable_collision_never_uploads(upload):
    store, asset, calls, sleeps, reads, observed = upload
    observed([b'preexisting different bytes'])
    with pytest.raises(RevisionError, match='immutable release collision'):
        store.archive('revision-test', [asset])
    assert calls == [] and sleeps == [] and len(reads) == 1
