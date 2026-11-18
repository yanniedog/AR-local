"""No sudo/systemd execution: strict standalone root request/argv contracts."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import pytest
import pi_product_evidence_launch as launch
from tests.test_product_evidence_admission import state,select,now


def request():
    return dict(day='2026-11-14',request_sha256='a'*64,attempt_id='b'*32,phase='snapshot',owner=select(),production_lease=None)


@pytest.mark.parametrize('change',['argv','env','source','path','unit','host','clock','nan','extended','cleanup','quiet','phase'])
def test_root_rejects_unreviewed_inputs_and_renewed_budget(change):
    value=request()
    if change in ('argv','env','source','path'):value[change]='untrusted'
    elif change=='unit':value['owner']['job']['unit']='sshd.service'
    elif change=='host':value['owner']['job']['resources'].append('host')
    elif change=='clock':value['owner']['admitted_monotonic']=1001
    elif change=='nan':value['owner']['deadline_monotonic']=float('nan')
    elif change=='extended':value['owner']['deadline_monotonic']=2801
    elif change=='cleanup':value['owner']['cleanup_seconds']=0
    elif change=='quiet':value['owner']['quiet_utc']=(now()+timedelta(days=1)).isoformat()
    else:value['phase']='shell'
    with pytest.raises((ValueError,TypeError)):launch.validate_job(value,clock=1000,now=now())


def test_valid_root_budget_preserves_original_cross_midnight_deadline():
    value=request();_,deadline=launch.validate_job(value,clock=1000,now=now())
    assert deadline==2800
    assert launch.validate_job(value,clock=1120,now=now()+timedelta(minutes=2))[1]==deadline
    with pytest.raises(ValueError):launch.validate_job(value,clock=2800,now=now()+timedelta(seconds=1800))


def test_separate_fixed_sandboxes_and_native_lifetime():
    value=request();approved=dict(user='operator',uid=1000,gid=1000,_source='/usr/local/lib/ar-local-product-evidence/source/'+'c'*40)
    attempt=Path('/owned/attempt')
    preparation=launch.properties(value,approved,attempt,1000)
    assert 'PrivateNetwork=yes' in preparation and 'RestrictAddressFamilies=AF_UNIX' in preparation
    assert not any(item.startswith('EnvironmentFile=') for item in preparation)
    assert 'RuntimeMaxSec=985s' in preparation and 'TimeoutStopSec=35s' in preparation
    assert 'BindsTo='+value['owner']['job']['unit'] in preparation
    assert {'PrivateTmp=yes','ProtectSystem=strict','ReadOnlyPaths=/tmp /var/tmp','IOWeight=10','MemoryMax=3G','MemorySwapMax=0'}<=set(preparation)
    value['phase']='publish';publication=launch.properties(value,approved,attempt,1000)
    assert 'EnvironmentFile=/etc/ar-local/app-payload.env' in publication and 'PrivateNetwork=yes' not in publication
    assert 'NoNewPrivileges=yes' in publication
    assert not any(item.startswith('ReadWritePaths=') and ('daily-ingest.lock' in item or item=='ReadWritePaths=/srv/ar-local/data/state') for item in publication)
    assert all('sh -c' not in item and 'sudo' not in item for item in publication)


def test_root_file_is_standalone_no_repository_imports():
    import ast
    tree=ast.parse(Path(launch.__file__).read_text())
    imports={node.module.split('.')[0] for node in ast.walk(tree) if isinstance(node,ast.ImportFrom) and node.module}
    imports|={alias.name.split('.')[0] for node in ast.walk(tree) if isinstance(node,ast.Import) for alias in node.names}
    assert not any(name.startswith(('pi_','cdr_','app_payload','ar_local')) for name in imports)


def test_optional_supervisor_namespace_is_exact():
    from pi_cdr_quality_resources import UNIT
    assert UNIT.fullmatch('ar-local-product-evidence-'+'a'*32+'.service')
    assert not UNIT.fullmatch('ar-local-product-evidence-arbitrary.service')
    assert not UNIT.fullmatch('ar-local-product-evidence-'+'a'*31+'.service')
