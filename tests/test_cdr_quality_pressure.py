import copy
import json
from pathlib import Path
import sys
import types

import pytest
import pi_cdr_quality_pressure as p


BOOT='cf36b73c-7655-4bbc-8445-e917f3a85012'


def host(t=1_000_000_000):
    cache={k:1024 for k in p.CACHE_FIELDS}
    cache.update(MemTotal=8*1024**3,MemAvailable=7*1024**3)
    pressure={'profile':p.PROFILE,'boot_id':BOOT,'page_size_bytes':16384,
              'monotonic_ns':t,'read_elapsed_ns':1_000_000,'lru_gen_enabled':0,'node_refaults':[[0,10,10]],
              'counters':{k:10 for k in p.COUNTERS},'cache_bytes':cache,
              'zones':[{'node':0,'zone':'Normal','managed':10000,'pages free':5000,
                        'boost':100,'min':200,'low':300,'high':400}]}
    pressure['capture'] = {'global_before': pressure['counters'], 'global_after': pressure['counters'],
                           'nodes_before': pressure['node_refaults'], 'nodes_after': pressure['node_refaults']}
    return {'page_size_bytes':16384,'available_bytes':7*1024**3,'pressure':pressure,
            'swap_out_pages':0,'swap_in_pages':0,'psi_avg10':None}


def next_host(value,ns=100_000_000):
    result=copy.deepcopy(value);result['pressure']['monotonic_ns']+=ns
    return result


def test_healthy_background_swap_and_cache_are_not_byte_allowance():
    first=host();tracker=p.PressureTracker(first);last=next_host(first)
    last['swap_out_pages']=10**12
    for key in p.ACTIVITY_COUNTERS:last['pressure']['counters'][key]+=50
    last['pressure']['node_refaults'][0][1:] = [60,60]
    last['pressure']['cache_bytes']['Cached']+=1024**3
    tracker.observe(last,None,1.1)
    summary=tracker.receipt()
    assert summary['observations']==2 and summary['cumulative']['pgscan_kswapd']==50
    assert summary['cache_max_bytes']['Cached']==1024**3+1024
    p.require_pressure_receipt(summary,first,last)


def test_baseline_only_is_incomplete_not_acceptance():
    first=host();tracker=p.PressureTracker(first)
    assert tracker.receipt()['result']=='INCOMPLETE' and tracker.receipt()['observations']==1
    with pytest.raises(ValueError):p.require_pressure_receipt(tracker.receipt(),first,first)


@pytest.mark.parametrize('counter',p.PRESSURE_COUNTERS)
def test_any_cumulative_real_pressure_is_latched(counter):
    first=host();tracker=p.PressureTracker(first);bad=next_host(first)
    bad['pressure']['counters'][counter]+=1
    with pytest.raises(ValueError,match='host_allocation_pressure_observed'):tracker.observe(bad)
    with pytest.raises(ValueError,match='latched'):tracker.observe(next_host(bad))
    receipt=tracker.receipt()
    assert receipt['result']=='FAIL' and receipt['cumulative'][counter]==1
    with pytest.raises(ValueError):p.require_pressure_receipt(receipt,first,bad)
    forged={**receipt,'result':'PASS','failure':None}
    with pytest.raises(ValueError):p.require_pressure_receipt(forged,first,bad)


@pytest.mark.parametrize('margin',[-1,0,1])
def test_printed_minimum_already_includes_boost(margin):
    first=host();tracker=p.PressureTracker(first);last=next_host(first)
    last['pressure']['zones'][0]['pages free']=200+margin
    if margin<=0:
        with pytest.raises(ValueError,match='minimum_headroom'):tracker.observe(last)
    else:
        tracker.observe(last)
        p.require_pressure_receipt(tracker.receipt(),first,last)
        assert tracker.receipt()['minimum_zone_margins']['0:Normal']['min']==1


@pytest.mark.parametrize('counter',p.REFAULT_COUNTERS)
def test_low_zone_and_interval_refault_rejected(counter):
    first=host();tracker=p.PressureTracker(first);last=next_host(first)
    last['pressure']['zones'][0]['pages free']=300
    last['pressure']['counters'][counter]+=1
    last['pressure']['node_refaults'][0][1+p.REFAULT_COUNTERS.index(counter)]+=1
    with pytest.raises(ValueError,match='low_with_refault'):tracker.observe(last)
    assert tracker.receipt()['low_with_activity_samples']==1
    assert tracker.receipt()['low_with_refault_samples']==1
    with pytest.raises(ValueError):
        p.require_pressure_receipt(tracker.receipt(),first,last)
    forged={**tracker.receipt(),'result':'PASS','failure':None}
    with pytest.raises(ValueError):p.require_pressure_receipt(forged,first,last)


def test_temporary_zone_breach_cannot_be_erased_by_terminal_health():
    first=host();tracker=p.PressureTracker(first);bad=next_host(first)
    bad['pressure']['zones'][0]['pages free']=199
    with pytest.raises(ValueError):tracker.observe(bad)
    with pytest.raises(ValueError):tracker.observe(next_host(first,200_000_000))
    assert tracker.receipt()['minimum_zone_margins']['0:Normal']['min']==-1


