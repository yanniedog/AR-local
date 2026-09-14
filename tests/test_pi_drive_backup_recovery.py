"""Recovery protocol/temporary SQLite tests; never production acceptance data."""
from dataclasses import asdict
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
from types import SimpleNamespace

import pytest

import pi_drive_backup as backup
import pi_drive_backup_controller as controller
import pi_drive_backup_recovery as recovery
import pi_drive_backup_resources as resources


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value).encode())
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def original(tmp_path, monkeypatch):
    spool = (tmp_path / "spool").resolve(); spool.mkdir()
    config = backup.Config(tmp_path / "untouched-source", spool, "unused-transport", spool / "password", spool / "config", [])
    monkeypatch.setattr(backup, "guard_window", lambda: None)
    monkeypatch.setattr("process_safety.process_alive", lambda _: False)
    began = datetime(2026, 9, 13, 18, 2, 52, tzinfo=backup.TZ)
    monkeypatch.setattr(backup, "now", lambda: began + timedelta(hours=1))
    spec = {"schema": recovery.SCHEMA, "source_operation": "a"*32, "source_run_id": "20260913T180252-" + "b"*12,
            "diagnostic_id": "c"*32, "capture_directory": "stdout-capture-test", "snapshot_id": "d"*64,
            "capture_helper_sha256": "e"*64, "hashes": {}}
    paths = recovery.evidence_paths(spool, spec)
    settings = {key: str(value) if isinstance(value, Path) else value for key,value in asdict(config).items()}
    rows = {"request": {"command":"run","supervisor_pid":100,"config":settings},
        "resources": {"schema":"ar-local-drive-resources-v1","result":"FAIL","group_clean":True,
            "workload_exit_code":1,"reason":"RuntimeError: workload_failed_or_left_descendants",
            "cgroup":"/sys/fs/cgroup/system.slice/ar-local-drive-backup.service"},
        "candidate":{"result":"FAIL","error":recovery.OUTPUT_FAILURE},
        "running":{"result":"RUNNING","run_id":spec["source_run_id"],"started_at":began.isoformat(),"request_ids":["f"*32]},
        "diagnostic_process":{"process_pid":300}}
    spec["hashes"]["request"] = put(paths["request"],rows["request"])
    started = {"schema":"ar-local-drive-command-diagnostic-v1","command":"backup","result":"STARTED",
        "operation_id":spec["source_operation"],"request_sha256":spec["hashes"]["request"],
        "supervisor_pid":100,"worker_pid":200}
    rows.update(diagnostic_started=started,diagnostic_result={**started,"result":"EXITED","exit_code":0,
        "reader_complete":True,"reader_error":False,"category":"NONE","process_pid":300})
    capture = {"purpose":"PRIVATE_STDOUT_EVIDENCE_NOT_BACKUP_ACCEPTANCE","operation":spec["source_operation"],
        "request_sha256":spec["hashes"]["request"],"supervisor_pid":100,"worker_pid":200,"restic_pid":300,
        "helper_sha256":spec["capture_helper_sha256"]}
    raw = spool/spec["capture_directory"]/"stdout.private.jsonl"; raw.parent.mkdir()
    summary = {"message_type":"summary","snapshot_id":spec["snapshot_id"],"data_added_packed":123}
    with raw.open("xb") as stream:
        record = json.dumps({"message_type":"status","current_files":["fixture"*1000]}).encode()+b"\n"
        for _ in range(2500): stream.write(record)
        stream.write(json.dumps(summary).encode()+b"\n")
    rows.update(capture_started=capture,capture_terminal={**capture,"result":"CAPTURE_COMPLETE","command_exit_code":0,
        "acceptance_verified":False,"captured_bytes":raw.stat().st_size,"stdout_sha256":backup.digest(raw),"summaries":[summary]})
    database=tmp_path/"archived.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE transport_control(id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO transport_control VALUES(1)")
    archive_path=(tmp_path/"gone-freeze"/"db.sqlite").as_posix()
    manifest={"schema":backup.SCHEMA,"content_sha256":"1"*64,"files":[{"logical_path":"data/state/control.sqlite",
        "backup_path":archive_path,"sha256":backup.digest(database),"size":database.stat().st_size,"sqlite":True}],"excluded":[]}
    spec["hashes"]["manifest"] = put(paths["manifest"],manifest)
    rows["failure"]={**rows["running"],"result":"FAIL","error":recovery.OUTPUT_FAILURE,
        "finished_at":(began+timedelta(minutes=30)).isoformat(),"manifest_path":"manifests/"+spec["source_run_id"]+".json",
        "manifest_sha256":spec["hashes"]["manifest"],"content_sha256":manifest["content_sha256"]}
    for key,value in rows.items(): spec["hashes"][key]=put(paths[key],value)
    descriptor=tmp_path/"recovery.json"; sha=put(descriptor,spec)
    bound=recovery.descriptor(descriptor,sha)
    return SimpleNamespace(config=config,spec=spec,paths=paths,rows=rows,descriptor=descriptor,sha=sha,bound=bound,
                           raw=raw,database=database,archive_path=archive_path,manifest=manifest,began=began)


