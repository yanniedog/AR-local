"""Definition-only installer controls; no elevated actions or service changes."""
from copy import deepcopy
from datetime import datetime,timezone
import ast
from pathlib import Path
import pytest
import pi_product_evidence_install as install


def plan():
    return dict(schema='ar-product-evidence-install-v1',uid=1000,source_commit='a'*40,source_tree='b'*40,
        helper_sha256='c'*64,profile_sha256='d'*64,ci_receipt_sha256='e'*64,qualification_receipt_sha256='f'*64,
        expires_utc='2026-11-15T00:00:00+00:00',preimages={key:None for key in install.TARGETS})


@pytest.mark.parametrize('fault',['target','extra','qualification','root','expiry','mode'])
def test_installer_rejects_broader_scope_or_unpinned_qualification(fault):
    value=plan()
    if fault=='target':value['preimages']['/etc/passwd']=None
    elif fault=='extra':value['command']='systemctl restart example'
    elif fault=='qualification':value['qualification_receipt_sha256']=None
    elif fault=='root':value['uid']=0
    elif fault=='expiry':value['expires_utc']='2026-11-15T00:00:00'
    else:value['preimages']['helper']=dict(sha256='0'*64,mode=0o7777)
    with pytest.raises(ValueError):install.validate_plan(value)


def test_definition_exact_targets_and_no_repository_imports():
    assert install.validate_plan(plan()).tzinfo is not None
    assert {path.as_posix() for path in install.TARGETS.values()}=={
        '/usr/local/lib/ar-local-product-evidence/launch.py','/etc/ar-local/product-evidence-launch.json',
        '/etc/sudoers.d/ar-local-product-evidence'}
    source=Path(install.__file__).read_text();tree=ast.parse(source)
    imports={node.module for node in ast.walk(tree) if isinstance(node,ast.ImportFrom)}
    imports|={alias.name for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names}
    assert not any(name and name.startswith(('pi_','cdr_','app_payload')) for name in imports)
    assert "'restart'" not in source and "'enable'" not in source and "'start'" not in source


def test_final_readback_rejects_late_changed_postimage(tmp_path,monkeypatch):
    paths={name:tmp_path/name for name in install.TARGETS};bodies={name:name.encode() for name in paths}
    for name,path in paths.items():path.write_bytes(bodies[name])
    monkeypatch.setattr(install,'TARGETS',paths)
    monkeypatch.setattr(install,'MODES',{name:path.stat().st_mode&0o777 for name,path in paths.items()})
    monkeypatch.setattr(install,'protected',lambda path,maximum=0:path.read_bytes())
    assert install.installed_proof(bodies,{name:None for name in paths},'apply')
    paths['profile'].write_bytes(b'foreign')
    with pytest.raises(ValueError,match='postimages'):install.installed_proof(bodies,{},'apply')


def test_partial_apply_rollback_uses_new_claim_and_retains_exact_preimages(tmp_path,monkeypatch):
    """Transaction control only; root ownership/OS primitives have separate gates."""
    root=tmp_path/'root';root.mkdir();records=tmp_path/'records';records.mkdir()
    stage=tmp_path/'stages'/('a'*32);stage.mkdir(parents=True)
    paths={name:root/name for name in install.TARGETS}
    originals={name:('original-'+name).encode() for name in paths}
    for name,path in paths.items():path.write_bytes(originals[name])
    monkeypatch.setattr(install,'STAGES',stage.parent);monkeypatch.setattr(install,'ROOT',root)
    monkeypatch.setattr(install,'RECORDS',records);monkeypatch.setattr(install,'TARGETS',paths)
    monkeypatch.setattr(install,'__file__',str(stage/'install.py'))
    monkeypatch.setattr(install.os,'geteuid',lambda:0,raising=False)
    monkeypatch.setattr(install,'protected',lambda path,maximum=0:path.read_bytes())
    monkeypatch.setattr(install.subprocess,'run',lambda *a,**k:None)
    monkeypatch.setattr(install,'sync',lambda path:None)
    def create(path,raw,mode=0o400):
        if path.exists():assert path.read_bytes()==raw
        else:path.write_bytes(raw)
    monkeypatch.setattr(install,'create',create)
    owner={'id':'first'};monkeypatch.setattr(install,'host_owner',lambda *a:dict(owner))
    helper=b'def profile_value(raw, deadline): pass\ndef trusted(path, directory=False): pass\n'
    profile=install.canonical(dict(uid=1000,user='operator',source_commit='a'*40,source_tree='b'*40,
        source_files={name:dict(bytes=len(raw),sha256=install.sha(raw)) for name,raw in
                      (('pi_product_evidence_launch.py',helper),('pi_product_evidence_install.py',b'reviewed'))}))
    value=plan();value.update(helper_sha256=install.sha(helper),profile_sha256=install.sha(profile),expires_utc='2099-01-01T00:00:00+00:00',
        ci_receipt_sha256=install.sha(b'ci'),qualification_receipt_sha256=install.sha(b'qualification'),
        preimages={name:dict(sha256=install.sha(raw),mode=paths[name].stat().st_mode&0o777) for name,raw in originals.items()})
    files={'install.py':b'reviewed','plan.json':install.canonical(value),'launch.py':helper,'profile.json':profile,
           'ci-receipt.json':b'ci','qualification-receipt.json':b'qualification'}
    for name,raw in files.items():(stage/name).write_bytes(raw)
    fail=True
    def replace(path,raw,mode):
        if fail and path==paths['profile']:raise OSError('injected second replacement failure')
        path.write_bytes(raw)
    monkeypatch.setattr(install,'replace',replace)
    args=(stage,install.sha(files['plan.json']),install.sha(files['install.py']))
    with pytest.raises(OSError,match='second replacement'):install._execute(*args,'apply')
    assert paths['helper'].read_bytes()==helper
    assert (stage/'apply-incomplete.json').exists()
    fail=False;owner['id']='fresh-rollback-claim'
    assert install._execute(*args,'rollback')['result']=='PASS'
    assert {name:path.read_bytes() for name,path in paths.items()}==originals
    assert (stage/'apply-incomplete.json').exists() and (stage/'rollback-complete.json').exists()


def test_whole_installation_alarm_is_bounded_and_restored(monkeypatch):
    import types
    events=[];previous=object()
    monkeypatch.setattr(install,'signal',types.SimpleNamespace(SIGALRM=14,signal=lambda *args:events.append(('signal',args)) or previous,
        alarm=lambda seconds:events.append(('alarm',seconds))))
    monkeypatch.setattr(install,'_execute',lambda *args:(_ for _ in ()).throw(ValueError('failed')))
    with pytest.raises(ValueError,match='failed'):install.execute(None,None,None,'apply')
    assert ('alarm',240) in events and events[-2]==('alarm',0) and events[-1]==('signal',(14,previous))


@pytest.mark.parametrize('name',['pi_product_evidence_launch.py','pi_product_evidence_install.py'])
def test_root_helper_pair_must_match_the_same_approved_source_inventory(name):
    originals={'pi_product_evidence_launch.py':b'launcher','pi_product_evidence_install.py':b'installer'}
    profile={'source_files':{key:dict(bytes=len(raw),sha256=install.sha(raw)) for key,raw in originals.items()}}
    install.source_pair(profile,b'launcher',b'installer')
    profile['source_files'][name]['sha256']='0'*64
    with pytest.raises(ValueError,match='source inventory'):install.source_pair(profile,b'launcher',b'installer')
