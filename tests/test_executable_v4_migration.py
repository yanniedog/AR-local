"""Isolated technical storage migration; no live source store."""
import pytest
import sqlite3
from cdr_terms.store import EvidenceStore
from cdr_terms.executable_registry import migrate_executable_registry
from cdr_terms.executable_v4_migration import MIGRATION
from tests.executable_v3_fixture import monetary_protocol


def test_additive003_is_idempotent_and_keeps_old_view_columns(tmp_path):
    with EvidenceStore(tmp_path / 'store') as store:
        migrate_executable_registry(store,wire_version=3,applied_at='2026-01-01T00:00:00Z')
        columns=[x[1] for x in store.db.execute('PRAGMA table_info(executable_registry_subjects)')]
        old=list(store.db.execute('SELECT * FROM executable_registry_migrations_v3'))
        migrate_executable_registry(store,wire_version=4,applied_at='2026-01-02T00:00:00Z')
        migrate_executable_registry(store,wire_version=4,applied_at='2026-01-03T00:00:00Z')
        assert columns==[x[1] for x in store.db.execute('PRAGMA table_info(executable_registry_subjects)')]
        assert old==list(store.db.execute('SELECT * FROM executable_registry_migrations_v3'))
        assert store.db.execute('SELECT count(*) FROM executable_registry_migrations_v4 WHERE migration_id=?',(MIGRATION,)).fetchone()[0]==1
        with pytest.raises(sqlite3.IntegrityError,match='append-only'):
            store.db.execute('DELETE FROM executable_registry_migrations_v4')


def test003_refuses_without002(tmp_path):
    with EvidenceStore(tmp_path / 'store') as store:
        with pytest.raises(ValueError,match='predecessor'):
            migrate_executable_registry(store,wire_version=4,applied_at='2026-01-02T00:00:00Z')
        assert not store.db.in_transaction
        assert store.db.execute("SELECT 1 FROM sqlite_master WHERE name='executable_subjects_v4'").fetchone() is None


@pytest.mark.parametrize('earlier_kind', ['wrong_wire', 'missing_collision_guards'])
def test003_never_relabels_an_installed_earlier_draft(tmp_path, monkeypatch, earlier_kind):
    import hashlib
    import cdr_terms.executable_v4_migration as migration
    original_root, original_sha = migration.ROOT, migration.DDL_SHA
    current = (original_root / 'storage/003_savings_activity_v4.sql').read_bytes()
    earlier = current.replace(b"json_extract(payload_json,'$.schemaVersion') IS 4",
                              b"json_extract(payload_json,'$.schemaVersion') IS 3")
    if earlier_kind == 'missing_collision_guards':
        earlier = current.split(b'-- v3/v4 review and publication collision guards.')[0]
        assert hashlib.sha256(earlier).hexdigest() == '070efdabe942b0b3f6d0abffd4507ed0fda47972e554d0be3315c22b6a6956b1'
    earlier_root = tmp_path / 'earlier-draft'
    (earlier_root / 'storage').mkdir(parents=True)
    (earlier_root / 'storage/003_savings_activity_v4.sql').write_bytes(earlier)
    earlier_sha = hashlib.sha256(earlier).hexdigest()
    with EvidenceStore(tmp_path / 'store') as store:
        migrate_executable_registry(store, wire_version=3, applied_at='2026-01-01T00:00:00Z')
        monkeypatch.setattr(migration, 'ROOT', earlier_root)
        monkeypatch.setattr(migration, 'DDL_SHA', earlier_sha)
        migration.migrate_activity_registry(store, applied_at='2026-01-02T00:00:00Z')
        before = list(store.db.execute('SELECT * FROM executable_registry_migrations_v4'))
        monkeypatch.setattr(migration, 'ROOT', original_root)
        monkeypatch.setattr(migration, 'DDL_SHA', original_sha)
        with pytest.raises(ValueError, match='marker differs'):
            migration.migrate_activity_registry(store, applied_at='2026-01-03T00:00:00Z')
        assert not store.db.in_transaction
        assert list(store.db.execute('SELECT * FROM executable_registry_migrations_v4')) == before


def test003_preserves_populated_v3_subject_review_dependencies(monetary_protocol):
    from cdr_terms.executable_registry import stage_subject,review_subject,lookup_subject
    from cdr_terms.executable_v3_migration import _snapshot
    from cdr_terms.identity import canonical_json
    store,subject,_=monetary_protocol
    now='2026-01-12T01:00:00Z'
    migrate_executable_registry(store,wire_version=3,applied_at=now)
    identity=stage_subject(store,subject,interpreter='technical-writer',staged_at=now)
    reason='Technical negative disposition retained through migration'
    evidence=store.put_blob(canonical_json(dict(schemaVersion=3,subjectId=identity,decision='rejected',previousReviewId=None,reason=reason)).encode())
    review_subject(store,identity,decision='rejected',reviewer='independent-technical',reviewer_kind='human',reviewed_at=now,evidence_sha256=evidence,reason=reason,expected_previous_review_id=None)
    before=_snapshot(store.db)
    views={name:[tuple(x) for x in store.db.execute('SELECT * FROM '+name)] for name in ('executable_registry_subjects','executable_registry_reviews')}
    assert store.db.execute('SELECT count(*) FROM executable_subject_terms_v3').fetchone()[0]>0
    migrate_executable_registry(store,wire_version=4,applied_at=now)
    after=_snapshot(store.db,before)
    assert before['rows']==after['rows'] and before['columns']==after['columns']
    assert lookup_subject(store,identity)==subject
    for name,expected in views.items():assert [tuple(x) for x in store.db.execute('SELECT * FROM '+name)]==expected
