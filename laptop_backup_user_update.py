"""Read-only verification of an ordinary-user receiver-only replacement."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import laptop_backup_user_session as user
from laptop_backup_runtime_lineage import authenticated_runtime_pairs, authenticate_pointer_descendant
from laptop_backup_scheduled_lineage import _pointer_identity


def verify_tool_contract(path: Path, sha: str, new_path: Path, new_digest: str) -> dict:
    import laptop_backup_git_dependency as dependency
    user.unlinked(path)
    if user.digest(path) != sha:
        raise ValueError('tool contract changed')
    value = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=user.strict_pairs)
    fields = {'archive', 'package_sha256', 'package_root', 'ssh_archive', 'ssh_sha256', 'ssh_root'}
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError('tool contract fields are not exact')
    return dependency.verify_current(new_path, new_digest, Path(value['archive']),
                                     value['package_sha256'], Path(value['package_root']),
                                     Path(value['ssh_archive']), value['ssh_sha256'], Path(value['ssh_root']))


def verify_tool_identity(old: dict, new: dict) -> None:
    tool_fields = {'ssh_path', 'ssh_sha256', 'scp_path', 'scp_sha256', 'ssh_null_device'}
    before = {k: v for k, v in old['transport'].items() if k not in tool_fields}
    after = {k: v for k, v in new['transport'].items() if k not in tool_fields}
    if before != after:
        raise ValueError('tool replacement changed SSH identity or host-key contract')


def verify(old_path: Path, old_digest: str, new_path: Path, new_digest: str,
           tool_contract: Path | None = None, tool_contract_sha256: str | None = None) -> dict:
    new = user.load_config(new_path, new_digest)
    if bool(tool_contract) != bool(tool_contract_sha256):
        raise ValueError('both tool contract path and hash are required')
    tools = verify_tool_contract(tool_contract, tool_contract_sha256, new_path, new_digest) if tool_contract else None
    user.verify_release(new)
    user.unlinked(old_path)
    if user.digest(old_path) != old_digest:
        raise ValueError('previous configuration changed')
    old = json.loads(old_path.read_text(encoding='utf-8'), object_pairs_hook=user.strict_pairs)
    if not isinstance(old, dict) or not user.KEYS.issubset(old):
        raise ValueError('previous configuration is invalid')
    user.unlinked(Path(old['receiver']))
    # A dependency transition authenticates the complete private package before
    # using it to read either tree. Never execute the drifted predecessor Git.
    user.verify_release(dict(old, git_path=new['git_path']) if tools else old)
    if old_path != Path(old['receiver']).parent / user.CONFIG_NAME or old_path == new_path:
        raise ValueError('receiver replacement requires separate immutable configurations')
    changed = {'receiver', 'candidate_sha', 'previous_runtime', 'lan_fallback_ipv4'}
    if tools:
        verify_tool_identity(old, new)
        changed |= {'git_path', 'git_sha256', 'transport'}
    if {k: v for k, v in old.items() if k not in changed} != {k: v for k, v in new.items() if k not in changed}:
        raise ValueError('receiver-only update changed runtime, identity, paths or transport')
    target = user.unlinked(Path(new['target']))
    pointer_path = user.unlinked(target / 'catalog/latest-scheduled.json')
    raw_pointer = pointer_path.read_bytes()
    # Strict decoding rejects duplicate fields; the shared pointer validator also
    # checks the result against the hash-authenticated referenced record.
    json.loads(raw_pointer, object_pairs_hook=user.strict_pairs)
    pointer = _pointer_identity(target, raw_pointer)
    previous = new.get('previous_runtime')
    expected_previous = {'production_sha': old['protected_sha'], 'receiver_sha': old['candidate_sha'],
                         'record_sha256': pointer['record_sha256']}
    if previous != expected_previous:
        raise ValueError('new receiver must pin the latest successful old receiver execution')
    expected = {'operator': new['operator_sid'], 'plan_git_commit': '9094a8e115958fcaf2cb36525736bd5e297e6b04',
                'protected_code_sha': new['protected_sha'], 'candidate_code_sha': new['candidate_sha'],
                'runtime_predecessor': previous}
    pairs = authenticated_runtime_pairs(target, previous, expected)
    authenticate_pointer_descendant(target, pointer, expected)
    return {'result': 'PASS', 'read_only': True, 'previous_runtime': previous,
            'authenticated_historical_pairs': sorted(pairs), 'config_sha256': new_digest,
            **({'tools': tools} if tools else {})}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-config', type=Path, required=True)
    parser.add_argument('--old-sha256', required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--config-sha256', required=True)
    parser.add_argument('--tool-contract', type=Path)
    parser.add_argument('--tool-contract-sha256')
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.old_config, args.old_sha256, args.config, args.config_sha256,
                                args.tool_contract, args.tool_contract_sha256)))
        return 0
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