@pytest.mark.parametrize('fault',['boot','page','zone_inventory','counter_reset','counter_missing','cache_missing',
                                   'clock_equal','clock_reverse','gap','stale','missing_pressure','host_binding','opaque_service'])
def test_invalid_profile_and_identity_fail_closed_and_latch(fault):
    first=host();tracker=p.PressureTracker(first);last=next_host(first)
    q=last['pressure'];now=None;service=None
    if fault=='boot':q['boot_id']='a'*8+'-aaaa-aaaa-aaaa-'+'a'*12
    if fault=='page':q['page_size_bytes']=4096;last['page_size_bytes']=4096
    if fault=='zone_inventory':q['zones'][0]['managed']+=1
    if fault=='counter_reset':q['counters']['pgmajfault']-=1
    if fault=='counter_missing':del q['counters']['workingset_refault_file']
    if fault=='cache_missing':del q['cache_bytes']['Writeback']
    if fault=='clock_equal':q['monotonic_ns']=first['pressure']['monotonic_ns']
    if fault=='clock_reverse':q['monotonic_ns']=1
    if fault=='gap':q['monotonic_ns']+=p.MAX_GAP_NS
    if fault=='stale':now=10
    if fault=='missing_pressure':del last['pressure']
    if fault=='host_binding':last['available_bytes']-=1
    if fault=='opaque_service':service={'success':True}
    with pytest.raises(ValueError):tracker.observe(last,service,now)
    assert tracker.receipt()['result']=='FAIL'
    with pytest.raises(ValueError,match='latched'):tracker.observe(next_host(first))


@pytest.mark.parametrize('fault',['result','old_profile','missing','baseline','last','observations','gap','cumulative',
                                   'peak','zone_extrema','cache_extrema','low_activity','clock'])
def test_receipt_independent_validation(fault):
    first=host();last=next_host(first);tracker=p.PressureTracker(first);tracker.observe(last)
    r=tracker.receipt()
    if fault=='result':r['result']='FAIL'
    if fault=='old_profile':r['profile']='old'
    if fault=='missing':del r['maximum_gap_ns']
    if fault=='baseline':r['baseline_sha256']='0'*64
    if fault=='last':r['last_sha256']='0'*64
    if fault=='observations':r['observations']=1
    if fault=='gap':r['maximum_gap_ns']=1
    if fault=='cumulative':r['cumulative']['pgmajfault']=1
    if fault=='peak':r['maximum_interval']['pgmajfault']=1
    if fault=='zone_extrema':r['minimum_zone_margins']['0:Normal']['min']=9999
    if fault=='cache_extrema':r['cache_min_bytes']['Cached']=9999
    if fault=='low_activity':r['low_with_activity_samples']=1
    if fault=='clock':r['last_monotonic_ns']+=1
    with pytest.raises(ValueError):p.require_pressure_receipt(r,first,last)


def test_receipts_are_deep_copies():
    first=host();tracker=p.PressureTracker(first);last=next_host(first);tracker.observe(last)
    r=tracker.receipt();r['minimum_zone_margins']['0:Normal']['min']=-100
    first['pressure']['counters']['pgmajfault']=999
    assert tracker.receipt()['minimum_zone_margins']['0:Normal']['min']==4800
    assert tracker.baseline['counters']['pgmajfault']==10


@pytest.mark.parametrize('fault',['boolean_host_memory','boolean_clock','read_clock','boolean_observations','boolean_cumulative'])
def test_boolean_and_clock_values_cannot_masquerade_as_integers(fault):
    first=host();last=next_host(first)
    if fault=='boolean_host_memory':
        first['available_bytes']=True
        with pytest.raises(ValueError):p.PressureTracker(first)
        return
    if fault=='read_clock':
        first['pressure']['read_elapsed_ns']=first['pressure']['monotonic_ns']+1
        with pytest.raises(ValueError):p.PressureTracker(first)
        return
    tracker=p.PressureTracker(first);tracker.observe(last);receipt=tracker.receipt()
    if fault=='boolean_clock':receipt['baseline_monotonic_ns']=True
    if fault=='boolean_observations':receipt['observations']=True
    if fault=='boolean_cumulative':receipt['cumulative']['pgmajfault']=False
    with pytest.raises(ValueError):p.require_pressure_receipt(receipt,first,last)


@pytest.mark.parametrize('fault',['missing','duplicate','float','negative','overflow','boolean','nonascii','unit','oversized'])
def test_strict_counter_parser(fault):
    text='MemTotal: 8192 kB\nMemAvailable: 4096 kB\n';names=('MemTotal','MemAvailable')
    if fault=='missing':text=text.splitlines()[0]
    if fault=='duplicate':text+='MemTotal: 8192 kB\n'
    if fault=='float':text=text.replace('8192','8.192')
    if fault=='negative':text=text.replace('8192','-1')
    if fault=='overflow':text=text.replace('8192',str(2**64))
    if fault=='boolean':text=text.replace('8192','true')
    if fault=='nonascii':text=text.replace('8192','８１９２')
    if fault=='unit':text=text.replace('kB','KB')
    if fault=='oversized':text+=' '*p.MAX_COUNTER_TEXT
    with pytest.raises(ValueError):p.numeric_map(text,names,kib=True)


