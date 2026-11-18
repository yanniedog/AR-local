"""Real captured product/rate/fact/body bytes, offline protocol fault controls."""
from copy import deepcopy
from pathlib import Path
import json
import shutil
from types import SimpleNamespace

import pytest

from app_payload_common import DEFAULT_REPO, DEFAULT_TAG
from app_payload_product_evidence_contract import canonical, digest
from app_payload_product_evidence_reference import LANES, SOURCE_FIELDS
from app_payload_product_evidence_transport import pack_snapshot
from app_payload_product_response_transport import pack_responses
from app_payload_publication_assets import complete_assets, verify_stage, asset_url
from app_payload_revisions import publish_revision_bundle
from app_payload_revisions_state import RevisionError, validate_manifest, bundle_sha256
from tests.test_app_payload_revisions import build_payload, MemoryStore, CONSUMER
from tests.test_app_payload_product_response_sources import real_source, reader
from tests.test_app_payload_product_evidence_reference import install
from tests.test_app_payload_product_evidence_publication_inventory import ready


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import socket
    monkeypatch.setattr(socket, 'create_connection', lambda *a, **k: pytest.fail('offline protocol test attempted network'))


class Store(MemoryStore):
    repo = DEFAULT_REPO

    def __init__(self):
        super().__init__(); self.reads = []; self.uploads = []

    def url(self, tag, name): return f'https://github.com/{self.repo}/releases/download/{tag}/{name}'

    def read(self, tag, name, limit=8*1024*1024, *, require_encrypted=False):
        self.reads.append((tag, name, require_encrypted))
        return super().read(tag, name, limit)

    def read_url(self, url, limit=64*1024*1024, *, require_encrypted=False):
        prefix = f'https://github.com/{self.repo}/releases/download/'
        assert url.startswith(prefix)
        tag, name = url[len(prefix):].split('/', 1)
        return self.read(tag, name, limit, require_encrypted=require_encrypted)

    def archive(self, tag, paths):
        self.uploads.append((tag, [p.name for p in paths])); super().archive(tag, paths)


@pytest.fixture
def payload(tmp_path):
    values = real_source(tmp_path); snapshot, _, _, binding, _ = values
    root = tmp_path/'payload'; manifest = build_payload(root); manifest['repo'] = DEFAULT_REPO
    for key, entry in manifest['files'].items():
        entry['url'] = f'https://github.com/{DEFAULT_REPO}/releases/download/{DEFAULT_TAG}/{entry["name"]}'
        binding[key+'_sha256'] = entry['sha256']
    manifest['source_observation'] = {k: binding['source'][k] for k in SOURCE_FIELDS}
    facts = pack_snapshot(snapshot, tmp_path/'facts', expected_source=binding['source'],
                          core_sha256=binding['core_sha256'], details_sha256=binding['details_sha256'])
    responses = pack_responses(reader(values), tmp_path/'responses')
    for lane, source, prepared in [('product_evidence_v1', tmp_path/'facts', facts),
                                   ('product_response_evidence_v1', tmp_path/'responses', responses)]:
        cap = prepared['capability']
        for entry in [cap['index'], *cap['shards']]: shutil.copyfile(source/entry['name'], root/entry['name'])
        install(root, manifest, lane, cap)
    manifest = ready(manifest); (root/'manifest.json').write_bytes(canonical(manifest))
    return root, manifest


def publish(root, store, state):
    return publish_revision_bundle(root, state_dir=state, repo=DEFAULT_REPO,
                                   enabled=True, consumer_commit=CONSUMER, store=store)


def test_real_recursive_revision_archive_remote_readback_and_idempotent_retry(payload, tmp_path):
    root, manifest = payload; store = Store(); before = {p.name:p.read_bytes() for p in root.iterdir()}
    expected = {entry['name'] for _,entry in complete_assets(manifest, root=root)}
    assert len(expected) > len(manifest['files'])+2
    first = publish(root, store, tmp_path/'state')
    assert set(store.uploads[-1][1]) == expected|{'manifest.json','revision-delta.json','publication-provenance.json'}
    assert store.uploads[-1][1][-1]=='manifest.json' and first.index_changed
    second = publish(root, store, tmp_path/'state')
    assert not second.index_changed and store.promotions==1
    downloaded = {name for tag,name,encrypted in store.reads if encrypted and tag==first.manifest['tag']}
    assert expected <= downloaded
    assert {p.name:p.read_bytes() for p in root.iterdir()}==before
    validate_manifest(first.manifest, first.archive_dir)  # Explicit reservation/control inventory.


