"""Operational preparation policy tests; no root or Pi writes."""
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import stat
import pytest
import pi_plain_backup_install as install
import pi_plain_backup_packet as packet


def plan():
    result={'schema':'ar-local-plain-backup-install-v1','manual_plaintext_backup_scope':True,
        'control':{name:'a'*64 for name in install.CONTROL|{'build-packet.py','plan.py'}},
        'queue':{name:'b'*64 for name in install.QUEUE_NAMES},
        'expected_existing_queue':{name:None if name=='pi_shared_queue_post_hooks.py' else 'c'*64 for name in install.QUEUE_NAMES},
        'producer':{'pi_plain_backup_probe.py':'d'*64},'remote':'approved:plaintext-recovery',
        'drive_root_folder_id':'approved-folder-012345'}
    for key in ('wrapper_sha256','expected_reclaim_sha256','global_hold_sha256','bwrap_sha256','setpriv_sha256','installer_sha256'):
        result[key]='e'*64
    return result


def test_plan_module_is_part_of_installed_and_hash_bound_builder_closure():
    data=plan();install.validate_plan(data)
    del data['control']['plan.py']
    with pytest.raises(RuntimeError):install.validate_plan(data)


@pytest.mark.parametrize('name',['../escape','/absolute','bad\\member','ok/../escape'])
def test_bundle_never_accepts_paths_outside_fixed_source_tree(name):
    data=plan();data['producer'][name]='f'*64
    with pytest.raises(RuntimeError):install.validate_plan(data)


def test_existing_pi_owned_private_credential_leaf_is_preserved_not_rejected_as_nonroot():
    leaf=SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=1000,st_gid=1000,st_nlink=1,st_size=123)
    packet.validate_credential_stat(leaf,1000,1000)
    leaf.st_uid=0
    with pytest.raises(RuntimeError):packet.validate_credential_stat(leaf,1000,1000)


@pytest.mark.parametrize('attribute,value',[('st_mode',stat.S_IFREG|0o644),('st_nlink',2),('st_size',65537),('st_gid',0)])
def test_credential_source_owner_mode_link_and_size_remain_strict(attribute,value):
    leaf=SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=1000,st_gid=1000,st_nlink=1,st_size=123)
    setattr(leaf,attribute,value)
    with pytest.raises(RuntimeError):packet.validate_credential_stat(leaf,1000,1000)


def evidence():
    return {'boot_id':'boot','exit':0,'scope':'kernel-confinement-probe-only-no-backup-acceptance',
        'runtime_sha256':{'/usr/bin/bwrap':'bwrap','/usr/bin/setpriv':'setpriv'},
        'host_namespaces':{'user':1,'pid':2,'mnt':3},
        'observed':{'result':'PASS_KERNEL_CONFINEMENT_ONLY','uid':1000,'gid':1000,'groups':[],'NNP':'1',
            'source_ro':True,'pid1_root':'ACCESS_DENIED','fd_root_owned':True,'fd_readonly':True,'fd_seals':15,
            'caps':{name:'0000000000000000' for name in ('CapInh','CapPrm','CapEff','CapBnd','CapAmb')},
            'namespaces':{'user':1,'pid':4,'mnt':5}}}


def test_real_kernel_receipt_normalization_never_manufactures_coupled_or_backup_acceptance():
    result=packet.normalized_kernel(evidence(),'boot','bwrap','setpriv')
    assert result['scope']=='KERNEL_ONLY_NOT_COUPLED_OR_BACKUP'
    assert result['schema']=='ar-local-plain-backup-sandbox-probe-v1'
    assert 'root_completion_verified' not in result
    with pytest.raises(RuntimeError):packet.normalized_kernel(evidence(),'changed-boot','bwrap','setpriv')


def test_fresh_probe_expiry_and_quiet_window_are_bounded():
    now=datetime(2026,10,24,5,tzinfo=timezone.utc)
    assert packet.expiry_for('PROBE',now)-now==timedelta(seconds=120)
    with pytest.raises(RuntimeError):packet.expiry_for('PROBE',datetime(2026,10,24,14,tzinfo=timezone.utc))

@pytest.mark.parametrize('value',['infinity','0','11min','1h','bogus'])
def test_installer_requires_a_real_finite_native_execution_ceiling(value):
    with pytest.raises(RuntimeError):install.bounded_runtime(value)


def test_installer_runtime_within_ten_minutes():
    assert install.bounded_runtime('10min')==600
    assert install.bounded_runtime('2min')==120


def test_installer_guard_counts_whole_cgroup_and_never_changes_swappiness(monkeypatch):
    code='''
def sample_host():
    return {'available_bytes':8*1024**3,'swap_out_pages':0,'swap_in_pages':0,'page_size_bytes':16384,'psi_avg10':0}
def host_violation(now,before,previous,admission=False):return None
def process_memory(pid):return {'rss':640*1024**2 if pid==1 else 1,'swap':0}
'''
    guard=install.InstallResources({'cgroup':'/owned'},code)
    guard.members=lambda:{1,2}
    original=install.Path.read_text
    monkeypatch.setattr(install.Path,'read_text',lambda self,*a,**kw:'60' if str(self).endswith('swappiness') else original(self,*a,**kw))
    with pytest.raises(RuntimeError,match='aggregate_rss_early_stop'):guard.sample()
    assert guard.receipt['peak_rss_bytes']>=640*1024**2
