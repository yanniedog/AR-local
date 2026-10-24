"""Bounded plaintext recovery packs: full cloud readback before catalog acceptance.

Call run() inside the approved resource supervisor and exclusive host admission.
The mandatory guard callback owns deadlines, quiet window, free-space and
resource boundaries. Root VM controls, system images and schedules are separate.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import tempfile
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
import shutil
import time as clock

from ar_local_backup_scope import build_data_scope
from pi_drive_backup_manifest import close_manifest, encoded
from pi_drive_backup_read import discard_created_cache
from pi_drive_backup_source import canonical_directory, digest, freeze, validate_layout, verify_direct_sources
from pi_plain_backup_packs import SCHEMA, PackIndex, build_pack, verify_pack, write_manifest


def write_json(path, value):
    with path.open('xb') as output:
        output.write(encoded(value) + b'\n')
        discard_created_cache(output)


def fetched_json(transport, remote, path):
    if not transport.download(remote, path):
        return None
    if path.stat().st_size > 16384:
        raise ValueError('oversized cloud pack descriptor')
    return json.loads(path.read_text(encoding='utf-8'))


def verify_cloud(transport, prefix, descriptor, index, group, directory, guard):
    archive = directory / 'cloud.tar.zst'
    if not transport.download(prefix + '/archive.tar.zst', archive):
        raise ValueError('cloud descriptor references a missing recovery archive')
    scratch = directory / 'restore'
    scratch.mkdir(mode=0o700)
    result = verify_pack(archive, descriptor, index, group, scratch, guard)
    archive.unlink()  # Only our own downloaded temporary artifact.
    return result


def ensure_pack(transport, index, group, directory, guard):
    identity = index.identity(group, guard)
    prefix = 'packs/' + identity['pack_id']
    descriptor = fetched_json(transport, prefix + '/descriptor.json', directory / 'existing.json')
    reused = descriptor is not None
    proof = None
    if descriptor is None:
        previous = directory / 'previous.tar.zst'
        if transport.download(prefix + '/archive.tar.zst', previous):
            manifest_path = directory / 'manifest.json'
            write_manifest(manifest_path, index, group, identity, guard)
            descriptor = dict(identity, schema=SCHEMA, compression='zstd-lossless-no-encryption',
                archive_sha256=digest(previous, guard), archive_bytes=previous.stat().st_size,
                manifest_sha256=digest(manifest_path, guard), manifest_bytes=manifest_path.stat().st_size)
            scratch = directory / 'restore'; scratch.mkdir(mode=0o700)
            proof = verify_pack(previous, descriptor, index, group, scratch, guard)
            previous.unlink()
        else:
            descriptor = build_pack(index, group, directory, guard)
            # Ignore-existing never replaces a concurrent or interrupted object.
            # A complete readback decides whether its actual content is valid.
            transport.upload(prefix + '/archive.tar.zst', directory / 'archive.tar.zst')
    if proof is None:
        proof = verify_cloud(transport, prefix, descriptor, index, group, directory, guard)
    if not reused:
        description = directory / 'descriptor.json'
        write_json(description, descriptor)
        transport.upload(prefix + '/descriptor.json', description)
        remote = fetched_json(transport, prefix + '/descriptor.json', directory / 'descriptor-readback.json')
        if remote != descriptor:
            raise ValueError('cloud descriptor readback differs')
        (directory / 'archive.tar.zst').unlink(missing_ok=True)
    return dict(descriptor=descriptor, proof=proof, reused=reused)


def run(data: Path, operation: Path, transport, *, controls, inherited_lease, guard):
    """Create a candidate receipt; independent whole-worker resource proof remains required.

    Existing encrypted snapshots and the global Restic hold are untouched. The
    operator's explicit plaintext-backup authorization is a separate bounded
    pipeline; no routine uploader is enabled or acknowledged by this function.
    """
    data, operation = Path(data), Path(operation)
    canonical_directory(data)
    if not callable(guard):
        raise ValueError('bounded operation guard required')
    guard()
    if inherited_lease is None:
        raise ValueError('plain cloud backup requires explicit inherited host admission')
    if operation.exists() or operation.is_symlink() or operation != operation.resolve():
        raise ValueError('new canonical private operation directory required')
    if data == operation or data in operation.parents or operation in data.parents:
        raise ValueError('operation must be outside authoritative data')
    # Validation accepts a separate spool without creating it.
    validate_layout(data, operation, controls)
    operation.mkdir(mode=0o700)
    frozen = operation / 'freeze'
    manifest = index = None
    try:
        # Hold proof stays valid throughout the entire backup, not only freeze.
        with inherited_lease.hold(data):
            manifest = freeze(data, frozen, controls=controls, guard=guard, inherited_lease=inherited_lease)
            index = PackIndex(operation / 'packs.sqlite', manifest['files'], guard, data=data)
            verify_direct_sources(manifest, guard)
            catalog = operation / 'catalog.json'
            verified_files = verified_databases = verified_packs = 0
            with catalog.open('xb') as output:
                output.write(b'{"schema":"ar-local-plain-catalog-v1","scope":' + encoded(manifest['scope']) + b',"packs":[')
                for number, group in enumerate(index.groups()):
                    guard()
                    with tempfile.TemporaryDirectory(prefix='pack-', dir=operation) as temp:
                        result = ensure_pack(transport, index, group, Path(temp), guard)
                    verified_files += result['proof']['files_verified']
                    verified_databases += result['proof']['databases_verified']
                    verified_packs += 1
                    index.registered(group, result['descriptor']['pack_id'])
                    if number:
                        output.write(b',')
                    output.write(encoded({'descriptor': result['descriptor'], 'verification': result['proof']}))
                file_index = index.file_index(operation / 'file-index.jsonl', data, guard)
                transport.upload(file_index['path'], operation / 'file-index.jsonl')
                index_readback = operation / 'file-index-readback.jsonl'
                if not transport.download(file_index['path'], index_readback) or digest(index_readback, guard) != file_index['sha256']:
                    raise ValueError('complete cloud file-index readback differs')
                output.write(b'],"file_index":' + encoded(file_index) + b',"excluded_paths":[')
                excluded_digest = hashlib.sha256()
                excluded_count = 0
                for excluded_count, omitted in enumerate(manifest['excluded'], 1):
                    guard()
                    if excluded_count > 1:
                        output.write(b',')
                    value = encoded(omitted)
                    output.write(value)
                    excluded_digest.update(value + b'\n')
                output.write(b'],"excluded_count":' + encoded(excluded_count)
                    + b',"excluded_sha256":' + encoded(excluded_digest.hexdigest()) + b'}\n')
                discard_created_cache(output)
            guard()
            if verified_files != len(manifest['files']):
                raise ValueError('verified pack file total differs from full source manifest')
            verify_direct_sources(manifest, guard)
            index.verify_directories(guard)
            if build_data_scope(data).manifest() != manifest['scope']:
                raise ValueError('source namespace scope changed during backup')
            catalog_id = digest(catalog, guard)
            remote = 'catalogs/' + catalog_id + '.json'
            transport.upload(remote, catalog)
            readback = operation / 'catalog-readback.json'
            if not transport.download(remote, readback) or digest(readback, guard) != catalog_id:
                raise ValueError('complete cloud catalog readback differs')
            verify_direct_sources(manifest, guard)
            index.verify_directories(guard)
            receipt = dict(schema='ar-local-plain-recovery-candidate-v1', result='PASS',
                scope='archive-transport-and-full-restore', resource_acceptance='EXTERNAL_REQUIRED',
                catalog_sha256=catalog_id, catalog_path=remote,
                file_index=file_index,
                files_verified=len(manifest['files']), encrypted=False,
                packs_verified=verified_packs, databases_verified=verified_databases,
                excluded_paths=excluded_count, excluded_sha256=excluded_digest.hexdigest(),
                system_image='SEPARATE_REQUIRED', original_restic='PRESERVED')
            write_json(operation / 'candidate.json', receipt)
            return receipt
    finally:
        if index:
            index.close()
        if manifest:
            close_manifest(manifest)


def main(argv=None):
    import argparse
    from pi_plain_backup_attestation import inherited_from_attestation_fd
    from pi_plain_backup_transport import Rclone
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--operation', type=Path, required=True)
    parser.add_argument('--rclone-config', type=Path, required=True)
    parser.add_argument('--remote', required=True)
    parser.add_argument('--drive-root-folder-id', required=True)
    parser.add_argument('--attestation-fd', type=int, required=True)
    parser.add_argument('--deadline', required=True)
    parser.add_argument('--control-file', action='append', type=Path, default=[])
    args = parser.parse_args(argv)
    deadline = datetime.fromisoformat(args.deadline.replace('Z', '+00:00'))
    remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
    if not 0 < remaining <= 21600:
        raise ValueError('future deadline within six hours required')
    monotonic_deadline = clock.monotonic() + remaining
    lease = inherited_from_attestation_fd(args.attestation_fd, deadline=args.deadline,
        remote=args.remote, drive_root_folder_id=args.drive_root_folder_id,
        data_root=args.data_root, operation=args.operation)
    def guard():
        current = datetime.now(timezone.utc)
        local = current.astimezone(ZoneInfo('Australia/Hobart')).time().replace(tzinfo=None)
        if clock.monotonic() >= monotonic_deadline or current >= deadline:
            raise RuntimeError('bounded backup deadline reached')
        if local >= time(0, 25) and local < time(3, 30):
            raise RuntimeError('backup quiet-window cleanup margin reached')
        disk = args.operation if args.operation.exists() else args.operation.parent
        if shutil.disk_usage(disk).free < 2 * 1024**3:
            raise RuntimeError('private backup workspace free-space floor reached')
    guard()
    lease.verify(args.data_root)
    transport = Rclone(args.rclone_config, args.remote, args.drive_root_folder_id, guard)
    result = run(args.data_root, args.operation, transport, controls=args.control_file,
        inherited_lease=lease, guard=guard)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        # No provider stderr, raw payloads, credentials, tokens or config bytes.
        print(json.dumps({'result': 'FAIL', 'error_type': type(error).__name__}))
        raise SystemExit(1)