def test_retention_archives_every_asset_without_selecting_anything(payload, tmp_path):
    from app_payload_archive import archive_payload_bundle
    root, manifest = payload; store = Store()
    result = archive_payload_bundle(root,state_dir=tmp_path/'archive',repo=DEFAULT_REPO,store=store,
        contract_coverage={'failure_provenance_complete':False},promotion_reason='partial')
    expected={entry['name'] for _,entry in complete_assets(manifest,root=root)}|{'manifest.json'}
    assert set(store.uploads[-1][1])==expected and store.promotions==0
    assert expected <= {name for tag,name,encrypted in store.reads if encrypted and tag==result.tag}
    assert complete_assets(result.manifest,store=store)==complete_assets(result.manifest,root=result.archive_dir)


@pytest.mark.parametrize('fault',['missing','corrupt','extra','control','symlink-control'])
def test_transitive_or_unknown_control_failure_precedes_any_remote_write(payload,tmp_path,fault):
    root, manifest=payload;store=Store()
    shard=next(entry for key,entry in complete_assets(manifest,root=root) if '-shard-' in entry['name'])
    if fault=='missing':(root/shard['name']).unlink()
    elif fault=='corrupt':(root/shard['name']).write_bytes(b'corrupt')
    elif fault=='extra':(root/'unbound.json').write_bytes(b'{}')
    elif fault=='control':(root/'reservation.json').write_bytes(b'{}')
    else:
        try:(root/'reservation.json').symlink_to(root/'manifest.json')
        except OSError:pytest.skip('symlink privilege unavailable')
    with pytest.raises((ValueError,OSError,RevisionError)):publish(root,store,tmp_path/'state')
    assert not store.objects and store.promotions==0


def test_explicit_control_pins_cannot_hide_extra_or_changed_file(payload):
    root,manifest=payload;raw=(root/'manifest.json').read_bytes()
    target=root/'state'/'receipt.json';target.parent.mkdir();target.write_bytes(b'{}')
    controls={'state/receipt.json':{'bytes':2,'sha256':digest(b'{}')}}
    assert verify_stage(root,expected_manifest_sha256=digest(raw),controls=controls)['asset_bytes_verified']
    target.write_bytes(b'[]')
    with pytest.raises(ValueError):verify_stage(root,expected_manifest_sha256=digest(raw),controls=controls)
    target.write_bytes(b'{}');(root/'state'/'unknown.json').write_bytes(b'{}')
    with pytest.raises(ValueError):verify_stage(root,expected_manifest_sha256=digest(raw),controls=controls)


@pytest.mark.parametrize('name',['../escape.json','state//x.json','C:relative.json',None,'a'*513])
def test_explicit_control_paths_cannot_escape_or_exhaust_inventory(payload,name):
    root,_=payload;raw=(root/'manifest.json').read_bytes()
    with pytest.raises(ValueError,match='unsafe control path'):
        verify_stage(root,expected_manifest_sha256=digest(raw),controls={name:dict(bytes=2,sha256=digest(b'{}'))})


def test_missing_remote_shard_prevents_idempotent_promotion(payload,tmp_path):
    root,manifest=payload;store=Store();first=publish(root,store,tmp_path/'state')
    key=next(key for key in store.objects if key[0]==first.manifest['tag'] and '-shard-' in key[1])
    del store.objects[key]
    with pytest.raises(RevisionError,match='hash verification'):publish(root,store,tmp_path/'state')
    assert store.promotions==1