@pytest.mark.parametrize('extra',[
    'allocstall 0\n',
    'allocstall_highmem 0\n',
    'allocstall_highmem 0\nallocstall_highmem 0\n',
    'allocstall_highmem malformed\n',
    'allocstall\n',
])
def test_unqualified_allocation_stall_family_is_never_ignored(extra):
    text=''.join(name+' 0\n' for name in p.COUNTERS)+extra
    with pytest.raises(ValueError,match='unsupported_allocation_stall_counter_family'):
        p.numeric_map(text,p.COUNTERS)


def test_missing_qualified_allocation_counter_cannot_be_replaced_by_aggregate():
    text=''.join(name+' 0\n' for name in p.COUNTERS if name!='allocstall_movable')
    with pytest.raises(ValueError,match='pressure_field_inventory'):
        p.numeric_map(text,p.COUNTERS)
    with pytest.raises(ValueError,match='unsupported_allocation_stall_counter_family'):
        p.numeric_map(text+'allocstall 0\n',p.COUNTERS)


def proc_fixture(tmp_path):
    boot=tmp_path/'sys/kernel/random/boot_id';boot.parent.mkdir(parents=True);boot.write_text(BOOT+'\n')
    (tmp_path/'zoneinfo').write_text('Node 0, zone Normal\n pages free 5000\n boost 100\n min 200\n low 300\n high 400\n managed 10000\n')
    memory=''.join(k+': '+str(8*1024**2 if k=='MemTotal' else 1024)+' kB\n' for k in p.CACHE_FIELDS)
    vm=''.join(k+' 0\n' for k in p.COUNTERS)
    (tmp_path/'vmstat').write_text(vm)
    sysfs=tmp_path/'sysfs'
    for relative,body in [('kernel/mm/lru_gen/enabled','0x0003\n'),('devices/system/node/online','0\n'),('devices/system/node/node0/vmstat','workingset_refault_anon 0\nworkingset_refault_file 0\n')]:
        path=sysfs/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body.encode('ascii'))
    return memory,vm


def test_actual_bounded_sampler_and_timestamp(tmp_path,monkeypatch):
    memory,vm=proc_fixture(tmp_path)
    monkeypatch.setattr(p.os,'sysconf',lambda name:16384,raising=False)
    clocks=iter([1_000_000_000,1_001_000_000]);monkeypatch.setattr(p.time,'monotonic_ns',lambda:next(clocks))
    snapshot=p.sample_pressure(tmp_path,memory,vm,sysfs=tmp_path/'sysfs')
    assert snapshot['boot_id']==BOOT and snapshot['monotonic_ns']==1_001_000_000
    assert snapshot['read_elapsed_ns']==1_000_000 and snapshot['zones'][0]['min']==200


@pytest.mark.parametrize('fault',['missing_zone','duplicate_zone','bad_watermark','missing_boot','bad_page','slow_read'])
def test_sampler_unavailable_and_invalid_inputs(tmp_path,monkeypatch,fault):
    memory,vm=proc_fixture(tmp_path)
    monkeypatch.setattr(p.os,'sysconf',lambda name:1234 if fault=='bad_page' else 16384,raising=False)
    if fault=='missing_zone':(tmp_path/'zoneinfo').unlink()
    if fault=='duplicate_zone':
        path=tmp_path/'zoneinfo';path.write_text(path.read_text()*2)
    if fault=='bad_watermark':
        path=tmp_path/'zoneinfo';path.write_text(path.read_text().replace('min 200','min 500'))
    if fault=='missing_boot':(tmp_path/'sys/kernel/random/boot_id').unlink()
    if fault=='slow_read':
        clocks=iter([1_000_000_000,4_000_000_000]);monkeypatch.setattr(p.time,'monotonic_ns',lambda:next(clocks))
    with pytest.raises((ValueError,OSError)):p.sample_pressure(tmp_path,memory,vm,sysfs=tmp_path/'sysfs')


def test_r10_remains_failed_under_cumulative_pressure_semantics():
    # Recorded deltas from failed R10 resource receipt SHA256
    # 871464e072717ec4ce7611d8f13f933108313c452277e0d32f8750cebc067068.
    # Supplemental fields are protocol controls, not an enhanced R10 receipt.
    # Keep this test self-contained; do not depend on private operator evidence.
    before=host();after=next_host(before)
    for key,delta in {'allocstall_movable':4,'pgscan_direct':432,'pgsteal_direct':432}.items():
        after['pressure']['counters'][key]+=delta
    tracker=p.PressureTracker(before)
    with pytest.raises(ValueError,match='allocation_pressure'):tracker.observe(after)
    assert tracker.receipt()['cumulative']['allocstall_movable']==4
    assert tracker.receipt()['cumulative']['pgscan_direct']==432
    assert tracker.receipt()['result']=='FAIL'
