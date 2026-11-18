"""Optional prepared inputs must remain inside existing full-backup state scope."""
from pathlib import Path

from app_payload_product_evidence_contract import require
from cdr_product_evidence_source import safe_path


def supported_location(state, path):
    state, path = Path(state).absolute(), Path(path).absolute()
    require(state.is_dir() and state.resolve() == state, 'canonical existing state root required')
    require(path != state and path.is_relative_to(state),
            'optional prepared input must be below the supported state backup root')
    relative = path.relative_to(state).as_posix()
    from pi_drive_backup_source import excluded
    require(not excluded(Path('state') / relative / 'artifact.json'),
            'optional prepared input directory is excluded from full backup')
    require(safe_path(state,relative) == path and path.is_dir() and path.resolve() == path,
            'optional prepared input location is not a canonical directory')
    return path


def delivery_locations(state, ready):
    state = Path(state).absolute()
    return {key:supported_location(state,safe_path(state.parent,value)) for key,value in (
        ('base',ready['base']['directory']),('evidence',ready['evidence_root']),('capability',ready['capability_root']))}