def test_route_is_immutable_and_cannot_be_forged_by_descriptor(payload,tmp_path):
    root,manifest=payload;store=Store();selected=publish(root,store,tmp_path/'state')
    entries=complete_assets(selected.manifest,root=selected.archive_dir)
    key,entry=next((key,entry) for key,entry in entries if key.startswith('product_evidence_'))
    assert asset_url(selected.manifest,key,entry,repo=DEFAULT_REPO,inventory=entries)==store.url(selected.manifest['tag'],entry['name'])
    changed=deepcopy(selected.manifest);changed['tag']=DEFAULT_TAG
    with pytest.raises(ValueError):asset_url(changed,key,entry,repo=DEFAULT_REPO,inventory=entries)
    with pytest.raises(ValueError):asset_url(selected.manifest,key,{**entry,'sha256':'0'*64},repo=DEFAULT_REPO,inventory=entries)


@pytest.mark.parametrize('fault',[None,'missing-shard','superseded'])
def test_alias_gate_requires_actual_selected_complete_encrypted_revision(payload,tmp_path,fault):
    from app_payload_publication_assets import verify_selected_remote
    root,_=payload;store=Store();selected=publish(root,store,tmp_path/'state')
    entries=complete_assets(selected.manifest,root=selected.archive_dir)
    if fault=='missing-shard':
        del store.objects[next(key for key in store.objects if key[0]==selected.manifest['tag'] and '-shard-' in key[1])]
    elif fault=='superseded':
        value=json.loads(store.objects[DEFAULT_TAG,'dates-index.json']);value['revision_heads'][selected.manifest['run_date']]['manifest_sha256']='0'*64
        store.objects[DEFAULT_TAG,'dates-index.json']=canonical(value)
    if fault:
        with pytest.raises(ValueError):verify_selected_remote(store,selected.manifest,selected.archive_dir,entries)
    else:
        verify_selected_remote(store,selected.manifest,selected.archive_dir,entries)
        assert all(encrypted for _,_,encrypted in store.reads[-len(entries)-2:])


def test_exact_v2_retention_subtree_is_supported_but_extra_file_is_not(payload,tmp_path):
    from app_payload_v2_archive import archive_v2
    from tests.test_app_payload_v2_archive import base,sidecar
    root,manifest=payload;store=Store();old=base(store);selector,_=sidecar(store,old)
    # Existing v2 transport controls contain no invented financial acceptance rows.
    archive_v2(selector,root/'v2-preservation',store=store,source_tag=DEFAULT_TAG)
    validate_manifest(manifest,root)
    directory=next((root/'v2-preservation').iterdir());(directory/'unexpected.json').write_bytes(b'{}')
    with pytest.raises(ValueError,match='unknown publication control'):validate_manifest(manifest,root)


def test_structurally_valid_changed_source_cannot_be_copied_after_initial_verification(payload,tmp_path,monkeypatch):
    import app_payload_revisions as revisions
    root,manifest=payload;store=Store();original=revisions.reserve_revision
    shard=next(entry for _,entry in complete_assets(manifest,root=root) if '-shard-' in entry['name'])
    def change(*args,**kwargs):
        result=original(*args,**kwargs);(root/shard['name']).write_bytes(b'changed');return result
    monkeypatch.setattr(revisions,'reserve_revision',change)
    with pytest.raises(ValueError,match='changed before copy'):publish(root,store,tmp_path/'state')
    assert not store.objects


def test_optional_retry_binds_exact_predecessor_before_reservation(payload,tmp_path,monkeypatch):
    import app_payload_revisions as revisions
    root,_=payload;store=Store();first=publish(root,store,tmp_path/'state')
    expected=deepcopy(first.head);expected['revision']+=1
    monkeypatch.setattr(revisions,'reserve_revision',lambda *a,**k:pytest.fail('stale predecessor reserved'))
    with pytest.raises((RevisionError,ValueError),match='predecessor'):
        publish_revision_bundle(root,state_dir=tmp_path/'state',repo=DEFAULT_REPO,store=store,
            enabled=True,consumer_commit=CONSUMER,expected_predecessor=expected)
    same=publish_revision_bundle(root,state_dir=tmp_path/'state',repo=DEFAULT_REPO,store=store,
        enabled=True,consumer_commit=CONSUMER,expected_predecessor=first.head)
    assert same.head==first.head and not same.index_changed and store.promotions==1