def change(state, key, patch):
    state.rows[key].update(patch)
    state.spec["hashes"][key]=put(state.paths[key],state.rows[key])
    state.sha=put(state.descriptor,state.spec)
    state.bound=recovery.descriptor(state.descriptor,state.sha)


@pytest.mark.parametrize("key,patch", [("resources",{"result":"PASS"}),("resources",{"group_clean":False}),
    ("resources",{"reason":"RuntimeError: host_swap_out_activity"}),("resources",{"workload_exit_code":True}),
    ("candidate",{"error":"other failure"}),("candidate",{"result":"PASS"}),
    ("diagnostic_result",{"exit_code":1}),("diagnostic_result",{"exit_code":False}),
    ("diagnostic_result",{"reader_complete":False}),("diagnostic_started",{"operation_id":"9"*32}),
    ("capture_terminal",{"result":"CAPTURE_FAILED"}),("capture_terminal",{"command_exit_code":False}),
    ("capture_terminal",{"summaries":[]}),("capture_terminal",{"summaries":[None]}),
    ("failure",{"manifest_sha256":"9"*64}),("failure",{"run_id":"other"})])
def test_only_actual_bound_output_failure_and_complete_upload_are_eligible(original,key,patch):
    change(original,key,patch)
    with pytest.raises(ValueError): recovery.verified_source(original.config,original.bound)


def test_candidate_need_not_have_run_fields_when_shipping_worker_only_emitted_error(original):
    assert set(original.rows["candidate"])=={"result","error"}
    spec,paths,rows,began,summary=recovery.verified_source(original.config,original.bound)
    assert summary["snapshot_id"]==original.spec["snapshot_id"] and began==original.began


@pytest.mark.parametrize("kind",["raw","manifest","descriptor","old_live","other_repository"])
def test_source_or_snapshot_binding_drift_is_rejected(original,monkeypatch,kind):
    if kind=="raw":
        with original.raw.open("ab") as stream:stream.write(b"changed")
    elif kind=="manifest":original.paths["manifest"].write_text("{}")
    elif kind=="descriptor":
        with pytest.raises(ValueError):recovery.descriptor(original.descriptor,"0"*64)
        return
    elif kind=="old_live":monkeypatch.setattr("process_safety.process_alive",lambda _:True)
    else: original.rows["request"]["config"]["repository"]="different"
    if kind=="other_repository":change(original,"request",{})
    with pytest.raises(ValueError):recovery.verified_source(original.config,original.bound)


