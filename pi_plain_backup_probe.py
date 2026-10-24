"""Unprivileged coupled commissioning probe: no freeze, archive or Drive calls."""
import argparse
import json
from pathlib import Path
import stat


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data-root',type=Path,required=True)
    p.add_argument('--operation',type=Path,required=True)
    p.add_argument('--rclone-config',type=Path,required=True)
    p.add_argument('--remote',required=True)
    p.add_argument('--drive-root-folder-id',required=True)
    p.add_argument('--attestation-fd',type=int,required=True)
    p.add_argument('--deadline',required=True)
    p.add_argument('--control-file',action='append',default=[])
    args=p.parse_args(argv)
    from pi_plain_backup_attestation import inherited_from_attestation_fd,protected_file
    lease=inherited_from_attestation_fd(args.attestation_fd,deadline=args.deadline,
        remote=args.remote,drive_root_folder_id=args.drive_root_folder_id,
        data_root=args.data_root,operation=args.operation)
    lease.verify(args.data_root)
    # Exercise actual dependency imports only after UID/caps/NNP/namespace proof.
    import pi_plain_drive_backup
    import pi_plain_backup_transport
    import zstandard
    from ar_local_backup_scope import build_data_scope
    from pi_drive_backup_source import validate_retained_export_stage
    protected_file(args.rclone_config)
    info=args.rclone_config.stat()
    if stat.S_IMODE(info.st_mode)!=0o440 or args.operation.exists():
        raise RuntimeError('probe config mode or NEW operation contract differs')
    scope=build_data_scope(args.data_root,include_retained_export_stage=True).manifest()
    retained=validate_retained_export_stage(args.data_root,lambda:lease.verify(args.data_root))
    if build_data_scope(args.data_root,include_retained_export_stage=True).manifest()!=scope:
        raise ValueError('probe source namespace scope changed')
    lease.verify(args.data_root)
    print(json.dumps({'schema':'ar-local-plain-backup-coupled-probe-v1',
        'result':'PROBE_PASS','scope':'NO_BACKUP_NO_DRIVE_WRITES','attestation_verified':True,
        'producer_dependencies_imported':True,'new_operation':True,'data_scope':scope,
        'retained_stage_validation':retained,
        'zstandard_version':zstandard.__version__},sort_keys=True))
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'result':'PROBE_FAIL','error_type':type(error).__name__}))
        raise SystemExit(2)