@pytest.mark.parametrize('fault',[None,'wrong-pin','missing-predecessor'])
def test_interrupted_optional_selection_recovers_only_exact_retained_parent(payload,tmp_path,fault):
    root,manifest=payload;store=Store();pending=deepcopy(manifest);pending_root=tmp_path/'pending';pending_root.mkdir()
    for lane in LANES:
        pending.pop(lane);pending['optional_product_evidence_status']['lanes'][lane]=dict(state='pending',reason='not_prepared')
    for entry in pending['files'].values():shutil.copyfile(root/entry['name'],pending_root/entry['name'])
    (pending_root/'manifest.json').write_bytes(canonical(pending))
    first=publish(pending_root,store,tmp_path/'state')
    selected=publish_revision_bundle(root,state_dir=tmp_path/'state',repo=DEFAULT_REPO,store=store,
        enabled=True,consumer_commit=CONSUMER,expected_predecessor=first.head)
    expected=deepcopy(first.head)
    if fault=='wrong-pin':expected['manifest_sha256']='0'*64
    elif fault=='missing-predecessor':
        next((selected.archive_dir/'promotions').glob('*/predecessor/dates-index.json')).unlink()
    def retry():
        return publish_revision_bundle(root,state_dir=tmp_path/'state',repo=DEFAULT_REPO,store=store,
            enabled=True,consumer_commit=CONSUMER,expected_predecessor=expected)
    if fault:
        with pytest.raises((ValueError,OSError)):retry()
    else:
        result=retry();assert not result.index_changed and result.head==selected.head
    assert store.promotions==2


@pytest.mark.parametrize('dated',[False,True])
def test_actual_alias_publisher_keeps_recursive_inventory_without_duplicate_lazy_copies(payload,tmp_path,monkeypatch,dated):
    import app_payload_publish as publisher
    from release_transport import decrypt_transport
    root,_=payload;store=Store();selected=publish(root,store,tmp_path/'state');protected=[];uploads=[]
    tag=f'app-payload-{selected.manifest["run_date"]}' if dated else DEFAULT_TAG
    store.objects[tag,'unknown-preserve']=b'untouched'
    key=bytes(range(32));keyfile=tmp_path/'key';keyfile.write_text(key.hex());monkeypatch.setenv('AR_LOCAL_PAYLOAD_KEY_FILE',str(keyfile))
    monkeypatch.setattr('app_payload_revisions_github.GitHubRevisionStore',lambda *a,**k:store)
    monkeypatch.setattr('app_payload_v2_archive.GitHubRevisionStore',lambda *a,**k:store)
    monkeypatch.setattr('publication_status.publish',lambda *a,**k:None)
    def run(argv,**kwargs):
        if argv[1]=='api':
            if '--paginate' in argv:
                values=[dict(id=i+1,name=name) for i,(_,name) in enumerate(
                    key for key in store.objects if key[0]==tag)]
                output=json.dumps([values])
            else:output=json.dumps(dict(id=1,tag_name=tag))
        elif argv[1:3]==['release','upload']:
            paths=[Path(p) for p in argv[4:argv.index('--repo')]];uploads.append([p.name for p in paths])
            for path in paths:store.objects[tag,path.name]=decrypt_transport(path.read_bytes(),lambda _:key)
            output=''
        else:output=''
        return SimpleNamespace(returncode=0,stdout=output,stderr='')
    def live(*args):
        raw=store.objects.get((tag,'manifest.json'))
        return ('present',json.loads(raw)) if raw else ('missing',None)
    functions={'_gh_available':lambda:'gh','_gh_authed':lambda gh:True,'subprocess':SimpleNamespace(run=run),
        '_live_manifest_status':live,'_manifest_should_replace':publisher._manifest_should_replace,
        '_update_release_title':lambda *a:True,'_prune_release_assets':lambda *a:protected.append(a[-1]) or 0}
    monkeypatch.setattr(publisher,'_app_payload',functions.__getitem__)
    entries=complete_assets(selected.manifest,root=selected.archive_dir)
    expected={entry['name'] for _,entry in entries}
    lazy={entry['name'] for name,entry in entries if name.startswith(tuple(lane+'_' for lane in LANES))}
    assert lazy
    # Complete immutable evidence remains mandatory BEFORE any alias mutation.
    missing=next((selected.manifest['tag'],name) for name in lazy if '-shard-' in name)
    original=store.objects.pop(missing);before=dict(store.objects)
    with pytest.raises(ValueError,match='immutable evidence asset'):
        publisher.publish_payload(selected.archive_dir,repo=DEFAULT_REPO,tag=tag)
    assert not uploads and store.objects==before
    store.objects[missing]=original;store.reads.clear()
    assert publisher.publish_payload(selected.archive_dir,repo=DEFAULT_REPO,tag=tag)
    alias_names={name for release,name in store.objects if release==tag}
    assert protected==([] if dated else [expected]) and expected-lazy <= alias_names
    assert lazy.isdisjoint(alias_names) and store.objects[tag,'unknown-preserve']==b'untouched'
    assert {name for release,name,encrypted in store.reads if release==selected.manifest['tag'] and encrypted} >= expected
    assert {name for release,name,encrypted in store.reads if release==tag and encrypted} >= expected-lazy
    assert lazy.isdisjoint({name for batch in uploads for name in batch})
    assert uploads[-1]==['manifest.json'] and all(len(batch)<=16 for batch in uploads)
    # Previously the missing-alias path left an empty, unbound backup directory.
    assert not (selected.archive_dir/'.prev-manifest').exists()
    publisher.publish_payload(selected.archive_dir,repo=DEFAULT_REPO,tag=tag)
    validate_manifest(selected.manifest,selected.archive_dir)
    copied=selected.manifest['files']['core']['name'];store.objects[tag,copied]=b'corrupted alias financial asset'
    prior_uploads=len(uploads)
    with pytest.raises(RevisionError,match='public asset failed encrypted byte verification'):
        publisher.publish_payload(selected.archive_dir,repo=DEFAULT_REPO,tag=tag)
    assert len(uploads)==prior_uploads and store.objects[tag,'unknown-preserve']==b'untouched'