def client(original,monkeypatch,*,corrupt=False):
    calls=[]
    class Transport:
        def __init__(self,_config):pass
        def run(self,*args):
            calls.append(args[0])
            assert args[0] in {"check","restore","stats"},"recovery must never upload/init/unlock"
            if args[0]=="restore":
                target=Path(args[args.index("--target")+1])
                assert args[1]==original.spec["snapshot_id"] and "--verify" in args
                for name,source in [(original.archive_path,original.database),(original.paths["manifest"].as_posix(),original.paths["manifest"])]:
                    destination=target/backup.restore_relative(name); destination.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(source,destination)
                    if corrupt and name==original.archive_path:
                        with destination.open("ab") as stream:stream.write(b"wrong")
            return '{"total_size":123}' if args[0]=="stats" else ""
    monkeypatch.setattr(backup,"Restic",Transport)
    monkeypatch.setattr(backup,"freeze",lambda *a,**k:pytest.fail("must not freeze source"))
    monkeypatch.setattr(backup,"verify_direct_sources",lambda *a,**k:pytest.fail("must not reread current source"))
    return calls


def test_real_temporary_sqlite_and_manifest_restore_after_original_stage_is_gone(original,monkeypatch):
    calls=client(original,monkeypatch)
    before={key:path.read_bytes() for key,path in original.paths.items()}
    candidate=recovery.recover_snapshot(original.config,original.bound)
    assert calls==["check","restore","stats"]
    assert candidate["acquisition"]=="recovered_snapshot" and candidate["source_run_id"]==original.spec["source_run_id"]
    assert candidate["run_id"]!=candidate["source_run_id"] and candidate["backup_date"]=="2026-09-13"
    assert candidate["restore"]["result"]=="PASS" and candidate["restore"]["full"] is True
    assert candidate["restore"]["files_verified"]==2 and candidate["restore"]["databases_verified"]==1
    assert candidate["request_ids"]==[] and candidate["uploaded_bytes"]==0
    assert not original.config.data.exists() and not (original.config.spool/"latest-verified.json").exists()
    assert all(path.read_bytes()==before[key] for key,path in original.paths.items())
    assert not list(original.config.spool.glob("restore-*")) and not list(original.config.spool.glob("recovery-index-*"))


def test_corrupt_restored_bytes_never_create_candidate_or_acceptance(original,monkeypatch):
    client(original,monkeypatch,corrupt=True)
    with pytest.raises(ValueError,match="restored bytes differ"):
        recovery.recover_snapshot(original.config,original.bound)
    assert not (original.config.spool/"latest-verified.json").exists()


def test_recovery_on_later_day_retains_original_source_date(original,monkeypatch):
    client(original,monkeypatch)
    monkeypatch.setattr(backup,"now",lambda:original.began+timedelta(days=1))
    assert recovery.recover_snapshot(original.config,original.bound)["backup_date"]=="2026-09-13"


def test_fixed_unit_and_absent_pointer_admission_and_post_worker_guard(original,monkeypatch):
    monkeypatch.setattr(resources,"own_cgroup",lambda:Path("/other"))
    with pytest.raises(ValueError):recovery.recovery_admission(original.config,"run",original.bound)
    monkeypatch.setattr(resources,"own_cgroup",lambda:PurePosixPath("/sys/fs/cgroup/system.slice/ar-local-drive-backup.service"))
    assert recovery.recovery_admission(original.config,"run",original.bound)==original.bound
    client(original,monkeypatch)
    accepted=recovery.recover_snapshot(original.config,original.bound)
    recovery.recovery_acceptance(original.config,original.bound,accepted)
    put(original.config.spool/"latest-verified.json",{"existing":"must not overwrite"})
    with pytest.raises(backup.Blocked):recovery.recovery_acceptance(original.config,original.bound,accepted)
    with pytest.raises(backup.Blocked):recovery.recovery_admission(original.config,"run",original.bound)


def test_recovery_worker_route_never_enters_normal_freeze(monkeypatch, tmp_path):
    expected={"result":"PASS"}
    monkeypatch.setattr(recovery,"recover_snapshot",lambda cfg,arg:expected)
    monkeypatch.setattr(backup,"_run_locked",lambda *a,**k:pytest.fail("normal freeze path"))
    config = backup.Config(tmp_path, tmp_path, '', tmp_path / 'password', tmp_path / 'rclone', [])
    assert controller.worker_action(config,{"command":"run","recovery":{"fixture":True}}) is expected


