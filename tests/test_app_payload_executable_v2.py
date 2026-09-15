"""Explicit opt-in packaging; source/controller protocols are isolated fixtures."""
import copy

import pytest

from cdr_terms.executable_registry import stage_subject
from cdr_terms.executable_v2_migration import migrate_registry
from cdr_terms.executable_v2_publication import build_asset,publish_asset
from tests.executable_protocol_fixture import protocol,NOW
from tests.test_executable_v2_sources import v2_protocol
from tests.test_executable_v2_publication import approve_controller_control


def test_public_api_emits_namespace_only_and_requires_current_publication(v2_protocol,protocol,tmp_path,monkeypatch):
    import app_payload_build as builder
    store,subject,core,details=v2_protocol
    migrate_registry(store,applied_at=NOW)
    stage_subject(store,subject,interpreter='author',staged_at=NOW)
    approve_controller_control(store,subject,monkeypatch)
    args=dict(core_asset_sha256=subject['source']['coreAssetSha256'],details_asset_sha256=subject['source']['detailsAssetSha256'],run_date=subject['source']['runDate'])
    asset=build_asset(store,subject['scope']['productKey'],**args)
    publish_asset(store,asset,expected_previous_publication_id=None,expected_observation_id=subject['source']['observationId'],published_at=NOW)
    data=dict(core=core,details=details,run_date=subject['source']['runDate'],counts={},search_index=None,history_banks=None,bank_history=None)
    monkeypatch.setattr(builder,'_compute_payload',lambda *a,**k:copy.deepcopy(data))
    monkeypatch.setattr(builder.payload_crypto,'resolve_key_from_env',lambda:None)
    default=builder.build_payload(tmp_path,tmp_path/'default')
    assert 'executable_v2' not in default
    current=builder.build_payload(tmp_path,tmp_path/'current',source_observation=protocol[3],executable_v2_root=store.root)
    assert 'executable_v2' in current
    assert not any(key.startswith('executable_v2_') for key in current['files'])
    assert 'url' not in current['executable_v2']['index']
    monkeypatch.setattr(builder.payload_crypto,'resolve_key_from_env',lambda:b'x'*32)
    with pytest.raises(ValueError,match='unencrypted'):
        builder.build_payload(tmp_path,tmp_path/'encrypted',source_observation=protocol[3],executable_v2_root=store.root)
    assert not (tmp_path/'encrypted/manifest.json').exists()
