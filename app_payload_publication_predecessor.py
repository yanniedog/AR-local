"""Recover only our exact already-selected child after interrupted alias work."""
from pathlib import Path

from app_payload_product_evidence_contract import canonical, decode, digest, require
from app_payload_product_evidence_delivery_check import read_stable


def verify_completed_predecessor(archive, manifest, head, expected):
    from app_payload_publication_assets import verify_publication_root
    from app_payload_revisions_state import validate_index
    require(manifest.get('payload_revision', {}).get('parent_revision') == expected.get('revision'),
            'selected evidence child has another predecessor')
    verify_publication_root(archive, manifest)
    root = Path(archive)/'promotions'
    require(root.is_dir() and not root.is_symlink(), 'retained promotion predecessor evidence required')
    count = 0
    for directory in root.iterdir():
        count += 1
        require(count <= 1024 and directory.is_dir() and not directory.is_symlink(), 'unsafe promotion inventory')
        # An intent/new-index without a committed receipt is recoverable only
        # because independent remote readback already proved this exact head.
        index_raw, _ = read_stable(directory/'dates-index.json',8*1024*1024)
        index = decode(index_raw); validate_index(index,repo=manifest['repo'])
        require(digest(index_raw) == directory.name, 'retained promotion index digest differs')
        if canonical(index.get('revision_heads',{}).get(manifest['run_date'])) != canonical(head): continue
        intent = decode(read_stable(directory/'promotion-intent.json',8*1024*1024)[0])
        prior_raw, _ = read_stable(directory/'predecessor'/'dates-index.json',8*1024*1024)
        prior = decode(prior_raw); validate_index(prior,repo=manifest['repo'])
        require(intent.get('index_sha256') == digest(index_raw)
                and intent.get('predecessor_index_sha256') == digest(prior_raw), 'retained predecessor digest differs')
        if canonical(prior.get('revision_heads',{}).get(manifest['run_date'])) == canonical(expected): return
    raise ValueError('exact expected predecessor is not retained for selected evidence child')