@pytest.mark.parametrize('patch',[{'request_ids':['f'*32]},{'snapshot_id':'9'*64},{'backup_date':'2026-09-14'},
    {'restore':{'result':'PASS','full':False}},{'repository_check':'FAIL'},{'uploaded_bytes':1},
    {'action':'NO_WORK'},{'restore':{'result':'PASS','full':True,'snapshot_id':'9'*64}}])
def test_parent_rejects_candidate_with_wrong_recovery_or_queue_claim(original,monkeypatch,patch):
    monkeypatch.setattr(resources,'own_cgroup',lambda:PurePosixPath('/sys/fs/cgroup/system.slice/ar-local-drive-backup.service'))
    client(original,monkeypatch)
    candidate=recovery.recover_snapshot(original.config,original.bound)
    with pytest.raises(ValueError):recovery.recovery_acceptance(original.config,original.bound,{**candidate,**patch})


def test_descriptor_drift_after_admission_is_rejected_before_network(original,monkeypatch):
    monkeypatch.setattr(resources,'own_cgroup',lambda:PurePosixPath('/sys/fs/cgroup/system.slice/ar-local-drive-backup.service'))
    recovery.recovery_admission(original.config,'run',original.bound)
    original.descriptor.write_text('{}')
    monkeypatch.setattr(backup,'Restic',lambda *a:pytest.fail('must reject descriptor before network'))
    with pytest.raises(ValueError):recovery.recover_snapshot(original.config,original.bound)


@pytest.mark.parametrize('schema,seed_value,valid', [
    (recovery.SEEDED_SCHEMA, {'directory':'restore-abcdefgh','device':1,'inode':2}, True),
    (recovery.SCHEMA, {'directory':'restore-abcdefgh','device':1,'inode':2}, False),
    (recovery.SEEDED_SCHEMA, {'directory':'../outside','device':1,'inode':2}, False),
    (recovery.SEEDED_SCHEMA, None, False)])
def test_seed_descriptor_is_explicit_and_keeps_original_source_binding(original,schema,seed_value,valid):
    original.spec['schema']=schema
    if seed_value is not None: original.spec['seed']=seed_value
    sha=put(original.descriptor,original.spec)
    if valid:
        bound=recovery.descriptor(original.descriptor,sha)
        spec,paths,rows,began,summary=recovery.verified_source(original.config,bound)
        assert spec['seed']==seed_value and summary['snapshot_id']==original.spec['snapshot_id']
    else:
        with pytest.raises(ValueError):recovery.descriptor(original.descriptor,sha)


@pytest.mark.parametrize('tamper',[False,True])
def test_seed_plumbing_preserves_full_source_checks_and_parent_binding(original,monkeypatch,tamper):
    import pi_drive_backup_seed as seed
    original.spec.update(schema=recovery.SEEDED_SCHEMA, seed={'directory':'restore-abcdefgh','device':1,'inode':2})
    original.sha=put(original.descriptor,original.spec)
    original.bound=recovery.descriptor(original.descriptor,original.sha)
    before={key:path.read_bytes() for key,path in original.paths.items()}
    calls=client(original,monkeypatch)
    seen=[]
    def copy(spool,target,rows,identity,*,guard):
        assert identity==original.spec['seed'] and spool==original.config.spool
        assert len(list(rows))==2  # Includes the archived manifest.
        seen.append(target)
        return {'schema':seed.SCHEMA,'seed':identity,'read_only':True,'untrusted':True,
            'files_considered':2,'files_copied':0,'bytes_copied':0,'files_missing':2,'files_oversize':0,
            'copied_streams_sha256':hashlib.sha256().hexdigest()}
    monkeypatch.setattr(seed,'copy_seed',copy)
    monkeypatch.setattr(resources,'own_cgroup',lambda:PurePosixPath('/sys/fs/cgroup/system.slice/ar-local-drive-backup.service'))
    candidate=recovery.recover_snapshot(original.config,original.bound)
    assert candidate['restore']['files_verified']==2 and candidate['restore']['databases_verified']==1
    assert calls==['check','restore','stats'] and candidate['request_ids']==[]
    assert candidate['backup_date']=='2026-09-13' and not any(path.exists() for path in seen)
    if tamper:
        candidate['restore']['seed']['seed']={'directory':'restore-wrongone','device':1,'inode':2}
        with pytest.raises(ValueError):recovery.recovery_acceptance(original.config,original.bound,candidate)
    else:recovery.recovery_acceptance(original.config,original.bound,candidate)
    assert all(path.read_bytes()==before[key] for key,path in original.paths.items())
    assert not (original.config.spool/'latest-verified.json').exists()