@pytest.mark.parametrize('fault',[None,'failed','duplicate','wrong-tag','oversized'])
def test_complete_authenticated_listing_keeps_all_pages_and_unknown_assets(fault):
    from app_payload_publication_listing import list_asset_names
    calls=[];pages=[[{'id':i+1,'name':f'asset-{i}'} for i in range(100)], [{'id':101,'name':'unknown-preserve'}]]
    if fault=='duplicate':pages[-1][0]['name']='asset-0'
    if fault=='oversized':pages=[[]]*101
    def runner(argv,**kwargs):
        calls.append(argv)
        value=pages if '--paginate' in argv else {'id':1,'tag_name':'wrong' if fault=='wrong-tag' else DEFAULT_TAG}
        return SimpleNamespace(returncode=1 if fault=='failed' else 0,stdout=json.dumps(value))
    if fault:
        with pytest.raises(RevisionError):list_asset_names('gh',DEFAULT_REPO,DEFAULT_TAG,runner=runner)
    else:
        assert len(list_asset_names('gh',DEFAULT_REPO,DEFAULT_TAG,runner=runner))==101
        assert '--paginate' in calls[-1] and '--slurp' in calls[-1]


def test_every_evidence_filename_is_are2_only(tmp_path,monkeypatch):
    from app_payload_secure_upload import secure_upload,classify_asset
    from release_transport import decrypt_transport,MAGIC,TransportError
    key=bytes(range(32));keyfile=tmp_path/'key';keyfile.write_text(key.hex());monkeypatch.setenv('AR_LOCAL_PAYLOAD_KEY_FILE',str(keyfile))
    raw=b'original gzip domain bytes';path=tmp_path/f'product-response-shard-{digest(raw)}.json.gz';path.write_bytes(raw)
    assert classify_asset(path.name)=='cdr_domain'
    def runner(argv,**kwargs):
        wire=Path(argv[4]).read_bytes();assert wire.startswith(MAGIC)
        assert decrypt_transport(wire,lambda _:key,limit=1024)==raw
        return SimpleNamespace(returncode=0)
    secure_upload(['gh','release','upload','technical',str(path)],runner=runner)
    assert path.read_bytes()==raw
    for name in [path.name+'.enc',path.name.replace('shard','future'),path.name.replace('product-response','product-future')]:
        with pytest.raises(TransportError):classify_asset(name)
