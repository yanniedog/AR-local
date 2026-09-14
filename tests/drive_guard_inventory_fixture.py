"""Protected-metadata emulation for private Windows/Linux protocol tests.

The launcher/control bytes below are deliberately non-executable placeholders.
This fixture tests proof validation, not deployment or operator attestation.
"""
import hashlib
import json
import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pi_drive_backup_hold_activate as activation


def installed_fixture(tmp_path, monkeypatch):
    root = tmp_path / 'protected'
    root.mkdir()
    system, bundle = root / 'system', root / 'bundle'
    system.mkdir()
    bundle.mkdir()
    spool = tmp_path / 'spool'
    spool.mkdir()
    source = Path(activation.__file__).parent
    names = ['pi_drive_backup_hold.py', 'pi_drive_backup.py',
             'pi_drive_backup_controller.py', 'ar_local_operation_lock.py']
    for name in names:
        (bundle / name).write_bytes((source / name).read_bytes())
    helper, launcher, control = root / 'activate.py', root / 'launcher.py', root / 'dispatch.service'
    helper.write_bytes(Path(activation.__file__).read_bytes())
    launcher.write_bytes(b'Non-executable isolated-launch protocol fixture; no deployment attestation.\n')
    control.write_bytes(b'Non-executable dispatcher/control protocol fixture; no runtime authority.\n')
    marker = system / 'drive-write-hold.json'
    monkeypatch.setattr(activation, 'SYSTEM_HOLD', marker)
    monkeypatch.setattr(activation, 'TRUSTED_HELPER', helper)
    proof_path = system / activation.GUARD_INVENTORY_NAME
    real_lstat = os.lstat
    faults = {}
    def metadata(path, *args, **kwargs):
        info = real_lstat(path, *args, **kwargs)
        path = Path(path)
        permissions = 0o755 if stat.S_ISDIR(info.st_mode) else 0o444
        if path in (helper, launcher):
            permissions = 0o555
        values = {name: getattr(info, name) for name in ('st_dev', 'st_ino', 'st_size',
                  'st_mtime_ns', 'st_ctime_ns', 'st_nlink')}
        values.update(st_uid=0, st_gid=0, st_mode=stat.S_IFMT(info.st_mode) | permissions)
        values.update(faults.get(path, {}))
        return SimpleNamespace(**values)
    monkeypatch.setattr(activation.os, 'lstat', metadata)
    def identity(path, label):
        body = path.read_bytes()
        return {'path': label, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
    proof = {'schema_version': 1, 'protocol': activation.GUARD_PROTOCOL,
             'approved_commit': '1' * 40, 'review_receipt_sha256': '2' * 64,
             'attestation': {'all_authorized_dispatch_paths_enumerated': True,
                             'unguarded_dispatch_paths_disabled': True,
                             'isolated_launch_and_dependency_closure_reviewed': True,
                             'all_backend_and_acceptance_work_uses_inventoried_spool_lock': True},
             'spools': [str(spool)], 'bundle': {'root': str(bundle),
                 'files': [identity(bundle / name, name) for name in names]},
             'artifacts': [{'role': role, **identity(path, str(path))} for role, path in
                           [('helper', helper), ('launcher', launcher), ('dispatch_control', control)]],
             'dispatchers': [{'id': 'protocol-fixture', 'launcher': str(launcher),
                 'controls': [str(control)], 'spools': [str(spool)],
                 'isolation': 'REVIEWED_NO_MUTABLE_IMPORT_OR_STARTUP_PATH'}]}
    def write():
        proof_path.write_text(json.dumps(proof), encoding='utf-8')
    write()
    return SimpleNamespace(proof=proof, path=proof_path, write=write, marker=marker,
                           spool=spool, bundle=bundle, helper=helper, faults=faults)