def test_descriptor_drift_after_worker_is_rejected_before_acceptance(original,monkeypatch):
    monkeypatch.setattr(resources,'own_cgroup',lambda:PurePosixPath('/sys/fs/cgroup/system.slice/ar-local-drive-backup.service'))
    client(original,monkeypatch)
    accepted=recovery.recover_snapshot(original.config,original.bound)
    original.descriptor.write_text('{}')
    with pytest.raises(ValueError):recovery.recovery_acceptance(original.config,original.bound,accepted)


@pytest.mark.parametrize('argv',[['run','--recover-from','missing'],['run','--recover-sha256','a'*64],
    ['init','--recover-from','missing','--recover-sha256','a'*64],
    ['run','--force','--recover-from','missing','--recover-sha256','a'*64]])
def test_cli_requires_explicit_paired_recovery_arguments(argv):
    with pytest.raises(SystemExit) as error:backup.main(argv)
    assert error.value.code==2


@pytest.mark.parametrize('resource_failure',[False,True])
def test_parent_resource_acceptance_keeps_all_queue_requests(original,monkeypatch,resource_failure):
    client(original,monkeypatch)
    monkeypatch.setattr(backup,'readiness',lambda _: {'result':'PASS'})
    monkeypatch.setattr(resources,'own_cgroup',lambda:PurePosixPath('/sys/fs/cgroup/system.slice/ar-local-drive-backup.service'))
    queued=backup.request_backup('transport test',spool=original.config.spool)
    queue_bytes=queued.read_bytes()
    def completed_worker(config,command,*,operation,recovery,**_):
        assert command=='run' and recovery==original.bound
        candidate=controller.worker_action(config,{'command':command,'recovery':recovery})
        host={'available_bytes':6*1024**3,'swap_in_pages':0,'swap_out_pages':0,'page_size_bytes':16384,'psi_avg10':None}
        proof={'schema':resources.SCHEMA,'result':'FAIL' if resource_failure else 'PASS','mode':'sampled_cgroup_rss',
            'limits':asdict(resources.Limits()),'samples':2,'peak_rss_bytes':1000,'minimum_available_bytes':host['available_bytes'],
            'maximum_sample_gap_seconds':.1,'group_clean':True,'workload_exit_code':0,'page_size_bytes':16384,
            'cold_swap_in_bytes':0,'peak_workload_swap_bytes':0,'elapsed_seconds':1,'baseline':host,'last_host_sample':host}
        put(operation/'candidate.json',candidate)
        put(operation/'request.json',{'command':command,'recovery':recovery,'supervisor_pid':1000})
        put(operation/'resources.json',proof)
        return candidate
    monkeypatch.setattr(controller,'execute_worker',completed_worker)
    if resource_failure:
        with pytest.raises(ValueError,match='resource receipt'):
            controller.run_protected(original.config,recovery=original.bound)
        assert not (original.config.spool/'latest-verified.json').exists()
        assert not list((original.config.spool/'receipts').glob('*.PASS.json'))
    else:
        accepted=controller.run_protected(original.config,recovery=original.bound)
        assert backup._load(original.config.spool/'latest-verified.json')==accepted
        assert accepted['resource_evidence']['path']!='resource-runs/'+original.spec['source_operation']
        assert len(list((original.config.spool/'receipts').glob('*.PASS.json')))==1
    assert queued.read_bytes()==queue_bytes
    assert original.paths['failure'].is_file()
